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

    # 2) Auto-fetch — nadpisuje price/ma/fng gdy dostępne
    pdata = price_binance.get_price_and_ma()
    warnings += pdata.warnings
    if pdata.price_usd is not None:
        reading["price_usd"] = pdata.price_usd
    if pdata.ma_200w is not None:
        reading["ma_200w"] = pdata.ma_200w
    fg = fear_greed_api.fetch_fear_greed()
    warnings += fg.warnings
    if fg.value is not None:
        reading["fear_greed"] = fg.value

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

    # --- Composite (cała logika w composite.evaluate) ---
    # graded_fng=True: F&G wnosi wkład STOPNIOWY do wyniku ważonego (headline gauge).
    # Wpływa tylko na weighted_met/weighted_ratio — count_met (twardy licznik) bez zmian.
    result = composite.evaluate(data["config"], data["reading"], graded_fng=True)

    ui.composite_summary(result)
    st.divider()
    ui.indicator_grid(result)
    st.divider()

    # --- DCA: opcjonalna ręczna cena (demo bez ceny; live pre-fill z auto-fetch) ---
    st.subheader(T.SECTION_DCA)
    auto_price = _reading_price(data["reading"])  # surowa cena z odczytu
    default_price = auto_price if auto_price is not None else 0.0
    price_in = st.number_input(
        "Cena BTC (USD) do oceny progów DCA — 0 = nieznana",
        min_value=0.0, value=default_price, step=500.0,
        help="W trybie live pole jest wstępnie wypełnione ceną z auto-fetch.",
    )
    current_price = price_in if price_in > 0 else None

    dca_state = dca.compute_dca_state(
        data["dca_df"], current_price=current_price, count_met=result.count_met,
    )
    ui.dca_panel(dca_state)
    st.divider()

    # --- Wykresy ---
    ui.history_charts(data["history_df"])

    # --- Uwagi + disclaimer ---
    ui.warnings_block(list(result.warnings) + list(data["warnings"]) + list(dca_state.warnings))
    ui.footer(composite.DISCLAIMER)


main()
