"""
Chart-related callbacks for TradingAgents WebUI
Enhanced with symbol-based pagination
"""

from dash import Input, Output, State, ctx, html, ALL, dash
import dash_bootstrap_components as dbc
import pandas as pd
from datetime import datetime
import time

from webui.utils.state import app_state
from webui.utils.charts_lwc import build_lwc_payload, empty_lwc_payload
from webui.config.constants import SYMBOL_CLICK_DEBOUNCE_SECONDS


def create_symbol_button(symbol, index, is_active=False):
    """Create a symbol button for pagination"""
    return dbc.Button(
        symbol,
        id={"type": "symbol-btn", "index": index, "component": "charts"},
        color="primary" if is_active else "outline-primary",
        size="sm",
        className=f"symbol-btn {'active' if is_active else ''}",
    )


def register_chart_callbacks(app):
    """Register all chart-related callbacks including symbol pagination"""
    
    @app.callback(
        Output("chart-pagination-container", "children"),
        [Input("app-store", "data"),
         Input("refresh-interval", "n_intervals")]
    )
    def update_chart_symbol_pagination(store_data, n_intervals):
        """Update the symbol pagination buttons for charts"""

        # CHECK: Has user clicked recently? If so, don't override their choice
        time_since_last_click = time.time() - app_state.last_symbol_click_time
        if time_since_last_click < SYMBOL_CLICK_DEBOUNCE_SECONDS:
            # User clicked recently - don't update to prevent override
            return dash.no_update

        if not app_state.symbol_states:
            return html.Div("No symbols available",
                          className="text-muted text-center",
                          style={"padding": "10px"})
        
        symbols = list(app_state.symbol_states.keys())
        current_symbol = app_state.current_symbol
        
        # Find active symbol index
        active_index = 0
        if current_symbol and current_symbol in symbols:
            active_index = symbols.index(current_symbol)
        
        buttons = []
        for i, symbol in enumerate(symbols):
            is_active = i == active_index
            buttons.append(create_symbol_button(symbol, i, is_active))
        
        if len(symbols) > 1:
            # Add navigation info
            nav_info = html.Div([
                html.I(className="fas fa-chart-line me-2"),
                f"Charts for {len(symbols)} symbols"
            ], className="text-muted small text-center mt-2")
            
            return html.Div([
                dbc.ButtonGroup(buttons, className="d-flex flex-wrap justify-content-center"),
                nav_info
            ], className="symbol-pagination-wrapper")
        else:
            return dbc.ButtonGroup(buttons, className="d-flex justify-content-center")

    @app.callback(
        [Output("chart-pagination", "active_page", allow_duplicate=True),
         Output("chart-pagination-container", "children", allow_duplicate=True)],
        [Input({"type": "symbol-btn", "index": ALL, "component": "charts"}, "n_clicks")],
        prevent_initial_call=True
    )
    def handle_chart_symbol_click(symbol_clicks):
        """Handle symbol button clicks for charts with immediate visual feedback"""
        if not any(symbol_clicks) or not ctx.triggered:
            return dash.no_update, dash.no_update

        # Find which button was clicked
        button_id = ctx.triggered[0]["prop_id"]
        if "symbol-btn" in button_id:
            # Extract index from the button ID
            import json
            button_data = json.loads(button_id.split('.')[0])
            clicked_index = button_data["index"]

            # Update chart-specific symbol
            symbols = list(app_state.symbol_states.keys())
            if 0 <= clicked_index < len(symbols):
                # CRITICAL: Record timestamp BEFORE updating symbol
                app_state.last_symbol_click_time = time.time()

                # Track chart-specific active symbol
                app_state.active_chart_symbol = symbols[clicked_index]

                # Also update current_symbol for backward compatibility
                app_state.current_symbol = symbols[clicked_index]

                page_number = clicked_index + 1

                # ⚡ IMMEDIATE BUTTON UPDATE - No waiting for refresh!
                buttons = []
                for i, symbol in enumerate(symbols):
                    is_active = i == clicked_index  # Active state based on click
                    buttons.append(create_symbol_button(symbol, i, is_active))

                if len(symbols) > 1:
                    # Add navigation info
                    nav_info = html.Div([
                        html.I(className="fas fa-chart-line me-2"),
                        f"Charts for {len(symbols)} symbols"
                    ], className="text-muted small text-center mt-2")

                    button_container = html.Div([
                        dbc.ButtonGroup(buttons, className="d-flex flex-wrap justify-content-center"),
                        nav_info
                    ], className="symbol-pagination-wrapper")
                else:
                    button_container = dbc.ButtonGroup(buttons, className="d-flex justify-content-center")

                return page_number, button_container

        return dash.no_update, dash.no_update

    @app.callback(
        [Output("chart-container-payload", "data"),
         Output("current-symbol-display", "children"),
         Output("chart-store", "data")],
        [Input("period-1d", "n_clicks"),
         Input("period-1w", "n_clicks"),
         Input("period-1mo", "n_clicks"),
         Input("period-1y", "n_clicks"),
         Input("chart-pagination", "active_page"),
         Input("manual-chart-refresh", "n_clicks")],
        [State("chart-store", "data")]
    )
    def update_chart(n_1d, n_1w, n_1mo, n_1y, active_page, manual_refresh, chart_store_data):
        """Build LWC payload and push to chart-container-payload store."""
        empty = empty_lwc_payload()

        if not app_state.symbol_states or not active_page:
            return empty, "", chart_store_data

        symbols_list = list(app_state.symbol_states.keys())
        if active_page > len(symbols_list):
            return empty, "Page index out of range", chart_store_data

        symbol = symbols_list[active_page - 1]

        triggered_prop = ctx.triggered[0]["prop_id"] if ctx.triggered else None

        period_map = {
            "period-1d.n_clicks": "1d",
            "period-1w.n_clicks": "1w",
            "period-1mo.n_clicks": "1mo",
            "period-1y.n_clicks": "1y"
        }

        if triggered_prop in period_map:
            selected_period = period_map[triggered_prop]
        elif chart_store_data and "selected_period" in chart_store_data:
            selected_period = chart_store_data["selected_period"]
        else:
            selected_period = "1y"

        try:
            payload = build_lwc_payload(symbol, selected_period)
            symbol_display = f"📈 {symbol.upper()}"

            updated_store_data = chart_store_data or {}
            updated_store_data["selected_period"] = selected_period
            updated_store_data["last_symbol"] = symbol
            updated_store_data["last_updated"] = datetime.now().isoformat()

            return payload, symbol_display, updated_store_data

        except Exception:
            return empty, f"❌ Error loading {symbol.upper()}", chart_store_data

    app.clientside_callback(
        """
        function(payload) {
            if (payload && window.lwcRender) {
                window.lwcRender('chart-container', payload);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("chart-container", "data-lwc-rendered"),
        Input("chart-container-payload", "data"),
    )

    @app.callback(
        Output("chart-last-updated", "children"),
        [Input("chart-store", "data")]
    )
    def update_chart_timestamp(chart_store_data):
        """Update the chart last updated timestamp"""
        if not chart_store_data or "last_updated" not in chart_store_data:
            return ""
        
        try:
            last_updated = datetime.fromisoformat(chart_store_data["last_updated"])
            return f"Last updated: {last_updated.strftime('%I:%M:%S %p')}"
        except:
            return ""

    @app.callback(
        [Output("period-1d", "active"),
         Output("period-1w", "active"),
         Output("period-1mo", "active"),
         Output("period-1y", "active")],
        [Input("period-1d", "n_clicks"),
         Input("period-1w", "n_clicks"),
         Input("period-1mo", "n_clicks"),
         Input("period-1y", "n_clicks")]
    )
    def update_active_period_button(n_1d, n_1w, n_1mo, n_1y):
        """Update which period button is active"""
        button_id = ctx.triggered_id if ctx.triggered_id else "period-1y"
        
        return (
            button_id == "period-1d",
            button_id == "period-1w", 
            button_id == "period-1mo",
            button_id == "period-1y"
        ) 