"""
test_signals.py — krok 03
Testy logiki sygnałów (composite.py). Bez sieci/BQ — czyste funkcje.
Uruchom z korzenia repo:  python -m pytest tests/ -q
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

# Import jak w run_ingest.py: dołóż ścieżkę do src/logic, działa też jako skrypt.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "logic"))
import composite as c  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures: config i odczyt zgodne ze schematem 01 / seedem 2026-06-01
# --------------------------------------------------------------------------- #
def make_config():
    return [
        {"indicator": "mvrv_z_score",        "operator": "lt",      "threshold_value": 0,    "threshold_value2": None, "weight": 1.0, "active": True, "description": ""},
        {"indicator": "nupl",                "operator": "lt",      "threshold_value": 0,    "threshold_value2": None, "weight": 1.0, "active": True, "description": ""},
        {"indicator": "price_to_200w_ratio", "operator": "lte",     "threshold_value": 1.05, "threshold_value2": None, "weight": 1.0, "active": True, "description": ""},
        {"indicator": "whale_accumulating",  "operator": "is_true", "threshold_value": None, "threshold_value2": None, "weight": 1.0, "active": True, "description": ""},
        {"indicator": "fear_greed",          "operator": "lt",      "threshold_value": 25,   "threshold_value2": None, "weight": 0.5, "active": True, "description": ""},
        {"indicator": "days_since_ath",      "operator": "between", "threshold_value": 300,  "threshold_value2": 400,  "weight": 1.0, "active": True, "description": ""},
    ]


def seed_reading():
    # Snapshot referencyjny 2026-06-01: tylko F&G aktywny.
    return {
        "reading_date": date(2026, 6, 1), "price_usd": None, "mvrv_z_score": None,
        "nupl": None, "ma_200w": None, "whale_accumulating": False, "whale_ratio": 0.90,
        "fear_greed": 23, "days_since_ath": None, "ath_date": None,
    }


def _by_key(result, key):
    return next(r for r in result.indicators if r.indicator == key)


# --------------------------------------------------------------------------- #
# Operatory — poprawność i granice
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value,op,t1,t2,expected", [
    (-0.5, "lt", 0, None, True),
    (0.0, "lt", 0, None, False),        # granica: 0 < 0 False
    (0.0, "lte", 0, None, True),        # granica: 0 <= 0 True
    (5, "gt", 0, None, True),
    (0, "gte", 0, None, True),
    (1.05, "lte", 1.05, None, True),    # ratio dokładnie na progu
    (1.06, "lte", 1.05, None, False),
    (1.00, "lte", 1.05, None, True),
    (300, "between", 300, 400, True),   # granice between domknięte
    (400, "between", 300, 400, True),
    (299, "between", 300, 400, False),
    (401, "between", 300, 400, False),
    (350, "between", 400, 300, True),   # odwrócone granice też działają
    (10, "eq", 10, None, True),
    (10, "eq", 11, None, False),
    (True, "is_true", None, None, True),
    (False, "is_true", None, None, False),
    (False, "is_false", None, None, True),
])
def test_apply_operator(value, op, t1, t2, expected):
    assert c.apply_operator(value, op, t1, t2) is expected


def test_apply_operator_missing_value_returns_none():
    assert c.apply_operator(None, "lt", 0) is None


def test_apply_operator_missing_threshold_returns_none():
    assert c.apply_operator(5, "lt", None) is None
    assert c.apply_operator(5, "between", 300, None) is None


def test_apply_operator_unknown_operator_returns_none():
    assert c.apply_operator(5, "wat", 0) is None


def test_bool_value_not_treated_as_number():
    # whale to bool — operator liczbowy nie może go tknąć
    assert c.apply_operator(True, "gt", 0) is None


# --------------------------------------------------------------------------- #
# Wartość computed: price_to_200w_ratio = price_usd / ma_200w
# --------------------------------------------------------------------------- #
def test_price_to_200w_ratio_computed():
    d = c.derive_values({"price_usd": 60000, "ma_200w": 50000})
    assert d["price_to_200w_ratio"] == pytest.approx(1.2)


def test_price_to_200w_ratio_none_when_missing():
    assert c.derive_values({"price_usd": None, "ma_200w": 50000})["price_to_200w_ratio"] is None
    assert c.derive_values({"price_usd": 60000, "ma_200w": None})["price_to_200w_ratio"] is None
    assert c.derive_values({"price_usd": 60000, "ma_200w": 0})["price_to_200w_ratio"] is None


# --------------------------------------------------------------------------- #
# Seed 2026-06-01 — composite == 1 (twardy kontrakt z seedem)
# --------------------------------------------------------------------------- #
def test_seed_composite_count_is_one():
    res = c.evaluate(make_config(), seed_reading())
    assert res.count_met == 1                 # expected_composite_count z seeda
    assert res.count_active == 6
    assert res.count_evaluable == 2           # F&G (met) + whale (False); reszta brak danych


def test_seed_individual_signals():
    res = c.evaluate(make_config(), seed_reading())
    assert _by_key(res, "fear_greed").met is True       # 23 < 25
    assert _by_key(res, "whale_accumulating").met is False
    assert _by_key(res, "mvrv_z_score").met is None     # brak danych
    assert _by_key(res, "nupl").met is None
    assert _by_key(res, "price_to_200w_ratio").met is None  # price/ma == None
    assert _by_key(res, "days_since_ath").met is None


def test_seed_weighted_score():
    res = c.evaluate(make_config(), seed_reading())
    # oceniane: F&G(0.5, met) + whale(1.0, not met) -> total 1.5, met 0.5
    assert res.weighted_met == pytest.approx(0.5)
    assert res.weighted_total == pytest.approx(1.5)
    assert res.weighted_ratio == pytest.approx(0.5 / 1.5)


# --------------------------------------------------------------------------- #
# Fear & Greed — granica progu < 25
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fng,expected", [(24, True), (25, False), (8, True), (30, False)])
def test_fear_greed_threshold_boundary(fng, expected):
    reading = seed_reading() | {"fear_greed": fng}
    res = c.evaluate(make_config(), reading)
    assert _by_key(res, "fear_greed").met is expected


# --------------------------------------------------------------------------- #
# Hak na stopniowy F&G (domyślnie wyłączony)
# --------------------------------------------------------------------------- #
def test_graded_fear_greed_function():
    assert c.graded_fear_greed(8) == pytest.approx(1.0)    # <10 pełny
    assert c.graded_fear_greed(25) == pytest.approx(0.0)   # >=25 zero
    assert c.graded_fear_greed(10) == pytest.approx(1.0)   # granica
    assert 0.0 < c.graded_fear_greed(20) < 1.0             # liniowo w środku


def test_graded_toggle_changes_weighted_not_counter():
    reading = seed_reading() | {"fear_greed": 20}          # 20 < 25 -> binarnie met
    binary = c.evaluate(make_config(), reading, graded_fng=False)
    graded = c.evaluate(make_config(), reading, graded_fng=True)
    # licznik identyczny
    assert binary.count_met == graded.count_met == 1
    # wkład ważony F&G mniejszy w trybie graded (20 -> ~0.33 * 0.5)
    fng_binary = _by_key(binary, "fear_greed").contribution
    fng_graded = _by_key(graded, "fear_greed").contribution
    assert fng_binary == pytest.approx(0.5)
    assert fng_graded < fng_binary
    assert fng_graded == pytest.approx(0.5 * (25 - 20) / 15)


# --------------------------------------------------------------------------- #
# Pełne dno — wszystkie 6 spełnione
# --------------------------------------------------------------------------- #
def test_full_bottom_all_six():
    reading = {
        "reading_date": date(2026, 9, 1), "price_usd": 50000, "ma_200w": 50000,  # ratio 1.0 <= 1.05
        "mvrv_z_score": -0.3, "nupl": -0.1, "whale_accumulating": True,
        "fear_greed": 12, "days_since_ath": 350,
    }
    res = c.evaluate(make_config(), reading)
    assert res.count_met == 6
    assert res.count_evaluable == 6
    assert "Wszystkie warunki dna" in res.verdict


# --------------------------------------------------------------------------- #
# Aktywność / wagi / werdykt
# --------------------------------------------------------------------------- #
def test_inactive_indicator_excluded_from_counts():
    cfg = make_config()
    cfg[4]["active"] = False     # wyłącz F&G
    res = c.evaluate(cfg, seed_reading())
    assert res.count_active == 5
    assert res.count_met == 0    # F&G był jedynym spełnionym, ale teraz nieaktywny


def test_verdict_bands():
    assert "Żaden sygnał" in c.build_verdict(0, 6, 6)
    assert "wczesne" in c.build_verdict(1, 6, 6)
    assert "mieszany" in c.build_verdict(3, 6, 6)
    assert "Większość" in c.build_verdict(5, 6, 6)


def test_verdict_reports_missing_data():
    res = c.evaluate(make_config(), seed_reading())
    assert "bez danych" in res.verdict      # 4 wskaźniki bez danych w seedzie


# --------------------------------------------------------------------------- #
# Odporność wejścia: pandas Series / DataFrame / przecinek dziesiętny
# --------------------------------------------------------------------------- #
def test_accepts_pandas_series_and_dataframe():
    pd = pytest.importorskip("pandas")
    s = pd.Series(seed_reading())
    res_series = c.evaluate(make_config(), s)
    res_df = c.evaluate(make_config(), pd.DataFrame([seed_reading()]))
    assert res_series.count_met == 1
    assert res_df.count_met == 1


def test_config_as_dataframe():
    pd = pytest.importorskip("pandas")
    res = c.evaluate(pd.DataFrame(make_config()), seed_reading())
    assert res.count_met == 1


def test_no_config_warns():
    res = c.evaluate([], seed_reading())
    assert res.count_active == 0
    assert any("Brak progów" in w for w in res.warnings)


def test_disclaimer_present():
    res = c.evaluate(make_config(), seed_reading())
    assert res.disclaimer == c.DISCLAIMER
