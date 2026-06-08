"""
dca.py — krok 04
================
Lekka, CZYSTA logika planu DCA (zakupy transzami $70K -> $55K). Bez UI, bez sieci,
bez BigQuery. Na wejściu: tabela transz (z `dca_tranches`), bieżąca cena BTC oraz
liczba spełnionych sygnałów dna (`count_met` z composite). Na wyjściu: stan każdej
transzy + agregaty.

WAŻNE: to NIE jest porada „kup/sprzedaj". Moduł raportuje wyłącznie, które warunki
Twojego WŁASNEGO planu są spełnione (cena osiągnięta / dość sygnałów). Decyzję
podejmujesz sam.

Reguły:
  - price_reached  = cena <= trigger_price_usd (cena spadła do/poniżej progu transzy),
  - signals_ok     = count_met >= min_signals_required (gdy próg sygnałów ustawiony),
  - conditions_met = status 'pending' AND price_reached AND (signals_ok lub brak progu sygnałów).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Optional

DISCLAIMER = "Narzędzie analityczne, nie porada inwestycyjna."

STATUS_PENDING = "pending"
STATUS_EXECUTED = "executed"
STATUS_SKIPPED = "skipped"
VALID_STATUS = {STATUS_PENDING, STATUS_EXECUTED, STATUS_SKIPPED}
STATUS_PL = {
    STATUS_PENDING: "oczekująca",
    STATUS_EXECUTED: "zrealizowana",
    STATUS_SKIPPED: "pominięta",
}


# --------------------------------------------------------------------------- #
# Helpery (lokalne, by moduł był samodzielny — działa też bez pandas)
# --------------------------------------------------------------------------- #
def _is_missing(v: Any) -> bool:
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


def _to_number(v: Any) -> Optional[float]:
    if isinstance(v, bool) or _is_missing(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return float(str(v).strip().replace(",", "."))
        except (TypeError, ValueError):
            return None


def _to_int(v: Any) -> Optional[int]:
    f = _to_number(v)
    return None if f is None else int(round(f))


def _to_date(v: Any) -> Optional[date]:
    if _is_missing(v):
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        import pandas as pd
        d = pd.to_datetime(v, errors="coerce")
        return None if pd.isna(d) else d.date()
    except Exception:
        return None


def _to_str(v: Any) -> str:
    return "" if _is_missing(v) else str(v)


def _records(tranches: Any) -> list[dict]:
    """Normalizuje wejście: pandas.DataFrame / list[dict] / iterable[Mapping] -> list[dict]."""
    if tranches is None:
        return []
    try:
        import pandas as pd
        if isinstance(tranches, pd.DataFrame):
            return tranches.to_dict("records")
    except Exception:
        pass
    out: list[dict] = []
    for r in tranches:
        try:
            out.append(dict(r))
        except (TypeError, ValueError):
            continue
    return out


# --------------------------------------------------------------------------- #
# Modele
# --------------------------------------------------------------------------- #
@dataclass
class TrancheState:
    tranche_id: Optional[int]
    trigger_price_usd: Optional[float]
    allocation_usd: Optional[float]
    allocation_pct: Optional[float]
    min_signals_required: Optional[int]
    status: str
    executed_date: Optional[date]
    executed_price_usd: Optional[float]
    note: str
    # pochodne
    price_reached: Optional[bool]    # None gdy cena nieznana
    signals_ok: Optional[bool]       # None gdy brak progu sygnałów lub count_met nieznany
    conditions_met: bool             # warunki planu spełnione (pending + cena + sygnały)
    state_label: str                 # opis PL


@dataclass
class DcaState:
    current_price: Optional[float]
    count_met: Optional[int]
    tranches: list[TrancheState]
    total_alloc_usd: Optional[float]
    executed_alloc_usd: float
    pending_alloc_usd: float
    executed_count: int
    pending_count: int
    conditions_met_now: list[TrancheState]   # transze pending z warunkami spełnionymi
    next_trigger: Optional[TrancheState]     # najbliższy próg poniżej bieżącej ceny
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER


# --------------------------------------------------------------------------- #
# Główna funkcja
# --------------------------------------------------------------------------- #
def compute_dca_state(tranches: Any,
                      current_price: Optional[float] = None,
                      count_met: Optional[int] = None) -> DcaState:
    """Liczy stan planu DCA. Brak ceny / brak sygnałów -> stany 'nieznane' (None),
    nigdy wyjątek (spójnie z resztą warstwy danych)."""
    warnings: list[str] = []
    price = _to_number(current_price)
    cmet = _to_int(count_met)

    if price is None:
        warnings.append("Brak bieżącej ceny — nie mogę ocenić, które progi cenowe osiągnięto.")

    states: list[TrancheState] = []
    for rec in _records(tranches):
        status = _to_str(rec.get("status")).strip().lower() or STATUS_PENDING
        if status not in VALID_STATUS:
            warnings.append(f"Transza {rec.get('tranche_id')}: nieznany status '{status}'.")
        trigger = _to_number(rec.get("trigger_price_usd"))
        min_sig = _to_int(rec.get("min_signals_required"))

        # price_reached
        if price is None or trigger is None:
            price_reached: Optional[bool] = None
        else:
            price_reached = price <= trigger

        # signals_ok
        if min_sig is None:
            signals_ok: Optional[bool] = None      # brak bramki sygnałowej
        elif cmet is None:
            signals_ok = None
        else:
            signals_ok = cmet >= min_sig

        # conditions_met (tylko transze pending mogą być „gotowe")
        conditions_met = (
            status == STATUS_PENDING
            and price_reached is True
            and (signals_ok is True or min_sig is None)
        )

        states.append(TrancheState(
            tranche_id=_to_int(rec.get("tranche_id")),
            trigger_price_usd=trigger,
            allocation_usd=_to_number(rec.get("allocation_usd")),
            allocation_pct=_to_number(rec.get("allocation_pct")),
            min_signals_required=min_sig,
            status=status,
            executed_date=_to_date(rec.get("executed_date")),
            executed_price_usd=_to_number(rec.get("executed_price_usd")),
            note=_to_str(rec.get("note")),
            price_reached=price_reached,
            signals_ok=signals_ok,
            conditions_met=conditions_met,
            state_label=_state_label(status, trigger, price_reached, signals_ok, min_sig),
        ))

    # agregaty
    executed = [t for t in states if t.status == STATUS_EXECUTED]
    pending = [t for t in states if t.status == STATUS_PENDING]
    executed_alloc = sum(t.allocation_usd for t in executed if t.allocation_usd is not None)
    pending_alloc = sum(t.allocation_usd for t in pending if t.allocation_usd is not None)
    all_alloc = [t.allocation_usd for t in states if t.allocation_usd is not None]
    total_alloc = sum(all_alloc) if all_alloc else None

    conditions_now = [t for t in pending if t.conditions_met]

    # następny próg w dół: najwyższa cena progowa wśród transz pending jeszcze nieosiągniętych
    not_reached = [t for t in pending if t.trigger_price_usd is not None and t.price_reached is False]
    if not_reached:
        next_trigger: Optional[TrancheState] = max(not_reached, key=lambda t: t.trigger_price_usd)
    elif price is None:
        # bez ceny: pokaż najwyższy próg pending jako orientację
        cand = [t for t in pending if t.trigger_price_usd is not None]
        next_trigger = max(cand, key=lambda t: t.trigger_price_usd) if cand else None
    else:
        next_trigger = None

    return DcaState(
        current_price=price,
        count_met=cmet,
        tranches=states,
        total_alloc_usd=total_alloc,
        executed_alloc_usd=executed_alloc,
        pending_alloc_usd=pending_alloc,
        executed_count=len(executed),
        pending_count=len(pending),
        conditions_met_now=conditions_now,
        next_trigger=next_trigger,
        warnings=warnings,
    )


def _state_label(status: str, trigger: Optional[float],
                 price_reached: Optional[bool], signals_ok: Optional[bool],
                 min_sig: Optional[int]) -> str:
    if status == STATUS_EXECUTED:
        return "zrealizowana"
    if status == STATUS_SKIPPED:
        return "pominięta"
    # pending
    if price_reached is None:
        return "oczekująca — cena nieznana"
    if price_reached is False:
        tp = f"${trigger:,.0f}".replace(",", " ") if trigger is not None else "progu"
        return f"oczekująca — czeka na cenę ≤ {tp}"
    # cena osiągnięta
    if min_sig is not None and signals_ok is False:
        return f"cena osiągnięta — za mało sygnałów (wymagane ≥ {min_sig})"
    if min_sig is None:
        return "warunek cenowy spełniony"
    return "warunki planu spełnione (cena + sygnały)"
