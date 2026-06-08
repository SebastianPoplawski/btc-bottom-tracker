"""
config.py — krok 04
===================
Ustawienia, sekrety i przełącznik trybu demo/live. CZYSTY moduł:
bez UI, bez sieci, bez twardej zależności od Streamlita.

Kolejność źródeł ustawień: st.secrets (jeśli Streamlit) -> zmienne środowiskowe -> default.
Klucz JSON service accountu NIE jest tu nigdy wczytywany ani logowany — robią to
warstwy warehouse/sheets z st.secrets/env w trybie live.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

# Ścieżka domyślna seeda demo (względem korzenia repo).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))          # .../src
_REPO_ROOT = os.path.dirname(_THIS_DIR)                          # repo root
SEED_PATH = os.getenv(
    "BTT_SEED_PATH",
    os.path.join(_REPO_ROOT, "data", "seed_snapshot_2026-06-01.json"),
)


def get_setting(key: str, default: Any = None) -> Any:
    """st.secrets (jeśli dostępne) -> env -> default."""
    try:
        import streamlit as st  # import opcjonalny
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


def app_mode() -> str:
    """'live' tylko gdy APP_MODE == 'live'; w przeciwnym razie 'demo'."""
    mode = str(get_setting("APP_MODE", "demo") or "demo").strip().lower()
    return "live" if mode == "live" else "demo"


def is_demo() -> bool:
    """Tryb demo. BTT_DEMO=1 wymusza demo niezależnie od APP_MODE (wygodne do testów)."""
    if str(os.environ.get("BTT_DEMO", "")).strip() == "1":
        return True
    return app_mode() == "demo"


@dataclass(frozen=True)
class Settings:
    mode: str                       # 'demo' | 'live'
    gcp_project_id: Optional[str]
    bq_dataset: str
    bq_location: str
    google_sheet_id: Optional[str]
    seed_path: str

    @property
    def is_demo(self) -> bool:
        return self.mode == "demo"


def load_settings() -> Settings:
    """Zbiera ustawienia w jeden obiekt. Nie waliduje obecności sekretów —
    brak poświadczeń w trybie live ujawni się dopiero przy realnym wywołaniu BQ/Sheets
    (i jest tam łapany jako czytelny komunikat, nie crash)."""
    return Settings(
        mode="demo" if is_demo() else "live",
        gcp_project_id=(str(get_setting("GCP_PROJECT_ID")) if get_setting("GCP_PROJECT_ID") else None),
        bq_dataset=str(get_setting("BQ_DATASET", "btc_tracker")),
        bq_location=str(get_setting("BQ_LOCATION", "EU")),
        google_sheet_id=(str(get_setting("GOOGLE_SHEET_ID")) if get_setting("GOOGLE_SHEET_ID") else None),
        seed_path=SEED_PATH,
    )
