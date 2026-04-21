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
                    source, source_order_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            return int(cur.lastrowid)

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
        source: str | None = None,
        exclude_source: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return decisions filtered by ticker/signal/date range/source."""
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
        source: str | None = None,
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
