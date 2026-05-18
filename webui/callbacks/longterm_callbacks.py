"""webui/callbacks/longterm_callbacks.py — Callbacks for the Long Term subtab.

Handles:
- Run Long-Term Scan → LongTermPipeline → results table.
- Provider→Model dropdown sync.
- Generate Thesis → LLM playbook.
- Save flow → SAVED_PLAYS.save() with strategy_id=LONGTERM_HOLD.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from dash import Input, Output, State, ctx, html, no_update

from tradingagents.scanner.longterm_models import (
    LONGTERM_STRATEGY_ID,
    LONGTERM_STRATEGY_NAME,
    LongTermFilters,
)
from tradingagents.scanner.longterm_pipeline import LongTermPipeline
from webui.components.scanner_page import PLAYBOOK_MODEL_OPTIONS
from webui.utils.longterm_state import LONGTERM_STATE
from webui.utils.saved_plays import SAVED_PLAYS

logger = logging.getLogger(__name__)

_FORCE_REFRESH_CATEGORIES = (
    "longterm_fundamentals",
    "longterm_profile",
    "longterm_trend",
)


def _clear_longterm_caches() -> None:
    from tradingagents.dataflows.cache_utils import clear_cache
    for cat in _FORCE_REFRESH_CATEGORIES:
        try:
            clear_cache(cache_category=cat)
        except Exception as exc:
            logger.debug("clear_cache(%s) failed: %s", cat, exc)


def _parse_watchlist(raw: Optional[str]) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


def _build_filters(
    universe: str,
    min_mcap: Optional[float],
    max_pe: Optional[float],
    profitable_only: Optional[list],
    excluded_sectors: Optional[list],
    watchlist_raw: Optional[str],
    catalyst_only: Optional[list] = None,
) -> LongTermFilters:
    return LongTermFilters(
        universe_kind=universe or "mega_cap",
        watchlist=_parse_watchlist(watchlist_raw),
        min_market_cap_b=float(min_mcap) if min_mcap not in (None, "") else 0.0,
        must_be_profitable=bool(profitable_only),
        max_pe=float(max_pe) if max_pe not in (None, "") else None,
        excluded_sectors=tuple(excluded_sectors or ()),
        catalyst_only=bool(catalyst_only),
    )


def _results_to_rows(results) -> list[dict]:
    rows = []
    for r in results:
        s = r.snapshot
        rows.append({
            "symbol": s.symbol,
            "last_price": s.last_price,
            "market_cap_b": s.market_cap_b,
            "sector": s.sector or "—",
            "roe_ttm": s.roe_ttm,
            "net_margin_ttm": s.net_margin_ttm,
            "revenue_growth_3y": s.revenue_growth_3y,
            "pe_forward": s.pe_forward,
            "debt_to_equity": s.debt_to_equity,
            "dividend_yield_ttm": s.dividend_yield_ttm,
            "score": r.score,
            "catalyst": s.catalyst_text if s.has_catalyst else "—",
            "catalyst_details": s.catalyst_details or "",
            "catalyst_category": s.catalyst_category or "",
            "catalyst_raw": list(s.catalyst_raw or ()),
        })
    return rows


def _format_bracket_grid(playbook) -> html.Div:
    """Render the bracket-order numbers (entry/stop/PT1/PT2/size/order)
    when the playbook has them populated. Older saved plays predating the
    bracket schema show entry_price=0.0 — we surface a regenerate hint
    instead of a row of zeros.
    """
    has_bracket = (
        getattr(playbook, "entry_price", 0) > 0
        and getattr(playbook, "stop_loss", 0) > 0
        and getattr(playbook, "profit_target_1", 0) > 0
    )
    if not has_bracket:
        return html.Div(
            "Bracket levels not populated on this playbook — re-generate "
            "to enable Execute (Paper).",
            style={"fontSize": "12px", "color": "#F59E0B",
                   "fontStyle": "italic", "marginBottom": "12px"},
        )
    risk_per_share = max(playbook.entry_price - playbook.stop_loss, 1e-6)
    reward_per_share = playbook.profit_target_1 - playbook.entry_price
    rr = reward_per_share / risk_per_share
    return html.Div(
        [
            html.Div("BRACKET ORDER (paper)", className="pb-label",
                     style={"marginBottom": "8px",
                            "color": "#3B82F6", "letterSpacing": "1px"}),
            html.Div(
                [
                    html.Div([
                        html.Div("ENTRY", className="pb-label"),
                        html.Div(f"${playbook.entry_price:,.2f}",
                                 className="pb-value",
                                 style={"fontWeight": "700", "color": "#60A5FA"}),
                    ], className="pb-row"),
                    html.Div([
                        html.Div("STOP (THESIS-BROKEN)", className="pb-label"),
                        html.Div(f"${playbook.stop_loss:,.2f}",
                                 className="pb-value",
                                 style={"fontWeight": "700", "color": "#EF4444"}),
                    ], className="pb-row"),
                    html.Div([
                        html.Div("PT1 (~1Y)", className="pb-label"),
                        html.Div(f"${playbook.profit_target_1:,.2f}",
                                 className="pb-value",
                                 style={"fontWeight": "700", "color": "#22C55E"}),
                    ], className="pb-row"),
                    html.Div([
                        html.Div("PT2 (3Y)", className="pb-label"),
                        html.Div(f"${playbook.profit_target_2:,.2f}",
                                 className="pb-value",
                                 style={"fontWeight": "700", "color": "#22C55E"}),
                    ], className="pb-row"),
                    html.Div([
                        html.Div("ORDER TYPE", className="pb-label"),
                        html.Div(playbook.order_type, className="pb-value"),
                    ], className="pb-row"),
                    html.Div([
                        html.Div("POSITION SIZE", className="pb-label"),
                        html.Div(f"{playbook.position_size_pct * 100:.1f}% of BP",
                                 className="pb-value"),
                    ], className="pb-row"),
                    html.Div([
                        html.Div("RISK / REWARD", className="pb-label"),
                        html.Div(f"{rr:.2f}", className="pb-value"),
                    ], className="pb-row"),
                ],
                style={"display": "grid",
                       "gridTemplateColumns": "repeat(auto-fit, minmax(160px, 1fr))",
                       "gap": "12px"},
            ),
        ],
        style={"padding": "12px 14px",
               "borderLeft": "3px solid #3B82F6",
               "backgroundColor": "rgba(59, 130, 246, 0.06)",
               "borderRadius": "0 6px 6px 0",
               "marginBottom": "16px"},
    )


def _format_thesis(playbook) -> html.Div:
    """Render a LongTermPlaybook as a structured card."""
    conviction = (playbook.conviction or "low").lower()
    conviction_color = {
        "high": "#22C55E", "medium": "#F59E0B", "low": "#94A3B8",
    }.get(conviction, "#94A3B8")
    return html.Div([
        html.Div(
            playbook.thesis,
            style={"fontSize": "14px", "color": "#F1F5F9",
                   "marginBottom": "16px", "lineHeight": "1.5"},
        ),
        _format_bracket_grid(playbook),
        html.Div(
            [
                html.Div([
                    html.Div("ENTRY ZONE", className="pb-label"),
                    html.Div(
                        f"${playbook.entry_zone_low:,.2f} – ${playbook.entry_zone_high:,.2f}",
                        className="pb-value",
                        style={"fontWeight": "700", "color": "#10B981"},
                    ),
                ], className="pb-row"),
                html.Div([
                    html.Div("DCA SCHEDULE", className="pb-label"),
                    html.Div(f"{playbook.dca_weeks} weeks", className="pb-value"),
                ], className="pb-row"),
                html.Div([
                    html.Div("HOLD HORIZON", className="pb-label"),
                    html.Div(f"{playbook.hold_horizon_years} years",
                             className="pb-value"),
                ], className="pb-row"),
                html.Div([
                    html.Div("3Y TARGET", className="pb-label",
                             title="LLM estimate, not advice."),
                    html.Div(
                        [
                            html.Span(f"${playbook.target_price_3y:,.2f}",
                                      style={"fontWeight": "700"}),
                            html.Span(" (LLM est.)",
                                      style={"fontSize": "11px",
                                             "color": "#64748B",
                                             "marginLeft": "6px",
                                             "fontStyle": "italic"}),
                        ],
                        className="pb-value",
                    ),
                ], className="pb-row"),
                html.Div([
                    html.Div("CONVICTION", className="pb-label"),
                    html.Div(
                        conviction.upper(),
                        className="pb-value",
                        style={"color": conviction_color, "fontWeight": "700"},
                    ),
                ], className="pb-row"),
            ],
            style={"display": "grid",
                   "gridTemplateColumns": "repeat(auto-fit, minmax(200px, 1fr))",
                   "gap": "12px", "marginBottom": "16px"},
        ),
        html.Div(
            [
                html.Div("KEY DRIVERS", className="pb-label",
                         style={"marginBottom": "6px"}),
                html.Ul(
                    [html.Li(d, style={"marginBottom": "4px"})
                     for d in (playbook.key_drivers or ())],
                    style={"color": "#CBD5E1", "fontSize": "13px",
                           "lineHeight": "1.5", "paddingLeft": "20px"},
                ),
            ],
            style={"marginBottom": "12px"},
        ),
        html.Div(
            [
                html.Div("KEY RISKS", className="pb-label",
                         style={"marginBottom": "6px"}),
                html.Ul(
                    [html.Li(r, style={"marginBottom": "4px"})
                     for r in (playbook.key_risks or ())],
                    style={"color": "#CBD5E1", "fontSize": "13px",
                           "lineHeight": "1.5", "paddingLeft": "20px"},
                ),
            ],
            style={"marginBottom": "12px"},
        ),
        html.Div(
            [
                html.Div("CONVICTION REASONING", className="pb-label",
                         style={"marginBottom": "6px"}),
                html.Div(
                    playbook.conviction_reason or "—",
                    style={"fontSize": "13px", "color": "#CBD5E1",
                           "lineHeight": "1.5"},
                ),
            ],
            style={"padding": "12px 14px",
                   "borderLeft": f"3px solid {conviction_color}",
                   "backgroundColor": "rgba(16, 185, 129, 0.06)",
                   "borderRadius": "0 6px 6px 0"},
        ),
    ])


def register_longterm_callbacks(app):
    """Attach all Long-Term callbacks to the Dash app."""

    # ── Provider → Model dropdown sync ──────────────────────────────────

    @app.callback(
        [Output("lt-llm-model", "options"), Output("lt-llm-model", "value")],
        Input("lt-llm-provider", "value"),
        prevent_initial_call=True,
    )
    def sync_lt_models(provider):
        opts = PLAYBOOK_MODEL_OPTIONS.get(provider or "openai", [])
        default_value = opts[0]["value"] if opts else None
        return opts, default_value

    # ── Run Scan ────────────────────────────────────────────────────────

    _run_idle_children = [
        html.Span("search", className="material-symbols-outlined me-1",
                  style={"fontSize": "18px", "verticalAlign": "middle"}),
        "Run Long-Term Scan",
    ]
    _run_busy_children = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Scanning... (first scan may take 1–2 min)",
    ]

    @app.callback(
        [
            Output("lt-results-table", "data"),
            Output("lt-results-store", "data"),
            Output("lt-stats", "children"),
        ],
        Input("lt-run-btn", "n_clicks"),
        [
            State("lt-universe", "value"),
            State("lt-min-mcap", "value"),
            State("lt-max-pe", "value"),
            State("lt-profitable-only", "value"),
            State("lt-excluded-sectors", "value"),
            State("lt-watchlist", "value"),
            State("lt-force-refresh", "value"),
            State("lt-catalyst-only", "value"),
        ],
        running=[
            (Output("lt-run-btn", "disabled"), True, False),
            (Output("lt-run-btn", "children"), _run_busy_children, _run_idle_children),
        ],
        prevent_initial_call=True,
    )
    def run_longterm_scan(n_clicks, universe, min_mcap, max_pe, profitable,
                          excluded, watchlist_raw, force_refresh, catalyst_only):
        if not n_clicks:
            return no_update, no_update, no_update

        if force_refresh:
            _clear_longterm_caches()

        filters = _build_filters(universe, min_mcap, max_pe, profitable,
                                 excluded, watchlist_raw, catalyst_only)
        try:
            from tradingagents.scanner.longterm_data_provider import LongTermDataProvider
            provider = LongTermDataProvider()
            results = LongTermPipeline(provider).run(filters)
        except Exception as exc:
            logger.exception("LongTermPipeline failed")
            return [], [], html.Span(f"Scan failed: {exc}",
                                      style={"color": "#EF4444"})

        LONGTERM_STATE.set_results(results)
        rows = _results_to_rows(results)
        # Strip non-display-friendly fields out of the table rows; the store
        # keeps the full payload so the catalyst modal can render details.
        table_rows = [{k: v for k, v in r.items() if k != "catalyst_raw"}
                      for r in rows]
        ts = datetime.now().strftime("%H:%M:%S")
        if not rows:
            stats = html.Span(
                f"No candidates passed the filters at {ts}. Loosen "
                "min market cap or remove sector exclusions.",
                style={"color": "#F59E0B"},
            )
        else:
            stats = html.Span(
                f"Found {len(rows)} candidates at {ts}. Top score: "
                f"{rows[0]['score']:.3f} ({rows[0]['symbol']}).",
                style={"color": "#10B981"},
            )
        return table_rows, rows, stats

    # ── Enable Generate Thesis on row select ────────────────────────────

    @app.callback(
        Output("lt-thesis-btn", "disabled"),
        Input("lt-results-table", "selected_rows"),
    )
    def toggle_thesis_button(selected_rows):
        return not bool(selected_rows)

    # ── Generate Thesis ─────────────────────────────────────────────────

    _thesis_idle_children = [
        html.Span("auto_awesome", className="material-symbols-outlined me-1",
                  style={"fontSize": "18px", "verticalAlign": "middle"}),
        "Generate Thesis",
    ]
    _thesis_busy_children = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Synthesizing thesis...",
    ]

    @app.callback(
        Output("lt-thesis-output", "children"),
        Input("lt-thesis-btn", "n_clicks"),
        [
            State("lt-results-table", "selected_rows"),
            State("lt-results-store", "data"),
            State("lt-llm-provider", "value"),
            State("lt-llm-model", "value"),
        ],
        running=[
            (Output("lt-thesis-btn", "disabled"), True, False),
            (Output("lt-thesis-btn", "color"), "danger", "secondary"),
            (Output("lt-thesis-btn", "children"),
             _thesis_busy_children, _thesis_idle_children),
        ],
        prevent_initial_call=True,
    )
    def generate_thesis(n_clicks, selected_rows, rows, provider, model):
        if not n_clicks or not selected_rows or not rows:
            return no_update
        symbol = rows[selected_rows[0]]["symbol"]

        scan_result = None
        for r in LONGTERM_STATE.get_results():
            if r.snapshot.symbol == symbol:
                scan_result = r
                break
        if scan_result is None:
            return html.Div("Candidate no longer in latest scan. Re-run scan.",
                            style={"color": "#F59E0B"})

        cached = LONGTERM_STATE.get_playbook(symbol, model or "")
        if cached is not None:
            return _format_thesis(cached)

        try:
            from tradingagents.scanner.longterm_playbook_llm import generate_longterm_playbook
            playbook = generate_longterm_playbook(scan_result, provider=provider, model=model)
        except Exception as exc:
            logger.exception("LongTerm thesis generation failed")
            return html.Div(f"Thesis generation failed: {exc}",
                            style={"color": "#EF4444"})

        LONGTERM_STATE.set_playbook(symbol, playbook, model or "")
        return _format_thesis(playbook)

    # ── Save flow ───────────────────────────────────────────────────────

    @app.callback(
        Output("lt-save-btn", "disabled"),
        [
            Input("lt-thesis-output", "children"),
            Input("lt-results-table", "selected_rows"),
        ],
    )
    def toggle_save_button(thesis_children, selected_rows):
        if not selected_rows:
            return True
        if not thesis_children or thesis_children == "No candidate selected.":
            return True
        return False

    @app.callback(
        [
            Output("lt-save-modal", "is_open"),
            Output("lt-save-modal-summary", "children"),
            Output("lt-save-label-input", "value"),
        ],
        Input("lt-save-btn", "n_clicks"),
        [
            State("lt-results-table", "selected_rows"),
            State("lt-results-store", "data"),
            State("lt-llm-model", "value"),
        ],
        prevent_initial_call=True,
    )
    def open_save_modal(n_clicks, selected_rows, rows, model):
        if not n_clicks or not selected_rows or not rows:
            return no_update, no_update, no_update
        row = rows[selected_rows[0]]
        symbol = row.get("symbol", "")
        playbook = LONGTERM_STATE.get_playbook(symbol, model or "")
        if playbook is None:
            return False, "Thesis not found in memory — re-generate first.", ""
        summary = html.Div([
            html.Span(f"{symbol} · long-term hold",
                      style={"fontWeight": "700", "color": "#F1F5F9"}),
            html.Span(
                f" · entry ${playbook.entry_zone_low:,.2f}–"
                f"${playbook.entry_zone_high:,.2f} · "
                f"{playbook.dca_weeks}w DCA · {playbook.hold_horizon_years}y hold",
                style={"color": "#94A3B8", "marginLeft": "6px"},
            ),
        ])
        default_label = f"{symbol} long-term {datetime.now().strftime('%Y-%m-%d')}"
        return True, summary, default_label

    @app.callback(
        [
            Output("lt-save-modal", "is_open", allow_duplicate=True),
            Output("lt-save-status", "children"),
        ],
        [
            Input("lt-save-confirm-btn", "n_clicks"),
            Input("lt-save-cancel-btn", "n_clicks"),
        ],
        [
            State("lt-save-label-input", "value"),
            State("lt-results-table", "selected_rows"),
            State("lt-results-store", "data"),
            State("lt-llm-model", "value"),
            State("lt-llm-provider", "value"),
        ],
        prevent_initial_call=True,
    )
    def submit_save(confirm_clicks, cancel_clicks, label_input,
                    selected_rows, rows, model, provider):
        triggered = ctx.triggered_id
        if triggered == "lt-save-cancel-btn":
            return False, no_update
        if not confirm_clicks or not selected_rows or not rows:
            return no_update, no_update
        row = rows[selected_rows[0]]
        symbol = row.get("symbol", "")
        playbook = LONGTERM_STATE.get_playbook(symbol, model or "")
        if playbook is None:
            return False, html.Div(
                "Thesis expired from memory — re-generate before saving.",
                style={"color": "#F59E0B"},
            )
        try:
            entry = SAVED_PLAYS.save(
                symbol=symbol,
                strategy_id=LONGTERM_STRATEGY_ID,
                strategy_name=LONGTERM_STRATEGY_NAME,
                model=model or "",
                provider=provider or "",
                playbook=playbook,
                scan_row=row,
                label=(label_input or "").strip() or None,
            )
        except Exception as exc:
            logger.exception("SAVED_PLAYS.save (long-term) failed")
            return False, html.Div(f"Save failed: {exc}",
                                    style={"color": "#EF4444"})
        status = html.Div(
            [
                html.Span("bookmark_added",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle", "color": "#3B82F6"}),
                "Saved as ",
                html.Code(entry["label"],
                          style={"backgroundColor": "rgba(15,23,42,0.6)",
                                 "padding": "1px 6px", "borderRadius": "3px"}),
                ". View in the Plays tab.",
            ],
            style={"color": "#3B82F6"},
        )
        return False, status

    # ── Deep Dive ───────────────────────────────────────────────────────
    #
    # Independent of Generate Thesis: deep dive answers "why is this a good
    # candidate, what's happening with it now, what's the moat?" using a
    # web-search-backed LLM. Three callbacks:
    #   1. toggle_deep_dive_button → enable button + reveal panel on row select.
    #   2. open_deep_dive → fire trigger store on click (cheap, server-fast).
    #   3. run_deep_dive → async LLM call, reads trigger, writes markdown.
    #
    # The trigger-store split keeps the click responsive (button updates
    # immediately) while the slow LLM call runs in its own callback.

    @app.callback(
        [
            Output("lt-deep-dive-btn", "disabled"),
            Output("lt-deep-dive-wrapper", "style"),
        ],
        Input("lt-results-table", "selected_rows"),
    )
    def toggle_deep_dive_button(selected_rows):
        if not selected_rows:
            return True, {"display": "none"}
        return False, {"display": "block"}

    _dd_idle_children = [
        html.Span("search", className="material-symbols-outlined me-1",
                  style={"fontSize": "16px", "verticalAlign": "middle"}),
        "Run Deep Dive",
    ]
    _dd_busy_children = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Researching... (web search ~30–60s)",
    ]

    @app.callback(
        Output("lt-deep-dive-trigger", "data"),
        Input("lt-deep-dive-btn", "n_clicks"),
        [
            State("lt-results-table", "selected_rows"),
            State("lt-results-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def open_deep_dive(n_clicks, selected_rows, rows):
        if not n_clicks or not selected_rows or not rows:
            return no_update
        try:
            row = rows[selected_rows[0]]
        except (IndexError, KeyError):
            return no_update
        symbol = row.get("symbol")
        if not symbol:
            return no_update
        # Stamp the trigger so identical clicks always re-fire downstream.
        return {"symbol": symbol, "ts": datetime.now().isoformat()}

    @app.callback(
        Output("lt-deep-dive-output", "children"),
        Input("lt-deep-dive-trigger", "data"),
        running=[
            (Output("lt-deep-dive-btn", "disabled"), True, False),
            (Output("lt-deep-dive-btn", "children"),
             _dd_busy_children, _dd_idle_children),
        ],
        prevent_initial_call=True,
    )
    def run_deep_dive(trigger):
        if not trigger or not trigger.get("symbol"):
            return no_update
        symbol = trigger["symbol"]
        scan_result = None
        for r in LONGTERM_STATE.get_results():
            if r.snapshot.symbol == symbol:
                scan_result = r
                break
        if scan_result is None:
            return ("_Candidate no longer in latest scan — re-run scan first._")
        try:
            from tradingagents.scanner.longterm_deep_dive import generate_deep_dive
            markdown = generate_deep_dive(scan_result)
        except Exception:
            logger.exception("longterm deep-dive generation failed")
            return "_Deep dive failed. Check logs and try again._"
        if not markdown:
            return ("_Deep dive returned no content. The LLM provider may be "
                    "unavailable, or web search may be rate-limited. Try again "
                    "in a minute._")
        return markdown

    # ── Execute / Cancel / Liquidate ────────────────────────────────────
    #
    # Mirrors the day-trade scanner's flow: each action is a two-step
    # confirm-then-submit pair. Long-term plays carry bracket fields, so
    # `to_bracket_playbook()` adapts them into the day-trade `Playbook`
    # shape that `execute_playbook_paper` already understands.
    #
    # Cancel and Liquidate reuse the same `scanner:` client_order_id prefix
    # used by `submit_scanner_bracket_order`, so the existing AlpacaUtils
    # helpers (`get_unfilled_scanner_orders`, `cancel_unfilled_scanner_order`,
    # `cancel_open_orders_for_symbol`, `close_position`) work for long-term
    # plays without modification.

    _lt_exec_idle = [
        html.Span("rocket_launch", className="material-symbols-outlined me-1",
                  style={"fontSize": "18px", "verticalAlign": "middle"}),
        "Execute (Paper)",
    ]
    _lt_exec_busy = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Submitting...",
    ]

    @app.callback(
        [
            Output("lt-execute-btn", "disabled"),
            Output("lt-order-state-interval", "disabled"),
        ],
        [
            Input("lt-thesis-output", "children"),
            Input("lt-results-table", "selected_rows"),
            Input("lt-order-state", "data"),
        ],
        prevent_initial_call=True,
    )
    def toggle_lt_execute_button(thesis_children, selected_rows, order_state):
        """Enable Execute only when:
          - a row is selected, AND
          - a thesis has been generated (output is not the placeholder), AND
          - no open position and no unfilled scanner order for this symbol.
        Also enables/disables the 5s order-state interval driven by row select.
        """
        if not selected_rows:
            return True, True
        if not thesis_children or thesis_children == "No candidate selected.":
            return True, False
        if order_state and (
            int(order_state.get("unfilled_count") or 0) > 0
            or order_state.get("has_position")
        ):
            return True, False
        return False, False

    @app.callback(
        [
            Output("lt-execute-confirm-modal", "is_open"),
            Output("lt-execute-confirm-body", "children"),
            Output("lt-pending-execution", "data"),
            Output("lt-execute-status", "children", allow_duplicate=True),
        ],
        Input("lt-execute-btn", "n_clicks"),
        [
            State("lt-results-table", "selected_rows"),
            State("lt-results-store", "data"),
            State("lt-llm-model", "value"),
        ],
        prevent_initial_call=True,
    )
    def open_lt_execute_confirm(n_clicks, selected_rows, rows, model):
        if not n_clicks or not selected_rows or not rows:
            return no_update, no_update, no_update, no_update
        try:
            row = rows[selected_rows[0]]
        except (IndexError, KeyError):
            return no_update, no_update, no_update, no_update
        symbol = row.get("symbol", "")
        if not symbol:
            return no_update, no_update, no_update, no_update

        playbook = LONGTERM_STATE.get_playbook(symbol, model or "")
        if playbook is None:
            return False, no_update, None, html.Div(
                "No long-term thesis in memory. Click Generate Thesis first.",
                style={"color": "#F59E0B"},
            )

        from tradingagents.scanner.longterm_execution import is_executable
        if not is_executable(playbook):
            return False, no_update, None, html.Div(
                "Bracket levels missing on this thesis — re-generate to "
                "populate entry/stop/PT before executing.",
                style={"color": "#F59E0B"},
            )

        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            from tradingagents.scanner.execution import compute_scanner_position_size
            account = AlpacaUtils.get_account_info()
            buying_power = float(account.get("buying_power") or 0.0)
        except Exception as exc:
            logger.exception("Account lookup failed (long-term execute)")
            return False, no_update, None, html.Div(
                f"Could not read Alpaca account: {exc}",
                style={"color": "#EF4444"},
            )

        qty = compute_scanner_position_size(
            buying_power=buying_power,
            position_size_pct=playbook.position_size_pct,
            entry_price=playbook.entry_price,
        )
        if qty <= 0:
            return False, no_update, None, html.Div(
                f"Insufficient buying power for "
                f"{playbook.position_size_pct * 100:.1f}% of "
                f"${buying_power:,.2f} at ${playbook.entry_price:.2f}/share — "
                "qty rounded to 0.",
                style={"color": "#EF4444"},
            )

        est_cost = qty * playbook.entry_price
        body = html.Div([
            html.Div(f"{symbol} — Long-Term Hold",
                     style={"fontSize": "16px", "fontWeight": "700",
                            "marginBottom": "12px"}),
            html.Div([
                html.Div([html.Span("Order: ", style={"color": "#94A3B8"}),
                          html.Span(playbook.order_type,
                                    style={"fontWeight": "600",
                                           "color": "#60A5FA"})]),
                html.Div([html.Span("Quantity: ", style={"color": "#94A3B8"}),
                          html.Span(f"{qty} shares",
                                    style={"fontWeight": "600"})]),
                html.Div([html.Span("Entry: ", style={"color": "#94A3B8"}),
                          html.Span(f"${playbook.entry_price:.2f}",
                                    style={"fontWeight": "600"})]),
                html.Div([html.Span("Stop (thesis-broken): ",
                                    style={"color": "#94A3B8"}),
                          html.Span(f"${playbook.stop_loss:.2f}",
                                    style={"color": "#EF4444",
                                           "fontWeight": "600"})]),
                html.Div([html.Span("PT1 (~1y): ", style={"color": "#94A3B8"}),
                          html.Span(f"${playbook.profit_target_1:.2f}",
                                    style={"color": "#22C55E",
                                           "fontWeight": "600"})]),
                html.Div([html.Span("PT2 (3y, manual scale-out): ",
                                    style={"color": "#94A3B8"}),
                          html.Span(f"${playbook.profit_target_2:.2f}",
                                    style={"color": "#94A3B8"})]),
                html.Div([html.Span("Estimated cost: ",
                                    style={"color": "#94A3B8"}),
                          html.Span(f"${est_cost:,.2f}",
                                    style={"fontWeight": "600"})]),
                html.Div([html.Span("Buying power: ",
                                    style={"color": "#94A3B8"}),
                          html.Span(f"${buying_power:,.2f}",
                                    style={"fontWeight": "600"})]),
            ], style={"fontSize": "13px", "lineHeight": "1.8"}),
            html.Hr(),
            html.Div(
                "This is a real bracket order to Alpaca PAPER. The stop is a "
                "thesis-broken floor — for buy-and-hold names, that's typically "
                "15–25% below the entry zone. Alpaca brackets only fire one "
                "take-profit, so PT2 is logged as reference.",
                style={"fontSize": "12px", "color": "#94A3B8",
                       "fontStyle": "italic"},
            ),
        ])

        pending = {"symbol": symbol, "model": model or "", "qty": qty}
        return True, body, pending, ""

    @app.callback(
        [
            Output("lt-execute-confirm-modal", "is_open", allow_duplicate=True),
            Output("lt-execute-status", "children", allow_duplicate=True),
            Output("lt-pending-execution", "data", allow_duplicate=True),
        ],
        [
            Input("lt-execute-confirm-btn", "n_clicks"),
            Input("lt-execute-cancel-btn", "n_clicks"),
        ],
        State("lt-pending-execution", "data"),
        running=[
            (Output("lt-execute-confirm-btn", "disabled"), True, False),
            (Output("lt-execute-confirm-btn", "children"),
             _lt_exec_busy, "Confirm & Submit"),
        ],
        prevent_initial_call=True,
    )
    def submit_lt_execute(confirm_clicks, cancel_clicks, pending):
        triggered = ctx.triggered_id
        if triggered == "lt-execute-cancel-btn":
            return False, no_update, None
        if not confirm_clicks or not pending:
            return no_update, no_update, no_update

        symbol = pending.get("symbol")
        model = pending.get("model", "")
        playbook = LONGTERM_STATE.get_playbook(symbol, model)
        if playbook is None:
            return False, html.Div(
                "Thesis expired from memory — re-generate before executing.",
                style={"color": "#F59E0B"},
            ), None

        try:
            from tradingagents.scanner.execution import execute_playbook_paper
            from tradingagents.scanner.longterm_execution import to_bracket_playbook
            bracket_pb = to_bracket_playbook(playbook)
            result = execute_playbook_paper(bracket_pb)
        except Exception as exc:
            logger.exception("Long-term execute paper failed unexpectedly")
            return False, html.Div(
                f"Execution failed: {exc}", style={"color": "#EF4444"},
            ), None

        if not result.success:
            return False, html.Div(
                [
                    html.Span("error",
                              className="material-symbols-outlined me-1",
                              style={"verticalAlign": "middle",
                                     "color": "#EF4444"}),
                    f"Failed: {result.error}",
                ],
                style={"color": "#EF4444"},
            ), None

        # Best-effort attach Alpaca linkage to any saved play of this symbol
        # so cancel/liquidate from the Plays tab can find this order.
        try:
            for play in SAVED_PLAYS.list_all():
                if (play.get("symbol") == symbol
                        and play.get("strategy_id") == LONGTERM_STRATEGY_ID):
                    SAVED_PLAYS.set_linked_alpaca(play["id"], {
                        "client_order_id": result.client_order_id,
                        "alpaca_order_id": result.alpaca_order_id,
                    })
                    break
        except Exception as exc:
            logger.debug("set_linked_alpaca (long-term) skipped: %s", exc)

        status = html.Div(
            [
                html.Span("check_circle",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle", "color": "#22C55E"}),
                f"Submitted {result.qty} shares — Alpaca id ",
                html.Code(result.alpaca_order_id or "?",
                          style={"backgroundColor": "rgba(15,23,42,0.6)",
                                 "padding": "1px 6px",
                                 "borderRadius": "3px"}),
                " · tag ",
                html.Code(result.client_order_id or "?",
                          style={"backgroundColor": "rgba(15,23,42,0.6)",
                                 "padding": "1px 6px",
                                 "borderRadius": "3px"}),
                ".",
            ],
            style={"color": "#22C55E"},
        )
        return False, status, None

    # ── Liquidate ─────────────────────────────────────────────────────

    @app.callback(
        Output("lt-liquidate-btn", "disabled"),
        [
            Input("lt-results-table", "selected_rows"),
            Input("lt-order-state", "data"),
        ],
        prevent_initial_call=True,
    )
    def toggle_lt_liquidate_button(selected_rows, order_state):
        if not selected_rows:
            return True
        if not order_state or not order_state.get("has_position"):
            return True
        return False

    @app.callback(
        [
            Output("lt-liquidate-confirm-modal", "is_open"),
            Output("lt-liquidate-confirm-body", "children"),
            Output("lt-execute-status", "children", allow_duplicate=True),
        ],
        Input("lt-liquidate-btn", "n_clicks"),
        [
            State("lt-results-table", "selected_rows"),
            State("lt-results-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def open_lt_liquidate_confirm(n_clicks, selected_rows, rows):
        if not n_clicks or not selected_rows or not rows:
            return no_update, no_update, no_update

        symbol = rows[selected_rows[0]].get("symbol", "")
        if not symbol:
            return no_update, no_update, no_update

        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            position = AlpacaUtils.get_position_with_brackets(symbol)
        except Exception as exc:
            logger.exception("Position lookup failed (lt liquidate)")
            return False, no_update, html.Div(
                f"Could not read position: {exc}", style={"color": "#EF4444"},
            )

        if not position:
            return False, no_update, html.Div(
                f"No open position for {symbol}.", style={"color": "#F59E0B"},
            )

        qty = float(position.get("qty") or 0.0)
        avg = float(position.get("avg_entry_price") or 0.0)
        cur = float(position.get("current_price") or 0.0)
        pl = float(position.get("unrealized_pl") or 0.0)
        plpc = float(position.get("unrealized_plpc") or 0.0) * 100.0
        side = (position.get("side") or "long").upper()
        pl_color = "#22C55E" if pl >= 0 else "#EF4444"
        sign = "+" if pl >= 0 else ""

        body = html.Div([
            html.Div(
                f"This will market-close your {side} position in {symbol} and "
                "cancel any open bracket legs (stop / take-profit).",
                style={"marginBottom": "14px", "color": "#CBD5E1",
                       "fontSize": "13px"},
            ),
            html.Div([
                html.Div([html.Div("SYMBOL", className="pb-label"),
                          html.Div(symbol, className="pb-value")],
                         className="pb-row"),
                html.Div([html.Div("QTY", className="pb-label"),
                          html.Div(f"{qty:g} ({side})",
                                   className="pb-value")],
                         className="pb-row"),
                html.Div([html.Div("AVG ENTRY", className="pb-label"),
                          html.Div(f"${avg:,.2f}",
                                   className="pb-value")],
                         className="pb-row"),
                html.Div([html.Div("CURRENT", className="pb-label"),
                          html.Div(f"${cur:,.2f}",
                                   className="pb-value")],
                         className="pb-row"),
                html.Div([html.Div("UNREALIZED P/L", className="pb-label"),
                          html.Div(f"{sign}${pl:,.2f} ({sign}{plpc:.2f}%)",
                                   className="pb-value",
                                   style={"color": pl_color,
                                          "fontWeight": "700"})],
                         className="pb-row"),
            ], style={"display": "grid",
                      "gridTemplateColumns": "repeat(2, 1fr)",
                      "gap": "10px"}),
        ])
        return True, body, no_update

    @app.callback(
        [
            Output("lt-liquidate-confirm-modal", "is_open", allow_duplicate=True),
            Output("lt-execute-status", "children", allow_duplicate=True),
        ],
        [
            Input("lt-liquidate-confirm-btn", "n_clicks"),
            Input("lt-liquidate-cancel-btn", "n_clicks"),
        ],
        [
            State("lt-results-table", "selected_rows"),
            State("lt-results-store", "data"),
        ],
        running=[
            (Output("lt-liquidate-confirm-btn", "disabled"), True, False),
            (Output("lt-liquidate-confirm-btn", "children"),
             "Liquidating…", "Confirm & Liquidate"),
        ],
        prevent_initial_call=True,
    )
    def submit_lt_liquidate(confirm_clicks, cancel_clicks, selected_rows, rows):
        triggered = ctx.triggered_id
        if triggered == "lt-liquidate-cancel-btn":
            return False, no_update
        if not confirm_clicks or not selected_rows or not rows:
            return no_update, no_update

        symbol = rows[selected_rows[0]].get("symbol", "")
        if not symbol:
            return False, no_update

        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        try:
            cancel_result = AlpacaUtils.cancel_open_orders_for_symbol(symbol)
        except Exception as exc:
            logger.exception("cancel_open_orders_for_symbol failed (lt)")
            return False, html.Div(
                f"Failed to cancel open orders for {symbol}: {exc}",
                style={"color": "#EF4444"},
            )

        try:
            close_result = AlpacaUtils.close_position(symbol)
        except Exception as exc:
            logger.exception("close_position failed (lt)")
            return False, html.Div(
                f"Failed to close position: {exc}",
                style={"color": "#EF4444"},
            )

        if not close_result.get("success"):
            err = close_result.get("error") or "unknown error"
            return False, html.Div(
                f"Liquidation failed: {err}",
                style={"color": "#EF4444"},
            )

        cancelled_n = (cancel_result.get("cancelled_count")
                       if isinstance(cancel_result, dict) else None)
        cancelled_str = (f" · cancelled {cancelled_n} bracket leg(s)"
                         if cancelled_n else "")
        status = html.Div(
            [
                html.Span("check_circle",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle",
                                 "color": "#22C55E"}),
                f"Liquidated {symbol}: market-close submitted (Alpaca id ",
                html.Code(str(close_result.get("order_id") or "?"),
                          style={"backgroundColor": "rgba(15,23,42,0.6)",
                                 "padding": "1px 6px",
                                 "borderRadius": "3px"}),
                f"){cancelled_str}.",
            ],
            style={"color": "#22C55E"},
        )
        return False, status

    # ── Cancel pending order ──────────────────────────────────────────

    @app.callback(
        Output("lt-cancel-order-btn", "disabled"),
        [
            Input("lt-order-state", "data"),
            Input("lt-results-table", "selected_rows"),
        ],
        prevent_initial_call=True,
    )
    def toggle_lt_cancel_order_button(order_state, selected_rows):
        if not selected_rows:
            return True
        if not order_state:
            return True
        return int(order_state.get("unfilled_count") or 0) <= 0

    @app.callback(
        [
            Output("lt-cancel-order-confirm-modal", "is_open"),
            Output("lt-cancel-order-confirm-body", "children"),
            Output("lt-execute-status", "children", allow_duplicate=True),
        ],
        Input("lt-cancel-order-btn", "n_clicks"),
        [
            State("lt-results-table", "selected_rows"),
            State("lt-results-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def open_lt_cancel_order_confirm(n_clicks, selected_rows, rows):
        if not n_clicks or not selected_rows or not rows:
            return no_update, no_update, no_update

        symbol = rows[selected_rows[0]].get("symbol", "")
        if not symbol:
            return no_update, no_update, no_update

        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            unfilled = AlpacaUtils.get_unfilled_scanner_orders(symbol)
        except Exception as exc:
            logger.exception("get_unfilled_scanner_orders failed (lt)")
            return False, no_update, html.Div(
                f"Could not read pending orders: {exc}",
                style={"color": "#EF4444"},
            )

        if not unfilled:
            return False, no_update, html.Div(
                f"No pending scanner order for {symbol}.",
                style={"color": "#F59E0B"},
            )

        rows_ui = []
        for o in unfilled:
            limit_str = (f"${o['limit_price']:,.2f}"
                         if o.get("limit_price") is not None else "—")
            stop_str = (f"${o['stop_price']:,.2f}"
                        if o.get("stop_price") is not None else "—")
            rows_ui.append(html.Div([
                html.Div([html.Div("ORDER ID", className="pb-label"),
                          html.Div(o["id"][:8] + "…",
                                   className="pb-value")],
                         className="pb-row"),
                html.Div([html.Div("SIDE / QTY", className="pb-label"),
                          html.Div(f"{o['side'].upper()} {o['qty']:g}",
                                   className="pb-value")],
                         className="pb-row"),
                html.Div([html.Div("TYPE", className="pb-label"),
                          html.Div(o.get("order_type", "") or "—",
                                   className="pb-value")],
                         className="pb-row"),
                html.Div([html.Div("LIMIT / STOP", className="pb-label"),
                          html.Div(f"{limit_str} / {stop_str}",
                                   className="pb-value")],
                         className="pb-row"),
                html.Div([html.Div("STATUS", className="pb-label"),
                          html.Div(o["status"], className="pb-value",
                                   style={"color": "#F59E0B",
                                          "fontWeight": "700"})],
                         className="pb-row"),
            ], style={"display": "grid",
                      "gridTemplateColumns": "repeat(auto-fit, minmax(120px, 1fr))",
                      "gap": "10px",
                      "padding": "10px",
                      "marginBottom": "8px",
                      "backgroundColor": "rgba(15, 23, 42, 0.6)",
                      "borderRadius": "6px"}))

        body = html.Div([
            html.Div(
                f"Cancel {len(unfilled)} pending order(s) for {symbol}? "
                "Bracket children (TP/SL) auto-cancel when the parent does.",
                style={"marginBottom": "14px", "color": "#CBD5E1",
                       "fontSize": "13px"},
            ),
            *rows_ui,
        ])
        return True, body, no_update

    @app.callback(
        [
            Output("lt-cancel-order-confirm-modal", "is_open", allow_duplicate=True),
            Output("lt-execute-status", "children", allow_duplicate=True),
        ],
        [
            Input("lt-cancel-order-confirm-btn", "n_clicks"),
            Input("lt-cancel-order-keep-btn", "n_clicks"),
        ],
        [
            State("lt-results-table", "selected_rows"),
            State("lt-results-store", "data"),
        ],
        running=[
            (Output("lt-cancel-order-confirm-btn", "disabled"), True, False),
            (Output("lt-cancel-order-confirm-btn", "children"),
             "Cancelling…", "Confirm & Cancel"),
        ],
        prevent_initial_call=True,
    )
    def submit_lt_cancel_order(confirm_clicks, keep_clicks, selected_rows, rows):
        triggered = ctx.triggered_id
        if triggered == "lt-cancel-order-keep-btn":
            return False, no_update
        if not confirm_clicks or not selected_rows or not rows:
            return no_update, no_update

        symbol = rows[selected_rows[0]].get("symbol", "")
        if not symbol:
            return False, no_update

        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            result = AlpacaUtils.cancel_unfilled_scanner_order(symbol)
        except Exception as exc:
            logger.exception("cancel_unfilled_scanner_order failed (lt)")
            return False, html.Div(
                f"Cancel failed: {exc}", style={"color": "#EF4444"},
            )

        cancelled_n = int(result.get("cancelled") or 0)
        failed_n = int(result.get("failed") or 0)

        if cancelled_n == 0 and failed_n == 0:
            return False, html.Div(
                f"No pending scanner order found for {symbol} — already filled "
                "or cancelled.",
                style={"color": "#94A3B8"},
            )

        if not result.get("success"):
            errs = "; ".join(result.get("errors") or []) or "unknown error"
            return False, html.Div(
                f"Cancel partial failure: {cancelled_n} cancelled, "
                f"{failed_n} failed. {errs}",
                style={"color": "#EF4444"},
            )

        status = html.Div(
            [
                html.Span("check_circle",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle",
                                 "color": "#22C55E"}),
                f"Cancelled {cancelled_n} pending order(s) for {symbol}. "
                "Bracket children auto-cancelled.",
            ],
            style={"color": "#22C55E"},
        )
        return False, status

    # ── 5s order-state poll ───────────────────────────────────────────
    #
    # While a row is selected, poll Alpaca every 5s for unfilled scanner
    # orders + open position on the symbol. Drives Cancel/Liquidate enable
    # state. Same call volume as the day-trade tab; no rate-limit risk.

    @app.callback(
        Output("lt-order-state", "data"),
        [
            Input("lt-order-state-interval", "n_intervals"),
            Input("lt-results-table", "selected_rows"),
        ],
        State("lt-results-store", "data"),
        prevent_initial_call=True,
    )
    def update_lt_order_state(_n, selected_rows, rows):
        empty = {"unfilled_count": 0, "has_position": False}
        if not selected_rows or not rows:
            return empty
        try:
            row = rows[selected_rows[0]]
        except (IndexError, KeyError):
            return empty
        symbol = row.get("symbol", "")
        if not symbol:
            return empty

        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            unfilled = AlpacaUtils.get_unfilled_scanner_orders(symbol) or []
            position = AlpacaUtils.get_position_with_brackets(symbol)
        except Exception as exc:
            logger.debug("lt order-state poll failed for %s: %s", symbol, exc)
            return empty

        return {
            "unfilled_count": len(unfilled),
            "has_position": bool(position),
        }

    # ── Chart panel: build payload + clientside render ──────────────────

    @app.callback(
        [
            Output("lt-chart-payload", "data"),
            Output("lt-chart-wrapper", "style"),
        ],
        [
            Input("lt-thesis-output", "children"),
            Input("lt-chart-timeframe", "value"),
        ],
        [
            State("lt-results-table", "selected_rows"),
            State("lt-results-store", "data"),
            State("lt-llm-model", "value"),
        ],
        prevent_initial_call=True,
    )
    def render_lt_chart(_thesis_children, timeframe, selected_rows, rows, model):
        """Build the LWC payload after a thesis renders or the timeframe changes."""
        hidden = {"display": "none"}
        if not selected_rows or not rows:
            return no_update, hidden

        try:
            row = rows[selected_rows[0]]
        except (IndexError, KeyError):
            return no_update, hidden

        symbol = row.get("symbol")
        if not symbol:
            return no_update, hidden

        playbook = LONGTERM_STATE.get_playbook(symbol, model or "")
        if playbook is None:
            return no_update, hidden

        overlay_levels = {
            "entry": playbook.entry_zone_low,
            "pt1": playbook.entry_zone_high,
            "pt2": playbook.target_price_3y,
        }

        try:
            from webui.utils.charts_lwc import build_lwc_payload
            payload = build_lwc_payload(
                symbol,
                period=timeframe or "1y",
                overlay_levels=overlay_levels,
                position_levels=None,
                fills=[],
            )
        except Exception:
            logger.exception("build_lwc_payload failed for %s (long-term)", symbol)
            return no_update, hidden

        return payload, {"display": "block"}

    app.clientside_callback(
        """
        function(payload) {
            if (payload && window.lwcRender) {
                window.lwcRender('lt-chart', payload);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("lt-chart", "data-lwc-rendered"),
        Input("lt-chart-payload", "data"),
    )

    # ── Catalyst modal — open on click of the Catalyst column ───────────

    @app.callback(
        [
            Output("lt-catalyst-modal", "is_open"),
            Output("lt-catalyst-modal-title", "children"),
            Output("lt-catalyst-modal-body", "children"),
            Output("lt-catalyst-explainer-output", "children"),
            Output("lt-catalyst-explain-trigger", "data"),
            Output("lt-results-table", "active_cell"),
        ],
        Input("lt-results-table", "active_cell"),
        [
            State("lt-results-store", "data"),
            State("lt-llm-provider", "value"),
            State("lt-llm-model", "value"),
        ],
        prevent_initial_call=True,
    )
    def open_lt_catalyst_modal(active_cell, rows, provider, model):
        if not active_cell or active_cell.get("column_id") != "catalyst":
            return (no_update, no_update, no_update, no_update,
                    no_update, no_update)
        row_idx = active_cell.get("row")
        if row_idx is None or rows is None or row_idx >= len(rows):
            return (no_update, no_update, no_update, no_update,
                    no_update, no_update)
        row = rows[row_idx]
        catalyst_label = row.get("catalyst", "")
        if not catalyst_label or catalyst_label == "—":
            return (no_update, no_update, no_update, no_update,
                    no_update, None)

        details = (row.get("catalyst_details") or "").strip()
        if not details:
            details = (
                f"**{catalyst_label}**\n\n"
                "_No extended details available. Re-run the scan to refresh — "
                "older scan results were cached before expanded catalyst "
                "information was added._"
            )
        title = f"{row.get('symbol', '')} · {catalyst_label}"
        symbol = row.get("symbol", "")
        category = row.get("catalyst_category") or ""
        trigger = {
            "symbol": symbol,
            "category": category,
            "short_text": catalyst_label,
            "structured_md": details,
            "raw_items": row.get("catalyst_raw") or [],
            "provider": provider or "openai",
            "model": model or "",
        } if category else None
        return (True, title, details,
                "_Searching the web for context…_", trigger, None)

    @app.callback(
        Output("lt-catalyst-explainer-output", "children",
               allow_duplicate=True),
        Input("lt-catalyst-explain-trigger", "data"),
        prevent_initial_call=True,
    )
    def run_lt_catalyst_explainer(trigger):
        if not trigger or not trigger.get("category"):
            return no_update
        from tradingagents.scanner.catalyst_explainer import explain_catalyst
        from tradingagents.scanner.models import CatalystFacts

        facts = CatalystFacts(
            has_catalyst=True,
            category=trigger.get("category"),
            short_text=trigger.get("short_text"),
            structured_md=trigger.get("structured_md"),
            raw_items=tuple(trigger.get("raw_items") or ()),
        )
        try:
            narrative = explain_catalyst(trigger.get("symbol", ""), facts)
        except Exception as exc:
            logger.exception("explain_catalyst failed (long-term)")
            return f"_Deep-dive unavailable: {exc}_"
        if not narrative:
            return "_Deep-dive unavailable for this catalyst._"
        return narrative

    # ── Export Tickers ──────────────────────────────────────────────────
    # Enable the button when there are ranked candidates; clicking opens a
    # modal with a comma-separated list ready to paste into the Analysis
    # section's watchlist.

    @app.callback(
        Output("lt-export-btn", "disabled"),
        Input("lt-results-store", "data"),
    )
    def toggle_lt_export_button(rows):
        return not bool(rows)

    @app.callback(
        [
            Output("lt-export-modal", "is_open"),
            Output("lt-export-textarea", "value"),
            Output("lt-export-count", "children"),
        ],
        [
            Input("lt-export-btn", "n_clicks"),
            Input("lt-export-close-btn", "n_clicks"),
        ],
        State("lt-results-store", "data"),
        prevent_initial_call=True,
    )
    def open_lt_export_modal(open_clicks, close_clicks, rows):
        triggered = ctx.triggered_id
        if triggered == "lt-export-close-btn":
            return False, no_update, no_update
        if not rows:
            return False, "", ""
        symbols = [str(r.get("symbol", "")).strip().upper()
                   for r in rows if r.get("symbol")]
        symbols = [s for s in symbols if s]
        text = ", ".join(symbols)
        count = f"{len(symbols)} ticker{'s' if len(symbols) != 1 else ''}"
        return True, text, count

    # Clientside copy-to-clipboard. Falls back gracefully when the Clipboard
    # API is unavailable (older browsers, non-secure contexts) by select+execCommand.
    app.clientside_callback(
        """
        function(n_clicks, value) {
            if (!n_clicks || !value) {
                return window.dash_clientside.no_update;
            }
            try {
                if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(value);
                } else {
                    const ta = document.getElementById('lt-export-textarea');
                    if (ta) { ta.select(); document.execCommand('copy'); }
                }
            } catch (e) { /* swallow */ }
            return window.dash_clientside.no_update;
        }
        """,
        Output("lt-export-copy-btn", "data-copied"),
        Input("lt-export-copy-btn", "n_clicks"),
        State("lt-export-textarea", "value"),
        prevent_initial_call=True,
    )
