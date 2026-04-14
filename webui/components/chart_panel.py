"""
webui/components/chart_panel.py - Chart panel with symbol-based pagination
"""

import dash_bootstrap_components as dbc
from dash import dcc, html
from webui.utils.charts import create_welcome_chart


def create_symbol_pagination(pagination_id, max_symbols=1):
    """Create a custom pagination component using symbol names instead of page numbers"""
    return html.Div(id=f"{pagination_id}-container",
                   children=[
                       html.Div("No symbols available",
                               className="text-muted text-center",
                               style={"padding": "10px"})
                   ],
                   className="symbol-pagination-container")


def create_chart_panel():
    """Create the chart panel — hero-style full-width chart."""
    return dbc.Card(
        dbc.CardBody([
            # Header row with symbol pagination and period selector
            dbc.Row([
                dbc.Col([
                    html.Div(
                        [
                            html.Span("show_chart", className="material-symbols-outlined",
                                       style={"color": "#3B82F6", "fontSize": "18px"}),
                            html.Span("CHART & TECHNICAL ANALYSIS",
                                       style={"fontFamily": "'Space Grotesk', sans-serif",
                                              "fontWeight": "700", "fontSize": "13px",
                                              "letterSpacing": "1px", "marginLeft": "8px"}),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                ], width="auto"),
                dbc.Col([
                    create_symbol_pagination("chart-pagination")
                ], className="d-flex align-items-center justify-content-center"),
                dbc.Col([
                    dbc.ButtonGroup([
                        dbc.Button("1D", id="period-1d", color="secondary", outline=True, size="sm"),
                        dbc.Button("1W", id="period-1w", color="secondary", outline=True, size="sm"),
                        dbc.Button("1M", id="period-1mo", color="secondary", outline=True, size="sm"),
                        dbc.Button("1Y", id="period-1y", color="secondary", outline=True, size="sm"),
                    ]),
                    dbc.Button(
                        html.Span("refresh", className="material-symbols-outlined",
                                  style={"fontSize": "18px"}),
                        id="manual-chart-refresh", color="outline-secondary", size="sm",
                        className="ms-2",
                    ),
                ], width="auto", className="d-flex align-items-center"),
            ], className="mb-3", align="center"),

            html.Div(id="current-symbol-display", className="text-center mb-1",
                     style={"fontFamily": "'Space Grotesk', sans-serif", "fontSize": "28px",
                            "fontWeight": "700"}),
            html.Div(id="chart-last-updated",
                     className="text-center small mb-2",
                     style={"color": "#94A3B8"}),

            # Chart
            html.Div(
                dcc.Graph(
                    id="chart-container",
                    figure=create_welcome_chart(),
                    config={'displayModeBar': True, 'responsive': True},
                    style={"height": "450px", "width": "100%"}
                ),
                style={"height": "450px", "width": "100%", "overflow": "hidden"}
            ),

            # Hidden pagination for callback compatibility
            html.Div([
                dbc.Pagination(
                    id="chart-pagination",
                    max_value=1,
                    fully_expanded=True,
                    first_last=True,
                    previous_next=True,
                    className="d-none"
                )
            ], style={"display": "none"})
        ]),
        className="mb-4 glass-card"
    )
