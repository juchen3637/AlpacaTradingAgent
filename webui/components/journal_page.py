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
                            style={"color": "#0F172A"},
                        ),
                    ], xs=12, lg=4),
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
                            style={"color": "#0F172A"},
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
                            style={"color": "#0F172A"},
                        ),
                    ], xs=12, lg=3),
                    dbc.Col([
                        html.Label(" ", style={"fontSize": "11px",
                                               "display": "block"}),
                        dbc.Button(
                            [html.Span("refresh", className="material-symbols-outlined me-1",
                                       style={"fontSize": "16px", "verticalAlign": "middle"}),
                             "Refresh"],
                            id="journal-refresh-btn",
                            color="primary",
                            outline=True,
                            size="sm",
                            className="w-100",
                        ),
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
    ])
