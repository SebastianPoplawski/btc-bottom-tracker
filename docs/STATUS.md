# STATUS / Handover — BTC Bottom Tracker

> Plik przekazania stanu miedzy czatami w Projekcie. Aktualny stan: **01 (schemat danych)
> ZAMKNIETE**. Architektura i instrukcje: README.md + docs/SETUP_GCP.md.
> Ostatnia aktualizacja: 2026-06-02.

---

## Gdzie jestesmy

- [x] **00 — Architektura i setup** — ZROBIONE (pliki fundamentow + pelny setup GCP na zywo).
- [x] **01 — Schemat danych** — ZROBIONE: DDL 3 tabel (`indicator_readings` native,
      `config_thresholds` + `dca_tranches` external/Sheets), modul dostepu `bigquery_warehouse.py`
      (auth SA, ensure_dataset, upsert MERGE, read_history, read_config/dca), seed
      `seed_snapshot_2026-06-01.json` + CSV-y layoutu zakladek arkusza.
- [ ] **02 — Ingestion** — NASTEPNY KROK: Binance (tygodniowe zamkniecia -> 200W MA),
      Fear&Greed (alternative.me), odczyt Sheets (gspread) + cache. Dopisanie odczytow do
      `indicator_readings` przez upsert. Naglowki 3. zakladki arkusza (`indicator_readings`).
- [ ] 03 — Logika sygnalow + Composite Bottom Score + werdykt
- [ ] 04 — UI Streamlit (karty, gauge, wykresy, modul DCA)
- [ ] 05 — Wariant Dash (szkielet do porownania)

## Decyzje zablokowane (nie zmieniac bez powodu)

- **Hurtownia = Google BigQuery** (NIE Snowflake — starszy master prompt wspominal Snowflake,
  ale obowiazuje BigQuery z instrukcji Projektu). Dataset `btc_tracker`, EU (juz istnieje).
- **Architektura tabel:**
  - `indicator_readings` = **NATIVE** (rosnaca historia, upsert MERGE po dacie, tanie zapytania
    po dacie). NIE externalizowac.
  - `config_thresholds` + `dca_tranches` = **EXTERNAL na Google Sheets** (live-edit, zero ETL).
    Default w module: `CONFIG_TABLE=config_thresholds_ext`, `DCA_TABLE=dca_tranches_ext`.
    Przelacznik na native = zmiana tych zmiennych env (tabele native tez sa w DDL).
- **Scope SA przy external nad Sheets:** `auth/bigquery` + **`auth/drive`** (inaczej 403 przy
  odczycie arkusza). Ustawione w `bigquery_warehouse.py: _SCOPES`. gspread (krok 02) i tak
  potrzebuje pelnego Drive do zapisu.
- **Whale:** sygnalem dna jest **reczna flaga boolean `whale_accumulating`** (TRUE/FALSE),
  operator `is_true`, NADRZEDNA. Liczbowy `whale_ratio` = Exchange Whale Ratio 72h MA
  (CryptoQuant), trzymany tylko **referencyjnie** (orient. < 0.85). Wpis **reczny przez Sheets**,
  bez platnego API on-chain (zgodnie z "czego unikac").
- **Fear & Greed prog = `< 25`** = udokumentowane pasmo **Extreme Fear** alternative.me (0-24).
  Niearbitralny/odtwarzalny (NIE 20 — to liczba "na oko" wewnatrz pasma). F&G ma **niska wage
  0.5** w composite (najslabszy/najszumniejszy sygnal).
  - DOC do poprawy: README i master prompt mowia jeszcze "< 20" — zaktualizowac na "< 25".
  - TODO krok 03: **zdjac binarnosc F&G** (wklad stopniowy: 0 dla >25, czesciowy 10-24,
    pelny <10); rozwazyc to samo dla innych progow binarnych. Composite **wazony** (kolumna
    `weight` juz w config_thresholds).
- **Cena BTC / 200W MA:** Binance public API (bez klucza), **CoinGecko jako ewentualny fallback**.
- **Python 3.14** (najnowszy stabilny). Streamlit Cloud domyslnie proponuje **3.12** — przy
  deployu trzeba recznie wybrac 3.14 w Advanced settings. `pandas==3.0.3` ma wheele cp314 (Windows OK).
- **Hosting = Streamlit Community Cloud** z publicznego repo GitHub. Sekrety przez panel, nie w repo.
- **OS uzytkownika = Windows.** Tryby `APP_MODE=demo` (mock+seed, bez chmury) / `live` (BigQuery+Sheets).

## Konfiguracja na zywo (do secrets.toml — KLUCZA JSON tu NIE MA i miec nie bedzie)

| Klucz | Wartosc |
|---|---|
| `GCP_PROJECT_ID` | `btc-bottom-tracker-498120` |
| `BQ_DATASET` | `btc_tracker` |
| `BQ_LOCATION` | `EU` (multi-region) |
| `GOOGLE_SHEET_ID` | `19GCtFyNBKBEj3-jWOLYfNBEd-7jVIXigkDJBGW0vHRY` |
| `CONFIG_TABLE` | `config_thresholds_ext` (external; native: `config_thresholds`) |
| `DCA_TABLE` | `dca_tranches_ext` (external; native: `dca_tranches`) |
| service account email | `btc-tracker-sa@btc-bottom-tracker-498120.iam.gserviceaccount.com` |
| plik klucza | `btc-bottom-tracker-498120-56eabcdb1342.json` (trzymany lokalnie u uzytkownika) |

Stan GCP: projekt + billing z alertem $1; API (BigQuery, Sheets, Drive) wlaczone; dataset
`btc_tracker` w EU utworzony; SA ma role (Editor/Viewer na projekcie — DO ZWEZENIA pozniej do
`BigQuery Job User` + `BigQuery Data Editor`); arkusz utworzony i udostepniony SA jako **writer**
(zweryfikowane przez odczyt uprawnien).

## Do zrobienia recznie zanim ruszy live (po stronie uzytkownika)

1. Uruchomic DDL z `btc_bottom_tracker_schema.sql` (tworzy tabele native + external; INSERT seed
   configu jest dla wariantu native — przy external progi wpisujesz w arkuszu).
2. W arkuszu utworzyc 3 zakladki: `indicator_readings`, `config_thresholds`, `dca_tranches`.
   Wkleic `sheets_tab_config_thresholds.csv` (A:G) i `sheets_tab_dca_tranches.csv` (A:I).
   Zakladke `indicator_readings` (naglowki) ustawi krok 02.
3. Uzupelnic w seedzie/arkuszu wartosci `null` (mvrv_z_score, nupl, days_since_ath, ath_date);
   price/200W MA wejda z API w trybie live.

## Pulapki napotkane (zeby nie powtarzac)

- **Organizacja secure-by-default** automatycznie wlaczyla zasade `iam.disableServiceAccountKeyCreation`,
  co blokowalo tworzenie klucza JSON. Rozwiazane: nadanie roli `roles/orgpolicy.policyAdmin`
  na poziomie **organizacji** `poplawski-sebastian94-org`, potem wylaczenie egzekwowania zasady.
  (UWAGA: "Administrator organizacji" to NIE to samo co "Administrator zasad organizacji".)
- External nad Sheets bez scope `auth/drive` => 403. (Pelny Drive, nie readonly — pod gspread.)
- Przy udostepnianiu arkusza SA pojawia sie ostrzezenie "nie znaleziono konta Google" — **jest
  niegrozne**, udostepnienie i tak dziala (SA nie ma profilu Gmaila).
- F&G: prog `< 20` to liczba "na oko" w srodku pasma Extreme Fear (0-24). Spojny wybor to
  `< 25` (pasmo dostawcy) albo `< 15` (kapitulacja) — nie 20.

## Czego pilnowac

- Klucz JSON: NIGDY do repo / na czat / do publicznych folderow. Tylko lokalnie + panel Streamlit Cloud.
- Repo PUBLICZNE — `.gitignore` blokuje sekrety; sprawdzic przed pushem. (Project/dataset/sheet ID
  w plikach to identyfikatory, nie sekrety — bez klucza nieuzyteczne.)
- Zapytania BQ: `SELECT` tylko potrzebnych kolumn + filtr po dacie (free tier 1 TB/mies.).
- Fixture vs config: `seed_snapshot_2026-06-01.json` ma `expected_composite_count=1` wyliczone
  Z REGULY (F&G<25). Przy kazdej zmianie progu/odczytu zaktualizowac te pola — demo i
  `test_signals.py` nie moga sie rozjezdzac z configiem.
- W UI zawsze disclaimer: "narzedzie analityczne, nie porada inwestycyjna".

## Pomocne: co Claude moze zrobic sam w tym Projekcie

- Przez konektor **Google Drive**: czytac/kopiowac/tworzyc pliki i sprawdzac uprawnienia.
  UWAGA: konektor Drive NIE pisze po komorkach/zakladkach istniejacego arkusza — layout
  zakladek robi sie recznie (wklejenie CSV) albo programowo przez `gspread` (krok 02).
- Czego NIE moze: konsola GCP (IAM, API, dataset, klucze), udostepnianie Drive, push na GitHub.
