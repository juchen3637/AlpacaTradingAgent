"""
webui/components/decision_panel.py - Decision summary panel for the web UI.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html


def create_decision_panel():
    """Create the decision summary panel with glass-card styling."""
    return dbc.Card(
        dbc.CardBody([
            html.Div(
                [
                    html.Span("gavel", className="material-symbols-outlined",
                               style={"color": "#3B82F6", "fontSize": "18px"}),
                    html.Span("DECISION SUMMARY",
                               style={"fontFamily": "'Space Grotesk', sans-serif",
                                      "fontWeight": "700", "fontSize": "13px",
                                      "letterSpacing": "1px", "marginLeft": "8px"}),
                ],
                style={"display": "flex", "alignItems": "center", "marginBottom": "16px"},
            ),
            html.Div(
                dcc.Markdown(
                    id="decision-summary",
                    children="Run analysis to see the final decision summary",
                    className="dash-markdown"
                ),
                style={
                    "height": "400px",
                    "overflowY": "auto",
                    "overflowX": "hidden",
                    "border": "1px solid rgba(51, 65, 85, 0.5)",
                    "borderRadius": "8px",
                    "padding": "16px",
                    "backgroundColor": "rgba(11, 17, 32, 0.6)",
                }
            )
        ]),
        className="mb-4 glass-card"
    )
