"""
check_alerts.py — krok 20 (uruchamiany przez cron PO ingeście)
==============================================================
Porównuje DZISIEJSZY stan frameworka z POPRZEDNIM odczytem (oba liczone z
`indicator_readings` w BigQuery aktualnym configiem) i przy zmianie tworzy
GitHub Issue w repo — GitHub sam wysyła mail o nowym issue (zero SMTP,
zero nowych sekretów; w workflow wystarczy `GITHUB_TOKEN` + `issues: write`).

Alarmowane zmiany: licznik sygnałów DNA, licznik SZCZYTU, nowe "gotowe"
transze DCA/sprzedaży. Logika porównania: src/logic/alerts.py (czysta).

Zasady bezpieczeństwa przebiegu:
  - brak poprzedniego odczytu (pierwszy dzień / świeża tabela) -> brak alertu,
  - KAŻDY błąd (BQ, config, GitHub API) -> log + exit 0. Alerty są best-effort;
    nie mogą zawalić crona ingestu (obserwowalność ingestu = exit code run_ingest).

Env:
  GITHUB_TOKEN, GITHUB_REPOSITORY (w Actions ustawione automatycznie),
  BTT_APP_URL (opcjonalnie — link do dashboardu w treści issue),
  BTT_DRY_RUN=1 albo --dry-run -> pokaż alerty, nie twórz issue.

Lokalne uruchomienie (diagnostyka):
  $env:GOOGLE_APPLICATION_CREDENTIALS = "...sa.json"; $env:GCP_PROJECT_ID = "..."
  python scripts/check_alerts.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys

# Importy jak w backfill_history.py — uruchamiane z korzenia repo.
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.join(_here, "..")
sys.path.insert(0, os.path.join(_root, "src", "logic"))
sys.path.insert(0, os.path.join(_root, "src", "warehouse"))
import alerts                  # type: ignore  # noqa: E402
import bigquery_client as wh   # type: ignore  # noqa: E402

DEFAULT_APP_URL = "https://btc-bottom-tracker-n5nan3lmjyvhyhcwprxqer.streamlit.app/"

# Kolumny potrzebne logice sygnałów (w tym computed: ath/halving/Pi Cycle).
_COLS = ["reading_date", "price_usd", "mvrv_z_score", "nupl", "ma_200w",
         "whale_accumulating", "whale_ratio", "fear_greed", "days_since_ath",
         "ath_date", "ma_111d", "ma_350d", "halving_date",
         "fed_funds_delta_3m", "dxy_delta_3m", "m2_yoy", "etf_flows_usd_7d"]


def _create_issue(payload: dict) -> bool:
    """POST /repos/{repo}/issues przez GITHUB_TOKEN. True gdy utworzone."""
    import requests
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("  ! Brak GITHUB_TOKEN/GITHUB_REPOSITORY — pomijam tworzenie issue.")
        return False
    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        json=payload,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
        timeout=20,
    )
    if resp.status_code == 201:
        print(f"  Issue utworzone: {resp.json().get('html_url')}")
        return True
    print(f"  ! GitHub API {resp.status_code}: {resp.text[:300]}")
    return False


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Alerty: porównaj dziś vs poprzedni odczyt.")
    parser.add_argument("--dry-run", action="store_true", help="pokaż alerty bez tworzenia issue")
    args = parser.parse_args()
    dry = args.dry_run or os.getenv("BTT_DRY_RUN") == "1"

    try:
        config = wh.read_config_thresholds()
        hist = wh.read_history(days=14, columns=_COLS)
        if hist is None or len(hist) < 2:
            print("Mniej niż 2 odczyty w historii — brak porównania, brak alertów.")
            return
        hist = hist.sort_values("reading_date")
        today_row = hist.iloc[-1].to_dict()
        prev_row = hist.iloc[-2].to_dict()

        # Plany transz — tolerancyjnie (brak tabeli/pusta -> None).
        try:
            dca_df = wh.read_dca_tranches()
        except Exception as exc:
            print(f"  ! dca_tranches niedostępne ({exc}) — transze DCA poza alertem.")
            dca_df = None
        sell_df = wh.read_sell_tranches()  # ma własny fallback (pusty DF)
        if sell_df is not None and getattr(sell_df, "empty", False):
            sell_df = None

        today = alerts.snapshot(config, today_row, dca_df, sell_df)
        prev = alerts.snapshot(config, prev_row, dca_df, sell_df)
        msgs = alerts.build_alerts(today, prev)

        d = today.reading_date, prev.reading_date
        print(f"Porównanie: {d[1]} -> {d[0]} | dno {prev.bottom_met}->{today.bottom_met}, "
              f"szczyt {prev.top_met}->{today.top_met}, "
              f"DCA ready {sorted(prev.dca_ready)}->{sorted(today.dca_ready)}, "
              f"EXIT ready {sorted(prev.exit_ready)}->{sorted(today.exit_ready)}")

        if not msgs:
            print("Brak zmian — brak alertu.")
            return
        payload = alerts.issue_payload(msgs, today, prev,
                                       app_url=os.getenv("BTT_APP_URL", DEFAULT_APP_URL))
        print("ALERTY:")
        for m in msgs:
            print("  -", m)
        if dry:
            print("--dry-run: issue NIE utworzone.")
            print(f"  Tytuł: {payload['title']}")
            return
        _create_issue(payload)
    except Exception as exc:
        # Best-effort: alerty nigdy nie walą crona.
        print(f"  ! check_alerts: błąd ({exc}) — pomijam (exit 0).")


if __name__ == "__main__":
    main()
