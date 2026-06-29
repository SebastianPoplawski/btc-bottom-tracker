"""
backfill_history.py — jednorazowy backfill arkusz -> BigQuery (krok 10)
======================================================================
Przepisuje WSZYSTKIE istniejace odczyty z zakladki `indicator_readings` arkusza
do natywnej tabeli `indicator_readings` w BigQuery. Zamyka luke: appka czytala
historie z BQ (`read_history`) zanim cokolwiek tam trafilo -> sekcja wykresow
byla pusta. Po backfillu wykresy maja z czego rysowac.

Idempotentne: zapis przez `upsert_reading` (MERGE po `reading_date`) — powtorne
uruchomienie aktualizuje te same wiersze, nie duplikuje. Tabela tworzona sama
przy starcie (`ensure_dataset` + `ensure_readings_table`).

Poswiadczenia (tak samo jak reszta aplikacji — klucz NIGDY na sztywno w kodzie):
  GOOGLE_APPLICATION_CREDENTIALS = sciezka do pliku klucza JSON, lub
  GCP_SERVICE_ACCOUNT_JSON       = cala tresc JSON.
Projekt/dataset/location z env (jak bigquery_client): GCP_PROJECT_ID, BQ_DATASET,
BQ_LOCATION. Arkusz: GOOGLE_SHEET_ID.

Przyklad (Windows / PowerShell, z korzenia repo, .venv aktywny):
  $env:GOOGLE_APPLICATION_CREDENTIALS = "$env:USERPROFILE\\.secrets\\btc-bottom-tracker-498120-56eabcdb1342.json"
  python scripts\\backfill_history.py

  # podglad bez zapisu (co poszloby do BQ):
  python scripts\\backfill_history.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

# Importy dzialaja przy uruchomieniu z korzenia repo (scripts/backfill_history.py).
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.join(_here, "..")
sys.path.insert(0, os.path.join(_root, "src", "ingestion"))
sys.path.insert(0, os.path.join(_root, "src", "warehouse"))
import sheets                 # type: ignore  # noqa: E402
import bigquery_client as wh  # type: ignore  # noqa: E402


def _compute_values(row, sheets_mod=sheets) -> dict:
    """Buduje values pod upsert_reading; dolicza days_since_ath z ath_date
    (parytet z run_ingest.collect_values), gdy brak wpisu recznego."""
    values = sheets_mod.build_reading_values(row)
    if values.get("days_since_ath") is None and values.get("ath_date"):
        try:
            values["days_since_ath"] = (row["reading_date"] - values["ath_date"]).days
        except Exception:
            pass
    return values


def backfill(dry_run: bool = False, sheets_mod=sheets, warehouse=wh) -> tuple[int, int]:
    """Przepisuje wszystkie odczyty z arkusza do BQ. Zwraca (przetworzone, zmodyfikowane)."""
    bundle = sheets_mod.load_all()
    for w in bundle.validation.warnings:
        print(f"  ! {w}")

    if not dry_run:
        warehouse.ensure_dataset()
        warehouse.ensure_readings_table()

    processed = 0
    affected = 0
    for _, row in bundle.readings.iterrows():
        reading_date = row.get("reading_date")
        if reading_date is None or pd.isna(reading_date):
            continue  # pomin wiersze bez reading_date

        values = _compute_values(row, sheets_mod)
        processed += 1
        if dry_run:
            print(f"  [dry-run] {reading_date} -> {values}")
            continue
        affected += warehouse.upsert_reading(reading_date, values)

    return processed, affected


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 safe
    except Exception:
        pass

    p = argparse.ArgumentParser(description="Backfill odczytow z arkusza do BigQuery.")
    p.add_argument("--dry-run", action="store_true",
                   help="pokaz co poszloby do BQ, bez zapisu i bez tworzenia tabeli")
    args = p.parse_args()

    print("Backfill: arkusz indicator_readings -> BigQuery")
    processed, affected = backfill(dry_run=args.dry_run)

    if args.dry_run:
        print(f"\n--dry-run: {processed} wierszy gotowych do zapisu (nic nie zapisano).")
    else:
        print(f"\nGotowe — przetworzono {processed} wierszy, "
              f"wstawiono/zaktualizowano {affected} w BigQuery.")


if __name__ == "__main__":
    main()
