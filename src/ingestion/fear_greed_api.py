"""
fear_greed_api.py — krok 02-API
===============================
Fear & Greed Index z alternative.me (darmowe, bez klucza).
Zwraca wartosc 0-100 (int) + klasyfikacje + date. Wynik jako DANE (z 'warnings').

Prog dna (F&G < 25 = pasmo Extreme Fear) liczy warstwa sygnalow (config_thresholds) —
ten modul tylko DOSTARCZA surowa wartosc.

Zaleznosci: requests, tenacity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

FNG_URL = "https://api.alternative.me/fng/"
HTTP_TIMEOUT = 15
_USER_AGENT = "btc-bottom-tracker/0.2 (ingestion)"


def _maybe_cache(ttl_seconds: int):
    try:
        import streamlit as st  # noqa: WPS433
        return st.cache_data(ttl=ttl_seconds, show_spinner=False)
    except Exception:
        def _identity(func):
            return func
        return _identity


@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=1, max=8),
       retry=retry_if_exception_type(requests.RequestException),
       reraise=True)
def _get_json(url, params=None):
    resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT,
                        headers={"User-Agent": _USER_AGENT})
    resp.raise_for_status()
    return resp.json()


@dataclass
class FearGreed:
    value: Optional[int]
    classification: Optional[str]
    as_of: Optional[date]
    warnings: list[str] = field(default_factory=list)


def _parse_fng(payload: dict) -> FearGreed:
    """Czysta funkcja parsujaca odpowiedz alternative.me (testowalna bez sieci)."""
    warnings: list[str] = []
    data = (payload or {}).get("data") or []
    if not data:
        return FearGreed(None, None, None, ["alternative.me: pusta odpowiedz 'data'."])

    item = data[0]
    try:
        value: Optional[int] = int(item["value"])
    except (KeyError, ValueError, TypeError):
        warnings.append("alternative.me: niepoprawne pole 'value'.")
        value = None
    if value is not None and not (0 <= value <= 100):
        warnings.append(f"F&G poza zakresem 0-100: {value}.")

    as_of: Optional[date] = None
    ts = item.get("timestamp")
    if ts:
        try:
            as_of = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
        except (ValueError, TypeError):
            pass

    return FearGreed(value, item.get("value_classification"), as_of, warnings)


@_maybe_cache(ttl_seconds=1800)
def fetch_fear_greed() -> FearGreed:
    try:
        payload = _get_json(FNG_URL, {"limit": 1, "format": "json"})
    except Exception as exc:
        return FearGreed(None, None, None, [f"alternative.me niedostepne ({exc})."])
    return _parse_fng(payload)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fg = fetch_fear_greed()
    print(f"fear_greed={fg.value} ({fg.classification}) as_of={fg.as_of}")
    for w in fg.warnings:
        print("  !", w)
