"""webui/callbacks/scanner_callbacks.py - Callbacks for the Trading tab.

Handles:
- "Run Scan" click → runs ScannerPipeline → updates the results table + stats.
- Row selection → enables the Generate Playbook button.
- "Generate Playbook" click → calls playbook_llm → renders a structured plan.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from dash import Input, Output, State, html, no_update

from tradingagents.scanner.models import ScanFilters
from tradingagents.scanner.pipeline import ScannerPipeline
from webui.components.scanner_page import PLAYBOOK_MODEL_OPTIONS
from webui.utils.saved_plays import SAVED_PLAYS
from webui.utils.scanner_state import SCANNER_STATE

logger = logging.getLogger(__name__)

# Cache categories cleared when "Force Refresh" is toggled on.
# Float is excluded — share counts don't change intraday and Finnhub free-tier
# rate limits punish us if we re-fetch them every scan.
_FORCE_REFRESH_CATEGORIES = (
    "scanner_daily_metrics",
    "scanner_intraday",
    "scanner_levels",
    "scanner_catalyst",
    "scanner_press_releases",
    "scanner_filings",
    "scanner_insider",
    "scanner_corp_actions",
)


def _clear_scanner_caches() -> None:
    """Clear all scanner cache categories so the next scan re-fetches live data."""
    from tradingagents.dataflows.cache_utils import clear_cache
    for category in _FORCE_REFRESH_CATEGORIES:
        try:
            clear_cache(cache_category=category)
        except Exception as exc:
            logger.debug("clear_cache(%s) failed: %s", category, exc)


def _parse_watchlist(raw: Optional[str]) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


def _build_filters(
    universe: str,
    min_rvol: Optional[float],
    price_min: Optional[float],
    price_max: Optional[float],
    max_float: Optional[float],
    catalyst_only: Optional[list],
    watchlist_raw: Optional[str],
) -> ScanFilters:
    return ScanFilters(
        universe_kind=universe or "most_active",
        watchlist=_parse_watchlist(watchlist_raw),
        min_rvol=float(min_rvol or 2.0),
        price_min=float(price_min or 0.0),
        price_max=float(price_max or 1_000_000.0),
        max_float_millions=float(max_float) if max_float else None,
        catalyst_only=bool(catalyst_only),
        asset_class="crypto" if universe == "crypto" else "stock",
    )


def _results_to_rows(results) -> list[dict]:
    rows = []
    for r in results:
        s = r.snapshot
        rows.append({
            "symbol": s.symbol,
            "last_price": s.last_price,
            "change_pct": s.change_pct,
            "rvol": s.rvol,
            "today_volume": s.today_volume,
            "float_shares": s.float_shares,
            "catalyst": s.catalyst_text if s.has_catalyst else "—",
            "catalyst_details": s.catalyst_details or "",
            "catalyst_category": s.catalyst_category or "",
            "catalyst_raw": list(s.catalyst_raw or ()),
            "strategy_id": r.strategy_id,
            "strategy_name": r.strategy_name,
            "score": r.score,
        })
    return rows


def _format_position_status(position: Optional[dict]):
    """Render the open-position P/L line above the chart."""
    if not position:
        return html.Span(
            "No open position for this symbol.",
            style={"color": "#64748B", "fontStyle": "italic"},
        )

    pl = float(position.get("unrealized_pl") or 0.0)
    plpc = float(position.get("unrealized_plpc") or 0.0) * 100.0
    qty = float(position.get("qty") or 0.0)
    avg = float(position.get("avg_entry_price") or 0.0)
    cur = float(position.get("current_price") or 0.0)
    side = (position.get("side") or "long").upper()
    sl = position.get("stop_loss")
    tp = position.get("take_profit")
    color = "#22C55E" if pl >= 0 else "#EF4444"
    sign = "+" if pl >= 0 else ""

    bracket_text = []
    if tp is not None:
        bracket_text.append(f"TP ${float(tp):,.2f}")
    if sl is not None:
        bracket_text.append(f"SL ${float(sl):,.2f}")
    bracket_str = " · " + " · ".join(bracket_text) if bracket_text else ""

    return html.Div([
        html.Span(f"OPEN {side} ", style={"fontWeight": "700", "color": "#F1F5F9"}),
        html.Span(f"{qty:g} @ ${avg:,.2f}",
                  style={"color": "#CBD5E1", "marginRight": "10px"}),
        html.Span(f"now ${cur:,.2f}",
                  style={"color": "#94A3B8", "marginRight": "10px"}),
        html.Span(f"{sign}${pl:,.2f} ({sign}{plpc:.2f}%)",
                  style={"color": color, "fontWeight": "700"}),
        html.Span(bracket_str, style={"color": "#94A3B8", "marginLeft": "6px"}),
    ])


def _format_playbook(playbook) -> html.Div:
    qualification = (getattr(playbook, "qualification_reason", "") or "").strip()
    confidence_reason = (getattr(playbook, "confidence_reason", "") or "").strip()
    return html.Div([
        html.Div(
            playbook.thesis,
            style={"fontSize": "14px", "color": "#F1F5F9", "marginBottom": "16px",
                   "lineHeight": "1.5"},
        ),
        html.Div(
            [
                html.Div("WHY THIS STRATEGY", className="pb-label"),
                html.Div(qualification,
                         style={"fontSize": "13px", "color": "#CBD5E1",
                                "lineHeight": "1.5"}),
            ],
            style={
                "marginBottom": "16px",
                "padding": "12px 14px",
                "borderLeft": "3px solid #3B82F6",
                "backgroundColor": "rgba(59, 130, 246, 0.08)",
                "borderRadius": "0 6px 6px 0",
            },
        ) if qualification else None,
        html.Div([
            html.Div([
                html.Div("ORDER TYPE", className="pb-label"),
                html.Div(playbook.order_type,
                         className="pb-value",
                         style={"fontWeight": "700", "color": "#60A5FA"}),
            ], className="pb-row"),
            html.Div([
                html.Div("ENTRY", className="pb-label"),
                html.Div([
                    html.Div(f"${playbook.entry_price:,.2f}",
                             className="pb-value",
                             style={"fontWeight": "700"}),
                    html.Div(playbook.entry_trigger,
                             style={"fontSize": "12px", "color": "#94A3B8",
                                    "marginTop": "4px", "lineHeight": "1.4"}),
                ]),
            ], className="pb-row"),
            html.Div([
                html.Div("STOP", className="pb-label"),
                html.Div(f"${playbook.stop_loss:,.2f}", className="pb-value"),
            ], className="pb-row"),
            html.Div([
                html.Div("PT1 / PT2", className="pb-label"),
                html.Div(
                    f"${playbook.profit_target_1:,.2f} / ${playbook.profit_target_2:,.2f}",
                    className="pb-value",
                ),
            ], className="pb-row"),
            html.Div([
                html.Div("R:R", className="pb-label"),
                html.Div(f"{playbook.risk_reward:,.2f}", className="pb-value"),
            ], className="pb-row"),
            html.Div([
                html.Div("SIZE", className="pb-label"),
                html.Div(f"{playbook.position_size_pct * 100:,.1f}% of BP",
                         className="pb-value"),
            ], className="pb-row"),
            html.Div([
                html.Div("CONFIDENCE", className="pb-label"),
                html.Div([
                    html.Div(playbook.confidence.upper(),
                             className="pb-value",
                             style={
                                 "color": {"high": "#22C55E", "medium": "#F59E0B",
                                           "low": "#EF4444"}.get(playbook.confidence, "#94A3B8"),
                                 "fontWeight": "700",
                             }),
                    html.Div(confidence_reason,
                             style={"fontSize": "12px", "color": "#94A3B8",
                                    "marginTop": "4px", "lineHeight": "1.4",
                                    "fontStyle": "italic"}),
                ] if confidence_reason else [
                    html.Div(playbook.confidence.upper(),
                             className="pb-value",
                             style={
                                 "color": {"high": "#22C55E", "medium": "#F59E0B",
                                           "low": "#EF4444"}.get(playbook.confidence, "#94A3B8"),
                             }),
                ]),
            ], className="pb-row"),
        ], style={
            "display": "grid",
            "gridTemplateColumns": "repeat(auto-fit, minmax(180px, 1fr))",
            "gap": "12px",
            "padding": "12px",
            "backgroundColor": "rgba(15, 23, 42, 0.6)",
            "borderRadius": "8px",
            "marginBottom": "12px",
        }),
        html.Div([
            html.Div("WATCH", className="pb-label"),
            html.Div(", ".join(playbook.indicators_to_watch) or "—",
                     style={"fontSize": "13px", "color": "#94A3B8"}),
        ], style={"marginBottom": "8px"}),
        html.Div([
            html.Div("INVALIDATION", className="pb-label"),
            html.Div(playbook.invalidation, style={"fontSize": "13px", "color": "#94A3B8"}),
        ]),
    ])


def register_scanner_callbacks(app):
    """Register the Trading (scanner) tab callbacks."""

    _run_idle_children = [
        html.Span("play_arrow", className="material-symbols-outlined me-1",
                  style={"fontSize": "18px", "verticalAlign": "middle"}),
        "Run Scan",
    ]
    _run_busy_children = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Running Scan...",
    ]

    @app.callback(
        [
            Output("scanner-results-table", "data"),
            Output("scanner-stats", "children"),
            Output("scanner-results-store", "data"),
            Output("scanner-results-table", "selected_rows"),
        ],
        Input("scanner-run-btn", "n_clicks"),
        [
            State("scanner-universe", "value"),
            State("scanner-min-rvol", "value"),
            State("scanner-price-min", "value"),
            State("scanner-price-max", "value"),
            State("scanner-max-float", "value"),
            State("scanner-catalyst-only", "value"),
            State("scanner-watchlist", "value"),
            State("scanner-force-refresh", "value"),
        ],
        running=[
            (Output("scanner-run-btn", "disabled"), True, False),
            (Output("scanner-run-btn", "color"), "danger", "primary"),
            (Output("scanner-run-btn", "children"), _run_busy_children, _run_idle_children),
        ],
        prevent_initial_call=True,
    )
    def run_scan(n_clicks, universe, min_rvol, price_min, price_max,
                 max_float, catalyst_only, watchlist_raw, force_refresh):
        if not n_clicks:
            return no_update, no_update, no_update, no_update

        filters = _build_filters(
            universe, min_rvol, price_min, price_max,
            max_float, catalyst_only, watchlist_raw,
        )

        if force_refresh:
            logger.info("Force Refresh enabled — clearing scanner caches")
            _clear_scanner_caches()

        # Lazy import so failures fetching Alpaca credentials don't break page load.
        try:
            from tradingagents.scanner.data_provider import AlpacaDataProvider
            provider = AlpacaDataProvider()
            pipeline = ScannerPipeline(provider)
            results = pipeline.run(filters)
        except Exception as exc:
            logger.exception("Scan failed")
            return (
                [],
                f"Scan failed: {exc}",
                [],
                [],
            )

        SCANNER_STATE.set_results(results)

        rows = _results_to_rows(results)
        # DataTable can only render scalar columns; raw_items lives in the store.
        table_rows = [{k: v for k, v in r.items() if k != "catalyst_raw"} for r in rows]
        universe_size = len(filters.watchlist) if filters.universe_kind == "watchlist" else None
        now = datetime.now().strftime("%H:%M:%S")
        summary = (
            f"Filters: universe={filters.universe_kind}, rvol≥{filters.min_rvol}, "
            f"price ${filters.price_min:,.2f}–${filters.price_max:,.2f} · "
            f"Qualifying: {len(rows)} · Last scan: {now}"
        )
        if universe_size is not None:
            summary = f"Universe: {universe_size} → {summary}"

        if len(rows) == 0:
            stats = html.Div([
                html.Div(summary, style={"fontSize": "12px", "color": "#94A3B8",
                                         "marginBottom": "8px"}),
                html.Div(
                    "No tickers passed the filters. Try lowering min RVOL, widening the "
                    "price band, or switching universe.",
                    style={
                        "padding": "12px",
                        "border": "1px solid #F59E0B",
                        "borderRadius": "6px",
                        "backgroundColor": "rgba(245, 158, 11, 0.1)",
                        "color": "#F59E0B",
                        "fontSize": "13px",
                    },
                ),
            ])
        else:
            stats = html.Div(summary, style={"fontSize": "12px", "color": "#94A3B8"})
        return table_rows, stats, rows, []

    @app.callback(
        Output("scanner-playbook-btn", "disabled"),
        Input("scanner-results-table", "selected_rows"),
        prevent_initial_call=True,
    )
    def toggle_playbook_button(selected_rows):
        return not selected_rows

    @app.callback(
        [
            Output("scanner-catalyst-modal", "is_open"),
            Output("scanner-catalyst-modal-title", "children"),
            Output("scanner-catalyst-modal-body", "children"),
            Output("scanner-catalyst-explainer-output", "children"),
            Output("scanner-catalyst-explain-trigger", "data"),
            Output("scanner-results-table", "active_cell"),
        ],
        Input("scanner-results-table", "active_cell"),
        [
            State("scanner-results-store", "data"),
            State("scanner-llm-provider", "value"),
            State("scanner-llm-model", "value"),
        ],
        prevent_initial_call=True,
    )
    def open_catalyst_modal(active_cell, rows, provider, model):
        if not active_cell or active_cell.get("column_id") != "catalyst":
            return (no_update, no_update, no_update, no_update, no_update, no_update)
        row_idx = active_cell.get("row")
        if row_idx is None or rows is None or row_idx >= len(rows):
            return (no_update, no_update, no_update, no_update, no_update, no_update)
        row = rows[row_idx]
        catalyst_label = row.get("catalyst", "")
        if not catalyst_label or catalyst_label == "—":
            return (no_update, no_update, no_update, no_update, no_update, None)

        details = (row.get("catalyst_details") or "").strip()
        if not details:
            details = (
                f"**{catalyst_label}**\n\n"
                "_No extended details available. Re-run the scan to refresh — "
                "older scan results were cached before expanded catalyst "
                "information was added._"
            )
        title = f"{row.get('symbol', '')} · {catalyst_label}"
        # Clear stale explainer text + fire async trigger with the row payload.
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
        return True, title, details, "_Searching the web for context…_", trigger, None

    @app.callback(
        Output("scanner-catalyst-explainer-output", "children", allow_duplicate=True),
        Input("scanner-catalyst-explain-trigger", "data"),
        prevent_initial_call=True,
    )
    def run_catalyst_explainer(trigger):
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
            # Explainer pins its own provider/model (Anthropic Sonnet) for the
            # best web-search citations — independent of playbook dropdown.
            narrative = explain_catalyst(trigger.get("symbol", ""), facts)
        except Exception as exc:
            logger.exception("explain_catalyst failed")
            return f"_Deep-dive unavailable: {exc}_"
        if not narrative:
            return "_Deep-dive unavailable for this catalyst._"
        return narrative

    _pb_idle_children = [
        html.Span("auto_awesome", className="material-symbols-outlined me-1",
                  style={"fontSize": "18px", "verticalAlign": "middle"}),
        "Generate Playbook",
    ]
    _pb_busy_children = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Generating...",
    ]

    @app.callback(
        [
            Output("scanner-llm-model", "options"),
            Output("scanner-llm-model", "value"),
        ],
        Input("scanner-llm-provider", "value"),
        prevent_initial_call=True,
    )
    def update_model_options(provider):
        opts = PLAYBOOK_MODEL_OPTIONS.get(provider or "openai", [])
        default_value = opts[0]["value"] if opts else None
        return opts, default_value

    @app.callback(
        Output("scanner-playbook-output", "children"),
        Input("scanner-playbook-btn", "n_clicks"),
        [
            State("scanner-results-table", "selected_rows"),
            State("scanner-results-store", "data"),
            State("scanner-llm-provider", "value"),
            State("scanner-llm-model", "value"),
        ],
        running=[
            (Output("scanner-playbook-btn", "disabled"), True, False),
            (Output("scanner-playbook-btn", "color"), "danger", "secondary"),
            (Output("scanner-playbook-btn", "children"), _pb_busy_children, _pb_idle_children),
        ],
        prevent_initial_call=True,
    )
    def generate_playbook(n_clicks, selected_rows, rows, provider, model):
        if not n_clicks or not selected_rows or not rows:
            return no_update

        row = rows[selected_rows[0]]
        symbol = row["symbol"]
        strategy_id = row["strategy_id"]

        # Pull the matching ScanResult out of state
        scan_result = None
        for r in SCANNER_STATE.get_results():
            if r.snapshot.symbol == symbol and r.strategy_id == strategy_id:
                scan_result = r
                break
        if scan_result is None:
            return html.Div("Ticker no longer in latest scan. Re-run scan.",
                            style={"color": "#F59E0B"})

        # Model included in cache key so switching LLMs re-generates.
        cached = SCANNER_STATE.get_playbook(symbol, strategy_id, model or "")
        if cached is not None:
            return _format_playbook(cached)

        try:
            from tradingagents.scanner.playbook_llm import generate_playbook as llm_generate
            playbook = llm_generate(scan_result, provider=provider, model=model)
        except Exception as exc:
            logger.exception("Playbook generation failed")
            return html.Div(f"Playbook generation failed: {exc}",
                            style={"color": "#EF4444"})

        SCANNER_STATE.set_playbook(symbol, strategy_id, playbook, model or "")
        return _format_playbook(playbook)

    # ── Execute (Paper) flow ──────────────────────────────────────────

    _exec_idle_children = [
        html.Span("rocket_launch", className="material-symbols-outlined me-1",
                  style={"fontSize": "18px", "verticalAlign": "middle"}),
        "Execute (Paper)",
    ]
    _exec_busy_children = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Submitting...",
    ]

    @app.callback(
        Output("scanner-execute-btn", "disabled"),
        [
            Input("scanner-playbook-output", "children"),
            Input("scanner-results-table", "selected_rows"),
        ],
        prevent_initial_call=True,
    )
    def toggle_execute_button(playbook_children, selected_rows):
        # Enabled only when a playbook has rendered AND a row is still selected.
        if not selected_rows:
            return True
        if not playbook_children or playbook_children == "No ticker selected.":
            return True
        return False

    @app.callback(
        [
            Output("scanner-execute-confirm-modal", "is_open"),
            Output("scanner-execute-confirm-body", "children"),
            Output("scanner-pending-execution", "data"),
            Output("scanner-execute-status", "children", allow_duplicate=True),
        ],
        Input("scanner-execute-btn", "n_clicks"),
        [
            State("scanner-results-table", "selected_rows"),
            State("scanner-results-store", "data"),
            State("scanner-llm-model", "value"),
        ],
        prevent_initial_call=True,
    )
    def open_execute_confirm(n_clicks, selected_rows, rows, model):
        if not n_clicks or not selected_rows or not rows:
            return no_update, no_update, no_update, no_update

        row = rows[selected_rows[0]]
        symbol = row["symbol"]
        strategy_id = row["strategy_id"]

        if "/" in symbol:
            return False, no_update, None, html.Div(
                "Crypto execution not yet supported.",
                style={"color": "#F59E0B"},
            )

        cached = SCANNER_STATE.get_playbook(symbol, strategy_id, model or "")
        if cached is None:
            return False, no_update, None, html.Div(
                "No playbook in memory. Click Generate Playbook first.",
                style={"color": "#F59E0B"},
            )

        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            from tradingagents.scanner.execution import compute_scanner_position_size
            account = AlpacaUtils.get_account_info()
            buying_power = float(account.get("buying_power") or 0.0)
        except Exception as exc:
            logger.exception("Account lookup failed")
            return False, no_update, None, html.Div(
                f"Could not read Alpaca account: {exc}",
                style={"color": "#EF4444"},
            )

        qty = compute_scanner_position_size(
            buying_power=buying_power,
            position_size_pct=cached.position_size_pct,
            entry_price=cached.entry_price,
        )
        if qty <= 0:
            return False, no_update, None, html.Div(
                f"Insufficient buying power for {cached.position_size_pct * 100:.1f}% "
                f"of ${buying_power:,.2f} at ${cached.entry_price:.2f}/share — qty rounded to 0.",
                style={"color": "#EF4444"},
            )

        est_cost = qty * cached.entry_price
        body = html.Div([
            html.Div(f"{symbol} — {strategy_id}",
                     style={"fontSize": "16px", "fontWeight": "700",
                            "marginBottom": "12px"}),
            html.Div([
                html.Div([html.Span("Order: ", style={"color": "#94A3B8"}),
                          html.Span(cached.order_type,
                                    style={"fontWeight": "600", "color": "#60A5FA"})]),
                html.Div([html.Span("Quantity: ", style={"color": "#94A3B8"}),
                          html.Span(f"{qty} shares",
                                    style={"fontWeight": "600"})]),
                html.Div([html.Span("Entry: ", style={"color": "#94A3B8"}),
                          html.Span(f"${cached.entry_price:.2f}",
                                    style={"fontWeight": "600"})]),
                html.Div([html.Span("Stop: ", style={"color": "#94A3B8"}),
                          html.Span(f"${cached.stop_loss:.2f}",
                                    style={"color": "#EF4444", "fontWeight": "600"})]),
                html.Div([html.Span("Take profit (PT1): ", style={"color": "#94A3B8"}),
                          html.Span(f"${cached.profit_target_1:.2f}",
                                    style={"color": "#22C55E", "fontWeight": "600"})]),
                html.Div([html.Span("PT2 (reference, manual): ", style={"color": "#94A3B8"}),
                          html.Span(f"${cached.profit_target_2:.2f}",
                                    style={"color": "#94A3B8"})]),
                html.Div([html.Span("Estimated cost: ", style={"color": "#94A3B8"}),
                          html.Span(f"${est_cost:,.2f}",
                                    style={"fontWeight": "600"})]),
                html.Div([html.Span("Buying power: ", style={"color": "#94A3B8"}),
                          html.Span(f"${buying_power:,.2f}",
                                    style={"fontWeight": "600"})]),
            ], style={"fontSize": "13px", "lineHeight": "1.8"}),
            html.Hr(),
            html.Div(
                "This sends a real bracket order to Alpaca paper trading. "
                "Alpaca brackets only support a single take-profit, so PT2 is "
                "logged as reference — you can scale out manually at PT1.",
                style={"fontSize": "12px", "color": "#94A3B8",
                       "fontStyle": "italic"},
            ),
        ])

        pending = {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "model": model or "",
            "qty": qty,
        }
        return True, body, pending, ""

    @app.callback(
        [
            Output("scanner-execute-confirm-modal", "is_open", allow_duplicate=True),
            Output("scanner-execute-status", "children", allow_duplicate=True),
            Output("scanner-pending-execution", "data", allow_duplicate=True),
        ],
        [
            Input("scanner-execute-confirm-btn", "n_clicks"),
            Input("scanner-execute-cancel-btn", "n_clicks"),
        ],
        State("scanner-pending-execution", "data"),
        running=[
            (Output("scanner-execute-confirm-btn", "disabled"), True, False),
            (Output("scanner-execute-confirm-btn", "children"),
             _exec_busy_children, "Confirm & Submit"),
        ],
        prevent_initial_call=True,
    )
    def submit_execute(confirm_clicks, cancel_clicks, pending):
        from dash import ctx
        triggered = ctx.triggered_id
        if triggered == "scanner-execute-cancel-btn":
            return False, no_update, None
        if not confirm_clicks or not pending:
            return no_update, no_update, no_update

        symbol = pending.get("symbol")
        strategy_id = pending.get("strategy_id")
        model = pending.get("model", "")
        playbook = SCANNER_STATE.get_playbook(symbol, strategy_id, model)
        if playbook is None:
            return False, html.Div(
                "Playbook expired from memory — re-generate before executing.",
                style={"color": "#F59E0B"},
            ), None

        try:
            from tradingagents.scanner.execution import execute_playbook_paper
            result = execute_playbook_paper(playbook)
        except Exception as exc:
            logger.exception("Execute paper failed unexpectedly")
            return False, html.Div(
                f"Execution failed: {exc}",
                style={"color": "#EF4444"},
            ), None

        if result.success:
            status = html.Div(
                [
                    html.Span("check_circle",
                              className="material-symbols-outlined me-1",
                              style={"verticalAlign": "middle", "color": "#22C55E"}),
                    f"Submitted {result.qty} shares — Alpaca id ",
                    html.Code(result.alpaca_order_id or "?",
                              style={"backgroundColor": "rgba(15,23,42,0.6)",
                                     "padding": "1px 6px", "borderRadius": "3px"}),
                    " · tag ",
                    html.Code(result.client_order_id or "?",
                              style={"backgroundColor": "rgba(15,23,42,0.6)",
                                     "padding": "1px 6px", "borderRadius": "3px"}),
                    ". Chart auto-refreshes every 3s.",
                ],
                style={"color": "#22C55E"},
            )
            return False, status, None
        else:
            status = html.Div(
                [
                    html.Span("error",
                              className="material-symbols-outlined me-1",
                              style={"verticalAlign": "middle", "color": "#EF4444"}),
                    f"Failed: {result.error}",
                ],
                style={"color": "#EF4444"},
            )
            return False, status, None

    # ── Liquidate Position flow ────────────────────────────────────────

    @app.callback(
        Output("scanner-liquidate-btn", "disabled"),
        [
            Input("scanner-position-status", "children"),
            Input("scanner-results-table", "selected_rows"),
        ],
        prevent_initial_call=True,
    )
    def toggle_liquidate_button(position_status, selected_rows):
        # The position-status component is "" or a "No open position…" Span when
        # there's nothing to close. Enable only when both a row is selected AND
        # the position status renders the OPEN summary.
        if not selected_rows:
            return True
        if not position_status:
            return True
        # Walk the children for the "OPEN" sentinel text emitted by
        # _format_position_status when a position exists.
        text_blob = repr(position_status)
        return "OPEN " not in text_blob

    @app.callback(
        [
            Output("scanner-liquidate-confirm-modal", "is_open"),
            Output("scanner-liquidate-confirm-body", "children"),
            Output("scanner-execute-status", "children", allow_duplicate=True),
        ],
        Input("scanner-liquidate-btn", "n_clicks"),
        [
            State("scanner-results-table", "selected_rows"),
            State("scanner-results-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def open_liquidate_confirm(n_clicks, selected_rows, rows):
        if not n_clicks or not selected_rows or not rows:
            return no_update, no_update, no_update

        symbol = rows[selected_rows[0]].get("symbol", "")
        if not symbol:
            return no_update, no_update, no_update

        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            position = AlpacaUtils.get_position_with_brackets(symbol)
        except Exception as exc:
            logger.exception("Position lookup failed for liquidate")
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
                f"This will market-close your {side} position in {symbol} and cancel "
                "any open bracket legs (stop-loss / take-profit).",
                style={"marginBottom": "14px", "color": "#CBD5E1", "fontSize": "13px"},
            ),
            html.Div([
                html.Div([html.Div("SYMBOL", className="pb-label"),
                          html.Div(symbol, className="pb-value")], className="pb-row"),
                html.Div([html.Div("QTY", className="pb-label"),
                          html.Div(f"{qty:g} ({side})", className="pb-value")], className="pb-row"),
                html.Div([html.Div("AVG ENTRY", className="pb-label"),
                          html.Div(f"${avg:,.2f}", className="pb-value")], className="pb-row"),
                html.Div([html.Div("CURRENT", className="pb-label"),
                          html.Div(f"${cur:,.2f}", className="pb-value")], className="pb-row"),
                html.Div([html.Div("UNREALIZED P/L", className="pb-label"),
                          html.Div(f"{sign}${pl:,.2f} ({sign}{plpc:.2f}%)",
                                   className="pb-value",
                                   style={"color": pl_color, "fontWeight": "700"})],
                         className="pb-row"),
            ], style={"display": "grid", "gridTemplateColumns": "repeat(2, 1fr)", "gap": "10px"}),
        ])
        return True, body, no_update

    @app.callback(
        [
            Output("scanner-liquidate-confirm-modal", "is_open", allow_duplicate=True),
            Output("scanner-execute-status", "children", allow_duplicate=True),
        ],
        [
            Input("scanner-liquidate-confirm-btn", "n_clicks"),
            Input("scanner-liquidate-cancel-btn", "n_clicks"),
        ],
        [
            State("scanner-results-table", "selected_rows"),
            State("scanner-results-store", "data"),
        ],
        running=[
            (Output("scanner-liquidate-confirm-btn", "disabled"), True, False),
            (Output("scanner-liquidate-confirm-btn", "children"),
             "Liquidating…", "Confirm & Liquidate"),
        ],
        prevent_initial_call=True,
    )
    def submit_liquidate(confirm_clicks, cancel_clicks, selected_rows, rows):
        from dash import ctx
        triggered = ctx.triggered_id
        if triggered == "scanner-liquidate-cancel-btn":
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
            logger.exception("Cancel-bracket-legs failed")
            return False, html.Div(
                f"Failed to cancel open orders for {symbol}: {exc}",
                style={"color": "#EF4444"},
            )

        try:
            close_result = AlpacaUtils.close_position(symbol)
        except Exception as exc:
            logger.exception("close_position failed")
            return False, html.Div(
                f"Failed to close position: {exc}", style={"color": "#EF4444"},
            )

        if not close_result.get("success"):
            err = close_result.get("error") or "unknown error"
            return False, html.Div(
                f"Liquidation failed: {err}", style={"color": "#EF4444"},
            )

        cancelled_n = cancel_result.get("cancelled_count") if isinstance(cancel_result, dict) else None
        cancelled_str = f" · cancelled {cancelled_n} bracket leg(s)" if cancelled_n else ""

        status = html.Div(
            [
                html.Span("check_circle",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle", "color": "#22C55E"}),
                f"Liquidated {symbol}: market-close submitted (Alpaca id ",
                html.Code(str(close_result.get("order_id") or "?"),
                          style={"backgroundColor": "rgba(15,23,42,0.6)",
                                 "padding": "1px 6px", "borderRadius": "3px"}),
                f"){cancelled_str}.",
            ],
            style={"color": "#22C55E"},
        )
        return False, status

    # ── Cancel Order flow (pre-fill) ───────────────────────────────────

    @app.callback(
        Output("scanner-cancel-order-btn", "disabled"),
        [
            Input("scanner-order-state", "data"),
            Input("scanner-results-table", "selected_rows"),
        ],
        prevent_initial_call=True,
    )
    def toggle_cancel_order_button(order_state, selected_rows):
        # Enable only when a row is selected AND there's at least one
        # scanner-tagged unfilled order for the symbol.
        if not selected_rows:
            return True
        if not order_state:
            return True
        return int(order_state.get("unfilled_count") or 0) <= 0

    @app.callback(
        [
            Output("scanner-cancel-order-confirm-modal", "is_open"),
            Output("scanner-cancel-order-confirm-body", "children"),
            Output("scanner-execute-status", "children", allow_duplicate=True),
        ],
        Input("scanner-cancel-order-btn", "n_clicks"),
        [
            State("scanner-results-table", "selected_rows"),
            State("scanner-results-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def open_cancel_order_confirm(n_clicks, selected_rows, rows):
        if not n_clicks or not selected_rows or not rows:
            return no_update, no_update, no_update

        symbol = rows[selected_rows[0]].get("symbol", "")
        if not symbol:
            return no_update, no_update, no_update

        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            unfilled = AlpacaUtils.get_unfilled_scanner_orders(symbol)
        except Exception as exc:
            logger.exception("get_unfilled_scanner_orders failed")
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
                          html.Div(o["id"][:8] + "…", className="pb-value")],
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
            Output("scanner-cancel-order-confirm-modal", "is_open", allow_duplicate=True),
            Output("scanner-execute-status", "children", allow_duplicate=True),
        ],
        [
            Input("scanner-cancel-order-confirm-btn", "n_clicks"),
            Input("scanner-cancel-order-keep-btn", "n_clicks"),
        ],
        [
            State("scanner-results-table", "selected_rows"),
            State("scanner-results-store", "data"),
        ],
        running=[
            (Output("scanner-cancel-order-confirm-btn", "disabled"), True, False),
            (Output("scanner-cancel-order-confirm-btn", "children"),
             "Cancelling…", "Confirm & Cancel"),
        ],
        prevent_initial_call=True,
    )
    def submit_cancel_order(confirm_clicks, keep_clicks, selected_rows, rows):
        from dash import ctx
        triggered = ctx.triggered_id
        if triggered == "scanner-cancel-order-keep-btn":
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
            logger.exception("cancel_unfilled_scanner_order failed")
            return False, html.Div(
                f"Cancel failed: {exc}", style={"color": "#EF4444"},
            )

        cancelled_n = int(result.get("cancelled") or 0)
        failed_n = int(result.get("failed") or 0)

        if cancelled_n == 0 and failed_n == 0:
            return False, html.Div(
                f"No pending scanner order found for {symbol} — already filled or cancelled.",
                style={"color": "#94A3B8"},
            )

        if not result.get("success"):
            errs = "; ".join(result.get("errors") or []) or "unknown error"
            return False, html.Div(
                f"Cancel partial failure: {cancelled_n} cancelled, {failed_n} failed. {errs}",
                style={"color": "#EF4444"},
            )

        status = html.Div(
            [
                html.Span("check_circle",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle", "color": "#22C55E"}),
                f"Cancelled {cancelled_n} pending order(s) for {symbol}. "
                "Bracket children auto-cancelled.",
            ],
            style={"color": "#22C55E"},
        )
        return False, status

    # ── Save Play flow ─────────────────────────────────────────────────

    @app.callback(
        Output("scanner-save-btn", "disabled"),
        [
            Input("scanner-playbook-output", "children"),
            Input("scanner-results-table", "selected_rows"),
        ],
        prevent_initial_call=True,
    )
    def toggle_save_button(playbook_children, selected_rows):
        if not selected_rows:
            return True
        if not playbook_children or playbook_children == "No ticker selected.":
            return True
        return False

    @app.callback(
        [
            Output("scanner-save-modal", "is_open"),
            Output("scanner-save-modal-summary", "children"),
            Output("scanner-save-label-input", "value"),
        ],
        Input("scanner-save-btn", "n_clicks"),
        [
            State("scanner-results-table", "selected_rows"),
            State("scanner-results-store", "data"),
            State("scanner-llm-model", "value"),
        ],
        prevent_initial_call=True,
    )
    def open_save_modal(n_clicks, selected_rows, rows, model):
        if not n_clicks or not selected_rows or not rows:
            return no_update, no_update, no_update
        row = rows[selected_rows[0]]
        symbol = row.get("symbol", "")
        strategy_id = row.get("strategy_id", "")
        strategy_name = row.get("strategy_name", strategy_id)
        playbook = SCANNER_STATE.get_playbook(symbol, strategy_id, model or "")
        if playbook is None:
            return False, "Playbook not found in memory — re-generate first.", ""
        summary = html.Div([
            html.Span(f"{symbol} · {strategy_name}",
                      style={"fontWeight": "700", "color": "#F1F5F9"}),
            html.Span(
                f" · entry ${playbook.entry_price:,.2f} · "
                f"stop ${playbook.stop_loss:,.2f} · "
                f"PT1 ${playbook.profit_target_1:,.2f}",
                style={"color": "#94A3B8", "marginLeft": "6px"},
            ),
        ])
        default_label = f"{symbol} {strategy_id} {datetime.now().strftime('%Y-%m-%d')}"
        return True, summary, default_label

    @app.callback(
        [
            Output("scanner-save-modal", "is_open", allow_duplicate=True),
            Output("scanner-execute-status", "children", allow_duplicate=True),
        ],
        [
            Input("scanner-save-confirm-btn", "n_clicks"),
            Input("scanner-save-cancel-btn", "n_clicks"),
        ],
        [
            State("scanner-save-label-input", "value"),
            State("scanner-results-table", "selected_rows"),
            State("scanner-results-store", "data"),
            State("scanner-llm-model", "value"),
            State("scanner-llm-provider", "value"),
            State("scanner-chart-timeframe", "value"),
            State("scanner-chart-toggles", "value"),
        ],
        prevent_initial_call=True,
    )
    def submit_save(confirm_clicks, cancel_clicks, label_input,
                    selected_rows, rows, model, provider,
                    chart_tf, chart_toggles):
        from dash import ctx
        triggered = ctx.triggered_id
        if triggered == "scanner-save-cancel-btn":
            return False, no_update
        if not confirm_clicks or not selected_rows or not rows:
            return no_update, no_update
        row = rows[selected_rows[0]]
        symbol = row.get("symbol", "")
        strategy_id = row.get("strategy_id", "")
        strategy_name = row.get("strategy_name", strategy_id)
        playbook = SCANNER_STATE.get_playbook(symbol, strategy_id, model or "")
        if playbook is None:
            return False, html.Div(
                "Playbook expired from memory — re-generate before saving.",
                style={"color": "#F59E0B"},
            )

        # Best-effort link to any pending scanner order for this symbol.
        linked = {"client_order_id": None, "alpaca_order_id": None}
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            unfilled = AlpacaUtils.get_unfilled_scanner_orders(symbol)
            if unfilled:
                linked = {
                    "client_order_id": unfilled[0].get("client_order_id"),
                    "alpaca_order_id": unfilled[0].get("id"),
                }
        except Exception as exc:
            logger.debug("link alpaca order failed: %s", exc)

        try:
            entry = SAVED_PLAYS.save(
                symbol=symbol,
                strategy_id=strategy_id,
                strategy_name=strategy_name,
                model=model or "",
                provider=provider or "",
                playbook=playbook,
                scan_row=row,
                ui_state={
                    "chart_timeframe": chart_tf or "5m",
                    "chart_toggles": list(chart_toggles or []),
                },
                linked_alpaca=linked,
                label=(label_input or "").strip() or None,
            )
        except Exception as exc:
            logger.exception("SAVED_PLAYS.save failed")
            return False, html.Div(
                f"Save failed: {exc}", style={"color": "#EF4444"},
            )

        status = html.Div(
            [
                html.Span("bookmark_added",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle", "color": "#3B82F6"}),
                f"Saved as ",
                html.Code(entry["label"],
                          style={"backgroundColor": "rgba(15,23,42,0.6)",
                                 "padding": "1px 6px", "borderRadius": "3px"}),
                ". View in the Plays tab.",
            ],
            style={"color": "#3B82F6"},
        )
        return False, status

    # ── Live chart panel (auto-overlay + fills) ────────────────────────

    @app.callback(
        [
            Output("scanner-chart-payload", "data"),
            Output("scanner-chart-wrapper", "style"),
            Output("scanner-position-status", "children"),
            Output("scanner-order-state", "data"),
        ],
        [
            Input("scanner-playbook-output", "children"),
            Input("scanner-chart-timeframe", "value"),
            Input("scanner-chart-toggles", "value"),
            Input("scanner-chart-poller", "n_intervals"),
        ],
        [
            State("scanner-results-table", "selected_rows"),
            State("scanner-results-store", "data"),
            State("scanner-llm-model", "value"),
        ],
        prevent_initial_call=True,
    )
    def render_scanner_chart(playbook_children, timeframe, toggles, _n_intervals,
                             selected_rows, rows, model):
        """Build the LWC payload and push it to the chart's dcc.Store.

        Re-fires on: new playbook, timeframe change, toggle change, 3s poller.
        Always reads the latest open-position + unfilled-order data from
        Alpaca on each tick to drive Liquidate / Cancel Order button state.
        """
        hidden = {"display": "none"}
        empty_state = {"unfilled_count": 0, "has_position": False}
        toggles = toggles or []
        show_playbook = "playbook" in toggles
        show_position = "position" in toggles

        if not selected_rows or not rows:
            return no_update, hidden, "", empty_state

        try:
            row = rows[selected_rows[0]]
        except (IndexError, KeyError):
            return no_update, hidden, "", empty_state

        symbol = row.get("symbol")
        strategy_id = row.get("strategy_id")
        if not symbol or not strategy_id:
            return no_update, hidden, "", empty_state

        playbook = SCANNER_STATE.get_playbook(symbol, strategy_id, model or "")
        if playbook is None:
            return no_update, hidden, "", empty_state

        overlay_levels = None
        if show_playbook:
            overlay_levels = {
                "entry": playbook.entry_price,
                "stop": playbook.stop_loss,
                "pt1": playbook.profit_target_1,
                "pt2": playbook.profit_target_2,
            }

        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        fills = []
        try:
            fills = AlpacaUtils.get_scanner_orders(symbol=symbol, since_minutes=600)
        except Exception as exc:
            logger.debug("get_scanner_orders failed: %s", exc)

        position = None
        try:
            position = AlpacaUtils.get_position_with_brackets(symbol)
        except Exception as exc:
            logger.debug("get_position_with_brackets failed: %s", exc)

        unfilled = []
        try:
            unfilled = AlpacaUtils.get_unfilled_scanner_orders(symbol)
        except Exception as exc:
            logger.debug("get_unfilled_scanner_orders failed: %s", exc)

        position_levels = None
        if show_position and position:
            position_levels = {
                "avg": position.get("avg_entry_price"),
                "tp": position.get("take_profit"),
                "sl": position.get("stop_loss"),
            }

        try:
            from webui.utils.charts_lwc import build_lwc_payload
            payload = build_lwc_payload(
                symbol,
                period=timeframe or "5m",
                overlay_levels=overlay_levels,
                position_levels=position_levels,
                fills=fills,
            )
        except Exception:
            logger.exception("build_lwc_payload failed for %s", symbol)
            return no_update, hidden, "", empty_state

        status = _format_position_status(position)
        order_state = {
            "unfilled_count": len(unfilled),
            "has_position": position is not None,
            "symbol": symbol,
        }
        return payload, {"display": "block"}, status, order_state

    app.clientside_callback(
        """
        function(payload) {
            if (payload && window.lwcRender) {
                window.lwcRender('scanner-chart', payload);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("scanner-chart", "data-lwc-rendered"),
        Input("scanner-chart-payload", "data"),
    )

    # ── Deep Dive (intraday strategy fit + bull/bear case + risks) ─────
    #
    # Mirrors the long-term Deep Dive flow. Three callbacks:
    #   1. toggle_scanner_deep_dive → enable button + reveal panel on
    #      row select.
    #   2. open_scanner_deep_dive → fire trigger store on click (cheap).
    #   3. run_scanner_deep_dive → async LLM call, reads trigger, writes
    #      markdown into the output panel.
    # The trigger-store split keeps the click responsive while the slow
    # LLM call runs in its own callback.

    @app.callback(
        [
            Output("scanner-deep-dive-btn", "disabled"),
            Output("scanner-deep-dive-wrapper", "style"),
        ],
        Input("scanner-results-table", "selected_rows"),
    )
    def toggle_scanner_deep_dive(selected_rows):
        if not selected_rows:
            return True, {"display": "none"}
        return False, {"display": "block"}

    _scanner_dd_idle_children = [
        html.Span("search", className="material-symbols-outlined me-1",
                  style={"fontSize": "16px", "verticalAlign": "middle"}),
        "Run Deep Dive",
    ]
    _scanner_dd_busy_children = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Researching... (web search ~30–60s)",
    ]

    @app.callback(
        Output("scanner-deep-dive-trigger", "data"),
        Input("scanner-deep-dive-btn", "n_clicks"),
        [
            State("scanner-results-table", "selected_rows"),
            State("scanner-results-store", "data"),
        ],
        prevent_initial_call=True,
    )
    def open_scanner_deep_dive(n_clicks, selected_rows, rows):
        if not n_clicks or not selected_rows or not rows:
            return no_update
        try:
            row = rows[selected_rows[0]]
        except (IndexError, KeyError):
            return no_update
        symbol = row.get("symbol")
        strategy_id = row.get("strategy_id") or row.get("strategy")
        if not symbol:
            return no_update
        return {
            "symbol": symbol,
            "strategy_id": strategy_id or "",
            "ts": datetime.now().isoformat(),
        }

    @app.callback(
        Output("scanner-deep-dive-output", "children"),
        Input("scanner-deep-dive-trigger", "data"),
        running=[
            (Output("scanner-deep-dive-btn", "disabled"), True, False),
            (Output("scanner-deep-dive-btn", "children"),
             _scanner_dd_busy_children, _scanner_dd_idle_children),
        ],
        prevent_initial_call=True,
    )
    def run_scanner_deep_dive(trigger):
        if not trigger or not trigger.get("symbol"):
            return no_update
        symbol = trigger["symbol"]
        strategy_id = trigger.get("strategy_id") or ""
        scan_result = None
        for r in SCANNER_STATE.get_results():
            if r.snapshot.symbol == symbol and (
                not strategy_id or r.strategy_id == strategy_id
            ):
                scan_result = r
                break
        if scan_result is None:
            return ("_Candidate no longer in latest scan — "
                    "re-run scan first._")
        try:
            from tradingagents.scanner.scanner_deep_dive import generate_deep_dive
            markdown = generate_deep_dive(scan_result)
        except Exception:
            logger.exception("scanner deep-dive generation failed")
            return "_Deep dive failed. Check logs and try again._"
        if not markdown:
            return ("_Deep dive returned no content. The LLM provider may "
                    "be unavailable, or web search may be rate-limited. "
                    "Try again in a minute._")
        return markdown

