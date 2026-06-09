"""
app_dash.py — krok 05 (wariant Dash, szkielet do porownania ze Streamlit)
=========================================================================
Dash konsumuje TE SAME warstwy co app.py (Streamlit):
    config (demo/live) + odczyty -> composite.evaluate / dca.compute_dca_state.
Logika i ingestion sa wspoldzielone; tu jest WYLACZNIE prezentacja (Dash + Plotly).

Z src/ui/ bierzemy TYLKO text_pl (czyste stale/formatery PL, bez Streamlita).
components.py (Streamlit-specyficzny) NIE jest importowany — patrz STATUS, otwarte
pytanie #2: nic Streamlit-owego nie przecieka do wariantu Dash.

Tryb: APP_MODE=demo (seed, bez chmury) / APP_MODE=live (BigQuery + Sheets).
      BTT_DEMO=1 wymusza demo (spojnie z config.is_demo()).

Uruchomienie (LOKALNIE; Streamlit Cloud nie uruchomi Dash — inny runtime):
    pip install -r requirements.txt
    python app_dash.py            # -> http://127.0.0.1:8050

⚠️ Narzedzie analityczne, nie porada inwestycyjna.
"""
from __future__ import annotations

import os
import sys
import logging
from typing import Any, Optional

import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output

# --- sciezki importu (spojnie z app.py / run_ingest.py / tests) ------------ #
_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (
    os.path.join(_ROOT, "src"),
    os.path.join(_ROOT, "src", "logic"),
    os.path.join(_ROOT, "src", "ui"),
    os.path.join(_ROOT, "src", "ingestion"),
    os.path.join(_ROOT, "src", "warehouse"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config                      # src/config.py
import composite                   # src/logic/composite.py
import dca                          # src/logic/dca.py
import text_pl as T                # src/ui/text_pl.py  (czyste stale PL, bez Streamlita)

logger = logging.getLogger(__name__)

# --- Motyw (spojny z .streamlit/config.toml) ------------------------------- #
C_BG     = "#0E1117"
C_PANEL  = "#1A1D24"
C_PANEL2 = "#23272f"
C_TEXT   = "#FAFAFA"
C_MUTED  = "#9aa0aa"
C_GRID   = "#2A2F3A"
C_ACCENT = T.ACCENT


# --------------------------------------------------------------------------- #
# Ladowanie danych — odwzorowanie app.py (_load_demo / _load_live).
# Te same struktury wynikowe, by composite/dca dostaly identyczne wejscie.
# --------------------------------------------------------------------------- #
def _load_demo() -> dict:
    import mock
    seed = mock.load_seed()
    as_of = mock.snapshot_date(seed)
    msg = (f"Tryb DEMO — snapshot {as_of.isoformat()}." if as_of else "Tryb DEMO — dane seed.")
    return {
        "config": mock.seed_config(seed),
        "reading": mock.latest_reading(seed),
        "history_df": mock.readings_df(seed),
        "dca_df": mock.dca_df(seed),
        "freshness_msg": msg,
        "as_of": as_of,
        "warnings": [],
    }


def _load_live() -> dict:
    import sheets
    import price_binance
    import fear_greed_api
    warnings: list[str] = []

    bundle = sheets.load_all()
    warnings += bundle.validation.warnings + bundle.validation.errors
    cfg = bundle.config.to_dict("records") if not bundle.config.empty else []
    dca_df = bundle.dca

    manual_row = sheets.latest_reading(bundle.readings)
    reading: dict[str, Any] = {}
    if manual_row is not None:
        reading = dict(sheets.build_reading_values(manual_row))
        reading["reading_date"] = manual_row.get("reading_date")

    pdata = price_binance.get_price_and_ma()
    warnings += pdata.warnings
    if pdata.price_usd is not None:
        reading["price_usd"] = pdata.price_usd
    if pdata.ma_200w is not None:
        reading["ma_200w"] = pdata.ma_200w
    fg = fear_greed_api.fetch_fear_greed()
    warnings += fg.warnings
    if fg.value is not None:
        reading["fear_greed"] = fg.value

    try:
        import bigquery_client as wh
        history_df = wh.read_history(days=365)
    except Exception as exc:
        import pandas as pd
        history_df = pd.DataFrame()
        warnings.append(f"Historia z BigQuery niedostepna ({exc}).")

    return {
        "config": cfg, "reading": reading, "history_df": history_df, "dca_df": dca_df,
        "freshness_msg": bundle.freshness.message, "as_of": bundle.freshness.latest_date,
        "warnings": warnings,
    }


def _load_data() -> dict:
    settings = config.load_settings()
    if settings.is_demo:
        return _load_demo()
    try:
        return _load_live()
    except Exception as exc:
        return {
            "config": [], "reading": {}, "history_df": None, "dca_df": None,
            "freshness_msg": f"Tryb LIVE niedostepny ({exc}). Ustaw APP_MODE=demo lub sprawdz sekrety.",
            "as_of": None, "warnings": [f"LIVE error: {exc}"],
        }


# Prosty cache: zmiana n_clicks (klik „Odswiez") wymusza ponowne zaladowanie;
# zmiana ceny (DCA) korzysta z cache, by nie odpytywac API.
_CACHE: dict = {"data": None, "clicks": None}


def _data_cached(n_clicks: Optional[int]) -> dict:
    if _CACHE["data"] is None or n_clicks != _CACHE["clicks"]:
        _CACHE["data"] = _load_data()
        _CACHE["clicks"] = n_clicks
    return _CACHE["data"]


def _reading_price(reading: Any) -> Optional[float]:
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
    return None if f != f else f


# --------------------------------------------------------------------------- #
# Figury (Plotly)
# --------------------------------------------------------------------------- #
def _gauge_fig(count_met: int, count_active: int) -> go.Figure:
    rng = max(count_active, 1)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=count_met,
        number={"suffix": f" / {count_active}", "font": {"size": 42, "color": C_TEXT}},
        gauge={
            "axis": {"range": [0, rng], "tickmode": "linear", "dtick": 1,
                     "tickcolor": C_MUTED, "tickfont": {"color": C_MUTED}},
            "bar": {"color": C_ACCENT, "thickness": 0.7}, "borderwidth": 0, "bgcolor": C_PANEL2,
            "steps": [
                {"range": [0, rng * 0.34], "color": "#1A1D24"},
                {"range": [rng * 0.34, rng * 0.67], "color": "#23272f"},
                {"range": [rng * 0.67, rng], "color": "#2c313a"},
            ],
        },
    ))
    fig.update_layout(height=230, margin=dict(l=20, r=20, t=10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", font={"color": C_TEXT})
    return fig


def _line_fig(history_df, series, title) -> Optional[go.Figure]:
    present = [(c, lbl, clr) for c, lbl, clr in series
               if c in history_df.columns and history_df[c].notna().any()]
    if not present:
        return None
    x = history_df["reading_date"] if "reading_date" in history_df.columns else list(range(len(history_df)))
    fig = go.Figure()
    for c, lbl, clr in present:
        fig.add_trace(go.Scatter(x=x, y=history_df[c], mode="lines+markers", name=lbl, line={"color": clr}))
    fig.update_layout(title={"text": title, "font": {"color": C_TEXT, "size": 15}},
                      template="plotly_dark", height=300, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=-0.2, font={"color": C_MUTED}),
                      xaxis={"gridcolor": C_GRID}, yaxis={"gridcolor": C_GRID})
    return fig


# --------------------------------------------------------------------------- #
# Komponenty UI
# --------------------------------------------------------------------------- #
_TH = {"textAlign": "left", "padding": "8px 10px", "color": C_MUTED, "fontSize": "12px",
       "borderBottom": f"1px solid {C_GRID}", "textTransform": "uppercase", "letterSpacing": "0.4px"}
_TD = {"textAlign": "left", "padding": "8px 10px", "color": C_TEXT, "fontSize": "14px",
       "borderBottom": f"1px solid {C_GRID}"}


def _panel(children, pad="16px"):
    return html.Div(children, style={"backgroundColor": C_PANEL, "borderRadius": "12px",
                                     "padding": pad, "border": f"1px solid {C_GRID}"})


def _met_color(met) -> str:
    return {True: T.COLOR_MET, False: T.COLOR_UNMET, None: T.COLOR_NA}[met]


def _metric(label, value):
    return html.Div(style={"backgroundColor": C_PANEL2, "borderRadius": "10px", "padding": "10px 14px",
                           "flex": "1 1 150px", "minWidth": "130px"},
                    children=[
                        html.Div(label, style={"color": C_MUTED, "fontSize": "12px"}),
                        html.Div(value, style={"color": C_TEXT, "fontSize": "20px", "fontWeight": 700}),
                    ])


def _banner(text, bg, fg):
    return html.Div(text, style={"backgroundColor": bg, "color": fg, "border": f"1px solid {fg}",
                                 "borderRadius": "10px", "padding": "10px 14px", "fontSize": "13px",
                                 "margin": "12px 0"})


def _indicator_card(ind):
    color = _met_color(ind.met)
    label_met = T.MET_LABEL[ind.met]
    value_str = T.format_value(ind.indicator, ind.value)
    thr_str = T.format_threshold(ind.operator, ind.threshold_value, ind.threshold_value2)
    help_txt = T.INDICATOR_HELP.get(ind.indicator, "")
    children = [
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                 children=[
                     html.Span(ind.label, style={"fontWeight": 600, "color": C_TEXT}),
                     html.Span(label_met, style={"backgroundColor": f"{color}22", "color": color,
                               "borderRadius": "6px", "padding": "1px 8px", "fontSize": "12px",
                               "fontWeight": 600}),
                 ]),
        html.Div(value_str, style={"color": color, "fontSize": "26px", "fontWeight": 700, "margin": "6px 0 2px"}),
        html.Div(f"prog dna: {thr_str}", style={"color": C_MUTED, "fontSize": "12px"}),
    ]
    if help_txt:
        children.append(html.Div(help_txt, style={"color": C_MUTED, "fontSize": "11px", "marginTop": "6px"}))
    return html.Div(style={"backgroundColor": C_PANEL, "borderRadius": "12px", "padding": "14px 16px",
                           "border": f"1px solid {C_GRID}", "borderTop": f"3px solid {color}",
                           "flex": "1 1 220px", "minWidth": "200px"}, children=children)


def _composite_block(result):
    gauge = _panel(dcc.Graph(figure=_gauge_fig(result.count_met, result.count_active),
                             config={"displayModeBar": False}))
    vc = [
        html.Div("Werdykt", style={"color": C_MUTED, "fontSize": "13px"}),
        html.Div(result.verdict, style={"color": C_TEXT, "fontSize": "16px", "lineHeight": "1.5", "margin": "6px 0"}),
    ]
    if result.weighted_ratio is not None:
        vc.append(html.Div(
            f"Wynik wazony: {result.weighted_met:.2f} / {result.weighted_total:.2f} "
            f"= {result.weighted_ratio:.0%} (niuans obok licznika).",
            style={"color": C_MUTED, "fontSize": "12px"}))
    missing = result.count_active - result.count_evaluable
    if missing > 0:
        vc.append(html.Div(f"⚠️ {missing} wskaznik(i) bez danych — nie wliczaja sie do licznika.",
                           style={"color": C_MUTED, "fontSize": "12px", "marginTop": "4px"}))
    return html.Div(style={"display": "flex", "flexWrap": "wrap", "gap": "16px"}, children=[
        html.Div(gauge, style={"flex": "1 1 300px", "minWidth": "280px"}),
        html.Div(_panel(vc, pad="20px"), style={"flex": "2 1 360px", "minWidth": "320px"}),
    ])


def _charts_block(history_df):
    if history_df is None or getattr(history_df, "empty", True):
        return _panel(html.Div("Brak historii do wykresow (tryb demo lub pusta hurtownia).",
                               style={"color": C_MUTED, "fontSize": "13px"}))
    specs = [
        ([("price_usd", "Cena BTC", C_ACCENT), ("ma_200w", "200W MA", "#6fb1ff")], "Cena vs 200W MA"),
        ([("mvrv_z_score", "MVRV Z", "#f5c451"), ("nupl", "NUPL", "#9b8cff")], "MVRV Z / NUPL"),
        ([("fear_greed", "Fear & Greed", "#5fd3a3")], "Fear & Greed"),
        ([("whale_ratio", "Whale Ratio (ref.)", "#ff8c6b")], "Whale Ratio (referencyjnie)"),
    ]
    panels = []
    for series, title in specs:
        fig = _line_fig(history_df, series, title)
        if fig is not None:
            panels.append(_panel(dcc.Graph(figure=fig, config={"displayModeBar": False})))
    if not panels:
        note = ("Tryb demo: jeden punkt odczytu, wartosci wskaznikow puste — "
                "wykresy ozyja na historii z BigQuery (tryb live).")
        return _panel(html.Div(note, style={"color": C_MUTED, "fontSize": "13px"}))
    return html.Div(panels, style={"display": "grid",
                                    "gridTemplateColumns": "repeat(auto-fit, minmax(320px, 1fr))", "gap": "12px"})


def _dca_block(state):
    metrics = html.Div(style={"display": "flex", "flexWrap": "wrap", "gap": "10px"}, children=[
        _metric("Cena biezaca", T.usd(state.current_price)),
        _metric("Sygnaly dna", "—" if state.count_met is None else str(state.count_met)),
        _metric("Zrealizowane", str(state.executed_count)),
        _metric("Oczekujace", str(state.pending_count)),
    ])
    children = [metrics]
    if state.conditions_met_now:
        ids = ", ".join(f"#{t.tranche_id}" for t in state.conditions_met_now)
        children.append(_banner(f"Warunki Twojego planu spelnione dla transz: {ids}.",
                                "#16331f", T.COLOR_MET))
    elif state.next_trigger is not None:
        nt = state.next_trigger
        children.append(_banner(f"Najblizszy prog w dol: transza #{nt.tranche_id} przy {T.usd(nt.trigger_price_usd)}.",
                                "#10243a", "#6fb1ff"))
    header = html.Tr([html.Th(h, style=_TH) for h in
                      ["#", "Prog", "Kwota", "% planu", "Min. sygn.", "Status", "Stan"]])
    rows = [header]
    for t in state.tranches:
        rows.append(html.Tr([
            html.Td(f"#{t.tranche_id}", style=_TD),
            html.Td(T.usd(t.trigger_price_usd), style=_TD),
            html.Td(T.usd(t.allocation_usd), style=_TD),
            html.Td("—" if t.allocation_pct is None else f"{t.allocation_pct:g}%", style=_TD),
            html.Td("—" if t.min_signals_required is None else str(t.min_signals_required), style=_TD),
            html.Td(dca.STATUS_PL.get(t.status, t.status), style=_TD),
            html.Td(t.state_label, style=_TD),
        ]))
    children.append(html.Table(rows, style={"width": "100%", "borderCollapse": "collapse", "marginTop": "10px"}))
    if state.total_alloc_usd is not None:
        budget = (f"Budzet w planie: {T.usd(state.total_alloc_usd)} "
                  f"(zrealizowane: {T.usd(state.executed_alloc_usd)}, "
                  f"oczekujace: {T.usd(state.pending_alloc_usd)}).")
    else:
        budget = "Uzupelnij allocation_usd / allocation_pct w arkuszu, by zobaczyc budzet."
    children.append(html.Div(budget, style={"color": C_MUTED, "fontSize": "12px", "marginTop": "10px"}))
    return _panel(children)


def _section_title(text):
    return html.H2(text, style={"color": C_TEXT, "fontSize": "18px", "fontWeight": 600, "margin": "26px 0 12px"})


def _warnings_block(warns):
    if not warns:
        return None
    items = [html.Li(str(w), style={"color": C_MUTED, "fontSize": "13px", "marginBottom": "4px"}) for w in warns]
    return html.Details([
        html.Summary(f"Uwagi ({len(warns)})", style={"color": C_MUTED, "cursor": "pointer", "fontSize": "13px"}),
        html.Ul(items, style={"marginTop": "8px"}),
    ], style={"marginTop": "20px"})


# --------------------------------------------------------------------------- #
# Budowa zawartosci ze stanu (uzywana w callbacku)
# --------------------------------------------------------------------------- #
def build_content(data: dict, price_value) -> list:
    result = composite.evaluate(data["config"], data["reading"])

    cp = None
    if price_value not in (None, ""):
        try:
            cp = float(price_value)
        except (TypeError, ValueError):
            cp = None
    current_price = cp if (cp is not None and cp > 0) else None

    dca_state = dca.compute_dca_state(data["dca_df"], current_price=current_price,
                                      count_met=result.count_met)

    mode = "demo" if config.load_settings().is_demo else "live"
    auto_price = _reading_price(data["reading"])
    price_hint = (f" Auto-fetch ceny: {T.usd(auto_price)} — wpisz wyzej, by ocenic progi DCA."
                  if auto_price is not None else "")

    header = html.Div(
        style={"display": "flex", "flexWrap": "wrap", "alignItems": "baseline",
               "gap": "14px", "justifyContent": "space-between"},
        children=[
            html.Div([
                html.Span("₿ ", style={"color": C_ACCENT, "fontSize": "20px"}),
                html.Span(T.APP_TITLE, style={"color": C_TEXT, "fontSize": "22px", "fontWeight": 800}),
                html.Div(T.APP_TAGLINE, style={"color": C_MUTED, "fontSize": "13px"}),
            ]),
            html.Div([
                html.Span(T.MODE_LABEL.get(mode, mode), style={
                    "backgroundColor": f"{C_ACCENT}22", "color": C_ACCENT, "borderRadius": "8px",
                    "padding": "3px 10px", "fontSize": "12px", "fontWeight": 700}),
                html.Div("🕓 " + data["freshness_msg"] + price_hint,
                         style={"color": C_MUTED, "fontSize": "12px", "marginTop": "6px"}),
            ], style={"textAlign": "right", "maxWidth": "520px"}),
        ],
    )

    cards = html.Div(style={"display": "flex", "flexWrap": "wrap", "gap": "12px"},
                     children=[_indicator_card(i) for i in result.indicators if i.active])
    inactive = [i.label for i in result.indicators if not i.active]
    if inactive:
        cards = html.Div([cards, html.Div("Nieaktywne progi (poza composite): " + ", ".join(inactive),
                                           style={"color": C_MUTED, "fontSize": "12px", "marginTop": "8px"})])

    all_warns = list(result.warnings) + list(data["warnings"]) + list(dca_state.warnings)

    out = [
        header,
        html.Div(style={"marginTop": "18px"}, children=_composite_block(result)),
        _section_title(T.SECTION_SIGNALS), cards,
        _section_title(T.SECTION_CHARTS), _charts_block(data["history_df"]),
        _section_title(T.SECTION_DCA), _dca_block(dca_state),
    ]
    wb = _warnings_block(all_warns)
    if wb is not None:
        out.append(wb)
    return out


# --------------------------------------------------------------------------- #
# Aplikacja Dash
# --------------------------------------------------------------------------- #
app = Dash(__name__, title="BTC Bottom Tracker — Dash")
server = app.server

app.index_string = """<!DOCTYPE html>
<html><head>{%metas%}<title>{%title%}</title>{%favicon%}{%css%}
<style>
  body { margin:0; background:""" + C_BG + """;
         font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
  ::-webkit-scrollbar { width:10px; height:10px; }
  ::-webkit-scrollbar-thumb { background:""" + C_GRID + """; border-radius:6px; }
</style></head>
<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"""


def serve_layout():
    return html.Div(
        style={"maxWidth": "1120px", "margin": "0 auto", "padding": "24px 18px 48px",
               "color": C_TEXT, "minHeight": "100vh"},
        children=[
            html.Div(f"⚠️ {T.DISCLAIMER}", style={
                "backgroundColor": "#2A2410", "color": "#F2C879", "border": f"1px solid {C_ACCENT}",
                "borderRadius": "10px", "padding": "10px 14px", "fontSize": "13px", "marginBottom": "14px"}),
            html.Div(style={"display": "flex", "flexWrap": "wrap", "gap": "12px",
                            "alignItems": "center", "marginBottom": "14px"}, children=[
                html.Button("⟳ Odswiez dane", id="refresh-btn", n_clicks=0, style={
                    "backgroundColor": C_ACCENT, "color": "#1A1206", "border": "none",
                    "borderRadius": "10px", "padding": "10px 16px", "fontWeight": 700,
                    "fontSize": "14px", "cursor": "pointer"}),
                html.Div([
                    html.Span("Cena BTC (USD) do oceny DCA: ", style={"color": C_MUTED, "fontSize": "13px"}),
                    dcc.Input(id="price-input", type="number", placeholder="0 = nieznana", min=0, step=500,
                              style={"backgroundColor": C_PANEL2, "color": C_TEXT, "border": f"1px solid {C_GRID}",
                                     "borderRadius": "8px", "padding": "8px 10px", "width": "150px"}),
                ]),
            ]),
            dcc.Loading(html.Div(id="content"), color=C_ACCENT, type="default"),
            html.Div(T.DISCLAIMER, style={
                "color": C_MUTED, "fontSize": "12px", "textAlign": "center",
                "marginTop": "34px", "paddingTop": "16px", "borderTop": f"1px solid {C_GRID}"}),
        ],
    )


app.layout = serve_layout


@app.callback(
    Output("content", "children"),
    Input("refresh-btn", "n_clicks"),
    Input("price-input", "value"),
)
def _refresh(n_clicks, price_value):
    data = _data_cached(n_clicks)         # reload tylko gdy zmieni sie n_clicks
    return build_content(data, price_value)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, host="127.0.0.1", port=8050)
