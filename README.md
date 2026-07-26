# BTC Bottom Tracker

Dashboard monitorujacy cykliczne **dno i szczyt Bitcoina** wg frameworka wskaznikow
on-chain i sentymentu. Liczy dwa zbiorcze wyniki — **Composite Bottom Score**
("ile sygnalow dna spelnionych jednoczesnie") i **Composite Top Score** (sygnaly
szczytu: MVRV Z, NUPL, cena/200W MA, F&G, Pi Cycle, czas od halvingu) — oraz
OSOBNY licznik **makro risk-off** (Fed, dolar, M2, ETF flows; poza frameworkiem).
Prowadzi plan zakupow transzami (DCA) i lustrzany **plan transz sprzedazy**.

> ⚠️ **To narzedzie analityczne, nie porada inwestycyjna.** Wskazniki, progi i werdykty
> to wbudowany framework uzytkownika — dashboard pokazuje, co mowia dane wg tych regul.

---

## Stos

| Warstwa | Technologia |
|---|---|
| UI / logika | Python 3.14 + **Streamlit** (domyslnie), Dash jako wariant |
| Reczne dane + config | Google Sheets (`gspread` + service account) |
| Hurtownia / historia | Google **BigQuery** (darmowy tier 10 GB / 1 TB zapytan mies.) |
| Ceny / sentyment | Binance public API (200W MA, 111/350DMA; fallback Kraken), alternative.me (Fear & Greed) |
| Makro (risk-off) | FRED API (DFF, DTWEXBGS, M2SL) — darmowy klucz `FRED_API_KEY`; ETF flows recznie |
| Hosting | Streamlit Community Cloud (deploy z publicznego repo GitHub) |

**Tryby:** `APP_MODE=demo` dziala od razu na danych seed (bez chmury);
`APP_MODE=live` korzysta z realnego BigQuery + Sheets.

---

## Drzewo plikow

```
btc-bottom-tracker/
├── app.py                      # Streamlit — punkt wejscia (TYLKO warstwa UI)
├── app_dash.py                 # Wariant Dash (szkielet do porownania)
├── requirements.txt            # zaleznosci (przypiete wersje)
├── .python-version             # 3.14
├── .gitignore                  # blokuje sekrety w publicznym repo
├── .env.example                # szablon zmiennych srodowiskowych (lokalnie)
├── README.md
├── .streamlit/
│   ├── config.toml             # motyw + serwer (bezpieczne do commitu)
│   └── secrets.toml.example    # szablon sekretow; realny secrets.toml = gitignored
├── src/
│   ├── config.py               # ladowanie ustawien/sekretow, wybor demo/live
│   ├── ingestion/              # ZRODLA DANYCH (oddzielone od logiki sygnalow)
│   │   ├── price_binance.py    #   zamkniecia tygodniowe (200W MA) + dzienne (111/350DMA); fallback Kraken
│   │   ├── fear_greed_api.py   #   alternative.me
│   │   ├── fred_api.py         #   makro FRED: Fed, dolar, M2 (krok 15)
│   │   ├── sheets.py           #   gspread: reczne wskazniki, progi, DCA, sell
│   │   ├── run_ingest.py       #   orkiestrator dziennego ingestu (cron CI)
│   │   └── mock.py             #   dane seed/demo (snapshot 2026-06-01)
│   ├── warehouse/
│   │   ├── bigquery_client.py  #   odczyt/zapis BQ, zapytania oszczedne kosztowo
│   │   └── ddl.sql             #   definicje tabel (native + external/Sheets)
│   ├── logic/
│   │   ├── composite.py        #   sygnaly bottom/top/macro (side) + werdykty
│   │   ├── dca.py              #   plan zakupow transzami
│   │   └── exit_plan.py        #   plan transz sprzedazy (lustro DCA; krok 16)
│   └── ui/
│       ├── components.py       #   zegary / karty / panele / wykresy
│       └── text_pl.py          #   polskie napisy UI + disclaimer
├── scripts/
│   ├── add_reading.py          # tygodniowy wpis reczny do arkusza (upsert)
│   ├── backfill_history.py     # arkusz -> BigQuery (idempotentny MERGE)
│   ├── bootstrap_sheet.py      # zakladki arkusza + niedestrukcyjny upgrade v13
│   └── migrate_13.py           # migracja schematu v13 (external DDL)
├── data/
│   └── seed_snapshot_2026-06-01.json (+ CSV layoutow zakladek)
├── docs/
│   └── SETUP_GCP.md, SETUP_GITHUB.md, SHEETS_LAYOUT.md, STATUS.md
└── tests/                      # pytest — 138 testow (logika, schemat, ingestion, plany)
```

**Zasada architektury:** `ingestion` (skad dane) ⟂ `logic` (jak liczymy sygnaly)
⟂ `ui` (jak pokazujemy). Progi i strony sygnalow (`side`: bottom/top/macro) zyja
w configu (arkusz/BQ) — dodanie wskaznika = wiersz w configu (+ ew. computed w
`composite.py`), zero zmian w UI.

---

## Sekrety i zmienne srodowiskowe

| Klucz | Co to | Gdzie |
|---|---|---|
| `gcp_service_account` | **klucz JSON service accounta (TAJNE)** — BigQuery + Sheets | `secrets.toml` / panel Streamlit Cloud |
| `GCP_PROJECT_ID` | ID projektu GCP | `secrets.toml` / `.env` |
| `BQ_DATASET` | dataset, np. `btc_tracker` | jw. |
| `BQ_LOCATION` | lokalizacja, `EU` | jw. |
| `GOOGLE_SHEET_ID` | ID arkusza z URL | jw. |
| `FRED_API_KEY` | darmowy klucz FRED (makro; opcjonalny — bez niego pola makro puste) | `secrets.toml` / env / GitHub Secret |
| `APP_MODE` | `demo` lub `live` | jw. |

- **Lokalnie:** skopiuj `.streamlit/secrets.toml.example` -> `.streamlit/secrets.toml` i uzupelnij.
- **Streamlit Cloud:** wklej tresc `secrets.toml` w *App settings -> Secrets*.
- Realny `secrets.toml`, `.env` i pliki kluczy sa w `.gitignore` — **nie trafiaja do repo**.

Pelna instrukcja zalozenia projektu, API, datasetu i service accounta: **`docs/SETUP_GCP.md`**.

---

## Uruchomienie lokalne (Windows)

Wymaga Pythona 3.14 z <https://python.org> (przy instalacji zaznacz *Add to PATH*).

```bat
:: w katalogu projektu
py -3.14 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

:: po pierwszej udanej instalacji — zablokuj pelny zestaw wersji:
pip freeze > requirements.lock.txt

streamlit run app.py
```

Aplikacja otworzy sie w przegladarce (`http://localhost:8501`).
Bez skonfigurowanej chmury ustaw `APP_MODE = "demo"` w `secrets.toml` — ruszy na seedzie.

---

## Deploy na Streamlit Community Cloud

1. Wypchnij projekt do **publicznego** repo na GitHub.
2. <https://share.streamlit.io> -> *New app* -> wskaz repo, branch, `app.py`.
3. **Advanced settings -> Python version -> 3.14** (domyslnie proponuje 3.12!).
4. **Secrets** -> wklej tresc `secrets.toml`.
5. Deploy. Aktualizacja nastepuje automatycznie po `git push`.

> Apki hostowane sa w USA i moga "zasypiac" przy braku ruchu — przy ponownym wejsciu
> wstaja w kilka sekund. Dla osobistego dashboardu bez znaczenia.

---

## Status budowy

- [x] 00 — Architektura i setup
- [x] 01 — Schemat danych: DDL BigQuery + layout Google Sheets + seed
- [x] 02 — Ingestion (Binance, Fear & Greed, Sheets) + cache
- [x] 03 — Logika sygnalow + Composite Score + werdykt
- [x] 04 — UI Streamlit (karty, gauge, wykresy, modul DCA)
- [x] 05 — Wariant Dash (lokalny; bottom-only)
- [x] 07–12 — fallbacki Kraken, computed days_since_ath, historia BQ, composite v2,
      automatyzacja (GitHub Actions cron)
- [x] **13–18 — Warstwa sprzedazy + makro:** kolumna `side` w configu (bottom/top/macro),
      sygnaly szczytu (MVRV Z>5, NUPL>0.7, cena>=2.5x 200W MA, F&G>75 graded, Pi Cycle,
      12–18 mies. od halvingu), osobny licznik makro risk-off (FRED + ETF flows recznie),
      `exit_plan.py` (transze sprzedazy w % pozycji), UI: dwa zegary + karty top + panel
      makro + panel wyjscia. Szczegoly i decyzje: `docs/STATUS.md`.

### Uruchomienie LIVE po v13 (kolejnosc!)

1. `git push` (auto-redeploy Streamlit Cloud — dziala od razu, fallbacki pre-v13 w kodzie),
2. darmowy klucz FRED -> `secrets.toml` lokalnie + panel Streamlit Cloud + GitHub Secret `FRED_API_KEY`,
3. `python scripts/bootstrap_sheet.py` — dolozy zakladke `sell_tranches`, kolumne `side`
   i wiersze top/macro NIE ruszajac istniejacych progow (niedestrukcyjny upgrade),
4. `python scripts/migrate_13.py` — external DDL (`config_thresholds_ext` z `side`,
   `sell_tranches_ext`); kolumny native dolozy sam najblizszy ingest,
5. w arkuszu: `halving_date` (2024-04-20) juz w przykladzie; wpisz progi transz
   sprzedazy i ew. `etf_flows_usd_7d`.
