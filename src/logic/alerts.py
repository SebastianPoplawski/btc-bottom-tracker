"""
alerts.py — krok 20
===================
CZYSTA logika alertów (zero I/O): buduje migawkę stanu frameworka z jednego
odczytu (`snapshot`) i porównuje dwie migawki dzień/dzień (`build_alerts`).
Wysyłką (GitHub Issue -> mail) zajmuje się scripts/check_alerts.py.

Podejście STATELESS: nie trzymamy żadnego "stanu alertów" — wczorajszą migawkę
liczymy z wczorajszego wiersza `indicator_readings` tym samym configiem, co
dzisiejszą. Zmiana progu w arkuszu nie generuje fałszywego alertu "z historii",
bo obie strony porównania liczone są aktualnymi regułami.

Co alarmujemy (zmiana wzgl. poprzedniego odczytu):
  - zmiana licznika sygnałów DNA (w górę i w dół — spadek też jest informacją),
  - zmiana licznika sygnałów SZCZYTU,
  - NOWE transze DCA / sprzedaży ze spełnionymi warunkami planu.
Makro (risk-off) celowo POZA alertami — to kontekst, nie sygnał (unikamy szumu).

Werdykty opisowe, bez "kup/sprzedaj". Disclaimer w treści issue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import composite
import dca
import exit_plan

DISCLAIMER = composite.DISCLAIMER


# --------------------------------------------------------------------------- #
# Migawka stanu z jednego odczytu
# --------------------------------------------------------------------------- #
@dataclass
class Snapshot:
    reading_date: Optional[date]
    bottom_met: int
    bottom_active: int
    top_met: int
    top_active: int
    price_usd: Optional[float]
    dca_ready: frozenset = frozenset()    # tranche_id transz DCA z warunkami planu
    exit_ready: frozenset = frozenset()   # tranche_id transz sprzedaży z warunkami planu
    warnings: list[str] = field(default_factory=list)


def _price(reading: Any) -> Optional[float]:
    try:
        val = reading.get("price_usd") if hasattr(reading, "get") else reading["price_usd"]
    except (KeyError, TypeError):
        return None
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN out


def snapshot(config: Any, reading: Any,
             dca_df: Any = None, sell_df: Any = None) -> Snapshot:
    """Migawka: liczniki bottom/top + zbiory 'gotowych' transz dla jednego odczytu.
    Te same ścieżki logiki co UI (evaluate_side / compute_dca_state /
    compute_exit_state) — alert nigdy nie rozjedzie się z dashboardem."""
    bottom = composite.evaluate_side(config, reading, composite.SIDE_BOTTOM)
    top = composite.evaluate_side(config, reading, composite.SIDE_TOP)
    price = _price(reading)

    dca_ready: frozenset = frozenset()
    if dca_df is not None:
        st = dca.compute_dca_state(dca_df, current_price=price, count_met=bottom.count_met)
        dca_ready = frozenset(t.tranche_id for t in st.conditions_met_now
                              if t.tranche_id is not None)

    exit_ready: frozenset = frozenset()
    if sell_df is not None:
        st = exit_plan.compute_exit_state(sell_df, current_price=price,
                                          top_count_met=top.count_met)
        exit_ready = frozenset(t.tranche_id for t in st.conditions_met_now
                               if t.tranche_id is not None)

    return Snapshot(
        reading_date=bottom.as_of,
        bottom_met=bottom.count_met, bottom_active=bottom.count_active,
        top_met=top.count_met, top_active=top.count_active,
        price_usd=price,
        dca_ready=dca_ready, exit_ready=exit_ready,
        warnings=list(bottom.warnings) + list(top.warnings),
    )


# --------------------------------------------------------------------------- #
# Porównanie dzień/dzień -> lista alertów (PL)
# --------------------------------------------------------------------------- #
def build_alerts(today: Snapshot, prev: Optional[Snapshot]) -> list[str]:
    """Lista komunikatów alertowych; pusta = brak zmian = brak issue.
    prev=None (pierwszy przebieg / luka w historii) -> celowo BRAK alertów."""
    if prev is None:
        return []
    out: list[str] = []

    if today.bottom_met != prev.bottom_met:
        strzalka = "WZRÓSŁ" if today.bottom_met > prev.bottom_met else "SPADŁ"
        out.append(
            f"Licznik sygnałów DNA {strzalka}: {prev.bottom_met} -> {today.bottom_met} "
            f"(z {today.bottom_active} aktywnych)."
        )
    if today.top_met != prev.top_met:
        strzalka = "WZRÓSŁ" if today.top_met > prev.top_met else "SPADŁ"
        out.append(
            f"Licznik sygnałów SZCZYTU {strzalka}: {prev.top_met} -> {today.top_met} "
            f"(z {today.top_active} aktywnych)."
        )

    new_dca = sorted(today.dca_ready - prev.dca_ready)
    if new_dca:
        ids = ", ".join(f"#{i}" for i in new_dca)
        out.append(f"NOWE transze DCA (zakup) ze spełnionymi warunkami planu: {ids}.")

    new_exit = sorted(today.exit_ready - prev.exit_ready)
    if new_exit:
        ids = ", ".join(f"#{i}" for i in new_exit)
        out.append(f"NOWE transze SPRZEDAŻY ze spełnionymi warunkami planu: {ids}.")

    return out


def issue_payload(alerts: list[str], today: Snapshot,
                  prev: Optional[Snapshot] = None,
                  app_url: str = "") -> dict:
    """Tytuł + treść GitHub Issue (markdown). Wołaj tylko gdy alerts niepuste."""
    d = today.reading_date.isoformat() if today.reading_date else "?"
    title = f"ALERT {d}: " + (alerts[0] if len(alerts) == 1
                              else f"{len(alerts)} zmiany sygnałów frameworka")
    # Tytuł zwięzły — GitHub obcina długie; szczegóły w body.
    if len(title) > 100:
        title = f"ALERT {d}: zmiana sygnałów frameworka ({len(alerts)})"

    lines = [f"Odczyt: **{d}**"
             + (f" (poprzedni: {prev.reading_date.isoformat()})" if prev and prev.reading_date else ""),
             ""]
    lines += [f"- {a}" for a in alerts]
    lines += ["",
              f"Stan: dno **{today.bottom_met}/{today.bottom_active}**, "
              f"szczyt **{today.top_met}/{today.top_active}**"
              + (f", cena ${today.price_usd:,.0f}".replace(",", " ")
                 if today.price_usd is not None else "") + "."]
    if app_url:
        lines += ["", f"Dashboard: {app_url}"]
    lines += ["", f"> {DISCLAIMER} Alert opisuje zmiany wg reguł Twojego frameworka."]
    return {"title": title, "body": "\n".join(lines), "labels": ["alert"]}
