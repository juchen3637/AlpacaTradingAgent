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
                                    "Watchlist (comma-separated symbols, used with Custom)",
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
                            xs=12, md=9,
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
            ],
            style={"padding": "20px"},
        ),
        className="glass-card",
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
                html.Div("Deep dive — why is this moving?", style=section_label),
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
            _filters_card(),
            _results_card(),
            _playbook_card(),
            _catalyst_modal(),
        ]
    )
