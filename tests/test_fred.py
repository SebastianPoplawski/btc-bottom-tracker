"""
test_fred.py — krok 15
Czysta logika fred_api (parser obserwacji, delty, YoY) + degradacja bez klucza
+ montaż pól makro w run_ingest.collect_values. Bez sieci — payloady inline / mocki.
Uruchom z korzenia repo:  python -m pytest tests/ -q
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

_root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_root, "src", "ingestion"))
sys.path.insert(0, os.path.join(_root, "src", "warehouse"))
import fred_api as fa  # noqa: E402


# --------------------------------------------------------------------------- #
# Parser obserwacji FRED
# --------------------------------------------------------------------------- #
def test_parse_observations_skips_dots_and_sorts():
    payload = {"observations": [
        {"date": "2026-07-20", "value": "4.33"},
        {"date": "2026-07-18", "value": "."},      # FRED: brak danych
        {"date": "2026-07-15", "value": "4.10"},
        {"date": "zepsuta",    "value": "1.0"},    # smiec -> pominiety
    ]}
    out = fa._parse_observations(payload)
    assert out == [(date(2026, 7, 15), 4.10), (date(2026, 7, 20), 4.33)]


def test_parse_observations_empty_payload():
    assert fa._parse_observations({}) == []
    assert fa._parse_observations({"observations": []}) == []


# --------------------------------------------------------------------------- #
# Delty / YoY (serie z lukami: weekendy, publikacje miesieczne)
# --------------------------------------------------------------------------- #
def _series_daily():
    # ostatnia 2026-07-20 = 4.50; ~3 mies. wczesniej (2026-04-20) = 4.00
    return [
        (date(2026, 4, 18), 3.90),
        (date(2026, 4, 20), 4.00),
        (date(2026, 6, 1), 4.25),
        (date(2026, 7, 20), 4.50),
    ]


def test_value_on_or_before_handles_gaps():
    s = _series_daily()
    assert fa.value_on_or_before(s, date(2026, 4, 21)) == 4.00  # luka -> ostatnia <= target
    assert fa.value_on_or_before(s, date(2026, 4, 20)) == 4.00
    assert fa.value_on_or_before(s, date(2026, 4, 19)) == 3.90
    assert fa.value_on_or_before(s, date(2026, 1, 1)) is None


def test_compute_delta_3m():
    delta = fa.compute_delta(_series_daily(), fa.DELTA_3M_DAYS)
    assert delta == pytest.approx(4.50 - 4.00)


def test_compute_delta_insufficient_history():
    assert fa.compute_delta([(date(2026, 7, 20), 4.5)], fa.DELTA_3M_DAYS) is None
    assert fa.compute_delta([], fa.DELTA_3M_DAYS) is None


def test_compute_yoy_pct_monthly_series():
    # M2 miesieczne: 2025-06-01 = 21000, 2026-06-01 = 21630 -> +3.0% r/r
    s = [
        (date(2025, 5, 1), 20900.0),
        (date(2025, 6, 1), 21000.0),
        (date(2026, 5, 1), 21500.0),
        (date(2026, 6, 1), 21630.0),
    ]
    assert fa.compute_yoy_pct(s) == pytest.approx(3.0)


def test_compute_yoy_pct_contraction_negative():
    s = [(date(2025, 6, 1), 21000.0), (date(2026, 6, 1), 20790.0)]
    assert fa.compute_yoy_pct(s) == pytest.approx(-1.0)


# --------------------------------------------------------------------------- #
# get_macro: degradacja bez klucza / per-seria
# --------------------------------------------------------------------------- #
def test_get_macro_without_key_degrades(monkeypatch):
    monkeypatch.setattr(fa, "get_api_key", lambda: None)
    m = fa.get_macro()
    assert m.fed_funds_rate is None and m.dxy_proxy is None and m.m2_yoy is None
    assert any("FRED_API_KEY" in w for w in m.warnings)


def test_get_macro_partial_failure(monkeypatch):
    monkeypatch.setattr(fa, "get_api_key", lambda: "test-key")

    def fake_fetch(series_id, days_back, api_key=None, as_of=None):
        if series_id == fa.SERIES_FED_FUNDS:
            return _series_daily()
        raise RuntimeError("seria niedostepna")

    monkeypatch.setattr(fa, "fetch_series", fake_fetch)
    m = fa.get_macro()
    assert m.fed_funds_rate == 4.50
    assert m.fed_funds_delta_3m == pytest.approx(0.50)
    assert m.dxy_proxy is None and m.m2_yoy is None
    assert any("DTWEXBGS" in w for w in m.warnings)
    assert any("M2SL" in w for w in m.warnings)


# --------------------------------------------------------------------------- #
# run_ingest.collect_values — montaz pol makro + MA Pi Cycle
# --------------------------------------------------------------------------- #
def test_collect_values_includes_macro_and_pi_cycle(monkeypatch):
    import price_binance as pb
    import fear_greed_api as fga
    import run_ingest as ri

    monkeypatch.setattr(ri.price_binance, "get_price_and_ma", lambda: pb.PriceData(
        price_usd=100000.0, ma_200w=50000.0, weeks_available=210,
        ma_111d=90000.0, ma_350d=60000.0, days_available=360))
    monkeypatch.setattr(ri.fear_greed_api, "fetch_fear_greed",
                        lambda: type("FG", (), {"value": 40, "warnings": []})())
    monkeypatch.setattr(ri.fred_api, "get_macro", lambda: fa.MacroData(
        fed_funds_rate=4.5, fed_funds_delta_3m=0.5, dxy_proxy=120.0,
        dxy_delta_3m=-1.2, m2_yoy=3.0, warnings=["nota"]))

    values, warnings = ri.collect_values(date(2026, 7, 26), use_sheet_manual=False)
    assert values["ma_111d"] == 90000.0 and values["ma_350d"] == 60000.0
    assert values["fed_funds_rate"] == 4.5 and values["fed_funds_delta_3m"] == 0.5
    assert values["dxy_proxy"] == 120.0 and values["dxy_delta_3m"] == -1.2
    assert values["m2_yoy"] == 3.0
    assert "nota" in warnings
    # wszystkie pola auto naleza do whitelisty upsertu warehouse
    import bigquery_client as wh
    reading_fields = {name for name, _ in wh._READING_FIELDS}
    assert set(ri._AUTO_FIELDS) <= reading_fields


def test_collect_values_macro_failure_does_not_break(monkeypatch):
    import price_binance as pb
    import run_ingest as ri

    monkeypatch.setattr(ri.price_binance, "get_price_and_ma", lambda: pb.PriceData(
        price_usd=None, ma_200w=None, weeks_available=0))
    monkeypatch.setattr(ri.fear_greed_api, "fetch_fear_greed",
                        lambda: type("FG", (), {"value": None, "warnings": []})())

    def boom():
        raise RuntimeError("FRED down")
    monkeypatch.setattr(ri.fred_api, "get_macro", boom)

    values, warnings = ri.collect_values(date(2026, 7, 26), use_sheet_manual=False)
    assert "fed_funds_rate" not in values
    assert any("Makro FRED niedostepne" in w for w in warnings)
