"""
fred_api.py — krok 15 (makro: FRED)
===================================
Wskazniki makro z darmowego API FRED (St. Louis Fed) pod OSOBNY licznik
risk-off (side=macro — POZA frameworkiem dna/szczytu):

  - DFF       -> fed_funds_rate + fed_funds_delta_3m  (stopa Fed; zmiana vs ~3 mies.)
  - DTWEXBGS  -> dxy_proxy + dxy_delta_3m             (broad dollar index — proxy DXY;
                                                       klasyczny DXY nie jest na FRED)
  - M2SL      -> m2_yoy                               (podaz M2 USA, dynamika r/r w %;
                                                       publikacja MIESIECZNA z opoznieniem)

Klucz API (darmowy, https://fred.stlouisfed.org/docs/api/api_key.html):
  st.secrets["FRED_API_KEY"] lub env FRED_API_KEY — NIGDY na sztywno w kodzie.
Brak klucza => wszystkie pola None + czytelny warning (lagodna degradacja,
spojnie z reszta warstwy ingestion). etf_flows_usd_7d NIE jest tu pobierany
(brak darmowego API — wpis reczny przez Sheets).

Zaleznosci: requests, tenacity (sa w requirements.txt).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import requests
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
HTTP_TIMEOUT = 15
_USER_AGENT = "btc-bottom-tracker/0.2 (ingestion)"

SERIES_FED_FUNDS = "DFF"
SERIES_DOLLAR = "DTWEXBGS"
SERIES_M2 = "M2SL"

DELTA_3M_DAYS = 91      # "~3 miesiace wstecz" dla delt DFF/DTWEXBGS
M2_YOY_DAYS = 365       # rok wstecz dla dynamiki M2 r/r
_LOOKBACK_MARGIN = 45   # zapas na weekendy/swieta/opoznienia publikacji


def _maybe_cache(ttl_seconds: int):
    """st.cache_data gdy w Streamlit; poza nim no-op (spojnie z price_binance)."""
    try:
        import streamlit as st  # noqa: WPS433
        return st.cache_data(ttl=ttl_seconds, show_spinner=False)
    except Exception:
        def _identity(func):
            return func
        return _identity


def get_api_key() -> Optional[str]:
    """Klucz FRED: najpierw st.secrets, potem env. None gdy brak (bez wyjatku)."""
    try:
        import streamlit as st  # noqa: WPS433
        key = st.secrets.get("FRED_API_KEY")
        if key:
            return str(key)
    except Exception:
        pass
    return os.environ.get("FRED_API_KEY") or None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(requests.RequestException),
    reraise=True,
)
def _get_json(url: str, params: Optional[dict] = None):
    resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT,
                        headers={"User-Agent": _USER_AGENT})
    resp.raise_for_status()
    return resp.json()


def _parse_observations(payload: dict) -> list[tuple[date, float]]:
    """Odpowiedz FRED -> [(data, wartosc)] rosnaco; pomija braki (value=".")."""
    out: list[tuple[date, float]] = []
    for obs in payload.get("observations", []):
        raw = str(obs.get("value", ".")).strip()
        if raw in (".", ""):
            continue  # FRED oznacza brak danych kropka
        try:
            d = date.fromisoformat(str(obs.get("date")))
            out.append((d, float(raw)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda t: t[0])
    return out


@_maybe_cache(ttl_seconds=6 * 3600)
def fetch_series(series_id: str, days_back: int, api_key: Optional[str] = None,
                 as_of: Optional[date] = None) -> list[tuple[date, float]]:
    """Obserwacje serii FRED od `days_back` dni wstecz. Wymaga klucza."""
    key = api_key or get_api_key()
    if not key:
        raise RuntimeError("Brak FRED_API_KEY (st.secrets lub env).")
    start = (as_of or date.today()) - timedelta(days=days_back)
    payload = _get_json(FRED_BASE, {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start.isoformat(),
        "sort_order": "asc",
    })
    return _parse_observations(payload)


# --------------------------------------------------------------------------- #
# Czysta logika (testowalna bez sieci)
# --------------------------------------------------------------------------- #
def latest_value(series: list[tuple[date, float]]) -> Optional[float]:
    return series[-1][1] if series else None


def value_on_or_before(series: list[tuple[date, float]], target: date) -> Optional[float]:
    """Ostatnia wartosc z data <= target (serie makro maja luki: weekendy/miesieczne)."""
    best: Optional[float] = None
    for d, v in series:
        if d <= target:
            best = v
        else:
            break  # posortowane rosnaco
    return best


def compute_delta(series: list[tuple[date, float]], days: int) -> Optional[float]:
    """Zmiana: ostatnia wartosc minus wartosc sprzed `days` dni (on-or-before)."""
    if not series:
        return None
    last_date, last_val = series[-1]
    prev = value_on_or_before(series, last_date - timedelta(days=days))
    if prev is None:
        return None
    return last_val - prev


def compute_yoy_pct(series: list[tuple[date, float]]) -> Optional[float]:
    """Dynamika r/r w %: (ostatnia / sprzed roku - 1) * 100."""
    if not series:
        return None
    last_date, last_val = series[-1]
    prev = value_on_or_before(series, last_date - timedelta(days=M2_YOY_DAYS))
    if prev is None or prev == 0:
        return None
    return (last_val / prev - 1.0) * 100.0


# --------------------------------------------------------------------------- #
@dataclass
class MacroData:
    fed_funds_rate: Optional[float] = None
    fed_funds_delta_3m: Optional[float] = None
    dxy_proxy: Optional[float] = None
    dxy_delta_3m: Optional[float] = None
    m2_yoy: Optional[float] = None
    warnings: list[str] = field(default_factory=list)


def get_macro() -> MacroData:
    """Komplet pol makro pod upsert_reading. Bledy per-seria jako warnings —
    awaria jednej serii nie blokuje pozostalych (lagodna degradacja)."""
    out = MacroData()
    if not get_api_key():
        out.warnings.append(
            "Brak FRED_API_KEY — pola makro (Fed/DXY/M2) puste. Zarejestruj darmowy "
            "klucz: https://fred.stlouisfed.org/docs/api/api_key.html"
        )
        return out

    try:
        dff = fetch_series(SERIES_FED_FUNDS, DELTA_3M_DAYS + _LOOKBACK_MARGIN)
        out.fed_funds_rate = latest_value(dff)
        out.fed_funds_delta_3m = compute_delta(dff, DELTA_3M_DAYS)
        if out.fed_funds_delta_3m is None:
            out.warnings.append("FRED DFF: za krotka historia do delty 3M.")
    except Exception as exc:
        out.warnings.append(f"FRED DFF niedostepne ({exc}).")

    try:
        dxy = fetch_series(SERIES_DOLLAR, DELTA_3M_DAYS + _LOOKBACK_MARGIN)
        out.dxy_proxy = latest_value(dxy)
        out.dxy_delta_3m = compute_delta(dxy, DELTA_3M_DAYS)
        if out.dxy_delta_3m is None:
            out.warnings.append("FRED DTWEXBGS: za krotka historia do delty 3M.")
    except Exception as exc:
        out.warnings.append(f"FRED DTWEXBGS niedostepne ({exc}).")

    try:
        m2 = fetch_series(SERIES_M2, M2_YOY_DAYS + 2 * _LOOKBACK_MARGIN)
        out.m2_yoy = compute_yoy_pct(m2)
        if out.m2_yoy is None:
            out.warnings.append("FRED M2SL: za krotka historia do dynamiki r/r.")
    except Exception as exc:
        out.warnings.append(f"FRED M2SL niedostepne ({exc}).")

    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    m = get_macro()
    print(f"fed_funds_rate={m.fed_funds_rate}  delta_3m={m.fed_funds_delta_3m}")
    print(f"dxy_proxy={m.dxy_proxy}  delta_3m={m.dxy_delta_3m}")
    print(f"m2_yoy={m.m2_yoy}")
    for w in m.warnings:
        print("  !", w)
