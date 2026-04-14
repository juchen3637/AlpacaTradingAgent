"""
webui/components/status_panel.py - Status panel for the web UI.
"""

import dash_bootstrap_components as dbc
from dash import html


def create_status_panel():
    """Create the status panel with glass-card styling."""
    return dbc.Card(
        dbc.CardBody([
            html.Div(
                [
                    html.Span("monitoring", className="material-symbols-outlined",
                               style={"color": "#3B82F6", "fontSize": "18px"}),
                    html.Span("ANALYSIS STATUS",
                               style={"fontFamily": "'Space Grotesk', sans-serif",
                                      "fontWeight": "700", "fontSize": "13px",
                                      "letterSpacing": "1px", "marginLeft": "8px"}),
                ],
                style={"display": "flex", "alignItems": "center", "marginBottom": "16px"},
            ),
            html.Div(id="status-table"),
            dbc.Row([
                dbc.Col([
                    html.Div(
                        [
                            html.Span("build", className="material-symbols-outlined",
                                       style={"fontSize": "16px", "marginRight": "6px", "color": "#94A3B8"}),
                            html.Span(id="tool-calls-text", children="Tool Calls: 0",
                                       style={"fontSize": "13px"}),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                ], width=4),
                dbc.Col([
                    html.Div(
                        [
                            html.Span("psychology", className="material-symbols-outlined",
                                       style={"fontSize": "16px", "marginRight": "6px", "color": "#94A3B8"}),
                            html.Span(id="llm-calls-text", children="LLM Calls: 0",
                                       style={"fontSize": "13px"}),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                ], width=4),
                dbc.Col([
                    html.Div(
                        [
                            html.Span("assessment", className="material-symbols-outlined",
                                       style={"fontSize": "16px", "marginRight": "6px", "color": "#94A3B8"}),
                            html.Span(id="reports-text", children="Reports: 0",
                                       style={"fontSize": "13px"}),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                ], width=4),
            ], className="mt-3"),
            html.Div(id="refresh-status",
                     children="Updates paused until analysis starts",
                     className="mt-2",
                     style={"color": "#94A3B8", "fontSize": "12px"})
        ]),
        className="mb-4 glass-card"
    )
