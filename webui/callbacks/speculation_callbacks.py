"""webui/callbacks/speculation_callbacks.py - Callbacks for the Speculation sub-tab."""

from __future__ import annotations

import logging
from datetime import datetime

import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, callback_context, dcc, html, no_update

from webui.components.scanner_page import PLAYBOOK_MODEL_OPTIONS
from webui.components.speculation_page import SPECULATION_MODEL_OPTIONS
from webui.utils.speculation_state import SPECULATION_STATE

logger = logging.getLogger(__name__)

_DIRECTION_COLOR = {"bullish": "#22C55E", "bearish": "#EF4444"}
_CONFIDENCE_COLOR = {"high": "#22C55E", "medium": "#F59E0B", "low": "#EF4444"}
_CATALYST_ICON = {
    "supply shock": "warning",
    "demand surge": "trending_up",
    "demand decline": "trending_down",
    "macro": "account_balance",
    "sentiment": "people",
    "regulatory": "gavel",
    "M&A": "handshake",
    "earnings": "bar_chart",
}


def _play_card(play) -> dbc.Card:
    dir_color = _DIRECTION_COLOR.get(play.direction, "#94A3B8")
    conf_color = _CONFIDENCE_COLOR.get(play.confidence, "#94A3B8")
    cat_icon = _CATALYST_ICON.get(play.catalyst_type, "lightbulb")

    # Compute rgba background for confidence badge
    hex_color = conf_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    conf_bg = f"rgba({r},{g},{b},0.15)"

    return dbc.Card(
        dbc.CardBody([
            html.Div([
                html.Span(
                    play.ticker,
                    style={
                        "backgroundColor": dir_color,
                        "color": "#0F172A",
                        "fontWeight": "800",
                        "fontSize": "13px",
                        "padding": "2px 10px",
                        "borderRadius": "4px",
                        "marginRight": "10px",
                        "letterSpacing": "0.5px",
                        "fontFamily": "'Space Grotesk', monospace",
                    },
                ),
                html.Span(
                    play.direction.upper(),
                    style={"color": dir_color, "fontWeight": "700", "fontSize": "11px",
                           "marginRight": "8px"},
                ),
                html.Span(
                    play.company_name,
                    style={"color": "#CBD5E1", "fontSize": "13px"},
                ),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "8px",
                      "flexWrap": "wrap", "gap": "4px"}),

            html.Div([
                html.Span([
                    html.Span(cat_icon, className="material-symbols-outlined",
                              style={"fontSize": "13px", "verticalAlign": "middle",
                                     "marginRight": "3px"}),
                    play.catalyst_type,
                ], style={
                    "backgroundColor": "rgba(167,139,250,0.15)",
                    "color": "#A78BFA",
                    "fontSize": "11px",
                    "padding": "2px 8px",
                    "borderRadius": "3px",
                    "marginRight": "6px",
                    "fontWeight": "600",
                }),
                html.Span(
                    play.sector,
                    style={
                        "backgroundColor": "rgba(100,116,139,0.2)",
                        "color": "#94A3B8",
                        "fontSize": "11px",
                        "padding": "2px 8px",
                        "borderRadius": "3px",
                        "marginRight": "6px",
                    },
                ),
                html.Span(
                    play.confidence.upper(),
                    style={
                        "color": conf_color,
                        "fontSize": "11px",
                        "fontWeight": "700",
                        "padding": "2px 8px",
                        "borderRadius": "3px",
                        "backgroundColor": conf_bg,
                    },
                ),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px",
                      "flexWrap": "wrap", "gap": "4px"}),

            html.Div([
                html.Span("Breaking: ", style={"color": "#64748B", "fontSize": "11px",
                                               "fontStyle": "italic"}),
                html.Span(
                    play.event.headline[:120] + ("…" if len(play.event.headline) > 120 else ""),
                    style={"color": "#94A3B8", "fontSize": "12px"},
                ),
                html.Span(f" — {play.event.source}",
                          style={"color": "#475569", "fontSize": "11px"}),
            ], style={"marginBottom": "8px", "lineHeight": "1.4"}),

            html.Div(
                play.reasoning,
                style={"fontSize": "12px", "color": "#CBD5E1", "lineHeight": "1.5",
                       "borderLeft": f"2px solid {dir_color}",
                       "paddingLeft": "10px", "marginBottom": "10px"},
            ),
            html.Div(
                dbc.Button(
                    [
                        html.Span("manage_search", className="material-symbols-outlined me-1",
                                  style={"fontSize": "14px", "verticalAlign": "middle"}),
                        "Deep Dive",
                    ],
                    id={"type": "spec-deep-dive-btn", "index": f"{play.ticker}_{play.direction}"},
                    size="sm",
                    color="link",
                    style={
                        "color": "#A78BFA",
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "padding": "2px 8px",
                        "border": "1px solid rgba(167,139,250,0.3)",
                        "borderRadius": "4px",
                        "textDecoration": "none",
                    },
                    n_clicks=0,
                ),
                style={"textAlign": "right"},
            ),
        ]),
        style={
            "backgroundColor": "rgba(15,23,42,0.7)",
            "border": f"1px solid {dir_color}33",
            "marginBottom": "10px",
        },
    )


def _render_results(plays) -> html.Div:
    if not plays:
        return html.Div(
            "No speculative plays identified from current news. Try again later or "
            "switch to a more powerful model.",
            style={"color": "#64748B", "fontSize": "13px", "padding": "24px",
                   "textAlign": "center"},
        )

    bullish = [p for p in plays if p.direction == "bullish"]
    bearish = [p for p in plays if p.direction == "bearish"]

    sections = []

    if bullish:
        sections.append(html.Div([
            html.Div([
                html.Span("trending_up", className="material-symbols-outlined me-2",
                          style={"color": "#22C55E", "verticalAlign": "middle"}),
                html.Span(f"BULLISH PLAYS ({len(bullish)})",
                          style={"fontWeight": "700", "fontSize": "12px",
                                 "letterSpacing": "1px", "color": "#22C55E"}),
            ], style={"marginBottom": "10px"}),
            *[_play_card(p) for p in bullish],
        ], style={"marginBottom": "16px"}))

    if bearish:
        sections.append(html.Div([
            html.Div([
                html.Span("trending_down", className="material-symbols-outlined me-2",
                          style={"color": "#EF4444", "verticalAlign": "middle"}),
                html.Span(f"BEARISH PLAYS ({len(bearish)})",
                          style={"fontWeight": "700", "fontSize": "12px",
                                 "letterSpacing": "1px", "color": "#EF4444"}),
            ], style={"marginBottom": "10px"}),
            *[_play_card(p) for p in bearish],
        ]))

    return html.Div(sections)


def register_speculation_callbacks(app):
    """Register callbacks for the Speculation sub-tab."""

    _run_idle = [
        html.Span("auto_awesome", className="material-symbols-outlined me-1",
                  style={"fontSize": "18px", "verticalAlign": "middle"}),
        "Run Speculation Scan",
    ]
    _run_busy = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Scanning news & analyzing...",
    ]

    @app.callback(
        [
            Output("speculation-llm-model", "options"),
            Output("speculation-llm-model", "value"),
        ],
        Input("speculation-llm-provider", "value"),
        prevent_initial_call=True,
    )
    def update_speculation_model_options(provider):
        opts = SPECULATION_MODEL_OPTIONS.get(provider or "openai", [])
        default = opts[0]["value"] if opts else None
        return opts, default

    @app.callback(
        [
            Output("speculation-results-panel", "children"),
            Output("speculation-scan-status", "children"),
            Output("speculation-results-store", "data"),
        ],
        Input("speculation-run-btn", "n_clicks"),
        [
            State("speculation-llm-provider", "value"),
            State("speculation-llm-model", "value"),
        ],
        running=[
            (Output("speculation-run-btn", "disabled"), True, False),
            (Output("speculation-run-btn", "children"), _run_busy, _run_idle),
        ],
        prevent_initial_call=True,
    )
    def run_speculation_scan(n_clicks, provider, model):
        if not n_clicks:
            return no_update, no_update, no_update

        try:
            from tradingagents.speculation import SpeculationEngine
            engine = SpeculationEngine()
            plays = engine.run(provider=provider or "openai", model=model or None)
            SPECULATION_STATE.set_plays(plays)
        except Exception as exc:
            logger.exception("Speculation scan failed")
            error_msg = html.Div(
                f"Scan failed: {exc}",
                style={"color": "#EF4444", "fontSize": "13px", "padding": "16px"},
            )
            return error_msg, f"Error: {exc}", []

        ts = datetime.now().strftime("%H:%M:%S")
        status = f"Last scan: {ts} · {len(plays)} plays identified"

        store_data = [
            {
                "ticker": p.ticker,
                "company_name": p.company_name,
                "sector": p.sector,
                "direction": p.direction,
                "confidence": p.confidence,
                "reasoning": p.reasoning,
                "catalyst_type": p.catalyst_type,
                "event_headline": p.event.headline,
                "event_source": p.event.source,
            }
            for p in plays
        ]

        return _render_results(plays), status, store_data

    @app.callback(
        Output("speculation-signal-banner", "children"),
        Input("speculation-results-store", "data"),
    )
    def update_signal_banner(store_data):
        """Show active speculation signals as a banner in the Day Trading tab."""
        if not store_data:
            return None

        bullish = [r["ticker"] for r in store_data if r.get("direction") == "bullish"]
        bearish = [r["ticker"] for r in store_data if r.get("direction") == "bearish"]

        if not bullish and not bearish:
            return None

        chips = []
        for t in bullish[:8]:
            chips.append(html.Button(
                [html.Span("▲ ", style={"fontSize": "10px"}), t],
                id={"type": "spec-signal-chip", "ticker": t, "dir": "bullish"},
                n_clicks=0,
                style={
                    "backgroundColor": "rgba(34,197,94,0.15)",
                    "color": "#22C55E",
                    "border": "1px solid rgba(34,197,94,0.3)",
                    "fontSize": "11px",
                    "fontWeight": "700",
                    "padding": "2px 8px",
                    "borderRadius": "3px",
                    "marginRight": "4px",
                    "fontFamily": "'Space Grotesk', monospace",
                    "cursor": "pointer",
                },
            ))
        for t in bearish[:8]:
            chips.append(html.Button(
                [html.Span("▼ ", style={"fontSize": "10px"}), t],
                id={"type": "spec-signal-chip", "ticker": t, "dir": "bearish"},
                n_clicks=0,
                style={
                    "backgroundColor": "rgba(239,68,68,0.15)",
                    "color": "#EF4444",
                    "border": "1px solid rgba(239,68,68,0.3)",
                    "fontSize": "11px",
                    "fontWeight": "700",
                    "padding": "2px 8px",
                    "borderRadius": "3px",
                    "marginRight": "4px",
                    "fontFamily": "'Space Grotesk', monospace",
                    "cursor": "pointer",
                },
            ))

        return html.Div(
            [
                html.Span(
                    [
                        html.Span("auto_awesome", className="material-symbols-outlined me-1",
                                  style={"fontSize": "13px", "verticalAlign": "middle",
                                         "color": "#A78BFA"}),
                        html.Span("Speculation signals: ",
                                  style={"color": "#A78BFA", "fontWeight": "600",
                                         "fontSize": "11px", "marginRight": "8px"}),
                    ]
                ),
                *chips,
            ],
            style={
                "display": "flex",
                "alignItems": "center",
                "flexWrap": "wrap",
                "gap": "4px",
                "padding": "6px 10px",
                "backgroundColor": "rgba(124,58,237,0.08)",
                "border": "1px solid rgba(124,58,237,0.25)",
                "borderRadius": "6px",
            },
        )

    # ── Deep Dive: button click → store the selected signal ──────────────────

    @app.callback(
        Output("spec-deep-dive-signal", "data"),
        Input({"type": "spec-deep-dive-btn", "index": ALL}, "n_clicks"),
        State("speculation-results-store", "data"),
        prevent_initial_call=True,
    )
    def store_deep_dive_signal(n_clicks_list, store_data):
        if not any(n_clicks_list) or not store_data:
            return no_update
        ctx = callback_context
        if not ctx.triggered:
            return no_update
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        try:
            import json
            btn_id = json.loads(triggered_id)
            index = btn_id.get("index", "")
        except Exception:
            return no_update
        # index is "{ticker}_{direction}"
        parts = index.rsplit("_", 1)
        if len(parts) != 2:
            return no_update
        ticker, direction = parts
        for sig in store_data:
            if sig.get("ticker") == ticker and sig.get("direction") == direction:
                return sig
        return no_update

    # ── Deep Dive: store change → open modal ─────────────────────────────────

    @app.callback(
        [
            Output("spec-deep-dive-modal", "is_open"),
            Output("spec-deep-dive-modal-title", "children"),
        ],
        [
            Input("spec-deep-dive-signal", "data"),
            Input("spec-deep-dive-close-btn", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def toggle_deep_dive_modal(signal_data, close_clicks):
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update
        trigger = ctx.triggered[0]["prop_id"]
        if "close" in trigger:
            return False, no_update
        if not signal_data:
            return no_update, no_update
        ticker = signal_data.get("ticker", "")
        direction = signal_data.get("direction", "")
        company = signal_data.get("company_name", "")
        dir_color = _DIRECTION_COLOR.get(direction, "#94A3B8")
        title = html.Div([
            html.Span(
                ticker,
                style={"backgroundColor": dir_color, "color": "#0F172A",
                       "fontWeight": "800", "fontSize": "14px",
                       "padding": "2px 10px", "borderRadius": "4px",
                       "marginRight": "10px", "fontFamily": "'Space Grotesk', monospace"},
            ),
            html.Span(direction.upper(), style={"color": dir_color, "fontWeight": "700",
                                                 "fontSize": "12px", "marginRight": "8px"}),
            html.Span(f"Deep Dive — {company}",
                      style={"color": "#CBD5E1", "fontSize": "13px"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "4px"})
        return True, title

    # ── Deep Dive: run button → LLM analysis ─────────────────────────────────

    _dd_idle = [
        html.Span("search", className="material-symbols-outlined me-1",
                  style={"fontSize": "16px", "verticalAlign": "middle"}),
        "Run Deep Dive",
    ]
    _dd_busy = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Researching...",
    ]

    @app.callback(
        Output("spec-deep-dive-content", "children"),
        Input("spec-deep-dive-run-btn", "n_clicks"),
        [
            State("spec-deep-dive-signal", "data"),
            State("spec-deep-dive-llm-provider", "value"),
            State("spec-deep-dive-llm-model", "value"),
        ],
        running=[
            (Output("spec-deep-dive-run-btn", "disabled"), True, False),
            (Output("spec-deep-dive-run-btn", "children"), _dd_busy, _dd_idle),
        ],
        prevent_initial_call=True,
    )
    def run_spec_deep_dive(n_clicks, signal_data, provider, model):
        if not n_clicks or not signal_data:
            return no_update
        ticker = signal_data.get("ticker", "")
        if not ticker:
            return html.Div("No signal selected.", style={"color": "#64748B"})
        try:
            from tradingagents.speculation.deep_dive_llm import generate_deep_dive
            markdown = generate_deep_dive(
                ticker=ticker,
                company_name=signal_data.get("company_name", ticker),
                direction=signal_data.get("direction", "bullish"),
                catalyst_type=signal_data.get("catalyst_type", ""),
                reasoning=signal_data.get("reasoning", ""),
                event_headline=signal_data.get("event_headline", ""),
                event_source=signal_data.get("event_source", ""),
                provider=provider or "anthropic",
                model=model or "claude-sonnet-4-6",
            )
        except Exception as exc:
            logger.exception("Speculation deep-dive failed")
            return html.Div(f"Deep dive failed: {exc}", style={"color": "#EF4444"})
        if not markdown:
            return html.Div("No analysis returned. Try a different model or check your API key.",
                            style={"color": "#F59E0B"})
        return dcc.Markdown(
            markdown,
            style={"color": "#CBD5E1", "fontSize": "13px", "lineHeight": "1.7"},
            className="speculation-deep-dive",
        )

    # ── Deep Dive: provider change → update model options ────────────────────

    @app.callback(
        [
            Output("spec-deep-dive-llm-model", "options"),
            Output("spec-deep-dive-llm-model", "value"),
        ],
        Input("spec-deep-dive-llm-provider", "value"),
        prevent_initial_call=True,
    )
    def update_deep_dive_model_options(provider):
        opts = PLAYBOOK_MODEL_OPTIONS.get(provider or "anthropic", [])
        default = opts[0]["value"] if opts else None
        return opts, default

    # ── Banner chip click → store clicked signal for Day Trading playbook ─────

    @app.callback(
        Output("speculation-clicked-signal", "data"),
        Input({"type": "spec-signal-chip", "ticker": ALL, "dir": ALL}, "n_clicks"),
        State("speculation-results-store", "data"),
        prevent_initial_call=True,
    )
    def store_clicked_signal(n_clicks_list, store_data):
        if not any(n_clicks_list) or not store_data:
            return no_update
        ctx = callback_context
        if not ctx.triggered:
            return no_update
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        try:
            import json
            chip_id = json.loads(triggered_id)
            ticker = chip_id.get("ticker", "")
            direction = chip_id.get("dir", "")
        except Exception:
            return no_update
        for sig in store_data:
            if sig.get("ticker") == ticker and sig.get("direction") == direction:
                return sig
        # Signal not found in store — return minimal dict from chip id
        return {"ticker": ticker, "direction": direction}
