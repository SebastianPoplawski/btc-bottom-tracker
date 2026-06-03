# Setup: Google Cloud (BigQuery) + Google Sheets — krok po kroku

> Cel: jeden **service account**, ktory obsluguje i BigQuery (hurtownia), i arkusz
> Google Sheets (reczne wskazniki). Wszystko na Twoim zwyklym koncie Google.
> Czas: ~15 min. Koszt: **$0** w darmowym tierze.

---

## 1. Projekt GCP

1. Wejdz na <https://console.cloud.google.com> i zaloguj sie kontem Google.
2. Gora ekranu -> selektor projektow -> **New Project**.
3. Nazwa np. `btc-bottom-tracker`. Zapamietaj **Project ID** (czasem rozne od nazwy,
   np. `btc-bottom-tracker-4821`) — wpiszesz je do `GCP_PROJECT_ID`.

## 2. Billing + alert budzetowy (zeby historia nie znikala)

> Sandbox kasuje tabele po 60 dniach. Wybieramy billing, ale w darmowym tierze
> realnie placisz $0. Alert to tylko mail ostrzegawczy.

1. Menu (☰) -> **Billing** -> podlacz/utworz konto rozliczeniowe (karta).
2. **Budgets & alerts** -> **Create budget**:
   - Amount: `1` (USD),
   - Alerty na 50% / 90% / 100% (mail).

## 3. Wlacz API

Menu (☰) -> **APIs & Services -> Enabled APIs & services -> + Enable APIs**.
Wlacz trzy (wpisz w wyszukiwarce i kliknij **Enable**):

- **BigQuery API**
- **Google Sheets API**
- **Google Drive API**  ← potrzebne, by `gspread` otwieral arkusz po ID

## 4. Dataset BigQuery (lokalizacja EU)

Najprosciej w konsoli:

1. Menu (☰) -> **BigQuery**.
2. Przy nazwie projektu klik ⋮ -> **Create dataset**.
3. Dataset ID: `btc_tracker`  •  Location type: **Multi-region** -> **EU**.
4. Create.

(Alternatywa CLI, jak masz `gcloud`/`bq`:)
```bat
bq --location=EU mk --dataset %GCP_PROJECT_ID%:btc_tracker
```

## 5. Service account + klucz JSON

1. Menu (☰) -> **IAM & Admin -> Service Accounts -> + Create service account**.
2. Nazwa: `btc-tracker-sa`. Skopiuj wygenerowany **email**
   (np. `btc-tracker-sa@PROJEKT.iam.gserviceaccount.com`) — bedzie potrzebny w kroku 6.
3. **Role** (zasada minimalnych uprawnien):
   - `BigQuery Job User`  (uruchamianie zapytan),
   - `BigQuery Data Editor`  (zapis/odczyt tabel).
   > Chcesz jeszcze ciasniej? Nadaj `Data Editor` tylko na poziomie datasetu
   > (BigQuery -> dataset -> Sharing -> Permissions), a na projekcie zostaw sam `Job User`.
4. Po utworzeniu: zakladka **Keys -> Add key -> Create new key -> JSON -> Create**.
   Pobierze sie plik `.json` — to Twoj sekret.

### Gdzie wlozyc klucz
- **Lokalnie:** wklej pola JSON do `.streamlit/secrets.toml` (sekcja `[gcp_service_account]`,
  patrz `secrets.toml.example`). Albo trzymaj plik w `./secrets/service_account.json`
  i ustaw `GOOGLE_APPLICATION_CREDENTIALS` w `.env`.
- **Streamlit Cloud:** App -> Settings -> **Secrets** -> wklej cala tresc `secrets.toml`.
- **NIGDY** nie commituj pliku JSON (chroni go `.gitignore`).

## 6. Arkusz Google Sheets

1. Utworz nowy arkusz na <https://sheets.google.com>.
2. ID arkusza jest w URL: `.../spreadsheets/d/`**`TO_ID`**`/edit` -> wpisz do `GOOGLE_SHEET_ID`.
3. Klik **Udostepnij (Share)** -> wklej **email service accounta** z kroku 5 ->
   uprawnienie **Edytujacy (Editor)** -> wyslij.
   > To kluczowy krok: bez udostepnienia arkusza temu emailowi `gspread` dostanie 403.
4. Layout zakladek/kolumn dostarcze w kroku „Sheets" (osobny etap budowy).

---

## Szybki test polaczenia (po skonfigurowaniu kodu w kolejnych krokach)

```bat
streamlit run app.py
```
Jezeli `APP_MODE=demo` — ruszy na danych seed bez chmury.
Jezeli `APP_MODE=live` — sprawdzi BigQuery i arkusz; bledy uwierzytelnienia
pokaza sie jako czytelny komunikat, nie crash.
