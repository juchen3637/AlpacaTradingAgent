"""
Constants and configuration for TradingAgents WebUI
"""

# Design system: AlpacaTrader Dark (Google Stitch)
COLORS = {
    "primary": "#3B82F6",         # Electric blue
    "secondary": "#22C55E",       # Success green
    "background": "#0F172A",      # Dark navy
    "card": "#1E293B",            # Slate card surface
    "card_rgba": "rgba(30, 41, 59, 0.8)",  # Glass card
    "text": "#F1F5F9",            # Primary text
    "text_secondary": "#94A3B8",  # Secondary text
    "pending": "#94A3B8",         # Slate gray
    "in_progress": "#F59E0B",     # Amber/warning
    "completed": "#22C55E",       # Success green
    "skipped": "#64748B",         # Muted slate for cooldown-skipped tickers
    "success": "#22C55E",         # Success green
    "error": "#EF4444",           # Danger red
    "warning": "#F59E0B",         # Warning amber
    "nav_active": "#3B82F6",      # Blue for active nav
    "nav_inactive": "#64748B",    # Slate for inactive nav
    "border": "#334155",          # Border color
    "border_rgba": "rgba(51, 65, 85, 0.5)",  # Glass border
    "hover": "#2563EB",           # Hover color
    "sidebar": "#0F172A",         # Sidebar background
    "input_bg": "#0B1120",        # Input/terminal background
}

# Refresh intervals (in milliseconds)
REFRESH_INTERVALS = {
    "fast": 2000,      # 2 seconds for critical updates during analysis
    "medium": 10000,   # 10 seconds for reports (reduced frequency for less interference)
    "slow": 60000,    # 1 minutes for account data (was 30 seconds)
}

# Debounce duration to prevent auto-refresh from overriding user symbol selection
SYMBOL_CLICK_DEBOUNCE_SECONDS = 0  # No debounce — update immediately

# App configuration
APP_CONFIG = {
    "title": "AlpacaTradingAgent — AI Trading Terminal",
    "external_stylesheets": [
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css",
        "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap",
        "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap",
    ],
    "suppress_callback_exceptions": True,
    "update_title": None,
}

# Sidebar navigation items
SIDEBAR_NAV = [
    {"icon": "dashboard", "label": "Dashboard", "id": "nav-dashboard"},
    {"icon": "analytics", "label": "Analytics", "id": "nav-analytics"},
    {"icon": "pie_chart", "label": "Portfolio", "id": "nav-portfolio"},
    {"icon": "receipt_long", "label": "Journal", "id": "nav-journal"},
    {"icon": "trending_up", "label": "Trading", "id": "nav-scanner"},
    {"icon": "bookmarks", "label": "Plays", "id": "nav-plays"},
    {"icon": "settings", "label": "Config", "id": "nav-config"},
]