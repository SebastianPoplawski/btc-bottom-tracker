"""
test_alerts.py — krok 20
Czysta logika alertów: snapshot z odczytu, diff dzień/dzień, payload issue.
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
import alerts  # noqa: E402
import composite as c  # noqa: E402
import mock  # noqa: E402


def seed_config():
    return mock.seed_config()


def reading(**over):
    base = {
        "reading_date": date(2026, 7, 27), "price_usd": 65303.0, "ma_200w": 63330.0,
        "mvrv_z_score": 0.34, "nupl": 0.12, "whale_accumulating": None,
        "fear_greed": 30, "ath_date": date(2025, 10, 6),
        "ma_111d": 70069.0, "ma_350d": 85871.0, "halving_date": date(2024, 4, 20),
    }
    base.update(over)
    return base


def dca_rows():
    return [
        {"tranche_id": 1, "trigger_price_usd": 70000, "status": "pending"},
        {"tranche_id": 2, "trigger_price_usd": 67500, "status": "pending"},
        {"tranche_id": 3, "trigger_price_usd": 55000, "status": "pending"},
    ]


def sell_rows():
    return [
        {"tranche_id": 1, "trigger_price_usd": 150000, "allocation_pct": 25,
         "min_top_signals": None, "status": "pending"},
    ]


# --------------------------------------------------------------------------- #
# snapshot
# --------------------------------------------------------------------------- #
def test_snapshot_counts_and_ready_sets():
    snap = alerts.snapshot(seed_config(), reading(), dca_rows(), sell_rows())
    assert snap.reading_date == date(2026, 7, 27)
    # dno: tylko ratio 65303/63330=1.031 <= 1.05 spełniony
    assert snap.bottom_met == 1 and snap.bottom_active == 6
    assert snap.top_met == 0 and snap.top_active == 6
    # DCA: cena 65303 <= 70000 i <= 67500 (bez bramek sygnałowych)
    assert snap.dca_ready == frozenset({1, 2})
    # sprzedaż: 65303 < 150000
    assert snap.exit_ready == frozenset()


def test_snapshot_without_tranche_frames():
    snap = alerts.snapshot(seed_config(), reading())
    assert snap.dca_ready == frozenset() and snap.exit_ready == frozenset()


# --------------------------------------------------------------------------- #
# build_alerts — diff
# --------------------------------------------------------------------------- #
def _snap(**over):
    base = dict(reading_date=date(2026, 7, 27), bottom_met=1, bottom_active=6,
                top_met=0, top_active=6, price_usd=65303.0,
                dca_ready=frozenset({1, 2}), exit_ready=frozenset())
    base.update(over)
    return alerts.Snapshot(**base)


def test_no_change_no_alerts():
    assert alerts.build_alerts(_snap(), _snap(reading_date=date(2026, 7, 26))) == []


def test_first_run_without_prev_is_silent():
    assert alerts.build_alerts(_snap(), None) == []


def test_bottom_count_increase_alert():
    msgs = alerts.build_alerts(_snap(bottom_met=2), _snap(bottom_met=1))
    assert len(msgs) == 1 and "DNA WZRÓSŁ: 1 -> 2" in msgs[0]


def test_bottom_count_decrease_also_alerts():
    msgs = alerts.build_alerts(_snap(bottom_met=1), _snap(bottom_met=2))
    assert len(msgs) == 1 and "SPADŁ: 2 -> 1" in msgs[0]


def test_top_count_change_alert():
    msgs = alerts.build_alerts(_snap(top_met=1), _snap())
    assert len(msgs) == 1 and "SZCZYTU WZRÓSŁ: 0 -> 1" in msgs[0]


def test_new_ready_tranches_alert_only_new_ones():
    today = _snap(dca_ready=frozenset({1, 2, 3}), exit_ready=frozenset({1}))
    prev = _snap(dca_ready=frozenset({1, 2}), exit_ready=frozenset())
    msgs = alerts.build_alerts(today, prev)
    assert any("transze DCA" in m and "#3" in m and "#1," not in m for m in msgs)
    assert any("SPRZEDAŻY" in m and "#1" in m for m in msgs)


def test_tranche_leaving_ready_set_is_not_alerted():
    # transza wypada z ready (np. cena odbiła) -> celowo cisza (alarmujemy NOWE)
    msgs = alerts.build_alerts(_snap(dca_ready=frozenset({1})),
                               _snap(dca_ready=frozenset({1, 2})))
    assert msgs == []


def test_multiple_changes_multiple_messages():
    today = _snap(bottom_met=3, top_met=1, dca_ready=frozenset({1, 2, 3}))
    prev = _snap(bottom_met=1, top_met=0, dca_ready=frozenset({1, 2}))
    assert len(alerts.build_alerts(today, prev)) == 3


# --------------------------------------------------------------------------- #
# issue_payload
# --------------------------------------------------------------------------- #
def test_issue_payload_single_alert_title_and_body():
    msgs = alerts.build_alerts(_snap(bottom_met=2), _snap(bottom_met=1, reading_date=date(2026, 7, 26)))
    p = alerts.issue_payload(msgs, _snap(bottom_met=2),
                             _snap(bottom_met=1, reading_date=date(2026, 7, 26)),
                             app_url="https://example.app")
    assert p["title"].startswith("ALERT 2026-07-27:")
    assert "1 -> 2" in p["body"] and "dno **2/6**" in p["body"]
    assert "https://example.app" in p["body"]
    assert alerts.DISCLAIMER in p["body"]
    assert p["labels"] == ["alert"]
    low = p["body"].lower()
    assert "kup teraz" not in low and "sprzedaj teraz" not in low


def test_issue_payload_many_alerts_compact_title():
    msgs = ["a", "b", "c"]
    p = alerts.issue_payload(msgs, _snap())
    assert "3 zmiany" in p["title"] and len(p["title"]) <= 100


# --------------------------------------------------------------------------- #
# spójność z UI: snapshot używa evaluate_side (te same liczby co dashboard)
# --------------------------------------------------------------------------- #
def test_snapshot_matches_evaluate_side():
    cfg, r = seed_config(), reading()
    snap = alerts.snapshot(cfg, r)
    assert snap.bottom_met == c.evaluate_side(cfg, r, c.SIDE_BOTTOM).count_met
    assert snap.top_met == c.evaluate_side(cfg, r, c.SIDE_TOP).count_met
