"""
add_reading.py — dopisywanie tygodniowego odczytu do arkusza (krok "uzywanie")
==============================================================================
Dopisuje (lub aktualizuje) jeden wiersz w zakladce `indicator_readings` Twojego arkusza,
poprawnie otypowany i wpisany RAW — omija problem przecinka dziesietnego i polskiego
locale, ktory psuje reczne wklejanie CSV. Zamyka petle:

    czat researchowy -> wartosci -> python scripts/add_reading.py ... -> wiersz w arkuszu
    -> dashboard sam sie odswieza (czyta arkusz na zywo przez gspread).

UPSERT po `reading_date`: jesli wiersz z ta data juz istnieje, zostaje ZAKTUALIZOWANY
(bez duplikatu — duplikat reading_date aplikacja traktuje jako blad). Przy aktualizacji
NADPISYWANE sa tylko pola, ktore podasz; reszta komorek w wierszu zostaje nietknieta.

Pola AUTO (price_usd, ma_200w, fear_greed) celowo zostawiamy puste — dociaga je API.

Poswiadczenia (tak samo jak reszta aplikacji — klucz NIGDY na sztywno w kodzie):
  GOOGLE_APPLICATION_CREDENTIALS = sciezka do pliku klucza JSON, lub
  GCP_SERVICE_ACCOUNT_JSON       = cala tresc JSON.
GOOGLE_SHEET_ID nadpisywalny przez env; domyslnie wskazuje Twoj arkusz.

Przyklad (Windows / PowerShell, z korzenia repo, .venv aktywny):
  $env:GOOGLE_APPLICATION_CREDENTIALS = "$env:USERPROFILE\\.secrets\\btc-bottom-tracker-498120-56eabcdb1342.json"
  python scripts\\add_reading.py --mvrv 0.34 --nupl 0.12 --ath-date 2025-10-06 `
      --whale-ratio 0.64 --notes "whale_ratio ~marzec, NISKA PEWNOSC; ATH cyklu ~126198 USD"

  # podglad bez zapisu:
  python scripts\\add_reading.py --mvrv 0.34 --nupl 0.12 --ath-date 2025-10-06 --dry-run

Domyslnie reading_date = dzis. whale_accumulating zostaw PUSTE, jesli nie masz swiezej,
pewnej oceny (puste = "brak danych", composite tego nie liczy jako spelnione).

Zaleznosci: gspread, google-auth (sa w requirements.txt).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Any, Optional

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:  # pragma: no cover
    sys.exit("Brak gspread/google-auth. Zainstaluj: pip install gspread google-auth")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DEFAULT_SHEET_ID = "19GCtFyNBKBEj3-jWOLYfNBEd-7jVIXigkDJBGW0vHRY"
SHEET_ID = os.getenv("GOOGLE_SHEET_ID", DEFAULT_SHEET_ID)
TAB_READINGS = os.getenv("SHEET_TAB_READINGS", "indicator_readings")

# Pola dociagane z API — zawsze puste w arkuszu (fallback only).
AUTO_FIELDS = {"price_usd", "ma_200w", "fear_greed"}


# --------------------------------------------------------------------------- #
# Poswiadczenia (mirror sheets._load_credentials_dict, bez streamlita)
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
        "Brak poswiadczen service accountu. Ustaw jedna z:\n"
        "  GOOGLE_APPLICATION_CREDENTIALS = sciezka do pliku klucza JSON\n"
        "  GCP_SERVICE_ACCOUNT_JSON       = cala tresc JSON"
    )


def get_client() -> "gspread.Client":
    creds = Credentials.from_service_account_info(load_credentials_dict(), scopes=SCOPES)
    return gspread.authorize(creds)


# --------------------------------------------------------------------------- #
# Normalizacja wartosci (kropka dziesietna, TRUE/FALSE, ISO data)
# --------------------------------------------------------------------------- #
def norm_number(v: Optional[str], field: str) -> str:
    """Zamien przecinek na kropke; ostrzez, jesli nie parsuje sie jako liczba."""
    if v is None or str(v).strip() == "":
        return ""
    s = str(v).strip().replace(",", ".")
    try:
        float(s)
    except ValueError:
        print(f"  ! UWAGA: '{field}'='{v}' nie wyglada na liczbe — wpisuje jak jest.")
    return s


def norm_bool(v: Optional[str]) -> str:
    """TRUE/FALSE (wielkimi) lub puste, jesli nie podano."""
    if v is None or str(v).strip() == "":
        return ""
    s = str(v).strip().lower()
    if s in ("true", "1", "tak", "yes", "y"):
        return "TRUE"
    if s in ("false", "0", "nie", "no", "n"):
        return "FALSE"
    sys.exit(f"--whale przyjmuje TRUE/FALSE (podano: '{v}').")


def norm_date(v: Optional[str], field: str) -> str:
    """Waliduj ISO YYYY-MM-DD; pusty dozwolony."""
    if v is None or str(v).strip() == "":
        return ""
    s = str(v).strip()
    try:
        date.fromisoformat(s)
    except ValueError:
        sys.exit(f"'{field}' musi byc w formacie YYYY-MM-DD (podano: '{v}').")
    return s


# --------------------------------------------------------------------------- #
def build_values(args: argparse.Namespace) -> dict[str, str]:
    """Mapa kolumna -> wartosc (string). Tylko pola podane przez uzytkownika
    (+ reading_date). Pola AUTO i niepodane pomijamy (zostana puste / nietkniete)."""
    out: dict[str, str] = {"reading_date": norm_date(args.date, "reading_date")}
    if args.mvrv is not None:
        out["mvrv_z_score"] = norm_number(args.mvrv, "mvrv_z_score")
    if args.nupl is not None:
        out["nupl"] = norm_number(args.nupl, "nupl")
    if args.whale is not None:
        out["whale_accumulating"] = norm_bool(args.whale)
    if args.whale_ratio is not None:
        out["whale_ratio"] = norm_number(args.whale_ratio, "whale_ratio")
    if args.days_ath is not None:
        out["days_since_ath"] = norm_number(args.days_ath, "days_since_ath")
    if args.ath_date is not None:
        out["ath_date"] = norm_date(args.ath_date, "ath_date")
    if args.notes is not None:
        out["notes"] = str(args.notes)
    return out


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 safe
    except Exception:
        pass

    p = argparse.ArgumentParser(description="Dopisz/aktualizuj wiersz w indicator_readings.")
    p.add_argument("--date", default=date.today().isoformat(),
                   help="reading_date YYYY-MM-DD (domyslnie dzis)")
    p.add_argument("--mvrv", help="mvrv_z_score (np. 0.34)")
    p.add_argument("--nupl", help="nupl (np. 0.12)")
    p.add_argument("--whale", help="whale_accumulating: TRUE/FALSE (puste = brak danych)")
    p.add_argument("--whale-ratio", dest="whale_ratio", help="whale_ratio referencyjnie (np. 0.64)")
    p.add_argument("--days-ath", dest="days_ath", help="days_since_ath (opcjonalne; gdy computed z ath_date — pomin)")
    p.add_argument("--ath-date", dest="ath_date", help="ath_date YYYY-MM-DD")
    p.add_argument("--notes", help="notatka")
    p.add_argument("--dry-run", action="store_true", help="pokaz wiersz bez zapisu")
    args = p.parse_args()

    provided = build_values(args)

    # Ostrzezenie, gdyby ktos jednak podal pole AUTO.
    for f in AUTO_FIELDS & set(provided):
        print(f"  ! '{f}' to pole AUTO (dociaga API) — pomijam, zostaje puste.")
        provided.pop(f, None)

    print(f"Arkusz: {SHEET_ID} / zakladka: {TAB_READINGS}")
    client = get_client()
    try:
        book = client.open_by_key(SHEET_ID)
        ws = book.worksheet(TAB_READINGS)
    except Exception as exc:
        sys.exit(f"Nie udalo sie otworzyc arkusza/zakladki ({exc}).")

    values = ws.get_all_values()
    if not values:
        sys.exit(f"Zakladka '{TAB_READINGS}' jest pusta — uruchom najpierw scripts/bootstrap_sheet.py.")

    header = [h.strip() for h in values[0]]
    idx = {name: i for i, name in enumerate(header)}
    if "reading_date" not in idx:
        sys.exit("Brak kolumny 'reading_date' w naglowku zakladki.")

    unknown = [k for k in provided if k not in idx]
    if unknown:
        sys.exit(f"Kolumny spoza naglowka arkusza: {unknown}. Sprawdz layout (docs/SHEETS_LAYOUT.md).")

    rd = provided["reading_date"]

    # UPSERT po reading_date: szukaj istniejacego wiersza.
    rd_col = idx["reading_date"]
    found_row = None  # 1-based numer wiersza w arkuszu
    base = [""] * len(header)
    for i, row in enumerate(values[1:], start=2):
        if len(row) > rd_col and row[rd_col].strip() == rd:
            found_row = i
            base = (row + [""] * len(header))[:len(header)]  # zachowaj istniejace komorki
            break

    # Nadpisz tylko pola podane przez uzytkownika.
    for col, val in provided.items():
        base[idx[col]] = val

    action = f"AKTUALIZACJA wiersza {found_row}" if found_row else "DOPISANIE nowego wiersza"
    print(f"\n{action} dla reading_date={rd}:")
    for name in header:
        cell = base[idx[name]]
        tag = "  (AUTO/puste)" if name in AUTO_FIELDS else ""
        print(f"  {name:20s} = {cell!r}{tag}")

    if args.dry_run:
        print("\n--dry-run: nie zapisano.")
        return

    if found_row:
        ws.update(range_name=f"A{found_row}", values=[base], value_input_option="RAW")
    else:
        ws.append_row(base, value_input_option="RAW", table_range="A1")

    print(f"\nGotowe — {action.lower()}. Dashboard odswiezy sie sam (cache do ~15 min).")


if __name__ == "__main__":
    main()
