"""
webui/components/header.py - Sidebar navigation + top status bar.

Redesigned from a simple header card to a persistent sidebar with icon navigation
and a top status bar showing portfolio metrics and market status.
"""

import dash_bootstrap_components as dbc
from dash import html

from webui.config.constants import COLORS, SIDEBAR_NAV


def _create_sidebar():
    """Create the fixed left sidebar with icon navigation."""
    nav_items = []
    for i, item in enumerate(SIDEBAR_NAV):
        is_first = i == 0
        nav_items.append(
            html.Button(
                [
                    html.Span(item["icon"], className="material-symbols-outlined"),
                    html.Span(item["label"], className="sidebar-nav-label"),
                ],
                id=item["id"],
                className=f"sidebar-nav-item {'active' if is_first else ''}",
                title=item["label"],
            )
        )

    return html.Nav(
        [
            # Logo
            html.Div(
                [
                    html.Span("🦙", style={"fontSize": "24px"}),
                    html.Div("Alpaca", className="sidebar-nav-label",
                             style={"fontSize": "11px", "fontWeight": "700",
                                    "color": COLORS["primary"], "marginTop": "2px"}),
                ],
                style={"marginBottom": "24px", "textAlign": "center"},
            ),
            # Nav items
            *nav_items,
            # Spacer
            html.Div(style={"flex": "1"}),
            # Debug toggle at bottom
            html.Button(
                [
                    html.Span("bug_report", className="material-symbols-outlined"),
                    html.Span("Debug", className="sidebar-nav-label"),
                ],
                id="toggle-debug-panel",
                className="sidebar-nav-item",
                title="Open Debug Tools panel",
            ),
        ],
        className="sidebar-nav",
    )


def _create_top_status_bar():
    """Create the top status bar with portfolio metrics."""
    return html.Div(
        [
            # Left: App title
            html.Div(
                [
                    html.Span(
                        "AlpacaTradingAgent",
                        style={
                            "fontFamily": "'Space Grotesk', sans-serif",
                            "fontWeight": "700",
                            "fontSize": "16px",
                            "color": COLORS["primary"],
                        },
                    ),
                ],
            ),
            # Center: Portfolio metrics (populated by callbacks)
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("PORTFOLIO VALUE", className="status-metric-label"),
                            html.Div(id="top-portfolio-value", children="—",
                                     className="status-metric-value"),
                        ],
                        className="status-metric",
                        style={"marginRight": "32px"},
                    ),
                    html.Div(
                        [
                            html.Div("DAY'S P&L", className="status-metric-label"),
                            html.Div(id="top-daily-pl", children="—",
                                     className="status-metric-value"),
                        ],
                        className="status-metric",
                    ),
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            # Right: Market status + time
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(className="market-status-dot open",
                                      id="market-status-dot"),
                            html.Span("MARKET", style={"fontWeight": "600"}),
                            html.Span(id="market-status-text", children="—"),
                        ],
                        className="market-status",
                    ),
                ],
            ),
        ],
        className="top-status-bar",
    )


def create_header():
    """Create the sidebar + top status bar layout wrapper."""
    return html.Div([
        _create_sidebar(),
        _create_top_status_bar(),
    ])
