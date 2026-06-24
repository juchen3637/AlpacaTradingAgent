"""
tradingagents/analytics/trade_journal.py - SQLite-backed trade journal.

Persists every agent decision with full reasoning, every trade execution,
and resolved outcomes. Single source of truth for performance analysis.

Schema:
- decisions: one row per analysis run (all agent reports + final signal)
- trades: one row per Alpaca order (linked to decision)
- outcomes: one row per closed position (realized P&L)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# Journal database location: <repo-root>/data/trade_journal.db
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "trade_journal.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    trade_date TEXT,
    signal TEXT,
    market_report TEXT,
    sentiment_report TEXT,
    news_report TEXT,
    fundamentals_report TEXT,
    macro_report TEXT,
    bull_summary TEXT,
    bear_summary TEXT,
    judge_decision TEXT,
    trader_plan TEXT,
    risk_debate_summary TEXT,
    final_decision TEXT,
    position_size_dollars REAL,
    entry_price REAL,
    stop_loss REAL,
    take_profit TEXT,
    selected_analysts TEXT,
    research_depth TEXT,
    llm_provider TEXT,
    quick_llm TEXT,
    deep_llm TEXT,
    execution_time_seconds REAL,
    allow_shorts INTEGER,
    source TEXT DEFAULT 'agent',
    source_order_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_decisions_ticker ON decisions(ticker);
CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp);
CREATE INDEX IF NOT EXISTS idx_decisions_signal ON decisions(signal);
CREATE INDEX IF NOT EXISTS idx_decisions_source ON decisions(source);
CREATE UNIQUE INDEX IF NOT EXISTS idx_decisions_source_order_id ON decisions(source_order_id)
    WHERE source_order_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT,
    qty REAL,
    filled_price REAL,
    order_type TEXT,
    alpaca_order_id TEXT,
    status TEXT,
    FOREIGN KEY(decision_id) REFERENCES decisions(id)
);

CREATE INDEX IF NOT EXISTS idx_trades_decision ON trades(decision_id);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_order_id ON trades(alpaca_order_id);

CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER,
    ticker TEXT NOT NULL,
    entry_timestamp TEXT,
    entry_price REAL,
    exit_timestamp TEXT,
    exit_price REAL,
    qty REAL,
    pnl_dollars REAL,
    pnl_percent REAL,
    hold_duration_hours REAL,
    exit_reason TEXT,
    FOREIGN KEY(decision_id) REFERENCES decisions(id)
);

CREATE INDEX IF NOT EXISTS idx_outcomes_decision ON outcomes(decision_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_ticker ON outcomes(ticker);
"""


@dataclass(frozen=True)
class DecisionRecord:
    """Immutable record of a single agent analysis + decision."""
    ticker: str
    trade_date: str
    signal: str | None
    market_report: str | None = None
    sentiment_report: str | None = None
    news_report: str | None = None
    fundamentals_report: str | None = None
    macro_report: str | None = None
    bull_summary: str | None = None
    bear_summary: str | None = None
    judge_decision: str | None = None
    trader_plan: str | None = None
    risk_debate_summary: str | None = None
    final_decision: str | None = None
    position_size_dollars: float | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: list[float] = field(default_factory=list)
    selected_analysts: list[str] = field(default_factory=list)
    research_depth: str | None = None
    llm_provider: str | None = None
    quick_llm: str | None = None
    deep_llm: str | None = None
    execution_time_seconds: float | None = None
    allow_shorts: bool = False
    source: str = "agent"  # 'agent' for live decisions, 'backfill' for Alpaca historical import
    source_order_id: str | None = None  # Alpaca client_order_id / order id for dedup
    # Eval loop fields — logged per decision to power the performance eval report
    conviction: float | None = None          # 0..1 extracted from agent output
    llm_cost_estimate: float | None = None   # estimated USD cost for this decision's LLM calls
    gate_rejection_reason: str | None = None # set when safety gate blocked the trade
    exit_gate_result: str | None = None      # set when position guard evaluated (open positions only)
    trade_notes: str | None = None           # warnings about trade execution (e.g. bracket fallback)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class TradeRecord:
    """Immutable record of a single Alpaca order execution."""
    decision_id: int | None
    ticker: str
    side: str
    qty: float
    filled_price: float
    order_type: str
    alpaca_order_id: str | None = None
    status: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TradeJournal:
    """SQLite-backed persistent journal of agent decisions, trades, and outcomes."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)
            # Migrate existing DBs: add columns if missing
            existing_cols = {
                r["name"] for r in conn.execute("PRAGMA table_info(decisions)").fetchall()
            }
            if "source" not in existing_cols:
                conn.execute("ALTER TABLE decisions ADD COLUMN source TEXT DEFAULT 'agent'")
            if "source_order_id" not in existing_cols:
                conn.execute("ALTER TABLE decisions ADD COLUMN source_order_id TEXT")
            if "conviction" not in existing_cols:
                conn.execute("ALTER TABLE decisions ADD COLUMN conviction REAL")
            if "llm_cost_estimate" not in existing_cols:
                conn.execute("ALTER TABLE decisions ADD COLUMN llm_cost_estimate REAL")
            if "gate_rejection_reason" not in existing_cols:
                conn.execute("ALTER TABLE decisions ADD COLUMN gate_rejection_reason TEXT")
            if "exit_gate_result" not in existing_cols:
                conn.execute("ALTER TABLE decisions ADD COLUMN exit_gate_result TEXT")
            if "trade_notes" not in existing_cols:
                conn.execute("ALTER TABLE decisions ADD COLUMN trade_notes TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_source ON decisions(source)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_decisions_source_order_id "
                "ON decisions(source_order_id) WHERE source_order_id IS NOT NULL"
            )

    # ---- Writes ---------------------------------------------------------

    def record_decision(self, record: DecisionRecord) -> int:
        """Insert a decision row; returns the new decision_id.

        If source_order_id is set and already exists (unique index), returns
        the existing decision_id instead of inserting a duplicate.
        """
        with self._lock, self._connect() as conn:
            if record.source_order_id:
                existing = conn.execute(
                    "SELECT id FROM decisions WHERE source_order_id = ?",
                    (record.source_order_id,),
                ).fetchone()
                if existing:
                    return int(existing["id"])

            cur = conn.execute(
                """
                INSERT INTO decisions (
                    timestamp, ticker, trade_date, signal,
                    market_report, sentiment_report, news_report,
                    fundamentals_report, macro_report,
                    bull_summary, bear_summary, judge_decision,
                    trader_plan, risk_debate_summary, final_decision,
                    position_size_dollars, entry_price, stop_loss, take_profit,
                    selected_analysts, research_depth, llm_provider,
                    quick_llm, deep_llm, execution_time_seconds, allow_shorts,
                    source, source_order_id,
                    conviction, llm_cost_estimate, gate_rejection_reason, exit_gate_result, trade_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp, record.ticker, record.trade_date, record.signal,
                    record.market_report, record.sentiment_report, record.news_report,
                    record.fundamentals_report, record.macro_report,
                    record.bull_summary, record.bear_summary, record.judge_decision,
                    record.trader_plan, record.risk_debate_summary, record.final_decision,
                    record.position_size_dollars, record.entry_price, record.stop_loss,
                    json.dumps(record.take_profit) if record.take_profit else None,
                    json.dumps(record.selected_analysts),
                    record.research_depth, record.llm_provider,
                    record.quick_llm, record.deep_llm, record.execution_time_seconds,
                    1 if record.allow_shorts else 0,
                    record.source, record.source_order_id,
                    record.conviction, record.llm_cost_estimate, record.gate_rejection_reason,
                    record.exit_gate_result, record.trade_notes,
                ),
            )
            return int(cur.lastrowid)

    def update_decision_gate_result(self, decision_id: int, reason: str) -> None:
        """Stamp a decision row with the safety-gate rejection reason."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE decisions SET gate_rejection_reason = ? WHERE id = ?",
                (reason, decision_id),
            )

    def update_decision_exit_gate(self, decision_id: int, result: str) -> None:
        """Stamp a decision row with the position-guard (exit gate) outcome."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE decisions SET exit_gate_result = ? WHERE id = ?",
                (result, decision_id),
            )

    def update_decision_trade_notes(self, decision_id: int, notes: str) -> None:
        """Append a trade execution warning/note to a decision row."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE decisions SET trade_notes = ? WHERE id = ?",
                (notes, decision_id),
            )

    def record_trade(self, record: TradeRecord) -> int:
        """Insert a trade row; returns the new trade_id."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO trades (
                    decision_id, timestamp, ticker, side, qty, filled_price,
                    order_type, alpaca_order_id, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.decision_id, record.timestamp, record.ticker,
                    record.side, record.qty, record.filled_price,
                    record.order_type, record.alpaca_order_id, record.status,
                ),
            )
            return int(cur.lastrowid)

    def record_outcome(
        self,
        *,
        decision_id: int | None,
        ticker: str,
        entry_timestamp: str | None,
        entry_price: float | None,
        exit_timestamp: str,
        exit_price: float,
        qty: float,
        pnl_dollars: float,
        pnl_percent: float,
        hold_duration_hours: float | None,
        exit_reason: str,
    ) -> int:
        """Insert an outcome row."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO outcomes (
                    decision_id, ticker, entry_timestamp, entry_price,
                    exit_timestamp, exit_price, qty, pnl_dollars, pnl_percent,
                    hold_duration_hours, exit_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id, ticker, entry_timestamp, entry_price,
                    exit_timestamp, exit_price, qty, pnl_dollars, pnl_percent,
                    hold_duration_hours, exit_reason,
                ),
            )
            return int(cur.lastrowid)

    # ---- Reads ----------------------------------------------------------

    def get_decisions(
        self,
        *,
        ticker: str | None = None,
        signal: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        source: str | list[str] | None = None,
        exclude_source: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return decisions filtered by ticker/signal/date range/source.

        ``source`` accepts a single value or a list (matched with IN).
        """
        query = "SELECT * FROM decisions WHERE 1=1"
        params: list[Any] = []

        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
        if signal:
            query += " AND signal = ?"
            params.append(signal)
        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)
        if source:
            if isinstance(source, (list, tuple, set)):
                sources = list(source)
                placeholders = ", ".join("?" for _ in sources)
                query += f" AND COALESCE(source, 'agent') IN ({placeholders})"
                params.extend(sources)
            else:
                query += " AND COALESCE(source, 'agent') = ?"
                params.append(source)
        if exclude_source:
            query += " AND COALESCE(source, 'agent') != ?"
            params.append(exclude_source)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_decision_dict(r) for r in rows]

    def get_decision_by_id(self, decision_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
            return self._row_to_decision_dict(row) if row else None

    def get_trades_for_decision(self, decision_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE decision_id = ? ORDER BY timestamp ASC",
                (decision_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_outcomes_for_decision(self, decision_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM outcomes WHERE decision_id = ? ORDER BY exit_timestamp ASC",
                (decision_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_decisions_with_outcomes(
        self,
        *,
        ticker: str | None = None,
        source: str | list[str] | None = None,
        exclude_source: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return decisions joined with any outcomes; outcomes list may be empty."""
        decisions = self.get_decisions(
            ticker=ticker, source=source, exclude_source=exclude_source, limit=limit
        )
        for d in decisions:
            d["outcomes"] = self.get_outcomes_for_decision(d["id"])
            d["trades"] = self.get_trades_for_decision(d["id"])
        return decisions

    def get_all_tickers(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM decisions ORDER BY ticker"
            ).fetchall()
            return [r["ticker"] for r in rows]

    def count_decisions(self, ticker: str | None = None) -> int:
        with self._connect() as conn:
            if ticker:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM decisions WHERE ticker = ?", (ticker,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM decisions").fetchone()
            return int(row["c"])

    def get_eval_report(
        self,
        *,
        days: int = 90,
        min_trades: int = 5,
    ) -> dict[str, Any]:
        """Return a performance eval report for the last ``days`` days.

        Metrics:
          - total_decisions: analysis runs in window
          - total_trades: Alpaca orders linked to decisions
          - closed_trades: outcomes recorded (position closed)
          - win_rate: % of closed trades with pnl_dollars > 0
          - total_pnl_dollars: sum of closed outcome P&L
          - avg_pnl_per_trade: mean P&L per closed trade
          - total_llm_cost: sum of llm_cost_estimate (where tracked)
          - avg_conviction: mean conviction score (where tracked)
          - conviction_calibration: win rate for conviction≥0.7 vs <0.7
          - gate_blocks: decisions blocked by safety gate
          - note: guidance message (e.g. "not enough data for statistical confidence")
        """
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        with self._connect() as conn:
            n_decisions = conn.execute(
                "SELECT COUNT(*) AS c FROM decisions WHERE timestamp >= ?", (cutoff,)
            ).fetchone()["c"]

            n_trades = conn.execute(
                "SELECT COUNT(*) AS c FROM trades t "
                "JOIN decisions d ON t.decision_id = d.id WHERE d.timestamp >= ?",
                (cutoff,),
            ).fetchone()["c"]

            outcome_rows = conn.execute(
                "SELECT o.pnl_dollars, d.conviction FROM outcomes o "
                "JOIN decisions d ON o.decision_id = d.id WHERE d.timestamp >= ?",
                (cutoff,),
            ).fetchall()

            cost_row = conn.execute(
                "SELECT SUM(llm_cost_estimate) AS total, AVG(llm_cost_estimate) AS avg "
                "FROM decisions WHERE timestamp >= ? AND llm_cost_estimate IS NOT NULL",
                (cutoff,),
            ).fetchone()

            gate_blocks = conn.execute(
                "SELECT COUNT(*) AS c FROM decisions "
                "WHERE timestamp >= ? AND gate_rejection_reason IS NOT NULL",
                (cutoff,),
            ).fetchone()["c"]

        closed = len(outcome_rows)
        wins = sum(1 for r in outcome_rows if (r["pnl_dollars"] or 0) > 0)
        total_pnl = sum((r["pnl_dollars"] or 0) for r in outcome_rows)

        high_conv = [r for r in outcome_rows if r["conviction"] is not None and r["conviction"] >= 0.7]
        low_conv = [r for r in outcome_rows if r["conviction"] is not None and r["conviction"] < 0.7]
        high_conv_wr = (
            sum(1 for r in high_conv if (r["pnl_dollars"] or 0) > 0) / len(high_conv)
            if high_conv else None
        )
        low_conv_wr = (
            sum(1 for r in low_conv if (r["pnl_dollars"] or 0) > 0) / len(low_conv)
            if low_conv else None
        )

        convictions = [r["conviction"] for r in outcome_rows if r["conviction"] is not None]

        note = ""
        if closed < min_trades:
            note = (
                f"Only {closed} closed trades in the last {days} days "
                f"(need {min_trades} for statistical confidence). Keep paper-trading."
            )

        return {
            "window_days": days,
            "total_decisions": int(n_decisions),
            "total_trades": int(n_trades),
            "closed_trades": closed,
            "win_rate": round(wins / closed, 3) if closed else None,
            "total_pnl_dollars": round(total_pnl, 2),
            "avg_pnl_per_trade": round(total_pnl / closed, 2) if closed else None,
            "total_llm_cost": round(float(cost_row["total"] or 0), 4),
            "avg_llm_cost_per_decision": round(float(cost_row["avg"] or 0), 4) if cost_row["avg"] else None,
            "avg_conviction": round(sum(convictions) / len(convictions), 3) if convictions else None,
            "conviction_calibration": {
                "high_conviction_win_rate": round(high_conv_wr, 3) if high_conv_wr is not None else None,
                "low_conviction_win_rate": round(low_conv_wr, 3) if low_conv_wr is not None else None,
                "high_conviction_trades": len(high_conv),
                "low_conviction_trades": len(low_conv),
            },
            "gate_blocks": int(gate_blocks),
            "note": note,
        }

    # ---- Destructive ----------------------------------------------------

    def clear_all(self) -> dict[str, int]:
        """Delete every row from outcomes, trades, and decisions.

        Returns the number of rows deleted from each table for confirmation/logging.
        Schema is preserved.
        """
        with self._lock, self._connect() as conn:
            outcomes = conn.execute("SELECT COUNT(*) AS c FROM outcomes").fetchone()["c"]
            trades = conn.execute("SELECT COUNT(*) AS c FROM trades").fetchone()["c"]
            decisions = conn.execute("SELECT COUNT(*) AS c FROM decisions").fetchone()["c"]
            conn.execute("DELETE FROM outcomes")
            conn.execute("DELETE FROM trades")
            conn.execute("DELETE FROM decisions")
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('outcomes', 'trades', 'decisions')"
            )
        return {
            "decisions": int(decisions),
            "trades": int(trades),
            "outcomes": int(outcomes),
        }

    # ---- Helpers --------------------------------------------------------

    @staticmethod
    def _row_to_decision_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        # Parse JSON-encoded fields back into native types
        for field_name in ("take_profit", "selected_analysts"):
            raw = d.get(field_name)
            if raw:
                try:
                    d[field_name] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d[field_name] = []
            else:
                d[field_name] = []
        d["allow_shorts"] = bool(d.get("allow_shorts"))
        return d


# Singleton access for convenient module-level use
_journal_singleton: TradeJournal | None = None
_singleton_lock = threading.Lock()


def get_journal() -> TradeJournal:
    """Return the process-wide journal instance (lazy init)."""
    global _journal_singleton
    if _journal_singleton is None:
        with _singleton_lock:
            if _journal_singleton is None:
                _journal_singleton = TradeJournal()
    return _journal_singleton


def build_decision_from_state(
    *,
    ticker: str,
    trade_date: str,
    final_state: dict[str, Any],
    signal: str | None,
    config: dict[str, Any],
    selected_analysts: Iterable[str],
    position_size_dollars: float | None,
    execution_time_seconds: float | None,
    allow_shorts: bool,
) -> DecisionRecord:
    """Extract a DecisionRecord from the full TradingAgentsGraph state dict."""
    investment_debate = final_state.get("investment_debate_state") or {}
    risk_debate = final_state.get("risk_debate_state") or {}
    approved_prices = final_state.get("approved_trading_prices") or {}

    conviction = None
    try:
        from tradingagents.agents.utils.position_size_extractor import extract_conviction
        decision_text = final_state.get("final_trade_decision") or ""
        if decision_text:
            conviction = extract_conviction(decision_text)
    except Exception as exc:
        logger.warning("Conviction extraction failed for %s: %s", ticker, exc)

    llm_cost = None
    try:
        from tradingagents.llm_cost import get_thread_cost
        cost = get_thread_cost()
        if cost > 0:
            llm_cost = round(cost, 4)
    except Exception:
        pass

    return DecisionRecord(
        ticker=ticker,
        trade_date=trade_date,
        signal=signal,
        market_report=final_state.get("market_report"),
        sentiment_report=final_state.get("sentiment_report"),
        news_report=final_state.get("news_report"),
        fundamentals_report=final_state.get("fundamentals_report"),
        macro_report=final_state.get("macro_report"),
        bull_summary=_last_message(investment_debate.get("bull_history")),
        bear_summary=_last_message(investment_debate.get("bear_history")),
        judge_decision=investment_debate.get("judge_decision")
        or investment_debate.get("current_response"),
        trader_plan=final_state.get("trader_investment_plan")
        or final_state.get("investment_plan"),
        risk_debate_summary=risk_debate.get("judge_decision")
        or risk_debate.get("latest_speaker"),
        final_decision=final_state.get("final_trade_decision"),
        position_size_dollars=position_size_dollars,
        entry_price=_safe_float(approved_prices.get("entry_price")),
        stop_loss=_safe_float(approved_prices.get("stop_loss")),
        take_profit=_normalize_targets(approved_prices.get("targets")),
        selected_analysts=list(selected_analysts),
        research_depth=str(config.get("research_depth")) if config.get("research_depth") is not None else None,
        llm_provider=config.get("llm_provider"),
        quick_llm=config.get("quick_think_llm"),
        deep_llm=config.get("deep_think_llm"),
        execution_time_seconds=execution_time_seconds,
        allow_shorts=allow_shorts,
        conviction=conviction,
        llm_cost_estimate=llm_cost,
    )


def _last_message(history: Any) -> str | None:
    """Return the last non-empty message from a debate history string."""
    if not history:
        return None
    if isinstance(history, list):
        for msg in reversed(history):
            if msg:
                return str(msg)
        return None
    # history is often a single accumulated string
    text = str(history).strip()
    return text or None


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_targets(targets: Any) -> list[float]:
    if not targets:
        return []
    if isinstance(targets, (list, tuple)):
        out = []
        for t in targets:
            fv = _safe_float(t)
            if fv is not None:
                out.append(fv)
        return out
    return []
