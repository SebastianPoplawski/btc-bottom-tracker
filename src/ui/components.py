"""
components.py — krok 04
=======================
Reużywalne widgety warstwy UI (Streamlit + Plotly). Tylko PREZENTACJA:
konsumuje gotowe obiekty z logiki (`composite.CompositeResult`, `dca.DcaState`),
niczego nie liczy ani nie pobiera.
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

import text_pl as T


# --------------------------------------------------------------------------- #
# Styl (drobna wstawka CSS — motyw bazowy jest w .streamlit/config.toml)
# --------------------------------------------------------------------------- #
def inject_css() -> None:
    st.markdown(
        f"""
        <style>
          .btt-badge {{
            display:inline-block; padding:2px 10px; border-radius:999px;
            font-size:0.78rem; font-weight:600; color:#0E1117;
          }}
          .btt-chip {{
            display:inline-block; padding:1px 8px; border-radius:6px;
            font-size:0.75rem; font-weight:600;
          }}
          .btt-card-val {{ font-size:1.55rem; font-weight:700; line-height:1.1; }}
          .btt-card-thr {{ color:#9aa0aa; font-size:0.82rem; }}
          .btt-accent {{ color:{T.ACCENT}; }}
          .btt-muted  {{ color:#9aa0aa; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _met_color(met: Optional[bool]) -> str:
    return {True: T.COLOR_MET, False: T.COLOR_UNMET, None: T.COLOR_NA}[met]


# --------------------------------------------------------------------------- #
# Nagłówek + plakietka świeżości
# --------------------------------------------------------------------------- #
def page_header(mode: str, freshness_msg: str, as_of: Any = None) -> None:
    left, right = st.columns([0.7, 0.3])
    with left:
        st.markdown(
            f"<h1 style='margin-bottom:0'>"
            f"<span class='btt-accent'>₿</span> {T.APP_TITLE}</h1>"
            f"<div class='btt-muted'>{T.APP_TAGLINE}</div>",
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f"<div style='text-align:right'>"
            f"<span class='btt-chip' style='background:{T.ACCENT}22;color:{T.ACCENT}'>"
            f"{T.MODE_LABEL.get(mode, mode)}</span></div>",
            unsafe_allow_html=True,
        )
    if freshness_msg:
        st.caption("🕓 " + freshness_msg)


# --------------------------------------------------------------------------- #
# Composite: gauge + werdykt
# --------------------------------------------------------------------------- #
def _gauge_fig(count_met: int, count_active: int):
    import plotly.graph_objects as go
    rng = max(count_active, 1)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=count_met,
        number={"suffix": f" / {count_active}", "font": {"size": 40}},
        gauge={
            "axis": {"range": [0, rng], "tickmode": "linear", "dtick": 1,
                     "tickcolor": "#9aa0aa"},
            "bar": {"color": T.ACCENT, "thickness": 0.7},
            "borderwidth": 0,
            "steps": [
                {"range": [0, rng * 0.34], "color": "#1A1D24"},
                {"range": [rng * 0.34, rng * 0.67], "color": "#23272f"},
                {"range": [rng * 0.67, rng], "color": "#2c313a"},
            ],
        },
    ))
    fig.update_layout(
        height=230, margin=dict(l=20, r=20, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", font={"color": "#FAFAFA"},
    )
    return fig


def composite_summary(result: Any) -> None:
    col_g, col_v = st.columns([0.42, 0.58])
    with col_g:
        st.plotly_chart(
            _gauge_fig(result.count_met, result.count_active),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    with col_v:
        st.subheader("Werdykt")
        st.write(result.verdict)
        wr = result.weighted_ratio
        if wr is not None:
            st.caption(
                f"Wynik ważony: {result.weighted_met:.2f} / {result.weighted_total:.2f} "
                f"= {wr:.0%} (niuans obok licznika)."
            )
        missing = result.count_active - result.count_evaluable
        if missing > 0:
            st.caption(f"⚠️ {missing} wskaźnik(i) bez danych — nie wliczają się do licznika.")


# --------------------------------------------------------------------------- #
# Siatka kart wskaźników
# --------------------------------------------------------------------------- #
def indicator_grid(result: Any, columns: int = 3) -> None:
    st.subheader(T.SECTION_SIGNALS)
    indicators = [i for i in result.indicators if i.active]
    inactive = [i for i in result.indicators if not i.active]
    cols = st.columns(columns)
    for idx, ind in enumerate(indicators):
        _indicator_card(cols[idx % columns], ind)
    if inactive:
        st.caption("Nieaktywne progi (poza composite): "
                   + ", ".join(i.label for i in inactive))


def _indicator_card(container, ind: Any) -> None:
    color = _met_color(ind.met)
    label_met = T.MET_LABEL[ind.met]
    value_str = T.format_value(ind.indicator, ind.value)
    thr_str = T.format_threshold(ind.operator, ind.threshold_value, ind.threshold_value2)
    help_txt = T.INDICATOR_HELP.get(ind.indicator, "")
    with container.container(border=True):
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;align-items:center'>"
            f"<span style='font-weight:600'>{ind.label}</span>"
            f"<span class='btt-chip' style='background:{color}22;color:{color}'>{label_met}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='btt-card-val' style='color:{color}'>{value_str}</div>"
            f"<div class='btt-card-thr'>próg dna: {thr_str}</div>",
            unsafe_allow_html=True,
        )
        if help_txt:
            st.caption(help_txt)


# --------------------------------------------------------------------------- #
# Wykresy historii
# --------------------------------------------------------------------------- #
def history_charts(history_df: Any) -> None:
    st.subheader(T.SECTION_CHARTS)
    if history_df is None or getattr(history_df, "empty", True):
        st.info("Brak historii do wykresów (tryb demo lub pusta hurtownia).")
        return
    n = len(history_df)
    if n < 2:
        st.caption("Tryb demo: za mało punktów na pełny przebieg — pokazuję dostępny odczyt.")

    import plotly.graph_objects as go
    x = history_df["reading_date"] if "reading_date" in history_df.columns else list(range(n))

    def _line(cols_labels, title, yfmt=None):
        present = [(c, lbl, clr) for c, lbl, clr in cols_labels
                   if c in history_df.columns and history_df[c].notna().any()]
        if not present:
            return
        fig = go.Figure()
        for c, lbl, clr in present:
            fig.add_trace(go.Scatter(x=x, y=history_df[c], mode="lines+markers",
                                     name=lbl, line={"color": clr}))
        fig.update_layout(
            title=title, template="plotly_dark", height=300,
            margin=dict(l=10, r=10, t=40, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    c1, c2 = st.columns(2)
    with c1:
        _line([("price_usd", "Cena BTC", T.ACCENT),
               ("ma_200w", "200W MA", "#6fb1ff")], "Cena vs 200W MA")
        _line([("mvrv_z_score", "MVRV Z", "#f5c451"),
               ("nupl", "NUPL", "#9b8cff")], "MVRV Z / NUPL")
    with c2:
        _line([("fear_greed", "Fear & Greed", "#5fd3a3")], "Fear & Greed")
        _line([("whale_ratio", "Whale Ratio (ref.)", "#ff8c6b")], "Whale Ratio (referencyjnie)")


# --------------------------------------------------------------------------- #
# Panel DCA
# --------------------------------------------------------------------------- #
def dca_panel(state: Any) -> None:
    st.subheader(T.SECTION_DCA)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cena bieżąca", T.usd(state.current_price))
    m2.metric("Sygnały dna", "—" if state.count_met is None else f"{state.count_met}")
    m3.metric("Transze zrealizowane", f"{state.executed_count}")
    m4.metric("Transze oczekujące", f"{state.pending_count}")

    if state.conditions_met_now:
        ids = ", ".join(f"#{t.tranche_id}" for t in state.conditions_met_now)
        st.success(f"Warunki Twojego planu spełnione dla transz: {ids} "
                   f"(cena osiągnięta{' + dość sygnałów' if state.count_met is not None else ''}).")
    elif state.next_trigger is not None:
        nt = state.next_trigger
        st.info(f"Najbliższy próg w dół: transza #{nt.tranche_id} przy "
                f"{T.usd(nt.trigger_price_usd)}.")

    import pandas as pd
    rows = []
    for t in state.tranches:
        rows.append({
            "#": t.tranche_id,
            "Próg": T.usd(t.trigger_price_usd),
            "Kwota": T.usd(t.allocation_usd),
            "% planu": "—" if t.allocation_pct is None else f"{t.allocation_pct:g}%",
            "Min. sygn.": "—" if t.min_signals_required is None else t.min_signals_required,
            "Status": T.STATUS_PL.get(t.status, t.status),
            "Stan": t.state_label,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if state.total_alloc_usd is not None:
        st.caption(f"Budżet w planie: {T.usd(state.total_alloc_usd)} "
                   f"(zrealizowane: {T.usd(state.executed_alloc_usd)}, "
                   f"oczekujące: {T.usd(state.pending_alloc_usd)}).")
    else:
        st.caption("Uzupełnij `allocation_usd` / `allocation_pct` w arkuszu, "
                   "by zobaczyć podsumowanie budżetu.")


# --------------------------------------------------------------------------- #
# Pomocnicze
# --------------------------------------------------------------------------- #
def warnings_block(warnings: list[str], title: str = "Uwagi") -> None:
    if not warnings:
        return
    with st.expander(f"{title} ({len(warnings)})", expanded=False):
        for w in warnings:
            st.write("• " + str(w))


def footer(disclaimer: str) -> None:
    st.divider()
    st.caption("⚠️ " + disclaimer)
