"""
Layout module for TradingAgents WebUI
4-tab layout: Dashboard, Analytics, Portfolio, Config
"""

from dash import dcc, html
import dash_bootstrap_components as dbc

from webui.components.header import create_header
from webui.components.config_panel import create_config_panel
from webui.components.status_panel import create_status_panel
from webui.components.chart_panel import create_chart_panel
from webui.components.decision_panel import create_decision_panel
from webui.components.reports_panel import create_reports_panel
from webui.components.alpaca_account import render_alpaca_account_section
from webui.components.batch_overview_panel import create_batch_overview_panel
from webui.components.debug_panel import create_debug_panel
from webui.components.portfolio_page import create_portfolio_page
from webui.config.constants import COLORS, REFRESH_INTERVALS


def create_intervals():
    """Create interval components for auto-refresh"""
    return [
        dcc.Interval(id='refresh-interval', interval=REFRESH_INTERVALS["fast"],
                     n_intervals=0, disabled=True),
        dcc.Interval(id='medium-refresh-interval', interval=REFRESH_INTERVALS["medium"],
                     n_intervals=0, disabled=True),
        dcc.Interval(id='slow-refresh-interval', interval=REFRESH_INTERVALS["slow"],
                     n_intervals=0, disabled=False),
    ]


def create_stores():
    """Create store components for state management"""
    from webui.utils.storage import create_storage_store_component
    return [
        dcc.Store(id='app-store'),
        dcc.Store(id='chart-store', data={'last_symbol': None, 'selected_period': '1y'}),
        create_storage_store_component(),
    ]


def _create_dashboard_page():
    """Dashboard: chart (full width) + ticker input + positions + orders + account cards."""
    chart_card = create_chart_panel()

    return html.Div(id="page-dashboard", children=[
        # Row 1: Ticker input + Start Analysis
        dbc.Row([
            dbc.Col([
                dbc.InputGroup([
                    dbc.InputGroupText(
                        html.Span("search", className="material-symbols-outlined",
                                  style={"fontSize": "18px", "color": "#94A3B8"}),
                    ),
                    dbc.Input(
                        id="ticker-input",
                        type="text",
                        placeholder="Enter symbols to analyze (e.g., AAPL, NVDA, BTC/USD)",
                        value="NVDA, AMD, TSLA",
                    ),
                ], className="mb-0"),
            ], xs=12, lg=9),
            dbc.Col([
                html.Div(id="control-button-container", children=[
                    dbc.Button(
                        [html.Span("play_arrow", className="material-symbols-outlined me-1",
                                   style={"fontSize": "18px", "verticalAlign": "middle"}),
                         "Start Analysis"],
                        id="control-btn",
                        color="primary",
                        className="w-100",
                    ),
                ]),
            ], xs=12, lg=3),
        ], className="mb-3", align="center"),
        html.Div(id="result-text", className="mb-3"),

        # Row 2: Full-width chart
        chart_card,

        # Row 3: Account summary cards
        html.Div(id="dashboard-account-cards", children=[
            render_alpaca_account_section()
        ]),
    ], style={"display": "block"})


def _create_analytics_page():
    """Analytics: agent reports + batch progress + status + decision."""
    return html.Div(id="page-analytics", children=[
        # Row 1: Batch progress + analysis status
        dbc.Row([
            dbc.Col([create_batch_overview_panel()], xs=12, lg=8),
            dbc.Col([create_status_panel()], xs=12, lg=4),
        ], className="mb-4"),

        # Row 2: Decision summary
        create_decision_panel(),

        # Row 3: Full reports panel (10 agent tabs)
        create_reports_panel(),
    ], style={"display": "none"})


def _create_portfolio_page():
    """Portfolio: performance analytics, charts, sector breakdown."""
    return html.Div(id="page-portfolio", children=[
        create_portfolio_page(),
    ], style={"display": "none"})


def _create_config_page():
    """Config: all analysis configuration options."""
    return html.Div(id="page-config", children=[
        create_config_panel(),
    ], style={"display": "none"})


def create_main_layout():
    """Create the main application layout."""

    layout = html.Div([
        # Intervals and stores (invisible)
        *create_intervals(),
        *create_stores(),

        # Client-side script for iframe prompt messages
        html.Script("""
            window.addEventListener('message', function(event) {
                if (event.origin !== window.location.origin) return;
                if (event.data && event.data.type === 'showPrompt') {
                    var buttons = document.querySelectorAll('[id*="show-prompt-"]');
                    var reportType = event.data.reportType;
                    var targetButton = null;
                    for (var i = 0; i < buttons.length; i++) {
                        var buttonId = buttons[i].getAttribute('id');
                        if (buttonId && buttonId.includes(reportType)) {
                            targetButton = buttons[i];
                            break;
                        }
                    }
                    if (targetButton) {
                        targetButton.click();
                    }
                }
            });
        """),

        # Sidebar + Top status bar
        create_header(),

        # Main content area (offset by sidebar)
        html.Div([
            _create_dashboard_page(),
            _create_analytics_page(),
            _create_portfolio_page(),
            _create_config_page(),
        ], className="main-content-with-sidebar p-3 p-md-4",
           style={"backgroundColor": COLORS["background"], "minHeight": "100vh"}),

        # Debug panel (side drawer)
        create_debug_panel(),
    ], style={"backgroundColor": COLORS["background"]})

    return layout
