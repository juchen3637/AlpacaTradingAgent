"""
webui/callbacks/portfolio_callbacks.py - Portfolio analytics data callbacks.

Fetches equity curve, sector allocation, position P&L, and performance metrics
from the Alpaca API and renders them on the Portfolio page.
"""

import logging

from dash import Input, Output, html, ctx
import plotly.graph_objects as go

logger = logging.getLogger(__name__)


def _empty_chart(message: str = "No data available") -> go.Figure:
    """Return an empty Plotly figure with a centered message."""
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
                          font=dict(size=14, color="#94A3B8"))],
        margin=dict(l=0, r=0, t=0, b=0),
    )
    return fig


# Rough sector mapping for common tickers
_SECTOR_MAP = {
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "GOOG": "Technology", "META": "Technology", "NVDA": "Technology",
    "AMD": "Technology", "TSLA": "Consumer Discretionary", "AMZN": "Consumer Discretionary",
    "NFLX": "Communication", "DIS": "Communication",
    "JPM": "Financials", "BAC": "Financials", "GS": "Financials", "V": "Financials",
    "JNJ": "Healthcare", "PFE": "Healthcare", "UNH": "Healthcare",
    "XOM": "Energy", "CVX": "Energy",
    "PLTR": "Technology", "MSTR": "Technology",
    "BTC/USD": "Crypto", "ETH/USD": "Crypto", "SOL/USD": "Crypto",
}


def _parse_num(val) -> float:
    """Parse a numeric value that may be pre-formatted with $, %, commas."""
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("$", "").replace(",", "").replace("%", "").strip()
    return float(s) if s else 0.0


def _get_sector(symbol: str) -> str:
    """Map a ticker to its sector. Falls back to 'Other'."""
    clean = symbol.replace("/", "").upper()
    for key, sector in _SECTOR_MAP.items():
        if key.replace("/", "").upper() == clean:
            return sector
    return "Other"


def register_portfolio_callbacks(app):
    """Register all portfolio page callbacks."""

    # ── Metric cards refresh ──────────────────────────────────────
    @app.callback(
        [Output("portfolio-total-value", "children"),
         Output("portfolio-total-pl", "children"),
         Output("portfolio-win-rate", "children"),
         Output("portfolio-sharpe", "children"),
         Output("top-portfolio-value", "children"),
         Output("top-daily-pl", "children"),
         Output("market-status-text", "children"),
         Output("market-status-dot", "className")],
        [Input("slow-refresh-interval", "n_intervals")],
    )
    def update_portfolio_metrics(_n):
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            acct = AlpacaUtils.get_account_info()
            positions = AlpacaUtils.get_positions_data()

            equity = float(acct.get("equity", 0))
            total_pl = sum(_parse_num(p.get("Total P/L ($)", 0)) for p in positions)
            daily_change = float(acct.get("daily_change_dollars", 0))
            daily_pct = float(acct.get("daily_change_percent", 0))

            value_str = f"${equity:,.2f}"
            pl_color = "#22C55E" if total_pl >= 0 else "#EF4444"
            pl_str = html.Span(f"{'+'if total_pl>=0 else ''}${total_pl:,.2f}",
                               style={"color": pl_color})
            if positions:
                winners = sum(1 for p in positions if _parse_num(p.get("Total P/L ($)", 0)) > 0)
                wr_str = f"{winners / len(positions) * 100:.0f}%"
            else:
                wr_str = "—"

            # Top status bar values
            daily_color = "#22C55E" if daily_change >= 0 else "#EF4444"
            top_pl = html.Span(
                f"{'+'if daily_change>=0 else ''}${daily_change:,.2f} ({daily_pct:+.1f}%)",
                style={"color": daily_color},
            )

            from webui.utils.market_hours import is_market_open
            is_open, _ = is_market_open()
            market_text = "OPEN" if is_open else "CLOSED"
            dot_cls = "market-status-dot open" if is_open else "market-status-dot closed"

            return value_str, pl_str, wr_str, "—", value_str, top_pl, market_text, dot_cls
        except Exception:
            logger.exception("Portfolio callback error")
            return "—", "—", "—", "—", "—", "—", "—", "market-status-dot closed"

    # ── Equity curve chart ────────────────────────────────────────
    @app.callback(
        Output("portfolio-equity-chart", "figure"),
        [Input("slow-refresh-interval", "n_intervals"),
         Input("portfolio-period-1d", "n_clicks"),
         Input("portfolio-period-1w", "n_clicks"),
         Input("portfolio-period-1m", "n_clicks"),
         Input("portfolio-period-3m", "n_clicks"),
         Input("portfolio-period-1y", "n_clicks"),
         Input("portfolio-period-all", "n_clicks")],
    )
    def update_equity_chart(_n, *_period_clicks):
        try:
            from datetime import datetime, timezone

            period_map = {
                "portfolio-period-1d": ("1D", "5Min"),
                "portfolio-period-1w": ("1W", "15Min"),
                "portfolio-period-1m": ("1M", "1D"),
                "portfolio-period-3m": ("3M", "1D"),
                "portfolio-period-1y": ("1A", "1D"),
                "portfolio-period-all": ("all", "1D"),
            }
            tick_format_map = {
                "portfolio-period-1d": ("%I:%M %p", 3600000),
                "portfolio-period-1w": ("%a %b %d", 86400000),
                "portfolio-period-1m": ("%b %d", None),
                "portfolio-period-3m": ("%b %d", None),
                "portfolio-period-1y": ("%b '%y", None),
                "portfolio-period-all": ("%b '%y", None),
            }
            triggered = ctx.triggered_id or "portfolio-period-1m"
            period, timeframe = period_map.get(triggered, ("1M", "1D"))
            tick_fmt, tick_dtick = tick_format_map.get(triggered, ("%b %d", None))

            from tradingagents.dataflows.alpaca_utils import get_alpaca_trading_client
            client = get_alpaca_trading_client()
            from alpaca.trading.requests import GetPortfolioHistoryRequest
            req = GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
            history = client.get_portfolio_history(req)

            if not history or not history.equity:
                return _empty_chart("No portfolio history available")

            timestamps = []
            for t in history.timestamp:
                if isinstance(t, (int, float)):
                    timestamps.append(datetime.fromtimestamp(t, tz=timezone.utc))
                elif hasattr(t, 'isoformat'):
                    timestamps.append(t)
                else:
                    timestamps.append(datetime.fromisoformat(str(t)))
            equity = list(history.equity)

            y_min = min(equity)
            y_max = max(equity)
            y_padding = max((y_max - y_min) * 0.1, y_max * 0.001)

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=timestamps, y=[y_min - y_padding] * len(timestamps),
                mode="lines", line=dict(width=0),
                showlegend=False, hoverinfo="skip",
            ))
            fig.add_trace(go.Scatter(
                x=timestamps, y=equity,
                mode="lines",
                fill="tonexty",
                fillcolor="rgba(59, 130, 246, 0.1)",
                line=dict(color="#3B82F6", width=2),
                hovertemplate="$%{y:,.2f}<extra>%{x}</extra>",
            ))

            xaxis_config = dict(
                gridcolor="rgba(51,65,85,0.3)", showgrid=True,
                tickformat=tick_fmt,
            )
            if tick_dtick is not None:
                xaxis_config["dtick"] = tick_dtick

            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter", color="#94A3B8"),
                xaxis=xaxis_config,
                yaxis=dict(gridcolor="rgba(51,65,85,0.3)", showgrid=True,
                           tickformat="$,.0f",
                           range=[y_min - y_padding, y_max + y_padding]),
                margin=dict(l=60, r=20, t=10, b=40),
                hovermode="x unified",
            )
            return fig
        except Exception:
            logger.exception("Portfolio callback error")
            return _empty_chart("Failed to load equity data")

    # ── Sector allocation pie chart ───────────────────────────────
    @app.callback(
        Output("portfolio-sector-chart", "figure"),
        [Input("slow-refresh-interval", "n_intervals")],
    )
    def update_sector_chart(_n):
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            positions = AlpacaUtils.get_positions_data()

            if not positions:
                return _empty_chart("No positions")

            sector_values = {}
            for p in positions:
                sector = _get_sector(p.get("Symbol", ""))
                mv = abs(_parse_num(p.get("Market Value", 0)))
                sector_values[sector] = sector_values.get(sector, 0) + mv

            labels = list(sector_values.keys())
            values = list(sector_values.values())
            colors = ["#3B82F6", "#22C55E", "#F59E0B", "#EF4444", "#8B5CF6",
                       "#EC4899", "#06B6D4", "#84CC16"]

            fig = go.Figure(data=[go.Pie(
                labels=labels, values=values,
                hole=0.55,
                textinfo="label+percent",
                textposition="outside",
                marker=dict(colors=colors[:len(labels)],
                            line=dict(color="#0F172A", width=2)),
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
        except Exception:
            logger.exception("Portfolio callback error")
            return _empty_chart("Failed to load sector data")

    # ── Position P&L table ────────────────────────────────────────
    @app.callback(
        Output("portfolio-position-pl-table", "children"),
        [Input("slow-refresh-interval", "n_intervals")],
    )
    def update_position_pl(_n):
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            positions = AlpacaUtils.get_positions_data()

            if not positions:
                return html.Div("No open positions", style={"color": "#94A3B8", "textAlign": "center"})

            rows = []
            for p in positions:
                pl = _parse_num(p.get("Total P/L ($)", 0))
                pl_pct = _parse_num(p.get("Total P/L (%)", 0))
                pl_color = "#22C55E" if pl >= 0 else "#EF4444"

                rows.append(html.Tr([
                    html.Td(p.get("Symbol", ""), style={"fontWeight": "700"}),
                    html.Td(p.get("Qty", ""), style={"textAlign": "right"}),
                    html.Td(f"${_parse_num(p.get('Market Value', 0)):,.2f}", style={"textAlign": "right"}),
                    html.Td(
                        f"{'+'if pl>=0 else ''}${pl:,.2f} ({pl_pct:+.1f}%)",
                        style={"textAlign": "right", "color": pl_color, "fontWeight": "600"},
                    ),
                ]))

            return html.Table([
                html.Thead(html.Tr([
                    html.Th("Symbol", style={"textAlign": "left"}),
                    html.Th("Qty", style={"textAlign": "right"}),
                    html.Th("Value", style={"textAlign": "right"}),
                    html.Th("P&L", style={"textAlign": "right"}),
                ]), className="portfolio-table-header"),
                html.Tbody(rows),
            ], className="portfolio-table")
        except Exception:
            logger.exception("Portfolio callback error")
            return html.Div("Error loading positions", style={"color": "#EF4444"})

    # ── Performance metrics table ─────────────────────────────────
    @app.callback(
        Output("portfolio-metrics-table", "children"),
        [Input("slow-refresh-interval", "n_intervals")],
    )
    def update_performance_metrics(_n):
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            acct = AlpacaUtils.get_account_info()
            positions = AlpacaUtils.get_positions_data()

            equity = float(acct.get("equity", 0))
            buying_power = float(acct.get("buying_power", 0))
            daily_change = float(acct.get("daily_change_dollars", 0))
            daily_pct = float(acct.get("daily_change_percent", 0))
            num_positions = len(positions)
            total_exposure = sum(abs(_parse_num(p.get("Market Value", 0))) for p in positions)
            exposure_pct = (total_exposure / equity * 100) if equity > 0 else 0

            metrics = [
                ("Buying Power", f"${buying_power:,.2f}"),
                ("Daily P&L", f"{'+'if daily_change>=0 else ''}${daily_change:,.2f} ({daily_pct:+.1f}%)"),
                ("Open Positions", str(num_positions)),
                ("Total Exposure", f"${total_exposure:,.2f} ({exposure_pct:.0f}%)"),
                ("Max Drawdown", "—"),
            ]

            rows = []
            for label, value in metrics:
                rows.append(html.Tr([
                    html.Td(label, style={"color": "#94A3B8", "fontWeight": "500"}),
                    html.Td(value, style={"textAlign": "right", "fontWeight": "700",
                                           "fontVariantNumeric": "tabular-nums"}),
                ]))

            return html.Table([html.Tbody(rows)], className="portfolio-table")
        except Exception:
            logger.exception("Portfolio callback error")
            return html.Div("Error loading metrics", style={"color": "#EF4444"})

    # ── Recent trades table ───────────────────────────────────────
    @app.callback(
        Output("portfolio-recent-trades-table", "children"),
        [Input("slow-refresh-interval", "n_intervals")],
    )
    def update_recent_trades(_n):
        try:
            from tradingagents.dataflows.alpaca_utils import AlpacaUtils
            orders = AlpacaUtils.get_recent_orders(limit=20)

            filled = [o for o in orders if o.get("Status") == "filled"][:10]
            if not filled:
                return html.Div("No recent filled trades", style={"color": "#94A3B8", "textAlign": "center"})

            rows = []
            for o in filled:
                side = o.get("Side", "").upper()
                side_color = "#22C55E" if side == "BUY" else "#EF4444"

                rows.append(html.Tr([
                    html.Td(o.get("Asset", ""), style={"fontWeight": "700"}),
                    html.Td(
                        html.Span(side, style={"color": side_color, "fontWeight": "700",
                                                "fontSize": "11px"}),
                    ),
                    html.Td(str(o.get("Filled Qty", o.get("Qty", ""))), style={"textAlign": "right"}),
                    html.Td(f"${_parse_num(o.get('Avg Fill Price', 0)):,.2f}" if o.get("Avg Fill Price") else "—",
                             style={"textAlign": "right"}),
                ]))

            return html.Table([
                html.Thead(html.Tr([
                    html.Th("Asset", style={"textAlign": "left"}),
                    html.Th("Side"),
                    html.Th("Qty", style={"textAlign": "right"}),
                    html.Th("Price", style={"textAlign": "right"}),
                ]), className="portfolio-table-header"),
                html.Tbody(rows),
            ], className="portfolio-table")
        except Exception:
            logger.exception("Portfolio callback error")
            return html.Div("Error loading trades", style={"color": "#EF4444"})
