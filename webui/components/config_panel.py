"""
webui/components/config_panel.py - Configuration panel for the web UI.
"""

import dash_bootstrap_components as dbc
from dash import html
from datetime import datetime

def create_config_panel():
    """Create the configuration panel for the web UI."""
    return dbc.Card(
        dbc.CardBody([
            html.Div(
                [
                    html.Span("tune", className="material-symbols-outlined",
                               style={"color": "#3B82F6", "fontSize": "18px"}),
                    html.Span("AGENT CONFIGURATION",
                               style={"fontFamily": "'Space Grotesk', sans-serif",
                                      "fontWeight": "700", "fontSize": "13px",
                                      "letterSpacing": "1px", "marginLeft": "8px"}),
                ],
                style={"display": "flex", "alignItems": "center", "marginBottom": "16px"},
            ),
            html.H5("AI Picked Stocks:", className="mt-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id="ai-picked-stocks",
                        label="Enable AI-Discovered Tickers",
                        value=False,
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    html.Div(id="ai-picked-stocks-info", className="mb-3"),
                ], xs=12, sm=6),
            ]),
            html.H5("Select Analysts:", className="mt-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Checkbox(id="analyst-market", label="Market Analyst", value=True, className="mb-2"),
                ], xs=12, sm=6),
                dbc.Col([
                    dbc.Checkbox(id="analyst-social", label="Social Media Analyst", value=True, className="mb-2"),
                ], xs=12, sm=6),
            ]),
            dbc.Row([
                dbc.Col([
                    dbc.Checkbox(id="analyst-news", label="News Analyst", value=True, className="mb-2"),
                ], xs=12, sm=6),
                dbc.Col([
                    dbc.Checkbox(id="analyst-fundamentals", label="Fundamentals Analyst", value=True, className="mb-2"),
                ], xs=12, sm=6),
            ]),
            dbc.Row([
                dbc.Col([
                    dbc.Checkbox(id="analyst-macro", label="Macro Analyst", value=True, className="mb-2"),
                ], xs=12, sm=6),
                dbc.Col([
                    # Empty column for alignment
                ], xs=12, sm=6),
            ]),
            html.H5("Research Depth:", className="mt-3"),
            dbc.Row([
                dbc.Col([
                    dbc.RadioItems(
                        id="research-depth",
                        options=[
                            {"label": "Shallow", "value": "Shallow"},
                            {"label": "Medium", "value": "Medium"},
                            {"label": "Deep", "value": "Deep"},
                        ],
                        value="Shallow",
                        inline=False,
                        className="mb-3"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    html.Div(id="research-depth-info", className="mb-3"),
                ], xs=12, sm=6),
            ]),
            html.H5("Trading Mode:", className="mt-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id="allow-shorts",
                        label="Allow Shorts (Trading Mode)",
                        value=False,
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    html.Div(id="trading-mode-info", className="mb-3"),
                ], xs=12, sm=6),
            ]),
            html.H5("Execution Mode:", className="mt-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id="parallel-execution",
                        label="Enable Parallel Analyst Execution",
                        value=False,
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    html.Div(id="parallel-execution-info", className="mb-3"),
                ], xs=12, sm=6),
            ]),
            html.H5("Parallel Batch Configuration:", className="mt-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Batch Size (symbols per batch)", className="mb-1"),
                    dbc.Input(
                        id="batch-size",
                        type="number",
                        placeholder="5",
                        value=5,
                        min=1,
                        max=20,
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    dbc.Label("Batch Delay (seconds between batches)", className="mb-1"),
                    dbc.Input(
                        id="batch-delay",
                        type="number",
                        placeholder="5",
                        value=5,
                        min=0,
                        max=60,
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
            ]),
            dbc.Row([
                dbc.Col([
                    html.Div(id="batch-config-info", className="mb-3"),
                ], width=12),
            ]),
            html.H5("Scheduling Configuration:", className="mt-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id="loop-enabled",
                        label="Enable Loop Mode",
                        value=False,
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    dbc.Label("Loop Interval (minutes)", className="mb-1"),
                    dbc.Input(
                        id="loop-interval",
                        type="number",
                        placeholder="60",
                        value=60,
                        min=1,
                        max=1440,
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
            ]),
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id="market-hour-enabled",
                        label="Trade at Market Hour",
                        value=False,
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    dbc.Label("Trading Hours — start,end (e.g. 9,16 for 9AM–4PM EST)", className="mb-1"),
                    dbc.Input(
                        id="market-hours-input",
                        type="text",
                        placeholder="e.g., 9,16",
                        value="",
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
            ]),
            html.Div(id="market-hours-validation", className="mb-2"),
            html.Div(id="scheduling-mode-info", className="mb-3"),
            html.H5("Automated Trading:", className="mt-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id="trade-after-analyze",
                        label="Trade After Analyze",
                        value=False,
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    dbc.Switch(
                        id="ai-position-sizing",
                        label="AI-Determined Position Sizing",
                        value=True,
                        className="mb-2"
                    ),
                ], xs=12, sm=6),
            ]),
            html.Small("AI agents determine trade size based on risk analysis", className="text-muted mb-2"),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Max Order Amount ($)", className="mb-1"),
                    html.Small(
                        "When AI sizing enabled: acts as maximum cap (leave blank for no cap). When disabled: fixed trade amount (leave blank to use buying power).",
                        className="text-muted d-block mb-1"
                    ),
                    dbc.Input(
                        id="trade-dollar-amount",
                        type="number",
                        placeholder="No limit (AI-determined)",
                        value=None,
                        max=10000000,
                        className="mb-2"
                    ),
                ], width=12),
            ]),
            html.Div(id="trade-after-analyze-info", className="mb-3"),

            html.H5("Order Protection:", className="mt-3"),
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id="use-stop-loss",
                        label="Use Stop Loss Orders",
                        value=True,
                        className="mb-2"
                    ),
                    html.Small("Place automatic stop loss orders based on AI analysis", className="text-muted d-block mb-2"),
                ], xs=12, sm=6),
                dbc.Col([
                    dbc.Switch(
                        id="use-take-profit",
                        label="Use Take Profit Orders",
                        value=True,
                        className="mb-2"
                    ),
                    html.Small("Place automatic take profit orders based on AI analysis", className="text-muted d-block mb-2"),
                ], xs=12, sm=6),
            ]),
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id="use-bracket-orders",
                        label="Use Native Bracket Orders",
                        value=False,
                        className="mb-2"
                    ),
                    html.Small(
                        "Atomic entry + stop + target in one order (uses T1 only, no T2 scale-out)",
                        className="text-muted d-block mb-3"
                    ),
                ], width=12),
            ]),

            html.H5("Position Management:", className="mt-3"),
            html.Small(
                "Prevents flip-flop liquidations by respecting active bracket orders. "
                "Once a bracket is placed, TP/SL is the primary exit; the AI can only "
                "override on strong dissent (high conviction + clear thesis break, or "
                "an adverse price move past the configured threshold).",
                className="text-muted d-block mb-2"
            ),
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id="respect-brackets-when-held",
                        label="Respect Active Brackets",
                        value=True,
                        className="mb-2"
                    ),
                    html.Small(
                        "Master switch — when off, every SELL signal closes immediately (legacy behavior).",
                        className="text-muted d-block mb-2"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    dbc.Label("Min Hold (hours)", className="mb-1"),
                    dbc.Input(
                        id="position-age-min-hold-hours",
                        type="number",
                        value=4,
                        min=0,
                        max=72,
                        step=1,
                        className="mb-2"
                    ),
                    html.Small(
                        "AI cannot exit a position younger than this unless the override fires.",
                        className="text-muted d-block mb-2"
                    ),
                ], xs=12, sm=6),
            ]),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Exit Conviction Threshold", className="mb-1"),
                    dbc.Input(
                        id="exit-conviction-threshold",
                        type="number",
                        value=0.75,
                        min=0,
                        max=1,
                        step=0.05,
                        className="mb-2"
                    ),
                    html.Small(
                        "Minimum conviction (0..1) for the AI to override an active bracket.",
                        className="text-muted d-block mb-2"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    dbc.Label("Adverse Move Override (%)", className="mb-1"),
                    dbc.Input(
                        id="exit-adverse-move-pct",
                        type="number",
                        value=2.0,
                        min=0,
                        max=20,
                        step=0.5,
                        className="mb-2"
                    ),
                    html.Small(
                        "Hard-dissent override: % move against entry that bypasses min-hold.",
                        className="text-muted d-block mb-3"
                    ),
                ], xs=12, sm=6),
            ]),

            html.H5("Cost Controls:", className="mt-3"),
            html.Small(
                "Reduces API spend by skipping low-value re-analyses. Held positions get "
                "a lightweight news + price check on the quick LLM (no full debate); "
                "tickers analyzed within the cooldown window are skipped unless price moves.",
                className="text-muted d-block mb-2"
            ),
            dbc.Row([
                dbc.Col([
                    dbc.Switch(
                        id="health-check-mode-for-held",
                        label="Health-Check Mode for Held Positions",
                        value=True,
                        className="mb-2"
                    ),
                    html.Small(
                        "Held positions skip the full 5-analyst debate; runs news + market only on quick LLM.",
                        className="text-muted d-block mb-2"
                    ),
                ], width=12),
            ]),
            dbc.Row([
                dbc.Col([
                    dbc.Label("Per-Ticker Cooldown (hours)", className="mb-1"),
                    dbc.Input(
                        id="per-ticker-cooldown-hours",
                        type="number",
                        value=4,
                        min=0,
                        max=72,
                        step=1,
                        className="mb-2"
                    ),
                    html.Small(
                        "0 disables the cooldown (legacy hourly cadence).",
                        className="text-muted d-block mb-2"
                    ),
                ], xs=12, sm=6),
                dbc.Col([
                    dbc.Label("Min Price Move to Re-analyze (%)", className="mb-1"),
                    dbc.Input(
                        id="min-price-move-reanalysis-pct",
                        type="number",
                        value=0.0,
                        min=0,
                        max=20,
                        step=0.25,
                        className="mb-2"
                    ),
                    html.Small(
                        "Inside cooldown, only re-analyze if price moved at least this much. 0 = strict cooldown.",
                        className="text-muted d-block mb-3"
                    ),
                ], xs=12, sm=6),
            ]),

            html.H5("LLM Provider:", className="mt-3"),
            dbc.RadioItems(
                id="llm-provider",
                options=[
                    {"label": "OpenAI", "value": "openai"},
                    {"label": "Anthropic", "value": "anthropic"},
                ],
                value="openai",
                inline=True,
                className="mb-3"
            ),
            html.Div(
                id="openai-model-section",
                children=[
                    html.H5("LLM Quick Thinker Model:", className="mt-3"),
                    dbc.Select(
                        id="quick-llm",
                        options=[
                            {"label": "gpt-5.2-2025-12-11", "value": "gpt-5.2-2025-12-11"},
                            {"label": "gpt-5-mini-2025-08-07", "value": "gpt-5-mini-2025-08-07"},
                            {"label": "gpt-5", "value": "gpt-5"},
                            {"label": "gpt-5-mini", "value": "gpt-5-mini"},
                            {"label": "gpt-5-nano", "value": "gpt-5-nano"},
                            {"label": "gpt-4.1", "value": "gpt-4.1"},
                            {"label": "gpt-4.1-nano", "value": "gpt-4.1-nano"},
                            {"label": "gpt-4.1-mini", "value": "gpt-4.1-mini"},
                            {"label": "gpt-4o", "value": "gpt-4o"},
                            {"label": "gpt-4o-mini", "value": "gpt-4o-mini"},
                            {"label": "o3-mini", "value": "o3-mini"},
                            {"label": "o3", "value": "o3"},
                            {"label": "o1", "value": "o1"},
                        ],
                        value="gpt-5-mini-2025-08-07",
                        className="mb-2"
                    ),
                    html.H5("LLM Deep Thinker Model:", className="mt-3"),
                    dbc.Select(
                        id="deep-llm",
                        options=[
                            {"label": "gpt-5.2-2025-12-11", "value": "gpt-5.2-2025-12-11"},
                            {"label": "gpt-5-mini-2025-08-07", "value": "gpt-5-mini-2025-08-07"},
                            {"label": "gpt-5", "value": "gpt-5"},
                            {"label": "gpt-5-mini", "value": "gpt-5-mini"},
                            {"label": "gpt-5-nano", "value": "gpt-5-nano"},
                            {"label": "gpt-4.1", "value": "gpt-4.1"},
                            {"label": "gpt-4.1-nano", "value": "gpt-4.1-nano"},
                            {"label": "gpt-4.1-mini", "value": "gpt-4.1-mini"},
                            {"label": "gpt-4o", "value": "gpt-4o"},
                            {"label": "gpt-4o-mini", "value": "gpt-4o-mini"},
                            {"label": "o3-mini", "value": "o3-mini"},
                            {"label": "o3", "value": "o3"},
                            {"label": "o1", "value": "o1"},
                        ],
                        value="gpt-5.2-2025-12-11",
                        className="mb-3"
                    ),
                ]
            ),
            html.Div(
                id="anthropic-model-section",
                style={"display": "none"},
                children=[
                    html.H5("Anthropic Quick Thinker Model:", className="mt-3"),
                    dbc.Select(
                        id="anthropic-quick-llm",
                        options=[
                            {"label": "claude-opus-4-8", "value": "claude-opus-4-8"},
                            {"label": "claude-opus-4-7", "value": "claude-opus-4-7"},
                            {"label": "claude-sonnet-4-6", "value": "claude-sonnet-4-6"},
                            {"label": "claude-haiku-4-5-20251001", "value": "claude-haiku-4-5-20251001"},
                            {"label": "claude-haiku-4-5", "value": "claude-haiku-4-5"},
                            {"label": "claude-3-5-haiku-20241022", "value": "claude-3-5-haiku-20241022"},
                        ],
                        value="claude-sonnet-4-6",
                        className="mb-2"
                    ),
                    html.H5("Anthropic Deep Thinker Model:", className="mt-3"),
                    dbc.Select(
                        id="anthropic-deep-llm",
                        options=[
                            {"label": "claude-opus-4-8", "value": "claude-opus-4-8"},
                            {"label": "claude-opus-4-7", "value": "claude-opus-4-7"},
                            {"label": "claude-opus-4-6", "value": "claude-opus-4-6"},
                            {"label": "claude-sonnet-4-6", "value": "claude-sonnet-4-6"},
                            {"label": "claude-opus-4-5", "value": "claude-opus-4-5"},
                            {"label": "claude-sonnet-4-5", "value": "claude-sonnet-4-5"},
                            {"label": "claude-3-5-sonnet-20241022", "value": "claude-3-5-sonnet-20241022"},
                        ],
                        value="claude-opus-4-8",
                        className="mb-3"
                    ),
                ]
            ),
        ]),
        className="mb-4 glass-card",
    ) 
