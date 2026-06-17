"""
webui/components/batch_overview_panel.py - Batch overview panel for parallel batch analysis
"""

import dash_bootstrap_components as dbc
from dash import html, dcc


def create_batch_overview_panel():
    """Create the batch overview panel component with interactive ticker navigation"""
    return dbc.Card(
        dbc.CardBody([
            html.Div(
                [
                    html.Span("layers", className="material-symbols-outlined",
                               style={"color": "#3B82F6", "fontSize": "18px"}),
                    html.Span("BATCH OVERVIEW",
                               style={"fontFamily": "'Space Grotesk', sans-serif",
                                      "fontWeight": "700", "fontSize": "13px",
                                      "letterSpacing": "1px", "marginLeft": "8px"}),
                ],
                style={"display": "flex", "alignItems": "center", "marginBottom": "16px"},
            ),

            # Symbol pagination buttons container
            html.Div(
                id="batch-pagination-container",
                children=[],
                className="mb-3"
            ),

            html.Div(id="batch-summary-header", children=[
                html.P("No batch analysis running",
                       style={"color": "#94A3B8", "textAlign": "center"})
            ]),
            html.Div(id="batch-ticker-table", children=[]),
            html.Div([
                html.Small([
                    html.Span("✅ Complete", className="me-3"),
                    html.Span("🔄 In Progress", className="me-3"),
                    html.Span("⏸️ Queued", className="me-3"),
                    html.Span("⏭️ Skipped")
                ], style={"color": "#64748B"})
            ], className="mt-2 text-center"),
            dcc.Store(id="batch-ticker-click-store")
        ]),
        className="mb-4 glass-card"
    )
