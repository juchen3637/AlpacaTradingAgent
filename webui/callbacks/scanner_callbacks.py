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
from webui.utils.scanner_state import SCANNER_STATE

logger = logging.getLogger(__name__)


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


def _format_playbook(playbook) -> html.Div:
    return html.Div([
        html.Div(
            playbook.thesis,
            style={"fontSize": "14px", "color": "#F1F5F9", "marginBottom": "16px",
                   "lineHeight": "1.5"},
        ),
        html.Div([
            html.Div([
                html.Div("ENTRY", className="pb-label"),
                html.Div(playbook.entry_trigger, className="pb-value"),
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
                html.Div(playbook.confidence.upper(),
                         className="pb-value",
                         style={
                             "color": {"high": "#22C55E", "medium": "#F59E0B",
                                       "low": "#EF4444"}.get(playbook.confidence, "#94A3B8"),
                         }),
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
        ],
        running=[
            (Output("scanner-run-btn", "disabled"), True, False),
            (Output("scanner-run-btn", "color"), "danger", "primary"),
            (Output("scanner-run-btn", "children"), _run_busy_children, _run_idle_children),
        ],
        prevent_initial_call=True,
    )
    def run_scan(n_clicks, universe, min_rvol, price_min, price_max,
                 max_float, catalyst_only, watchlist_raw):
        if not n_clicks:
            return no_update, no_update, no_update, no_update

        filters = _build_filters(
            universe, min_rvol, price_min, price_max,
            max_float, catalyst_only, watchlist_raw,
        )

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
