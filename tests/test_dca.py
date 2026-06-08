"""
test_dca.py — krok 04
Testy logiki DCA (src/logic/dca.py). Bez sieci/BQ — czyste funkcje.
Uruchom z korzenia repo:  python -m pytest tests/ -q
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "logic"))
import dca as d  # noqa: E402


def tranches():
    return [
        {"tranche_id": 1, "trigger_price_usd": 70000, "allocation_usd": 1000, "allocation_pct": 20,
         "min_signals_required": None, "status": "executed", "executed_date": "2026-05-20",
         "executed_price_usd": 69500, "note": ""},
        {"tranche_id": 2, "trigger_price_usd": 65000, "allocation_usd": 1000, "allocation_pct": 20,
         "min_signals_required": 2, "status": "pending", "executed_date": None,
         "executed_price_usd": None, "note": ""},
        {"tranche_id": 3, "trigger_price_usd": 60000, "allocation_usd": 1000, "allocation_pct": 20,
         "min_signals_required": 4, "status": "pending", "executed_date": None,
         "executed_price_usd": None, "note": ""},
        {"tranche_id": 4, "trigger_price_usd": 55000, "allocation_usd": 2000, "allocation_pct": 40,
         "min_signals_required": None, "status": "pending", "executed_date": None,
         "executed_price_usd": None, "note": "dno docelowe"},
    ]


def _by_id(state, tid):
    return next(t for t in state.tranches if t.tranche_id == tid)


# --------------------------------------------------------------------------- #
# price_reached
# --------------------------------------------------------------------------- #
def test_price_reached_boundary():
    s = d.compute_dca_state(tranches(), current_price=65000, count_met=3)
    assert _by_id(s, 2).price_reached is True       # 65000 <= 65000 (granica)
    assert _by_id(s, 3).price_reached is False      # 65000 > 60000
    assert _by_id(s, 4).price_reached is False


def test_price_unknown_gives_none_and_warning():
    s = d.compute_dca_state(tranches(), current_price=None, count_met=3)
    assert _by_id(s, 2).price_reached is None
    assert all(t.conditions_met is False for t in s.tranches)
    assert any("Brak bieżącej ceny" in w for w in s.warnings)


def test_price_zero_treated_as_unknown_via_app_layer():
    # compute_dca_state dostaje już None (konwersję 0->None robi app.py),
    # ale i tak: 0 jako cena oznacza, że żaden próg nie jest 'reached' sensownie.
    s = d.compute_dca_state(tranches(), current_price=0, count_met=3)
    # 0 <= każdy trigger -> price_reached True; to świadoma granica (app przekazuje None dla 0)
    assert _by_id(s, 2).price_reached is True


# --------------------------------------------------------------------------- #
# signals_ok + conditions_met
# --------------------------------------------------------------------------- #
def test_signals_gate():
    s = d.compute_dca_state(tranches(), current_price=58000, count_met=3)
    t2 = _by_id(s, 2)   # trigger 65000, min 2, count 3 -> ok, cena osiągnięta
    t3 = _by_id(s, 3)   # trigger 60000, min 4, count 3 -> za mało sygnałów
    assert t2.price_reached is True and t2.signals_ok is True and t2.conditions_met is True
    assert t3.price_reached is True and t3.signals_ok is False and t3.conditions_met is False


def test_no_signal_gate_means_price_only():
    s = d.compute_dca_state(tranches(), current_price=54000, count_met=0)
    t4 = _by_id(s, 4)   # min None -> brak bramki sygnałowej
    assert t4.signals_ok is None
    assert t4.price_reached is True
    assert t4.conditions_met is True


def test_count_met_none_blocks_gated_tranche():
    s = d.compute_dca_state(tranches(), current_price=58000, count_met=None)
    t2 = _by_id(s, 2)   # ma bramkę (min 2), ale count nieznany
    assert t2.signals_ok is None
    assert t2.conditions_met is False


def test_executed_and_skipped_never_conditions_met():
    rows = tranches()
    rows[1]["status"] = "skipped"
    s = d.compute_dca_state(rows, current_price=50000, count_met=6)
    assert _by_id(s, 1).conditions_met is False   # executed
    assert _by_id(s, 2).conditions_met is False   # skipped


# --------------------------------------------------------------------------- #
# Agregaty
# --------------------------------------------------------------------------- #
def test_aggregates():
    s = d.compute_dca_state(tranches(), current_price=64000, count_met=2)
    assert s.executed_count == 1
    assert s.pending_count == 3
    assert s.executed_alloc_usd == pytest.approx(1000)
    assert s.pending_alloc_usd == pytest.approx(4000)
    assert s.total_alloc_usd == pytest.approx(5000)


def test_conditions_met_now_collects_ready_pending():
    s = d.compute_dca_state(tranches(), current_price=64000, count_met=2)
    # cena 64000: t2 (65000, min2, count2) -> gotowa; t3/t4 cena nieosiągnięta
    ids = {t.tranche_id for t in s.conditions_met_now}
    assert ids == {2}


# --------------------------------------------------------------------------- #
# next_trigger
# --------------------------------------------------------------------------- #
def test_next_trigger_is_highest_not_reached_below_price():
    s = d.compute_dca_state(tranches(), current_price=64000, count_met=2)
    # nieosiągnięte pending: 60000, 55000 -> najbliższy w dół = 60000
    assert s.next_trigger is not None
    assert s.next_trigger.trigger_price_usd == pytest.approx(60000)


def test_next_trigger_when_price_unknown_is_highest_pending():
    s = d.compute_dca_state(tranches(), current_price=None, count_met=2)
    assert s.next_trigger.trigger_price_usd == pytest.approx(65000)


# --------------------------------------------------------------------------- #
# Wejście jako DataFrame + braki
# --------------------------------------------------------------------------- #
def test_accepts_dataframe():
    pd = pytest.importorskip("pandas")
    s = d.compute_dca_state(pd.DataFrame(tranches()), current_price=58000, count_met=3)
    assert s.pending_count == 3
    assert _by_id(s, 2).conditions_met is True


def test_empty_input():
    s = d.compute_dca_state([], current_price=60000, count_met=3)
    assert s.tranches == []
    assert s.total_alloc_usd is None
    assert s.next_trigger is None


def test_missing_allocation_total_none():
    rows = [{"tranche_id": 1, "trigger_price_usd": 60000, "status": "pending"}]
    s = d.compute_dca_state(rows, current_price=70000, count_met=1)
    assert s.total_alloc_usd is None
    assert _by_id(s, 1).price_reached is False      # 70000 > 60000


def test_disclaimer_present():
    s = d.compute_dca_state(tranches(), current_price=60000, count_met=3)
    assert s.disclaimer == d.DISCLAIMER


def test_state_labels_are_descriptive_not_advice():
    s = d.compute_dca_state(tranches(), current_price=64000, count_met=2)
    labels = " ".join(t.state_label for t in s.tranches).lower()
    # opisowe, bez „kup/sprzedaj"
    assert "kup" not in labels and "sprzedaj" not in labels
