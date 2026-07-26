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
TAB_SELL = os.getenv("SHEET_TAB_SELL", "sell_tranches")  # krok 13
TAB_READINGS = os.getenv("SHEET_TAB_READINGS", "indicator_readings")

FORCE = os.getenv("BTT_BOOTSTRAP_FORCE", "").strip() == "1"


# --------------------------------------------------------------------------- #
# Dane startowe (1:1 z data/*.csv i docs/SHEETS_LAYOUT.md). Wartości jako STRING,
# wpisywane RAW — Sheets nie reinterpretuje ich wg locale (kropka zostaje kropką).
# --------------------------------------------------------------------------- #
# Wiersze 1:1 z data/sheets_tab_config_thresholds.csv (zrodlo prawdy).
# Krok 13: kolumna `side` (bottom/top/macro) + progi szczytu i makro.
# Wagi mvrv/nupl = 0.5 (redundancja, krok 11).
CONFIG_HEADER = ["indicator", "operator", "threshold_value", "threshold_value2",
                 "weight", "active", "description", "side"]
CONFIG_ROWS = [
    ["mvrv_z_score",        "lt",      "0",    "",    "0.5", "TRUE", "Dno: MVRV Z < 0 (redundancja z NUPL -> waga 0.5)", "bottom"],
    ["nupl",                "lt",      "0",    "",    "0.5", "TRUE", "Dno: NUPL < 0 (kapitulacja; redundancja z MVRV-Z -> waga 0.5)", "bottom"],
    ["price_to_200w_ratio", "lte",     "1.05", "",    "1.0", "TRUE", "Dno: cena <= ~105% 200W MA", "bottom"],
    ["whale_accumulating",  "is_true", "",     "",    "1.0", "TRUE", "Dno: reczna flaga TRUE; ref. Exchange Whale Ratio 72h MA < 0.85", "bottom"],
    ["fear_greed",          "lt",      "25",   "",    "0.5", "TRUE", "Dno: F&G < 25 = pasmo Extreme Fear alternative.me (0-24); niska waga", "bottom"],
    ["days_since_ath",      "between", "300",  "400", "1.0", "TRUE", "Dno: ~10-13 mies. od ATH", "bottom"],
    ["mvrv_z_score",        "gt",      "5",    "",    "0.5", "TRUE", "Szczyt: MVRV Z > 5 (malejace szczyty cykli; redundancja z NUPL -> 0.5)", "top"],
    ["nupl",                "gt",      "0.7",  "",    "0.5", "TRUE", "Szczyt: NUPL > 0.7 (euforia; redundancja z MVRV-Z -> 0.5)", "top"],
    ["price_to_200w_ratio", "gte",     "2.5",  "",    "1.0", "TRUE", "Szczyt: cena >= 2.5x 200W MA", "top"],
    ["fear_greed",          "gt",      "75",   "",    "0.5", "TRUE", "Szczyt: F&G > 75 (Extreme Greed); wklad stopniowy 75->90; niska waga", "top"],
    ["pi_cycle_crossed",    "is_true", "",     "",    "1.0", "TRUE", "Szczyt: Pi Cycle Top - 111DMA >= 2x 350DMA (computed)", "top"],
    ["months_since_halving","between", "12",   "18",  "1.0", "TRUE", "Szczyt: 12-18 mies. od halvingu (computed z halving_date)", "top"],
    ["fed_funds_delta_3m",  "gt",      "0",    "",    "1.0", "TRUE", "Risk-off: Fed zaciesnia (DFF wyzej niz ~3 mies. temu)", "macro"],
    ["dxy_delta_3m",        "gt",      "0",    "",    "1.0", "TRUE", "Risk-off: dolar umacnia sie (broad index wyzej niz ~3 mies. temu)", "macro"],
    ["m2_yoy",              "lt",      "0",    "",    "1.0", "TRUE", "Risk-off: podaz M2 kurczy sie r/r", "macro"],
    ["etf_flows_usd_7d",    "lt",      "0",    "",    "1.0", "TRUE", "Risk-off: odplywy netto z ETF spot BTC (7d; wpis reczny)", "macro"],
]

SELL_HEADER = ["tranche_id", "trigger_price_usd", "allocation_pct", "min_top_signals",
               "status", "executed_date", "executed_price_usd", "note"]
# Progi cen wyjscia to TWOJ plan — nie zgadujemy rynku; wiersze przykladowe puste.
SELL_ROWS = [
    ["1", "", "", "", "pending", "", "", "PRZYKLAD - uzupelnij progi cen i % pozycji (plan wyjscia)"],
    ["2", "", "", "", "pending", "", "", "PRZYKLAD"],
    ["3", "", "", "", "pending", "", "", "PRZYKLAD"],
    ["4", "", "", "", "pending", "", "", "PRZYKLAD"],
    ["5", "", "", "", "pending", "", "", "PRZYKLAD - ostatnia transza"],
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

# Krok 13: dochodza kolumny Pi Cycle (ma_111d/ma_350d, AUTO), halving_date
# (reczne, RAZ) i makro (FRED AUTO; etf_flows_usd_7d recznie).
READINGS_HEADER = ["reading_date", "price_usd", "mvrv_z_score", "nupl", "ma_200w",
                   "whale_accumulating", "whale_ratio", "fear_greed", "days_since_ath",
                   "ath_date", "ma_111d", "ma_350d", "halving_date",
                   "fed_funds_rate", "fed_funds_delta_3m", "dxy_proxy", "dxy_delta_3m",
                   "m2_yoy", "etf_flows_usd_7d", "notes"]
# Jeden wiersz przykładowy (snapshot ref. 1.06) — POKAZUJE FORMAT. Edytuj/zastąp aktualnym.
# price_usd / ma_200w / ma_111d / ma_350d / fear_greed / makro FRED dociąga API w trybie
# live; wpisujesz głównie mvrv_z_score, nupl, whale_accumulating, ath_date, halving_date,
# etf_flows_usd_7d.
READINGS_ROWS = [
    ["2026-06-01", "", "", "", "", "FALSE", "0.90", "23", "", "",
     "", "", "2024-04-20", "", "", "", "", "", "",
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


# --------------------------------------------------------------------------- #
# Upgrade v13 (NIEDESTRUKCYJNY): dopisuje braki do ISTNIEJĄCYCH zakładek,
# nie ruszając wartości wpisanych ręcznie (progi/wagi/odczyty zostają).
# --------------------------------------------------------------------------- #
def _col_letter(n: int) -> str:
    """1 -> A, 2 -> B, ... 27 -> AA."""
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def upgrade_config_tab(book: "gspread.Spreadsheet") -> str:
    """Dokłada kolumnę `side` (istniejące wiersze -> 'bottom') i brakujące
    wiersze top/macro do istniejącej zakładki config. Idempotentne."""
    try:
        ws = book.worksheet(TAB_CONFIG)
    except gspread.WorksheetNotFound:
        return f"UPGRADE '{TAB_CONFIG}': brak zakładki (utworzy ją ensure_tab)."
    values = ws.get_all_values()
    if _is_empty(values):
        return f"UPGRADE '{TAB_CONFIG}': pusta (wypełni ją ensure_tab)."

    header = [h.strip() for h in values[0]]
    changes: list[str] = []

    # 1) kolumna side
    if "side" not in header:
        col = len(header) + 1
        letter = _col_letter(col)
        n_data = len([r for r in values[1:] if any(str(c).strip() for c in r)])
        col_values = [["side"]] + [["bottom"]] * n_data
        if ws.col_count < col:
            ws.add_cols(col - ws.col_count)
        ws.update(range_name=f"{letter}1", values=col_values, value_input_option="RAW")
        header.append("side")
        changes.append(f"dodano kolumnę side ({letter}); istniejące wiersze -> bottom")

    # 2) brakujące wiersze top/macro (klucz: indicator+side)
    idx_ind = header.index("indicator")
    idx_side = header.index("side")
    existing = set()
    for r in values[1:]:
        if len(r) > idx_ind and str(r[idx_ind]).strip():
            side = r[idx_side].strip().lower() if len(r) > idx_side and str(r[idx_side]).strip() else "bottom"
            existing.add((str(r[idx_ind]).strip(), side))
    to_add = [row for row in CONFIG_ROWS if (row[0], row[-1]) not in existing]
    if to_add:
        ws.append_rows(to_add, value_input_option="RAW")
        changes.append(f"dopisano {len(to_add)} wierszy (top/macro)")

    return (f"UPGRADE '{TAB_CONFIG}': " + "; ".join(changes)) if changes \
        else f"UPGRADE '{TAB_CONFIG}': aktualna (side + wiersze top/macro już są)."


def upgrade_readings_tab(book: "gspread.Spreadsheet") -> str:
    """Dokłada brakujące NAGŁÓWKI nowych kolumn (v13) na końcu wiersza 1.
    Danych nie rusza. Idempotentne."""
    try:
        ws = book.worksheet(TAB_READINGS)
    except gspread.WorksheetNotFound:
        return f"UPGRADE '{TAB_READINGS}': brak zakładki (utworzy ją ensure_tab)."
    values = ws.get_all_values()
    if _is_empty(values):
        return f"UPGRADE '{TAB_READINGS}': pusta (wypełni ją ensure_tab)."
    header = [h.strip() for h in values[0]]
    missing = [c for c in READINGS_HEADER if c not in header]
    if not missing:
        return f"UPGRADE '{TAB_READINGS}': nagłówki aktualne."
    start = len(header) + 1
    if ws.col_count < len(header) + len(missing):
        ws.add_cols(len(header) + len(missing) - ws.col_count)
    ws.update(range_name=f"{_col_letter(start)}1", values=[missing], value_input_option="RAW")
    return f"UPGRADE '{TAB_READINGS}': dodano nagłówki: {', '.join(missing)}."


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
        ensure_tab(book, TAB_SELL, SELL_HEADER, SELL_ROWS),        # krok 13
        ensure_tab(book, TAB_READINGS, READINGS_HEADER, READINGS_ROWS),
        # Upgrade v13 (niedestrukcyjny) dla zakładek, które już miały dane:
        upgrade_config_tab(book),
        upgrade_readings_tab(book),
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
