"""
test_topside.py — krok 14
Logika strony SZCZYTU + MAKRO: computed pi_cycle_crossed i months_since_halving,
graded_greed (lustro graded F&G), werdykty side-aware, evaluate_side.
Bez sieci/BQ — czyste funkcje.
Uruchom z korzenia repo:  python -m pytest tests/ -q
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

import pytest

_root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_root, "src", "logic"))
sys.path.insert(0, os.path.join(_root, "src", "ingestion"))
import composite as c  # noqa: E402
import mock  # noqa: E402


def top_config():
    """6 progów top 1:1 z data/sheets_tab_config_thresholds.csv (side=top)."""
    return [
        {"indicator": "mvrv_z_score",         "operator": "gt",      "threshold_value": 5,    "weight": 0.5, "active": True, "side": "top"},
        {"indicator": "nupl",                 "operator": "gt",      "threshold_value": 0.7,  "weight": 0.5, "active": True, "side": "top"},
        {"indicator": "price_to_200w_ratio",  "operator": "gte",     "threshold_value": 2.5,  "weight": 1.0, "active": True, "side": "top"},
        {"indicator": "fear_greed",           "operator": "gt",      "threshold_value": 75,   "weight": 0.5, "active": True, "side": "top"},
        {"indicator": "pi_cycle_crossed",     "operator": "is_true", "threshold_value": None, "weight": 1.0, "active": True, "side": "top"},
        {"indicator": "months_since_halving", "operator": "between", "threshold_value": 12, "threshold_value2": 18, "weight": 1.0, "active": True, "side": "top"},
    ]


def macro_config():
    return [
        {"indicator": "fed_funds_delta_3m", "operator": "gt", "threshold_value": 0, "weight": 1.0, "active": True, "side": "macro"},
        {"indicator": "dxy_delta_3m",       "operator": "gt", "threshold_value": 0, "weight": 1.0, "active": True, "side": "macro"},
        {"indicator": "m2_yoy",             "operator": "lt", "threshold_value": 0, "weight": 1.0, "active": True, "side": "macro"},
        {"indicator": "etf_flows_usd_7d",   "operator": "lt", "threshold_value": 0, "weight": 1.0, "active": True, "side": "macro"},
    ]


# --------------------------------------------------------------------------- #
# Computed: pi_cycle_crossed
# --------------------------------------------------------------------------- #
def test_pi_cycle_missing_data_is_none():
    d = c.derive_values({"ma_111d": None, "ma_350d": 45000})
    assert d["pi_cycle_crossed"] is None
    d = c.derive_values({})
    assert d["pi_cycle_crossed"] is None


def test_pi_cycle_crossed_true_false_and_boundary():
    assert c.derive_values({"ma_111d": 100000, "ma_350d": 45000})["pi_cycle_crossed"] is True
    assert c.derive_values({"ma_111d": 80000, "ma_350d": 45000})["pi_cycle_crossed"] is False
    # dokładnie 2x -> crossed (>=)
    assert c.derive_values({"ma_111d": 90000, "ma_350d": 45000})["pi_cycle_crossed"] is True


def test_pi_cycle_feeds_is_true_operator():
    cfg = [r for r in top_config() if r["indicator"] == "pi_cycle_crossed"]
    res = c.evaluate(cfg, {"ma_111d": 100000, "ma_350d": 45000})
    assert res.count_met == 1
    res = c.evaluate(cfg, {"ma_111d": 80000, "ma_350d": 45000})
    assert res.count_met == 0 and res.count_evaluable == 1


# --------------------------------------------------------------------------- #
# Computed: months_since_halving
# --------------------------------------------------------------------------- #
def test_months_since_halving_computed_from_halving_date():
    d = c.derive_values({"reading_date": date(2025, 7, 20), "halving_date": date(2024, 4, 20)})
    assert d["months_since_halving"] == pytest.approx(456 / 30.4375, rel=1e-9)  # ~15.0


def test_months_since_halving_missing_without_halving_date():
    assert "months_since_halving" not in c.derive_values({"reading_date": date(2026, 6, 1)})


def test_months_since_halving_seed_outside_window():
    # Seed 2026-06-01, halving 2024-04-20 -> 772 dni ~ 25.4 mies. -> poza 12-18.
    reading = mock.latest_reading()
    d = c.derive_values(reading)
    assert d["months_since_halving"] == pytest.approx(772 / 30.4375, rel=1e-9)
    cfg = [r for r in top_config() if r["indicator"] == "months_since_halving"]
    res = c.evaluate(cfg, reading)
    assert res.count_met == 0 and res.count_evaluable == 1  # oceniony False, nie brak danych


def test_months_since_halving_in_window_met():
    cfg = [r for r in top_config() if r["indicator"] == "months_since_halving"]
    reading = {"reading_date": date(2025, 7, 20), "halving_date": date(2024, 4, 20)}
    assert c.evaluate(cfg, reading).count_met == 1


# --------------------------------------------------------------------------- #
# Graded greed (lustro graded F&G) — tylko wynik ważony, licznik binarny
# --------------------------------------------------------------------------- #
def test_graded_greed_curve():
    assert c.graded_greed(None) is None
    assert c.graded_greed(50) == 0.0
    assert c.graded_greed(75) == 0.0
    assert c.graded_greed(90) == 1.0
    assert c.graded_greed(100) == 1.0
    assert c.graded_greed(80) == pytest.approx(5 / 15)


def test_graded_greed_contribution_in_top_evaluate():
    cfg = [r for r in top_config() if r["indicator"] == "fear_greed"]
    res = c.evaluate(cfg, {"fear_greed": 80}, graded_fng=True)
    assert res.count_met == 1  # licznik binarny bez zmian
    assert res.weighted_met == pytest.approx(0.5 * (5 / 15))
    # bez graded: pełna waga
    res_plain = c.evaluate(cfg, {"fear_greed": 80})
    assert res_plain.weighted_met == pytest.approx(0.5)


def test_graded_direction_picked_by_operator():
    # Ten sam odczyt 80: strona TOP (gt) dostaje wkład częściowy,
    # strona BOTTOM (lt 25) w ogóle niespełniona — kierunek po operatorze.
    bottom_row = [{"indicator": "fear_greed", "operator": "lt", "threshold_value": 25,
                   "weight": 0.5, "active": True, "side": "bottom"}]
    res_b = c.evaluate(bottom_row, {"fear_greed": 80}, graded_fng=True)
    assert res_b.count_met == 0 and res_b.weighted_met == 0.0
    # regresja dna: odczyt 23 -> graded fear (25-23)/15
    res_f = c.evaluate(bottom_row, {"fear_greed": 23}, graded_fng=True)
    assert res_f.weighted_met == pytest.approx(0.5 * (2 / 15))


def test_fear_greed_boundary_75_not_met_on_top():
    cfg = [r for r in top_config() if r["indicator"] == "fear_greed"]
    assert c.evaluate(cfg, {"fear_greed": 75}).count_met == 0


# --------------------------------------------------------------------------- #
# Pełny szczyt 6/6 + werdykty side-aware
# --------------------------------------------------------------------------- #
def full_top_reading():
    return {
        "reading_date": date(2025, 7, 20),   # ~15 mies. od halvingu
        "halving_date": date(2024, 4, 20),
        "mvrv_z_score": 6.2, "nupl": 0.82,
        "price_usd": 300000, "ma_200w": 100000,   # ratio 3.0 >= 2.5
        "fear_greed": 95,
        "ma_111d": 100000, "ma_350d": 45000,      # crossed
    }


def test_full_top_six_of_six():
    res = c.evaluate(top_config(), full_top_reading(), graded_fng=True, side=c.SIDE_TOP)
    assert res.count_met == 6 and res.count_active == 6 and res.count_evaluable == 6
    # wagi: 0.5+0.5+1.0+0.5(F&G 95 -> pełny)+1.0+1.0 = 4.5
    assert res.weighted_met == pytest.approx(4.5)
    assert "Wszystkie warunki szczytu" in res.verdict


def test_verdict_top_zero():
    v = c.build_verdict(0, 6, 2, side=c.SIDE_TOP)
    assert "warunków szczytu" in v and "Żaden sygnał szczytu" in v and "(4 bez danych)" in v


def test_verdict_macro():
    v0 = c.build_verdict(0, 4, 4, side=c.SIDE_MACRO)
    assert v0.startswith("Otoczenie makro") and "risk-off" in v0
    v3 = c.build_verdict(3, 4, 4, side=c.SIDE_MACRO)
    assert "Przewaga sygnałów risk-off" in v3
    v2 = c.build_verdict(2, 4, 4, side=c.SIDE_MACRO)
    assert "mieszane" in v2


def test_verdict_backward_compatible_three_args():
    # Stara sygnatura (bez side) = tekst dna jak przed krokiem 14.
    assert c.build_verdict(1, 6, 2) == c.build_verdict(1, 6, 2, side=c.SIDE_BOTTOM)
    assert "warunków dna" in c.build_verdict(1, 6, 2)


def test_verdict_no_buy_sell_language():
    for side in (c.SIDE_BOTTOM, c.SIDE_TOP, c.SIDE_MACRO):
        for met in (0, 3, 6):
            v = c.build_verdict(met, 6, 6, side=side).lower()
            assert "kup" not in v and "sprzedaj" not in v


# --------------------------------------------------------------------------- #
# evaluate_side — wejście dla aplikacji
# --------------------------------------------------------------------------- #
def test_evaluate_side_filters_and_labels_verdict():
    seed = mock.load_seed()
    cfg, reading = mock.seed_config(seed), mock.latest_reading(seed)

    bottom = c.evaluate_side(cfg, reading, c.SIDE_BOTTOM, graded_fng=True)
    assert bottom.count_met == 1 and bottom.count_active == 6
    assert "warunków dna" in bottom.verdict

    top = c.evaluate_side(cfg, reading, c.SIDE_TOP, graded_fng=True)
    assert top.count_met == 0 and top.count_active == 6
    # F&G (23 -> False) + months_since_halving (~25.4 -> False) są ocenialne od kroku 14
    assert top.count_evaluable == 2
    assert "warunków szczytu" in top.verdict

    macro = c.evaluate_side(cfg, reading, c.SIDE_MACRO)
    assert macro.count_met == 0 and macro.count_active == 4 and macro.count_evaluable == 0
    assert macro.verdict.startswith("Otoczenie makro")


def test_evaluate_side_equivalent_to_manual_composition():
    seed = mock.load_seed()
    cfg, reading = mock.seed_config(seed), mock.latest_reading(seed)
    a = c.evaluate_side(cfg, reading, c.SIDE_TOP, graded_fng=True)
    b = c.evaluate(c.filter_side(cfg, c.SIDE_TOP), reading, graded_fng=True, side=c.SIDE_TOP)
    assert a.count_met == b.count_met and a.verdict == b.verdict \
        and a.weighted_met == b.weighted_met
