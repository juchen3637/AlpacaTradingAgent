"""
webui/components/portfolio_page.py - Portfolio analytics page.

Displays equity curve, P&L by position, sector allocation, and performance metrics.
Data refreshed via slow-refresh-interval callback in portfolio_callbacks.py.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html


def _section_header(icon: str, title: str):
    """Create a consistent section header with Material icon."""
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


def _metric_card(card_id: str, label: str, icon: str):
    """Create a single metric card with a label and dynamic value."""
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


def create_portfolio_page():
    """Create the full portfolio analytics page."""
    return html.Div([
        # Row 1: Performance metric cards
        dbc.Row([
            _metric_card("portfolio-total-value", "Portfolio Value", "account_balance"),
            _metric_card("portfolio-total-pl", "Total P&L", "trending_up"),
            _metric_card("portfolio-win-rate", "Win Rate", "check_circle"),
            _metric_card("portfolio-sharpe", "Sharpe Ratio", "insights"),
        ], className="mb-4"),

        # Row 2: P&L period toggle + equity curve
        dbc.Card(
            dbc.CardBody([
                html.Div([
                    _section_header("show_chart", "EQUITY CURVE"),
                    dbc.ButtonGroup([
                        dbc.Button("1D", id="portfolio-period-1d", color="secondary", outline=True, size="sm"),
                        dbc.Button("1W", id="portfolio-period-1w", color="secondary", outline=True, size="sm"),
                        dbc.Button("1M", id="portfolio-period-1m", color="secondary", outline=True, size="sm"),
                        dbc.Button("3M", id="portfolio-period-3m", color="secondary", outline=True, size="sm"),
                        dbc.Button("1Y", id="portfolio-period-1y", color="secondary", outline=True, size="sm"),
                        dbc.Button("ALL", id="portfolio-period-all", color="secondary", outline=True, size="sm"),
                    ]),
                ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start"}),
                dcc.Graph(
                    id="portfolio-equity-chart",
                    config={"displayModeBar": False, "responsive": True},
                    style={"height": "350px"},
                ),
            ]),
            className="mb-4 glass-card",
        ),

        # Row 3: Sector allocation + P&L by position
        dbc.Row([
            dbc.Col([
                dbc.Card(
                    dbc.CardBody([
                        _section_header("donut_large", "SECTOR ALLOCATION"),
                        dcc.Graph(
                            id="portfolio-sector-chart",
                            config={"displayModeBar": False, "responsive": True},
                            style={"height": "300px"},
                        ),
                    ]),
                    className="glass-card",
                ),
            ], xs=12, lg=5, className="mb-4"),
            dbc.Col([
                dbc.Card(
                    dbc.CardBody([
                        _section_header("format_list_numbered", "P&L BY POSITION"),
                        html.Div(id="portfolio-position-pl-table"),
                    ]),
                    className="glass-card",
                ),
            ], xs=12, lg=7, className="mb-4"),
        ]),

        # Row 4: Additional metrics
        dbc.Row([
            dbc.Col([
                dbc.Card(
                    dbc.CardBody([
                        _section_header("bar_chart", "PERFORMANCE METRICS"),
                        html.Div(id="portfolio-metrics-table"),
                    ]),
                    className="glass-card",
                ),
            ], xs=12, lg=6, className="mb-4"),
            dbc.Col([
                dbc.Card(
                    dbc.CardBody([
                        _section_header("history", "RECENT TRADES"),
                        html.Div(id="portfolio-recent-trades-table"),
                    ]),
                    className="glass-card",
                ),
            ], xs=12, lg=6, className="mb-4"),
        ]),
    ])
