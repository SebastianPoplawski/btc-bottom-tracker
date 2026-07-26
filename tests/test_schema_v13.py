"""
test_schema_v13.py — krok 13
Testy schematu warstwy sprzedaży + makro: kolumna `side` w configu,
filter_side, spójność seeda/CSV/bootstrapu/warehouse, plan sell_tranches.
Bez sieci/BQ — czyste funkcje i pliki repo.
Uruchom z korzenia repo:  python -m pytest tests/ -q
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import date

import pytest

_root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_root, "src", "logic"))
sys.path.insert(0, os.path.join(_root, "src", "ingestion"))
sys.path.insert(0, os.path.join(_root, "src", "warehouse"))
import composite as c  # noqa: E402
import mock  # noqa: E402

SEED_PATH = os.path.join(_root, "data", "seed_snapshot_2026-06-01.json")
CSV_CONFIG = os.path.join(_root, "data", "sheets_tab_config_thresholds.csv")
CSV_SELL = os.path.join(_root, "data", "sheets_tab_sell_tranches.csv")
DDL_PATH = os.path.join(_root, "src", "warehouse", "ddl.sql")


def load_seed():
    with open(SEED_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# filter_side / _clean_side
# --------------------------------------------------------------------------- #
def test_clean_side_defaults_to_bottom():
    assert c._clean_side(None) == c.SIDE_BOTTOM
    assert c._clean_side("") == c.SIDE_BOTTOM
    assert c._clean_side("  TOP ") == c.SIDE_TOP
    assert c._clean_side("Macro") == c.SIDE_MACRO
    assert c._clean_side("cokolwiek") == c.SIDE_BOTTOM  # nieznane -> bottom


def test_filter_side_without_side_column_is_backward_compatible():
    # Config sprzed kroku 13 (bez kolumny side) -> wszystko trafia do bottom.
    legacy = [{"indicator": "fear_greed", "operator": "lt", "threshold_value": 25,
               "threshold_value2": None, "weight": 0.5, "active": True, "description": ""}]
    assert len(c.filter_side(legacy, c.SIDE_BOTTOM)) == 1
    assert c.filter_side(legacy, c.SIDE_TOP) == []
    assert c.filter_side(legacy, c.SIDE_MACRO) == []


def test_filter_side_splits_seed_config():
    cfg = mock.seed_config(load_seed())
    bottom = c.filter_side(cfg, c.SIDE_BOTTOM)
    top = c.filter_side(cfg, c.SIDE_TOP)
    macro = c.filter_side(cfg, c.SIDE_MACRO)
    assert len(bottom) == 6
    assert len(top) == 6
    assert len(macro) == 4
    assert len(bottom) + len(top) + len(macro) == len(cfg)


def test_filter_side_accepts_dataframe():
    pd = pytest.importorskip("pandas")
    cfg = pd.DataFrame(mock.seed_config(load_seed()))
    assert len(c.filter_side(cfg, c.SIDE_TOP)) == 6


def test_filter_side_output_feeds_evaluate():
    cfg = mock.seed_config(load_seed())
    reading = mock.latest_reading(load_seed())
    res = c.evaluate(c.filter_side(cfg, c.SIDE_TOP), reading)
    assert res.count_active == 6


# --------------------------------------------------------------------------- #
# Regresja: framework DNA liczy się jak przed krokiem 13
# --------------------------------------------------------------------------- #
def test_seed_bottom_composite_unchanged():
    seed = load_seed()
    cfg = c.filter_side(mock.seed_config(seed), c.SIDE_BOTTOM)
    res = c.evaluate(cfg, mock.latest_reading(seed), graded_fng=True)
    assert res.count_met == seed["_meta"]["expected_composite_count"] == 1
    assert res.count_active == 6


def test_seed_top_composite():
    seed = load_seed()
    cfg = c.filter_side(mock.seed_config(seed), c.SIDE_TOP)
    res = c.evaluate(cfg, mock.latest_reading(seed))
    # F&G 23 NIE > 75 -> False; reszta null (pi_cycle/months computed dopiero w kroku 14).
    assert res.count_met == seed["_meta"]["expected_top_count"] == 0
    assert res.count_active == 6
    fng = next(r for r in res.indicators if r.indicator == "fear_greed")
    assert fng.met is False  # oceniony, nie brak danych


def test_seed_macro_composite():
    seed = load_seed()
    cfg = c.filter_side(mock.seed_config(seed), c.SIDE_MACRO)
    res = c.evaluate(cfg, mock.latest_reading(seed))
    assert res.count_met == seed["_meta"]["expected_macro_count"] == 0
    assert res.count_active == 4
    assert res.count_evaluable == 0  # wszystkie odczyty makro null w seedzie


def test_same_indicator_on_both_sides_evaluates_independently():
    cfg = [
        {"indicator": "fear_greed", "operator": "lt", "threshold_value": 25,
         "weight": 0.5, "active": True, "side": "bottom"},
        {"indicator": "fear_greed", "operator": "gt", "threshold_value": 75,
         "weight": 0.5, "active": True, "side": "top"},
    ]
    reading = {"fear_greed": 80}
    bottom = c.evaluate(c.filter_side(cfg, "bottom"), reading)
    top = c.evaluate(c.filter_side(cfg, "top"), reading)
    assert bottom.count_met == 0
    assert top.count_met == 1


# --------------------------------------------------------------------------- #
# Seed: nowe pola odczytu + transze sprzedaży
# --------------------------------------------------------------------------- #
def test_seed_reading_has_v13_fields():
    reading = mock.latest_reading(load_seed())
    for field in ("ma_111d", "ma_350d", "halving_date", "fed_funds_rate",
                  "fed_funds_delta_3m", "dxy_proxy", "dxy_delta_3m",
                  "m2_yoy", "etf_flows_usd_7d"):
        assert field in reading, f"brak pola {field} w seedzie"
    assert reading["halving_date"] == date(2024, 4, 20)  # parsowane do date


def test_mock_sell_df():
    df = mock.sell_df(load_seed())
    assert len(df) == 5
    assert set(df["status"]) == {"pending"}
    # nie zgadujemy rynku: progi cen puste w seedzie
    assert df["trigger_price_usd"].isna().all()


def test_labels_for_new_indicators():
    for key in ("pi_cycle_crossed", "months_since_halving", "fed_funds_delta_3m",
                "dxy_delta_3m", "m2_yoy", "etf_flows_usd_7d"):
        assert key in c.LABELS


# --------------------------------------------------------------------------- #
# Spójność plików: CSV <-> seed <-> bootstrap <-> warehouse <-> ddl
# --------------------------------------------------------------------------- #
def _csv_rows(path):
    with open(path, "r", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_csv_config_matches_seed_config():
    csv_rows = _csv_rows(CSV_CONFIG)
    seed_cfg = mock.seed_config(load_seed())
    assert {(r["indicator"], r["side"]) for r in csv_rows} \
        == {(r["indicator"], r["side"]) for r in seed_cfg}
    # unikalność per (indicator, side)
    keys = [(r["indicator"], r["side"]) for r in csv_rows]
    assert len(keys) == len(set(keys))


def test_bootstrap_config_matches_csv():
    sys.path.insert(0, os.path.join(_root, "scripts"))
    import bootstrap_sheet as bs
    assert bs.CONFIG_HEADER[-1] == "side"
    boot_keys = {(row[0], row[-1]) for row in bs.CONFIG_ROWS}
    csv_keys = {(r["indicator"], r["side"]) for r in _csv_rows(CSV_CONFIG)}
    assert boot_keys == csv_keys
    # wagi mvrv/nupl w bootstrapie = 0.5 (naprawa rozjazdu sprzed kroku 11)
    for row in bs.CONFIG_ROWS:
        if row[0] in ("mvrv_z_score", "nupl"):
            assert row[4] == "0.5"


def test_warehouse_fields_cover_v13():
    import bigquery_client as wh
    import sheets
    reading_fields = {name for name, _ in wh._READING_FIELDS}
    v13 = {name for name, _ in wh._V13_COLUMNS}
    assert v13 <= reading_fields
    assert v13 <= wh._SELECTABLE
    # sheets.UPSERT_FIELDS musi pokrywać pola upsertu warehouse 1:1
    assert set(sheets.UPSERT_FIELDS) == reading_fields
    assert sheets.TAB_SELL == "sell_tranches"
    assert wh.SELL_TABLE == "sell_tranches_ext"


def test_ddl_contains_v13_schema():
    with open(DDL_PATH, "r", encoding="utf-8") as fh:
        ddl = fh.read()
    for col in ("ma_111d", "ma_350d", "halving_date", "fed_funds_delta_3m",
                "dxy_delta_3m", "m2_yoy", "etf_flows_usd_7d"):
        assert col in ddl
    assert "sell_tranches_ext" in ddl
    assert "config_thresholds!A1:H100" in ddl  # external z kolumną side


def test_csv_sell_tranches_layout():
    rows = _csv_rows(CSV_SELL)
    assert len(rows) == 5
    assert list(rows[0].keys()) == ["tranche_id", "trigger_price_usd", "allocation_pct",
                                    "min_top_signals", "status", "executed_date",
                                    "executed_price_usd", "note"]
