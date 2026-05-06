"""webui/callbacks/plays_callbacks.py - Callbacks for the Plays tab.

Handles:
- Grid render (filter / sort / cards)
- Per-card Re-analyze (LLM viability check, persists verdict)
- Per-card Exit Now (close_position)
- Per-card Cancel Pending Order (cancel_unfilled_scanner_order)
- Per-card Delete (SAVED_PLAYS.delete)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from webui.utils.plays_filter import filter_and_sort_plays
from tradingagents.scanner.longterm_models import LONGTERM_STRATEGY_ID
from webui.utils.saved_plays import (
    SAVED_PLAYS,
    longterm_playbook_from_dict,
    playbook_from_dict,
)

logger = logging.getLogger(__name__)


# ─── verdict styling ────────────────────────────────────────────────


_VERDICT_COLORS = {
    "still_viable": "#22C55E",
    "degraded": "#F59E0B",
    "invalidated": "#EF4444",
    "thesis_played_out": "#94A3B8",
}
_VERDICT_LABELS = {
    "still_viable": "STILL VIABLE",
    "degraded": "DEGRADED",
    "invalidated": "INVALIDATED",
    "thesis_played_out": "PLAYED OUT",
}
_ACTION_LABELS = {
    "hold": "Hold",
    "tighten_stop": "Tighten stop",
    "scale_out": "Scale out",
    "exit_now": "Exit now",
    "no_position_skip": "Skip — don't enter",
}


# ─── live-state lookup ─────────────────────────────────────────────


def _index_positions(positions: list[dict]) -> dict[str, dict]:
    """Convert get_positions_data() rows into {symbol: row} for O(1) lookup."""
    out: dict[str, dict] = {}
    for p in positions or []:
        sym = (p.get("Symbol") or "").upper()
        if sym:
            out[sym] = p
    return out


def _index_unfilled(orders: list[dict]) -> dict[str, list[dict]]:
    """Group unfilled scanner orders by symbol."""
    out: dict[str, list[dict]] = {}
    for o in orders or []:
        sym = (o.get("symbol") or "").upper()
        if not sym:
            continue
        out.setdefault(sym, []).append(o)
    return out


def _fetch_live_state() -> tuple[dict, dict]:
    """Fetch all positions and all unfilled scanner orders (2 Alpaca calls)."""
    positions: list[dict] = []
    unfilled: list[dict] = []
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils
        positions = AlpacaUtils.get_positions_data() or []
    except Exception as exc:
        logger.debug("plays: get_positions_data failed: %s", exc)
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils
        unfilled = AlpacaUtils.get_unfilled_scanner_orders() or []
    except Exception as exc:
        logger.debug("plays: get_unfilled_scanner_orders failed: %s", exc)
    return _index_positions(positions), _index_unfilled(unfilled)


# ─── card rendering ────────────────────────────────────────────────


def _label_style():
    return {"fontSize": "11px", "color": "#94A3B8",
            "textTransform": "uppercase", "letterSpacing": "1px"}


def _value_style(weight: str = "600", color: str = "#F1F5F9"):
    return {"fontSize": "14px", "color": color, "fontWeight": weight,
            "fontVariantNumeric": "tabular-nums"}


def _kv(label: str, value, color: str = "#F1F5F9"):
    return html.Div(
        [
            html.Div(label, style=_label_style()),
            html.Div(value, style=_value_style(color=color)),
        ],
        style={"flex": "1 1 50%", "marginBottom": "8px"},
    )


def _verdict_badge(verdict: Optional[dict]) -> html.Div:
    if not verdict or not verdict.get("status"):
        return html.Div(
            "Not analyzed yet",
            style={
                "display": "inline-block", "padding": "4px 10px",
                "borderRadius": "12px", "fontSize": "11px", "fontWeight": "700",
                "letterSpacing": "1px", "color": "#94A3B8",
                "border": "1px solid #475569", "backgroundColor": "rgba(71,85,105,0.15)",
            },
        )
    status = verdict.get("status")
    color = _VERDICT_COLORS.get(status, "#94A3B8")
    label = _VERDICT_LABELS.get(status, status.upper())
    return html.Div(
        label,
        style={
            "display": "inline-block", "padding": "4px 10px",
            "borderRadius": "12px", "fontSize": "11px", "fontWeight": "700",
            "letterSpacing": "1px", "color": color,
            "border": f"1px solid {color}",
            "backgroundColor": f"{color}1F",
        },
    )


def _position_summary(pos_row: Optional[dict]) -> html.Div:
    if not pos_row:
        return html.Div("No open position",
                        style={"color": "#64748B", "fontStyle": "italic",
                               "fontSize": "12px"})
    qty = pos_row.get("Qty") or 0
    avg = pos_row.get("Avg Entry") or "$0.00"
    pl = pos_row.get("Total P/L ($)") or "$0.00"
    plpc = pos_row.get("Total P/L (%)") or "0.00%"
    pl_neg = "-" in pl
    color = "#EF4444" if pl_neg else "#22C55E"
    return html.Div([
        html.Span(f"OPEN {qty:g} ",
                  style={"fontWeight": "700", "color": "#F1F5F9"}),
        html.Span(f"@ {avg} · ", style={"color": "#94A3B8"}),
        html.Span(f"{pl} ({plpc})",
                  style={"color": color, "fontWeight": "700"}),
    ], style={"fontSize": "12px"})


def _pending_summary(unfilled: list[dict]) -> Optional[html.Div]:
    if not unfilled:
        return None
    o = unfilled[0]
    return html.Div(
        [
            html.Span("PENDING ", style={"fontWeight": "700", "color": "#F59E0B"}),
            html.Span(
                f"{(o.get('side') or '').upper()} {o.get('qty', 0):g} "
                f"{o.get('order_type', '')} · status {o.get('status', '?')}",
                style={"color": "#CBD5E1"},
            ),
        ],
        style={"fontSize": "12px"},
    )


def _verdict_detail_block(verdict: Optional[dict]) -> Optional[html.Div]:
    if not verdict or not verdict.get("status"):
        return None
    status = verdict.get("status", "")
    color = _VERDICT_COLORS.get(status, "#94A3B8")
    action = verdict.get("recommended_action", "hold")
    action_label = _ACTION_LABELS.get(action, action)
    reasoning = verdict.get("reasoning", "")
    key_changes = verdict.get("key_changes", []) or []
    news_signals = verdict.get("news_signals", []) or []
    analyzed_at = verdict.get("analyzed_at", "")

    children = [
        html.Div([
            html.Span("Recommended: ",
                      style={"color": "#94A3B8", "fontSize": "11px",
                             "textTransform": "uppercase", "letterSpacing": "1px"}),
            html.Span(action_label,
                      style={"color": color, "fontWeight": "700", "fontSize": "13px"}),
        ], style={"marginBottom": "6px"}),
        html.Div(reasoning,
                 style={"fontSize": "12px", "color": "#CBD5E1",
                        "lineHeight": "1.5", "marginBottom": "8px"}),
    ]
    if key_changes:
        children.append(html.Div([
            html.Div("WHAT CHANGED", style=_label_style()),
            html.Ul(
                [html.Li(c, style={"fontSize": "12px", "color": "#94A3B8"})
                 for c in key_changes],
                style={"marginBottom": "6px", "paddingLeft": "18px"},
            ),
        ]))
    if news_signals:
        children.append(html.Div([
            html.Div("NEWS SIGNALS", style=_label_style()),
            html.Ul(
                [html.Li(c, style={"fontSize": "12px", "color": "#94A3B8"})
                 for c in news_signals],
                style={"marginBottom": "6px", "paddingLeft": "18px"},
            ),
        ]))
    if analyzed_at:
        children.append(html.Div(
            f"Analyzed {analyzed_at[:16].replace('T', ' ')} UTC",
            style={"fontSize": "10px", "color": "#475569",
                   "fontStyle": "italic"},
        ))
    return html.Div(children, style={
        "padding": "10px 12px",
        "marginTop": "10px",
        "borderLeft": f"3px solid {color}",
        "backgroundColor": f"{color}0D",
        "borderRadius": "0 6px 6px 0",
    })


def _chart_panel(play_id: str, *, is_longterm: bool = False) -> html.Div:
    """Collapsible per-card LWC chart panel — hidden by default.

    Day-trade plays use intraday timeframes (1m/5m/15m/1h). Long-term plays
    use daily/weekly/monthly so the 200-SMA and multi-year structure are
    actually visible.
    """
    if is_longterm:
        tf_options = [
            {"label": "1mo", "value": "1mo"},
            {"label": "1y", "value": "1y"},
            {"label": "3y", "value": "3y"},
            {"label": "5y", "value": "5y"},
        ]
        tf_default = "1y"
    else:
        tf_options = [
            {"label": "1m", "value": "1m"},
            {"label": "5m", "value": "5m"},
            {"label": "15m", "value": "15m"},
            {"label": "1h", "value": "1h"},
        ]
        tf_default = "5m"
    return html.Div(
        [
            html.Div(
                [
                    dbc.RadioItems(
                        id={"type": "play-chart-timeframe", "id": play_id},
                        options=tf_options,
                        value=tf_default,
                        inline=True,
                        className="btn-group",
                        inputClassName="btn-check",
                        labelClassName="btn btn-outline-secondary btn-sm",
                        labelCheckedClassName="active",
                    ),
                ],
                className="d-flex justify-content-end",
                style={"marginBottom": "8px"},
            ),
            html.Div(
                id={"type": "play-chart", "id": play_id},
                style={"width": "100%", "height": "300px"},
            ),
            dcc.Store(id={"type": "play-chart-payload", "id": play_id}),
            html.Div(
                "Data via Alpaca · free-tier minute bars may be ~15m delayed",
                style={"fontSize": "10px", "color": "#475569",
                       "fontStyle": "italic", "marginTop": "4px"},
            ),
        ],
        id={"type": "play-chart-wrapper", "id": play_id},
        style={"display": "none", "marginTop": "12px"},  # hidden by default
    )


def _play_card(play: dict, pos_row: Optional[dict],
               unfilled: list[dict]) -> dbc.Card:
    play_id = play.get("id") or ""
    symbol = play.get("symbol") or "?"
    strategy_id = play.get("strategy_id") or ""
    strategy_name = play.get("strategy_name") or strategy_id or ""
    label = play.get("label") or f"{symbol} {strategy_name}"
    pb = play.get("playbook") or {}
    verdict = play.get("verdict") or None
    has_position = bool(pos_row)
    has_unfilled = bool(unfilled)
    is_longterm = strategy_id == LONGTERM_STRATEGY_ID

    if is_longterm:
        zone_lo = pb.get("entry_zone_low") or 0
        zone_hi = pb.get("entry_zone_high") or 0
        levels_grid = html.Div([
            _kv("Entry Zone",
                f"${zone_lo:,.2f} – ${zone_hi:,.2f}",
                color="#10B981"),
            _kv("DCA", f"{pb.get('dca_weeks') or '?'} weeks", color="#60A5FA"),
            _kv("Hold", f"{pb.get('hold_horizon_years') or '?'} yrs", color="#60A5FA"),
            _kv("3y Target",
                f"${(pb.get('target_price_3y') or 0):,.2f}",
                color="#22C55E"),
        ], style={"display": "flex", "flexWrap": "wrap"})
    else:
        levels_grid = html.Div([
            _kv("Entry", f"${(pb.get('entry_price') or 0):,.2f}", color="#60A5FA"),
            _kv("Stop", f"${(pb.get('stop_loss') or 0):,.2f}", color="#EF4444"),
            _kv("PT1", f"${(pb.get('profit_target_1') or 0):,.2f}", color="#22C55E"),
            _kv("PT2", f"${(pb.get('profit_target_2') or 0):,.2f}", color="#22C55E"),
        ], style={"display": "flex", "flexWrap": "wrap"})

    btn_kwargs = {"size": "sm", "outline": True, "className": "me-2 mb-1"}

    action_color = "danger" if (verdict and verdict.get("recommended_action") == "exit_now"
                                and has_position) else "danger"
    exit_outline = not (verdict and verdict.get("recommended_action") == "exit_now"
                        and has_position)

    # Long-term plays don't have Exit/Cancel buttons (DCA, no single-trigger order).
    # Pattern-matched callbacks still need the IDs in the DOM, so we render them
    # hidden so the callback registry stays satisfied.
    hidden_style = {"display": "none"}

    # Day-trade plays can be executed (bracket order) only when no position
    # is already open and there's no live unfilled scanner order — otherwise
    # the user is just stacking duplicates.
    can_execute = (not is_longterm) and (not has_position) and (not has_unfilled)

    buttons = [
        dbc.Button(
            [html.Span("show_chart",
                       className="material-symbols-outlined me-1",
                       style={"fontSize": "16px", "verticalAlign": "middle"}),
             "Show Chart"],
            id={"type": "play-chart-toggle-btn", "id": play_id},
            color="info",
            **btn_kwargs,
        ),
        dbc.Button(
            [html.Span("auto_awesome",
                       className="material-symbols-outlined me-1",
                       style={"fontSize": "16px", "verticalAlign": "middle"}),
             "Re-analyze"],
            id={"type": "play-reanalyze-btn", "id": play_id},
            color="primary",
            **btn_kwargs,
        ),
        dbc.Button(
            [html.Span("rocket_launch",
                       className="material-symbols-outlined me-1",
                       style={"fontSize": "16px", "verticalAlign": "middle"}),
             "Execute (Paper)"],
            id={"type": "play-execute-btn", "id": play_id},
            color="success",
            disabled=not can_execute,
            size="sm",
            className="me-2 mb-1",
            style=hidden_style if is_longterm else None,
            title=("Already have an open position or pending order — execute disabled."
                   if (has_position or has_unfilled)
                   else "Submit a paper bracket order from this saved playbook."),
        ),
        dbc.Button(
            [html.Span("close",
                       className="material-symbols-outlined me-1",
                       style={"fontSize": "16px", "verticalAlign": "middle"}),
             "Exit Now"],
            id={"type": "play-exit-btn", "id": play_id},
            color=action_color,
            outline=exit_outline,
            disabled=not has_position,
            size="sm",
            className="me-2 mb-1",
            style=hidden_style if is_longterm else None,
        ),
        dbc.Button(
            [html.Span("cancel",
                       className="material-symbols-outlined me-1",
                       style={"fontSize": "16px", "verticalAlign": "middle"}),
             "Cancel Pending"],
            id={"type": "play-cancel-btn", "id": play_id},
            color="warning",
            disabled=not has_unfilled,
            style=hidden_style if is_longterm else None,
            **btn_kwargs,
        ),
        dbc.Button(
            [html.Span("delete",
                       className="material-symbols-outlined me-1",
                       style={"fontSize": "16px", "verticalAlign": "middle"}),
             "Delete"],
            id={"type": "play-delete-btn", "id": play_id},
            color="secondary",
            **btn_kwargs,
        ),
    ]

    return dbc.Card(
        dbc.CardBody(
            [
                # Header row: symbol + verdict badge
                html.Div([
                    html.Div([
                        html.Span(symbol,
                                  style={"fontFamily": "'Space Grotesk', sans-serif",
                                         "fontWeight": "700", "fontSize": "20px",
                                         "color": "#F1F5F9", "marginRight": "8px"}),
                        html.Span(strategy_name,
                                  style={"color": "#94A3B8", "fontSize": "12px"}),
                    ]),
                    _verdict_badge(verdict),
                ], style={"display": "flex", "justifyContent": "space-between",
                          "alignItems": "center", "marginBottom": "4px"}),
                html.Div(label, style={"fontSize": "12px", "color": "#64748B",
                                       "marginBottom": "12px"}),
                # Levels
                levels_grid,
                # Live state
                html.Div([
                    _position_summary(pos_row),
                    _pending_summary(unfilled),
                ], style={"marginBottom": "8px"}),
                # Verdict detail
                _verdict_detail_block(verdict),
                # Re-analyze loading slot — populated by the re-analyze callback
                # while a request is in flight (per-card spinner).
                html.Div(
                    id={"type": "play-reanalyze-loading", "id": play_id},
                    style={"fontSize": "11px", "color": "#94A3B8",
                           "fontStyle": "italic", "marginTop": "6px",
                           "minHeight": "14px"},
                ),
                # Action buttons
                html.Div(buttons, style={"marginTop": "12px"}),
                # Expandable LWC chart (hidden by default)
                _chart_panel(play_id, is_longterm=is_longterm),
            ],
            style={"padding": "16px"},
        ),
        className="glass-card mb-3",
        style={"height": "100%"},
    )


def _empty_state() -> html.Div:
    return html.Div([
        html.Div("No saved plays yet.",
                 style={"fontSize": "16px", "color": "#94A3B8",
                        "marginBottom": "8px"}),
        html.Div("Generate a playbook in the Trading tab and click Save to add one here.",
                 style={"fontSize": "13px", "color": "#64748B"}),
    ], style={"textAlign": "center", "padding": "40px 20px"})


def _filtered_empty_state() -> html.Div:
    return html.Div(
        "No plays match the current filters.",
        style={"fontSize": "13px", "color": "#94A3B8",
               "fontStyle": "italic", "padding": "20px",
               "textAlign": "center"},
    )


def _build_grid(plays: list[dict], positions_by_sym: dict,
                unfilled_by_sym: dict) -> Any:
    if not plays:
        return _filtered_empty_state()
    cols = []
    for p in plays:
        sym = (p.get("symbol") or "").upper()
        cols.append(dbc.Col(
            _play_card(p, positions_by_sym.get(sym), unfilled_by_sym.get(sym, [])),
            xs=12, md=6, xl=4,
            style={"display": "flex"},
        ))
    return dbc.Row(cols, className="g-3")


# ─── viability re-analysis (snapshot collector + LLM call) ─────────


def _today_yyyy_mm_dd() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _fetch_finnhub_news_24h(symbol: str) -> list[dict]:
    """Get the last 24h of Finnhub headlines for the symbol as list[dict]."""
    try:
        from tradingagents.dataflows.finnhub_utils import get_finnhub_client
        client = get_finnhub_client()
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=1)
        items = client.company_news(symbol, _from=start.strftime("%Y-%m-%d"),
                                    to=end.strftime("%Y-%m-%d"))
        out = []
        for item in (items or [])[:5]:
            out.append({
                "headline": item.get("headline") or "",
                "source": item.get("source") or "",
                "summary": item.get("summary") or "",
            })
        return out
    except Exception as exc:
        logger.debug("plays: finnhub news fetch failed for %s: %s", symbol, exc)
        return []


def _fetch_current_price(symbol: str) -> Optional[float]:
    """Best-effort latest price via Alpaca."""
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils
        q = AlpacaUtils.get_latest_quote(symbol)
        # Mid-price; if either side is missing, fall back to the present one.
        bid = q.get("bid_price") if q else None
        ask = q.get("ask_price") if q else None
        if bid and ask:
            return (float(bid) + float(ask)) / 2.0
        return float(bid or ask) if (bid or ask) else None
    except Exception as exc:
        logger.debug("plays: get_latest_quote failed for %s: %s", symbol, exc)
        return None


def _collect_viability_inputs(loaded_play: dict) -> dict:
    """Gather everything the LLM needs to judge viability of a saved play.

    Returns the kwargs dict for `analyze_viability(...)`.
    """
    symbol = loaded_play.get("symbol", "")
    scan_row = dict(loaded_play.get("scan_row") or {})
    saved_price = scan_row.get("last_price")

    cur_price = _fetch_current_price(symbol)

    change_since_save_pct = None
    if saved_price and cur_price:
        try:
            change_since_save_pct = ((cur_price - float(saved_price)) /
                                     float(saved_price)) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            change_since_save_pct = None

    # Position for the symbol (use the more detailed get_position_with_brackets)
    position = None
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils
        position = AlpacaUtils.get_position_with_brackets(symbol)
    except Exception as exc:
        logger.debug("plays: position lookup failed for %s: %s", symbol, exc)

    unfilled = []
    try:
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils
        unfilled = AlpacaUtils.get_unfilled_scanner_orders(symbol) or []
    except Exception as exc:
        logger.debug("plays: unfilled lookup failed for %s: %s", symbol, exc)

    today_change_pct = None
    if position and position.get("change_today") is not None:
        try:
            today_change_pct = float(position["change_today"]) * 100.0
        except (TypeError, ValueError):
            today_change_pct = None

    news = _fetch_finnhub_news_24h(symbol)
    catalyst_now = scan_row.get("catalyst") or None  # snapshot-time catalyst

    current_snapshot = {
        "current_price": cur_price,
        "change_since_save_pct": change_since_save_pct,
        "today_change_pct": today_change_pct,
        "current_rvol": None,  # not tracked live; LLM gets the saved value separately
    }

    playbook_obj = loaded_play.get("playbook_obj")
    if playbook_obj is None:
        # `load()` always rehydrates, but keep a defensive fallback.
        playbook_obj = playbook_from_dict(loaded_play.get("playbook") or {})

    return dict(
        playbook=playbook_obj,
        scan_row=scan_row,
        current_snapshot=current_snapshot,
        news=news,
        catalyst_now=catalyst_now,
        position=position,
        unfilled_orders=unfilled,
    )


# ─── callback registration ─────────────────────────────────────────


def register_plays_callbacks(app):
    """Register Plays-tab callbacks."""

    @app.callback(
        Output("plays-grid", "children"),
        [
            Input("plays-tick", "data"),
            Input("plays-filter-symbol", "value"),
            Input("plays-filter-status", "value"),
            Input("plays-filter-verdict", "value"),
            Input("plays-sort", "value"),
            Input("nav-plays", "n_clicks"),
        ],
    )
    def render_plays_grid(_tick, filter_sym, filter_status, filter_verdict,
                          sort_key, _nav_clicks):
        plays = SAVED_PLAYS.list_all()
        if not plays:
            return _empty_state()
        positions_by_sym, unfilled_by_sym = _fetch_live_state()
        filtered = filter_and_sort_plays(
            plays,
            symbol=filter_sym or "",
            status_filter=filter_status or "all",
            verdict_filter=filter_verdict or "any",
            sort_key=sort_key or "last_opened_desc",
            positions_by_sym=positions_by_sym,
            unfilled_by_sym=unfilled_by_sym,
        )
        return _build_grid(filtered, positions_by_sym, unfilled_by_sym)

    # ── Re-analyze ────────────────────────────────────────────────

    # Fast clientside hook: paint a spinner into the clicked card's loading
    # slot the instant the button is pressed, before the Python callback has
    # even started its LLM round-trip. The Python callback below clears it.
    app.clientside_callback(
        """
        function(allClicks, allIds) {
            const n = (allIds || []).length;
            const noUp = window.dash_clientside.no_update;
            if (!allClicks || !n) return Array(n).fill(noUp);
            const triggered = (window.dash_clientside.callback_context || {}).triggered || [];
            if (!triggered.length) return Array(n).fill(noUp);
            const propId = triggered[0].prop_id || '';
            const idJson = propId.split('.n_clicks')[0];
            let triggeredId;
            try { triggeredId = JSON.parse(idJson); } catch (e) { return Array(n).fill(noUp); }
            const spinner = {
                namespace: 'dash_html_components',
                type: 'Span',
                props: {
                    children: [
                        { namespace: 'dash_html_components', type: 'Span',
                          props: { className: 'spinner-border spinner-border-sm me-2',
                                   role: 'status', 'aria-hidden': 'true', children: '' } },
                        { namespace: 'dash_html_components', type: 'Span',
                          props: { children: 'Analyzing… contacting the LLM (this may take 10–30s)' } }
                    ],
                    style: { color: '#3B82F6' }
                }
            };
            const out = [];
            for (let i = 0; i < n; i++) {
                out.push(allIds[i].id === triggeredId.id ? spinner : noUp);
            }
            return out;
        }
        """,
        Output({"type": "play-reanalyze-loading", "id": ALL}, "children",
               allow_duplicate=True),
        Input({"type": "play-reanalyze-btn", "id": ALL}, "n_clicks"),
        State({"type": "play-reanalyze-btn", "id": ALL}, "id"),
        prevent_initial_call=True,
    )

    _reanalyze_busy_children = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Analyzing…",
    ]
    _reanalyze_idle_children = [
        html.Span("auto_awesome", className="material-symbols-outlined me-1",
                  style={"fontSize": "16px", "verticalAlign": "middle"}),
        "Re-analyze",
    ]

    @app.callback(
        [
            Output({"type": "play-reanalyze-loading", "id": ALL}, "children"),
            Output("plays-tick", "data", allow_duplicate=True),
            Output("plays-status", "children", allow_duplicate=True),
        ],
        Input({"type": "play-reanalyze-btn", "id": ALL}, "n_clicks"),
        [
            State({"type": "play-reanalyze-btn", "id": ALL}, "id"),
            State("plays-tick", "data"),
        ],
        running=[
            (Output({"type": "play-reanalyze-btn", "id": ALL}, "disabled"),
             True, False),
            (Output({"type": "play-reanalyze-btn", "id": ALL}, "children"),
             _reanalyze_busy_children, _reanalyze_idle_children),
        ],
        prevent_initial_call=True,
    )
    def reanalyze_play(all_clicks, all_ids, current_tick):
        # No clicks anywhere → nothing to do.
        if not all_clicks or all(not c for c in all_clicks):
            n = len(all_ids or [])
            return [no_update] * n, no_update, no_update

        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            n = len(all_ids or [])
            return [no_update] * n, no_update, no_update
        play_id = triggered.get("id")
        if not play_id:
            n = len(all_ids or [])
            return [no_update] * n, no_update, no_update

        loaded = SAVED_PLAYS.load(play_id)
        if not loaded or not loaded.get("playbook_obj"):
            n = len(all_ids or [])
            err = html.Div(
                f"Could not load play to re-analyze.",
                style={"color": "#EF4444"},
            )
            return [no_update] * n, no_update, err

        is_longterm = loaded.get("strategy_id") == LONGTERM_STRATEGY_ID

        if is_longterm:
            try:
                from tradingagents.scanner.longterm_viability import (
                    analyze_longterm_viability,
                )
                saved_score = (loaded.get("scan_row") or {}).get("score")
                verdict_dict = analyze_longterm_viability(
                    playbook=loaded["playbook_obj"],
                    saved_score=saved_score,
                )
            except Exception as exc:
                logger.exception("plays: longterm re-analyze raised")
                n = len(all_ids or [])
                err = html.Div(f"Long-term re-analyze failed: {exc}",
                               style={"color": "#EF4444"})
                return [no_update] * n, no_update, err
            SAVED_PLAYS.set_verdict(play_id, verdict_dict)
            verdict_status = verdict_dict["status"]
        else:
            try:
                inputs = _collect_viability_inputs(loaded)
            except Exception as exc:
                logger.exception("plays: snapshot collection failed")
                n = len(all_ids or [])
                err = html.Div(f"Snapshot fetch failed: {exc}",
                               style={"color": "#EF4444"})
                return [no_update] * n, no_update, err

            try:
                from tradingagents.scanner.viability import analyze_viability
                verdict = analyze_viability(
                    **inputs,
                    provider=loaded.get("provider") or None,
                    model=loaded.get("model") or None,
                )
            except Exception as exc:
                logger.exception("plays: analyze_viability raised")
                n = len(all_ids or [])
                err = html.Div(f"Re-analyze failed: {exc}",
                               style={"color": "#EF4444"})
                return [no_update] * n, no_update, err

            SAVED_PLAYS.set_verdict(play_id, verdict.to_dict())
            verdict_status = verdict.status

        # Clear all loading slots; bump tick so the grid re-renders.
        n = len(all_ids or [])
        clears = ["" for _ in range(n)]
        ok = html.Div(
            [
                html.Span("check_circle",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle", "color": "#22C55E"}),
                f"Verdict updated for {loaded.get('symbol', '')}: ",
                html.Strong(_VERDICT_LABELS.get(verdict_status, verdict_status)),
            ],
            style={"color": "#22C55E"},
        )
        return clears, int(current_tick or 0) + 1, ok

    # ── Delete ────────────────────────────────────────────────────

    @app.callback(
        [
            Output("plays-delete-modal", "is_open"),
            Output("plays-delete-body", "children"),
            Output("plays-pending-delete-id", "data"),
        ],
        Input({"type": "play-delete-btn", "id": ALL}, "n_clicks"),
        State({"type": "play-delete-btn", "id": ALL}, "id"),
        prevent_initial_call=True,
    )
    def open_delete_modal(all_clicks, _all_ids):
        if not all_clicks or all(not c for c in all_clicks):
            return no_update, no_update, no_update
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            return no_update, no_update, no_update
        play_id = triggered.get("id")
        if not play_id:
            return no_update, no_update, no_update

        loaded = SAVED_PLAYS.load(play_id)
        if not loaded:
            return no_update, no_update, no_update
        body = html.Div([
            html.Div(f"Delete saved play \"{loaded.get('label', '')}\"?",
                     style={"marginBottom": "8px", "fontSize": "14px"}),
            html.Div(f"Symbol: {loaded.get('symbol', '')}",
                     style={"color": "#94A3B8", "fontSize": "12px"}),
        ])
        return True, body, play_id

    @app.callback(
        [
            Output("plays-delete-modal", "is_open", allow_duplicate=True),
            Output("plays-tick", "data", allow_duplicate=True),
            Output("plays-status", "children", allow_duplicate=True),
        ],
        [
            Input("plays-delete-confirm-btn", "n_clicks"),
            Input("plays-delete-cancel-btn", "n_clicks"),
        ],
        [
            State("plays-pending-delete-id", "data"),
            State("plays-tick", "data"),
        ],
        prevent_initial_call=True,
    )
    def submit_delete(confirm_n, cancel_n, play_id, current_tick):
        triggered = ctx.triggered_id
        if triggered == "plays-delete-cancel-btn":
            return False, no_update, no_update
        if not confirm_n or not play_id:
            return no_update, no_update, no_update
        try:
            ok = SAVED_PLAYS.delete(play_id)
        except Exception as exc:
            logger.exception("plays: delete failed")
            return False, no_update, html.Div(
                f"Delete failed: {exc}", style={"color": "#EF4444"})
        msg = "Deleted." if ok else "Already gone."
        return False, int(current_tick or 0) + 1, html.Div(
            msg, style={"color": "#94A3B8", "fontStyle": "italic"})

    # ── Exit Now ──────────────────────────────────────────────────

    @app.callback(
        [
            Output("plays-exit-modal", "is_open"),
            Output("plays-exit-body", "children"),
            Output("plays-pending-exit-id", "data"),
        ],
        Input({"type": "play-exit-btn", "id": ALL}, "n_clicks"),
        State({"type": "play-exit-btn", "id": ALL}, "id"),
        prevent_initial_call=True,
    )
    def open_exit_modal(all_clicks, _all_ids):
        if not all_clicks or all(not c for c in all_clicks):
            return no_update, no_update, no_update
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            return no_update, no_update, no_update
        play_id = triggered.get("id")
        if not play_id:
            return no_update, no_update, no_update

        loaded = SAVED_PLAYS.load(play_id)
        if not loaded:
            return no_update, no_update, no_update
        symbol = loaded.get("symbol", "")
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            position = AlpacaUtils.get_position_with_brackets(symbol)
        except Exception as exc:
            return False, no_update, None  # no-op on lookup failure

        if not position:
            return False, no_update, None

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
                style={"marginBottom": "12px", "color": "#CBD5E1",
                       "fontSize": "13px"},
            ),
            html.Div([
                html.Div([html.Div("QTY", style=_label_style()),
                          html.Div(f"{qty:g} ({side})",
                                   style=_value_style())], style={"flex": "1"}),
                html.Div([html.Div("AVG ENTRY", style=_label_style()),
                          html.Div(f"${avg:,.2f}",
                                   style=_value_style())], style={"flex": "1"}),
                html.Div([html.Div("CURRENT", style=_label_style()),
                          html.Div(f"${cur:,.2f}",
                                   style=_value_style())], style={"flex": "1"}),
                html.Div([html.Div("UNREALIZED P/L", style=_label_style()),
                          html.Div(f"{sign}${pl:,.2f} ({sign}{plpc:.2f}%)",
                                   style={**_value_style(),
                                          "color": pl_color, "fontWeight": "700"})],
                         style={"flex": "1"}),
            ], style={"display": "flex", "gap": "12px"}),
        ])
        return True, body, play_id

    @app.callback(
        [
            Output("plays-exit-modal", "is_open", allow_duplicate=True),
            Output("plays-tick", "data", allow_duplicate=True),
            Output("plays-status", "children", allow_duplicate=True),
        ],
        [
            Input("plays-exit-confirm-btn", "n_clicks"),
            Input("plays-exit-cancel-btn", "n_clicks"),
        ],
        [
            State("plays-pending-exit-id", "data"),
            State("plays-tick", "data"),
        ],
        prevent_initial_call=True,
    )
    def submit_exit(confirm_n, cancel_n, play_id, current_tick):
        triggered = ctx.triggered_id
        if triggered == "plays-exit-cancel-btn":
            return False, no_update, no_update
        if not confirm_n or not play_id:
            return no_update, no_update, no_update
        loaded = SAVED_PLAYS.load(play_id)
        if not loaded:
            return False, no_update, html.Div("Play not found.",
                                              style={"color": "#EF4444"})
        symbol = loaded.get("symbol", "")
        from tradingagents.dataflows.alpaca_utils import AlpacaUtils

        try:
            AlpacaUtils.cancel_open_orders_for_symbol(symbol)
        except Exception as exc:
            logger.warning("cancel_open_orders_for_symbol failed: %s", exc)

        try:
            close = AlpacaUtils.close_position(symbol)
        except Exception as exc:
            logger.exception("close_position failed")
            return False, no_update, html.Div(
                f"Exit failed: {exc}", style={"color": "#EF4444"})

        if not close.get("success"):
            return False, no_update, html.Div(
                f"Exit failed: {close.get('error') or 'unknown'}",
                style={"color": "#EF4444"})

        ok = html.Div(
            [
                html.Span("check_circle",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle", "color": "#22C55E"}),
                f"Exited {symbol} (Alpaca id ",
                html.Code(str(close.get("order_id") or "?")),
                ").",
            ],
            style={"color": "#22C55E"},
        )
        return False, int(current_tick or 0) + 1, ok

    # ── Cancel Pending Order ──────────────────────────────────────

    @app.callback(
        [
            Output("plays-cancel-order-modal", "is_open"),
            Output("plays-cancel-order-body", "children"),
            Output("plays-pending-cancel-id", "data"),
        ],
        Input({"type": "play-cancel-btn", "id": ALL}, "n_clicks"),
        State({"type": "play-cancel-btn", "id": ALL}, "id"),
        prevent_initial_call=True,
    )
    def open_cancel_modal(all_clicks, _all_ids):
        if not all_clicks or all(not c for c in all_clicks):
            return no_update, no_update, no_update
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            return no_update, no_update, no_update
        play_id = triggered.get("id")
        if not play_id:
            return no_update, no_update, no_update

        loaded = SAVED_PLAYS.load(play_id)
        if not loaded:
            return no_update, no_update, no_update
        symbol = loaded.get("symbol", "")
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            unfilled = AlpacaUtils.get_unfilled_scanner_orders(symbol)
        except Exception as exc:
            logger.exception("plays: unfilled lookup failed")
            return False, no_update, None
        if not unfilled:
            return False, no_update, None

        body = html.Div([
            html.Div(
                f"Cancel {len(unfilled)} pending order(s) for {symbol}? "
                "Bracket children auto-cancel with the parent.",
                style={"marginBottom": "10px", "color": "#CBD5E1",
                       "fontSize": "13px"},
            ),
        ] + [
            html.Div(
                f"{(o.get('side') or '').upper()} {o.get('qty', 0):g} "
                f"{o.get('order_type', '')} · status {o.get('status', '?')}",
                style={"fontSize": "12px", "color": "#94A3B8",
                       "padding": "4px 0"},
            )
            for o in unfilled
        ])
        return True, body, play_id

    @app.callback(
        [
            Output("plays-cancel-order-modal", "is_open", allow_duplicate=True),
            Output("plays-tick", "data", allow_duplicate=True),
            Output("plays-status", "children", allow_duplicate=True),
        ],
        [
            Input("plays-cancel-order-confirm-btn", "n_clicks"),
            Input("plays-cancel-order-cancel-btn", "n_clicks"),
        ],
        [
            State("plays-pending-cancel-id", "data"),
            State("plays-tick", "data"),
        ],
        prevent_initial_call=True,
    )
    def submit_cancel(confirm_n, cancel_n, play_id, current_tick):
        triggered = ctx.triggered_id
        if triggered == "plays-cancel-order-cancel-btn":
            return False, no_update, no_update
        if not confirm_n or not play_id:
            return no_update, no_update, no_update
        loaded = SAVED_PLAYS.load(play_id)
        if not loaded:
            return False, no_update, no_update
        symbol = loaded.get("symbol", "")
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            result = AlpacaUtils.cancel_unfilled_scanner_order(symbol)
        except Exception as exc:
            logger.exception("plays: cancel failed")
            return False, no_update, html.Div(
                f"Cancel failed: {exc}", style={"color": "#EF4444"})

        cancelled = int(result.get("cancelled") or 0)
        if cancelled == 0 and not result.get("success"):
            return False, no_update, html.Div(
                f"No pending order found for {symbol}.",
                style={"color": "#94A3B8"})

        ok = html.Div(
            [
                html.Span("check_circle",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle", "color": "#22C55E"}),
                f"Cancelled {cancelled} order(s) for {symbol}.",
            ],
            style={"color": "#22C55E"},
        )
        return False, int(current_tick or 0) + 1, ok

    # ── Execute (Paper) — submit a bracket from a saved playbook ──

    @app.callback(
        [
            Output("plays-execute-modal", "is_open"),
            Output("plays-execute-body", "children"),
            Output("plays-pending-execute", "data"),
            Output("plays-status", "children", allow_duplicate=True),
        ],
        Input({"type": "play-execute-btn", "id": ALL}, "n_clicks"),
        State({"type": "play-execute-btn", "id": ALL}, "id"),
        prevent_initial_call=True,
    )
    def open_execute_modal(all_clicks, _all_ids):
        if not all_clicks or all(not c for c in all_clicks):
            return no_update, no_update, no_update, no_update
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            return no_update, no_update, no_update, no_update
        play_id = triggered.get("id")
        if not play_id:
            return no_update, no_update, no_update, no_update

        loaded = SAVED_PLAYS.load(play_id)
        if not loaded or not loaded.get("playbook_obj"):
            return False, no_update, None, html.Div(
                "Could not load play to execute.", style={"color": "#EF4444"},
            )

        # Long-term plays don't have entry_price/stop_loss/PT — block at the boundary.
        if loaded.get("strategy_id") == LONGTERM_STRATEGY_ID:
            return False, no_update, None, html.Div(
                "Long-term plays use DCA, not bracket orders. Execute is not supported.",
                style={"color": "#F59E0B"},
            )

        pb = loaded["playbook_obj"]
        symbol = loaded.get("symbol", "")
        if "/" in symbol:
            return False, no_update, None, html.Div(
                "Crypto execution not yet supported.",
                style={"color": "#F59E0B"},
            )

        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            from tradingagents.scanner.execution import compute_scanner_position_size
            account = AlpacaUtils.get_account_info()
            buying_power = float(account.get("buying_power") or 0.0)
        except Exception as exc:
            logger.exception("plays: account lookup failed")
            return False, no_update, None, html.Div(
                f"Could not read Alpaca account: {exc}",
                style={"color": "#EF4444"},
            )

        qty = compute_scanner_position_size(
            buying_power=buying_power,
            position_size_pct=pb.position_size_pct,
            entry_price=pb.entry_price,
        )
        if qty <= 0:
            return False, no_update, None, html.Div(
                f"Insufficient buying power for {pb.position_size_pct * 100:.1f}% "
                f"of ${buying_power:,.2f} at ${pb.entry_price:.2f}/share — "
                "qty rounded to 0.",
                style={"color": "#EF4444"},
            )

        est_cost = qty * pb.entry_price
        body = html.Div([
            html.Div(f"{symbol} — {pb.strategy_id}",
                     style={"fontSize": "16px", "fontWeight": "700",
                            "marginBottom": "12px"}),
            html.Div([
                html.Div([html.Span("Order: ", style={"color": "#94A3B8"}),
                          html.Span(pb.order_type,
                                    style={"fontWeight": "600", "color": "#60A5FA"})]),
                html.Div([html.Span("Quantity: ", style={"color": "#94A3B8"}),
                          html.Span(f"{qty} shares",
                                    style={"fontWeight": "600"})]),
                html.Div([html.Span("Entry: ", style={"color": "#94A3B8"}),
                          html.Span(f"${pb.entry_price:.2f}",
                                    style={"fontWeight": "600"})]),
                html.Div([html.Span("Stop: ", style={"color": "#94A3B8"}),
                          html.Span(f"${pb.stop_loss:.2f}",
                                    style={"color": "#EF4444",
                                           "fontWeight": "600"})]),
                html.Div([html.Span("Take profit (PT1): ", style={"color": "#94A3B8"}),
                          html.Span(f"${pb.profit_target_1:.2f}",
                                    style={"color": "#22C55E",
                                           "fontWeight": "600"})]),
                html.Div([html.Span("PT2 (reference, manual): ", style={"color": "#94A3B8"}),
                          html.Span(f"${pb.profit_target_2:.2f}",
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
        pending = {"play_id": play_id, "qty": qty}
        return True, body, pending, ""

    _exec_busy_children = [
        html.Span(className="spinner-border spinner-border-sm me-2",
                  role="status", **{"aria-hidden": "true"}),
        "Submitting...",
    ]

    @app.callback(
        [
            Output("plays-execute-modal", "is_open", allow_duplicate=True),
            Output("plays-pending-execute", "data", allow_duplicate=True),
            Output("plays-tick", "data", allow_duplicate=True),
            Output("plays-status", "children", allow_duplicate=True),
        ],
        [
            Input("plays-execute-confirm-btn", "n_clicks"),
            Input("plays-execute-cancel-btn", "n_clicks"),
        ],
        [
            State("plays-pending-execute", "data"),
            State("plays-tick", "data"),
        ],
        running=[
            (Output("plays-execute-confirm-btn", "disabled"), True, False),
            (Output("plays-execute-confirm-btn", "children"),
             _exec_busy_children, "Confirm & Submit"),
        ],
        prevent_initial_call=True,
    )
    def submit_execute(confirm_n, cancel_n, pending, current_tick):
        triggered = ctx.triggered_id
        if triggered == "plays-execute-cancel-btn":
            return False, None, no_update, no_update
        if not confirm_n or not pending:
            return no_update, no_update, no_update, no_update

        play_id = pending.get("play_id")
        if not play_id:
            return False, None, no_update, html.Div(
                "Missing play id — re-open the confirm dialog.",
                style={"color": "#F59E0B"},
            )

        loaded = SAVED_PLAYS.load(play_id)
        if not loaded or not loaded.get("playbook_obj"):
            return False, None, no_update, html.Div(
                "Play could not be loaded — try Re-analyze first.",
                style={"color": "#EF4444"},
            )

        playbook = loaded["playbook_obj"]
        try:
            from tradingagents.scanner.execution import execute_playbook_paper
            result = execute_playbook_paper(playbook)
        except Exception as exc:
            logger.exception("plays: execute_playbook_paper raised")
            return False, None, no_update, html.Div(
                f"Execution failed: {exc}", style={"color": "#EF4444"})

        if not result.success:
            return False, None, no_update, html.Div(
                f"Execution rejected: {result.error or 'unknown'}",
                style={"color": "#EF4444"},
            )

        # Link the freshly submitted Alpaca order back into the saved play
        # so the Cancel/Exit flows can find it later.
        try:
            SAVED_PLAYS.set_linked_alpaca(play_id, {
                "client_order_id": result.client_order_id,
                "alpaca_order_id": result.alpaca_order_id,
            })
        except Exception as exc:
            logger.warning("plays: linked_alpaca persist failed: %s", exc)

        ok = html.Div(
            [
                html.Span("check_circle",
                          className="material-symbols-outlined me-1",
                          style={"verticalAlign": "middle", "color": "#22C55E"}),
                f"Submitted {result.qty} shares of {loaded.get('symbol', '')} — "
                "Alpaca id ",
                html.Code(result.alpaca_order_id or "?",
                          style={"backgroundColor": "rgba(15,23,42,0.6)",
                                 "padding": "1px 6px", "borderRadius": "3px"}),
                ".",
            ],
            style={"color": "#22C55E"},
        )
        return False, None, int(current_tick or 0) + 1, ok

    # ── Show / Hide Chart toggle ──────────────────────────────────

    @app.callback(
        [
            Output({"type": "play-chart-wrapper", "id": ALL}, "style"),
            Output({"type": "play-chart-toggle-btn", "id": ALL}, "children"),
        ],
        Input({"type": "play-chart-toggle-btn", "id": ALL}, "n_clicks"),
        [
            State({"type": "play-chart-toggle-btn", "id": ALL}, "id"),
            State({"type": "play-chart-wrapper", "id": ALL}, "style"),
        ],
        prevent_initial_call=True,
    )
    def toggle_chart(all_clicks, all_ids, all_styles):
        n = len(all_ids or [])
        if not all_clicks or all(not c for c in all_clicks):
            return [no_update] * n, [no_update] * n
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            return [no_update] * n, [no_update] * n
        target_id = triggered.get("id")

        new_styles: list = []
        new_labels: list = []
        for i, cb_id in enumerate(all_ids):
            if cb_id.get("id") != target_id:
                new_styles.append(no_update)
                new_labels.append(no_update)
                continue
            current = all_styles[i] or {}
            is_visible = current.get("display") == "block"
            if is_visible:
                next_style = {**current, "display": "none"}
                label = [
                    html.Span("show_chart",
                              className="material-symbols-outlined me-1",
                              style={"fontSize": "16px", "verticalAlign": "middle"}),
                    "Show Chart",
                ]
            else:
                next_style = {**current, "display": "block", "marginTop": "12px"}
                label = [
                    html.Span("visibility_off",
                              className="material-symbols-outlined me-1",
                              style={"fontSize": "16px", "verticalAlign": "middle"}),
                    "Hide Chart",
                ]
            new_styles.append(next_style)
            new_labels.append(label)
        return new_styles, new_labels

    # ── Build chart payload (lazy: only when visible) ─────────────

    @app.callback(
        Output({"type": "play-chart-payload", "id": ALL}, "data"),
        [
            Input({"type": "play-chart-wrapper", "id": ALL}, "style"),
            Input({"type": "play-chart-timeframe", "id": ALL}, "value"),
            Input("plays-tick", "data"),
        ],
        State({"type": "play-chart-payload", "id": ALL}, "id"),
        prevent_initial_call=True,
    )
    def build_chart_payloads(all_styles, all_tfs, _tick, payload_ids):
        n = len(payload_ids or [])
        if not n:
            return []
        out: list = []
        for i, pid in enumerate(payload_ids):
            style = all_styles[i] if i < len(all_styles) else None
            if not style or style.get("display") != "block":
                # Not expanded — skip the bar fetch entirely.
                out.append(no_update)
                continue
            play_id = pid.get("id")
            timeframe = all_tfs[i] if i < len(all_tfs) else "5m"
            try:
                loaded = SAVED_PLAYS.load(play_id)
                if not loaded or not loaded.get("playbook_obj"):
                    out.append(no_update)
                    continue
                pb = loaded["playbook_obj"]
                symbol = loaded.get("symbol", "")
                is_lt = loaded.get("strategy_id") == LONGTERM_STRATEGY_ID

                if is_lt:
                    # Long-term: entry zone band + 3y target. No live position
                    # lines (DCA, no brackets). No fills (no scanner orders).
                    overlay_levels = {
                        "entry": pb.entry_zone_low,
                        "pt1": pb.entry_zone_high,
                        "pt2": pb.target_price_3y,
                    }
                    position_levels = None
                    fills = []
                else:
                    overlay_levels = {
                        "entry": pb.entry_price,
                        "stop": pb.stop_loss,
                        "pt1": pb.profit_target_1,
                        "pt2": pb.profit_target_2,
                    }
                    # Live position lines (best-effort).
                    position_levels = None
                    fills = []
                    try:
                        from tradingagents.dataflows.alpaca_utils import AlpacaUtils
                        pos = AlpacaUtils.get_position_with_brackets(symbol)
                        if pos:
                            position_levels = {
                                "avg": pos.get("avg_entry_price"),
                                "tp": pos.get("take_profit"),
                                "sl": pos.get("stop_loss"),
                            }
                        fills = AlpacaUtils.get_scanner_orders(
                            symbol=symbol, since_minutes=600,
                        ) or []
                    except Exception as exc:
                        logger.debug("plays: chart live state for %s: %s", symbol, exc)

                from webui.utils.charts_lwc import build_lwc_payload
                payload = build_lwc_payload(
                    symbol,
                    period=timeframe or ("1y" if is_lt else "5m"),
                    overlay_levels=overlay_levels,
                    position_levels=position_levels,
                    fills=fills,
                )
                out.append(payload)
            except Exception as exc:
                logger.exception("plays: chart payload build failed")
                out.append(no_update)
        return out

    # ── Clientside: render LWC into the per-card chart div ────────

    app.clientside_callback(
        """
        function(payloads, ids) {
            if (!payloads || !ids) return window.dash_clientside.no_update;
            for (let i = 0; i < payloads.length; i++) {
                const payload = payloads[i];
                if (!payload) continue;
                const cbId = ids[i];
                if (!cbId) continue;
                // Dash serializes pattern-matched IDs as JSON with sorted keys.
                const sortedKeys = Object.keys(cbId).sort();
                const sortedObj = {};
                for (const k of sortedKeys) sortedObj[k] = cbId[k];
                const domId = JSON.stringify(sortedObj);
                if (window.lwcRender) {
                    window.lwcRender(domId, payload);
                }
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output({"type": "play-chart", "id": ALL}, "data-lwc-rendered"),
        Input({"type": "play-chart-payload", "id": ALL}, "data"),
        State({"type": "play-chart", "id": ALL}, "id"),
    )
