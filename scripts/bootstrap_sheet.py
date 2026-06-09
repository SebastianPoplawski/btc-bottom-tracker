"""
bootstrap_sheet.py — jednorazowy setup arkusza Google (krok "uruchom LIVE")
===========================================================================
Tworzy w istniejącym arkuszu trzy zakładki wymagane przez aplikację i wypełnia je
nagłówkami + danymi startowymi:

  - config_thresholds   -> nagłówki + 6 progów (z data/sheets_tab_config_thresholds.csv)
  - dca_tranches        -> nagłówki + 7 transz (z data/sheets_tab_dca_tranches.csv)
  - indicator_readings  -> nagłówki + 1 wiersz przykładowy (do edycji)

Działa na GOOGLE SHEETS (Drive), NIE na BigQuery. To jest puste ogniwo, które blokuje
tryb live — aplikacja czyta te 3 zakładki przez gspread (src/ingestion/sheets.py).

IDEMPOTENTNY i BEZPIECZNY:
  - zakładka, która już ma jakiekolwiek dane, jest POMIJANA (nie nadpisuję tego,
    co wpiszesz ręcznie — np. MVRV/NUPL),
  - ponowne uruchomienie nie zaszkodzi.
  - Chcesz mimo to nadpisać? Ustaw BTT_BOOTSTRAP_FORCE=1 (wyczyści i wpisze od nowa).

Poświadczenia (tak samo jak reszta aplikacji — klucz NIGDY na sztywno w kodzie):
  - GOOGLE_APPLICATION_CREDENTIALS = ścieżka do pliku klucza JSON service accountu, lub
  - GCP_SERVICE_ACCOUNT_JSON       = cała treść JSON jako zmienna środowiskowa.
GOOGLE_SHEET_ID można nadpisać przez env; domyślnie wskazuje na Twój arkusz.

Uruchomienie (Windows / PowerShell, z korzenia repo, w aktywnym .venv):
    $env:GOOGLE_APPLICATION_CREDENTIALS = "C:\\sciezka\\do\\klucz.json"
    python scripts\\bootstrap_sheet.py

Zależności: gspread, google-auth  (są już w requirements.txt).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError as exc:  # pragma: no cover
    sys.exit("Brak gspread/google-auth. Zainstaluj: pip install gspread google-auth")

# Pełny Drive — spójnie z src/ingestion/sheets.py SCOPES (zapis do arkusza).
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ID arkusza (to NIE sekret — bez klucza JSON i tak bezużyteczny). Override przez env.
DEFAULT_SHEET_ID = "19GCtFyNBKBEj3-jWOLYfNBEd-7jVIXigkDJBGW0vHRY"
SHEET_ID = os.getenv("GOOGLE_SHEET_ID", DEFAULT_SHEET_ID)

# Nazwy zakładek = domyślne z sheets.py (override tymi samymi zmiennymi env).
TAB_CONFIG = os.getenv("SHEET_TAB_CONFIG", "config_thresholds")
TAB_DCA = os.getenv("SHEET_TAB_DCA", "dca_tranches")
TAB_READINGS = os.getenv("SHEET_TAB_READINGS", "indicator_readings")

FORCE = os.getenv("BTT_BOOTSTRAP_FORCE", "").strip() == "1"


# --------------------------------------------------------------------------- #
# Dane startowe (1:1 z data/*.csv i docs/SHEETS_LAYOUT.md). Wartości jako STRING,
# wpisywane RAW — Sheets nie reinterpretuje ich wg locale (kropka zostaje kropką).
# --------------------------------------------------------------------------- #
CONFIG_HEADER = ["indicator", "operator", "threshold_value", "threshold_value2",
                 "weight", "active", "description"]
CONFIG_ROWS = [
    ["mvrv_z_score",        "lt",      "0",    "",  "1.0", "TRUE", "Dno: MVRV Z < 0"],
    ["nupl",                "lt",      "0",    "",  "1.0", "TRUE", "Dno: NUPL < 0 (kapitulacja)"],
    ["price_to_200w_ratio", "lte",     "1.05", "",  "1.0", "TRUE", "Dno: cena <= ~105% 200W MA"],
    ["whale_accumulating",  "is_true", "",     "",  "1.0", "TRUE", "Dno: reczna flaga TRUE; ref. Exchange Whale Ratio 72h MA < 0.85"],
    ["fear_greed",          "lt",      "25",   "",  "0.5", "TRUE", "Dno: F&G < 25 = pasmo Extreme Fear alternative.me (0-24); niska waga"],
    ["days_since_ath",      "between", "300",  "400", "1.0", "TRUE", "Dno: ~10-13 mies. od ATH"],
]

DCA_HEADER = ["tranche_id", "trigger_price_usd", "allocation_usd", "allocation_pct",
              "min_signals_required", "status", "executed_date", "executed_price_usd", "note"]
DCA_ROWS = [
    ["1", "70000", "", "", "", "pending", "", "", "PRZYKLAD - uzupelnij kwoty/udzialy"],
    ["2", "67500", "", "", "", "pending", "", "", "PRZYKLAD"],
    ["3", "65000", "", "", "", "pending", "", "", "PRZYKLAD"],
    ["4", "62500", "", "", "", "pending", "", "", "PRZYKLAD"],
    ["5", "60000", "", "", "", "pending", "", "", "PRZYKLAD"],
    ["6", "57500", "", "", "", "pending", "", "", "PRZYKLAD"],
    ["7", "55000", "", "", "", "pending", "", "", "PRZYKLAD - dno docelowe"],
]

READINGS_HEADER = ["reading_date", "price_usd", "mvrv_z_score", "nupl", "ma_200w",
                   "whale_accumulating", "whale_ratio", "fear_greed", "days_since_ath",
                   "ath_date", "notes"]
# Jeden wiersz przykładowy (snapshot ref. 1.06) — POKAZUJE FORMAT. Edytuj/zastąp aktualnym.
# price_usd / ma_200w / fear_greed i tak dociąga API w trybie live; wpisujesz głównie
# mvrv_z_score, nupl, whale_accumulating, ath_date.
READINGS_ROWS = [
    ["2026-06-01", "", "", "", "", "FALSE", "0.90", "23", "", "",
     "PRZYKLAD - edytuj lub dodaj nowy wiersz z dzisiejsza data (YYYY-MM-DD)"],
]


# --------------------------------------------------------------------------- #
# Poświadczenia (mirror src/ingestion/sheets._load_credentials_dict, bez streamlita)
# --------------------------------------------------------------------------- #
def load_credentials_dict() -> dict[str, Any]:
    raw = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.exit(f"GCP_SERVICE_ACCOUNT_JSON nie jest poprawnym JSON: {exc}")
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    sys.exit(
        "Brak poświadczeń service accountu. Ustaw jedną z:\n"
        "  GOOGLE_APPLICATION_CREDENTIALS = ścieżka do pliku klucza JSON\n"
        "  GCP_SERVICE_ACCOUNT_JSON       = cała treść JSON"
    )


def get_client() -> "gspread.Client":
    creds = Credentials.from_service_account_info(load_credentials_dict(), scopes=SCOPES)
    return gspread.authorize(creds)


# --------------------------------------------------------------------------- #
# Logika zakładek
# --------------------------------------------------------------------------- #
def _is_empty(values: list[list[str]]) -> bool:
    """True gdy zakładka nie ma żadnej niepustej komórki."""
    return not any(any(str(c).strip() for c in row) for row in values)


def ensure_tab(book: "gspread.Spreadsheet", title: str,
               header: list[str], rows: list[list[str]]) -> str:
    """Tworzy zakładkę jeśli brak i wypełnia ją, gdy pusta. Zwraca status tekstowy."""
    data = [header] + rows
    n_rows = max(len(data) + 20, 50)
    n_cols = max(len(header) + 2, 12)

    try:
        ws = book.worksheet(title)
        created = False
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=title, rows=n_rows, cols=n_cols)
        created = True

    existing = ws.get_all_values()
    if not _is_empty(existing) and not FORCE:
        return f"POMINIETO '{title}' — zawiera juz dane (uzyj BTT_BOOTSTRAP_FORCE=1 by nadpisac)."

    if FORCE and not _is_empty(existing):
        ws.clear()

    # RAW = wpisz dokładnie te stringi (kropka dziesiętna i TRUE/FALSE bez zmian przez locale).
    ws.update(range_name="A1", values=data, value_input_option="RAW")
    verb = "UTWORZONO i wypelniono" if created else "WYPELNIONO (byla pusta)"
    return f"{verb} '{title}' ({len(rows)} wierszy danych + naglowek)."


def main() -> None:
    # Windows konsola domyslnie cp1252 — wymus UTF-8, by polskie znaki w printach
    # nie wywalaly skryptu. try/except: reconfigure nie istnieje w starszych srodowiskach.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(f"Arkusz: {SHEET_ID}")
    print("Laczę przez service account...")
    client = get_client()
    try:
        book = client.open_by_key(SHEET_ID)
    except Exception as exc:
        sys.exit(
            f"Nie udalo sie otworzyc arkusza ({exc}).\n"
            "Sprawdz: GOOGLE_SHEET_ID poprawne ORAZ arkusz udostepniony e-mailowi SA jako Edytujacy."
        )

    print(f"Otwarto: '{book.title}'. Tryb FORCE = {FORCE}.\n")

    results = [
        ensure_tab(book, TAB_CONFIG, CONFIG_HEADER, CONFIG_ROWS),
        ensure_tab(book, TAB_DCA, DCA_HEADER, DCA_ROWS),
        ensure_tab(book, TAB_READINGS, READINGS_HEADER, READINGS_ROWS),
    ]
    for r in results:
        print("  -", r)

    print(
        "\nGotowe. Nastepne kroki:\n"
        "  1) Sprawdz arkusz — 3 zakladki z naglowkami i danymi.\n"
        "  2) (zalecane) Plik -> Ustawienia -> Regionalne -> United States (kropka dziesietna).\n"
        "  3) Uzupelnij w 'indicator_readings' wartosci reczne (mvrv_z_score, nupl, whale_accumulating, ath_date).\n"
        "  4) W panelu Streamlit Cloud -> Secrets: wklej klucz JSON i ustaw APP_MODE=\"live\".\n"
        "  (price_usd / ma_200w / fear_greed dociaga API automatycznie — ich nie wpisujesz.)"
    )


if __name__ == "__main__":
    main()
