"""
webui/callbacks/nav_callbacks.py - Sidebar navigation page switching.

Toggles visibility of page sections (dashboard, analytics, portfolio, config)
based on which sidebar nav button is clicked. Updates the active button class.
"""

from dash import Input, Output, ctx


_SHOW = {"display": "block"}
_HIDE = {"display": "none"}
_ACTIVE = "sidebar-nav-item active"
_INACTIVE = "sidebar-nav-item"

# Map nav button ID → page to show
_PAGE_MAP = {
    "nav-dashboard": "dashboard",
    "nav-analytics": "analytics",
    "nav-portfolio": "portfolio",
    "nav-journal": "journal",
    "nav-config": "config",
}

_NAV_IDS = list(_PAGE_MAP.keys())
_PAGE_IDS = [
    "page-dashboard", "page-analytics", "page-portfolio",
    "page-journal", "page-config",
]


def register_nav_callbacks(app):
    """Register sidebar navigation callbacks."""

    @app.callback(
        [Output(pid, "style") for pid in _PAGE_IDS]
        + [Output(nid, "className") for nid in _NAV_IDS],
        [Input(nid, "n_clicks") for nid in _NAV_IDS],
        prevent_initial_call=True,
    )
    def switch_page(*_clicks):
        triggered = ctx.triggered_id
        active_page = _PAGE_MAP.get(triggered, "dashboard")

        page_styles = [
            _SHOW if pid == f"page-{active_page}" else _HIDE
            for pid in _PAGE_IDS
        ]

        nav_classes = [
            _ACTIVE if nid == triggered else _INACTIVE
            for nid in _NAV_IDS
        ]

        return page_styles + nav_classes
