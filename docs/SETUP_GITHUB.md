# Setup: GitHub + GitHub Desktop (Windows) — krok po kroku

> Cel: jedno repozytorium jako **zrodlo prawdy** dla calego projektu.
> Czat generuje pliki -> Ty zapisujesz do folderu -> commit -> push.
> Sekrety (klucz JSON, secrets.toml) NIGDY nie trafiaja do repo.
> Czas: ~10 min. Uzywamy GitHub Desktop (GUI) — bez walki z terminalem.

---

## 0. Zasada (najwazniejsze)

- **Czat = maszyna do pisania kodu. Repo = magazyn.**
- Tekst wygenerowany w oknie czatu **NIE zapisuje sie sam**. Po kazdym pliku:
  zapisz do folderu -> commit -> push. Inaczej praca zostaje tylko w czacie.
- **Klucz JSON service accountu i `secrets.toml` NIGDY do repo.** Patrz krok 5.

## 1. Folder projektu

- Utworz jeden folder, np. `C:\Users\<Ty>\btc-bottom-tracker`.
- Wrzuc do niego pliki z kroku 00:
  `README.md`, `requirements.txt`, `.gitignore`, `.python-version`, `.env.example`,
  `.streamlit\config.toml`, `.streamlit\secrets.toml.example`, `docs\SETUP_GCP.md`,
  `docs\SETUP_GITHUB.md` (ten plik), `STATUS.md`.
- **Klucz JSON** trzymaj POZA repo, albo w podfolderze `secrets\` (jest w `.gitignore`).
  Nie zmieniaj jego nazwy.

## 2. Konto GitHub + GitHub Desktop

1. Zaloz konto na <https://github.com> (jesli nie masz).
2. Pobierz GitHub Desktop: <https://desktop.github.com> -> zainstaluj.
3. Otworz -> **File -> Options -> Accounts -> Sign in** -> zaloguj sie kontem GitHub.

## 3. Publiczne czy prywatne repo?

- **Prywatne = rekomendowane.** Nikt nie widzi kodu, a Streamlit Community Cloud
  i tak deployuje z prywatnych repo (aplikacja staje sie wtedy prywatna). Bezpieczniejsze
  dla osobistego projektu.
- Publiczne tez dziala (Twoj `.gitignore` jest pod to napisany), ale wymaga wiekszej czujnosci.
- Mozesz zmienic widocznosc pozniej. Ten przewodnik zaklada **prywatne**.

## 4. Utworz repozytorium z folderu

W GitHub Desktop:

1. **File -> Add local repository** -> wskaz folder `btc-bottom-tracker`.
2. Jesli pojawi sie "this directory does not appear to be a Git repository" ->
   kliknij link **create a repository**.
3. W oknie: Name = `btc-bottom-tracker`, **Git ignore: None** (masz juz wlasny `.gitignore`),
   License: None -> **Create repository**.

## 5. KONTROLA SEKRETOW przed pierwszym pushem (krytyczne)

W GitHub Desktop, lewa kolumna **Changes** — to lista plikow, ktore pojda do repo. OBEJRZYJ JA.

- **NIE moze tam byc:** zadnego pliku klucza `*.json` (np. `btc-bottom-tracker-...json`),
  `.streamlit\secrets.toml`, `.env`, folderu `secrets\`.
- Jesli widzisz ktorys z nich -> **STOP**. Upewnij sie, ze `.gitignore` lezy w glownym folderze
  repo i zawiera te wpisy. Po poprawce plik powinien zniknac z listy.
- **Powinno tam byc:** `README.md`, `requirements.txt`, `.gitignore`, pliki `*.example`,
  `docs\`, `STATUS.md`, kod (`app.py`, `src\...`).

> Zasada: do repo trafiaja tylko pliki `*.example` (szablony bez wartosci). Realny
> `secrets.toml` i klucz JSON zostaja wylacznie na Twoim dysku.

## 6. Pierwszy commit + push

1. Dol lewej kolumny: **Summary** -> np. `00: fundamenty + setup`.
2. **Commit to main**.
3. Gora okna: **Publish repository** -> zaznacz **Keep this code private** -> **Publish repository**.

Gotowe — kod jest w repo na GitHub.

## 7. Workflow na co dzien (po kazdym kroku 01, 02, ...)

1. Zapisz nowe/zmienione pliki do folderu projektu.
2. GitHub Desktop -> obejrzyj **Changes** (znowu zerknij, czy nie ma sekretow).
3. **Summary** -> np. `02: ingestion (binance, fng, sheets)` -> **Commit to main**.
4. **Push origin** (przycisk u gory).

Gdy w kroku 04/05 podlaczysz Streamlit Community Cloud do tego repo, aplikacja bedzie
sie aktualizowac **automatycznie po kazdym pushu**.

---

## Alternatywa: git z konsoli (dla chetnych)

GitHub Desktop robi dokladnie to samo myszka. Jesli wolisz terminal:

```bat
cd C:\Users\<Ty>\btc-bottom-tracker
git init
git status                 :: SPRAWDZ: brak klucza JSON i secrets.toml na liscie
git add .
git commit -m "00: fundamenty + setup"
git branch -M main
git remote add origin https://github.com/<login>/btc-bottom-tracker.git
git push -u origin main
```

## Awaria: klucz JSON trafil do repo

- Usuniecie go kolejnym commitem **nie wystarczy** — zostaje w historii repo.
- Natychmiast uniewaznij klucz: konsola GCP -> **IAM & Admin -> Service Accounts ->
  `btc-tracker-sa` -> Keys** -> usun stary klucz -> **Add key** -> utworz nowy JSON.
- Podmien klucz lokalnie w `secrets.toml`. Stary klucz w publicznym repo = ktos moze
  uzywac Twojej chmury, dlatego kontrola z kroku 5 jest obowiazkowa.
