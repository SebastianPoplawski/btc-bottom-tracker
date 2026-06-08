"""
text_pl.py — krok 04
====================
Polskie napisy UI + disclaimer. Czyste stałe/funkcje, bez zależności od Streamlita.
"""

from __future__ import annotations

from typing import Optional

DISCLAIMER = "Narzędzie analityczne, nie porada inwestycyjna."

APP_TITLE = "BTC Bottom Tracker"
APP_TAGLINE = "Composite Bottom Score — ile sygnałów dna spełnionych jednocześnie"

# Stany sygnału (met -> etykieta + semantyczny kolor)
MET_LABEL = {True: "spełniony", False: "niespełniony", None: "brak danych"}
COLOR_MET = "#1f9d55"      # zielony — warunek dna spełniony
COLOR_UNMET = "#c0563b"    # czerwono-rdzawy — niespełniony
COLOR_NA = "#5b616e"       # szary — brak danych
ACCENT = "#F7931A"         # bitcoin orange

SECTION_SIGNALS = "Sygnały dna"
SECTION_CHARTS = "Historia wskaźników"
SECTION_DCA = "Plan DCA"

MODE_LABEL = {"demo": "DEMO (seed)", "live": "LIVE (BigQuery + Sheets)"}

# Pomoc do kart wskaźników (krótko, po polsku)
INDICATOR_HELP = {
    "mvrv_z_score": "MVRV Z-Score — dno gdy < 0 (lookintobitcoin).",
    "nupl": "NUPL — dno gdy < 0 (kapitulacja).",
    "price_to_200w_ratio": "Cena / 200-tyg. średnia — dno gdy ≤ ~1.05 (blisko/poniżej MA).",
    "whale_accumulating": "Akumulacja wielorybów — ręczna flaga TAK/NIE.",
    "fear_greed": "Fear & Greed — dno gdy < 25 (pasmo Extreme Fear).",
    "days_since_ath": "Czas od ATH — dno ~300–400 dni (10–13 mies.).",
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
    if indicator == "whale_accumulating":
        return "TAK" if bool(value) else "NIE"
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
