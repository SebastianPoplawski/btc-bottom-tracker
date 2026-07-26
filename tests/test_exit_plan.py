"""
test_exit_plan.py — krok 16
Czysta logika planu transz SPRZEDAŻY (exit_plan.py) — lustro test_dca.py.
Bez sieci/BQ. Uruchom z korzenia repo:  python -m pytest tests/ -q
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

_root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_root, "src", "logic"))
sys.path.insert(0, os.path.join(_root, "src", "ingestion"))
import exit_plan as ep  # noqa: E402


def plan():
    """Przykładowy plan wyjścia: 3 transze rosnąco, po 25% pozycji."""
    return [
        {"tranche_id": 1, "trigger_price_usd": 150000, "allocation_pct": 25,
         "min_top_signals": None, "status": "pending", "note": ""},
        {"tranche_id": 2, "trigger_price_usd": 175000, "allocation_pct": 25,
         "min_top_signals": 3, "status": "pending", "note": ""},
        {"tranche_id": 3, "trigger_price_usd": 200000, "allocation_pct": 25,
         "min_top_signals": 4, "status": "pending", "note": ""},
    ]


# --------------------------------------------------------------------------- #
# price_reached — kierunek LUSTRZANY do DCA (>= progu)
# --------------------------------------------------------------------------- #
def test_price_reached_upwards():
    st = ep.compute_exit_state(plan(), current_price=180000, top_count_met=5)
    by_id = {t.tranche_id: t for t in st.tranches}
    assert by_id[1].price_reached is True    # 180k >= 150k
    assert by_id[2].price_reached is True    # 180k >= 175k
    assert by_id[3].price_reached is False   # 180k < 200k


def test_price_boundary_equal_is_reached():
    st = ep.compute_exit_state(plan(), current_price=150000, top_count_met=0)
    assert {t.tranche_id: t.price_reached for t in st.tranches}[1] is True


def test_no_price_all_unknown():
    st = ep.compute_exit_state(plan(), current_price=None, top_count_met=2)
    assert all(t.price_reached is None for t in st.tranches)
    assert st.conditions_met_now == []
    assert any("Brak bieżącej ceny" in w for w in st.warnings)


# --------------------------------------------------------------------------- #
# signals_ok — licznik sygnałów SZCZYTU
# --------------------------------------------------------------------------- #
def test_signals_gate():
    st = ep.compute_exit_state(plan(), current_price=250000, top_count_met=3)
    by_id = {t.tranche_id: t for t in st.tranches}
    assert by_id[1].conditions_met is True    # bez bramki sygnałowej
    assert by_id[2].conditions_met is True    # 3 >= 3
    assert by_id[3].conditions_met is False   # 3 < 4
    assert "za mało sygnałów szczytu" in by_id[3].state_label


def test_signals_unknown_blocks_gated_tranche():
    st = ep.compute_exit_state(plan(), current_price=250000, top_count_met=None)
    by_id = {t.tranche_id: t for t in st.tranches}
    assert by_id[1].conditions_met is True    # brak bramki -> cena wystarcza
    assert by_id[2].conditions_met is False   # bramka jest, licznik nieznany
    assert by_id[2].signals_ok is None


# --------------------------------------------------------------------------- #
# statusy / agregaty w % pozycji
# --------------------------------------------------------------------------- #
def test_executed_and_skipped_never_conditions_met():
    rows = plan()
    rows[0]["status"] = "executed"
    rows[0]["executed_date"] = "2026-05-01"
    rows[0]["executed_price_usd"] = 152000
    rows[1]["status"] = "skipped"
    st = ep.compute_exit_state(rows, current_price=300000, top_count_met=6)
    by_id = {t.tranche_id: t for t in st.tranches}
    assert by_id[1].conditions_met is False and by_id[1].state_label == "zrealizowana"
    assert by_id[1].executed_date == date(2026, 5, 1)
    assert by_id[2].conditions_met is False and by_id[2].state_label == "pominięta"
    assert by_id[3].conditions_met is True
    assert st.executed_count == 1 and st.pending_count == 1
    assert st.executed_alloc_pct == 25 and st.pending_alloc_pct == 25


def test_total_alloc_pct_and_over_100_warning():
    rows = plan()
    for r in rows:
        r["allocation_pct"] = 40  # 3 x 40 = 120% pozycji
    st = ep.compute_exit_state(rows, current_price=None)
    assert st.total_alloc_pct == 120
    assert any("> 100% pozycji" in w for w in st.warnings)


def test_empty_plan_totals_none():
    st = ep.compute_exit_state([], current_price=100000, top_count_met=0)
    assert st.tranches == [] and st.total_alloc_pct is None
    assert st.next_trigger is None and st.conditions_met_now == []


# --------------------------------------------------------------------------- #
# next_trigger — najbliższy próg W GÓRĘ (lustro DCA)
# --------------------------------------------------------------------------- #
def test_next_trigger_is_lowest_unreached():
    st = ep.compute_exit_state(plan(), current_price=160000, top_count_met=0)
    assert st.next_trigger is not None and st.next_trigger.tranche_id == 2  # 175k (nie 200k)


def test_next_trigger_without_price_shows_lowest_pending():
    st = ep.compute_exit_state(plan(), current_price=None)
    assert st.next_trigger is not None and st.next_trigger.tranche_id == 1


def test_next_trigger_none_when_all_reached():
    st = ep.compute_exit_state(plan(), current_price=999999, top_count_met=6)
    assert st.next_trigger is None


# --------------------------------------------------------------------------- #
# seed / dataframe / odporność
# --------------------------------------------------------------------------- #
def test_seed_sell_tranches_all_pending_no_triggers():
    import mock
    st = ep.compute_exit_state(mock.sell_df(), current_price=100000, top_count_met=0)
    assert st.pending_count == 5
    assert st.conditions_met_now == []
    assert all("brak progu ceny" in t.state_label for t in st.tranches)


def test_accepts_dataframe_and_locale_numbers():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame([{"tranche_id": "1", "trigger_price_usd": "150000,5",
                        "allocation_pct": "12,5", "min_top_signals": None,
                        "status": "PENDING", "note": None}])
    st = ep.compute_exit_state(df, current_price=200000)
    t = st.tranches[0]
    assert t.trigger_price_usd == 150000.5 and t.allocation_pct == 12.5
    assert t.status == "pending" and t.conditions_met is True


def test_unknown_status_warns_but_does_not_crash():
    rows = [{"tranche_id": 1, "trigger_price_usd": 1, "status": "cooked"}]
    st = ep.compute_exit_state(rows, current_price=2)
    assert any("nieznany status" in w for w in st.warnings)
    assert st.tranches[0].conditions_met is False  # nie-pending nie bywa gotowa


def test_disclaimer_and_no_advice_language():
    st = ep.compute_exit_state(plan(), current_price=250000, top_count_met=6)
    assert st.disclaimer == ep.DISCLAIMER
    for t in st.tranches:
        low = t.state_label.lower()
        assert "sprzedaj" not in low and "kup" not in low
