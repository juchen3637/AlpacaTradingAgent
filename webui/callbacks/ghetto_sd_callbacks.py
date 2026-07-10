"""webui/callbacks/ghetto_sd_callbacks.py - Callbacks for the Ghetto SD analyzer tab."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

import dash_bootstrap_components as dbc
from dash import ALL, Input, Output, State, ctx, html, no_update

from tradingagents.analytics.ghetto_sd import (
    AnalysisInput,
    ExpirationClass,
    GhettoSDConfig,
    analyze,
    atm_from_chain,
    candidate_contracts,
    classify_expiration,
    pick_best_strangle,
)
from tradingagents.analytics.ghetto_sd_exec import (
    estimate_text as _estimate_text,
    scan_legs_map as _scan_legs_map,
    strangle_payload as _strangle_payload,
)

logger = logging.getLogger(__name__)

_CFG = GhettoSDConfig.default()

_VERDICT_COLOR = {
    "Valid Play": "#22C55E",
    "Borderline": "#F59E0B",
    "Too Expensive": "#EF4444",
    "Too Far OTM": "#64748B",
}
_WARN_STYLE = {
    "critical": {"bg": "rgba(239,68,68,0.15)", "border": "#EF4444", "icon": "error"},
    "warning": {"bg": "rgba(245,158,11,0.12)", "border": "#F59E0B", "icon": "warning"},
    "info": {"bg": "rgba(56,189,248,0.10)", "border": "#38BDF8", "icon": "info"},
}
# Candidate strikes within this % of the relevant 2SD target are shown in the screener.
_SHOPPING_BAND_PCT = 15.0

# Boundary validation: tickers are 1-6 alphanumerics; numeric inputs are sane.
_TICKER_RE = re.compile(r"^[A-Z]{1,6}$")
_MAX_NUMERIC = 1_000_000.0


def _validate_ticker(ticker: str | None) -> str | None:
    if not ticker:
        return None
    t = ticker.strip().upper()
    return t if _TICKER_RE.match(t) else None


def _valid_numeric(value) -> bool:
    """True if value is a positive, finite number within sane bounds."""
    if value is None:
        return False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return 0 < v < _MAX_NUMERIC


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _expiration_label(exp: date, earnings: date | None, today: date) -> str:
    info = classify_expiration(exp, earnings, today, cfg=_CFG)
    if info.classification is ExpirationClass.INVALID:
        return f"{exp.isoformat()} 🚫 0 DTE (invalid)"
    if info.classification is ExpirationClass.IDEAL:
        return f"{exp.isoformat()} ✅ ideal ({info.days_to_expiry}d)"
    return f"{exp.isoformat()} ⚠️ {info.days_to_expiry}d"


def register_ghetto_sd_callbacks(app):
    _load_busy = [html.Span("Loading…")]
    _load_idle = [html.Span("download", className="material-symbols-outlined me-1",
                            style={"fontSize": "18px", "verticalAlign": "middle"}), "Load Options Chain"]

    @app.callback(
        [
            Output("gsd-expiration", "options"),
            Output("gsd-expiration", "value"),
            Output("gsd-current-price", "value"),
            Output("gsd-load-status", "children"),
            Output("gsd-chain-store", "data"),
        ],
        Input("gsd-load-btn", "n_clicks"),
        [State("gsd-ticker", "value"), State("gsd-earnings-date", "date")],
        running=[
            (Output("gsd-load-btn", "disabled"), True, False),
            (Output("gsd-load-btn", "children"), _load_busy, _load_idle),
        ],
        prevent_initial_call=True,
    )
    def load_chain(n_clicks, ticker, earnings_date):
        if not n_clicks:
            return no_update, no_update, no_update, no_update, no_update
        ticker = _validate_ticker(ticker)
        if not ticker:
            return [], None, no_update, "Enter a valid ticker (1-6 letters).", no_update

        today = datetime.now().date()
        earnings = _parse_date(earnings_date)

        # Current price (mid of latest quote).
        price = None
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            q = AlpacaUtils.get_latest_quote(ticker)
            if q.get("bid_price") and q.get("ask_price"):
                price = round((q["bid_price"] + q["ask_price"]) / 2, 2)
        except Exception:
            logger.exception("price fetch failed for %s", ticker)

        # Available expirations.
        try:
            from tradingagents.dataflows.options_utils import get_option_expirations
            exp_strings = get_option_expirations(ticker)
        except Exception:
            logger.exception("expiration fetch failed for %s", ticker)
            status = html.Span(
                "Options chain unavailable. Enter quotes manually and click Analyze.",
                style={"color": "#F59E0B"},
            )
            return [], None, price, status, {"ticker": ticker}

        options = []
        for s in exp_strings:
            d = _parse_date(s)
            if d:
                options.append({"label": _expiration_label(d, earnings, today), "value": s})

        ideal_value = None
        if earnings:
            from tradingagents.analytics.ghetto_sd import select_ideal_expiration
            ideal = select_ideal_expiration([_parse_date(s) for s in exp_strings if _parse_date(s)],
                                            earnings, today, cfg=_CFG)
            ideal_value = ideal.isoformat() if ideal else None

        status = html.Span(
            f"Loaded {len(options)} expirations for {ticker}"
            + (f" · price ${price:.2f}" if price else " · price unavailable (enter manually)"),
            style={"color": "#22C55E" if options else "#F59E0B"},
        )
        return options, ideal_value or (options[0]["value"] if options else None), price, status, {"ticker": ticker}

    @app.callback(
        [Output("gsd-warnings", "children"), Output("gsd-results-panel", "children"),
         Output("gsd-analyze-legs-store", "data")],
        Input("gsd-analyze-btn", "n_clicks"),
        [
            State("gsd-ticker", "value"),
            State("gsd-earnings-date", "date"),
            State("gsd-expiration", "value"),
            State("gsd-current-price", "value"),
            State("gsd-call-ask", "value"),
            State("gsd-put-ask", "value"),
        ],
        running=[
            (Output("gsd-analyze-btn", "disabled"), True, False),
        ],
        prevent_initial_call=True,
    )
    def run_analysis(n_clicks, ticker, earnings_date, expiration, price_override, call_override, put_override):
        if not n_clicks:
            return no_update, no_update, no_update
        ticker = _validate_ticker(ticker)
        if not ticker:
            return _error("Enter a valid ticker (1-6 letters)."), no_update, no_update
        exp_date = _parse_date(expiration)
        if exp_date is None:
            return _error("Select a valid expiration (or load the chain)."), no_update, no_update
        for label, override in (("price", price_override), ("call ask", call_override),
                                ("put ask", put_override)):
            if override is not None and not _valid_numeric(override):
                return _error(f"{label.capitalize()} override out of valid range."), no_update, no_update

        today = datetime.now().date()
        earnings = _parse_date(earnings_date)

        # Resolve current price: override wins, else fetch mid.
        price = price_override if _valid_numeric(price_override) else None
        if not price:
            try:
                from tradingagents.dataflows.alpaca_utils import AlpacaUtils
                q = AlpacaUtils.get_latest_quote(ticker)
                if q.get("bid_price") and q.get("ask_price"):
                    price = round((q["bid_price"] + q["ask_price"]) / 2, 2)
            except Exception:
                logger.exception("price fetch failed for %s", ticker)
        if not price:
            return _error("No current price — enter it in the override field."), no_update, no_update

        # Pull live chain (best-effort) for ATM quotes + candidate contracts.
        chain: list[dict] = []
        try:
            from tradingagents.dataflows.options_utils import get_option_chain_quotes
            chain = get_option_chain_quotes(ticker, expiration)
        except Exception:
            logger.exception("chain fetch failed for %s %s", ticker, expiration)

        atm_strike, call_ask, put_ask = _resolve_atm(chain, float(price), call_override, put_override)
        if call_ask is None or put_ask is None:
            return _error(
                "Missing ATM call/put ask. Fill the override fields to compute manually."
            ), no_update, no_update

        sd_preview = float(call_ask) + float(put_ask)
        contracts = candidate_contracts(chain, float(price), sd_preview, band_pct=_SHOPPING_BAND_PCT)

        inp = AnalysisInput(
            ticker=ticker,
            current_price=float(price),
            earnings_date=earnings,
            today=today,
            expiry_date=exp_date,
            has_e_badge=bool(earnings) and classify_expiration(
                exp_date, earnings, today, cfg=_CFG).classification is ExpirationClass.IDEAL,
            atm_strike=float(atm_strike),
            atm_call_ask=float(call_ask),
            atm_put_ask=float(put_ask),
            contracts=tuple(contracts),
        )
        result = analyze(inp, cfg=_CFG)
        call_leg, put_leg = pick_best_strangle(result)
        legs = _strangle_payload(ticker, call_leg, put_leg)
        return _render_warnings(result.warnings), _render_results(result, legs), legs

    _scan_busy = [html.Span("Scanning…")]
    _scan_idle = [html.Span("radar", className="material-symbols-outlined me-1",
                            style={"fontSize": "18px", "verticalAlign": "middle"}), "Scan Most-Actives"]

    @app.callback(
        [Output("gsd-scan-status", "children"), Output("gsd-scan-results", "children"),
         Output("gsd-scan-legs-store", "data")],
        Input("gsd-scan-btn", "n_clicks"),
        [State("gsd-scan-min-suit", "value"), State("gsd-scan-min-price", "value"),
         State("gsd-scan-size", "value")],
        running=[
            (Output("gsd-scan-btn", "disabled"), True, False),
            (Output("gsd-scan-btn", "children"), _scan_busy, _scan_idle),
        ],
        prevent_initial_call=True,
    )
    def scan_qualifying(n_clicks, min_suit, min_price, universe_size):
        if not n_clicks:
            return no_update, no_update, no_update

        from tradingagents.analytics.ghetto_sd import ScanCriteria
        from tradingagents.analytics.ghetto_sd_scanner import scan_most_actives

        criteria = ScanCriteria.default()
        if min_suit is not None and 1 <= int(min_suit) <= 10:
            criteria = ScanCriteria(min_suitability=int(min_suit),
                                    max_2sd_cost=criteria.max_2sd_cost)
        limit = int(universe_size) if universe_size and int(universe_size) > 0 else None
        floor = float(min_price) if _valid_numeric(min_price) or min_price == 0 else None

        today = datetime.now().date()
        try:
            results = scan_most_actives(today, limit=limit, criteria=criteria, min_price=floor)
        except Exception:
            logger.exception("ghetto SD scan failed")
            return (html.Span("Scan failed — check Alpaca credentials and try again.",
                              style={"color": "#EF4444"}), None, no_update)

        from tradingagents.default_config import DEFAULT_CONFIG
        floor_shown = floor if floor is not None else DEFAULT_CONFIG["ghetto_sd_scan"]["min_price"]
        status = html.Span(
            f"{len(results)} qualifying "
            f"ticker{'s' if len(results) != 1 else ''} "
            f"(price ≥ ${floor_shown:.0f}, suitability ≥ {criteria.min_suitability}, "
            f"2SD cost ≤ ${criteria.max_2sd_cost:.0f}).",
            style={"color": "#22C55E" if results else "#F59E0B"},
        )
        return status, _render_scan_table(results), _scan_legs_map(results)

    # ─── Strangle execution ─────────────────────────────────────────────

    @app.callback(
        [Output("gsd-exec-modal", "is_open"),
         Output("gsd-exec-store", "data"),
         Output("gsd-exec-title", "children"),
         Output("gsd-exec-env-badge", "children"),
         Output("gsd-exec-call-symbol", "children"),
         Output("gsd-exec-put-symbol", "children"),
         Output("gsd-exec-call-limit", "value"),
         Output("gsd-exec-put-limit", "value"),
         Output("gsd-exec-qty", "value"),
         Output("gsd-exec-estimate", "children"),
         Output("gsd-exec-result", "children")],
        [Input({"type": "gsd-trade-btn", "index": ALL}, "n_clicks"),
         Input("gsd-exec-cancel", "n_clicks")],
        [State("gsd-analyze-legs-store", "data"),
         State("gsd-scan-legs-store", "data")],
        prevent_initial_call=True,
    )
    def toggle_exec_modal(trade_clicks, cancel_clicks, analyze_legs, scan_legs):
        trig = ctx.triggered_id
        value = ctx.triggered[0]["value"] if ctx.triggered else None
        if trig is None or value in (None, 0):  # spurious fire (e.g. table re-render)
            return [no_update] * 11
        if trig == "gsd-exec-cancel":
            return [False] + [no_update] * 10

        if isinstance(trig, dict) and trig.get("type") == "gsd-trade-btn":
            idx = trig.get("index")
            payload = analyze_legs if idx == "__analyze__" else (scan_legs or {}).get(idx)
        else:
            payload = None
        if not payload:
            return [no_update] * 11

        call, put = payload["call"], payload["put"]
        call_limit, put_limit = round(call["ask"], 2), round(put["ask"], 2)
        call_disp = f"{call['symbol']}  ·  strike ${call['strike']:g}"
        put_disp = f"{put['symbol']}  ·  strike ${put['strike']:g}"
        return (
            True, payload, payload["ticker"], _env_badge(),
            call_disp, put_disp, call_limit, put_limit, 1,
            _estimate_text(call_limit, put_limit, 1), None,
        )

    @app.callback(
        Output("gsd-exec-estimate", "children", allow_duplicate=True),
        [Input("gsd-exec-qty", "value"), Input("gsd-exec-call-limit", "value"),
         Input("gsd-exec-put-limit", "value")],
        prevent_initial_call=True,
    )
    def update_estimate(qty, call_limit, put_limit):
        return _estimate_text(call_limit, put_limit, qty)

    @app.callback(
        Output("gsd-exec-result", "children", allow_duplicate=True),
        Input("gsd-exec-confirm", "n_clicks"),
        [State("gsd-exec-store", "data"), State("gsd-exec-qty", "value"),
         State("gsd-exec-call-limit", "value"), State("gsd-exec-put-limit", "value")],
        running=[(Output("gsd-exec-confirm", "disabled"), True, False)],
        prevent_initial_call=True,
    )
    def submit_strangle(n_clicks, store, qty, call_limit, put_limit):
        if not n_clicks or not store:
            return no_update
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            return _error("Enter a whole number of contracts.")
        if qty <= 0:
            return _error("Quantity must be at least 1.")
        if not _valid_numeric(call_limit) or not _valid_numeric(put_limit):
            return _error("Enter valid positive limit prices for both legs.")

        from tradingagents.dataflows.alpaca_utils import AlpacaUtils
        res = AlpacaUtils.place_strangle(
            call_symbol=store["call"]["symbol"], call_limit=float(call_limit),
            put_symbol=store["put"]["symbol"], put_limit=float(put_limit), qty=qty,
        )
        _record_strangle(store, res, qty, float(call_limit), float(put_limit))
        return _render_order_result(res)


# ─── Strangle execution helpers ─────────────────────────────────────────


def _is_paper() -> bool:
    from tradingagents.dataflows.config import get_alpaca_use_paper
    val = get_alpaca_use_paper()
    return val.lower() == "true" if val else True


def _env_badge():
    paper = _is_paper()
    text, bg, border = (
        ("PAPER TRADING", "rgba(34,197,94,0.15)", "#22C55E") if paper
        else ("● LIVE TRADING — REAL MONEY", "rgba(239,68,68,0.18)", "#EF4444")
    )
    return html.Div(text, style={
        "backgroundColor": bg, "border": f"1px solid {border}", "color": "#F1F5F9",
        "borderRadius": "6px", "padding": "6px 10px", "fontSize": "12px", "fontWeight": "700",
        "textAlign": "center",
    })


def _record_strangle(store, res, qty, call_limit, put_limit):
    """Persist a submitted strangle to the trade journal (source='ghetto_sd')."""
    from datetime import datetime, timezone

    from tradingagents.analytics import get_journal
    from tradingagents.analytics.ghetto_sd_journal import build_strangle_records

    try:
        built = build_strangle_records(
            store, res, qty=qty, call_limit=call_limit, put_limit=put_limit,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        if built is None:
            return
        decision, trades = built
        journal = get_journal()
        decision_id = journal.record_decision(decision)
        for trade in trades:
            journal.record_trade(_with_decision_id(trade, decision_id))
    except Exception as e:
        print(f"[GHETTO SD] Failed to journal strangle: {e}")


def _with_decision_id(trade, decision_id):
    from dataclasses import replace
    return replace(trade, decision_id=decision_id)


def _render_order_result(legs: dict):
    """Render the per-leg submit outcome from AlpacaUtils.place_strangle."""
    rows = []
    for label, res in (("Call", legs.get("call", {})), ("Put", legs.get("put", {}))):
        ok = res.get("success")
        color = "#22C55E" if ok else "#EF4444"
        msg = res.get("message") if ok else res.get("error", "unknown error")
        rows.append(html.Div([
            html.Span(f"{'✅' if ok else '❌'} {label}: ", style={"fontWeight": "700", "color": color}),
            html.Span(msg, style={"fontSize": "12px", "color": "#CBD5E1"}),
        ], style={"marginBottom": "4px"}))
    return html.Div(rows, style={"borderTop": "1px solid #1E293B", "paddingTop": "8px"})


# ─── Resolution helpers ─────────────────────────────────────────────────


def _resolve_atm(chain, price, call_override, put_override):
    """ATM strike + call/put asks; overrides take precedence over chain data."""
    atm, chain_call, chain_put = atm_from_chain(chain, price)
    call_ask = call_override if call_override is not None else chain_call
    put_ask = put_override if put_override is not None else chain_put
    return atm, call_ask, put_ask


# ─── Rendering ──────────────────────────────────────────────────────────


def _error(msg: str):
    return html.Div(msg, style={"color": "#EF4444", "fontSize": "13px", "padding": "12px 0"})


def _earnings_cell(earnings_date, expiry_date, today):
    """Whether earnings are coming up, and whether the strangle's expiry captures them."""
    if earnings_date is None:
        return html.Span("none scheduled", style={"color": "#64748B", "fontSize": "11px"})
    days = (earnings_date - today).days
    within = today <= earnings_date <= expiry_date
    color = "#22C55E" if within else "#94A3B8"
    note = "⚡ before expiry" if within else ("past" if days < 0 else "after expiry")
    return html.Div([
        html.Div(f"{earnings_date.isoformat()} ({days:+d}d)",
                 style={"color": color, "fontWeight": "600"}),
        html.Div(note, style={"fontSize": "10px", "color": color}),
    ])


def _render_scan_table(results):
    if not results:
        return html.Div(
            "No tickers qualified. Loosen the gates (lower min suitability) or try again "
            "during market hours when option quotes are live.",
            style={"fontSize": "12px", "color": "#64748B", "padding": "8px 0"},
        )
    header = html.Thead(html.Tr([
        html.Th(c) for c in
        ["Ticker", "Price", "Expiry", "DTE", "Earnings", "±1SD", "Call leg", "Put leg",
         "Strangle $", "Suit.", ""]
    ]))
    today = datetime.now().date()
    rows = []
    for c in results:
        sd = c.analysis.sd
        exp = c.analysis.expiration
        call_leg, put_leg = c.call_leg, c.put_leg
        call_txt = f"${call_leg.strike:g} (${call_leg.cost_per_contract:.0f})" if call_leg else "—"
        put_txt = f"${put_leg.strike:g} (${put_leg.cost_per_contract:.0f})" if put_leg else "—"
        strangle = f"${c.strangle_cost:.0f}" if c.strangle_cost is not None else "—"
        score_color = "#22C55E" if c.analysis.suitability.score >= 7 else "#F59E0B"
        tradeable = c.call_leg is not None and c.put_leg is not None
        trade_btn = dbc.Button(
            "Trade", id={"type": "gsd-trade-btn", "index": c.ticker},
            size="sm", color="success", outline=True, disabled=not tradeable,
            style={"fontSize": "11px", "padding": "2px 10px"},
        )
        rows.append(html.Tr([
            html.Td(html.Span(c.ticker, style={"fontWeight": "700", "color": "#F1F5F9"})),
            html.Td(f"${c.price:.2f}"),
            html.Td(exp.expiry_date.isoformat()),
            html.Td(f"{exp.days_to_expiry}d"),
            html.Td(_earnings_cell(c.earnings_date, exp.expiry_date, today)),
            html.Td(f"±{sd.one_sd_pct:.1f}%" if sd else "—"),
            html.Td(call_txt),
            html.Td(put_txt),
            html.Td(html.Span(strangle, style={"fontWeight": "700", "color": "#F1F5F9"})),
            html.Td(html.Span(f"{c.analysis.suitability.score}/10",
                              style={"color": score_color, "fontWeight": "700"})),
            html.Td(trade_btn),
        ]))
    return dbc.Card(dbc.CardBody([
        dbc.Table([header, html.Tbody(rows)], bordered=False, hover=True, responsive=True,
                  style={"color": "#E2E8F0", "fontSize": "13px"}),
    ]), style={"backgroundColor": "rgba(15,23,42,0.8)", "border": "1px solid #1E293B",
               "marginTop": "8px"})


def _render_warnings(warnings):
    if not warnings:
        return None
    banners = []
    for w in warnings:
        st = _WARN_STYLE[w.level]
        banners.append(html.Div(
            [
                html.Span(st["icon"], className="material-symbols-outlined",
                          style={"color": st["border"], "marginRight": "8px",
                                 "fontSize": "18px", "verticalAlign": "middle"}),
                html.Span(w.message, style={"fontSize": "13px",
                                            "fontWeight": "700" if w.level == "critical" else "500"}),
            ],
            style={"backgroundColor": st["bg"], "border": f"1px solid {st['border']}",
                   "borderRadius": "6px", "padding": "10px 12px", "marginBottom": "8px",
                   "color": "#F1F5F9"},
        ))
    return html.Div(banners, style={"marginBottom": "12px"})


def _metric(label, value, sub=""):
    return dbc.Col(
        html.Div([
            html.Div(label, style={"fontSize": "11px", "color": "#94A3B8",
                                   "textTransform": "uppercase", "letterSpacing": "1px"}),
            html.Div(value, style={"fontSize": "22px", "fontWeight": "800",
                                   "fontFamily": "'Space Grotesk', monospace", "color": "#F1F5F9"}),
            html.Div(sub, style={"fontSize": "12px", "color": "#64748B"}) if sub else None,
        ]),
        xs=6, md=3,
    )


def _render_results(result, trade_legs=None):
    children = []

    if trade_legs is not None:
        children.append(html.Div(
            dbc.Button(
                [html.Span("bolt", className="material-symbols-outlined me-1",
                           style={"fontSize": "18px", "verticalAlign": "middle"}),
                 "Place Strangle"],
                id={"type": "gsd-trade-btn", "index": "__analyze__"}, color="success",
                style={"fontWeight": "600"},
            ),
            style={"marginBottom": "12px"},
        ))

    if result.sd is not None:
        sd = result.sd
        children.append(dbc.Card(dbc.CardBody([
            dbc.Row([
                _metric("1 SD Move", f"${sd.one_sd:.2f}", f"±{sd.one_sd_pct:.1f}%"),
                _metric("2 SD Move", f"${sd.two_sd:.2f}", f"±{sd.two_sd_pct:.1f}%"),
                _metric("Upside Target", f"${sd.upside_target:.2f}", f"shop calls near ${sd.upside_target:.0f}"),
                _metric("Downside Target", f"${sd.downside_target:.2f}", f"shop puts near ${sd.downside_target:.0f}"),
            ]),
        ]), style={"backgroundColor": "rgba(15,23,42,0.8)", "border": "1px solid #1E293B",
                   "marginBottom": "12px"}))

    # Suitability score.
    s = result.suitability
    score_color = "#22C55E" if s.score >= 7 else "#F59E0B" if s.score >= 4 else "#EF4444"
    children.append(dbc.Card(dbc.CardBody([
        html.Div([
            html.Span("Suitability ", style={"fontSize": "13px", "color": "#94A3B8"}),
            html.Span(f"{s.score}/10", style={"fontSize": "20px", "fontWeight": "800",
                                              "color": score_color, "marginLeft": "6px"}),
        ]),
        html.Div(" · ".join(s.breakdown), style={"fontSize": "11px", "color": "#64748B",
                                                 "marginTop": "4px"}),
    ]), style={"backgroundColor": "rgba(15,23,42,0.8)", "border": "1px solid #1E293B",
               "marginBottom": "12px"}))

    # Screener table.
    if result.screener:
        header = html.Thead(html.Tr([
            html.Th(c) for c in ["Strike", "Side", "Ask", "Cost/Contract", "2SD Rating", "Verdict", "Liquidity"]
        ]))
        rows = []
        for r in sorted(result.screener, key=lambda x: (x.side, x.strike)):
            color = _VERDICT_COLOR[r.verdict]
            rows.append(html.Tr([
                html.Td(f"${r.strike:g}"),
                html.Td(r.side),
                html.Td(f"${r.ask:.2f}"),
                html.Td(f"${r.cost_per_contract:.0f}"),
                html.Td(r.rating),
                html.Td(html.Span(f"{r.verdict_icon} {r.verdict}",
                                  style={"color": color, "fontWeight": "700"})),
                html.Td("⚠️ wide" if r.liquidity_warning else "—"),
            ]))
        children.append(dbc.Card(dbc.CardBody([
            html.Div("OPTIONS SCREENER", style={"fontSize": "12px", "fontWeight": "700",
                                                "letterSpacing": "1px", "marginBottom": "8px",
                                                "color": "#CBD5E1"}),
            dbc.Table([header, html.Tbody(rows)], bordered=False, hover=True, responsive=True,
                      style={"color": "#E2E8F0", "fontSize": "13px"}),
        ]), style={"backgroundColor": "rgba(15,23,42,0.8)", "border": "1px solid #1E293B"}))
    elif result.sd is not None:
        children.append(html.Div(
            "No candidate contracts near the 2SD targets in the live chain. "
            "SD targets above show where to shop manually.",
            style={"fontSize": "12px", "color": "#64748B", "padding": "8px 0"},
        ))

    return children
