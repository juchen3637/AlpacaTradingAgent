"""webui/components/longterm_page.py — 'Long Term' subtab inside the Trading page.

Mega-cap quality screen with a buy-and-hold thesis generator. All Dash IDs
prefixed `lt-` to avoid collision with `scanner-*` (day-trade) and
`trading-*` (Alpaca account) IDs.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dash_table, dcc, html

from webui.components.scanner_page import (
    PLAYBOOK_DEFAULT_MODEL,
    PLAYBOOK_DEFAULT_PROVIDER,
    PLAYBOOK_MODEL_OPTIONS,
)

# Sectors offered in the exclude multi-select. Keep aligned with Finnhub
# `finnhubIndustry` values we expect in mega-cap names.
# Substring tokens against Finnhub `gicsSector` (with `finnhubIndustry`
# fallback). `passes_sector_exclusion` matches case-insensitively, so
# short tokens like "Consumer" cover both Discretionary and Staples.
SECTOR_OPTIONS = [
    {"label": "Information Technology", "value": "Information Technology"},
    {"label": "Financials", "value": "Financial"},
    {"label": "Health Care", "value": "Health"},
    {"label": "Consumer Discretionary", "value": "Consumer Discretionary"},
    {"label": "Consumer Staples", "value": "Consumer Staples"},
    {"label": "Energy", "value": "Energy"},
    {"label": "Industrials", "value": "Industrial"},
    {"label": "Communication Services", "value": "Communication"},
    {"label": "Utilities", "value": "Utilities"},
    {"label": "Real Estate", "value": "Real Estate"},
    {"label": "Materials", "value": "Materials"},
]


def _section_header(icon: str, title: str, subtitle: str = ""):
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        icon,
                        className="material-symbols-outlined",
                        style={"color": "#10B981", "fontSize": "20px"},
                    ),
                    html.Span(
                        title,
                        style={
                            "fontFamily": "'Space Grotesk', sans-serif",
                            "fontWeight": "700", "fontSize": "14px",
                            "letterSpacing": "1px", "marginLeft": "8px",
                        },
                    ),
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            html.Div(
                subtitle,
                style={"fontSize": "12px", "color": "#94A3B8", "marginTop": "4px"},
            ) if subtitle else None,
        ],
        style={"marginBottom": "16px"},
    )


def _filters_card():
    label_style = {"fontSize": "11px", "color": "#94A3B8",
                   "textTransform": "uppercase", "letterSpacing": "1px"}
    return dbc.Card(
        dbc.CardBody(
            [
                _section_header(
                    "trending_up",
                    "LONG-TERM FILTERS",
                    "Quality + valuation screen for buy-and-hold investing. "
                    "Default = S&P 100 mega caps.",
                ),
                dbc.Row(
                    [
                        dbc.Col([
                            html.Label("Universe", style=label_style),
                            dcc.Dropdown(
                                id="lt-universe",
                                options=[
                                    {"label": "Mega Cap (S&P 100)", "value": "mega_cap"},
                                    {"label": "Custom Watchlist", "value": "watchlist"},
                                ],
                                value="mega_cap",
                                clearable=False,
                            ),
                        ], xs=12, md=3),
                        dbc.Col([
                            html.Label("Min Mkt Cap ($B)", style=label_style),
                            dbc.Input(id="lt-min-mcap", type="number",
                                      min=0, step=10, value=100),
                        ], xs=6, md=2),
                        dbc.Col([
                            html.Label("Max P/E", style=label_style),
                            dbc.Input(id="lt-max-pe", type="number",
                                      min=0, step=1, placeholder="—"),
                        ], xs=6, md=2),
                        dbc.Col([
                            html.Label("Profitable Only", style=label_style),
                            dbc.Checklist(
                                id="lt-profitable-only",
                                options=[{"label": " Req.", "value": "on"}],
                                value=["on"], switch=True,
                            ),
                        ], xs=6, md=2),
                        dbc.Col([
                            html.Label("Catalyst Only", style=label_style,
                                       title="Require recent catalyst (earnings, M&A, "
                                             "FDA, mgmt change, insider, filing, news)."),
                            dbc.Checklist(
                                id="lt-catalyst-only",
                                options=[{"label": " Req.", "value": "on"}],
                                value=[], switch=True,
                            ),
                        ], xs=6, md=2),
                        dbc.Col([
                            html.Label("Force Refresh", style=label_style,
                                       title="Bypass fundamentals/profile/trend caches."),
                            dbc.Checklist(
                                id="lt-force-refresh",
                                options=[{"label": " Bypass cache", "value": "on"}],
                                value=[], switch=True,
                            ),
                        ], xs=6, md=1),
                    ],
                    className="mb-3",
                ),
                dbc.Row(
                    [
                        dbc.Col([
                            html.Label(
                                "Watchlist (comma-separated; leave blank to use Universe)",
                                style=label_style,
                            ),
                            dbc.Input(
                                id="lt-watchlist", type="text",
                                placeholder="NVDA, MSFT, GOOGL, AMZN",
                                value="",
                            ),
                        ], xs=12, md=6),
                        dbc.Col([
                            html.Label("Exclude Sectors", style=label_style),
                            dcc.Dropdown(
                                id="lt-excluded-sectors",
                                options=SECTOR_OPTIONS,
                                value=[], multi=True, clearable=True,
                                placeholder="None",
                            ),
                        ], xs=12, md=3),
                        dbc.Col([
                            html.Div(style={"height": "22px"}),
                            dbc.Button(
                                [
                                    html.Span(
                                        "search",
                                        className="material-symbols-outlined me-1",
                                        style={"fontSize": "18px",
                                               "verticalAlign": "middle"},
                                    ),
                                    "Run Long-Term Scan",
                                ],
                                id="lt-run-btn", color="success",
                                className="w-100",
                            ),
                        ], xs=12, md=3),
                    ],
                ),
                html.Div(
                    "First scan can take ~1–2 minutes (Finnhub fundamentals "
                    "fetch). Subsequent scans hit the 24h cache and complete in seconds.",
                    style={"fontSize": "11px", "color": "#64748B",
                           "fontStyle": "italic", "marginTop": "12px"},
                ),
            ],
            style={"padding": "20px"},
        ),
        className="glass-card mb-3",
        style={"position": "relative", "zIndex": 10},
    )


def _results_card():
    return dbc.Card(
        dbc.CardBody(
            [
                dbc.Row(
                    [
                        dbc.Col(
                            _section_header(
                                "leaderboard",
                                "RANKED CANDIDATES",
                                "Composite score = ROE · margins · revenue growth · valuation · "
                                "long-term trend · debt · dividend. Higher is better.",
                            ),
                        ),
                        dbc.Col(
                            dbc.Button(
                                [
                                    html.Span(
                                        "content_copy",
                                        className="material-symbols-outlined me-1",
                                        style={"fontSize": "16px",
                                               "verticalAlign": "middle"},
                                    ),
                                    "Export Tickers",
                                ],
                                id="lt-export-btn", color="info", outline=True,
                                size="sm", disabled=True,
                            ),
                            width="auto",
                            className="text-end align-self-start",
                        ),
                    ],
                    align="start",
                    className="g-2 mb-2",
                ),
                html.Div(id="lt-stats", children="Click Run Long-Term Scan to begin.",
                         style={"fontSize": "12px", "color": "#94A3B8",
                                "marginBottom": "12px",
                                "fontVariantNumeric": "tabular-nums"}),
                dash_table.DataTable(
                    id="lt-results-table",
                    columns=[
                        {"name": "Symbol", "id": "symbol"},
                        {"name": "Price", "id": "last_price", "type": "numeric",
                         "format": {"specifier": ",.2f"}},
                        {"name": "Mkt Cap ($B)", "id": "market_cap_b",
                         "type": "numeric", "format": {"specifier": ",.0f"}},
                        {"name": "Sector", "id": "sector"},
                        {"name": "ROE %", "id": "roe_ttm", "type": "numeric",
                         "format": {"specifier": ",.1f"}},
                        {"name": "Net Mgn %", "id": "net_margin_ttm",
                         "type": "numeric", "format": {"specifier": ",.1f"}},
                        {"name": "Rev 3y %", "id": "revenue_growth_3y",
                         "type": "numeric", "format": {"specifier": ",.1f"}},
                        {"name": "P/E", "id": "pe_forward", "type": "numeric",
                         "format": {"specifier": ",.1f"}},
                        {"name": "D/E", "id": "debt_to_equity", "type": "numeric",
                         "format": {"specifier": ",.2f"}},
                        {"name": "Div %", "id": "dividend_yield_ttm",
                         "type": "numeric", "format": {"specifier": ",.2f"}},
                        {"name": "Catalyst", "id": "catalyst"},
                        {"name": "Score", "id": "score", "type": "numeric",
                         "format": {"specifier": ",.3f"}},
                    ],
                    data=[],
                    row_selectable="single",
                    selected_rows=[],
                    page_size=25,
                    style_table={"overflowX": "auto"},
                    style_cell={
                        "backgroundColor": "#1E293B", "color": "#F1F5F9",
                        "fontFamily": "'Inter', sans-serif", "fontSize": "13px",
                        "fontVariantNumeric": "tabular-nums",
                        "border": "1px solid #334155", "padding": "10px",
                    },
                    style_header={
                        "backgroundColor": "#0F172A", "color": "#94A3B8",
                        "fontWeight": "700", "textTransform": "uppercase",
                        "fontSize": "11px", "letterSpacing": "1px",
                    },
                    style_data_conditional=[
                        {"if": {"column_id": "catalyst"},
                         "cursor": "pointer",
                         "color": "#60A5FA",
                         "textDecoration": "underline",
                         "maxWidth": "260px",
                         "overflow": "hidden",
                         "textOverflow": "ellipsis",
                         "whiteSpace": "nowrap"},
                        {"if": {"column_id": "catalyst",
                                "filter_query": '{catalyst} = "—"'},
                         "color": "#64748B",
                         "textDecoration": "none",
                         "cursor": "default"},
                    ],
                ),
            ],
            style={"padding": "20px"},
        ),
        className="glass-card mb-3",
    )


def _chart_panel():
    """Daily/multi-year chart, hidden until a thesis is generated.

    Long-term plays don't use intraday timeframes — the 200-SMA + multi-year
    structure is what matters. Overlays draw the entry zone band + 3y target.
    """
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                html.Span(
                                    "show_chart",
                                    className="material-symbols-outlined",
                                    style={"color": "#10B981", "fontSize": "18px"},
                                ),
                                html.Span(
                                    "PRICE CHART",
                                    style={
                                        "fontFamily": "'Space Grotesk', sans-serif",
                                        "fontWeight": "700", "fontSize": "13px",
                                        "letterSpacing": "1px", "marginLeft": "8px",
                                    },
                                ),
                                html.Span(
                                    " · entry zone + 3y target auto-drawn",
                                    style={"fontSize": "11px", "color": "#64748B",
                                           "marginLeft": "10px"},
                                ),
                            ],
                            style={"display": "flex", "alignItems": "center"},
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.RadioItems(
                            id="lt-chart-timeframe",
                            options=[
                                {"label": "1mo", "value": "1mo"},
                                {"label": "1y", "value": "1y"},
                                {"label": "3y", "value": "3y"},
                                {"label": "5y", "value": "5y"},
                            ],
                            value="1y",
                            inline=True,
                            className="btn-group",
                            inputClassName="btn-check",
                            labelClassName="btn btn-outline-secondary btn-sm",
                            labelCheckedClassName="active",
                        ),
                        className="text-end",
                    ),
                ],
                align="center",
                className="mb-2",
                style={"marginTop": "16px"},
            ),
            html.Div(
                id="lt-chart",
                className="chart-host",
                style={"width": "100%", "height": "400px"},
            ),
            dcc.Store(id="lt-chart-payload"),
            html.Div(
                "Data via Alpaca · daily bars · 200-SMA structure visible at 1y+",
                style={"fontSize": "11px", "color": "#64748B",
                       "fontStyle": "italic", "marginTop": "4px"},
            ),
        html.Button(
            html.Span("fullscreen", className="material-symbols-outlined",
                      style={"fontSize": "18px", "lineHeight": "1"}),
            className="chart-fullscreen-btn",
            title="Fullscreen (Esc to exit)",
        ),
        ],
        id="lt-chart-wrapper",
        **{"data-fs-wrapper": "true"},
        style={"display": "none", "position": "relative"},
    )


def _deep_dive_panel():
    """Web-search-backed AI deep-dive: why this is a good candidate, recent
    catalysts, moat, risks. Hidden until a candidate is selected; renders
    a markdown report after the user clicks Deep Dive.
    """
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                html.Span(
                                    "travel_explore",
                                    className="material-symbols-outlined",
                                    style={"color": "#3B82F6", "fontSize": "18px"},
                                ),
                                html.Span(
                                    "DEEP DIVE",
                                    style={
                                        "fontFamily": "'Space Grotesk', sans-serif",
                                        "fontWeight": "700", "fontSize": "13px",
                                        "letterSpacing": "1px", "marginLeft": "8px",
                                    },
                                ),
                                html.Span(
                                    " · why is this a good candidate? recent catalysts, moat, risks",
                                    style={"fontSize": "11px", "color": "#64748B",
                                           "marginLeft": "10px"},
                                ),
                            ],
                            style={"display": "flex", "alignItems": "center",
                                   "flexWrap": "wrap"},
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Button(
                            [
                                html.Span(
                                    "search",
                                    className="material-symbols-outlined me-1",
                                    style={"fontSize": "16px",
                                           "verticalAlign": "middle"},
                                ),
                                "Run Deep Dive",
                            ],
                            id="lt-deep-dive-btn",
                            color="primary", outline=True, size="sm",
                            disabled=True,
                            title="Web-search backed analysis (~30–60s, Anthropic Sonnet)",
                        ),
                        className="text-end",
                    ),
                ],
                align="center",
                className="mb-2",
                style={"marginTop": "20px"},
            ),
            dcc.Loading(
                id="lt-deep-dive-loading",
                type="dot", color="#3B82F6",
                children=dcc.Markdown(
                    id="lt-deep-dive-output",
                    children="",
                    link_target="_blank",
                    style={"fontSize": "13px", "color": "#CBD5E1",
                           "lineHeight": "1.6",
                           "padding": "12px 14px",
                           "backgroundColor": "rgba(15, 23, 42, 0.4)",
                           "borderRadius": "6px",
                           "borderLeft": "3px solid #3B82F6",
                           "minHeight": "1px"},
                ),
            ),
            dcc.Store(id="lt-deep-dive-trigger"),
        ],
        id="lt-deep-dive-wrapper",
        style={"display": "none"},  # revealed once a candidate is selected
    )


def _thesis_card():
    label_style = {"fontSize": "11px", "color": "#94A3B8",
                   "textTransform": "uppercase", "letterSpacing": "1px"}
    return dbc.Card(
        dbc.CardBody(
            [
                _section_header(
                    "psychology",
                    "AI THESIS",
                    "Select a candidate above, then click Generate Thesis for a "
                    "buy-and-hold plan with DCA cadence and 3-year target.",
                ),
                dbc.Row(
                    [
                        dbc.Col([
                            html.Label("LLM Provider", style=label_style),
                            dcc.Dropdown(
                                id="lt-llm-provider",
                                options=[
                                    {"label": "OpenAI", "value": "openai"},
                                    {"label": "Anthropic", "value": "anthropic"},
                                ],
                                value=PLAYBOOK_DEFAULT_PROVIDER, clearable=False,
                            ),
                        ], xs=12, md=4),
                        dbc.Col([
                            html.Label("Model", style=label_style),
                            dcc.Dropdown(
                                id="lt-llm-model",
                                options=PLAYBOOK_MODEL_OPTIONS[PLAYBOOK_DEFAULT_PROVIDER],
                                value=PLAYBOOK_DEFAULT_MODEL, clearable=False,
                            ),
                        ], xs=12, md=5),
                        dbc.Col([
                            html.Div(style={"height": "22px"}),
                            dbc.Button(
                                [
                                    html.Span(
                                        "auto_awesome",
                                        className="material-symbols-outlined me-1",
                                        style={"fontSize": "18px",
                                               "verticalAlign": "middle"},
                                    ),
                                    "Generate Thesis",
                                ],
                                id="lt-thesis-btn", color="secondary",
                                className="w-100", disabled=True,
                            ),
                        ], xs=12, md=3),
                    ],
                    className="mb-3", align="start",
                ),
                html.Div(
                    id="lt-thesis-output",
                    children="No candidate selected.",
                    style={"fontSize": "13px", "color": "#94A3B8"},
                ),
                _deep_dive_panel(),
                _chart_panel(),
                html.Div(
                    [
                        dbc.Button(
                            [
                                html.Span(
                                    "rocket_launch",
                                    className="material-symbols-outlined me-1",
                                    style={"fontSize": "18px",
                                           "verticalAlign": "middle"},
                                ),
                                "Execute (Paper)",
                            ],
                            id="lt-execute-btn", color="success",
                            disabled=True,
                            style={"marginTop": "12px"},
                            title="Submit a paper bracket order from this long-term thesis.",
                        ),
                        dbc.Button(
                            [
                                html.Span(
                                    "cancel",
                                    className="material-symbols-outlined me-1",
                                    style={"fontSize": "18px",
                                           "verticalAlign": "middle"},
                                ),
                                "Cancel Order",
                            ],
                            id="lt-cancel-order-btn", color="warning", outline=True,
                            disabled=True,
                            style={"marginTop": "12px", "marginLeft": "10px"},
                            title="Cancel a long-term scanner order that hasn't filled yet.",
                        ),
                        dbc.Button(
                            [
                                html.Span(
                                    "close",
                                    className="material-symbols-outlined me-1",
                                    style={"fontSize": "18px",
                                           "verticalAlign": "middle"},
                                ),
                                "Liquidate Position",
                            ],
                            id="lt-liquidate-btn", color="danger", outline=True,
                            disabled=True,
                            style={"marginTop": "12px", "marginLeft": "10px"},
                            title="Cancel any open bracket legs and market-close the position.",
                        ),
                        dbc.Button(
                            [
                                html.Span(
                                    "bookmark_add",
                                    className="material-symbols-outlined me-1",
                                    style={"fontSize": "18px",
                                           "verticalAlign": "middle"},
                                ),
                                "Save to Plays",
                            ],
                            id="lt-save-btn", color="info", outline=True,
                            disabled=True,
                            style={"marginTop": "12px", "marginLeft": "10px"},
                            title="Save this long-term thesis to the Plays tab",
                        ),
                        html.Div(id="lt-execute-status",
                                 style={"marginTop": "10px", "fontSize": "13px"}),
                        html.Div(id="lt-save-status",
                                 style={"marginTop": "10px", "fontSize": "13px"}),
                    ],
                ),
            ],
            style={"padding": "20px"},
        ),
        className="glass-card",
    )


def _export_tickers_modal():
    """Modal showing the candidates as a comma-separated ticker list, ready to
    paste into the Analysis section's watchlist."""
    return dbc.Modal(
        [
            dbc.ModalHeader(
                dbc.ModalTitle("Export Tickers"),
                close_button=True,
            ),
            dbc.ModalBody(
                [
                    html.Div(
                        "Comma-separated list of all ranked candidates. Paste "
                        "into the Analysis section's watchlist.",
                        style={"fontSize": "13px", "color": "#CBD5E1",
                               "marginBottom": "12px"},
                    ),
                    dbc.Textarea(
                        id="lt-export-textarea",
                        value="",
                        readOnly=True,
                        style={"fontFamily": "'JetBrains Mono', monospace",
                               "fontSize": "13px", "minHeight": "120px",
                               "backgroundColor": "#0F172A", "color": "#F1F5F9",
                               "border": "1px solid #334155"},
                    ),
                    html.Div(
                        id="lt-export-count",
                        style={"fontSize": "11px", "color": "#64748B",
                               "fontStyle": "italic", "marginTop": "6px"},
                    ),
                ],
                style={"color": "#F1F5F9"},
            ),
            dbc.ModalFooter([
                dbc.Button("Close", id="lt-export-close-btn",
                           color="secondary", outline=True),
                dbc.Button(
                    [
                        html.Span(
                            "content_copy",
                            className="material-symbols-outlined me-1",
                            style={"fontSize": "16px", "verticalAlign": "middle"},
                        ),
                        "Copy to Clipboard",
                    ],
                    id="lt-export-copy-btn", color="info",
                ),
            ]),
        ],
        id="lt-export-modal",
        is_open=False, size="lg", centered=True,
    )


def _save_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Save Long-Term Play"), close_button=True),
            dbc.ModalBody(
                [
                    html.Div(id="lt-save-modal-summary",
                             style={"color": "#CBD5E1", "fontSize": "13px",
                                    "marginBottom": "12px"}),
                    html.Label("Label",
                               style={"fontSize": "11px", "color": "#94A3B8",
                                      "textTransform": "uppercase",
                                      "letterSpacing": "1px"}),
                    dbc.Input(id="lt-save-label-input", type="text",
                              placeholder="NVDA long-term hold"),
                    html.Div(
                        "Saved long-term plays appear in the Plays tab with the "
                        "thesis, DCA schedule, and 3-year target preserved.",
                        style={"fontSize": "12px", "color": "#64748B",
                               "fontStyle": "italic", "marginTop": "10px"},
                    ),
                ],
                style={"color": "#F1F5F9"},
            ),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="lt-save-cancel-btn",
                           color="secondary", outline=True),
                dbc.Button("Save Play", id="lt-save-confirm-btn", color="info"),
            ]),
        ],
        id="lt-save-modal",
        is_open=False, size="md", centered=True, backdrop="static",
    )


def _execute_confirm_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Confirm Long-Term Paper Trade"),
                            close_button=True),
            dbc.ModalBody(id="lt-execute-confirm-body",
                          style={"color": "#F1F5F9"}),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="lt-execute-cancel-btn",
                           color="secondary", outline=True),
                dbc.Button("Confirm & Submit", id="lt-execute-confirm-btn",
                           color="success"),
            ]),
        ],
        id="lt-execute-confirm-modal",
        is_open=False, size="md", centered=True, backdrop="static",
    )


def _liquidate_confirm_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Liquidate Long-Term Position"),
                            close_button=True),
            dbc.ModalBody(id="lt-liquidate-confirm-body",
                          style={"color": "#F1F5F9"}),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="lt-liquidate-cancel-btn",
                           color="secondary", outline=True),
                dbc.Button("Confirm & Liquidate", id="lt-liquidate-confirm-btn",
                           color="danger"),
            ]),
        ],
        id="lt-liquidate-confirm-modal",
        is_open=False, size="md", centered=True, backdrop="static",
    )


def _cancel_order_confirm_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Cancel Pending Long-Term Order"),
                            close_button=True),
            dbc.ModalBody(id="lt-cancel-order-confirm-body",
                          style={"color": "#F1F5F9"}),
            dbc.ModalFooter([
                dbc.Button("Keep Order", id="lt-cancel-order-keep-btn",
                           color="secondary", outline=True),
                dbc.Button("Confirm & Cancel", id="lt-cancel-order-confirm-btn",
                           color="warning"),
            ]),
        ],
        id="lt-cancel-order-confirm-modal",
        is_open=False, size="md", centered=True, backdrop="static",
    )


def _catalyst_modal():
    """Catalyst deep-dive modal — mirrors the day-trade scanner pattern.

    Shows the structured Finnhub card synchronously, then streams an
    AI-written narrative ("why is this catalyst favorable?") into the
    same modal once the bound LLM finishes its web-search call.
    """
    body_text_style = {"color": "#F1F5F9", "fontSize": "14px",
                       "lineHeight": "1.6"}
    section_label = {
        "fontSize": "11px", "fontWeight": "600", "letterSpacing": "0.08em",
        "textTransform": "uppercase", "color": "#94A3B8",
        "marginBottom": "8px", "marginTop": "20px",
    }
    return dbc.Modal(
        [
            dbc.ModalHeader(
                dbc.ModalTitle(id="lt-catalyst-modal-title"),
                close_button=True,
            ),
            dbc.ModalBody([
                # Triggers the async explainer callback when modal opens.
                dcc.Store(id="lt-catalyst-explain-trigger"),
                # Instant: structured Finnhub card
                dcc.Markdown(
                    id="lt-catalyst-modal-body",
                    link_target="_blank",
                    style=body_text_style,
                ),
                # Async: AI narrative — why is this favorable for the stock?
                html.Div("Why is this catalyst favorable?",
                         style=section_label),
                dcc.Loading(
                    id="lt-catalyst-explainer-loading",
                    type="dot",
                    color="#3B82F6",
                    children=dcc.Markdown(
                        id="lt-catalyst-explainer-output",
                        link_target="_blank",
                        style=body_text_style,
                    ),
                ),
            ]),
        ],
        id="lt-catalyst-modal",
        is_open=False,
        size="lg",
        centered=True,
        scrollable=True,
    )


def create_longterm_page():
    """Assemble the Long Term subtab layout."""
    return html.Div(
        [
            dcc.Store(id="lt-results-store", data=[]),
            dcc.Store(id="lt-pending-execution"),
            dcc.Store(id="lt-order-state",
                      data={"unfilled_count": 0, "has_position": False}),
            # 5s poll while a row is selected — drives Cancel/Liquidate enable state
            dcc.Interval(id="lt-order-state-interval",
                         interval=5000, disabled=True),
            _filters_card(),
            _results_card(),
            _thesis_card(),
            _export_tickers_modal(),
            _save_modal(),
            _execute_confirm_modal(),
            _liquidate_confirm_modal(),
            _cancel_order_confirm_modal(),
            _catalyst_modal(),
        ]
    )
