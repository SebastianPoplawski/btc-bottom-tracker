-- ============================================================
-- BTC Bottom Tracker — warstwa hurtowni BigQuery (GoogleSQL)
-- Wartości podstawione na żywo: projekt btc-bottom-tracker-498120,
-- dataset btc_tracker (już istnieje w EU), sheet 19GCtFy...vHRY.
--
-- UWAGA repo publiczne: tu są tylko IDENTYFIKATORY (projekt, dataset,
-- arkusz) — to NIE sekrety (bez klucza JSON nikt się nie zaloguje, a
-- arkusz jest udostępniony tylko service accountowi). Jedyny realny
-- sekret = klucz JSON SA i ten nigdy nie trafia do tych plików.
-- Jeśli mimo to wolisz nie pokazewać ID w repo — zostaw je jako
-- ${PLACEHOLDER} i wstrzykuj przy uruchomieniu.
-- ============================================================

-- Utworzenie datasetu (raz). Z CLI:
--   bq --location=EU mk --dataset btc-bottom-tracker-498120:btc_tracker
-- albo z Pythona: ensure_dataset()

-- ------------------------------------------------------------
-- 1) indicator_readings  (TABELA NATYWNA — rdzeń hurtowni)
--    1 wiersz = komplet odczytów na dany dzień.
--    Przechowujemy WYŁĄCZNIE surowe odczyty. Sygnały bool są
--    liczone w Pythonie wzgl. config_thresholds — dzięki temu
--    zmiana progu NIE wymaga przeliczania historii, a warstwa
--    sygnałów jest oddzielona od warstwy danych i prezentacji.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `btc-bottom-tracker-498120.btc_tracker.indicator_readings` (
  reading_date    DATE      NOT NULL OPTIONS(description="Dzień odczytu — klucz logiczny dla upsertu (MERGE)"),
  price_usd       NUMERIC   OPTIONS(description="Cena BTC, zamknięcie dnia, USD"),
  mvrv_z_score    NUMERIC   OPTIONS(description="MVRV Z-Score; dno gdy < 0"),
  nupl            NUMERIC   OPTIONS(description="NUPL; dno gdy < 0 (kapitulacja)"),
  ma_200w         NUMERIC   OPTIONS(description="200-tyg. średnia krocząca ceny, USD"),
  whale_accumulating BOOL   OPTIONS(description="SYGNAŁ dna (ręczny TRUE/FALSE): czy wieloryby akumulują — NADRZĘDNY"),
  whale_ratio     NUMERIC   OPTIONS(description="Opcjonalna wartość ref.: Exchange Whale Ratio 72h MA (CryptoQuant)"),
  fear_greed      INT64     OPTIONS(description="Fear & Greed 0..100; dno gdy < 25 (pasmo Extreme Fear 0-24)"),
  days_since_ath  INT64     OPTIONS(description="Dni od ATH; dno ~300-400 (10-13 mies.)"),
  ath_date        DATE      OPTIONS(description="Data ATH (opcjonalnie, do przeliczeń)"),
  notes           STRING    OPTIONS(description="Notatka ręczna"),
  inserted_at     TIMESTAMP OPTIONS(description="Czas pierwszego zapisu wiersza"),
  updated_at      TIMESTAMP OPTIONS(description="Czas ostatniej modyfikacji")
)
-- PARTITION BY reading_date   -- patrz NOTATKA O PARTYCJONOWANIU niżej: przy tej skali ZBĘDNE
OPTIONS(description="Dzienna historia surowych odczytów wskaźników dna BTC");

-- price_to_200w_ratio celowo NIE jest składowane — liczymy je przy
-- odczycie (price_usd / ma_200w), żeby nie trzymać danych pochodnych.

-- ------------------------------------------------------------
-- 2) dca_tranches  (plan zakupów transzami $70K -> $55K)
--    Kandydat na tabelę zewnętrzną (Sheets) — patrz wariant niżej,
--    bo to dane które edytujesz ręcznie.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `btc-bottom-tracker-498120.btc_tracker.dca_tranches` (
  tranche_id           INT64   NOT NULL OPTIONS(description="Numer transzy"),
  trigger_price_usd    NUMERIC OPTIONS(description="Cena BTC wyzwalająca transzę"),
  allocation_usd       NUMERIC OPTIONS(description="Kwota do wdrożenia, USD"),
  allocation_pct       NUMERIC OPTIONS(description="Udział transzy w budżecie (%)"),
  min_signals_required INT64   OPTIONS(description="Min. liczba sygnałów dna by aktywować (opcjonalne)"),
  status               STRING  OPTIONS(description="pending | executed | skipped"),
  executed_date        DATE    OPTIONS(description="Data realizacji"),
  executed_price_usd   NUMERIC OPTIONS(description="Faktyczna cena realizacji"),
  note                 STRING
)
OPTIONS(description="Plan DCA i status realizacji transz");

-- ------------------------------------------------------------
-- 3) config_thresholds  (edytowalne progi sygnałów)
--    Operator wykonuje Python (lt/gt/lte/gte/between). Też dobry
--    kandydat na tabelę zewnętrzną (Sheets).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `btc-bottom-tracker-498120.btc_tracker.config_thresholds` (
  indicator        STRING  NOT NULL OPTIONS(description="Klucz: mvrv_z_score|nupl|price_to_200w_ratio|whale_accumulating|fear_greed|days_since_ath"),
  operator         STRING  OPTIONS(description="lt | gt | lte | gte | between | is_true | is_false"),
  threshold_value  NUMERIC OPTIONS(description="Próg główny"),
  threshold_value2 NUMERIC OPTIONS(description="Drugi próg dla 'between'"),
  weight           NUMERIC OPTIONS(description="Waga w composite (domyślnie 1.0; composite ważony liczy krok 03)"),
  active           BOOL    OPTIONS(description="Czy wliczać do composite 'okno zakupu'"),
  description      STRING
)
OPTIONS(description="Edytowalne progi: definicja kiedy wskaźnik potwierdza dno");

-- Seed progów (uruchom raz; dostosuj do uznania).
-- whale: sygnałem dna jest RĘCZNA flaga boolean whale_accumulating (operator is_true).
-- whale_ratio (Exchange Whale Ratio 72h MA, CryptoQuant) trzymamy tylko referencyjnie;
-- orientacyjny próg auto-klasyfikacji < 0.85, ale flaga jest NADRZĘDNA.
-- F&G: próg = < 25  ==  udokumentowane pasmo "Extreme Fear" alternative.me (0-24).
--   Reguła z ZASADY (pasmo dostawcy), nie pod fixture — seed liczymy DOPIERO z reguły.
--   F&G ma niską weight (0.5): najsłabszy / najszumniejszy / redundantny-w-ogonie sygnał.
--   TODO krok 03: zdjąć binarność F&G (wkład stopniowy: 0 dla >25, częściowy 10-24,
--   pełny dla <10); rozważyć to samo dla pozostałych progów binarnych.
INSERT INTO `btc-bottom-tracker-498120.btc_tracker.config_thresholds`
(indicator, operator, threshold_value, threshold_value2, weight, active, description) VALUES
('mvrv_z_score',        'lt',       0,    NULL, 0.5, TRUE, 'Dno: MVRV Z < 0 (redundancja z NUPL -> waga 0.5)'),
('nupl',                'lt',       0,    NULL, 0.5, TRUE, 'Dno: NUPL < 0 (kapitulacja; redundancja z MVRV-Z -> waga 0.5)'),
('price_to_200w_ratio', 'lte',      1.05, NULL, 1.0, TRUE, 'Dno: cena <= ~105% 200W MA'),
('whale_accumulating',  'is_true',  NULL, NULL, 1.0, TRUE, 'Dno: reczna flaga TRUE; ref. Exchange Whale Ratio 72h MA < 0.85'),
('fear_greed',          'lt',       25,   NULL, 0.5, TRUE, 'Dno: F&G < 25 = pasmo Extreme Fear alternative.me (0-24); niska waga'),
('days_since_ath',      'between',  300,  400,  1.0, TRUE, 'Dno: ~10-13 mies. od ATH');

-- ============================================================
-- WARIANT: config_thresholds / dca_tranches jako TABELE ZEWNĘTRZNE
-- podpięte do Google Sheets (edytujesz w arkuszu -> widać w BQ bez ETL).
--
-- Wymagania:
--  (a) udostepnij arkusz e-mailowi service accountu (Viewer),
--  (b) poswiadczenia z dodatkowym scope Drive (auth/bigquery + auth/drive),
--      inaczej 403 przy odczycie arkusza (patrz bigquery_warehouse.py: _SCOPES),
--  (c) zapytania wykonuja sie w LOCATION datasetu.
--
-- KIEDY SĘ OPŁACA: małe, wolnozmienne dane ręcznie edytowane
--   (progi, plan DCA) — masz live-edit, zero ETL.
-- KIEDY NIE: indicator_readings (chcesz historii + upsert MERGE +
--   stabilnych typów) trzymaj jako NATYWNĄ. External nie wspiera
--   MERGE jako target, partycji, klastrowania; każdy SELECT
--   re-czyta arkusz (lekka latencja).
-- ============================================================
CREATE OR REPLACE EXTERNAL TABLE `btc-bottom-tracker-498120.btc_tracker.config_thresholds_ext`
(
  indicator        STRING,
  operator         STRING,
  threshold_value  NUMERIC,
  threshold_value2 NUMERIC,
  weight           NUMERIC,
  active           BOOL,
  description      STRING
)
OPTIONS (
  format            = 'GOOGLE_SHEETS',
  uris              = ['https://docs.google.com/spreadsheets/d/19GCtFyNBKBEj3-jWOLYfNBEd-7jVIXigkDJBGW0vHRY/edit'],
  sheet_range       = 'config_thresholds!A1:G100',
  skip_leading_rows = 1
);

CREATE OR REPLACE EXTERNAL TABLE `btc-bottom-tracker-498120.btc_tracker.dca_tranches_ext`
(
  tranche_id           INT64,
  trigger_price_usd    NUMERIC,
  allocation_usd       NUMERIC,
  allocation_pct       NUMERIC,
  min_signals_required INT64,
  status               STRING,
  executed_date        DATE,
  executed_price_usd   NUMERIC,
  note                 STRING
)
OPTIONS (
  format            = 'GOOGLE_SHEETS',
  uris              = ['https://docs.google.com/spreadsheets/d/19GCtFyNBKBEj3-jWOLYfNBEd-7jVIXigkDJBGW0vHRY/edit'],
  sheet_range       = 'dca_tranches!A1:I200',
  skip_leading_rows = 1
);

-- ============================================================
-- ZAPYTANIA PRZYKŁADOWE (90 / 180 / 365 dni)
-- Zasada darmowego tieru: SELECT tylko potrzebnych kolumn.
-- BigQuery bilansuje koszt po bajtach przeskanowanych kolumn,
-- NIE po liczbie wierszy — kolumny których nie wybierzesz nie kosztują.
-- (Ta tabelka i tak jest mikroskopijna: ~365 wierszy/rok.)
-- ============================================================

-- MVRV Z, ostatnie 90 dni
SELECT reading_date, mvrv_z_score
FROM `btc-bottom-tracker-498120.btc_tracker.indicator_readings`
WHERE reading_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
ORDER BY reading_date;

-- NUPL, ostatnie 180 dni
SELECT reading_date, nupl
FROM `btc-bottom-tracker-498120.btc_tracker.indicator_readings`
WHERE reading_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 180 DAY)
ORDER BY reading_date;

-- Fear & Greed, ostatnie 365 dni
SELECT reading_date, fear_greed
FROM `btc-bottom-tracker-498120.btc_tracker.indicator_readings`
WHERE reading_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
ORDER BY reading_date;

-- Cena vs 200W MA (ratio liczone w locie), 365 dni
SELECT
  reading_date,
  price_usd,
  ma_200w,
  SAFE_DIVIDE(price_usd, ma_200w) AS price_to_200w_ratio
FROM `btc-bottom-tracker-498120.btc_tracker.indicator_readings`
WHERE reading_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
ORDER BY reading_date;

-- Komplet wskazaników do wykresów (1 odczyt na dzień), 365 dni
SELECT
  reading_date, price_usd, mvrv_z_score, nupl,
  ma_200w, whale_accumulating, whale_ratio, fear_greed, days_since_ath
FROM `btc-bottom-tracker-498120.btc_tracker.indicator_readings`
WHERE reading_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
ORDER BY reading_date;
