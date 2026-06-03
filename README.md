# BTC Bottom Tracker

Dashboard monitorujacy cykliczne **dno Bitcoina** wg frameworka 5–6 wskaznikow
on-chain i sentymentu. Liczy zbiorczy **Composite Bottom Score** ("ile sygnalow dna
spelnionych jednoczesnie") i prowadzi plan zakupow transzami (DCA).

> ⚠️ **To narzedzie analityczne, nie porada inwestycyjna.** Wskazniki, progi i werdykty
> to wbudowany framework uzytkownika — dashboard pokazuje, co mowia dane wg tych regul.

---

## Stos

| Warstwa | Technologia |
|---|---|
| UI / logika | Python 3.14 + **Streamlit** (domyslnie), Dash jako wariant |
| Reczne dane + config | Google Sheets (`gspread` + service account) |
| Hurtownia / historia | Google **BigQuery** (darmowy tier 10 GB / 1 TB zapytan mies.) |
| Ceny / sentyment | Binance public API (200W MA), alternative.me (Fear & Greed) |
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
│   ├── indicators/             # LOGIKA SYGNALOW — 1 modul = 1 wskaznik
│   │   ├── base.py             #   wspolny kontrakt: Zone/Indicator + rejestr
│   │   ├── mvrv_z.py           #   MVRV Z-Score (dno: Z < 0)
│   │   ├── nupl.py             #   NUPL (dno: < 0)
│   │   ├── ma_200w.py          #   cena vs 200-tyg. srednia
│   │   ├── whale_ratio.py      #   akumulacja wielorybow
│   │   ├── fear_greed.py       #   Fear & Greed (dno: < 20)
│   │   └── time_since_ath.py   #   miesiace od ATH (cel 10–12)
│   ├── ingestion/              # ZRODLA DANYCH (oddzielone od logiki sygnalow)
│   │   ├── price_binance.py    #   tygodniowe zamkniecia BTC -> 200W MA
│   │   ├── fear_greed_api.py   #   alternative.me
│   │   ├── sheets.py           #   gspread: reczne wskazniki, DCA, progi
│   │   └── mock.py             #   dane seed/demo (snapshot 2026-06-01)
│   ├── warehouse/
│   │   ├── bigquery_client.py  #   odczyt/zapis BQ, zapytania oszczedne kosztowo
│   │   └── ddl.sql             #   definicje tabel
│   ├── logic/
│   │   ├── composite.py        #   bottom_score + generator werdyktu
│   │   └── dca.py              #   kalkulacje planu transz
│   └── ui/
│       ├── components.py       #   karty / gauge (reuzywalne widgety)
│       └── text_pl.py          #   polskie napisy UI + disclaimer
├── data/
│   └── seed_snapshot_2026-06-01.json
├── docs/
│   └── SETUP_GCP.md            # konfiguracja GCP/BigQuery + udostepnienie arkusza
└── tests/
    └── test_signals.py         # testy klasyfikacji progow
```

**Zasada architektury:** `ingestion` (skad dane) ⟂ `indicators`+`logic` (jak liczymy sygnaly)
⟂ `ui` (jak pokazujemy). Dodanie 6. wskaznika = nowy plik w `indicators/` + wpis w rejestrze.
Zero zmian w UI.

> Pliki w `src/`, `app.py`, `app_dash.py`, `data/`, `tests/` powstaja w kolejnych krokach
> budowy (01+). Ten commit to fundamenty: config, zaleznosci, setup, bezpieczenstwo.

---

## Sekrety i zmienne srodowiskowe

| Klucz | Co to | Gdzie |
|---|---|---|
| `gcp_service_account` | **klucz JSON service accounta (TAJNE)** — BigQuery + Sheets | `secrets.toml` / panel Streamlit Cloud |
| `GCP_PROJECT_ID` | ID projektu GCP | `secrets.toml` / `.env` |
| `BQ_DATASET` | dataset, np. `btc_tracker` | jw. |
| `BQ_LOCATION` | lokalizacja, `EU` | jw. |
| `GOOGLE_SHEET_ID` | ID arkusza z URL | jw. |
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

- [x] **00 — Architektura i setup** (ten commit)
- [ ] 01 — Schemat danych: DDL BigQuery + layout Google Sheets + seed
- [ ] 02 — Ingestion (Binance, Fear & Greed, Sheets) + cache
- [ ] 03 — Logika sygnalow + Composite Score + werdykt
- [ ] 04 — UI Streamlit (karty, gauge, wykresy, modul DCA)
- [ ] 05 — Wariant Dash
