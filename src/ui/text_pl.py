"""
text_pl.py — krok 04
====================
Polskie napisy UI + disclaimer. Czyste stałe/funkcje, bez zależności od Streamlita.
"""

from __future__ import annotations

from typing import Optional

DISCLAIMER = "Narzędzie analityczne, nie porada inwestycyjna."

APP_TITLE = "BTC Bottom Tracker"
APP_TAGLINE = ("Composite Bottom & Top Score — ważone wskaźniki potwierdzenia "
               "dna i szczytu (0–100%)")

# Nota metodologiczna do panelu composite (opisowa, nie porada).
COMPOSITE_NOTE = (
    "MVRV-Z i NUPL liczą się łącznie jak jeden sygnał wyceny (waga 0.5 każdy — "
    "redundancja), a Fear & Greed wnosi wkład stopniowo (im głębszy strach, tym większy)."
)
# krok 17: nota strony szczytu + makro
COMPOSITE_NOTE_TOP = (
    "Progi szczytu skalibrowane pod malejące szczyty cykli (edytowalne w arkuszu); "
    "F&G wnosi wkład stopniowo po stronie chciwości (75→90)."
)
MACRO_NOTE = (
    "Osobny licznik kontekstu makro — NIE wchodzi do frameworka dna/szczytu. "
    "Serie FRED publikowane z opóźnieniem (M2 miesięcznie); ETF flows wpis ręczny."
)

# Stany sygnału (met -> etykieta + semantyczny kolor)
MET_LABEL = {True: "spełniony", False: "niespełniony", None: "brak danych"}
COLOR_MET = "#1f9d55"      # zielony — warunek dna spełniony
COLOR_UNMET = "#c0563b"    # czerwono-rdzawy — niespełniony
COLOR_NA = "#5b616e"       # szary — brak danych
ACCENT = "#F7931A"         # bitcoin orange

SECTION_SIGNALS = "Sygnały dna"
SECTION_TOP = "Sygnały szczytu"
SECTION_MACRO = "Otoczenie makro (risk-off)"
SECTION_CHARTS = "Historia wskaźników"
SECTION_DCA = "Plan DCA (zakupy)"
SECTION_EXIT = "Plan transz sprzedaży (wyjście)"

GAUGE_BOTTOM_TITLE = "Dno — okno zakupu"
GAUGE_TOP_TITLE = "Szczyt — okno wyjścia"

MODE_LABEL = {"demo": "DEMO (seed)", "live": "LIVE (BigQuery + Sheets)"}

# Statusy transz DCA (klucz -> etykieta PL) — używane przez components.dca_panel.
STATUS_PL = {
    "pending": "oczekująca",
    "executed": "zrealizowana",
    "skipped": "pominięta",
}

# Pomoc do kart wskaźników (krótko, po polsku)
INDICATOR_HELP = {
    "mvrv_z_score": "MVRV Z-Score — dno gdy < 0 (lookintobitcoin).",
    "nupl": "NUPL — dno gdy < 0 (kapitulacja).",
    "price_to_200w_ratio": "Cena / 200-tyg. średnia — dno gdy ≤ ~1.05 (blisko/poniżej MA).",
    "whale_accumulating": "Akumulacja wielorybów — ręczna flaga TAK/NIE.",
    "fear_greed": "Fear & Greed — dno gdy < 25 (pasmo Extreme Fear).",
    "days_since_ath": "Czas od ATH — dno ~300–400 dni (10–13 mies.).",
}
# krok 17: pomoc dla kart strony szczytu (te same klucze wskaźników, inna reguła)
INDICATOR_HELP_TOP = {
    "mvrv_z_score": "MVRV Z-Score — szczyt gdy > 5 (malejące szczyty cykli).",
    "nupl": "NUPL — szczyt gdy > 0.7 (strefa euforii).",
    "price_to_200w_ratio": "Cena / 200-tyg. średnia — szczyt gdy ≥ 2.5× MA.",
    "fear_greed": "Fear & Greed — szczyt gdy > 75 (Extreme Greed).",
    "pi_cycle_crossed": "Pi Cycle Top — przecięcie: 111DMA ≥ 2× 350DMA (liczone z API).",
    "months_since_halving": "Czas od halvingu — historycznie szczyt 12–18 mies. po halvingu.",
}
INDICATOR_HELP_MACRO = {
    "fed_funds_delta_3m": "Zmiana stopy Fed vs ~3 mies. — dodatnia = zacieśnianie (FRED DFF).",
    "dxy_delta_3m": "Zmiana broad dollar index vs ~3 mies. — dodatnia = mocniejszy dolar (FRED).",
    "m2_yoy": "Dynamika podaży M2 r/r — ujemna = kurcząca się płynność (FRED M2SL).",
    "etf_flows_usd_7d": "Przepływy netto ETF spot BTC 7d — ujemne = odpływy (wpis ręczny).",
}


def format_threshold(operator: str, t1, t2) -> str:
    """Czytelny opis progu z operatora + wartości (do karty wskaźnika)."""
    op = (operator or "").strip().lower()
    if op == "is_true":
        return "wymagane: TAK"
    if op == "is_false":
        return "wymagane: NIE"
    if op == "between":
        return f"{_num(t1)} – {_num(t2)}"
    sym = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "eq": "="}.get(op, op)
    return f"{sym} {_num(t1)}"


def format_value(indicator: str, value) -> str:
    """Formatuje wartość wskaźnika do wyświetlenia."""
    if value is None:
        return "—"
    if indicator in ("whale_accumulating", "pi_cycle_crossed"):
        return "TAK" if bool(value) else "NIE"
    if indicator == "months_since_halving":
        try:
            return f"{float(value):.1f} mies."
        except (TypeError, ValueError):
            return str(value)
    if indicator in ("fed_funds_delta_3m", "dxy_delta_3m"):
        try:
            return f"{float(value):+.2f}"
        except (TypeError, ValueError):
            return str(value)
    if indicator == "m2_yoy":
        try:
            return f"{float(value):+.1f}% r/r"
        except (TypeError, ValueError):
            return str(value)
    if indicator == "etf_flows_usd_7d":
        try:
            v = float(value)
            return ("−" if v < 0 else "+") + usd(abs(v))
        except (TypeError, ValueError):
            return str(value)
    if indicator == "days_since_ath":
        try:
            d = int(round(float(value)))
            return f"{d} dni (~{d / 30.44:.1f} mies.)"
        except (TypeError, ValueError):
            return str(value)
    if indicator == "fear_greed":
        try:
            return f"{int(round(float(value)))}"
        except (TypeError, ValueError):
            return str(value)
    if indicator == "price_to_200w_ratio":
        try:
            return f"{float(value):.3f}× MA"
        except (TypeError, ValueError):
            return str(value)
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def usd(value: Optional[float]) -> str:
    if value is None:
        return "—"
    try:
        return "$" + f"{float(value):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _num(v) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
        return f"{f:g}"
    except (TypeError, ValueError):
        return str(v)
