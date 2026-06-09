# STATUS / Handover — BTC Bottom Tracker

> Plik przekazania stanu między czatami w Projekcie. Aktualny stan: **05 (wariant Dash)
> ZAMKNIĘTE**. Projekt funkcjonalnie kompletny (demo + live).
> Wdrożone na Streamlit Community Cloud (APP_MODE=demo): https://btc-bottom-tracker-n5nan3lmjyvhyhcwprxqer.streamlit.app/ — repo PUBLICZNE.
> Architektura i instrukcje: README.md + docs/SETUP_GCP.md.
> Ostatnia aktualizacja: 2026-06-09.

---

## Gdzie jesteśmy

- [x] **00 — Architektura i setup** — ZROBIONE (fundamenty + pełny setup GCP na żywo).
- [x] **01 — Schemat danych** — ZROBIONE: DDL 3 tabel (`indicator_readings` native,
      `config_thresholds` + `dca_tranches` external/Sheets), moduł `src/warehouse/bigquery_client.py`
      (auth SA, ensure_dataset, upsert MERGE, read_history, read_config/dca), seed
      `data/seed_snapshot_2026-06-01.json` + CSV-y layoutu zakładek.
- [x] **02 — Ingestion (Sheets)** — ZROBIONE: `src/ingestion/sheets.py` (gspread; odczyt 3
      zakładek → DataFrame, walidacja, świeżość `assess_freshness`, mostek `build_reading_values`
      → `upsert_reading`). Layout: `docs/SHEETS_LAYOUT.md`.
- [x] **02-API — Ingestion (auto-fetch)** — ZROBIONE: `src/ingestion/price_binance.py`
      (cena spot Binance + 200W MA z tygodniowych zamknięć; fallback CoinGecko dla ceny),
      `src/ingestion/fear_greed_api.py` (alternative.me), `src/ingestion/run_ingest.py`
      (orkiestrator AUTO + ręczne z arkusza → `upsert_reading`). Dry-run zweryfikowany na żywo.
- [x] **03 — Logika sygnałów + Composite Bottom Score + werdykt** — ZROBIONE:
      `src/logic/composite.py` + `tests/test_signals.py` (**41 testów, wszystkie zielone**).
      Commit: `dba7fcb`. Szczegóły niżej.
- [x] **04 — UI Streamlit (jedna strona) + lekka logika DCA** — ZROBIONE:
      `app.py` (punkt wejścia, tylko UI), `src/config.py` (przełącznik demo/live),
      `src/ingestion/mock.py` (loader seeda), `src/logic/dca.py` (czysta logika DCA),
      `src/ui/components.py` + `src/ui/text_pl.py` (gauge, karty, wykresy, panel DCA),
      `tests/test_dca.py` (**16 testów**). Commit: `0878c3c`. Szczegóły niżej.
- [x] **05 — Wariant Dash** — ZROBIONE: `app_dash.py` (korzeń repo, obok app.py). Reużywa
      wspólnych warstw (config + composite.evaluate + dca.compute_dca_state + ingestion);
      z src/ui tylko `text_pl` (czysty), `components.py` NIE importowany. Commit: `d1342a2`.

---

## Krok 03 — co dokładnie powstało (źródło prawdy = kod w repo)

**`src/logic/composite.py`** — CZYSTA logika, zero I/O (nie importuje BigQuery/Streamlita/sieci).
- `evaluate(config, reading, graded_fng=False) -> CompositeResult` — główne wejście.
  - `config`: DataFrame **lub** list[dict] (kolumny: indicator, operator, threshold_value,
    threshold_value2, weight, active, description). Akceptuje wynik `read_config_thresholds()`
    (BQ) i `sheets.read_config`.
  - `reading`: Mapping / pandas.Series / dict / **1-wierszowy DataFrame**. Pasuje pod
    `sheets.latest_reading(...)` i `build_reading_values(...)`.
- `derive_values(reading)` — wartości testowalne: bezpośrednie z kolumn `indicator_readings`
  + **computed**. `price_to_200w_ratio = price_usd / ma_200w` liczone przez rejestr `COMPUTED`
  (dodanie nowego computed = jedna linia, bez ruszania reszty).
- `apply_operator(value, op, t1, t2)` — operatory `lt/lte/gt/gte/eq/is_true/between`
  (+ `is_false` defensywnie). Bool celowo **nie** przechodzi przez operatory liczbowe
  (whale nie da się przypadkiem porównać `>`). Brak danych/progu/nieznany operator → `met=None`.
- `graded_fear_greed(value)` — **hak** na wkład stopniowy F&G (pełny <10, liniowo 10–25,
  zero ≥25). Domyślnie NIEUŻYWANY; włącza go `evaluate(..., graded_fng=True)`.
- `build_verdict(...)` — opisowy werdykt PL (bez „kup/sprzedaj"), z liczbą brakujących danych.
- `CompositeResult` (pola): `count_met`, `count_active`, `count_evaluable`,
  `weighted_met`, `weighted_total`, `weighted_ratio`, `indicators[IndicatorResult]`,
  `verdict`, `warnings`, `as_of`, `disclaimer` (= stała `DISCLAIMER`).
- `results_to_dataframe(result)` — tabela wskaźników pod UI (gotowe pod krok 04).
- `LABELS` — czytelne PL etykiety wskaźników do UI.

**`tests/test_signals.py`** — 41 testów (operatory + granice, computed ratio, brak danych,
seed 2026-06-01, ważony score, granica F&G <25, hak graded, pełne dno 6/6, aktywność/wagi,
werdykt, pandas Series/DataFrame, locale). Uruchom: `python -m pytest tests/ -q`.

**Walidacja na seedzie 2026-06-01:** `count_met=1`, `count_evaluable=2` (F&G met + whale=False),
ważony `0.5/1.5` → dokładnie `expected_composite_count=1`.

---

## Decyzje kroku 03 (rozstrzygnięte — nie zmieniać bez powodu)

1. **Wkład do composite = binarnie wg configu + hak na stopniowy F&G (domyślnie OFF).**
   Licznik „ile z 6" jest CAŁKOWITY (spełniony = +1, niezależnie od wagi) → spójne z seedem
   `expected_composite_count=1`. Wagi wchodzą TYLKO do `weighted_*`. Tryb graded modyfikuje
   wyłącznie wkład ważony F&G, licznik zostaje binarny (test to pilnuje).
2. **„Okno zakupu" = OBA:** werdykt opisowy na liczniku `count_met`, ważony `weighted_ratio`
   jako niuans obok.
3. **`price_to_200w_ratio` = COMPUTED** (`price_usd/ma_200w`), nie kolumna w `indicator_readings`
   (zgodnie z DDL — tabela trzyma surowe odczyty, sygnały liczy Python).

---

## Decyzje kroku 04 (rozstrzygnięte — nie zmieniać bez powodu)

1. **Układ = jedna strona (scroll):** nagłówek z werdyktem + gauge → grid kart wskaźników →
   wykresy → panel DCA. Gauge oparty na liczniku `count_met/count_active`, `weighted_ratio`
   jako podtekst (zgodnie z decyzją 03: werdykt na liczniku, score jako niuans).
2. **Świeżość danych** przez `sheets.assess_freshness`; gdy wskaźnik `met=None` → karta
   „brak danych", composite **się NIE zeruje** (brak danych ≠ sygnał niespełniony).
3. **Live degraduje się łagodnie:** każde źródło (Sheets / Binance / F&G / BQ) w osobnym `try` —
   awaria jednego nie wywala całego UI. **Tryb demo nie importuje `google`/`gspread`**
   (czysty seed, zero zależności sieciowych/chmurowych).
4. **DCA — cena ręczna w UI** (`st.number_input`), bo seed ma `price_usd=null` — nie zgadujemy
   rynku. Logika `dca.py` jest czysta i opisowa (`price_reached` / `signals_ok` /
   `conditions_met`), bez „kup/sprzedaj".

---

## Decyzje zablokowane (z poprzednich kroków)

- **Hurtownia = Google BigQuery** (NIE Snowflake). Dataset `btc_tracker`, EU.
- **Tabele:** `indicator_readings` = NATIVE (upsert MERGE po dacie); `config_thresholds`
  + `dca_tranches` = EXTERNAL na Google Sheets. Env: `CONFIG_TABLE=config_thresholds_ext`,
  `DCA_TABLE=dca_tranches_ext`.
- **Scope SA:** `auth/bigquery` + `auth/drive` (full, nie readonly).
- **Whale:** sygnał dna = ręczna flaga `whale_accumulating` (operator `is_true`, NADRZĘDNA).
  `whale_ratio` tylko referencyjnie (orient. < 0.85), wpis ręczny przez Sheets.
- **Fear & Greed próg = `< 25`** (pasmo Extreme Fear alternative.me 0–24), **waga 0.5**.
- **Cena BTC / 200W MA:** Binance public API (bez klucza); CoinGecko fallback tylko dla ceny
  spot (dla 200W MA brak darmowego fallbacku — wtedy ma_200w=None + ostrzeżenie).
- **Zależności:** `pandas` ODPIĘTY (Streamlit 1.55.0 wymaga `pandas<3`; pip dobiera 2.3.x cp314).
  `requirements.lock.txt` zacommitowany.
- **Python 3.14**, Windows. Hosting docelowy = Streamlit Community Cloud z repo GitHub.
- **Tryby:** `APP_MODE=demo` (mock+seed) / `live` (BigQuery+Sheets); `BTT_DRY_RUN=1` dla ingestu.

---

## Repo / workflow

- **Repo GitHub: `github.com/SebastianPoplawski/btc-bottom-tracker` — PUBLICZNE (zmienione z prywatnego, by Streamlit Community Cloud widział repo; darmowy
  Community Cloud nie dawał dostępu do prywatnego repo). Historia zweryfikowana — brak
  realnych sekretów (tylko atrapy w secrets.toml.example); `.gitignore` blokuje klucze.** Źródło prawdy.
  Commity: `a6732e3` (00–02), `6625fb4` (02-API), `dba7fcb` (03), `11f1e68` (docs/hash 03),
  `0878c3c` (04).
- **Lokalnie:** `C:\Users\sebastian.poplawski\Projects\BTC Bottom Tracker`, venv `.venv`,
  Windows + PowerShell. Push przez **Claude Code** (lokalny git + `gh`).
- **git config:** `user.name="Sebastian Poplawski"`, `user.email="poplawski.sebastian94@gmail.com"`.
- **Struktura repo (po 04):**
  ```
  app.py                              (04 — punkt wejścia Streamlit, tylko UI)
  src/config.py                       (04 — przełącznik demo/live)
  src/warehouse/bigquery_client.py
  src/warehouse/ddl.sql
  src/ingestion/sheets.py
  src/ingestion/price_binance.py
  src/ingestion/fear_greed_api.py
  src/ingestion/run_ingest.py
  src/ingestion/mock.py               (04 — loader seeda dla trybu demo)
  src/logic/composite.py              (03)
  src/logic/dca.py                    (04 — czysta logika DCA)
  src/ui/components.py                (04 — gauge, karty, wykresy, panel DCA)
  src/ui/text_pl.py                   (04 — polskie napisy UI)
  data/  seed + 2 CSV
  docs/  SETUP_GCP, SETUP_GITHUB, SHEETS_LAYOUT, STATUS
  tests/test_signals.py               (03)
  tests/test_dca.py                   (04 — 16 testów)
  .streamlit/  config.toml, secrets.toml.example
  ```
- **Konektor GitHub w Claude:** dociąganie plików repo przez „+". Claude nie przegląda repo sam;
  push robi Claude Code lokalnie.

---

## Krok 05 — Dash (rozstrzygnięte)

1. **Zakres:** pełniejsza parzystość niż goły szkielet — header (cena/tryb/świeżość),
   gauge `count_met/count_active` + werdykt, 6 kart wskaźników, wykresy (cena vs 200W MA,
   MVRV/NUPL, F&G, whale_ratio ref.), panel DCA z polem ceny (seed ma price_usd=null),
   przycisk „Odśwież dane", stały disclaimer. UI po polsku.
2. **Współdzielenie warstw:** ścieżka ładowania danych 1:1 z app.py (_load_demo/_load_live).
   Z `src/ui/` reużyty TYLKO `text_pl` (bez Streamlita); `components.py` NIE importowany.
   Prosty cache: klik „Odśwież" przeładowuje dane, zmiana ceny korzysta z cache.
3. **Hosting:** lokalnie (`app.run`, 127.0.0.1:8050), bez deployu. `server = app.server`
   zostawiony pod ewentualny WSGI/gunicorn.

---

## Wdrożenie (Streamlit Community Cloud)

- App URL: https://btc-bottom-tracker-n5nan3lmjyvhyhcwprxqer.streamlit.app/ (publiczny).
  Main file: `app.py`, branch `main`, Python 3.14.
- `APP_MODE=demo` (seed, bez chmury) — build na 3.14 przeszedł, dashboard renderuje się
  w całości (gauge 1/6, 6 kart, panel DCA, wykresy, disclaimer). Potwierdzone na żywo.
- Auto-redeploy po każdym `git push` na `main`.
- Wariant Dash (app_dash.py) NIE jest deployowany — Streamlit Cloud go nie uruchamia
  (inny runtime); pozostaje lokalny.
- Przejście na LIVE bez redeployu: Manage app -> Settings -> Secrets -> wklej treść
  lokalnego secrets.toml (z kluczem JSON) i zmień APP_MODE na "live" (propaguje ~minutę).
  Wymaga wcześniej domknięcia sekcji "Do zrobienia ręcznie" (DDL + 3 zakładki w arkuszu).
- Klucz JSON NIGDY do repo (repo publiczne!) — tylko panel Secrets. .gitignore to egzekwuje,
  ale przy każdym pushu sprawdzaj listę plików (SETUP_GITHUB.md krok 5).

---

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

---

## Dług techniczny (do sprzątnięcia — NIE blokuje 05)

- **FIX (krok 04): `text_pl.STATUS_PL` brakujące.** `components.dca_panel` wołał `T.STATUS_PL`,
  którego nie było w `text_pl.py` → `AttributeError` przy renderze DCA w Streamlicie. Dodano
  `STATUS_PL` do `text_pl.py`. Commit: `914d7f0`. Wariant Dash używał `dca.STATUS_PL` (odporny).
  Potwierdzony na żywo na deployu — panel DCA renderuje się poprawnie.
- **Master prompt (poza repo): „F&G < 20" → „< 25".** README.md i `ddl.sql` już poprawione
  (commit `11f1e68`), ale master prompt Projektu wciąż mówi „< 20" → zaktualizować ręcznie
  na **„< 25"** (zgodnie z configiem i `composite.py`). Niezrobione.

## Do zrobienia ręcznie zanim ruszy LIVE (po stronie użytkownika)

1. Uruchomić DDL z `src/warehouse/ddl.sql` (tabele native + external).
2. W arkuszu: 3 zakładki `indicator_readings`, `config_thresholds`, `dca_tranches`. Wkleić
   `data/sheets_tab_config_thresholds.csv` (A:G) i `sheets_tab_dca_tranches.csv` (A:I).
   Nagłówki `indicator_readings` wg `docs/SHEETS_LAYOUT.md`.
3. Uzupełnić wartości ręczne (`mvrv_z_score`, `nupl`, `whale_accumulating`, `ath_date`).
4. Sekrety: skopiować `.streamlit/secrets.toml.example` → `secrets.toml`, wkleić pola klucza JSON,
   `APP_MODE="live"`.

---

## Pułapki napotkane (żeby nie powtarzać)

- **Org secure-by-default** włączała `iam.disableServiceAccountKeyCreation` — rozwiązane rolą
  `orgpolicy.policyAdmin` na poziomie organizacji `poplawski-sebastian94-org`.
- External nad Sheets bez scope `auth/drive` => 403.
- **Konflikt zależności:** `pandas==3.0.3` × `streamlit<3` → ResolutionImpossible. Fix: odpiąć pandas.
- **PowerShell ≠ cmd:** `set VAR=1` nie działa; używać `$env:VAR = "1"`. venv: `.venv\Scripts\activate`.
- **02-API live (2026-06-08):** dry-run zwrócił price_usd≈63941, ma_200w≈61827, **fear_greed=8**
  (głęboki Extreme Fear; snapshot z 1.06 miał ~23 — sentyment mocno spadł). F&G<25 dalej aktywny.
- **03 — schemat indicatorów:** w configu klucz to `mvrv_z_score`/`nupl`/`fear_greed`/
  `days_since_ath`/`whale_accumulating` (1:1 z kolumnami readings) ORAZ `price_to_200w_ratio`
  (computed, NIE kolumna). `composite.derive_values` to obsługuje — przy dodaniu wskaźnika
  pamiętać o tej różnicy.
- **03 — bool vs liczba:** `whale_accumulating` jest bool; operatory liczbowe celowo go
  odrzucają (`_to_number` zwraca None dla bool), więc działa tylko `is_true`.

## Czego pilnować

- Klucz JSON: NIGDY do repo/na czat/na publiczne foldery. Tylko lokalnie + panel Streamlit Cloud.
- Repo PUBLICZNE — `.gitignore` i tak blokuje sekrety; sprawdzać listę przed pushem.
- Zapytania BQ: `SELECT` tylko potrzebnych kolumn + filtr po dacie (free tier 1 TB/mies.).
- **Fixture vs config:** `seed_snapshot_2026-06-01.json` ma `expected_composite_count=1` Z REGUŁY
  (F&G<25). Przy zmianie progu/odczytu zaktualizować seed — demo, `test_signals.py` i
  `composite.py` nie mogą się rozjeżdżać.
- W UI zawsze disclaimer: „narzędzie analityczne, nie porada inwestycyjna" (stała
  `composite.DISCLAIMER` + pole `CompositeResult.disclaimer`).
- **Metodologia:** framework = strukturalny obiektyw, NIE zwalidowany predyktor (~3–4 dna, 6
  parametrów → fit gwarantowany; MVRV Z i NUPL redundantne). Werdykt opisowy, bez „kup/sprzedaj".

## Pomocne: co Claude może zrobić sam w Projekcie

- **Attach z GitHub przez „+"**: dociągnąć aktualne pliki repo do rozmowy (źródło prawdy).
- **Google Drive**: czytać/kopiować/tworzyć pliki (głównie pod arkusz).
- Czego NIE: konsola GCP (IAM/API/dataset/klucze), push na GitHub (robi Claude Code lokalnie),
  pisanie po komórkach istniejącego arkusza (layout ręcznie albo przez gspread).
