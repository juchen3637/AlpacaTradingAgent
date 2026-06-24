"""
webui/callbacks/journal_callbacks.py - Journal page interactivity.

Loads decisions from the SQLite journal, renders the filterable trade log,
and shows per-decision agent reasoning when a row is clicked.
"""

from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, html, no_update

from tradingagents.analytics import get_journal
from tradingagents.analytics.backfill import backfill_from_alpaca
from tradingagents.analytics.performance import calculate_per_ticker_stats
from tradingagents.analytics.strategy_analysis import (
    calculate_analyst_effectiveness,
    calculate_streaks,
    get_signal_distribution,
    analyze_time_patterns,
)


_SIGNAL_COLORS = {
    "BUY": "#22C55E",
    "LONG": "#22C55E",
    "SELL": "#EF4444",
    "SHORT": "#EF4444",
    "HOLD": "#94A3B8",
    "NEUTRAL": "#94A3B8",
}


def _signal_badge(signal: str | None):
    if not signal:
        return html.Span("—", style={"color": "#94A3B8"})
    sig = signal.upper().strip()
    color = _SIGNAL_COLORS.get(sig, "#94A3B8")
    return html.Span(
        sig,
        style={
            "backgroundColor": f"{color}22",
            "color": color,
            "padding": "3px 10px",
            "borderRadius": "4px",
            "fontSize": "11px",
            "fontWeight": "700",
            "letterSpacing": "0.5px",
            "border": f"1px solid {color}44",
        },
    )


def _format_dollar(v: Any) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"${f:,.2f}"


def _format_percent(v: Any) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{f:+.2f}%"


def _format_timestamp(ts: str | None) -> str:
    if not ts:
        return "—"
    # Already ISO; trim to minute for readability
    return ts.replace("T", " ").split(".")[0][:16]


def _build_log_table(decisions: list[dict[str, Any]]) -> Any:
    """Render decisions as a styled HTML table with click-to-expand rows."""
    if not decisions:
        return html.Div(
            "No decisions recorded yet. Start an analysis to populate the journal.",
            style={"color": "#94A3B8", "fontSize": "13px",
                   "padding": "24px", "textAlign": "center"},
        )

    header = html.Thead(html.Tr([
        html.Th("Time", style={"width": "140px"}),
        html.Th("Ticker"),
        html.Th("Signal"),
        html.Th("Size"),
        html.Th("Entry"),
        html.Th("Stop"),
        html.Th("Trades"),
        html.Th("P&L"),
        html.Th("Runtime"),
        html.Th(""),
    ]))

    rows = []
    for d in decisions:
        outcomes = d.get("outcomes") or []
        trades = d.get("trades") or []
        total_pnl = sum((o.get("pnl_dollars") or 0) for o in outcomes) if outcomes else None

        pnl_cell = "—"
        pnl_color = "#94A3B8"
        if total_pnl is not None:
            pnl_cell = _format_dollar(total_pnl)
            pnl_color = "#22C55E" if total_pnl >= 0 else "#EF4444"

        runtime = d.get("execution_time_seconds")
        runtime_str = f"{runtime:.1f}s" if runtime is not None else "—"

        view_btn = dbc.Button(
            "View",
            id={"type": "journal-view-decision", "index": d["id"]},
            size="sm",
            color="primary",
            outline=True,
            style={"fontSize": "11px", "padding": "2px 10px"},
        )

        rows.append(html.Tr([
            html.Td(_format_timestamp(d.get("timestamp")),
                    style={"fontSize": "12px", "color": "#94A3B8",
                           "fontVariantNumeric": "tabular-nums"}),
            html.Td(d.get("ticker") or "—",
                    style={"fontWeight": "700"}),
            html.Td(_signal_badge(d.get("signal"))),
            html.Td(_format_dollar(d.get("position_size_dollars")),
                    style={"fontVariantNumeric": "tabular-nums"}),
            html.Td(_format_dollar(d.get("entry_price")),
                    style={"fontVariantNumeric": "tabular-nums"}),
            html.Td(_format_dollar(d.get("stop_loss")),
                    style={"fontVariantNumeric": "tabular-nums"}),
            html.Td(str(len(trades)) if trades else "0",
                    style={"fontVariantNumeric": "tabular-nums",
                           "textAlign": "center"}),
            html.Td(pnl_cell,
                    style={"color": pnl_color, "fontWeight": "600",
                           "fontVariantNumeric": "tabular-nums"}),
            html.Td(runtime_str,
                    style={"color": "#94A3B8", "fontSize": "12px",
                           "fontVariantNumeric": "tabular-nums"}),
            html.Td(view_btn),
        ]))

    return dbc.Table(
        [header, html.Tbody(rows)],
        bordered=False,
        hover=True,
        responsive=True,
        color="dark",
        style={"fontSize": "13px"},
    )


def _accordion_item(title: str, body: str | None, item_id: str):
    """Build a single accordion item for an agent report."""
    content = body.strip() if body else ""
    display = content if content else "_(no content)_"
    return dbc.AccordionItem(
        [
            html.Pre(
                display,
                style={
                    "whiteSpace": "pre-wrap",
                    "fontFamily": "'Inter', monospace",
                    "fontSize": "12px",
                    "color": "#CBD5E1",
                    "backgroundColor": "rgba(11, 17, 32, 0.6)",
                    "padding": "16px",
                    "borderRadius": "6px",
                    "maxHeight": "400px",
                    "overflowY": "auto",
                    "margin": 0,
                },
            ),
        ],
        title=title,
        item_id=item_id,
    )


def _build_decision_detail(decision: dict[str, Any] | None):
    """Render the full reasoning drill-down for a single decision."""
    if not decision:
        return html.Div(
            "Select a row above to see the full agent reasoning for that decision.",
            style={"color": "#94A3B8", "fontSize": "13px",
                   "padding": "24px", "textAlign": "center"},
        )

    # Header summary
    header = html.Div([
        html.Div([
            html.Span(decision.get("ticker") or "—",
                      style={"fontSize": "24px", "fontWeight": "700",
                             "fontFamily": "'Space Grotesk', sans-serif",
                             "marginRight": "16px"}),
            _signal_badge(decision.get("signal")),
            html.Span(_format_timestamp(decision.get("timestamp")),
                      style={"marginLeft": "16px", "color": "#94A3B8",
                             "fontSize": "12px"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "12px"}),

        dbc.Row([
            dbc.Col([
                html.Div("Position Size", style={"fontSize": "10px",
                                                  "color": "#94A3B8",
                                                  "textTransform": "uppercase",
                                                  "letterSpacing": "0.5px"}),
                html.Div(_format_dollar(decision.get("position_size_dollars")),
                         style={"fontSize": "14px", "fontWeight": "600",
                                "fontVariantNumeric": "tabular-nums"}),
            ], xs=6, lg=3),
            dbc.Col([
                html.Div("Entry", style={"fontSize": "10px",
                                          "color": "#94A3B8",
                                          "textTransform": "uppercase",
                                          "letterSpacing": "0.5px"}),
                html.Div(_format_dollar(decision.get("entry_price")),
                         style={"fontSize": "14px", "fontWeight": "600",
                                "fontVariantNumeric": "tabular-nums"}),
            ], xs=6, lg=3),
            dbc.Col([
                html.Div("Stop Loss", style={"fontSize": "10px",
                                              "color": "#94A3B8",
                                              "textTransform": "uppercase",
                                              "letterSpacing": "0.5px"}),
                html.Div(_format_dollar(decision.get("stop_loss")),
                         style={"fontSize": "14px", "fontWeight": "600",
                                "color": "#EF4444",
                                "fontVariantNumeric": "tabular-nums"}),
            ], xs=6, lg=3),
            dbc.Col([
                html.Div("Targets", style={"fontSize": "10px",
                                            "color": "#94A3B8",
                                            "textTransform": "uppercase",
                                            "letterSpacing": "0.5px"}),
                html.Div(
                    ", ".join(_format_dollar(t) for t in (decision.get("take_profit") or []))
                    or "—",
                    style={"fontSize": "14px", "fontWeight": "600",
                           "color": "#22C55E",
                           "fontVariantNumeric": "tabular-nums"},
                ),
            ], xs=6, lg=3),
        ], className="mb-3"),

        html.Div([
            html.Span(f"Analysts: {', '.join(decision.get('selected_analysts') or []) or '—'}",
                      style={"fontSize": "11px", "color": "#94A3B8",
                             "marginRight": "16px"}),
            html.Span(f"Depth: {decision.get('research_depth') or '—'}",
                      style={"fontSize": "11px", "color": "#94A3B8",
                             "marginRight": "16px"}),
            html.Span(f"Quick: {decision.get('quick_llm') or '—'}",
                      style={"fontSize": "11px", "color": "#94A3B8",
                             "marginRight": "16px"}),
            html.Span(f"Deep: {decision.get('deep_llm') or '—'}",
                      style={"fontSize": "11px", "color": "#94A3B8"}),
        ], style={"marginBottom": "16px", "paddingBottom": "12px",
                  "borderBottom": "1px solid rgba(51, 65, 85, 0.5)"}),
    ] + ([
        html.Div(
            decision["trade_notes"],
            style={
                "padding": "10px 14px",
                "marginBottom": "12px",
                "backgroundColor": "rgba(245, 158, 11, 0.12)",
                "border": "1px solid rgba(245, 158, 11, 0.4)",
                "borderRadius": "6px",
                "color": "#F59E0B",
                "fontSize": "12px",
                "fontWeight": "600",
            },
        )
    ] if decision.get("trade_notes") else []))

    # Agent reasoning accordion
    accordion = dbc.Accordion(
        [
            _accordion_item("📊 Market Analyst",
                            decision.get("market_report"), "market"),
            _accordion_item("💬 Social/Sentiment Analyst",
                            decision.get("sentiment_report"), "sentiment"),
            _accordion_item("📰 News Analyst",
                            decision.get("news_report"), "news"),
            _accordion_item("💼 Fundamentals Analyst",
                            decision.get("fundamentals_report"), "fundamentals"),
            _accordion_item("🌍 Macro Analyst",
                            decision.get("macro_report"), "macro"),
            _accordion_item("🐂 Bull Researcher",
                            decision.get("bull_summary"), "bull"),
            _accordion_item("🐻 Bear Researcher",
                            decision.get("bear_summary"), "bear"),
            _accordion_item("⚖️  Research Judge",
                            decision.get("judge_decision"), "judge"),
            _accordion_item("📋 Trader Plan",
                            decision.get("trader_plan"), "trader"),
            _accordion_item("🛡️  Risk Manager",
                            decision.get("risk_debate_summary"), "risk"),
            _accordion_item("✅ Final Decision",
                            decision.get("final_decision"), "final"),
            _accordion_item("🔒 Position Guard (Exit Gate)",
                            decision.get("exit_gate_result"), "exit_gate"),
        ],
        start_collapsed=True,
        always_open=False,
        id="journal-detail-accordion",
    )

    return html.Div([header, accordion])


def _compute_summary_stats(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(decisions)
    total_trades = sum(len(d.get("trades") or []) for d in decisions)

    outcomes = [o for d in decisions for o in (d.get("outcomes") or [])]
    if outcomes:
        wins = sum(1 for o in outcomes if (o.get("pnl_dollars") or 0) > 0)
        win_rate = wins / len(outcomes) * 100
        avg_pnl = sum((o.get("pnl_dollars") or 0) for o in outcomes) / len(outcomes)
    else:
        win_rate = None
        avg_pnl = None

    return {
        "total_decisions": total,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
    }


# ─── Chart builders ─────────────────────────────────────────────────────


def _empty_figure(message: str = "No data") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#94A3B8"),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[dict(text=message, xref="paper", yref="paper",
                          x=0.5, y=0.5, showarrow=False,
                          font=dict(size=13, color="#94A3B8"))],
        margin=dict(l=0, r=0, t=0, b=0),
    )
    return fig


def _signal_distribution_chart(distribution: dict[str, int]) -> go.Figure:
    if not distribution or sum(distribution.values()) == 0:
        return _empty_figure("No decisions recorded yet")

    # Order signals consistently so colors stay meaningful
    order = ["BUY", "LONG", "HOLD", "NEUTRAL", "SELL", "SHORT", "UNKNOWN"]
    labels, values, colors = [], [], []
    for sig in order:
        if sig in distribution and distribution[sig] > 0:
            labels.append(sig)
            values.append(distribution[sig])
            colors.append(_SIGNAL_COLORS.get(sig, "#64748B"))

    # Catch any signals not in our known list
    for sig, count in distribution.items():
        if sig not in order and count > 0:
            labels.append(sig)
            values.append(count)
            colors.append("#64748B")

    fig = go.Figure(data=[go.Pie(
        labels=labels, values=values,
        hole=0.55,
        textinfo="label+value",
        textposition="outside",
        marker=dict(colors=colors, line=dict(color="#0F172A", width=2)),
    )])
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#F1F5F9", size=11),
        showlegend=False,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


def _per_ticker_pnl_chart(per_ticker: dict[str, dict[str, Any]]) -> go.Figure:
    # Filter to tickers that have outcomes (non-zero trade_count)
    entries = [(t, s) for t, s in per_ticker.items() if s.get("trade_count")]
    if not entries:
        return _empty_figure("No closed trades yet — P&L will populate as positions close")

    # Sort by total_pnl descending (best first)
    entries.sort(key=lambda x: x[1].get("total_pnl") or 0, reverse=True)
    tickers = [t for t, _ in entries]
    pnls = [s.get("total_pnl") or 0 for _, s in entries]
    colors = ["#22C55E" if p >= 0 else "#EF4444" for p in pnls]
    hover = [
        f"<b>{t}</b><br>Total P&L: ${s.get('total_pnl') or 0:,.2f}"
        f"<br>Trades: {s.get('trade_count')}"
        f"<br>Win Rate: {s.get('win_rate'):.1f}%" if s.get("win_rate") is not None
        else f"<b>{t}</b><br>Total P&L: ${s.get('total_pnl') or 0:,.2f}"
        for t, s in entries
    ]

    fig = go.Figure(go.Bar(
        x=tickers, y=pnls, marker_color=colors,
        hovertext=hover, hoverinfo="text",
    ))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#94A3B8", size=11),
        xaxis=dict(gridcolor="rgba(51,65,85,0.3)", showgrid=False),
        yaxis=dict(gridcolor="rgba(51,65,85,0.3)", showgrid=True,
                   tickformat="$,.0f", zerolinecolor="rgba(148,163,184,0.5)"),
        margin=dict(l=50, r=20, t=10, b=40),
    )
    return fig


def _unrealized_pnl_chart(positions: list[dict[str, Any]]) -> go.Figure:
    """Bar chart of unrealized P&L per open position (from live Alpaca data)."""
    if not positions:
        return _empty_figure("No open positions")

    # Sort by total_pl desc (best first)
    sorted_positions = sorted(
        positions, key=lambda p: p.get("_total_pl_dollars", 0.0), reverse=True
    )
    tickers = [p["Symbol"] for p in sorted_positions]
    pnls = [p.get("_total_pl_dollars", 0.0) for p in sorted_positions]
    colors = ["#22C55E" if p >= 0 else "#EF4444" for p in pnls]
    hover = [
        f"<b>{p['Symbol']}</b><br>"
        f"Unrealized P&L: ${p.get('_total_pl_dollars', 0):,.2f} "
        f"({p.get('_total_pl_percent', 0):+.2f}%)<br>"
        f"Qty: {p.get('Qty', 0)}<br>"
        f"Market Value: {p.get('Market Value', '—')}<br>"
        f"Cost Basis: {p.get('Cost Basis', '—')}"
        for p in sorted_positions
    ]

    fig = go.Figure(go.Bar(
        x=tickers, y=pnls, marker_color=colors,
        hovertext=hover, hoverinfo="text",
    ))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#94A3B8", size=11),
        xaxis=dict(gridcolor="rgba(51,65,85,0.3)", showgrid=False),
        yaxis=dict(gridcolor="rgba(51,65,85,0.3)", showgrid=True,
                   tickformat="$,.0f", zerolinecolor="rgba(148,163,184,0.5)"),
        margin=dict(l=50, r=20, t=10, b=40),
    )
    return fig


def _unrealized_summary(positions: list[dict[str, Any]]):
    """Summary row showing totals across all open positions."""
    if not positions:
        return html.Div(
            "No open positions",
            style={"color": "#94A3B8", "fontSize": "13px"},
        )

    total_pl = sum(p.get("_total_pl_dollars", 0.0) for p in positions)
    total_cost = sum(p.get("_cost_basis", 0.0) for p in positions)
    total_pct = (total_pl / total_cost * 100) if total_cost else 0.0
    pl_color = "#22C55E" if total_pl >= 0 else "#EF4444"

    def stat(label, value, color=None):
        return html.Div([
            html.Div(label, style={"fontSize": "10px", "color": "#64748B",
                                   "textTransform": "uppercase", "letterSpacing": "1px",
                                   "fontWeight": "600"}),
            html.Div(value, style={"fontSize": "18px", "fontWeight": "700",
                                   "fontFamily": "'Space Grotesk', sans-serif",
                                   "fontVariantNumeric": "tabular-nums",
                                   **({"color": color} if color else {})}),
        ], style={"marginRight": "24px"})

    return html.Div([
        stat("Open Positions", str(len(positions))),
        stat("Total Unrealized P&L", f"${total_pl:,.2f}", color=pl_color),
        stat("Total Unrealized %", f"{total_pct:+.2f}%", color=pl_color),
        stat("Total Cost Basis", f"${total_cost:,.2f}"),
    ], style={"display": "flex", "flexWrap": "wrap"})


def _fetch_open_positions() -> list[dict[str, Any]]:
    """Pull live positions from Alpaca, parsing the P&L strings back to floats."""
    from tradingagents.dataflows.alpaca_utils import AlpacaUtils

    raw = AlpacaUtils.get_positions_data() or []
    parsed: list[dict[str, Any]] = []
    for p in raw:
        # get_positions_data formats values as strings like "$12.34"; parse back
        def _money(s: Any) -> float:
            try:
                return float(str(s).replace("$", "").replace("%", "").replace(",", ""))
            except (TypeError, ValueError):
                return 0.0

        cost_basis = _money(p.get("Cost Basis"))
        p["_total_pl_dollars"] = _money(p.get("Total P/L ($)"))
        p["_total_pl_percent"] = _money(p.get("Total P/L (%)"))
        p["_cost_basis"] = cost_basis
        parsed.append(p)
    return parsed


def _analyst_radar_chart(effectiveness: dict[str, dict[str, Any]]) -> go.Figure:
    """Two overlapping radar polygons:
    - Alignment rate (% of decisions where analyst sentiment matched final signal)
    - Influence score (% of aligned-with-winner / total aligned-with-outcome)
    """
    # Keep analysts that have at least one decision
    analysts = [name for name, s in effectiveness.items() if s["total_decisions"] > 0]
    if not analysts:
        return _empty_figure("No decisions recorded yet")

    def _alignment_pct(s: dict[str, Any]) -> float:
        total = s["total_decisions"]
        return (s["aligned_with_signal"] / total * 100) if total > 0 else 0.0

    alignment_vals = [_alignment_pct(effectiveness[a]) for a in analysts]
    # Influence score: fall back to None→0 for radar
    influence_vals = [effectiveness[a].get("influence_score") or 0 for a in analysts]

    has_any_influence = any(
        effectiveness[a].get("influence_score") is not None for a in analysts
    )

    labels = [a.capitalize() for a in analysts]
    # Close the loop
    theta = labels + [labels[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=alignment_vals + [alignment_vals[0]],
        theta=theta,
        fill="toself",
        name="Signal Alignment %",
        line=dict(color="#3B82F6"),
        fillcolor="rgba(59, 130, 246, 0.25)",
    ))
    if has_any_influence:
        fig.add_trace(go.Scatterpolar(
            r=influence_vals + [influence_vals[0]],
            theta=theta,
            fill="toself",
            name="Win Contribution %",
            line=dict(color="#22C55E"),
            fillcolor="rgba(34, 197, 94, 0.25)",
        ))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#94A3B8", size=10),
        polar=dict(
            bgcolor="rgba(11, 17, 32, 0.3)",
            radialaxis=dict(visible=True, range=[0, 100],
                             gridcolor="rgba(51,65,85,0.5)",
                             tickfont=dict(size=9)),
            angularaxis=dict(gridcolor="rgba(51,65,85,0.5)",
                              tickfont=dict(size=11, color="#F1F5F9")),
        ),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15,
                    xanchor="center", x=0.5, font=dict(size=10)),
        margin=dict(l=40, r=40, t=10, b=40),
    )
    return fig


def _hour_chart(hour_patterns: dict[int, dict[str, Any]]) -> go.Figure:
    hours = list(range(24))
    counts = [hour_patterns.get(h, {}).get("count", 0) for h in hours]
    if sum(counts) == 0:
        return _empty_figure("No decision timestamps yet")

    labels = [f"{h:02d}:00" for h in hours]
    colors = ["#3B82F6" if c > 0 else "rgba(59, 130, 246, 0.2)" for c in counts]

    fig = go.Figure(go.Bar(
        x=labels, y=counts, marker_color=colors,
        hovertemplate="<b>%{x}</b><br>Decisions: %{y}<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#94A3B8", size=10),
        xaxis=dict(gridcolor="rgba(51,65,85,0.3)", showgrid=False,
                   tickmode="array",
                   tickvals=labels[::3], ticktext=labels[::3]),
        yaxis=dict(gridcolor="rgba(51,65,85,0.3)", showgrid=True,
                   title=dict(text="Decisions", font=dict(size=10))),
        margin=dict(l=40, r=20, t=10, b=40),
    )
    return fig


def _streak_timeline_chart(timeline: list[int]) -> go.Figure:
    if not timeline:
        return _empty_figure("No outcomes yet")

    indices = list(range(1, len(timeline) + 1))
    colors = ["#22C55E" if v > 0 else "#EF4444" for v in timeline]

    fig = go.Figure(go.Bar(
        x=indices, y=timeline, marker_color=colors,
        hovertemplate="Trade #%{x}: %{text}<extra></extra>",
        text=["Win" if v > 0 else "Loss" for v in timeline],
    ))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#94A3B8", size=10),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, range=[-1.5, 1.5]),
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
    )
    return fig


def _streak_summary_html(streaks: dict[str, Any]):
    current = streaks.get("current_streak", 0)
    cur_color = "#22C55E" if current > 0 else ("#EF4444" if current < 0 else "#94A3B8")
    cur_label = f"W{current}" if current > 0 else (f"L{abs(current)}" if current < 0 else "—")

    return html.Div([
        html.Div([
            html.Div("CURRENT", style={"fontSize": "10px", "color": "#94A3B8",
                                        "textTransform": "uppercase",
                                        "letterSpacing": "0.5px"}),
            html.Div(cur_label, style={"fontSize": "22px", "fontWeight": "700",
                                         "color": cur_color,
                                         "fontFamily": "'Space Grotesk', sans-serif"}),
        ], style={"textAlign": "center", "flex": "1"}),
        html.Div([
            html.Div("LONGEST WIN", style={"fontSize": "10px", "color": "#94A3B8",
                                            "textTransform": "uppercase",
                                            "letterSpacing": "0.5px"}),
            html.Div(str(streaks.get("longest_win", 0)),
                     style={"fontSize": "22px", "fontWeight": "700",
                            "color": "#22C55E",
                            "fontFamily": "'Space Grotesk', sans-serif"}),
        ], style={"textAlign": "center", "flex": "1"}),
        html.Div([
            html.Div("LONGEST LOSS", style={"fontSize": "10px", "color": "#94A3B8",
                                             "textTransform": "uppercase",
                                             "letterSpacing": "0.5px"}),
            html.Div(str(streaks.get("longest_loss", 0)),
                     style={"fontSize": "22px", "fontWeight": "700",
                            "color": "#EF4444",
                            "fontFamily": "'Space Grotesk', sans-serif"}),
        ], style={"textAlign": "center", "flex": "1"}),
    ], style={"display": "flex", "padding": "8px 0 16px 0",
              "borderBottom": "1px solid rgba(51, 65, 85, 0.3)",
              "marginBottom": "8px"})


def register_journal_callbacks(app):
    """Register all journal-page callbacks with the Dash app."""

    @app.callback(
        Output("journal-ticker-filter", "options"),
        [
            Input("journal-refresh-btn", "n_clicks"),
            Input("slow-refresh-interval", "n_intervals"),
        ],
    )
    def _populate_ticker_options(_n, _intervals):
        try:
            tickers = get_journal().get_all_tickers()
        except Exception as e:
            print(f"[JOURNAL UI] Failed to load tickers: {e}")
            return []
        return [{"label": t, "value": t} for t in tickers]

    @app.callback(
        [
            Output("journal-log-table", "children"),
            Output("journal-total-decisions", "children"),
            Output("journal-total-trades", "children"),
            Output("journal-win-rate", "children"),
            Output("journal-avg-pnl", "children"),
        ],
        [
            Input("journal-refresh-btn", "n_clicks"),
            Input("slow-refresh-interval", "n_intervals"),
            Input("journal-ticker-filter", "value"),
            Input("journal-signal-filter", "value"),
            Input("journal-tab", "active_tab"),
            Input("journal-limit-filter", "value"),
        ],
    )
    def _refresh_log(_n, _intervals, ticker, signal, tab, limit):
        # Analysis tab folds in legacy Alpaca-history backfill rows.
        source = {"agent": ["agent", "backfill"]}.get(tab, tab or "agent")
        try:
            journal = get_journal()
            decisions = journal.get_decisions(
                ticker=ticker,
                signal=None if not signal or signal == "ALL" else signal,
                source=source,
                limit=int(limit or 100),
            )
            # Attach outcomes and trades so the table can show P&L and trade counts
            for d in decisions:
                d["outcomes"] = journal.get_outcomes_for_decision(d["id"])
                d["trades"] = journal.get_trades_for_decision(d["id"])
        except Exception as e:
            print(f"[JOURNAL UI] Failed to load decisions: {e}")
            decisions = []

        stats = _compute_summary_stats(decisions)
        table = _build_log_table(decisions)

        total_decisions_str = str(stats["total_decisions"])
        total_trades_str = str(stats["total_trades"])
        win_rate_str = f"{stats['win_rate']:.1f}%" if stats["win_rate"] is not None else "—"
        avg_pnl_str = _format_dollar(stats["avg_pnl"])

        return table, total_decisions_str, total_trades_str, win_rate_str, avg_pnl_str

    @app.callback(
        Output("journal-decision-detail", "children"),
        Input({"type": "journal-view-decision", "index": ALL}, "n_clicks"),
        State({"type": "journal-view-decision", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def _show_decision_detail(n_clicks_list, id_list):
        # Only run if an actual click triggered this (n_clicks > 0)
        if not n_clicks_list or not any(n_clicks_list):
            return no_update

        triggered = ctx.triggered_id
        if not triggered or not isinstance(triggered, dict):
            return no_update

        decision_id = triggered.get("index")
        if decision_id is None:
            return no_update

        try:
            decision = get_journal().get_decision_by_id(int(decision_id))
        except Exception as e:
            print(f"[JOURNAL UI] Failed to load decision {decision_id}: {e}")
            return html.Div(
                f"Error loading decision {decision_id}: {e}",
                style={"color": "#EF4444", "padding": "16px"},
            )

        return _build_decision_detail(decision)

    # ── Analytics charts (Phase 4) ────────────────────────────────────
    @app.callback(
        [
            Output("journal-signal-distribution", "figure"),
            Output("journal-per-ticker-pnl", "figure"),
            Output("journal-analyst-radar", "figure"),
            Output("journal-hour-chart", "figure"),
            Output("journal-streak-timeline", "figure"),
            Output("journal-streak-summary", "children"),
        ],
        [
            Input("journal-refresh-btn", "n_clicks"),
            Input("journal-ticker-filter", "value"),
        ],
    )
    def _refresh_analytics(_n, ticker):
        try:
            journal = get_journal()
            distribution = get_signal_distribution(journal, ticker=ticker)
            per_ticker = calculate_per_ticker_stats(journal)
            effectiveness = calculate_analyst_effectiveness(journal)
            hour_patterns = analyze_time_patterns(journal)
            streaks = calculate_streaks(journal)
        except Exception as e:
            print(f"[JOURNAL UI] Failed to load analytics: {e}")
            empty = _empty_figure(f"Error: {e}")
            return empty, empty, empty, empty, empty, html.Div()

        return (
            _signal_distribution_chart(distribution),
            _per_ticker_pnl_chart(per_ticker),
            _analyst_radar_chart(effectiveness),
            _hour_chart(hour_patterns),
            _streak_timeline_chart(streaks.get("streak_timeline") or []),
            _streak_summary_html(streaks),
        )

    @app.callback(
        [
            Output("journal-unrealized-pnl", "figure"),
            Output("journal-unrealized-summary", "children"),
        ],
        Input("journal-refresh-btn", "n_clicks"),
    )
    def _refresh_unrealized(_n):
        try:
            positions = _fetch_open_positions()
        except Exception as e:
            print(f"[JOURNAL UI] Failed to load open positions: {e}")
            return _empty_figure(f"Error loading positions: {e}"), html.Div()
        return _unrealized_pnl_chart(positions), _unrealized_summary(positions)

    # ── Clear journal: open modal → confirm → wipe → refresh ────────────
    @app.callback(
        [
            Output("journal-clear-modal", "is_open"),
            Output("journal-clear-preview", "children"),
        ],
        [
            Input("journal-clear-btn", "n_clicks"),
            Input("journal-clear-cancel-btn", "n_clicks"),
            Input("journal-clear-confirm-btn", "n_clicks"),
        ],
        prevent_initial_call=True,
    )
    def _toggle_clear_modal(open_clicks, cancel_clicks, confirm_clicks):
        triggered = ctx.triggered_id
        if triggered == "journal-clear-btn":
            try:
                journal = get_journal()
                total = journal.count_decisions()
            except Exception as e:
                print(f"[JOURNAL UI] Failed to count decisions: {e}")
                total = None
            preview = (
                f"Currently {total} decision{'s' if total != 1 else ''} on record."
                if total is not None
                else "Could not read current journal size — proceed only if you're sure."
            )
            return True, preview
        # cancel or confirm both close the modal; confirm hand-off happens in the next callback
        return False, no_update

    @app.callback(
        [
            Output("journal-clear-toast", "is_open"),
            Output("journal-clear-toast", "children"),
            Output("journal-refresh-btn", "n_clicks", allow_duplicate=True),
        ],
        Input("journal-clear-confirm-btn", "n_clicks"),
        State("journal-refresh-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def _confirm_clear_journal(n_clicks, refresh_clicks):
        if not n_clicks:
            return no_update, no_update, no_update
        try:
            deleted = get_journal().clear_all()
        except Exception as e:
            print(f"[JOURNAL UI] Failed to clear journal: {e}")
            return True, html.Span(
                f"Error clearing journal: {e}", style={"color": "#EF4444"},
            ), no_update

        msg = (
            f"Removed {deleted['decisions']} decision"
            f"{'s' if deleted['decisions'] != 1 else ''}, "
            f"{deleted['trades']} trade{'s' if deleted['trades'] != 1 else ''}, "
            f"{deleted['outcomes']} outcome{'s' if deleted['outcomes'] != 1 else ''}."
        )
        new_refresh = (refresh_clicks or 0) + 1
        return True, msg, new_refresh

    @app.callback(
        [
            Output("journal-backfill-status", "children"),
            Output("journal-refresh-btn", "n_clicks", allow_duplicate=True),
        ],
        Input("journal-backfill-btn", "n_clicks"),
        State("journal-backfill-lookback", "value"),
        State("journal-refresh-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def _run_backfill(n_clicks, lookback_days, refresh_clicks):
        if not n_clicks:
            return no_update, no_update
        try:
            report = backfill_from_alpaca(lookback_days=int(lookback_days or 90))
        except Exception as e:
            return (
                html.Span(f"Sync failed: {e}", style={"color": "#EF4444"}),
                no_update,
            )

        if report.error:
            return (
                html.Span(f"Sync failed: {report.error}", style={"color": "#EF4444"}),
                no_update,
            )

        msg = (
            f"Scanned {report.orders_scanned} orders · "
            f"Added {report.decisions_added} decisions, "
            f"{report.outcomes_added} outcomes · "
            f"Skipped {report.skipped_duplicates} duplicates"
        )
        # Bump the refresh counter so other callbacks re-fire and pick up new rows
        new_refresh = (refresh_clicks or 0) + 1
        return (
            html.Span(msg, style={"color": "#22C55E"}),
            new_refresh,
        )
