"""
run_ingest.py — krok 02-API (orkiestracja)
==========================================
Spina auto-fetch (Binance: cena + 200W MA; alternative.me: F&G) z RECZNYMI wskaznikami
z arkusza (sheets.py) i zapisuje komplet do `indicator_readings` przez `upsert_reading`.

Zasada laczenia pol:
  - AUTO wygrywa dla: price_usd, ma_200w, fear_greed
    (gdy auto-fetch zawiedzie -> fallback na wartosc reczna z arkusza, jesli jest),
  - RECZNE (arkusz) dostarcza: mvrv_z_score, nupl, whale_accumulating, whale_ratio,
    ath_date, days_since_ath, notes.

Uruchomienie z korzenia repo (APP_MODE=live, skonfigurowane BQ + Sheets):
    python src/ingestion/run_ingest.py          # zapis
    BTT_DRY_RUN=1 python src/ingestion/run_ingest.py   # bez zapisu (podglad)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

# Importy dzialaja i jako pakiet, i przy bezposrednim uruchomieniu skryptu.
try:
    from . import price_binance, fear_greed_api, sheets
    from ..warehouse import bigquery_client as wh
except ImportError:  # python src/ingestion/run_ingest.py
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, _here)                                   # src/ingestion
    sys.path.insert(0, os.path.join(_here, "..", "warehouse"))  # src/warehouse
    import price_binance          # type: ignore
    import fear_greed_api         # type: ignore
    import sheets                 # type: ignore
    import bigquery_client as wh  # type: ignore

logger = logging.getLogger(__name__)

_AUTO_FIELDS = ("price_usd", "ma_200w", "fear_greed")


@dataclass
class IngestResult:
    reading_date: date
    values: dict[str, Any]
    rows_affected: Optional[int]
    warnings: list[str] = field(default_factory=list)


def collect_values(reading_date: date, use_sheet_manual: bool = True) -> tuple[dict[str, Any], list[str]]:
    """Zbiera komplet pol pod upsert_reading (BEZ zapisu). Zwraca (values, warnings)."""
    warnings: list[str] = []
    values: dict[str, Any] = {}

    # 1) AUTO: cena spot + 200W MA (Binance; fallback CoinGecko dla ceny)
    pdata = price_binance.get_price_and_ma()
    warnings += pdata.warnings
    if pdata.price_usd is not None:
        values["price_usd"] = pdata.price_usd
    if pdata.ma_200w is not None:
        values["ma_200w"] = pdata.ma_200w

    # 2) AUTO: Fear & Greed (alternative.me)
    fg = fear_greed_api.fetch_fear_greed()
    warnings += fg.warnings
    if fg.value is not None:
        values["fear_greed"] = fg.value

    # 3) RECZNE z arkusza (najnowszy wiersz indicator_readings)
    if use_sheet_manual:
        try:
            bundle = sheets.load_all()
            warnings += bundle.validation.warnings
            row = sheets.latest_reading(bundle.readings)
            if row is not None:
                manual = sheets.build_reading_values(row)
                for key, val in manual.items():
                    if key in _AUTO_FIELDS:
                        values.setdefault(key, val)   # tylko gdy auto nie dostarczylo
                    elif val is not None:
                        values[key] = val             # reczne pola wskaznikow
        except Exception as exc:
            warnings.append(f"Arkusz niedostepny ({exc}) — zapisuje tylko auto-wskazniki.")

    # 4) days_since_ath z ath_date, jesli nie podano recznie
    if values.get("days_since_ath") is None and values.get("ath_date"):
        try:
            values["days_since_ath"] = (reading_date - values["ath_date"]).days
        except Exception:
            pass

    return values, warnings


def ingest_today(reading_date: Optional[date] = None,
                 use_sheet_manual: bool = True,
                 dry_run: bool = False) -> IngestResult:
    """Pelny przebieg: zbierz wartosci i (opcjonalnie) zapisz przez upsert_reading."""
    reading_date = reading_date or date.today()
    values, warnings = collect_values(reading_date, use_sheet_manual)

    rows: Optional[int] = None
    if dry_run:
        warnings.append("dry_run=True — nie zapisano do BigQuery.")
    else:
        try:
            rows = wh.upsert_reading(reading_date, values)
        except Exception as exc:
            warnings.append(f"upsert_reading nie powiodl sie: {exc}")

    return IngestResult(reading_date, values, rows, warnings)


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)
    res = ingest_today(dry_run=(os.getenv("BTT_DRY_RUN") == "1"))
    print(f"reading_date={res.reading_date}  rows_affected={res.rows_affected}")
    print("values:", res.values)
    for w in res.warnings:
        print("  !", w)
