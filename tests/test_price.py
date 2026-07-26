"""
test_price.py — krok 07
Test czystego parsera Kraken OHLC (fallback dla 200W MA, gdy Binance daje 451 z US).
Bez sieci — payload inline, jak test _parse_klines. Uruchom z korzenia repo:
    python -m pytest tests/ -q
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

# Import jak w test_signals.py: dolóż sciezke do src/ingestion.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ingestion"))
import price_binance as pb  # noqa: E402


# Trzy tygodnie: A i B zamkniete (time + 604800 < now), C to biezacy tydzien (jeszcze trwa).
# Celowo NIE po kolei (B przed A), zeby sprawdzic sortowanie rosnaco.
_T_A = 1_700_000_000          # zamkniety dawno
_T_B = 1_700_604_800          # A + 1 tydzien, tez zamkniety
_T_C = 1_701_000_000          # biezacy, niezamkniety wzgledem now ponizej
_NOW_MS = 1_701_300_000 * 1000  # A i B juz zamkniete; C jeszcze nie

_KRAKEN_PAYLOAD = {
    "error": [],
    "result": {
        # row = [time, open, high, low, close, vwap, volume, count]
        "XXBTZUSD": [
            [_T_B, "20500.0", "21500.0", "20000.0", "21000.0", "20800.0", "123.4", 456],
            [_T_A, "19000.0", "20600.0", "18800.0", "20000.5", "19900.0", "234.5", 567],
            [_T_C, "21000.0", "22000.0", "20900.0", "21900.9", "21500.0", "12.3",  78],
        ],
        "last": 1_701_000_000,
    },
}


def test_parse_kraken_ohlc_extract_sort_and_drop_current_week():
    out = pb._parse_kraken_ohlc(_KRAKEN_PAYLOAD, now_ms=_NOW_MS)

    # C (biezacy tydzien) odrzucony -> zostaja 2 zamkniecia.
    assert len(out) == 2

    # Posortowane rosnaco po dacie (A przed B mimo odwrotnej kolejnosci w payloadzie).
    dates = [d for d, _ in out]
    assert dates == sorted(dates)

    expected_a = datetime.fromtimestamp(_T_A, tz=timezone.utc).date()
    expected_b = datetime.fromtimestamp(_T_B, tz=timezone.utc).date()
    assert dates == [expected_a, expected_b]

    # close = pole index 4 (string -> float), we wlasciwej kolejnosci.
    closes = [c for _, c in out]
    assert closes == [20000.5, 21000.0]


def test_parse_kraken_ohlc_picks_pair_key_not_last():
    # Klucz pary to jedyny klucz w result rozny od "last".
    out = pb._parse_kraken_ohlc(_KRAKEN_PAYLOAD, now_ms=_NOW_MS)
    assert all(isinstance(c, float) for _, c in out)
    assert len(out) == 2


def test_parse_kraken_ohlc_empty_when_no_pair_key():
    # Defensywnie: brak klucza pary -> pusta lista, bez wyjatku.
    assert pb._parse_kraken_ohlc({"result": {"last": 0}}, now_ms=_NOW_MS) == []


# --------------------------------------------------------------------------- #
# Kraken Ticker (cena spot, fallback po Binance/CoinGecko) — krok 09
# --------------------------------------------------------------------------- #
_KRAKEN_TICKER_PAYLOAD = {
    "error": [],
    "result": {
        # c = [last_trade_price, lot_volume]; bierzemy c[0].
        "XXBTZUSD": {
            "a": ["64010.0", "1", "1.000"],
            "b": ["64005.0", "2", "2.000"],
            "c": ["64007.5", "0.015"],
            "v": ["100.0", "200.0"],
        },
    },
}


def test_parse_kraken_ticker_extracts_last_price():
    # Cena = c[0] (string -> float), z wlasciwego klucza pary.
    price = pb._parse_kraken_ticker(_KRAKEN_TICKER_PAYLOAD)
    assert price == 64007.5
    assert isinstance(price, float)


def test_parse_kraken_ticker_none_when_no_pair_key():
    # Defensywnie: brak klucza pary -> None, bez wyjatku.
    assert pb._parse_kraken_ticker({"result": {}}) is None
    assert pb._parse_kraken_ticker({"result": {"XXBTZUSD": {}}}) is None


# --------------------------------------------------------------------------- #
# krok 15: swiece dzienne (Pi Cycle 111DMA / 350DMA)
# --------------------------------------------------------------------------- #
_DAY = 86400
_D_A = 1_700_000_000                 # dzien zamkniety
_D_B = _D_A + _DAY                   # zamkniety
_D_C = _D_B + _DAY                   # biezacy (niezamkniety wzgledem _NOW_D)
_NOW_D = (_D_C + 100) * 1000         # A i B zamkniete; C jeszcze trwa

_KRAKEN_DAILY = {
    "error": [],
    "result": {
        "XXBTZUSD": [
            [_D_B, "20500.0", "21500.0", "20000.0", "21000.0", "20800.0", "123.4", 456],
            [_D_A, "19000.0", "20600.0", "18800.0", "20000.5", "19900.0", "234.5", 567],
            [_D_C, "21000.0", "22000.0", "20900.0", "21900.9", "21500.0", "12.3",  78],
        ],
        "last": _D_C,
    },
}


def test_parse_kraken_ohlc_daily_period_drops_current_day():
    out = pb._parse_kraken_ohlc(_KRAKEN_DAILY, now_ms=_NOW_D, period_seconds=pb.DAY_SECONDS)
    assert len(out) == 2  # C (biezacy dzien) odrzucony
    assert [c for _, c in out] == [20000.5, 21000.0]


def test_parse_kraken_ohlc_weekly_default_unchanged():
    # Domyslne period_seconds=WEEK_SECONDS: dla tych timestampow zaden "tydzien"
    # nie jest zamkniety wzgledem _NOW_D -> pusta lista (regresja starego zachowania).
    out = pb._parse_kraken_ohlc(_KRAKEN_DAILY, now_ms=_NOW_D)
    assert out == []


def test_compute_ma_generic_windows():
    closes = [float(i) for i in range(1, 401)]  # 1..400
    ma111 = pb.compute_200w_ma(closes, window=pb.MA_111_WINDOW)
    ma350 = pb.compute_200w_ma(closes, window=pb.MA_350_WINDOW)
    assert ma111 == sum(range(290, 401)) / 111
    assert ma350 == sum(range(51, 401)) / 350
    assert pb.compute_200w_ma(closes[:100], window=pb.MA_350_WINDOW) is None


def test_pricedata_backward_compatible_defaults():
    d = pb.PriceData(price_usd=1.0, ma_200w=2.0, weeks_available=3)
    assert d.ma_111d is None and d.ma_350d is None and d.days_available == 0
