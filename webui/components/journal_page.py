"""
webui/components/journal_page.py - Trade journal UI page.

Surfaces every AI decision with full agent reasoning, linked trades,
and realized outcomes. Supports filtering by ticker / signal / date range
and drill-down into each decision's analyst reports and debate history.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html


def _section_header(icon: str, title: str):
    return html.Div(
        [
            html.Span(icon, className="material-symbols-outlined",
                      style={"color": "#3B82F6", "fontSize": "18px"}),
            html.Span(title,
                      style={"fontFamily": "'Space Grotesk', sans-serif",
                             "fontWeight": "700", "fontSize": "13px",
                             "letterSpacing": "1px", "marginLeft": "8px"}),
        ],
        style={"display": "flex", "alignItems": "center", "marginBottom": "16px"},
    )


def _stat_card(card_id: str, label: str, icon: str):
    return dbc.Col(
        dbc.Card(
            dbc.CardBody([
                html.Div(
                    [
                        html.Span(icon, className="material-symbols-outlined",
                                  style={"fontSize": "20px", "color": "#3B82F6", "marginRight": "8px"}),
                        html.Span(label, style={"fontSize": "11px", "color": "#94A3B8",
                                                "textTransform": "uppercase", "fontWeight": "700",
                                                "letterSpacing": "1px"}),
                    ],
                    style={"display": "flex", "alignItems": "center", "marginBottom": "8px"},
                ),
                html.Div(id=card_id, children="—",
                         style={"fontSize": "24px", "fontWeight": "700",
                                "fontFamily": "'Space Grotesk', sans-serif",
                                "fontVariantNumeric": "tabular-nums"}),
            ], style={"padding": "16px"}),
            className="glass-card",
        ),
        xs=6, lg=3, className="mb-3",
    )


def create_journal_page():
    """Create the full journal page with trade log, filters, and decision drill-down."""
    return html.Div([
        # Row 1: Summary stats
        dbc.Row([
            _stat_card("journal-total-decisions", "Total Decisions", "fact_check"),
            _stat_card("journal-total-trades", "Trades Executed", "swap_vert"),
            _stat_card("journal-win-rate", "Win Rate", "check_circle"),
            _stat_card("journal-avg-pnl", "Avg P&L / Trade", "trending_up"),
        ], className="mb-4"),

        # Row 2: Filters (high z-index so dropdowns render above cards below)
        dbc.Card(
            dbc.CardBody([
                _section_header("filter_alt", "FILTERS"),
                dbc.Row([
                    dbc.Col([
                        html.Label("Ticker", style={"fontSize": "11px",
                                                    "color": "#94A3B8", "fontWeight": "600",
                                                    "textTransform": "uppercase",
                                                    "letterSpacing": "0.5px"}),
                        dcc.Dropdown(
                            id="journal-ticker-filter",
                            options=[],  # populated by callback
                            value=None,
                            clearable=True,
                            placeholder="All tickers",
                        ),
                    ], xs=12, lg=3),
                    dbc.Col([
                        html.Label("Signal", style={"fontSize": "11px",
                                                    "color": "#94A3B8", "fontWeight": "600",
                                                    "textTransform": "uppercase",
                                                    "letterSpacing": "0.5px"}),
                        dcc.Dropdown(
                            id="journal-signal-filter",
                            options=[
                                {"label": "All signals", "value": "ALL"},
                                {"label": "BUY", "value": "BUY"},
                                {"label": "SELL", "value": "SELL"},
                                {"label": "HOLD", "value": "HOLD"},
                                {"label": "LONG", "value": "LONG"},
                                {"label": "NEUTRAL", "value": "NEUTRAL"},
                                {"label": "SHORT", "value": "SHORT"},
                            ],
                            value="ALL",
                            clearable=False,
                        ),
                    ], xs=12, lg=2),
                    dbc.Col([
                        html.Label("Source", style={"fontSize": "11px",
                                                    "color": "#94A3B8", "fontWeight": "600",
                                                    "textTransform": "uppercase",
                                                    "letterSpacing": "0.5px"}),
                        dcc.Dropdown(
                            id="journal-source-filter",
                            options=[
                                {"label": "All sources", "value": "ALL"},
                                {"label": "Scanner (paper trades)", "value": "scanner"},
                                {"label": "Agent (LLM decisions)", "value": "agent"},
                                {"label": "Backfill (Alpaca history)", "value": "backfill"},
                            ],
                            value="ALL",
                            clearable=False,
                        ),
                    ], xs=12, lg=3),
                    dbc.Col([
                        html.Label("Limit", style={"fontSize": "11px",
                                                   "color": "#94A3B8", "fontWeight": "600",
                                                   "textTransform": "uppercase",
                                                   "letterSpacing": "0.5px"}),
                        dcc.Dropdown(
                            id="journal-limit-filter",
                            options=[
                                {"label": "Last 25", "value": 25},
                                {"label": "Last 50", "value": 50},
                                {"label": "Last 100", "value": 100},
                                {"label": "Last 250", "value": 250},
                                {"label": "Last 500", "value": 500},
                            ],
                            value=100,
                            clearable=False,
                        ),
                    ], xs=12, lg=2),
                    dbc.Col([
                        html.Label(" ", style={"fontSize": "11px",
                                               "display": "block"}),
                        html.Div([
                            dbc.Button(
                                [html.Span("refresh", className="material-symbols-outlined me-1",
                                           style={"fontSize": "16px", "verticalAlign": "middle"}),
                                 "Refresh"],
                                id="journal-refresh-btn",
                                color="primary",
                                outline=True,
                                size="sm",
                                style={"flex": "1"},
                            ),
                            dbc.Button(
                                [html.Span("delete_forever", className="material-symbols-outlined",
                                           style={"fontSize": "16px", "verticalAlign": "middle"})],
                                id="journal-clear-btn",
                                color="danger",
                                outline=True,
                                size="sm",
                                title="Clear all journal entries",
                                style={"marginLeft": "6px"},
                            ),
                        ], style={"display": "flex", "width": "100%"}),
                    ], xs=12, lg=2),
                ]),
                # Backfill row (hidden — kept for callback compatibility)
                html.Div([
                    dcc.Dropdown(id="journal-backfill-lookback", value=90),
                    html.Button(id="journal-backfill-btn"),
                    html.Div(id="journal-backfill-status"),
                ], style={"display": "none"}),
            ]),
            className="mb-4 glass-card",
            style={"position": "relative", "zIndex": 10},
        ),

        # Row 3: Analytics charts
        dbc.Row([
            dbc.Col([
                dbc.Card(
                    dbc.CardBody([
                        _section_header("donut_large", "SIGNAL DISTRIBUTION"),
                        dcc.Graph(
                            id="journal-signal-distribution",
                            config={"displayModeBar": False, "responsive": True},
                            style={"height": "280px"},
                        ),
                    ]),
                    className="glass-card",
                ),
            ], xs=12, lg=4, className="mb-4"),
            dbc.Col([
                dbc.Card(
                    dbc.CardBody([
                        _section_header("bar_chart", "PER-TICKER REALIZED P&L"),
                        html.Div("Closed trades only — open positions excluded",
                                 style={"fontSize": "10px", "color": "#64748B",
                                        "marginTop": "-12px", "marginBottom": "8px",
                                        "fontStyle": "italic"}),
                        dcc.Graph(
                            id="journal-per-ticker-pnl",
                            config={"displayModeBar": False, "responsive": True},
                            style={"height": "260px"},
                        ),
                    ]),
                    className="glass-card",
                ),
            ], xs=12, lg=4, className="mb-4"),
            dbc.Col([
                dbc.Card(
                    dbc.CardBody([
                        _section_header("radar", "ANALYST EFFECTIVENESS"),
                        dcc.Graph(
                            id="journal-analyst-radar",
                            config={"displayModeBar": False, "responsive": True},
                            style={"height": "280px"},
                        ),
                    ]),
                    className="glass-card",
                ),
            ], xs=12, lg=4, className="mb-4"),
        ]),

        # Hidden placeholders for removed charts (callbacks still target these IDs)
        dcc.Graph(id="journal-unrealized-pnl", style={"display": "none"}),
        html.Div(id="journal-unrealized-summary", style={"display": "none"}),

        # Row 3b: Streak card + decision activity by hour
        dbc.Row([
            dbc.Col([
                dbc.Card(
                    dbc.CardBody([
                        _section_header("timeline", "WIN/LOSS STREAK"),
                        html.Div(id="journal-streak-summary"),
                        dcc.Graph(
                            id="journal-streak-timeline",
                            config={"displayModeBar": False, "responsive": True},
                            style={"height": "140px"},
                        ),
                    ]),
                    className="glass-card",
                ),
            ], xs=12, lg=6, className="mb-4"),
            dbc.Col([
                dbc.Card(
                    dbc.CardBody([
                        _section_header("schedule", "DECISIONS BY HOUR (UTC)"),
                        dcc.Graph(
                            id="journal-hour-chart",
                            config={"displayModeBar": False, "responsive": True},
                            style={"height": "240px"},
                        ),
                    ]),
                    className="glass-card",
                ),
            ], xs=12, lg=6, className="mb-4"),
        ]),

        # Row 4: Trade log table
        dbc.Card(
            dbc.CardBody([
                _section_header("receipt_long", "DECISION LOG"),
                html.Div(id="journal-log-table"),
            ]),
            className="mb-4 glass-card",
        ),

        # Row 4: Decision detail panel (agent reasoning drill-down)
        dbc.Card(
            dbc.CardBody([
                _section_header("psychology", "AGENT REASONING"),
                html.Div(id="journal-decision-detail",
                         children=html.Div(
                             "Select a row above to see the full agent reasoning for that decision.",
                             style={"color": "#94A3B8", "fontSize": "13px",
                                    "padding": "24px", "textAlign": "center"},
                         )),
            ]),
            className="mb-4 glass-card",
        ),

        # Hidden store for tracking selected decision
        dcc.Store(id="journal-selected-decision", data=None),

        # Clear-journal confirmation modal
        dbc.Modal(
            [
                dbc.ModalHeader(
                    dbc.ModalTitle([
                        html.Span("warning", className="material-symbols-outlined me-2",
                                  style={"color": "#EF4444", "verticalAlign": "middle",
                                         "fontSize": "22px"}),
                        "Clear Journal?",
                    ]),
                    close_button=False,
                ),
                dbc.ModalBody([
                    html.P(
                        "This will permanently delete every recorded decision, trade, "
                        "and outcome from the journal database.",
                        style={"marginBottom": "8px"},
                    ),
                    html.P(
                        "This action cannot be undone.",
                        style={"color": "#EF4444", "fontWeight": "600",
                               "marginBottom": "12px"},
                    ),
                    html.Div(id="journal-clear-preview",
                             style={"fontSize": "12px", "color": "#94A3B8"}),
                ]),
                dbc.ModalFooter([
                    dbc.Button("Cancel", id="journal-clear-cancel-btn",
                               color="secondary", outline=True),
                    dbc.Button(
                        [html.Span("delete_forever", className="material-symbols-outlined me-1",
                                   style={"fontSize": "16px", "verticalAlign": "middle"}),
                         "Yes, clear everything"],
                        id="journal-clear-confirm-btn",
                        color="danger",
                    ),
                ]),
            ],
            id="journal-clear-modal",
            is_open=False,
            backdrop="static",
            centered=True,
        ),

        # Toast for clear-success feedback
        dbc.Toast(
            id="journal-clear-toast",
            header="Journal cleared",
            is_open=False,
            dismissable=True,
            duration=4000,
            icon="success",
            style={"position": "fixed", "top": 80, "right": 20,
                   "minWidth": "min(320px, calc(100vw - 40px))",
                   "maxWidth": "calc(100vw - 40px)", "zIndex": 1100},
        ),
    ])
