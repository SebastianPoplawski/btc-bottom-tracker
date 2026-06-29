"""
test_backfill.py — krok 10
==========================
Bez sieci. Dwa obszary:
  (a) bigquery_client.ensure_readings_table — DDL zawiera CREATE TABLE IF NOT EXISTS,
      nazwe tabeli i komplet kolumn (SQL przechwycony przez monkeypatch execute_sql).
  (b) scripts/backfill_history.backfill — upsert woła sie raz na wiersz z poprawnym
      reading_date, a days_since_ath jest doliczane z ath_date gdy puste.

Uruchom z korzenia repo:
    python -m pytest tests/ -q
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pandas as pd
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "warehouse"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ingestion"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import bigquery_client as bq   # noqa: E402
import backfill_history as bh  # noqa: E402


# --------------------------------------------------------------------------- #
# (a) ensure_readings_table — DDL
# --------------------------------------------------------------------------- #
_READING_COLUMNS = [
    "reading_date", "price_usd", "mvrv_z_score", "nupl", "ma_200w",
    "whale_accumulating", "whale_ratio", "fear_greed", "days_since_ath",
    "ath_date", "notes", "inserted_at", "updated_at",
]


def test_ensure_readings_table_emits_create_if_not_exists(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(bq, "execute_sql", lambda sql: captured.append(sql))
    monkeypatch.setattr(bq, "PROJECT_ID", "test-proj")

    bq.ensure_readings_table()

    assert len(captured) == 1
    sql = captured[0]
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert bq.TABLE_READINGS in sql  # indicator_readings
    assert "test-proj" in sql and bq.DATASET in sql
    for col in _READING_COLUMNS:
        assert col in sql, f"brak kolumny '{col}' w DDL"
    # inserted_at/updated_at jako TIMESTAMP (1:1 z ddl.sql)
    assert "TIMESTAMP" in sql


# --------------------------------------------------------------------------- #
# (b) logika backfillu
# --------------------------------------------------------------------------- #
def _fake_bundle() -> types.SimpleNamespace:
    # Wiersz A: ath_date jest, days_since_ath PUSTE -> ma sie doliczyc.
    # Wiersz B: days_since_ath podane recznie, ath_date puste -> bez zmian.
    df = pd.DataFrame(
        {
            "reading_date": [date(2026, 2, 1), date(2026, 1, 1)],
            "mvrv_z_score": [0.34, 0.20],
            "ath_date": [date(2025, 10, 6), pd.NA],
            "days_since_ath": [pd.NA, 50],
        }
    )
    validation = types.SimpleNamespace(warnings=[])
    return types.SimpleNamespace(readings=df, validation=validation)


def test_backfill_upserts_once_per_row_and_computes_days_since_ath(monkeypatch):
    calls: list[tuple] = []

    monkeypatch.setattr(bh.sheets, "load_all", lambda *a, **k: _fake_bundle())
    monkeypatch.setattr(bh.wh, "ensure_dataset", lambda: None)
    monkeypatch.setattr(bh.wh, "ensure_readings_table", lambda: None)
    monkeypatch.setattr(
        bh.wh, "upsert_reading",
        lambda reading_date, values: calls.append((reading_date, values)) or 1,
    )

    processed, affected = bh.backfill(dry_run=False)

    # Jeden upsert na wiersz.
    assert processed == 2
    assert affected == 2
    assert len(calls) == 2

    # Poprawne reading_date, w kolejnosci wierszy.
    assert calls[0][0] == date(2026, 2, 1)
    assert calls[1][0] == date(2026, 1, 1)

    # Wiersz A: days_since_ath doliczone z ath_date (2026-02-01 - 2025-10-06 = 118).
    assert calls[0][1]["days_since_ath"] == 118
    # Wiersz B: wartosc reczna nietknieta.
    assert calls[1][1]["days_since_ath"] == 50


def test_backfill_dry_run_does_not_write(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(bh.sheets, "load_all", lambda *a, **k: _fake_bundle())
    monkeypatch.setattr(
        bh.wh, "upsert_reading",
        lambda reading_date, values: calls.append((reading_date, values)) or 1,
    )
    # Tabela NIE moze byc tworzona w dry-run.
    def _boom():
        raise AssertionError("dry_run nie powinien tworzyc niczego")
    monkeypatch.setattr(bh.wh, "ensure_dataset", _boom)
    monkeypatch.setattr(bh.wh, "ensure_readings_table", _boom)

    processed, affected = bh.backfill(dry_run=True)

    assert processed == 2
    assert affected == 0
    assert calls == []
