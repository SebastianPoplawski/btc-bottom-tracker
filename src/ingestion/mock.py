"""
mock.py — krok 04 (źródło danych DEMO)
======================================
Ładuje seed (snapshot 2026-06-01) i zwraca struktury w kształtach zgodnych z
warstwą live, tak by app.py traktował demo i live tym samym kodem:

  - config:    list[dict]            -> wprost do composite.evaluate
  - reading:   dict (najnowszy wpis) -> wprost do composite.evaluate
  - readings_df / dca_df: pandas.DataFrame (pod wykresy i panel DCA)

Bez sieci, bez BigQuery. pandas importowany leniwie (demo dla logiki działa i bez niego).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any, Optional

try:
    import config as _config  # gdy src/ na sys.path (jak w app.py)
except Exception:  # pragma: no cover - fallback przy innym sposobie importu
    _config = None


def _seed_path(path: Optional[str] = None) -> str:
    if path:
        return path
    if _config is not None:
        return _config.SEED_PATH
    here = os.path.dirname(os.path.abspath(__file__))            # .../src/ingestion
    root = os.path.dirname(os.path.dirname(here))                # repo root
    return os.path.join(root, "data", "seed_snapshot_2026-06-01.json")


def load_seed(path: Optional[str] = None) -> dict:
    with open(_seed_path(path), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_date(v: Any) -> Optional[date]:
    if not v:
        return None
    try:
        return datetime.strptime(str(v), "%Y-%m-%d").date()
    except ValueError:
        return None


def seed_config(seed: Optional[dict] = None) -> list[dict]:
    seed = seed or load_seed()
    return list(seed.get("config_thresholds", []))


def latest_reading(seed: Optional[dict] = None) -> dict:
    """Najnowszy wiersz indicator_readings jako dict (reading_date -> date)."""
    seed = seed or load_seed()
    rows = seed.get("indicator_readings", []) or []
    if not rows:
        return {}
    rows = sorted(rows, key=lambda r: str(r.get("reading_date", "")))
    row = dict(rows[-1])
    row["reading_date"] = _parse_date(row.get("reading_date"))
    if row.get("ath_date"):
        row["ath_date"] = _parse_date(row.get("ath_date"))
    return row


def readings_df(seed: Optional[dict] = None):
    """Historia odczytów jako DataFrame (w demo zwykle 1 wiersz)."""
    import pandas as pd
    seed = seed or load_seed()
    df = pd.DataFrame(seed.get("indicator_readings", []))
    if not df.empty and "reading_date" in df.columns:
        df["reading_date"] = pd.to_datetime(df["reading_date"], errors="coerce")
        df = df.sort_values("reading_date").reset_index(drop=True)
    return df


def dca_df(seed: Optional[dict] = None):
    import pandas as pd
    seed = seed or load_seed()
    df = pd.DataFrame(seed.get("dca_tranches", []))
    if not df.empty and "trigger_price_usd" in df.columns:
        df = df.sort_values("trigger_price_usd", ascending=False).reset_index(drop=True)
    return df


def snapshot_date(seed: Optional[dict] = None) -> Optional[date]:
    seed = seed or load_seed()
    return _parse_date((seed.get("_meta") or {}).get("snapshot_date"))
