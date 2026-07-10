"""webui/components/ghetto_sd_page.py - "Ghetto Standard Deviation" options analyzer UI.

Enter a ticker + earnings date, load the options chain (or type quotes manually),
and get the priced-in move, 2SD target strikes, a color-coded screener, a 1-10
suitability score, and warning flags.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

_LABEL = {"fontSize": "12px", "color": "#94A3B8", "marginBottom": "4px"}
_ACCENT = "#38BDF8"


def _section_header(icon: str, title: str, subtitle: str = ""):
    return html.Div(
        [
            html.Div(
                [
                    html.Span(icon, className="material-symbols-outlined",
                              style={"color": _ACCENT, "fontSize": "20px"}),
                    html.Span(title, style={
                        "fontFamily": "'Space Grotesk', sans-serif", "fontWeight": "700",
                        "fontSize": "14px", "letterSpacing": "1px", "marginLeft": "8px",
                    }),
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            html.Div(subtitle, style={"fontSize": "12px", "color": "#94A3B8", "marginTop": "4px"})
            if subtitle else None,
        ],
        style={"marginBottom": "16px"},
    )


def _num_input(input_id: str, placeholder: str):
    return dcc.Input(
        id=input_id, type="number", placeholder=placeholder, debounce=True,
        min=0, max=1_000_000, step=0.01,
        className="form-control",
        style={"backgroundColor": "#0F172A", "border": "1px solid #1E293B", "color": "#F1F5F9"},
    )


def _controls_card():
    return dbc.Card(
        dbc.CardBody([
            _section_header(
                "calculate", "GHETTO STANDARD DEVIATION",
                "1 SD = ATM call ask + ATM put ask · 2 SD target strikes = price ± (2 × 1 SD).",
            ),
            dbc.Row([
                dbc.Col([
                    html.Label("Ticker", style=_LABEL),
                    dcc.Input(id="gsd-ticker", type="text", placeholder="DRI", debounce=True,
                              className="form-control",
                              style={"backgroundColor": "#0F172A", "border": "1px solid #1E293B",
                                     "color": "#F1F5F9", "textTransform": "uppercase"}),
                ], xs=6, md=2),
                dbc.Col([
                    html.Label("Earnings date", style=_LABEL),
                    dcc.DatePickerSingle(id="gsd-earnings-date", display_format="YYYY-MM-DD",
                                         className="dark-datepicker"),
                ], xs=6, md=3),
                dbc.Col([
                    html.Div(style={"height": "24px"}),
                    dbc.Button(
                        [html.Span("download", className="material-symbols-outlined me-1",
                                   style={"fontSize": "18px", "verticalAlign": "middle"}),
                         "Load Options Chain"],
                        id="gsd-load-btn", color="primary",
                        style={"backgroundColor": "#0EA5E9", "borderColor": "#0EA5E9", "fontWeight": "600"},
                    ),
                ], xs=12, md=4),
            ]),
            html.Div(id="gsd-load-status",
                     style={"marginTop": "10px", "fontSize": "12px", "color": "#94A3B8"}),
            html.Hr(style={"borderColor": "#1E293B"}),
            dbc.Row([
                dbc.Col([
                    html.Label("Expiration", style=_LABEL),
                    dcc.Dropdown(id="gsd-expiration", options=[], placeholder="Load chain first",
                                 clearable=False, className="dark-dropdown"),
                ], xs=12, md=4),
                dbc.Col([
                    html.Label("Current price (override)", style=_LABEL),
                    _num_input("gsd-current-price", "auto"),
                ], xs=6, md=2),
                dbc.Col([
                    html.Label("ATM call ask (override)", style=_LABEL),
                    _num_input("gsd-call-ask", "auto"),
                ], xs=6, md=2),
                dbc.Col([
                    html.Label("ATM put ask (override)", style=_LABEL),
                    _num_input("gsd-put-ask", "auto"),
                ], xs=6, md=2),
                dbc.Col([
                    html.Div(style={"height": "24px"}),
                    dbc.Button(
                        [html.Span("analytics", className="material-symbols-outlined me-1",
                                   style={"fontSize": "18px", "verticalAlign": "middle"}),
                         "Analyze"],
                        id="gsd-analyze-btn", color="primary", className="w-100",
                        style={"backgroundColor": "#7C3AED", "borderColor": "#7C3AED", "fontWeight": "600"},
                    ),
                ], xs=6, md=2),
            ]),
            html.Div(
                "Tip: leave overrides blank to use live chain data. Fill them to compute manually "
                "when options data is unavailable.",
                style={"fontSize": "11px", "color": "#475569", "marginTop": "8px"},
            ),
        ]),
        style={"backgroundColor": "rgba(15,23,42,0.8)", "border": "1px solid #1E293B",
               "marginBottom": "16px"},
    )


def _scanner_card():
    return dbc.Card(
        dbc.CardBody([
            _section_header(
                "radar", "SCAN MOST-ACTIVES",
                "Sweep the most-active stocks and surface tickers whose nearest weekly options "
                "clear every gate: suitability, a Valid Play, 2SD cost, and liquidity.",
            ),
            dbc.Row([
                dbc.Col([
                    html.Label("Min suitability", style=_LABEL),
                    dcc.Input(id="gsd-scan-min-suit", type="number", placeholder="6",
                              min=1, max=10, step=1, debounce=True, className="form-control",
                              style={"backgroundColor": "#0F172A", "border": "1px solid #1E293B",
                                     "color": "#F1F5F9"}),
                ], xs=6, md=2),
                dbc.Col([
                    html.Label("Min price ($)", style=_LABEL),
                    dcc.Input(id="gsd-scan-min-price", type="number", placeholder="20",
                              min=0, max=10000, step=1, debounce=True, className="form-control",
                              style={"backgroundColor": "#0F172A", "border": "1px solid #1E293B",
                                     "color": "#F1F5F9"}),
                ], xs=6, md=2),
                dbc.Col([
                    html.Label("Universe size", style=_LABEL),
                    dcc.Input(id="gsd-scan-size", type="number", placeholder="25",
                              min=1, max=100, step=1, debounce=True, className="form-control",
                              style={"backgroundColor": "#0F172A", "border": "1px solid #1E293B",
                                     "color": "#F1F5F9"}),
                ], xs=6, md=2),
                dbc.Col([
                    html.Div(style={"height": "24px"}),
                    dbc.Button(
                        [html.Span("radar", className="material-symbols-outlined me-1",
                                   style={"fontSize": "18px", "verticalAlign": "middle"}),
                         "Scan Most-Actives"],
                        id="gsd-scan-btn", color="primary", className="w-100",
                        style={"backgroundColor": "#059669", "borderColor": "#059669", "fontWeight": "600"},
                    ),
                ], xs=12, md=3),
            ]),
            html.Div(id="gsd-scan-status",
                     style={"marginTop": "10px", "fontSize": "12px", "color": "#94A3B8"}),
            dcc.Loading(
                html.Div(id="gsd-scan-results", style={"marginTop": "8px"}),
                type="default", color=_ACCENT,
            ),
        ]),
        style={"backgroundColor": "rgba(15,23,42,0.8)", "border": "1px solid #1E293B",
               "marginBottom": "16px"},
    )


def _exec_modal():
    """Confirm dialog for placing the two-leg strangle (one limit order per leg)."""
    def _limit_input(input_id):
        return dcc.Input(id=input_id, type="number", min=0.01, max=100000, step=0.01,
                         debounce=True, className="form-control form-control-sm",
                         style={"backgroundColor": "#0F172A", "border": "1px solid #1E293B",
                                "color": "#F1F5F9"})

    def _leg_row(label, symbol_id, limit_id, color):
        return html.Div([
            html.Div([
                html.Span(label, style={"fontWeight": "700", "color": color, "marginRight": "8px"}),
                html.Span(id=symbol_id, style={"fontFamily": "monospace", "fontSize": "12px",
                                               "color": "#CBD5E1"}),
            ], style={"marginBottom": "4px"}),
            html.Label("Limit (per share · ×100 = cost/contract)", style=_LABEL),
            _limit_input(limit_id),
        ], style={"marginBottom": "12px"})

    return dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle([
            html.Span("bolt", className="material-symbols-outlined me-1",
                      style={"fontSize": "20px", "verticalAlign": "middle", "color": _ACCENT}),
            "Place Strangle — ", html.Span(id="gsd-exec-title", style={"color": _ACCENT}),
        ])),
        dbc.ModalBody([
            html.Div(id="gsd-exec-env-badge", style={"marginBottom": "12px"}),
            dbc.Row([
                dbc.Col([
                    html.Label("Contracts (qty per leg)", style=_LABEL),
                    dcc.Input(id="gsd-exec-qty", type="number", min=1, max=1000, step=1, value=1,
                              debounce=True, className="form-control form-control-sm",
                              style={"backgroundColor": "#0F172A", "border": "1px solid #1E293B",
                                     "color": "#F1F5F9"}),
                ], xs=12, md=4),
            ], style={"marginBottom": "12px"}),
            _leg_row("CALL", "gsd-exec-call-symbol", "gsd-exec-call-limit", "#22C55E"),
            _leg_row("PUT", "gsd-exec-put-symbol", "gsd-exec-put-limit", "#EF4444"),
            html.Div(id="gsd-exec-estimate", style={"fontSize": "12px", "color": "#94A3B8"}),
            html.Div(id="gsd-exec-result", style={"marginTop": "10px"}),
        ]),
        dbc.ModalFooter([
            dbc.Button("Cancel", id="gsd-exec-cancel", color="secondary", outline=True),
            dbc.Button([html.Span("send", className="material-symbols-outlined me-1",
                                  style={"fontSize": "16px", "verticalAlign": "middle"}),
                        "Confirm & Submit"],
                       id="gsd-exec-confirm", color="success", style={"fontWeight": "600"}),
        ]),
    ], id="gsd-exec-modal", is_open=False, centered=True, backdrop="static")


def _empty_state():
    return html.Div(
        [
            html.Span("calculate", className="material-symbols-outlined",
                      style={"fontSize": "48px", "color": "#334155", "display": "block",
                             "textAlign": "center", "marginBottom": "12px"}),
            html.Div("No analysis yet.",
                     style={"textAlign": "center", "color": "#64748B", "fontSize": "14px"}),
            html.Div("Load a chain (or enter quotes manually), pick the week-of-earnings "
                     "expiration, and click Analyze.",
                     style={"textAlign": "center", "color": "#475569", "fontSize": "12px",
                            "marginTop": "6px"}),
        ],
        style={"padding": "48px 24px"},
    )


def create_ghetto_sd_page() -> html.Div:
    return html.Div([
        dcc.Store(id="gsd-chain-store"),
        dcc.Store(id="gsd-scan-legs-store"),
        dcc.Store(id="gsd-analyze-legs-store"),
        dcc.Store(id="gsd-exec-store"),
        _exec_modal(),
        html.Div([_scanner_card()], style={"padding": "16px 16px 0"}),
        html.Div([_controls_card()], style={"padding": "0 16px 0"}),
        html.Div(id="gsd-warnings", style={"padding": "0 16px"}),
        html.Div(id="gsd-results-panel", children=[_empty_state()],
                 style={"padding": "0 16px 16px"}),
    ])
