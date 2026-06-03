"""
sheets_ingest.py  (krok 02)
---------------------------
Warstwa wejścia ręcznego: odczyt 3 zakładek Google Sheets do pandas.DataFrame,
walidacja, świeżość, oraz mostek do `bigquery_warehouse.upsert_reading`.

Nazwy zakładek/kolumn zgodne ze schematem 01 (btc_bottom_tracker_schema.sql,
bigquery_warehouse.py). Sekrety przez st.secrets / env, nigdy na sztywno.

Zależności: gspread, google-auth, pandas
    pip install gspread google-auth pandas
"""

from __future__ import annotations

import os
import json
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError as e:  # pragma: no cover
    raise ImportError("Brak gspread/google-auth: pip install gspread google-auth") from e

logger = logging.getLogger(__name__)

# Pełny Drive — spójnie z bigquery_warehouse._SCOPES (external tables + zapis gspread).
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

LOCAL_TZ = ZoneInfo("Europe/Warsaw")
STALE_AFTER_DAYS = 2

# Nazwy ZAKŁADEK w arkuszu (nie mylić z nazwami tabel external w BQ).
TAB_READINGS = os.getenv("SHEET_TAB_READINGS", "indicator_readings")
TAB_CONFIG = os.getenv("SHEET_TAB_CONFIG", "config_thresholds")
TAB_DCA = os.getenv("SHEET_TAB_DCA", "dca_tranches")

# Kolumny indicator_readings = pola upsertu z bigquery_warehouse + reading_date.
READING_NUMERIC = ["price_usd", "mvrv_z_score", "nupl", "ma_200w", "whale_ratio"]
READING_INT = ["fear_greed", "days_since_ath"]
READING_BOOL = ["whale_accumulating"]
READING_DATE = ["reading_date", "ath_date"]
READING_STR = ["notes"]
# Pola przekazywane do upsert_reading (bez reading_date, który jest kluczem).
UPSERT_FIELDS = ["price_usd", "mvrv_z_score", "nupl", "ma_200w", "whale_accumulating",
                 "whale_ratio", "fear_greed", "days_since_ath", "ath_date", "notes"]

VALID_OPERATORS = {"lt", "lte", "gt", "gte", "eq", "is_true", "between"}
VALID_DCA_STATUS = {"pending", "executed", "skipped"}


# --------------------------------------------------------------------------- #
class SheetsConfigError(RuntimeError):
    pass


class SheetsReadError(RuntimeError):
    pass


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, m: str) -> None:
        self.errors.append(m)

    def warn(self, m: str) -> None:
        self.warnings.append(m)


# --------------------------------------------------------------------------- #
# Autoryzacja (analogicznie do bigquery_warehouse._load_credentials)
# --------------------------------------------------------------------------- #
def _load_credentials_dict() -> dict[str, Any]:
    try:
        import streamlit as st  # noqa: WPS433
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass
    raw = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise SheetsConfigError(f"GCP_SERVICE_ACCOUNT_JSON nie jest poprawnym JSON: {e}") from e
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    raise SheetsConfigError(
        "Brak poświadczeń SA: ustaw st.secrets['gcp_service_account'], "
        "GCP_SERVICE_ACCOUNT_JSON lub GOOGLE_APPLICATION_CREDENTIALS."
    )


def get_client() -> "gspread.Client":
    try:
        creds = Credentials.from_service_account_info(_load_credentials_dict(), scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        raise SheetsConfigError(f"Autoryzacja service account nie powiodła się: {e}") from e


def _spreadsheet_key() -> str:
    try:
        import streamlit as st  # noqa: WPS433
        key = st.secrets.get("GOOGLE_SHEET_ID")
        if key:
            return str(key)
    except Exception:
        pass
    key = os.environ.get("GOOGLE_SHEET_ID")
    if not key:
        raise SheetsConfigError("Brak GOOGLE_SHEET_ID (st.secrets lub env).")
    return key


def open_book(client: Optional["gspread.Client"] = None) -> "gspread.Spreadsheet":
    client = client or get_client()
    try:
        return client.open_by_key(_spreadsheet_key())
    except Exception as e:
        raise SheetsReadError(f"Nie udało się otworzyć arkusza: {e}") from e


# --------------------------------------------------------------------------- #
def read_tab(book: "gspread.Spreadsheet", tab: str) -> pd.DataFrame:
    try:
        ws = book.worksheet(tab)
    except gspread.WorksheetNotFound as e:
        raise SheetsReadError(f"Brak zakładki '{tab}'.") from e
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame()
    header = [h.strip() for h in values[0]]
    df = pd.DataFrame(values[1:], columns=header)
    df = df.loc[:, [c for c in df.columns if c != ""]]
    df = df.replace("", pd.NA).dropna(how="all").reset_index(drop=True)
    return df


# --------------------------------------------------------------------------- #
# Parsery (odporne na locale PL)
# --------------------------------------------------------------------------- #
_NUM_CLEAN = re.compile(r"[^\d,.\-+eE]")


def to_float(value: Any) -> Optional[float]:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("\u00a0", "").replace("−", "-")
    if s == "":
        return None
    s = _NUM_CLEAN.sub("", s)
    if s in ("", "-", "+", "."):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def to_int(value: Any) -> Optional[int]:
    f = to_float(value)
    return None if f is None else int(round(f))


def to_date(value: Any) -> Optional[date]:
    if value is None or value is pd.NA:
        return None
    s = str(value).strip()
    if s == "":
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def to_bool(value: Any) -> Optional[bool]:
    if value is None or value is pd.NA:
        return None
    s = str(value).strip().lower()
    if s in ("true", "1", "tak", "yes", "y"):
        return True
    if s in ("false", "0", "nie", "no", "n"):
        return False
    return None


def _require(df: pd.DataFrame, cols: list[str], tab: str, vr: ValidationResult) -> None:
    miss = [c for c in cols if c not in df.columns]
    if miss:
        vr.error(f"[{tab}] brak kolumn: {', '.join(miss)}")


# --------------------------------------------------------------------------- #
# Typowane czytniki
# --------------------------------------------------------------------------- #
def read_readings(book: "gspread.Spreadsheet") -> tuple[pd.DataFrame, ValidationResult]:
    vr = ValidationResult()
    df = read_tab(book, TAB_READINGS)
    if df.empty:
        vr.warn(f"[{TAB_READINGS}] brak odczytów.")
        return df, vr
    _require(df, ["reading_date"], TAB_READINGS, vr)
    if not vr.ok:
        return df, vr

    for c in READING_DATE:
        if c in df.columns:
            df[c] = df[c].map(to_date)
    for c in READING_NUMERIC:
        if c in df.columns:
            df[c] = df[c].map(to_float)
    for c in READING_INT:
        if c in df.columns:
            df[c] = df[c].map(to_int)
    for c in READING_BOOL:
        if c in df.columns:
            df[c] = df[c].map(to_bool)

    if df["reading_date"].isna().any():
        vr.error(f"[{TAB_READINGS}] niesparsowane reading_date w {int(df['reading_date'].isna().sum())} wierszach.")
    if df["reading_date"].duplicated().any():
        vr.error(f"[{TAB_READINGS}] zduplikowane reading_date.")
    if "fear_greed" in df.columns:
        fg = df["fear_greed"].dropna()
        if ((fg < 0) | (fg > 100)).any():
            vr.warn(f"[{TAB_READINGS}] fear_greed poza 0–100.")
    for c in ("mvrv_z_score", "nupl"):
        if c in df.columns and df[c].isna().any():
            vr.warn(f"[{TAB_READINGS}] brak '{c}' w niektórych wierszach (wskaźnik ręczny).")
    if "whale_accumulating" in df.columns and df["whale_accumulating"].isna().any():
        vr.warn(f"[{TAB_READINGS}] 'whale_accumulating' niesparsowane (oczekiwane TRUE/FALSE).")

    return df.sort_values("reading_date").reset_index(drop=True), vr


def read_config(book: "gspread.Spreadsheet") -> tuple[pd.DataFrame, ValidationResult]:
    vr = ValidationResult()
    df = read_tab(book, TAB_CONFIG)
    if df.empty:
        vr.error(f"[{TAB_CONFIG}] brak progów — logika sygnałów nie ruszy.")
        return df, vr
    _require(df, ["indicator", "operator", "threshold_value", "weight", "active"], TAB_CONFIG, vr)
    if not vr.ok:
        return df, vr

    df["threshold_value"] = df["threshold_value"].map(to_float)
    if "threshold_value2" in df.columns:
        df["threshold_value2"] = df["threshold_value2"].map(to_float)
    df["weight"] = df["weight"].map(to_float).fillna(1.0)
    df["active"] = df["active"].map(to_bool)
    df["operator"] = df["operator"].astype(str).str.strip().str.lower()

    bad_op = df.loc[~df["operator"].isin(VALID_OPERATORS), "operator"].dropna().unique()
    if len(bad_op):
        vr.error(f"[{TAB_CONFIG}] nieznane operatory: {list(bad_op)} (dozwolone: {sorted(VALID_OPERATORS)}).")
    if df["indicator"].duplicated().any():
        vr.error(f"[{TAB_CONFIG}] zduplikowane indicator.")
    # 'between' wymaga threshold_value2; 'is_true' nie wymaga threshold_value
    is_between = df["operator"] == "between"
    if "threshold_value2" in df.columns and (is_between & df["threshold_value2"].isna()).any():
        vr.error(f"[{TAB_CONFIG}] operator 'between' bez threshold_value2.")
    needs_v1 = ~df["operator"].isin({"is_true"})
    if (needs_v1 & df["threshold_value"].isna()).any():
        vr.error(f"[{TAB_CONFIG}] brak threshold_value dla operatora innego niż 'is_true'.")
    return df, vr


def read_dca(book: "gspread.Spreadsheet") -> tuple[pd.DataFrame, ValidationResult]:
    vr = ValidationResult()
    df = read_tab(book, TAB_DCA)
    if df.empty:
        vr.warn(f"[{TAB_DCA}] brak transz.")
        return df, vr
    _require(df, ["tranche_id", "trigger_price_usd", "status"], TAB_DCA, vr)
    if not vr.ok:
        return df, vr

    df["tranche_id"] = df["tranche_id"].map(to_int)
    for c in ("trigger_price_usd", "allocation_usd", "allocation_pct", "executed_price_usd"):
        if c in df.columns:
            df[c] = df[c].map(to_float)
    if "min_signals_required" in df.columns:
        df["min_signals_required"] = df["min_signals_required"].map(to_int)
    if "executed_date" in df.columns:
        df["executed_date"] = df["executed_date"].map(to_date)
    df["status"] = df["status"].astype(str).str.strip().str.lower()

    bad = df.loc[~df["status"].isin(VALID_DCA_STATUS), "status"].dropna().unique()
    if len(bad):
        vr.warn(f"[{TAB_DCA}] nieznane statusy: {list(bad)} (dozwolone: {sorted(VALID_DCA_STATUS)}).")
    if df["tranche_id"].duplicated().any():
        vr.error(f"[{TAB_DCA}] zduplikowane tranche_id.")
    if "allocation_pct" in df.columns:
        tot = df["allocation_pct"].dropna().sum()
        if tot and abs(tot - 100) > 1:
            vr.warn(f"[{TAB_DCA}] suma allocation_pct = {tot:.1f}% (≠ 100%).")
    return df.sort_values("trigger_price_usd", ascending=False).reset_index(drop=True), vr


# --------------------------------------------------------------------------- #
# Świeżość
# --------------------------------------------------------------------------- #
@dataclass
class Freshness:
    latest_date: Optional[date]
    age_days: Optional[int]
    is_stale: bool
    has_today: bool
    message: str


def assess_freshness(readings: pd.DataFrame, stale_after: int = STALE_AFTER_DAYS) -> Freshness:
    today = datetime.now(LOCAL_TZ).date()
    if readings.empty or "reading_date" not in readings.columns or readings["reading_date"].dropna().empty:
        return Freshness(None, None, True, False, "Brak jakichkolwiek odczytów w arkuszu.")
    latest = max(d for d in readings["reading_date"] if isinstance(d, date))
    age = (today - latest).days
    has_today = age == 0
    is_stale = age > stale_after
    if has_today:
        msg = f"Dane z dziś ({latest.isoformat()})."
    elif is_stale:
        msg = f"Brak nowego wpisu — ostatni odczyt {latest.isoformat()} (sprzed {age} dni). Pokazuję ostatni znany stan."
    else:
        msg = f"Najnowszy odczyt {latest.isoformat()} (sprzed {age} dni)."
    return Freshness(latest, age, is_stale, has_today, msg)


def latest_reading(readings: pd.DataFrame) -> Optional[pd.Series]:
    if readings.empty or readings["reading_date"].dropna().empty:
        return None
    return readings.sort_values("reading_date").iloc[-1]


# --------------------------------------------------------------------------- #
# Mostek do upsert_reading (bigquery_warehouse)
# --------------------------------------------------------------------------- #
def build_reading_values(row: pd.Series) -> dict[str, Any]:
    """
    Z wiersza arkusza buduje dict pod bigquery_warehouse.upsert_reading(reading_date, values).
    Pomija reading_date (klucz). Zwraca tylko pola z UPSERT_FIELDS obecne w wierszu.
    Użycie:
        r = latest_reading(readings)
        warehouse.upsert_reading(r["reading_date"], build_reading_values(r))
    """
    out: dict[str, Any] = {}
    for fld in UPSERT_FIELDS:
        if fld in row.index:
            val = row[fld]
            out[fld] = None if (val is pd.NA or (isinstance(val, float) and pd.isna(val))) else val
    return out


@dataclass
class SheetBundle:
    readings: pd.DataFrame
    config: pd.DataFrame
    dca: pd.DataFrame
    freshness: Freshness
    validation: ValidationResult


def load_all(client: Optional["gspread.Client"] = None,
             stale_after: int = STALE_AFTER_DAYS) -> SheetBundle:
    book = open_book(client)
    agg = ValidationResult()
    readings, vr1 = read_readings(book)
    config, vr2 = read_config(book)
    dca, vr3 = read_dca(book)
    for vr in (vr1, vr2, vr3):
        agg.errors.extend(vr.errors)
        agg.warnings.extend(vr.warnings)
    return SheetBundle(readings, config, dca, assess_freshness(readings, stale_after), agg)


if __name__ == "__main__":  # python sheets_ingest.py
    logging.basicConfig(level=logging.INFO)
    b = load_all()
    print(b.freshness.message)
    print("Błędy:", b.validation.errors or "brak")
    print("Ostrzeżenia:", b.validation.warnings or "brak")
    print("Odczyty:", len(b.readings), "| Progi:", len(b.config), "| Transze:", len(b.dca))
