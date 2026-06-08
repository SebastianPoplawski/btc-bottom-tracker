"""
price_binance.py — krok 02-API
==============================
Cena BTC + 200-tygodniowa srednia (200W MA) z publicznego API Binance (bez klucza).
CoinGecko jako fallback TYLKO dla ceny spot — dla 200W MA brak darmowego zrodla o
wystarczajacej historii (~4 lata), wiec gdy Binance padnie: ma_200w=None + ostrzezenie.

Wynik zwracany jako DANE (PriceData z lista 'warnings'), nie wyjatki — apka degraduje
sie lagodnie (spojnie z reszta warstwy ingestion).

Zaleznosci: requests, tenacity  (sa w requirements.txt)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from typing import Optional

import requests
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
SYMBOL = "BTCUSDT"
MA_WINDOW = 200
WEEKLY_LIMIT = MA_WINDOW + 12        # zapas na odrzucenie biezacego (niezamknietego) tygodnia
HTTP_TIMEOUT = 15
_USER_AGENT = "btc-bottom-tracker/0.2 (ingestion)"


def _maybe_cache(ttl_seconds: int):
    """st.cache_data gdy w Streamlit; poza nim no-op (modul dziala tez jako skrypt)."""
    try:
        import streamlit as st  # noqa: WPS433
        return st.cache_data(ttl=ttl_seconds, show_spinner=False)
    except Exception:
        def _identity(func):
            return func
        return _identity


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


# --- 200W MA -------------------------------------------------------------- #
def _parse_klines(raw: list, now_ms: Optional[int] = None) -> list[tuple[date, float]]:
    """Surowe klines Binance -> [(data_zamkniecia_tygodnia, close)].
    Odrzuca biezacy (niezamkniety) tydzien: closeTime w przyszlosci."""
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    out: list[tuple[date, float]] = []
    for k in raw:
        # k = [openTime, open, high, low, close, volume, closeTime, ...]
        close_time_ms = int(k[6])
        if close_time_ms > now_ms:
            continue  # tydzien jeszcze trwa -> pomijamy do liczenia MA
        out.append((
            datetime.fromtimestamp(close_time_ms / 1000, tz=timezone.utc).date(),
            float(k[4]),
        ))
    return out


def compute_200w_ma(closes: list[float], window: int = MA_WINDOW) -> Optional[float]:
    """Srednia z ostatnich `window` zamkniec tygodniowych. None gdy za malo danych."""
    if len(closes) < window:
        return None
    last = closes[-window:]
    return sum(last) / window


@_maybe_cache(ttl_seconds=3600)
def fetch_weekly_closes(symbol: str = SYMBOL, limit: int = WEEKLY_LIMIT) -> list[tuple[date, float]]:
    raw = _get_json(f"{BINANCE_BASE}/api/v3/klines",
                    {"symbol": symbol, "interval": "1w", "limit": limit})
    return _parse_klines(raw)


# --- cena spot ------------------------------------------------------------ #
@_maybe_cache(ttl_seconds=300)
def fetch_spot_price_binance(symbol: str = SYMBOL) -> Optional[float]:
    data = _get_json(f"{BINANCE_BASE}/api/v3/ticker/price", {"symbol": symbol})
    return float(data["price"]) if "price" in data else None


@_maybe_cache(ttl_seconds=300)
def fetch_spot_price_coingecko() -> Optional[float]:
    data = _get_json(f"{COINGECKO_BASE}/simple/price",
                     {"ids": "bitcoin", "vs_currencies": "usd"})
    return float(data["bitcoin"]["usd"]) if data.get("bitcoin") else None


def fetch_spot_price() -> tuple[Optional[float], list[str]]:
    """Binance jako pierwszy, CoinGecko jako fallback. Zwraca (cena, ostrzezenia)."""
    warnings: list[str] = []
    try:
        p = fetch_spot_price_binance()
        if p:
            return p, warnings
    except Exception as exc:
        warnings.append(f"Binance spot niedostepny ({exc}); probuje CoinGecko.")
    try:
        p = fetch_spot_price_coingecko()
        if p:
            return p, warnings
    except Exception as exc:
        warnings.append(f"CoinGecko spot niedostepny ({exc}).")
    warnings.append("Brak ceny spot z obu zrodel.")
    return None, warnings


@dataclass
class PriceData:
    price_usd: Optional[float]
    ma_200w: Optional[float]
    weeks_available: int
    warnings: list[str] = field(default_factory=list)


def get_price_and_ma() -> PriceData:
    """Komplet: cena spot + 200W MA. Bledy jako 'warnings', pola None gdy brak danych."""
    warnings: list[str] = []
    price, w = fetch_spot_price()
    warnings += w

    ma: Optional[float] = None
    weeks = 0
    try:
        closes = fetch_weekly_closes()
        weeks = len(closes)
        ma = compute_200w_ma([c for _, c in closes])
        if ma is None:
            warnings.append(f"Za malo zamkniec tygodniowych do 200W MA ({weeks} < {MA_WINDOW}).")
    except Exception as exc:
        warnings.append(f"Binance klines niedostepne ({exc}); ma_200w=None (mozna wpisac recznie).")

    return PriceData(price_usd=price, ma_200w=ma, weeks_available=weeks, warnings=warnings)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    d = get_price_and_ma()
    print(f"price_usd={d.price_usd}  ma_200w={d.ma_200w}  weeks={d.weeks_available}")
    for msg in d.warnings:
        print("  !", msg)
