"""
migrate_13.py — migracja schematu do v13 (warstwa sprzedaży + makro)
====================================================================
Co robi (idempotentnie, w tej kolejności):
  1. `indicator_readings` (native): dokłada nowe kolumny
     (ma_111d, ma_350d, halving_date, fed_funds_*, dxy_*, m2_yoy,
     etf_flows_usd_7d) — przez `bigquery_client.ensure_readings_table()`
     (CREATE IF NOT EXISTS + ALTER ADD COLUMN IF NOT EXISTS).
     UWAGA: to samo dzieje się automatycznie przy każdym zapisie ingested —
     ten krok jest tu tylko po to, żeby zrobić migrację świadomie i od razu.
  2. `config_thresholds_ext` (external/Sheets): CREATE OR REPLACE z kolumną
     `side` (zakres A1:H100).
  3. `sell_tranches_ext` (external/Sheets): CREATE OR REPLACE (A1:H200).

WYMAGANA KOLEJNOŚĆ: najpierw arkusz, potem external DDL!
  python scripts/bootstrap_sheet.py     # dokłada kolumnę side + zakładkę sell_tranches
  python scripts/migrate_13.py          # dopiero potem ten skrypt

Poświadczenia i konfiguracja jak reszta projektu (env / plik klucza SA):
  GOOGLE_APPLICATION_CREDENTIALS lub GCP_SERVICE_ACCOUNT_JSON,
  GCP_PROJECT_ID, BQ_DATASET, BQ_LOCATION, GOOGLE_SHEET_ID.

Uruchomienie (Windows / PowerShell, z korzenia repo, w aktywnym .venv):
    $env:GOOGLE_APPLICATION_CREDENTIALS = "C:\\sciezka\\do\\klucz.json"
    $env:GCP_PROJECT_ID = "btc-bottom-tracker-498120"
    python scripts\\migrate_13.py            # wykonuje migrację
    python scripts\\migrate_13.py --dry-run  # tylko pokazuje SQL
"""

from __future__ import annotations

import argparse
import os
import sys

# Importy dzialaja przy uruchomieniu z korzenia repo (scripts/migrate_13.py).
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.join(_here, "..")
sys.path.insert(0, os.path.join(_root, "src", "warehouse"))
import bigquery_client as wh  # type: ignore  # noqa: E402

DEFAULT_SHEET_ID = "19GCtFyNBKBEj3-jWOLYfNBEd-7jVIXigkDJBGW0vHRY"


def _sheet_uri() -> str:
    sheet_id = os.getenv("GOOGLE_SHEET_ID", DEFAULT_SHEET_ID)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


def config_ext_sql() -> str:
    return f"""
    CREATE OR REPLACE EXTERNAL TABLE `{wh.PROJECT_ID}.{wh.DATASET}.config_thresholds_ext`
    (
      indicator        STRING,
      operator         STRING,
      threshold_value  NUMERIC,
      threshold_value2 NUMERIC,
      weight           NUMERIC,
      active           BOOL,
      description      STRING,
      side             STRING
    )
    OPTIONS (
      format            = 'GOOGLE_SHEETS',
      uris              = ['{_sheet_uri()}'],
      sheet_range       = 'config_thresholds!A1:H100',
      skip_leading_rows = 1
    )
    """


def sell_ext_sql() -> str:
    return f"""
    CREATE OR REPLACE EXTERNAL TABLE `{wh.PROJECT_ID}.{wh.DATASET}.sell_tranches_ext`
    (
      tranche_id         INT64,
      trigger_price_usd  NUMERIC,
      allocation_pct     NUMERIC,
      min_top_signals    INT64,
      status             STRING,
      executed_date      DATE,
      executed_price_usd NUMERIC,
      note               STRING
    )
    OPTIONS (
      format            = 'GOOGLE_SHEETS',
      uris              = ['{_sheet_uri()}'],
      sheet_range       = 'sell_tranches!A1:H200',
      skip_leading_rows = 1
    )
    """


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Migracja schematu v13 (sell-side + makro).")
    parser.add_argument("--dry-run", action="store_true", help="tylko pokaż SQL, nic nie wykonuj")
    args = parser.parse_args()

    steps = [
        ("indicator_readings: nowe kolumny v13 (ensure_readings_table + ALTER)", None),
        ("config_thresholds_ext: CREATE OR REPLACE z kolumną side (A1:H100)", config_ext_sql()),
        ("sell_tranches_ext: CREATE OR REPLACE (A1:H200)", sell_ext_sql()),
    ]

    if args.dry_run:
        print("DRY-RUN — nic nie wykonuję. Plan:")
        for title, sql in steps:
            print(f"\n--- {title} ---")
            print(sql.strip() if sql else "(wywołanie bigquery_client.ensure_readings_table())")
        return

    if not wh.PROJECT_ID:
        sys.exit("Ustaw GCP_PROJECT_ID (env).")

    print(f"Projekt: {wh.PROJECT_ID} | dataset: {wh.DATASET} ({wh.LOCATION})")
    print("UWAGA: external DDL wymaga, by arkusz miał już kolumnę `side` i zakładkę "
          "`sell_tranches` (scripts/bootstrap_sheet.py).")

    print("\n[1/3] indicator_readings — kolumny v13...")
    wh.ensure_readings_table()
    print("      OK")

    print("[2/3] config_thresholds_ext — side...")
    wh.execute_sql(config_ext_sql())
    print("      OK")

    print("[3/3] sell_tranches_ext...")
    wh.execute_sql(sell_ext_sql())
    print("      OK")

    print("\nGotowe. Sprawdź: SELECT indicator, side FROM config_thresholds_ext / "
          "SELECT * FROM sell_tranches_ext (LIMIT 20).")


if __name__ == "__main__":
    main()
