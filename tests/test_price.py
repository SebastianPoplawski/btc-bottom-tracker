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
