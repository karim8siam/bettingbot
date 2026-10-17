"""
Audit and CLV (Closing Line Value) Logger.
Persists all signals, evaluations, and simulated/live trades into a local SQLite database.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger


class AuditLogger:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self):
        """Create audit tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Signals table: every market evaluated
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    market_hash TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    outcome_name TEXT NOT NULL,
                    minute INTEGER,
                    score TEXT,
                    model_prob REAL NOT NULL,
                    market_prob REAL NOT NULL,
                    decimal_odds REAL NOT NULL,
                    edge_pct REAL NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL
                )
            """)

            # Trades table: every trade placed (paper or live)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    is_paper INTEGER NOT NULL,
                    market_hash TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    outcome_name TEXT NOT NULL,
                    stake_usdc REAL NOT NULL,
                    decimal_odds REAL NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT DEFAULT 'PENDING',
                    pnl_usdc REAL DEFAULT 0.0,
                    closing_odds REAL,
                    clv_pct REAL
                )
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
            for name, kind in [("is_outcome_one", "INTEGER"), ("settled_at", "TEXT")]:
                if name not in columns:
                    conn.execute(f"ALTER TABLE trades ADD COLUMN {name} {kind}")
            conn.commit()

    def log_signal(
        self,
        market_hash: str,
        event_name: str,
        outcome_name: str,
        minute: Optional[int],
        score: Optional[str],
        model_prob: float,
        market_prob: float,
        decimal_odds: float,
        edge_pct: float,
        decision: str,
        reason: str,
    ):
        """Log a market scan evaluation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO signals (
                    timestamp, market_hash, event_name, outcome_name,
                    minute, score, model_prob, market_prob, decimal_odds,
                    edge_pct, decision, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.utcnow().isoformat(),
                    market_hash,
                    event_name,
                    outcome_name,
                    minute,
                    score or "",
                    model_prob,
                    market_prob,
                    decimal_odds,
                    edge_pct,
                    decision,
                    reason,
                ),
            )
            conn.commit()

    def log_trade(
        self,
        order_id: str,
        is_paper: bool,
        market_hash: str,
        event_name: str,
        outcome_name: str,
        stake_usdc: float,
        decimal_odds: float,
        status: str = "FILLED",
        is_outcome_one: Optional[bool] = None,
    ):
        """Log an executed or simulated trade."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trades (
                    order_id, timestamp, is_paper, market_hash,
                    event_name, outcome_name, stake_usdc, decimal_odds, status, is_outcome_one
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    datetime.utcnow().isoformat(),
                    1 if is_paper else 0,
                    market_hash,
                    event_name,
                    outcome_name,
                    stake_usdc,
                    decimal_odds,
                    status,
                    is_outcome_one,
                ),
            )
            conn.commit()
        logger.info(
            f"Logged {'[PAPER]' if is_paper else '[LIVE]'} Trade: {event_name} | {outcome_name} | ${stake_usdc:.2f} @ {decimal_odds:.2f}"
        )

    def update_closing_line_value(self, order_id: str, closing_odds: float):
        """
        Record Closing Line Value (CLV).
        CLV Formula: (bet_odds / closing_odds) - 1.0
        A positive CLV means you beat the closing market!
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT decimal_odds FROM trades WHERE order_id = ?", (order_id,))
            row = cursor.fetchone()
            if row:
                bet_odds = row[0]
                clv_pct = (bet_odds / closing_odds) - 1.0 if closing_odds > 0 else 0.0
                cursor.execute(
                    "UPDATE trades SET closing_odds = ?, clv_pct = ? WHERE order_id = ?",
                    (closing_odds, clv_pct, order_id),
                )
                conn.commit()

    def get_pending_trades(self) -> List[Dict[str, Any]]:
        """Get all trades that are currently pending settlement."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE result = 'PENDING'")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def settle_trade(
        self,
        order_id: str,
        won: Optional[bool],
        pnl_usdc: float,
        closing_odds: Optional[float] = None,
    ):
        """Update trade with final settlement result."""
        result_str = "VOID" if won is None else ("WON" if won else "LOST")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE trades 
                SET result = ?, pnl_usdc = ?, closing_odds = COALESCE(?, closing_odds), settled_at = ?
                WHERE order_id = ? AND result = 'PENDING'
                """,
                (result_str, pnl_usdc, closing_odds, datetime.utcnow().isoformat(), order_id),
            )
            conn.commit()
        return cursor.rowcount == 1

    def get_trade_summary(self) -> Dict[str, Any]:
        """Fetch cumulative performance metrics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN result = 'WON' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN result = 'LOST' THEN 1 ELSE 0 END) as losses,
                    SUM(pnl_usdc) as total_pnl,
                    AVG(clv_pct) as avg_clv
                FROM trades
            """)
            row = cursor.fetchone()
            return {
                "total_trades": row[0] or 0,
                "wins": row[1] or 0,
                "losses": row[2] or 0,
                "total_pnl": row[3] or 0.0,
                "avg_clv_pct": (row[4] or 0.0) * 100,
            }

    def restore_risk(self, risk, initial_bankroll):
        """Reconstruct cash and UTC-day loss budget from this mode/network ledger."""
        today = datetime.utcnow().date().isoformat()
        with self._get_connection() as conn:
            pnl = conn.execute("SELECT COALESCE(SUM(pnl_usdc),0) FROM trades WHERE result != 'PENDING'").fetchone()[0]
            daily = conn.execute("SELECT COALESCE(SUM(pnl_usdc),0) FROM trades WHERE settled_at LIKE ?", (today + '%',)).fetchone()[0]
        pending = self.get_pending_trades()
        risk.pending_stakes = sum(t['stake_usdc'] for t in pending)
        risk.active_open_trades = len(pending)
        risk.current_bankroll = initial_bankroll + pnl - risk.pending_stakes
        risk.daily_pnl = daily
        risk.initial_daily_bankroll = initial_bankroll + pnl - daily
        risk.is_circuit_breaker_active = daily <= -risk.initial_daily_bankroll * risk.max_daily_drawdown_pct
