"""
composite.py — krok 03
======================
Logika sygnałów dna + Composite Bottom Score + werdykt (PL).

Architektura (separacja warstw): ten moduł NIE pobiera danych i NIE rysuje UI.
Dostaje na wejściu:
  - config:  progi z `config_thresholds` (pandas.DataFrame lub list[dict]),
  - reading: surowe odczyty z `indicator_readings` na 1 dzień
             (Mapping / pandas.Series / dict / jednowierszowy DataFrame),
i zwraca: ocenę każdego wskaźnika + composite + tekstowy werdykt.

Zgodnie z DDL: tabela `indicator_readings` trzyma WYŁĄCZNIE surowe odczyty.
Sygnały bool liczy ten moduł względem configu — zmiana progu w arkuszu nie
wymaga przeliczania historii. `price_to_200w_ratio` jest COMPUTED
(= price_usd / ma_200w), nie kolumną w schemacie.

> Narzędzie analityczne, nie porada inwestycyjna. Werdykt jest opisowy
> (co mówią dane wg reguł frameworka), bez sygnałów „kup/sprzedaj".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional

DISCLAIMER = "Narzędzie analityczne, nie porada inwestycyjna."

# Czytelne etykiety do UI (fallback = surowy klucz wskaźnika).
LABELS: dict[str, str] = {
    "mvrv_z_score": "MVRV Z-Score",
    "nupl": "NUPL",
    "price_to_200w_ratio": "Cena / 200W MA",
    "whale_accumulating": "Akumulacja wielorybów",
    "fear_greed": "Fear & Greed",
    "days_since_ath": "Czas od ATH",
}

# Operatory configu (spójne z sheets.VALID_OPERATORS; is_false dodane defensywnie,
# bo komentarz w ddl.sql je wymienia).
_NUMERIC_OPS = {"lt", "lte", "gt", "gte", "eq", "between"}
_BOOL_OPS = {"is_true", "is_false"}
VALID_OPERATORS = _NUMERIC_OPS | _BOOL_OPS


# --------------------------------------------------------------------------- #
# Pomocnicze: brak danych / liczby / wartości z odczytu
# --------------------------------------------------------------------------- #
def _is_missing(v: Any) -> bool:
    """True dla None / NaN / pd.NA (działa też bez pandas)."""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    try:
        import pandas as pd
        res = pd.isna(v)
        if isinstance(res, bool) and res:
            return True
    except Exception:
        pass
    return False


def _get(reading: Any, key: str) -> Any:
    """Wartość spod `key` z dict/Series/Mapping; None gdy brak lub puste."""
    if reading is None:
        return None
    try:
        val = reading[key]
    except (KeyError, TypeError, IndexError):
        val = None
    return None if _is_missing(val) else val


def _to_number(v: Any) -> Optional[float]:
    """Konwersja do float; bool celowo NIE jest liczbą (whale ma operator is_true)."""
    if isinstance(v, bool):
        return None
    if _is_missing(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return float(str(v).strip().replace(",", "."))
        except (TypeError, ValueError):
            return None


def _coerce_date(v: Any) -> Optional[date]:
    if _is_missing(v):
        return None
    if isinstance(v, date):
        return v
    try:
        import pandas as pd
        return pd.to_datetime(v).date()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Wartości pochodne (computed) — rejestr rozszerzalny
# --------------------------------------------------------------------------- #
def _safe_div(a: Any, b: Any) -> Optional[float]:
    na, nb = _to_number(a), _to_number(b)
    if na is None or nb is None or nb == 0:
        return None
    return na / nb


# klucz wskaźnika -> funkcja licząca wartość z surowego odczytu
COMPUTED = {
    "price_to_200w_ratio": lambda r: _safe_div(_get(r, "price_usd"), _get(r, "ma_200w")),
}

# wskaźniki czytane wprost z kolumn `indicator_readings`
_DIRECT_FIELDS = ("mvrv_z_score", "nupl", "fear_greed", "days_since_ath", "whale_accumulating")


def derive_values(reading: Any) -> dict[str, Any]:
    """Słownik wartości testowalnych: bezpośrednie z odczytu + computed."""
    out: dict[str, Any] = {k: _get(reading, k) for k in _DIRECT_FIELDS}
    for key, fn in COMPUTED.items():
        out[key] = fn(reading)
    return out


# --------------------------------------------------------------------------- #
# Ewaluacja operatora
# --------------------------------------------------------------------------- #
def apply_operator(value: Any, operator: str,
                   t1: Any = None, t2: Any = None) -> Optional[bool]:
    """
    True/False czy reguła dna spełniona; None gdy nie da się ocenić
    (brak wartości / brak progu / nieznany operator).
    """
    op = (operator or "").strip().lower()
    if _is_missing(value):
        return None

    if op == "is_true":
        return bool(value) is True
    if op == "is_false":
        return bool(value) is False

    num = _to_number(value)
    if num is None:                      # operator liczbowy, a wartość nieliczbowa
        return None
    a = _to_number(t1)

    if op in {"lt", "lte", "gt", "gte", "eq"}:
        if a is None:
            return None
        if op == "lt":  return num < a
        if op == "lte": return num <= a
        if op == "gt":  return num > a
        if op == "gte": return num >= a
        if op == "eq":  return num == a
    if op == "between":
        b = _to_number(t2)
        if a is None or b is None:
            return None
        lo, hi = (a, b) if a <= b else (b, a)
        return lo <= num <= hi
    return None  # nieznany operator


# --------------------------------------------------------------------------- #
# Hak na wkład stopniowy F&G (TODO z kroku 03; domyślnie wyłączony)
# --------------------------------------------------------------------------- #
def graded_fear_greed(value: Any) -> Optional[float]:
    """
    Wkład stopniowy F&G w [0,1]: pełny dla <10, liniowo 10..25, zero dla >=25.
    Używany tylko gdy evaluate(..., graded_fng=True). Modyfikuje WYŁĄCZNIE
    wagę wkładu do score; licznik 'ile z 6' pozostaje binarny.
    """
    num = _to_number(value)
    if num is None:
        return None
    if num >= 25:
        return 0.0
    if num <= 10:
        return 1.0
    return (25.0 - num) / 15.0


# --------------------------------------------------------------------------- #
# Normalizacja configu (DataFrame lub list[dict])
# --------------------------------------------------------------------------- #
def _clean_num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    return _to_number(v)


def _clean_bool(v: Any, default: bool = True) -> bool:
    if isinstance(v, bool):
        return v
    if _is_missing(v):
        return default
    s = str(v).strip().lower()
    if s in ("true", "1", "tak", "yes", "y"):
        return True
    if s in ("false", "0", "nie", "no", "n"):
        return False
    return default


def _normalize_config(config: Any) -> list[dict]:
    if config is None:
        return []
    try:
        import pandas as pd
        records = config.to_dict("records") if isinstance(config, pd.DataFrame) else list(config)
    except Exception:
        records = list(config)

    rows: list[dict] = []
    for rec in records:
        rows.append({
            "indicator": str(rec.get("indicator", "")).strip(),
            "operator": str(rec.get("operator", "")).strip().lower(),
            "threshold_value": _clean_num(rec.get("threshold_value")),
            "threshold_value2": _clean_num(rec.get("threshold_value2")),
            "weight": _clean_num(rec.get("weight")) or 1.0,
            "active": _clean_bool(rec.get("active")),
            "description": (None if _is_missing(rec.get("description")) else str(rec.get("description"))),
        })
    return rows


# --------------------------------------------------------------------------- #
# Wyniki
# --------------------------------------------------------------------------- #
@dataclass
class IndicatorResult:
    indicator: str
    label: str
    operator: str
    threshold_value: Optional[float]
    threshold_value2: Optional[float]
    weight: float
    active: bool
    value: Any                       # testowana wartość (np. ratio, F&G, bool)
    met: Optional[bool]              # None = nie da się ocenić (brak danych/progu)
    contribution: float              # wkład do weighted_met (0 gdy niespełniony)
    note: str = ""


@dataclass
class CompositeResult:
    count_met: int                   # ile sygnałów dna spełnionych (licznik 'ile z N')
    count_active: int                # ile aktywnych progów (zwykle 6)
    count_evaluable: int             # ile aktywnych ma dane (met != None)
    weighted_met: float              # suma wag/wkładów spełnionych
    weighted_total: float            # suma wag aktywnych+ocenianych
    weighted_ratio: Optional[float]  # weighted_met / weighted_total
    indicators: list[IndicatorResult]
    verdict: str
    warnings: list[str] = field(default_factory=list)
    as_of: Optional[date] = None
    disclaimer: str = DISCLAIMER


# --------------------------------------------------------------------------- #
# Werdykt PL (opisowy, bez „kup/sprzedaj")
# --------------------------------------------------------------------------- #
def build_verdict(count_met: int, count_active: int, count_evaluable: int) -> str:
    missing = count_active - count_evaluable
    base = f"Wg reguł frameworka: {count_met} z {count_active} warunków dna spełnionych"
    if missing > 0:
        base += f" ({missing} bez danych)"
    base += "."

    if count_active == 0:
        tag = "Brak aktywnych progów w konfiguracji."
    elif count_met == 0:
        tag = "Żaden sygnał dna nie jest aktywny."
    elif count_met <= 2:
        tag = "Pojedyncze, wczesne sygnały — obraz daleki od potwierdzenia dna."
    elif count_met <= 4:
        tag = "Obraz mieszany — część warunków dna spełniona."
    elif count_met == count_active and missing == 0:
        tag = "Wszystkie warunki dna spełnione jednocześnie wg frameworka."
    else:
        tag = "Większość warunków dna spełniona wg frameworka."
    return f"{base} {tag}"


# --------------------------------------------------------------------------- #
# Główna funkcja
# --------------------------------------------------------------------------- #
def evaluate(config: Any, reading: Any, graded_fng: bool = False) -> CompositeResult:
    """
    Ocenia komplet wskaźników względem configu dla jednego odczytu.

    config: DataFrame/list[dict] z kolumnami indicator, operator, threshold_value,
            threshold_value2, weight, active, description.
    reading: Mapping/Series/dict (lub 1-wierszowy DataFrame) z surowymi odczytami.
    graded_fng: gdy True, F&G wnosi wkład stopniowy do weighted_met (licznik bez zmian).
    """
    warnings: list[str] = []

    # Wygodnie: pozwól podać 1-wierszowy DataFrame jako reading.
    try:
        import pandas as pd
        if isinstance(reading, pd.DataFrame):
            reading = reading.iloc[-1] if len(reading) else {}
    except Exception:
        pass

    rows = _normalize_config(config)
    if not rows:
        warnings.append("Brak progów w config_thresholds — nie można policzyć sygnałów.")

    derived = derive_values(reading)
    results: list[IndicatorResult] = []

    for row in rows:
        ind, op = row["indicator"], row["operator"]
        if op not in VALID_OPERATORS:
            warnings.append(f"[{ind}] nieznany operator '{op}' — wskaźnik pominięty w ocenie.")

        # wartość: najpierw computed/direct, w razie czego wprost z odczytu (rozszerzalność)
        value = derived[ind] if ind in derived else _get(reading, ind)
        met = apply_operator(value, op, row["threshold_value"], row["threshold_value2"]) \
            if op in VALID_OPERATORS else None

        weight = row["weight"]
        if met is True:
            if graded_fng and ind == "fear_greed":
                g = graded_fear_greed(value)
                contribution = weight * (g if g is not None else 1.0)
            else:
                contribution = weight
        else:
            contribution = 0.0

        if _is_missing(value):
            note = "brak danych"
        elif ind in COMPUTED:
            note = "wartość liczona"
        else:
            note = ""

        results.append(IndicatorResult(
            indicator=ind,
            label=LABELS.get(ind, ind),
            operator=op,
            threshold_value=row["threshold_value"],
            threshold_value2=row["threshold_value2"],
            weight=weight,
            active=row["active"],
            value=value,
            met=met,
            contribution=contribution,
            note=note,
        ))

    # Composite — wyłącznie aktywne wskaźniki
    active = [r for r in results if r.active]
    evaluable = [r for r in active if r.met is not None]
    count_active = len(active)
    count_evaluable = len(evaluable)
    count_met = sum(1 for r in active if r.met is True)
    weighted_total = sum(r.weight for r in evaluable)
    weighted_met = sum(r.contribution for r in evaluable)
    weighted_ratio = (weighted_met / weighted_total) if weighted_total else None

    return CompositeResult(
        count_met=count_met,
        count_active=count_active,
        count_evaluable=count_evaluable,
        weighted_met=weighted_met,
        weighted_total=weighted_total,
        weighted_ratio=weighted_ratio,
        indicators=results,
        verdict=build_verdict(count_met, count_active, count_evaluable),
        warnings=warnings,
        as_of=_coerce_date(_get(reading, "reading_date")),
    )


def results_to_dataframe(result: CompositeResult):
    """Pomocniczo dla UI: tabela wskaźników (wymaga pandas)."""
    import pandas as pd
    return pd.DataFrame([{
        "indicator": r.indicator, "label": r.label, "value": r.value,
        "operator": r.operator, "threshold_value": r.threshold_value,
        "threshold_value2": r.threshold_value2, "weight": r.weight,
        "active": r.active, "met": r.met, "contribution": r.contribution, "note": r.note,
    } for r in result.indicators])


# --------------------------------------------------------------------------- #
# Demo offline (bez sieci/BQ): seed 2026-06-01 + progi z CSV
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    seed_config = [
        {"indicator": "mvrv_z_score",        "operator": "lt",      "threshold_value": 0,    "threshold_value2": None, "weight": 1.0, "active": True,  "description": "Dno: MVRV Z < 0"},
        {"indicator": "nupl",                "operator": "lt",      "threshold_value": 0,    "threshold_value2": None, "weight": 1.0, "active": True,  "description": "Dno: NUPL < 0"},
        {"indicator": "price_to_200w_ratio", "operator": "lte",     "threshold_value": 1.05, "threshold_value2": None, "weight": 1.0, "active": True,  "description": "Dno: cena <= ~105% 200W MA"},
        {"indicator": "whale_accumulating",  "operator": "is_true", "threshold_value": None, "threshold_value2": None, "weight": 1.0, "active": True,  "description": "Dno: flaga TRUE"},
        {"indicator": "fear_greed",          "operator": "lt",      "threshold_value": 25,   "threshold_value2": None, "weight": 0.5, "active": True,  "description": "Dno: F&G < 25"},
        {"indicator": "days_since_ath",      "operator": "between", "threshold_value": 300,  "threshold_value2": 400,  "weight": 1.0, "active": True,  "description": "Dno: ~10-13 mies. od ATH"},
    ]
    seed_reading = {
        "reading_date": date(2026, 6, 1), "price_usd": None, "mvrv_z_score": None,
        "nupl": None, "ma_200w": None, "whale_accumulating": False, "whale_ratio": 0.90,
        "fear_greed": 23, "days_since_ath": None, "ath_date": None,
    }
    res = evaluate(seed_config, seed_reading)
    print(res.verdict)
    print(f"count_met={res.count_met} / active={res.count_active} "
          f"(evaluable={res.count_evaluable}); weighted={res.weighted_met}/{res.weighted_total}")
    for r in res.indicators:
        print(f"  {r.label:24s} value={r.value!s:8s} met={r.met} note={r.note}")
    print(DISCLAIMER)
