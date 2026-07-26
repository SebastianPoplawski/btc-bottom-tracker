"""
app.py — krok 04 (UI Streamlit, punkt wejścia)
==============================================
TYLKO warstwa prezentacji. Spina warstwy:
    config (demo/live) + odczyty -> composite.evaluate / dca.compute_dca_state -> UI.
Cała logika sygnałów zostaje w src/logic/* — tu jej nie przeliczamy.

Uruchomienie:  streamlit run app.py
Tryb:          APP_MODE=demo (seed, bez chmury)  /  APP_MODE=live (BigQuery + Sheets)
"""

from __future__ import annotations

import os
import sys
from datetime import date
from typing import Any, Optional

import streamlit as st

# --- ścieżki importu (spójnie z run_ingest.py / tests) --------------------- #
_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (
    os.path.join(_ROOT, "src"),
    os.path.join(_ROOT, "src", "logic"),
    os.path.join(_ROOT, "src", "ui"),
    os.path.join(_ROOT, "src", "ingestion"),
    os.path.join(_ROOT, "src", "warehouse"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config                      # src/config.py
import composite                   # src/logic/composite.py
import dca                         # src/logic/dca.py
import exit_plan                   # src/logic/exit_plan.py (krok 17)
import components as ui            # src/ui/components.py
import text_pl as T               # src/ui/text_pl.py


# --------------------------------------------------------------------------- #
# Ładowanie danych (cache). Zwracamy wyłącznie struktury picklowalne.
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=900, show_spinner=False)
def _load_demo() -> dict:
    import mock
    seed = mock.load_seed()
    as_of = mock.snapshot_date(seed)
    msg = (f"Tryb DEMO — snapshot {as_of.isoformat()}." if as_of
           else "Tryb DEMO — dane seed.")
    return {
        "config": mock.seed_config(seed),
        "reading": mock.latest_reading(seed),
        "history_df": mock.readings_df(seed),
        "dca_df": mock.dca_df(seed),
        "sell_df": mock.sell_df(seed),       # krok 17: plan transz sprzedaży
        "freshness_msg": msg,
        "as_of": as_of,
        "warnings": [],
    }


@st.cache_data(ttl=900, show_spinner=False)
def _load_live() -> dict:
    """Live: Sheets (config/dca/odczyty ręczne + świeżość) + auto-fetch (Binance, F&G)
    + historia z BigQuery. Każde źródło osobno opakowane — błąd jednego nie wywala apki."""
    import sheets
    import price_binance
    import fear_greed_api
    warnings: list[str] = []

    # 1) Arkusz: config, dca, odczyty ręczne, świeżość
    bundle = sheets.load_all()
    warnings += bundle.validation.warnings + bundle.validation.errors
    cfg = bundle.config.to_dict("records") if not bundle.config.empty else []
    dca_df = bundle.dca

    manual_row = sheets.latest_reading(bundle.readings)
    reading: dict[str, Any] = {}
    if manual_row is not None:
        reading = dict(sheets.build_reading_values(manual_row))
        reading["reading_date"] = manual_row.get("reading_date")

    # 2) Auto-fetch — nadpisuje price/ma/fng/makro gdy dostępne
    pdata = price_binance.get_price_and_ma()
    warnings += pdata.warnings
    if pdata.price_usd is not None:
        reading["price_usd"] = pdata.price_usd
    if pdata.ma_200w is not None:
        reading["ma_200w"] = pdata.ma_200w
    if pdata.ma_111d is not None:            # krok 17: Pi Cycle
        reading["ma_111d"] = pdata.ma_111d
    if pdata.ma_350d is not None:
        reading["ma_350d"] = pdata.ma_350d
    fg = fear_greed_api.fetch_fear_greed()
    warnings += fg.warnings
    if fg.value is not None:
        reading["fear_greed"] = fg.value
    try:                                      # krok 17: makro FRED (opcjonalne)
        import fred_api
        macro = fred_api.get_macro()
        warnings += macro.warnings
        for key in ("fed_funds_rate", "fed_funds_delta_3m",
                    "dxy_proxy", "dxy_delta_3m", "m2_yoy"):
            val = getattr(macro, key)
            if val is not None:
                reading[key] = val
    except Exception as exc:
        warnings.append(f"Makro FRED niedostępne ({exc}).")

    # 3) Historia z BigQuery (pod wykresy) — opcjonalna
    try:
        import bigquery_client as wh
        history_df = wh.read_history(days=365)
    except Exception as exc:  # BQ niedostępne / brak poświadczeń
        import pandas as pd
        history_df = pd.DataFrame()
        warnings.append(f"Historia z BigQuery niedostępna ({exc}).")

    return {
        "config": cfg,
        "reading": reading,
        "history_df": history_df,
        "dca_df": dca_df,
        "sell_df": bundle.sell,               # krok 17: plan transz sprzedaży
        "freshness_msg": bundle.freshness.message,
        "as_of": bundle.freshness.latest_date,
        "warnings": warnings,
    }


def _reading_price(reading: Any) -> Optional[float]:
    """Cena z odczytu (dict/Series), odporna na None/NaN — bez sięgania do innych modułów."""
    try:
        val = reading.get("price_usd") if hasattr(reading, "get") else reading["price_usd"]
    except (KeyError, TypeError):
        return None
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # odrzuć NaN


def _load_data(settings) -> dict:
    if settings.is_demo:
        return _load_demo()
    try:
        return _load_live()
    except Exception as exc:
        st.error(f"Tryb LIVE niedostępny ({exc}). Przełącz APP_MODE=demo lub sprawdź sekrety.")
        st.stop()


# --------------------------------------------------------------------------- #
# Strona
# --------------------------------------------------------------------------- #
def main() -> None:
    st.set_page_config(page_title=T.APP_TITLE, page_icon="₿", layout="wide")
    ui.inject_css()

    settings = config.load_settings()
    data = _load_data(settings)

    ui.page_header(settings.mode, data["freshness_msg"], data["as_of"])

    # --- Composite (cała logika w composite.evaluate_side) ---
    # graded_fng=True: F&G wnosi wkład STOPNIOWY do wyniku ważonego (headline gauge);
    # kierunek (fear/greed) rozpoznawany po operatorze wiersza. Twardy count bez zmian.
    # krok 17: TRZY strony — dno (framework, jak dotąd), szczyt (framework, warstwa
    # sprzedaży) i makro (OSOBNY licznik risk-off, poza frameworkiem).
    result = composite.evaluate_side(
        data["config"], data["reading"], composite.SIDE_BOTTOM, graded_fng=True)
    top_result = composite.evaluate_side(
        data["config"], data["reading"], composite.SIDE_TOP, graded_fng=True)
    macro_result = composite.evaluate_side(
        data["config"], data["reading"], composite.SIDE_MACRO)

    ui.dual_composite_summary(result, top_result)
    st.divider()
    ui.indicator_grid(result)                       # karty dna (jak dotąd)
    st.divider()
    ui.indicator_grid(top_result, title=T.SECTION_TOP,
                      threshold_prefix="próg szczytu:",
                      help_map=T.INDICATOR_HELP_TOP)  # karty szczytu (krok 17)
    st.divider()
    ui.macro_panel(macro_result)                    # kontekst makro (krok 17)
    st.divider()

    # --- Jedna cena dla OBU planów (DCA + wyjście); demo bez ceny, live pre-fill ---
    auto_price = _reading_price(data["reading"])  # surowa cena z odczytu
    default_price = auto_price if auto_price is not None else 0.0
    price_in = st.number_input(
        "Cena BTC (USD) do oceny progów planów (DCA i wyjścia) — 0 = nieznana",
        min_value=0.0, value=default_price, step=500.0,
        help="W trybie live pole jest wstępnie wypełnione ceną z auto-fetch.",
    )
    current_price = price_in if price_in > 0 else None

    dca_state = dca.compute_dca_state(
        data["dca_df"], current_price=current_price, count_met=result.count_met,
    )
    ui.dca_panel(dca_state)
    st.divider()

    # --- Plan transz sprzedaży (krok 17) — bramka na sygnałach SZCZYTU ---
    exit_state = exit_plan.compute_exit_state(
        data.get("sell_df"), current_price=current_price,
        top_count_met=top_result.count_met,
    )
    ui.exit_panel(exit_state)
    st.divider()

    # --- Wykresy ---
    ui.history_charts(data["history_df"])

    # --- Uwagi + disclaimer ---
    ui.warnings_block(
        list(result.warnings) + list(top_result.warnings) + list(macro_result.warnings)
        + list(data["warnings"]) + list(dca_state.warnings) + list(exit_state.warnings)
    )
    ui.footer(composite.DISCLAIMER)


main()
