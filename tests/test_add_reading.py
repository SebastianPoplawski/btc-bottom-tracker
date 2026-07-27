"""
test_add_reading.py — krok 19
Czysta logika planowania wiersza w add_reading.py: upsert po reading_date,
auto-przenoszenie ath_date/halving_date przy dopisywaniu, flagi v13.
Bez sieci — nagłówki/wiersze inline. Uruchom z korzenia repo:
    python -m pytest tests/ -q
"""
from __future__ import annotations

import argparse
import os
import sys

_root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_root, "scripts"))
import add_reading as ar  # noqa: E402

# Nagłówek jak w realnym arkuszu po upgrade v13 (nowe kolumny NA KOŃCU, za notes).
HEADER = ["reading_date", "price_usd", "mvrv_z_score", "nupl", "ma_200w",
          "whale_accumulating", "whale_ratio", "fear_greed", "days_since_ath",
          "ath_date", "notes", "ma_111d", "ma_350d", "halving_date",
          "fed_funds_rate", "fed_funds_delta_3m", "dxy_proxy", "dxy_delta_3m",
          "m2_yoy", "etf_flows_usd_7d"]


def sheet_values():
    """2 wiersze danych; najnowszy (2026-06-09) ma ath_date i halving_date."""
    row_old = [""] * len(HEADER)
    row_old[0] = "2026-06-01"
    row_old[7] = "23"
    row_new = [""] * len(HEADER)
    row_new[0] = "2026-06-09"
    row_new[2] = "0.34"
    row_new[3] = "0.12"
    row_new[9] = "2025-10-06"      # ath_date
    row_new[13] = "2024-04-20"     # halving_date
    return [HEADER, row_old, row_new]


def _ns(**kw):
    base = dict(date="2026-07-27", mvrv=None, nupl=None, whale=None,
                whale_ratio=None, days_ath=None, ath_date=None,
                halving_date=None, etf_flows=None, notes=None)
    base.update(kw)
    return argparse.Namespace(**base)


# --------------------------------------------------------------------------- #
# build_values — nowe flagi v13
# --------------------------------------------------------------------------- #
def test_build_values_v13_flags():
    out = ar.build_values(_ns(halving_date="2024-04-20", etf_flows="-230000000"))
    assert out["halving_date"] == "2024-04-20"
    assert out["etf_flows_usd_7d"] == "-230000000"


def test_build_values_etf_flows_locale_comma():
    out = ar.build_values(_ns(etf_flows="-1,5"))
    assert out["etf_flows_usd_7d"] == "-1.5"


def test_auto_fields_include_v13():
    for f in ("ma_111d", "ma_350d", "fed_funds_rate", "dxy_proxy", "m2_yoy"):
        assert f in ar.AUTO_FIELDS


# --------------------------------------------------------------------------- #
# plan_row — carry-forward przy dopisywaniu
# --------------------------------------------------------------------------- #
def test_new_row_carries_cycle_dates_from_latest():
    provided = {"reading_date": "2026-07-27", "mvrv_z_score": "0.31"}
    found, base, carried = ar.plan_row(HEADER, sheet_values(), provided)
    assert found is None                              # nowy wiersz
    assert base[9] == "2025-10-06"                    # ath_date przeniesione
    assert base[13] == "2024-04-20"                   # halving_date przeniesione
    assert carried == {"ath_date": "2025-10-06", "halving_date": "2024-04-20"}
    assert base[2] == "0.31" and base[0] == "2026-07-27"
    assert base[3] == ""                              # nupl NIE przenoszony (tylko daty cyklu)


def test_carry_uses_latest_by_date_not_last_row():
    # Najnowszy wiersz celowo NIE jest ostatni fizycznie.
    values = sheet_values()
    values.append(values.pop(2))          # 2026-06-09 na koncu
    values[1], values[2] = values[2], values[1]  # przetasowanie
    provided = {"reading_date": "2026-07-27"}
    _, base, carried = ar.plan_row(HEADER, values, provided)
    assert carried.get("halving_date") == "2024-04-20"


def test_explicit_value_wins_over_carry():
    provided = {"reading_date": "2026-07-27", "ath_date": "2025-11-01"}
    _, base, carried = ar.plan_row(HEADER, sheet_values(), provided)
    assert base[9] == "2025-11-01"                    # jawne wygrywa
    assert "ath_date" not in carried
    assert carried == {"halving_date": "2024-04-20"}  # druga data dalej przeniesiona


def test_no_carry_flag_disables_forwarding():
    provided = {"reading_date": "2026-07-27"}
    _, base, carried = ar.plan_row(HEADER, sheet_values(), provided, carry=False)
    assert base[9] == "" and base[13] == "" and carried == {}


def test_update_existing_row_no_carry_and_preserves_cells():
    provided = {"reading_date": "2026-06-09", "nupl": "0.15"}
    found, base, carried = ar.plan_row(HEADER, sheet_values(), provided)
    assert found == 3                                 # 1-based: naglowek=1, wiersz 2026-06-09=3
    assert carried == {}                              # aktualizacja: nic nie przenosimy
    assert base[3] == "0.15"                          # nadpisane
    assert base[2] == "0.34"                          # istniejace zachowane
    assert base[13] == "2024-04-20"                   # halving zostal jak byl


def test_carry_skips_when_no_previous_data():
    provided = {"reading_date": "2026-07-27"}
    _, base, carried = ar.plan_row(HEADER, [HEADER], provided)
    assert carried == {} and base[0] == "2026-07-27"


def test_legacy_header_without_v13_columns_still_works():
    # Arkusz sprzed v13 (bez halving_date) — carry przenosi tylko ath_date.
    header = HEADER[:11]  # do notes
    row = [""] * len(header)
    row[0] = "2026-06-09"
    row[9] = "2025-10-06"
    _, base, carried = ar.plan_row(header, [header, row], {"reading_date": "2026-07-27"})
    assert carried == {"ath_date": "2025-10-06"}
