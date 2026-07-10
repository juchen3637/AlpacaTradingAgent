"""webui/components/speculation_page.py - Speculation sub-tab UI.

Scan broad market/world news → LLM identifies stocks likely to move.
Results feed a signal banner in the Day Trading tab.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

from webui.components.scanner_page import (
    PLAYBOOK_DEFAULT_MODEL,
    PLAYBOOK_DEFAULT_PROVIDER,
    PLAYBOOK_MODEL_OPTIONS,
)

SPECULATION_MODEL_OPTIONS: dict[str, list[dict]] = {
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

SPECULATION_DEFAULT_PROVIDER = "anthropic"
SPECULATION_DEFAULT_MODEL = "claude-opus-4-8"


def _section_header(icon: str, title: str, subtitle: str = ""):
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        icon,
                        className="material-symbols-outlined",
                        style={"color": "#A78BFA", "fontSize": "20px"},
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
                style={"fontSize": "12px", "color": "#94A3B8", "marginTop": "4px"},
            ) if subtitle else None,
        ],
        style={"marginBottom": "16px"},
    )


def _controls_card():
    return dbc.Card(
        dbc.CardBody([
            _section_header(
                "newspaper",
                "SPECULATION SCANNER",
                "Scans macro & world news, then uses AI to identify stocks likely to move.",
            ),
            dbc.Row([
                dbc.Col([
                    html.Label("LLM Provider", style={"fontSize": "12px", "color": "#94A3B8",
                                                       "marginBottom": "4px"}),
                    dcc.Dropdown(
                        id="speculation-llm-provider",
                        options=[
                            {"label": "OpenAI", "value": "openai"},
                            {"label": "Anthropic", "value": "anthropic"},
                        ],
                        value=SPECULATION_DEFAULT_PROVIDER,
                        clearable=False,
                        className="dark-dropdown",
                    ),
                ], xs=12, md=3),
                dbc.Col([
                    html.Label("Model", style={"fontSize": "12px", "color": "#94A3B8",
                                               "marginBottom": "4px"}),
                    dcc.Dropdown(
                        id="speculation-llm-model",
                        options=SPECULATION_MODEL_OPTIONS[SPECULATION_DEFAULT_PROVIDER],
                        value=SPECULATION_DEFAULT_MODEL,
                        clearable=False,
                        className="dark-dropdown",
                    ),
                ], xs=12, md=4),
                dbc.Col([
                    html.Div(style={"height": "24px"}),
                    dbc.Button(
                        [
                            html.Span("auto_awesome", className="material-symbols-outlined me-1",
                                      style={"fontSize": "18px", "verticalAlign": "middle"}),
                            "Run Speculation Scan",
                        ],
                        id="speculation-run-btn",
                        color="primary",
                        style={"backgroundColor": "#7C3AED", "borderColor": "#7C3AED",
                               "fontWeight": "600"},
                    ),
                ], xs=12, md=5),
            ]),
            html.Div(id="speculation-scan-status",
                     style={"marginTop": "10px", "fontSize": "12px", "color": "#94A3B8"}),
        ]),
        style={"backgroundColor": "rgba(15,23,42,0.8)", "border": "1px solid #1E293B",
               "marginBottom": "16px"},
    )


def _empty_state():
    return html.Div(
        [
            html.Span("newspaper", className="material-symbols-outlined",
                      style={"fontSize": "48px", "color": "#334155", "display": "block",
                             "textAlign": "center", "marginBottom": "12px"}),
            html.Div("No speculation scan run yet.",
                     style={"textAlign": "center", "color": "#64748B", "fontSize": "14px"}),
            html.Div("Click 'Run Speculation Scan' to fetch recent news and identify "
                     "event-driven opportunities.",
                     style={"textAlign": "center", "color": "#475569", "fontSize": "12px",
                            "marginTop": "6px"}),
        ],
        style={"padding": "48px 24px"},
    )


def _deep_dive_modal() -> dbc.Modal:
    _label_style = {"fontSize": "11px", "color": "#94A3B8",
                    "textTransform": "uppercase", "letterSpacing": "1px"}
    return dbc.Modal(
        [
            dbc.ModalHeader(
                html.Div(
                    id="spec-deep-dive-modal-title",
                    style={"fontFamily": "'Space Grotesk', sans-serif",
                           "fontWeight": "700", "fontSize": "15px"},
                ),
                style={"backgroundColor": "#0F172A", "borderBottom": "1px solid #1E293B"},
            ),
            dbc.ModalBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Label("LLM Provider", style=_label_style),
                                    dcc.Dropdown(
                                        id="spec-deep-dive-llm-provider",
                                        options=[
                                            {"label": "Anthropic (recommended — web search)", "value": "anthropic"},
                                            {"label": "OpenAI", "value": "openai"},
                                        ],
                                        value="anthropic",
                                        clearable=False,
                                        className="dark-dropdown",
                                    ),
                                ],
                                xs=12, md=5,
                            ),
                            dbc.Col(
                                [
                                    html.Label("Model", style=_label_style),
                                    dcc.Dropdown(
                                        id="spec-deep-dive-llm-model",
                                        options=PLAYBOOK_MODEL_OPTIONS["anthropic"],
                                        value="claude-sonnet-4-6",
                                        clearable=False,
                                        className="dark-dropdown",
                                    ),
                                ],
                                xs=12, md=5,
                            ),
                            dbc.Col(
                                [
                                    html.Div(style={"height": "22px"}),
                                    dbc.Button(
                                        [
                                            html.Span("search", className="material-symbols-outlined me-1",
                                                      style={"fontSize": "16px", "verticalAlign": "middle"}),
                                            "Run Deep Dive",
                                        ],
                                        id="spec-deep-dive-run-btn",
                                        color="primary",
                                        className="w-100",
                                        style={"backgroundColor": "#7C3AED", "borderColor": "#7C3AED"},
                                    ),
                                ],
                                xs=12, md=2,
                            ),
                        ],
                        className="mb-3",
                        align="start",
                    ),
                    dcc.Loading(
                        html.Div(
                            id="spec-deep-dive-content",
                            style={"minHeight": "200px"},
                        ),
                        type="dot",
                        color="#A78BFA",
                    ),
                ],
                style={"backgroundColor": "#0F172A"},
            ),
            dbc.ModalFooter(
                dbc.Button("Close", id="spec-deep-dive-close-btn", n_clicks=0, color="secondary",
                           outline=True, size="sm"),
                style={"backgroundColor": "#0F172A", "borderTop": "1px solid #1E293B"},
            ),
        ],
        id="spec-deep-dive-modal",
        is_open=False,
        size="xl",
        backdrop=True,
        scrollable=True,
        style={"color": "#F1F5F9"},
    )


def create_speculation_page() -> html.Div:
    return html.Div([
        dcc.Store(id="speculation-results-store", data=[]),
        dcc.Store(id="spec-deep-dive-signal"),
        dcc.Interval(id="speculation-refresh-interval", interval=3000, n_intervals=0),
        _deep_dive_modal(),
        html.Div(
            [_controls_card()],
            style={"padding": "16px 16px 0"},
        ),
        html.Div(
            id="speculation-results-panel",
            children=[_empty_state()],
            style={"padding": "0 16px 16px"},
        ),
    ])
