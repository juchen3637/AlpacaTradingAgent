"""webui/components/scanner_page.py - "Trading" tab (ticker scanner + strategy recommender).

UI label is "Trading" but all internal IDs use the `scanner-` prefix to avoid
collision with the pre-existing webui.callbacks.trading_callbacks module (which
handles Alpaca account / liquidation, not scanning).
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dash_table, dcc, html

# Provider → list of model option dicts for the dcc.Dropdown.
PLAYBOOK_MODEL_OPTIONS: dict[str, list[dict]] = {
    "openai": [
        {"label": "GPT-5 (deep)", "value": "gpt-5"},
        {"label": "GPT-5 mini", "value": "gpt-5-mini-2025-08-07"},
        {"label": "GPT-5 nano", "value": "gpt-5-nano"},
        {"label": "GPT-4o", "value": "gpt-4o"},
        {"label": "GPT-4o mini", "value": "gpt-4o-mini"},
        {"label": "o3", "value": "o3"},
        {"label": "o4-mini", "value": "o4-mini"},
    ],
    "anthropic": [
        {"label": "Claude Opus 4.8", "value": "claude-opus-4-8"},
        {"label": "Claude Opus 4.7", "value": "claude-opus-4-7"},
        {"label": "Claude Opus 4.6", "value": "claude-opus-4-6"},
        {"label": "Claude Sonnet 4.6", "value": "claude-sonnet-4-6"},
        {"label": "Claude Haiku 4.5", "value": "claude-haiku-4-5-20251001"},
    ],
}

PLAYBOOK_DEFAULT_PROVIDER = "openai"
PLAYBOOK_DEFAULT_MODEL = "gpt-5-mini-2025-08-07"


def _section_header(icon: str, title: str, subtitle: str = ""):
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        icon,
                        className="material-symbols-outlined",
                        style={"color": "#3B82F6", "fontSize": "20px"},
                    ),
                    html.Span(
                        title,
                        style={
                            "fontFamily": "'Space Grotesk', sans-serif",
                            "fontWeight": "700",
                            "fontSize": "14px",
                            "letterSpacing": "1px",
                            "marginLeft": "8px",
                        },
                    ),
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            html.Div(
                subtitle,
                style={
                    "fontSize": "12px",
                    "color": "#94A3B8",
                    "marginTop": "4px",
                },
            ) if subtitle else None,
        ],
        style={"marginBottom": "16px"},
    )


def _filters_card():
    return dbc.Card(
        dbc.CardBody(
            [
                _section_header(
                    "filter_list",
                    "SCAN FILTERS",
                    "Reddit-distilled day-trade filters: RVOL, price band, float, catalysts.",
                ),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Label(
                                    "Universe",
                                    style={"fontSize": "11px", "color": "#94A3B8",
                                           "textTransform": "uppercase", "letterSpacing": "1px"},
                                ),
                                dcc.Dropdown(
                                    id="scanner-universe",
                                    options=[
                                        {"label": "Most Active (Stocks)", "value": "most_active"},
                                        {"label": "Custom Watchlist", "value": "watchlist"},
                                        {"label": "Crypto", "value": "crypto"},
                                    ],
                                    value="most_active",
                                    clearable=False,
                                ),
                            ],
                            xs=12, md=3,
                        ),
                        dbc.Col(
                            [
                                html.Label(
                                    "Min RVOL",
                                    style={"fontSize": "11px", "color": "#94A3B8",
                                           "textTransform": "uppercase", "letterSpacing": "1px"},
                                ),
                                dbc.Input(
                                    id="scanner-min-rvol",
                                    type="number",
                                    min=0, max=100, step=0.5,
                                    value=2.0,
                                ),
                            ],
                            xs=6, md=2,
                        ),
                        dbc.Col(
                            [
                                html.Label(
                                    "Price Min",
                                    style={"fontSize": "11px", "color": "#94A3B8",
                                           "textTransform": "uppercase", "letterSpacing": "1px"},
                                ),
                                dbc.Input(
                                    id="scanner-price-min",
                                    type="number", min=0, step=0.1, value=1.0,
                                ),
                            ],
                            xs=6, md=2,
                        ),
                        dbc.Col(
                            [
                                html.Label(
                                    "Price Max",
                                    style={"fontSize": "11px", "color": "#94A3B8",
                                           "textTransform": "uppercase", "letterSpacing": "1px"},
                                ),
                                dbc.Input(
                                    id="scanner-price-max",
                                    type="number", min=0, step=0.1, value=1000.0,
                                ),
                            ],
                            xs=6, md=2,
                        ),
                        dbc.Col(
                            [
                                html.Label(
                                    "Max Float (M)",
                                    style={"fontSize": "11px", "color": "#94A3B8",
                                           "textTransform": "uppercase", "letterSpacing": "1px"},
                                ),
                                dbc.Input(
                                    id="scanner-max-float",
                                    type="number", min=0, step=1,
                                    placeholder="—",
                                ),
                            ],
                            xs=6, md=2,
                        ),
                        dbc.Col(
                            [
                                html.Label(
                                    "Catalyst Only",
                                    style={"fontSize": "11px", "color": "#94A3B8",
                                           "textTransform": "uppercase", "letterSpacing": "1px"},
                                ),
                                dbc.Checklist(
                                    id="scanner-catalyst-only",
                                    options=[{"label": " Req.", "value": "on"}],
                                    value=[],
                                    switch=True,
                                ),
                            ],
                            xs=6, md=1,
                        ),
                    ],
                    className="mb-3",
                ),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Label(
                                    "Watchlist (comma-separated symbols — leave blank to use Universe; fill to override)",
                                    style={"fontSize": "11px", "color": "#94A3B8",
                                           "textTransform": "uppercase", "letterSpacing": "1px"},
                                ),
                                dbc.Input(
                                    id="scanner-watchlist",
                                    type="text",
                                    placeholder="NVDA, AMD, TSLA, SPY",
                                    value="",
                                ),
                            ],
                            xs=12, md=7,
                        ),
                        dbc.Col(
                            [
                                html.Label(
                                    "Force Refresh",
                                    style={"fontSize": "11px", "color": "#94A3B8",
                                           "textTransform": "uppercase", "letterSpacing": "1px"},
                                    title=("Bypass caches for daily metrics, intraday VWAP, "
                                           "levels, and catalysts so this scan re-fetches "
                                           "everything live."),
                                ),
                                dbc.Checklist(
                                    id="scanner-force-refresh",
                                    options=[{"label": " Bypass cache", "value": "on"}],
                                    value=[],
                                    switch=True,
                                ),
                            ],
                            xs=6, md=2,
                        ),
                        dbc.Col(
                            [
                                html.Div(style={"height": "22px"}),
                                dbc.Button(
                                    [
                                        html.Span(
                                            "radar",
                                            className="material-symbols-outlined me-1",
                                            style={"fontSize": "18px", "verticalAlign": "middle"},
                                        ),
                                        "Run Scan",
                                    ],
                                    id="scanner-run-btn",
                                    color="primary",
                                    className="w-100",
                                ),
                            ],
                            xs=12, md=3,
                        ),
                    ],
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
                _section_header(
                    "inventory_2",
                    "QUALIFYING TICKERS",
                    "Ranked by composite score (RVOL · ATH proximity · catalyst · move).",
                ),
                html.Div(id="scanner-stats", children="Click Run Scan to begin.",
                         style={"fontSize": "12px", "color": "#94A3B8",
                                "marginBottom": "12px",
                                "fontVariantNumeric": "tabular-nums"}),
                html.Div(id="speculation-signal-banner", style={"marginBottom": "10px"}),
                dcc.Store(id="speculation-clicked-signal"),
                html.Div(id="spec-playbook-panel", style={"display": "none"}, children=[
                    dbc.Card(
                        dbc.CardBody([
                            html.Div(id="spec-playbook-signal-header",
                                     style={"marginBottom": "12px"}),
                            dbc.Row([
                                dbc.Col([
                                    html.Label("Provider",
                                               style={"fontSize": "11px", "color": "#94A3B8",
                                                      "textTransform": "uppercase",
                                                      "letterSpacing": "1px"}),
                                    dcc.Dropdown(
                                        id="spec-signal-llm-provider",
                                        options=[
                                            {"label": "OpenAI", "value": "openai"},
                                            {"label": "Anthropic", "value": "anthropic"},
                                        ],
                                        value=PLAYBOOK_DEFAULT_PROVIDER,
                                        clearable=False,
                                        className="dark-dropdown",
                                    ),
                                ], xs=12, md=4),
                                dbc.Col([
                                    html.Label("Model",
                                               style={"fontSize": "11px", "color": "#94A3B8",
                                                      "textTransform": "uppercase",
                                                      "letterSpacing": "1px"}),
                                    dcc.Dropdown(
                                        id="spec-signal-llm-model",
                                        options=PLAYBOOK_MODEL_OPTIONS[PLAYBOOK_DEFAULT_PROVIDER],
                                        value=PLAYBOOK_DEFAULT_MODEL,
                                        clearable=False,
                                        className="dark-dropdown",
                                    ),
                                ], xs=12, md=5),
                                dbc.Col([
                                    html.Div(style={"height": "22px"}),
                                    dbc.Button(
                                        [
                                            html.Span("auto_awesome",
                                                      className="material-symbols-outlined me-1",
                                                      style={"fontSize": "16px",
                                                             "verticalAlign": "middle"}),
                                            "Generate Playbook",
                                        ],
                                        id="spec-signal-playbook-btn",
                                        color="primary",
                                        className="w-100",
                                    ),
                                ], xs=12, md=3),
                            ], className="mb-3", align="start"),
                            html.Div(id="spec-signal-playbook-output",
                                     style={"fontSize": "13px", "color": "#94A3B8"}),
                        ]),
                        style={"backgroundColor": "rgba(124,58,237,0.06)",
                               "border": "1px solid rgba(124,58,237,0.25)",
                               "marginBottom": "12px"},
                    ),
                ]),
                dash_table.DataTable(
                    id="scanner-results-table",
                    columns=[
                        {"name": "Symbol", "id": "symbol"},
                        {"name": "Price", "id": "last_price", "type": "numeric",
                         "format": {"specifier": ",.2f"}},
                        {"name": "Chg %", "id": "change_pct", "type": "numeric",
                         "format": {"specifier": "+,.2f"}},
                        {"name": "RVOL", "id": "rvol", "type": "numeric",
                         "format": {"specifier": ",.2f"}},
                        {"name": "Volume", "id": "today_volume", "type": "numeric",
                         "format": {"specifier": ",.0f"}},
                        {"name": "Float", "id": "float_shares", "type": "numeric",
                         "format": {"specifier": ",.0f"}},
                        {"name": "Catalyst", "id": "catalyst"},
                        {"name": "Strategy", "id": "strategy_name"},
                        {"name": "Score", "id": "score", "type": "numeric",
                         "format": {"specifier": ",.3f"}},
                    ],
                    data=[],
                    row_selectable="single",
                    selected_rows=[],
                    page_size=25,
                    style_table={"overflowX": "auto"},
                    style_cell={
                        "backgroundColor": "#1E293B",
                        "color": "#F1F5F9",
                        "fontFamily": "'Inter', sans-serif",
                        "fontSize": "13px",
                        "fontVariantNumeric": "tabular-nums",
                        "border": "1px solid #334155",
                        "padding": "10px",
                    },
                    style_header={
                        "backgroundColor": "#0F172A",
                        "color": "#94A3B8",
                        "fontWeight": "700",
                        "textTransform": "uppercase",
                        "fontSize": "11px",
                        "letterSpacing": "1px",
                    },
                    style_data_conditional=[
                        {"if": {"filter_query": "{change_pct} > 0", "column_id": "change_pct"},
                         "color": "#22C55E"},
                        {"if": {"filter_query": "{change_pct} < 0", "column_id": "change_pct"},
                         "color": "#EF4444"},
                        {"if": {"column_id": "catalyst"},
                         "cursor": "pointer",
                         "color": "#60A5FA",
                         "textDecoration": "underline",
                         "maxWidth": "260px",
                         "overflow": "hidden",
                         "textOverflow": "ellipsis",
                         "whiteSpace": "nowrap"},
                        {"if": {"column_id": "catalyst", "filter_query": '{catalyst} = "—"'},
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
    """Live chart panel embedded into the playbook card.

    Auto-renders entry/stop/PT1/PT2 horizontal lines from the generated
    playbook, plus triangle markers for any executed Alpaca paper fills.
    Shown only after a playbook is generated (initially hidden via the
    'd-none' class flipped on by `render_scanner_chart`).
    """
    label_style = {"fontSize": "11px", "color": "#94A3B8",
                   "textTransform": "uppercase", "letterSpacing": "1px"}
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                html.Span("show_chart",
                                          className="material-symbols-outlined",
                                          style={"color": "#3B82F6", "fontSize": "18px"}),
                                html.Span("LIVE CHART",
                                          style={"fontFamily": "'Space Grotesk', sans-serif",
                                                 "fontWeight": "700", "fontSize": "13px",
                                                 "letterSpacing": "1px", "marginLeft": "8px"}),
                                html.Span(
                                    " · entry/stop/PT lines auto-drawn · fills appear after Execute",
                                    style={"fontSize": "11px", "color": "#64748B",
                                           "marginLeft": "10px"},
                                ),
                            ],
                            style={"display": "flex", "alignItems": "center"},
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                dbc.RadioItems(
                                    id="scanner-chart-timeframe",
                                    options=[
                                        {"label": "1m", "value": "1m"},
                                        {"label": "5m", "value": "5m"},
                                        {"label": "15m", "value": "15m"},
                                        {"label": "1h", "value": "1h"},
                                    ],
                                    value="5m",
                                    inline=True,
                                    className="btn-group",
                                    inputClassName="btn-check",
                                    labelClassName="btn btn-outline-secondary btn-sm",
                                    labelCheckedClassName="active",
                                ),
                                dbc.Checklist(
                                    id="scanner-chart-toggles",
                                    options=[
                                        {"label": " Playbook", "value": "playbook"},
                                        {"label": " Position", "value": "position"},
                                    ],
                                    value=["playbook", "position"],
                                    inline=True,
                                    switch=True,
                                    className="ms-3",
                                    style={"fontSize": "12px"},
                                ),
                            ],
                            className="d-flex align-items-center justify-content-end",
                        ),
                        className="text-end",
                    ),
                ],
                align="center",
                className="mb-2",
                style={"marginTop": "16px"},
            ),
            html.Div(
                id="scanner-position-status",
                style={"fontSize": "12px", "color": "#94A3B8",
                       "marginBottom": "6px", "marginTop": "8px",
                       "fontFamily": "'Space Grotesk', sans-serif"},
            ),
            html.Div(
                id="scanner-chart",
                style={"width": "100%", "height": "400px"},
            ),
            dcc.Store(id="scanner-chart-payload"),
            html.Div(
                [
                    "Data via Alpaca IEX feed (free tier) · ~15 min SIP delay, and minutes "
                    "with no IEX trade are simply absent — set ",
                    html.Code("ALPACA_DATA_FEED=sip",
                              style={"backgroundColor": "rgba(148, 163, 184, 0.12)",
                                     "padding": "1px 5px", "borderRadius": "3px"}),
                    " in ",
                    html.Code(".env",
                              style={"backgroundColor": "rgba(148, 163, 184, 0.12)",
                                     "padding": "1px 5px", "borderRadius": "3px"}),
                    " if you have a paid plan · auto-refreshes every 3s",
                ],
                style={"fontSize": "11px", "color": "#64748B",
                       "fontStyle": "italic", "marginTop": "4px"},
            ),
            dcc.Interval(
                id="scanner-chart-poller",
                interval=3_000,  # 3s
                disabled=False,
                n_intervals=0,
            ),
        ],
        id="scanner-chart-wrapper",
        style={"display": "none"},  # Hidden until playbook renders
    )


def _deep_dive_panel():
    """Web-search-backed AI deep-dive: why this strategy fits this ticker
    right now, today's setup, bull/bear case, day-trade risks. Hidden
    until a candidate is selected; renders a markdown report after
    the user clicks Run Deep Dive.
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
                                    " · why does this strategy fit? today's setup, bull/bear case, risks",
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
                            id="scanner-deep-dive-btn",
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
                id="scanner-deep-dive-loading",
                type="dot", color="#3B82F6",
                children=dcc.Markdown(
                    id="scanner-deep-dive-output",
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
            dcc.Store(id="scanner-deep-dive-trigger"),
        ],
        id="scanner-deep-dive-wrapper",
        style={"display": "none"},  # revealed once a row is selected
    )


def _playbook_card():
    _label_style = {"fontSize": "11px", "color": "#94A3B8",
                    "textTransform": "uppercase", "letterSpacing": "1px"}
    return dbc.Card(
        dbc.CardBody(
            [
                _section_header(
                    "menu_book",
                    "AI PLAYBOOK",
                    "Select a ticker above, then click Generate Playbook for an AI-synthesized plan.",
                ),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Label("LLM Provider", style=_label_style),
                                dcc.Dropdown(
                                    id="scanner-llm-provider",
                                    options=[
                                        {"label": "OpenAI", "value": "openai"},
                                        {"label": "Anthropic", "value": "anthropic"},
                                    ],
                                    value=PLAYBOOK_DEFAULT_PROVIDER,
                                    clearable=False,
                                ),
                            ],
                            xs=12, md=4,
                        ),
                        dbc.Col(
                            [
                                html.Label("Model", style=_label_style),
                                dcc.Dropdown(
                                    id="scanner-llm-model",
                                    options=PLAYBOOK_MODEL_OPTIONS[PLAYBOOK_DEFAULT_PROVIDER],
                                    value=PLAYBOOK_DEFAULT_MODEL,
                                    clearable=False,
                                ),
                            ],
                            xs=12, md=5,
                        ),
                        dbc.Col(
                            [
                                html.Div(style={"height": "22px"}),
                                dbc.Button(
                                    [
                                        html.Span("auto_awesome",
                                                  className="material-symbols-outlined me-1",
                                                  style={"fontSize": "18px",
                                                         "verticalAlign": "middle"}),
                                        "Generate Playbook",
                                    ],
                                    id="scanner-playbook-btn",
                                    color="secondary",
                                    className="w-100",
                                    disabled=True,
                                ),
                            ],
                            xs=12, md=3,
                        ),
                    ],
                    className="mb-3",
                    align="start",
                ),
                html.Div(id="scanner-playbook-output",
                         children="No ticker selected.",
                         style={"fontSize": "13px", "color": "#94A3B8"}),
                _chart_panel(),
                _deep_dive_panel(),
                html.Div(
                    [
                        dbc.Button(
                            [
                                html.Span("rocket_launch",
                                          className="material-symbols-outlined me-1",
                                          style={"fontSize": "18px",
                                                 "verticalAlign": "middle"}),
                                "Execute (Paper)",
                            ],
                            id="scanner-execute-btn",
                            color="success",
                            disabled=True,
                            style={"marginTop": "12px"},
                        ),
                        dbc.Button(
                            [
                                html.Span("cancel",
                                          className="material-symbols-outlined me-1",
                                          style={"fontSize": "18px",
                                                 "verticalAlign": "middle"}),
                                "Cancel Order",
                            ],
                            id="scanner-cancel-order-btn",
                            color="warning",
                            outline=True,
                            disabled=True,
                            style={"marginTop": "12px", "marginLeft": "10px"},
                            title="Cancel a scanner order that hasn't filled yet "
                                  "(bracket children auto-cancel with parent)",
                        ),
                        dbc.Button(
                            [
                                html.Span("close",
                                          className="material-symbols-outlined me-1",
                                          style={"fontSize": "18px",
                                                 "verticalAlign": "middle"}),
                                "Liquidate Position",
                            ],
                            id="scanner-liquidate-btn",
                            color="danger",
                            outline=True,
                            disabled=True,
                            style={"marginTop": "12px", "marginLeft": "10px"},
                            title="Cancel any open bracket legs and market-close the position",
                        ),
                        dbc.Button(
                            [
                                html.Span("bookmark_add",
                                          className="material-symbols-outlined me-1",
                                          style={"fontSize": "18px",
                                                 "verticalAlign": "middle"}),
                                "Save",
                            ],
                            id="scanner-save-btn",
                            color="info",
                            outline=True,
                            disabled=True,
                            style={"marginTop": "12px", "marginLeft": "10px"},
                            title="Save this play so you can reopen it later",
                        ),
                        html.Div(id="scanner-execute-status",
                                 style={"marginTop": "10px", "fontSize": "13px"}),
                    ],
                ),
            ],
            style={"padding": "20px"},
        ),
        className="glass-card",
    )


def _liquidate_confirm_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Liquidate Position"), close_button=True),
            dbc.ModalBody(id="scanner-liquidate-confirm-body",
                          style={"color": "#F1F5F9"}),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="scanner-liquidate-cancel-btn",
                           color="secondary", outline=True),
                dbc.Button("Confirm & Liquidate", id="scanner-liquidate-confirm-btn",
                           color="danger"),
            ]),
        ],
        id="scanner-liquidate-confirm-modal",
        is_open=False,
        size="md",
        centered=True,
        backdrop="static",
    )


def _cancel_order_confirm_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Cancel Pending Order"), close_button=True),
            dbc.ModalBody(id="scanner-cancel-order-confirm-body",
                          style={"color": "#F1F5F9"}),
            dbc.ModalFooter([
                dbc.Button("Keep Order", id="scanner-cancel-order-keep-btn",
                           color="secondary", outline=True),
                dbc.Button("Confirm & Cancel", id="scanner-cancel-order-confirm-btn",
                           color="warning"),
            ]),
        ],
        id="scanner-cancel-order-confirm-modal",
        is_open=False,
        size="md",
        centered=True,
        backdrop="static",
    )


def _save_play_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Save Play"), close_button=True),
            dbc.ModalBody(
                [
                    html.Div(id="scanner-save-modal-summary",
                             style={"color": "#CBD5E1", "fontSize": "13px",
                                    "marginBottom": "12px"}),
                    html.Label("Label",
                               style={"fontSize": "11px", "color": "#94A3B8",
                                      "textTransform": "uppercase",
                                      "letterSpacing": "1px"}),
                    dbc.Input(id="scanner-save-label-input", type="text",
                              placeholder="NVDA breakout 5/5"),
                    html.Div(
                        "Saved plays survive a server restart. View, re-analyze, "
                        "and manage them from the Plays tab.",
                        style={"fontSize": "12px", "color": "#64748B",
                               "fontStyle": "italic", "marginTop": "10px"},
                    ),
                ],
                style={"color": "#F1F5F9"},
            ),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="scanner-save-cancel-btn",
                           color="secondary", outline=True),
                dbc.Button("Save Play", id="scanner-save-confirm-btn",
                           color="info"),
            ]),
        ],
        id="scanner-save-modal",
        is_open=False,
        size="md",
        centered=True,
        backdrop="static",
    )


def _execute_confirm_modal():
    label_style = {"fontSize": "11px", "color": "#94A3B8",
                   "textTransform": "uppercase", "letterSpacing": "1px"}
    value_style = {"fontSize": "14px", "color": "#F1F5F9",
                   "fontWeight": "600", "fontVariantNumeric": "tabular-nums"}
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Confirm Paper Trade"), close_button=True),
            dbc.ModalBody(id="scanner-execute-confirm-body",
                          style={"color": "#F1F5F9"}),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="scanner-execute-cancel-btn",
                           color="secondary", outline=True),
                dbc.Button("Confirm & Submit", id="scanner-execute-confirm-btn",
                           color="success"),
            ]),
        ],
        id="scanner-execute-confirm-modal",
        is_open=False,
        size="md",
        centered=True,
        backdrop="static",
    )


def _catalyst_modal():
    body_text_style = {"color": "#F1F5F9", "fontSize": "14px", "lineHeight": "1.6"}
    section_label = {
        "fontSize": "11px", "fontWeight": "600", "letterSpacing": "0.08em",
        "textTransform": "uppercase", "color": "#94A3B8",
        "marginBottom": "8px", "marginTop": "20px",
    }
    return dbc.Modal(
        [
            dbc.ModalHeader(
                dbc.ModalTitle(id="scanner-catalyst-modal-title"),
                close_button=True,
            ),
            dbc.ModalBody([
                # Triggers the async explainer callback when modal opens.
                dcc.Store(id="scanner-catalyst-explain-trigger"),
                # Instant: structured Finnhub card
                dcc.Markdown(
                    id="scanner-catalyst-modal-body",
                    link_target="_blank",
                    style=body_text_style,
                ),
                # Async: AI deep-dive narrative
                html.Div("Why is this catalyst favorable?", style=section_label),
                dcc.Loading(
                    id="scanner-catalyst-explainer-loading",
                    type="dot",
                    color="#3B82F6",
                    children=dcc.Markdown(
                        id="scanner-catalyst-explainer-output",
                        link_target="_blank",
                        style=body_text_style,
                    ),
                ),
            ]),
        ],
        id="scanner-catalyst-modal",
        is_open=False,
        size="lg",
        centered=True,
        scrollable=True,
    )


def create_scanner_page():
    """Assemble the full 'Trading' page layout."""
    return html.Div(
        [
            dcc.Store(id="scanner-results-store", data=[]),
            dcc.Store(id="scanner-pending-execution"),
            dcc.Store(id="scanner-order-state", data={"unfilled_count": 0,
                                                       "has_position": False}),
            _filters_card(),
            _results_card(),
            _playbook_card(),
            _catalyst_modal(),
            _execute_confirm_modal(),
            _liquidate_confirm_modal(),
            _cancel_order_confirm_modal(),
            _save_play_modal(),
        ]
    )
