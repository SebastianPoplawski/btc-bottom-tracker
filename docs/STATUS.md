# STATUS / Handover — BTC Bottom Tracker

> Plik przekazania stanu między czatami w Projekcie. Aktualny stan: **02 + 02-API
> (ingestion) ZAMKNIĘTE**. Następny krok: **03 — logika sygnałów + Composite Bottom Score**.
> Architektura i instrukcje: README.md + docs/SETUP_GCP.md.
> Ostatnia aktualizacja: 2026-06-08.

---

## Gdzie jesteśmy

- [x] **00 — Architektura i setup** — ZROBIONE (fundamenty + pełny setup GCP na żywo).
- [x] **01 — Schemat danych** — ZROBIONE: DDL 3 tabel (`indicator_readings` native,
      `config_thresholds` + `dca_tranches` external/Sheets), moduł dostępu
      `src/warehouse/bigquery_client.py` (auth SA, ensure_dataset, upsert MERGE, read_history,
      read_config/dca), seed `data/seed_snapshot_2026-06-01.json` + CSV-y layoutu zakładek.
- [x] **02 — Ingestion (Sheets)** — ZROBIONE: `src/ingestion/sheets.py` (gspread; odczyt 3
      zakładek do DataFrame, walidacja, świeżość `assess_freshness`, mostek `build_reading_values`
      → `upsert_reading`). Layout arkusza: `docs/SHEETS_LAYOUT.md`.
- [x] **02-API — Ingestion (auto-fetch)** — ZROBIONE: `src/ingestion/price_binance.py`
      (cena spot Binance + 200W MA z tygodniowych zamknięć; fallback CoinGecko dla ceny),
      `src/ingestion/fear_greed_api.py` (alternative.me), `src/ingestion/run_ingest.py`
      (orkiestrator: AUTO + ręczne z arkusza → `upsert_reading`). Dry-run zweryfikowany na żywo
      (price/ma_200w/fear_greed pobrane OK). retry (`tenacity`), cache (`st.cache_data` w
      Streamlit, no-op poza).
- [ ] **03 — Logika sygnałów + Composite Bottom Score + werdykt** — NASTĘPNY KROK.
      `src/logic/composite.py` + `tests/test_signals.py`. Czyta `config_thresholds`
      (operatory `lt/lte/gt/gte/eq/is_true/between`), liczy `price_to_200w_ratio =
      price_usd/ma_200w` (computed, nie ze schematu), ocenia każdy wskaźnik → composite + werdykt PL.
- [ ] 04 — UI Streamlit (karty, gauge, wykresy, moduł DCA) — `app.py`, `src/ui/`.
- [ ] 05 — Wariant Dash (szkielet do porównania).

## Repo / workflow (NOWE)

- **Repo GitHub: `github.com/SebastianPoplawski/btc-bottom-tracker` — PRYWATNE.** To jest
  źródło prawdy. Commity: `a6732e3` (00-02 fundamenty+schemat+reorg), `6625fb4` (02-API + fix pandas).
- **Lokalnie:** `C:\Users\sebastian.poplawski\Projects\BTC Bottom Tracker`, venv `.venv`,
  Windows + PowerShell. Push przez **Claude Code** (lokalny git + `gh`).
- **git config (ustawione):** `user.name="Sebastian Poplawski"`,
  `user.email="poplawski.sebastian94@gmail.com"`. (Commity `a6732e3`/`6625fb4` mają jeszcze
  stary służbowy e-mail — zostawione świadomie, nie przepisujemy historii.)
- **Struktura po reorganizacji:**
  ```
  src/warehouse/bigquery_client.py   (był bigquery_warehouse.py)
  src/warehouse/ddl.sql              (był btc_bottom_tracker_schema.sql)
  src/ingestion/sheets.py            (był sheets_ingest.py)
  src/ingestion/price_binance.py     (02-API)
  src/ingestion/fear_greed_api.py    (02-API)
  src/ingestion/run_ingest.py        (02-API, orkiestrator)
  data/  seed + 2 CSV
  docs/  SETUP_GCP, SETUP_GITHUB, SHEETS_LAYOUT, STATUS
  .streamlit/  config.toml, secrets.toml.example
  ```
- **Drive:** już TYLKO żywy arkusz „BTC Bottom Tracker — dane" (warstwa danych). Kopie kodu
  na Drive są zbędne — źródłem prawdy jest repo.
- **Konektor GitHub w Claude:** połączony na koncie; w czacie działa „attach files via +"
  (dociąganie plików z repo do rozmowy). NIE wystawia narzędzi agentowych w Projekcie — Claude
  nie przegląda repo sam; pliki dodaje się przez **+** albo wkleja. Push robi Claude Code lokalnie.

## Decyzje zablokowane (nie zmieniać bez powodu)

- **Hurtownia = Google BigQuery** (NIE Snowflake). Dataset `btc_tracker`, EU (istnieje).
- **Architektura tabel:** `indicator_readings` = NATIVE (upsert MERGE po dacie);
  `config_thresholds` + `dca_tranches` = EXTERNAL na Google Sheets. Default env:
  `CONFIG_TABLE=config_thresholds_ext`, `DCA_TABLE=dca_tranches_ext`.
- **Scope SA:** `auth/bigquery` + `auth/drive` (full, nie readonly).
- **Whale:** sygnał dna = ręczna flaga `whale_accumulating` (operator `is_true`, NADRZĘDNA).
  `whale_ratio` tylko referencyjnie (orient. < 0.85), wpis ręczny przez Sheets.
- **Fear & Greed próg = `< 25`** (pasmo Extreme Fear alternative.me 0–24), **waga 0.5**.
  - DOC do poprawy: README i master prompt mówią jeszcze „< 20" → zaktualizować na „< 25".
  - TODO krok 03: rozważyć zdjęcie binarności F&G (wkład stopniowy: 0 dla >25, częściowy 10–24,
    pełny <10). Composite ważony (kolumna `weight`).
- **Cena BTC / 200W MA:** Binance public API (bez klucza); CoinGecko fallback dla ceny spot
  (dla 200W MA brak darmowego fallbacku — wtedy ma_200w=None + ostrzeżenie).
- **Zależności:** `pandas` ODPIĘTY (`==3.0.3` → `pandas`), bo Streamlit 1.55.0 wymaga
  `pandas<3`. pip dobrał `pandas-2.3.3` (cp314). `requirements.lock.txt` zacommitowany.
- **Python 3.14**, Windows. Hosting docelowy = Streamlit Community Cloud z repo GitHub.
- **Tryby:** `APP_MODE=demo` (mock+seed) / `live` (BigQuery+Sheets); `BTT_DEMO=1` / dry-run.

## DO ROZSTRZYGNIĘCIA na start kroku 03 (otwarte)

1. **Wkład wskaźników do composite:** binarnie wg config (spełniony = pełna waga) vs wkład
    stopniowy dla F&G. Rekomendacja Claude: **binarnie teraz + hak na stopniowy później**
    (spójne z seedem `expected_composite_count=1` i `test_signals.py`).
2. **„Okno zakupu":** licznik (ile z 6) vs ważony score vs oba. Rekomendacja Claude: **oba**
    (werdykt na liczniku, score jako niuans).
   > Użytkownik jeszcze nie potwierdził — dopytać na początku 03.

## Konfiguracja na żywo (do secrets.toml — KLUCZA JSON tu NIE MA)

| Klucz | Wartość |
|---|---|
| `GCP_PROJECT_ID` | `btc-bottom-tracker-498120` |
| `BQ_DATASET` | `btc_tracker` |
| `BQ_LOCATION` | `EU` |
| `GOOGLE_SHEET_ID` | `19GCtFyNBKBEj3-jWOLYfNBEd-7jVIXigkDJBGW0vHRY` |
| `CONFIG_TABLE` | `config_thresholds_ext` (native: `config_thresholds`) |
| `DCA_TABLE` | `dca_tranches_ext` (native: `dca_tranches`) |
| service account | `btc-tracker-sa@btc-bottom-tracker-498120.iam.gserviceaccount.com` |
| plik klucza | `btc-bottom-tracker-498120-56eabcdb1342.json` (lokalnie u użytkownika) |

Stan GCP: projekt + billing (alert $1); API (BigQuery/Sheets/Drive) on; dataset `btc_tracker`
w EU; SA z rolami (Editor/Viewer — do zwężenia do `BigQuery Job User` + `Data Editor`); arkusz
udostępniony SA jako writer.

## Do zrobienia ręcznie zanim ruszy LIVE (po stronie użytkownika)

1. Uruchomić DDL z `src/warehouse/ddl.sql` (tabele native + external).
2. W arkuszu: 3 zakładki `indicator_readings`, `config_thresholds`, `dca_tranches`. Wkleić
   `data/sheets_tab_config_thresholds.csv` (A:G) i `sheets_tab_dca_tranches.csv` (A:I).
   Nagłówki `indicator_readings` wg `docs/SHEETS_LAYOUT.md`.
3. Uzupełnić wartości ręczne (`mvrv_z_score`, `nupl`, `whale_accumulating`, `ath_date`).
4. Sekrety: skopiować `.streamlit/secrets.toml.example` → `secrets.toml`, wkleić pola klucza JSON,
   `APP_MODE="live"`. Wtedy `run_ingest.py` dopisze AUTO + ręczne do `indicator_readings`.

## Pułapki napotkane (żeby nie powtarzać)

- **Org secure-by-default** włączała `iam.disableServiceAccountKeyCreation` — rozwiązane rolą
  `orgpolicy.policyAdmin` na poziomie organizacji `poplawski-sebastian94-org`.
- External nad Sheets bez scope `auth/drive` => 403.
- **Konflikt zależności:** `pandas==3.0.3` × `streamlit<3` → ResolutionImpossible. Fix: odpiąć pandas.
- **PowerShell ≠ cmd:** `set VAR=1` nie działa; używać `$env:VAR = "1"`. venv: `.venv\Scripts\activate`.
- **Niespójność słownika statusów DCA:** `ddl.sql` (komentarz) mówi `pending|filled|skipped`,
  a `sheets.py` waliduje `{pending, executed, skipped}`. Kolumny to `executed_*` → ujednolicić na
  **`executed`** (poprawić komentarz w ddl.sql). DO ZROBIENIA przy 03/DCA.
- **02-API live (2026-06-08):** dry-run zwrócił price_usd≈63941, ma_200w≈61827, **fear_greed=8**
  (głęboki Extreme Fear; snapshot z 1.06 miał ~23 — sentyment mocno spadł). F&G<25 dalej aktywny.
- `run_ingest.py` import ma fallback na `sys.path` (działa jako skrypt i jako pakiet). Gdy 04
  zacznie importować jako pakiet — rozważyć puste `__init__.py`.

## Czego pilnować

- Klucz JSON: NIGDY do repo/na czat/na publiczne foldery. Tylko lokalnie + panel Streamlit Cloud.
- Repo PRYWATNE — `.gitignore` i tak blokuje sekrety; sprawdzać listę przed pushem.
- Zapytania BQ: `SELECT` tylko potrzebnych kolumn + filtr po dacie (free tier 1 TB/mies.).
- Fixture vs config: `seed_snapshot_2026-06-01.json` ma `expected_composite_count=1` Z REGUŁY
  (F&G<25). Przy zmianie progu/odczytu zaktualizować — demo i `test_signals.py` nie mogą się
  rozjeżdżać z configiem.
- W UI zawsze disclaimer: „narzędzie analityczne, nie porada inwestycyjna".
- **Metodologia:** framework = strukturalny obiektyw, NIE zwalidowany predyktor (~3–4 dna, 6
  parametrów → fit gwarantowany; MVRV Z i NUPL redundantne). Werdykt opisowy, bez „kup/sprzedaj teraz".

## Pomocne: co Claude może zrobić sam w Projekcie

- **Attach z GitHub przez +**: dociągnąć aktualne pliki repo do rozmowy (źródło prawdy).
- **Google Drive**: czytać/kopiować/tworzyć pliki (już głównie pod arkusz).
- Czego NIE: konsola GCP (IAM/API/dataset/klucze), push na GitHub (to robi Claude Code lokalnie),
  pisanie po komórkach istniejącego arkusza (layout ręcznie albo przez gspread).
