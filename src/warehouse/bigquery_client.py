"""bigquery_warehouse.py
Warstwa dostępu do BigQuery dla BTC Bottom Tracker.

Sekrety (NIGDY na sztywno w kodzie):
  - Streamlit:  st.secrets["gcp_service_account"]  (cały JSON SA jako tabela TOML)
  - lub env:    GOOGLE_APPLICATION_CREDENTIALS = ścieżka do pliku JSON SA

Konfiguracja przez env (z domyślnymi):
  GCP_PROJECT_ID, BQ_DATASET, BQ_LOCATION,
  CONFIG_TABLE (np. config_thresholds lub config_thresholds_ext),
  DCA_TABLE    (np. dca_tranches lub dca_tranches_ext)

Zależności:
  pip install google-cloud-bigquery google-auth pandas db-dtypes
  (db-dtypes jest potrzebne dla .to_dataframe())
"""

from __future__ import annotations

import os
import logging
from decimal import Decimal
from datetime import date, timedelta
from typing import Any, Mapping, Optional

import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account
from google.api_core.exceptions import GoogleAPIError

logger = logging.getLogger(__name__)

# Scope BigQuery + Drive. Drive (auth/drive) jest WYMAGANY do tabel
# zewnętrznych podpiętych pod Google Sheets — inaczej 403 przy odczycie
# arkusza. (drive.readonly bywa wystarczające do odczytu, ale gspread
# w kroku 02 będzie pisać do arkusza, więc trzymamy pełny auth/drive.)
_SCOPES = [
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/drive",
]

# --- Konfiguracja (parametryzowana) -------------------------------
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
DATASET = os.getenv("BQ_DATASET", "btc_tracker")  # zgodnie ze STATUS (już w EU)
LOCATION = os.getenv("BQ_LOCATION", "EU")  # EU / US / europe-central2

TABLE_READINGS = "indicator_readings"
CONFIG_TABLE = os.getenv("CONFIG_TABLE", "config_thresholds_ext")  # external (default); native: config_thresholds
DCA_TABLE = os.getenv("DCA_TABLE", "dca_tranches_ext")             # external (default); native: dca_tranches

# Kolumny i ich typy BQ dla upsertu odczytu (bez reading_date — to klucz).
_READING_FIELDS: list[tuple[str, str]] = [
    ("price_usd", "NUMERIC"),
    ("mvrv_z_score", "NUMERIC"),
    ("nupl", "NUMERIC"),
    ("ma_200w", "NUMERIC"),
    ("whale_accumulating", "BOOL"),   # sygnał dna (ręczny TRUE/FALSE) — nadrzędny
    ("whale_ratio", "NUMERIC"),       # opcjonalna wartość referencyjna
    ("fear_greed", "INT64"),
    ("days_since_ath", "INT64"),
    ("ath_date", "DATE"),
    ("notes", "STRING"),
]

# Whitelist kolumn dozwolonych do SELECT (ochrona przed wstrzyknięciem nazw).
_SELECTABLE = {
    "reading_date", "price_usd", "mvrv_z_score", "nupl", "ma_200w",
    "whale_accumulating", "whale_ratio", "fear_greed", "days_since_ath",
    "ath_date", "notes",
}
_DEFAULT_COLS = [
    "reading_date", "price_usd", "mvrv_z_score", "nupl", "ma_200w",
    "whale_accumulating", "whale_ratio", "fear_greed", "days_since_ath",
]


# ------------------------------------------------------------------
# Autoryzacja
# ------------------------------------------------------------------
def _load_credentials() -> service_account.Credentials:
    """Ładuje poświadczenia SA: najpierw st.secrets, potem plik z env."""
    # 1) Streamlit secrets (jeśli dostępne)
    try:
        import streamlit as st  # import opcjonalny

        if "gcp_service_account" in st.secrets:
            info = dict(st.secrets["gcp_service_account"])
            return service_account.Credentials.from_service_account_info(
                info, scopes=_SCOPES
            )
    except Exception:  # brak streamlit albo brak sekretu — lecimy dalej
        pass

    # 2) Plik wskazany przez zmienną środowiskową
    key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if key_path and os.path.exists(key_path):
        return service_account.Credentials.from_service_account_file(
            key_path, scopes=_SCOPES
        )

    raise RuntimeError(
        "Brak poświadczeń: ustaw st.secrets['gcp_service_account'] "
        "albo GOOGLE_APPLICATION_CREDENTIALS (ścieżka do JSON service accountu)."
    )


_client: Optional[bigquery.Client] = None


def get_client() -> bigquery.Client:
    """Singleton klienta BigQuery. W Streamlit owiń wywołanie w
    @st.cache_resource po stronie aplikacji, by nie tworzyć go co rerun."""
    global _client
    if _client is None:
        if not PROJECT_ID:
            raise RuntimeError("Ustaw GCP_PROJECT_ID (env lub bezpośrednio w module).")
        _client = bigquery.Client(
            project=PROJECT_ID, credentials=_load_credentials(), location=LOCATION
        )
    return _client


# ------------------------------------------------------------------
# Inicjalizacja / DDL
# ------------------------------------------------------------------
def ensure_dataset() -> None:
    """Tworzy dataset w zadanym LOCATION, jeśli nie istnieje (idempotentne)."""
    client = get_client()
    ds = bigquery.Dataset(f"{PROJECT_ID}.{DATASET}")
    ds.location = LOCATION
    try:
        client.create_dataset(ds, exists_ok=True)
        logger.info("Dataset %s gotowy (location=%s).", DATASET, LOCATION)
    except GoogleAPIError as exc:
        logger.error("Nie udało się utworzyć datasetu: %s", exc)
        raise


def execute_sql(sql: str) -> None:
    """Uruchamia dowolny statement DDL/DML (np. tworzenie tabel z pliku .sql)."""
    client = get_client()
    try:
        client.query(sql).result()
    except GoogleAPIError as exc:
        logger.error("Błąd SQL: %s", exc)
        raise


# ------------------------------------------------------------------
# Zapis odczytu — upsert po dacie (MERGE; BigQuery nie ma UPSERT)
# ------------------------------------------------------------------
def upsert_reading(reading_date: date, values: Mapping[str, Any]) -> int:
    """Wstawia lub aktualizuje odczyt dla danego dnia (klucz: reading_date).

    Args:
        reading_date: dzień odczytu.
        values: dict z kluczami z _READING_FIELDS; brakujące -> NULL.
    Returns:
        liczba zmodyfikowanych wierszy (0 lub 1).
    """
    client = get_client()
    table = f"`{PROJECT_ID}.{DATASET}.{TABLE_READINGS}`"

    params = [bigquery.ScalarQueryParameter("reading_date", "DATE", reading_date)]
    for name, bq_type in _READING_FIELDS:
        val = values.get(name)
        if bq_type == "NUMERIC" and val is not None:
            val = Decimal(str(val))  # bezpieczna konwersja do NUMERIC
        params.append(bigquery.ScalarQueryParameter(name, bq_type, val))

    set_clause = ",\n      ".join(f"{n} = S.{n}" for n, _ in _READING_FIELDS)
    insert_cols = ", ".join(n for n, _ in _READING_FIELDS)
    insert_vals = ", ".join(f"S.{n}" for n, _ in _READING_FIELDS)
    select_src = ", ".join(f"@{n} AS {n}" for n, _ in _READING_FIELDS)

    sql = f"""
    MERGE {table} T
    USING (SELECT @reading_date AS reading_date, {select_src}) S
    ON T.reading_date = S.reading_date
    WHEN MATCHED THEN UPDATE SET
      {set_clause},
      updated_at = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT
      (reading_date, {insert_cols}, inserted_at, updated_at)
    VALUES
      (S.reading_date, {insert_vals}, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
    """
    try:
        job = client.query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
        )
        job.result()
        return job.num_dml_affected_rows or 0
    except GoogleAPIError as exc:
        logger.error("upsert_reading nie powiódł się (%s): %s", reading_date, exc)
        raise


# ------------------------------------------------------------------
# Odczyt historii do DataFrame (pod wykresy)
# ------------------------------------------------------------------
def read_history(days: int = 365, columns: Optional[list[str]] = None) -> pd.DataFrame:
    """Zwraca odczyty z ostatnich `days` dni jako DataFrame.

    SELECT tylko potrzebnych kolumn (oszczędność bytes-scanned).
    Cutoff liczony w Pythonie i podany jako parametr DATE — pewniejsze
    niż INTERVAL ze zmienną.
    """
    client = get_client()
    cols = columns or _DEFAULT_COLS
    safe = [c for c in cols if c in _SELECTABLE]
    if "reading_date" not in safe:
        safe.insert(0, "reading_date")
    col_sql = ", ".join(safe)

    cutoff = date.today() - timedelta(days=days)
    sql = f"""
    SELECT {col_sql}
    FROM `{PROJECT_ID}.{DATASET}.{TABLE_READINGS}`
    WHERE reading_date >= @cutoff
    ORDER BY reading_date
    """
    try:
        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("cutoff", "DATE", cutoff)
                ]
            ),
        )
        return job.result().to_dataframe(create_bqstorage_client=False)
    except GoogleAPIError as exc:
        logger.error("read_history nie powiódł się: %s", exc)
        raise


# ------------------------------------------------------------------
# Odczyt konfiguracji i planu DCA (działa dla tabel natywnych I _ext)
# ------------------------------------------------------------------
def read_config_thresholds() -> pd.DataFrame:
    """Progi sygnałów. Wejście do logiki sygnałów (oddzielny moduł)."""
    client = get_client()
    sql = f"""
    SELECT indicator, operator, threshold_value, threshold_value2,
           weight, active, description
    FROM `{PROJECT_ID}.{DATASET}.{CONFIG_TABLE}`
    """
    return client.query(sql).result().to_dataframe(create_bqstorage_client=False)


def read_dca_tranches() -> pd.DataFrame:
    """Plan DCA $70K -> $55K wraz ze statusem realizacji."""
    client = get_client()
    sql = f"""
    SELECT tranche_id, trigger_price_usd, allocation_usd, allocation_pct,
           min_signals_required, status, executed_date, executed_price_usd, note
    FROM `{PROJECT_ID}.{DATASET}.{DCA_TABLE}`
    ORDER BY trigger_price_usd DESC
    """
    return client.query(sql).result().to_dataframe(create_bqstorage_client=False)


# ------------------------------------------------------------------
# Przykład użycia (uruchamiaj świadomie — wymaga poświadczeń i projektu).
# Nie wpisuję tu wartości rynkowych — świeże odczyty wprowadzasz sam.
# ------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_dataset()
    # Tabele utwórz raz z pliku btc_bottom_tracker_schema.sql, np.:
    #   with open("btc_bottom_tracker_schema.sql") as f:
    #       for stmt in f.read().split(";"):
    #           if stmt.strip():
    #               execute_sql(stmt)
    #
    # Przykład upsertu (PODSTAW realne odczyty zamiast None):
    #   upsert_reading(
    #       date.today(),
    #       {"price_usd": None, "fear_greed": 23, "days_since_ath": None,
    #        "mvrv_z_score": None, "nupl": None, "ma_200w": None,
    #        "whale_accumulating": False, "whale_ratio": None, "notes": "snapshot ref"},
    #   )
    #
    # df = read_history(days=180, columns=["reading_date", "fear_greed"])
    # print(df.tail())
