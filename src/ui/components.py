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
def _gauge_fig(weighted_ratio: Optional[float]):
    """Gauge = wynik WAŻONY (uczciwy headline). Skala 0–100%.
    weighted_ratio is None (brak ocenialnych) -> pokaż 0 z adnotacją."""
    import plotly.graph_objects as go
    value = 0 if weighted_ratio is None else weighted_ratio * 100
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": "%", "font": {"size": 40}},
        gauge={
            "axis": {"range": [0, 100], "ticksuffix": "%", "tickcolor": "#9aa0aa"},
            "bar": {"color": T.ACCENT, "thickness": 0.7},
            "borderwidth": 0,
            "steps": [
                {"range": [0, 34], "color": "#1A1D24"},
                {"range": [34, 67], "color": "#23272f"},
                {"range": [67, 100], "color": "#2c313a"},
            ],
        },
    ))
    fig.update_layout(
        height=230, margin=dict(l=20, r=20, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", font={"color": "#FAFAFA"},
    )
    if weighted_ratio is None:
        fig.add_annotation(
            text="brak ocenialnych wskaźników", showarrow=False,
            x=0.5, y=0.0, xref="paper", yref="paper",
            font={"color": "#9aa0aa", "size": 12},
        )
    return fig


# Pasma Fear & Greed — tinty COLOR_MET/COLOR_UNMET, żeby zegar mówił tym samym
# językiem co karty (strach = zielony po stronie dna, chciwość = czerwony).
_FNG_BANDS = (
    "rgba(31,157,85,0.45)",    # skrajny strach — sygnał dna
    "rgba(31,157,85,0.20)",    # strach
    "#23272f",                 # neutralnie
    "rgba(192,86,59,0.20)",    # chciwość
    "rgba(192,86,59,0.45)",    # skrajna chciwość
)


def fng_gauge_fig(value: Optional[float], fear_threshold: float = 25,
                  greed_threshold: float = 75):
    """Zegar Fear & Greed (0–100) — pasma nastroju + znacznik progu dna.
    value is None -> pokaż 0 z adnotacją (jak `_gauge_fig`)."""
    import plotly.graph_objects as go
    missing = value is None or value != value  # None albo NaN
    # Sam gauge, bez liczby — wartość jest już w nagłówku karty (btt-card-val).
    fig = go.Figure(go.Indicator(
        mode="gauge",
        value=0 if missing else float(value),
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#9aa0aa"},
            "bar": {"color": T.ACCENT, "thickness": 0.7},
            "borderwidth": 0,
            "steps": [
                {"range": [0, fear_threshold], "color": _FNG_BANDS[0]},
                {"range": [fear_threshold, 45], "color": _FNG_BANDS[1]},
                {"range": [45, 55], "color": _FNG_BANDS[2]},
                {"range": [55, greed_threshold], "color": _FNG_BANDS[3]},
                {"range": [greed_threshold, 100], "color": _FNG_BANDS[4]},
            ],
            # Znacznik = próg dna (F&G < 25 = pasmo Extreme Fear).
            "threshold": {
                "line": {"color": T.COLOR_MET, "width": 3},
                "thickness": 0.85,
                "value": fear_threshold,
            },
        },
    ))
    fig.update_layout(
        height=170, margin=dict(l=15, r=15, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", font={"color": "#FAFAFA"},
    )
    if missing:
        fig.add_annotation(
            text="brak danych", showarrow=False,
            x=0.5, y=0.0, xref="paper", yref="paper",
            font={"color": "#9aa0aa", "size": 12},
        )
    return fig


def composite_summary(result: Any) -> None:
    col_g, col_v = st.columns([0.42, 0.58])
    with col_g:
        st.plotly_chart(
            _gauge_fig(result.weighted_ratio),
            use_container_width=True,
            config={"displayModeBar": False},
        )
        # Twardy licznik jako podpis pod ważonym headline'em.
        st.caption(f"Twarde progi: {result.count_met}/{result.count_active} spełnione")
    with col_v:
        st.subheader("Werdykt")
        st.write(result.verdict)
        st.caption(T.COMPOSITE_NOTE)
        if result.weighted_ratio is not None:
            st.caption("Zegar pokazuje wynik ważony (potwierdzenie dna 0–100%); "
                       "twardy licznik spełnionych progów jest pod zegarem.")
        missing = result.count_active - result.count_evaluable
        if missing > 0:
            st.caption(f"⚠️ {missing} wskaźnik(i) bez danych — nie wliczają się do licznika.")


def _gauge_column(result: Any, title: str, note: str, key: str) -> None:
    """Pojedyncza kolumna dual-gauge: tytuł, zegar, twardy licznik, werdykt."""
    st.markdown(f"**{title}**")
    st.plotly_chart(
        _gauge_fig(result.weighted_ratio),
        use_container_width=True,
        config={"displayModeBar": False},
        key=f"gauge_{key}",
    )
    st.caption(f"Twarde progi: {result.count_met}/{result.count_active} spełnione")
    st.write(result.verdict)
    if note:
        st.caption(note)
    missing = result.count_active - result.count_evaluable
    if missing > 0:
        st.caption(f"⚠️ {missing} wskaźnik(i) bez danych — nie wliczają się do licznika.")


def dual_composite_summary(bottom: Any, top: Any) -> None:
    """krok 17: dwa zegary obok siebie — DNO (okno zakupu) | SZCZYT (okno wyjścia).
    Oba pokazują wynik ważony 0–100%; twarde liczniki w podpisach."""
    col_b, col_t = st.columns(2)
    with col_b:
        _gauge_column(bottom, f"🟢 {T.GAUGE_BOTTOM_TITLE}", T.COMPOSITE_NOTE, "bottom")
    with col_t:
        _gauge_column(top, f"🔴 {T.GAUGE_TOP_TITLE}", T.COMPOSITE_NOTE_TOP, "top")


# --------------------------------------------------------------------------- #
# Siatka kart wskaźników
# --------------------------------------------------------------------------- #
def indicator_grid(result: Any, columns: int = 3, title: str = T.SECTION_SIGNALS,
                   threshold_prefix: str = "próg dna:",
                   help_map: Optional[dict] = None,
                   fng_gauge: bool = False) -> None:
    """Siatka kart wskaźników. Od kroku 17 parametryzowana (strony top/macro
    podają własny tytuł, prefiks progu i mapę pomocy) — wywołanie bez
    argumentów zachowuje się jak przed krokiem 17 (strona dna).
    `fng_gauge=True` dokłada zegar nastroju do karty `fear_greed`."""
    st.subheader(title)
    indicators = [i for i in result.indicators if i.active]
    inactive = [i for i in result.indicators if not i.active]
    cols = st.columns(columns)
    for idx, ind in enumerate(indicators):
        _indicator_card(cols[idx % columns], ind, threshold_prefix,
                        help_map if help_map is not None else T.INDICATOR_HELP,
                        fng_gauge=fng_gauge)
    if inactive:
        st.caption("Nieaktywne progi (poza composite): "
                   + ", ".join(i.label for i in inactive))


def _indicator_card(container, ind: Any, threshold_prefix: str = "próg dna:",
                    help_map: Optional[dict] = None,
                    fng_gauge: bool = False) -> None:
    color = _met_color(ind.met)
    label_met = T.MET_LABEL[ind.met]
    # Stopniowy F&G: spełniony, ale z wkładem częściowym (0 < contribution < weight).
    if ind.met is True and 0 < ind.contribution < ind.weight:
        label_met = "częściowy"
    value_str = T.format_value(ind.indicator, ind.value)
    thr_str = T.format_threshold(ind.operator, ind.threshold_value, ind.threshold_value2)
    help_txt = (help_map or T.INDICATOR_HELP).get(ind.indicator, "")
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
            f"<div class='btt-card-thr'>{threshold_prefix} {thr_str}</div>",
            unsafe_allow_html=True,
        )
        if fng_gauge and ind.indicator == "fear_greed":
            st.plotly_chart(
                fng_gauge_fig(ind.value, fear_threshold=(ind.threshold_value
                                                         if ind.threshold_value is not None
                                                         else 25)),
                use_container_width=True,
                config={"displayModeBar": False},
                key="fng_gauge_card",
            )
        if help_txt:
            st.caption(help_txt)


# --------------------------------------------------------------------------- #
# Panel makro (krok 17) — OSOBNY licznik risk-off, poza frameworkiem
# --------------------------------------------------------------------------- #
def macro_panel(result: Any) -> None:
    indicator_grid(result, columns=4, title=T.SECTION_MACRO,
                   threshold_prefix="warunek risk-off:",
                   help_map=T.INDICATOR_HELP_MACRO)
    st.write(result.verdict)
    st.caption(T.MACRO_NOTE)


# --------------------------------------------------------------------------- #
# Wykresy historii
# --------------------------------------------------------------------------- #
def price_ma_fng_fig(history: Any):
    """Cena + 200W MA (lewa oś USD) i Fear & Greed (prawa oś 0–100, pasmo dna
    < 25). connectgaps=False — dziury w historii mają zostać dziurami.
    Zwraca None, gdy nie ma czego rysować."""
    import plotly.graph_objects as go
    if history is None or getattr(history, "empty", True):
        return None

    def _has(col: str) -> bool:
        return col in history.columns and history[col].notna().any()

    if not (_has("price_usd") or _has("ma_200w")):
        return None

    x = (history["reading_date"] if "reading_date" in history.columns
         else list(range(len(history))))

    fig = go.Figure()
    for col, label, color in (("price_usd", "Cena BTC", T.ACCENT),
                              ("ma_200w", "200W MA", "#6fb1ff")):
        if _has(col):
            fig.add_trace(go.Scatter(
                x=x, y=history[col], mode="lines+markers", name=label,
                line={"color": color}, connectgaps=False,
            ))
    if _has("fear_greed"):
        fig.add_trace(go.Scatter(
            x=x, y=history["fear_greed"], mode="lines+markers",
            name="Fear & Greed", yaxis="y2",
            line={"color": "#5fd3a3", "width": 1.5}, connectgaps=False,
        ))
        # Pasmo Extreme Fear (< 25) na prawej osi — tło sygnału dna.
        fig.add_shape(
            type="rect", xref="paper", yref="y2", x0=0, x1=1, y0=0, y1=25,
            fillcolor="rgba(31,157,85,0.12)", line={"width": 0}, layer="below",
        )

    fig.update_layout(
        title="Cena vs 200W MA + Fear & Greed", template="plotly_dark", height=300,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.2),
        yaxis=dict(title="USD"),
        yaxis2=dict(title="F&G", range=[0, 100], overlaying="y", side="right",
                    showgrid=False, fixedrange=True),
    )
    return fig


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

    # Pi Cycle (krok 17): 2x350DMA liczone TYLKO do wykresu (prezentacja),
    # sygnał liczy composite z surowych ma_111d/ma_350d.
    if "ma_350d" in history_df.columns and history_df["ma_350d"].notna().any():
        history_df = history_df.assign(_pi_2x350=history_df["ma_350d"] * 2)

    c1, c2 = st.columns(2)
    with c1:
        fig_pmf = price_ma_fng_fig(history_df)
        if fig_pmf is not None:
            st.plotly_chart(fig_pmf, use_container_width=True,
                            config={"displayModeBar": False})
        _line([("mvrv_z_score", "MVRV Z", "#f5c451"),
               ("nupl", "NUPL", "#9b8cff")], "MVRV Z / NUPL")
        _line([("price_usd", "Cena BTC", T.ACCENT),
               ("ma_111d", "111DMA", "#5fd3a3"),
               ("_pi_2x350", "2× 350DMA", "#ff8c6b")], "Pi Cycle Top (111DMA vs 2× 350DMA)")
    with c2:
        # F&G ma własny przebieg na prawej osi wykresu ceny — osobny wykres zbędny.
        _line([("whale_ratio", "Whale Ratio (ref.)", "#ff8c6b")], "Whale Ratio (referencyjnie)")
        _line([("fed_funds_rate", "Stopa Fed", "#f5c451"),
               ("dxy_proxy", "Dollar index (proxy)", "#6fb1ff"),
               ("m2_yoy", "M2 r/r (%)", "#9b8cff")], "Makro (FRED)")


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
# Panel transz SPRZEDAŻY (krok 17) — lustro dca_panel; alokacje w % pozycji
# --------------------------------------------------------------------------- #
def exit_panel(state: Any) -> None:
    st.subheader(T.SECTION_EXIT)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cena bieżąca", T.usd(state.current_price))
    m2.metric("Sygnały szczytu", "—" if state.top_count_met is None else f"{state.top_count_met}")
    m3.metric("Transze zrealizowane", f"{state.executed_count}")
    m4.metric("Transze oczekujące", f"{state.pending_count}")

    if state.conditions_met_now:
        ids = ", ".join(f"#{t.tranche_id}" for t in state.conditions_met_now)
        st.success(f"Warunki Twojego planu wyjścia spełnione dla transz: {ids} "
                   f"(cena osiągnięta{' + dość sygnałów szczytu' if state.top_count_met is not None else ''}).")
    elif state.next_trigger is not None:
        nt = state.next_trigger
        if nt.trigger_price_usd is not None:
            st.info(f"Najbliższy próg w górę: transza #{nt.tranche_id} przy "
                    f"{T.usd(nt.trigger_price_usd)}.")

    import pandas as pd
    rows = []
    for t in state.tranches:
        rows.append({
            "#": t.tranche_id,
            "Próg": T.usd(t.trigger_price_usd),
            "% pozycji": "—" if t.allocation_pct is None else f"{t.allocation_pct:g}%",
            "Min. sygn. szczytu": "—" if t.min_top_signals is None else t.min_top_signals,
            "Status": T.STATUS_PL.get(t.status, t.status),
            "Stan": t.state_label,
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Brak transz sprzedaży — załóż zakładkę `sell_tranches` "
                "(scripts/bootstrap_sheet.py) i wpisz progi swojego planu wyjścia.")

    if state.total_alloc_pct is not None:
        st.caption(f"Plan wyjścia obejmuje {state.total_alloc_pct:g}% pozycji "
                   f"(zrealizowane: {state.executed_alloc_pct:g}%, "
                   f"oczekujące: {state.pending_alloc_pct:g}%).")
    elif rows:
        st.caption("Uzupełnij `trigger_price_usd` i `allocation_pct` w zakładce "
                   "`sell_tranches`, by plan wyjścia był policzalny.")


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
