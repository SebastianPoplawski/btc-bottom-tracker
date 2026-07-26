# BTC Bottom Tracker — layout Google Sheets (krok 02 + 13), zgodny ze schematem

4 zakładki (krok 13 dokłada `sell_tranches`), nazwy = nazwy tabel/źródeł z `ddl.sql`
i `bigquery_client.py`. Każda zakładka jest czytelna jednocześnie przez `gspread`
(→ DataFrame) i przez BigQuery jako tabela zewnętrzna nad Sheets
(`config_thresholds_ext`, `dca_tranches_ext`, `sell_tranches_ext`). Stąd reguły niżej.

## Reguły wspólne (wymagane dla external tables BQ)
1. Wiersz 1 = nagłówki dokładnie jak w specyfikacji (`snake_case`). Bez wiersza opisów.
2. Płaska tabela: bez scalania, bez pustych wierszy w środku, bez stopek/notatek pod danymi.
3. Jeden typ na kolumnę; pusta komórka = NULL (nie wpisuj `-`, `n/a`).
4. Daty ISO `YYYY-MM-DD`. Liczby z kropką (`1.5`), bez `$`, `%`, spacji, separatora tysięcy.
   - Pułapka locale PL: arkusz zapisuje `1,5`. Ustaw locale arkusza na *United States*
     (Plik → Ustawienia → Regionalne) — najpewniejsze dla parsera FLOAT64/NUMERIC w BQ.
     `sheets_ingest.py` i tak normalizuje przecinek po stronie gspread (siatka bezpieczeństwa).
5. Booleany jako `TRUE` / `FALSE`.
6. Klucze unikalne: `reading_date`, `tranche_id`, `indicator`.

---

## Zakładka `indicator_readings` (1 wiersz = 1 dzień; klucz `reading_date`)
Kolumny = pola upsertu z `bigquery_warehouse.py` (`_READING_FIELDS`) + `reading_date`.

| kolumna             | typ BQ   | źródło            | opis |
|---------------------|----------|-------------------|------|
| `reading_date`      | DATE     | —                 | dzień odczytu, unikalny (klucz upsertu) |
| `price_usd`         | NUMERIC  | auto (Binance)    | cena BTC; w live z API, ręcznie tylko fallback |
| `mvrv_z_score`      | NUMERIC  | **ręczne**        | lookintobitcoin |
| `nupl`              | NUMERIC  | **ręczne**        | lookintobitcoin |
| `ma_200w`           | NUMERIC  | auto (Binance)    | 200-tyg. średnia; live z API |
| `whale_accumulating`| BOOL     | **ręczne**        | flaga dna `TRUE`/`FALSE` (nadrzędny sygnał wielorybów) |
| `whale_ratio`       | NUMERIC  | **ręczne (ref.)** | Exchange Whale Ratio 72h MA (CryptoQuant); tylko referencyjnie |
| `fear_greed`        | INT64    | auto (alt.me)     | 0–100; ręcznie tylko fallback |
| `days_since_ath`    | INT64    | **computed**      | liczony z `ath_date` (= reading_date − ath_date); ręczny wpis opcjonalny jako fallback gdy brak `ath_date` |
| `ath_date`          | DATE     | **ręczne**        | data ATH cyklu; wpisujesz RAZ — `days_since_ath` liczy się sam |
| `ma_111d`           | NUMERIC  | auto (Binance/Kraken) | 111-dniowa MA ceny (Pi Cycle Top); krok 13 |
| `ma_350d`           | NUMERIC  | auto (Binance/Kraken) | 350-dniowa MA ceny (Pi Cycle: cross 111DMA ≥ 2×350DMA); krok 13 |
| `halving_date`      | DATE     | **ręczne**        | data ostatniego halvingu (2024-04-20); wpisujesz RAZ — `months_since_halving` computed |
| `fed_funds_rate`    | NUMERIC  | auto (FRED DFF)   | makro: stopa Fed; wymaga `FRED_API_KEY` |
| `fed_funds_delta_3m`| NUMERIC  | auto (FRED)       | makro: zmiana stopy vs ~3 mies. wstecz (>0 = zacieśnianie) |
| `dxy_proxy`         | NUMERIC  | auto (FRED DTWEXBGS) | makro: broad dollar index (proxy DXY) |
| `dxy_delta_3m`      | NUMERIC  | auto (FRED)       | makro: zmiana indeksu dolara vs ~3 mies. wstecz |
| `m2_yoy`            | NUMERIC  | auto (FRED M2SL)  | makro: dynamika M2 r/r w % (M2 USA; publikacja miesięczna z opóźnieniem) |
| `etf_flows_usd_7d`  | NUMERIC  | **ręczne**        | makro: przepływy netto ETF spot BTC za 7 dni, USD (np. z Farside) |
| `notes`             | STRING   | opcjonalne        | komentarz |

Ręcznie wpisujesz głównie: `mvrv_z_score`, `nupl`, `whale_accumulating`, `whale_ratio`,
`ath_date`. `days_since_ath` jest teraz **computed** z `ath_date` (krok 08) — ręczny wpis
opcjonalny, służy tylko jako fallback gdy `ath_date` jest puste. `price_usd`, `ma_200w`,
`fear_greed` dociąga ingestion z API (krok 02) i przez `upsert_reading` dopisuje do tej samej daty.

## Zakładka `config_thresholds` (external: `config_thresholds_ext`)
Steruje logiką sygnałów. Dodanie wskaźnika = nowy wiersz tutaj, bez zmian w UI.

| kolumna            | typ     | opis |
|--------------------|---------|------|
| `indicator`        | STRING  | klucz wskaźnika (patrz niżej) |
| `operator`         | STRING  | `lt` \| `lte` \| `gt` \| `gte` \| `eq` \| `is_true` \| `between` |
| `threshold_value`  | NUMERIC | próg główny (puste dla `is_true`) |
| `threshold_value2` | NUMERIC | górna granica dla `between` |
| `weight`           | NUMERIC | waga w composite |
| `active`           | BOOL    | `TRUE`/`FALSE` |
| `description`      | STRING  | opis reguły |
| `side`             | STRING  | **krok 13:** `bottom` (dno, domyślne gdy puste) \| `top` (szczyt) \| `macro` (risk-off) |

Wiersze (stan z Twojego CSV — źródło prawdy):

| indicator             | operator | threshold_value | threshold_value2 | weight | active | description |
|-----------------------|----------|-----------------|------------------|--------|--------|-------------|
| `mvrv_z_score`        | lt       | 0               |                  | 0.5    | TRUE   | Dno: MVRV Z < 0 (redundancja z NUPL → 0.5) |
| `nupl`                | lt       | 0               |                  | 0.5    | TRUE   | Dno: NUPL < 0 (kapitulacja; redundancja z MVRV-Z → 0.5) |
| `price_to_200w_ratio` | lte      | 1.05            |                  | 1.0    | TRUE   | Dno: cena ≤ ~105% 200W MA |
| `whale_accumulating`  | is_true  |                 |                  | 1.0    | TRUE   | Dno: ręczna flaga TRUE; ref. EWR 72h MA < 0.85 |
| `fear_greed`          | lt       | 25              |                  | 0.5    | TRUE   | Dno: F&G < 25 (Extreme Fear 0–24); niska waga, wkład stopniowy |
| `days_since_ath`      | between  | 300             | 400              | 1.0    | TRUE   | Dno: ~10–13 mies. od ATH |

> Uwaga: `price_to_200w_ratio` jest **computed** = `price_usd / ma_200w` (logika 03), nie kolumna w readings.
> **Composite v2 (krok 11):** `mvrv_z_score` i `nupl` mają wagę **0.5** (są redundantne — liczą się
> łącznie jak jeden sygnał wyceny). F&G wnosi wkład **stopniowo** (`graded_fng=True` w aplikacji). To
> wpływa wyłącznie na **wynik ważony** (headline gauge 0–100%), nie na twardy licznik `count_met`.
> **Wagę zmienia się TU, w arkuszu** (config live = `config_thresholds_ext`) — kod jej nie nadpisuje.

**Krok 13 — wiersze `side=top` (sygnały szczytu) i `side=macro` (risk-off):** pełna lista
w `data/sheets_tab_config_thresholds.csv` (źródło prawdy) — m.in. `mvrv_z_score gt 5`,
`nupl gt 0.7`, `price_to_200w_ratio gte 2.5`, `fear_greed gt 75`, `pi_cycle_crossed is_true`,
`months_since_halving between 12 18` (progi **skalibrowane pod malejące szczyty cykli**,
edytowalne tutaj) oraz makro: `fed_funds_delta_3m gt 0`, `dxy_delta_3m gt 0`, `m2_yoy lt 0`,
`etf_flows_usd_7d lt 0`. Ten sam `indicator` może wystąpić raz na stronę — unikalność
obowiązuje per (`indicator`, `side`). `pi_cycle_crossed` i `months_since_halving` są
**computed** (z `ma_111d`/`ma_350d` i `halving_date`), nie kolumnami w readings.
Makro liczy się w OSOBNYM liczniku risk-off — nie wchodzi do frameworka dna/szczytu.

## Zakładka `dca_tranches` (external: `dca_tranches_ext`)

| kolumna                | typ     | opis |
|------------------------|---------|------|
| `tranche_id`           | INT64   | unikalny (1..7) |
| `trigger_price_usd`    | NUMERIC | cena wyzwalająca transzę |
| `allocation_usd`       | NUMERIC | kwota transzy w USD (uzupełnij) |
| `allocation_pct`       | NUMERIC | udział transzy w % (uzupełnij) |
| `min_signals_required` | INT64   | min. liczba sygnałów dna, by transza była „gotowa" |
| `status`               | STRING  | `pending` \| `executed` \| `skipped` |
| `executed_date`        | DATE    | data realizacji |
| `executed_price_usd`   | NUMERIC | cena realizacji |
| `note`                 | STRING  | komentarz |

## Zakładka `sell_tranches` (external: `sell_tranches_ext`) — krok 13

Plan transz **sprzedaży** (lustro `dca_tranches`). Progi cen = Twój plan wyjścia —
wpisujesz je sam; bootstrap zakłada tylko puste wiersze przykładowe.

| kolumna              | typ     | opis |
|----------------------|---------|------|
| `tranche_id`         | INT64   | unikalny (1..N) |
| `trigger_price_usd`  | NUMERIC | cena wyzwalająca transzę (transze sortowane ROSNĄCO — pierwsza aktywuje się najniżej) |
| `allocation_pct`     | NUMERIC | **% POZYCJI BTC** do zdjęcia w transzy (nie USD); suma ≤ 100 |
| `min_top_signals`    | INT64   | min. liczba sygnałów szczytu (side=top), by transza była „gotowa" (opcjonalne) |
| `status`             | STRING  | `pending` \| `executed` \| `skipped` |
| `executed_date`      | DATE    | data realizacji |
| `executed_price_usd` | NUMERIC | cena realizacji |
| `note`               | STRING  | komentarz |

---

## „Brak nowego wpisu dziś"
`sheets_ingest.py` zwraca metadane świeżości po `reading_date`: najnowsza data, wiek w dniach,
`is_stale` (domyślnie > 2 dni). UI pokazuje ostatni znany odczyt z plakietką „dane z dnia X
(sprzed N dni)" i liczy sygnały na ostatnich dostępnych wartościach — nie zeruje i nie blokuje
widoku. Wskaźniki auto (price/MA/F&G) i tak dociągają świeże dane.
