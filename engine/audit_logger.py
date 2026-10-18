"""
Audit and CLV (Closing Line Value) Logger.
Persists all signals, evaluations, and simulated/live trades into a local SQLite database.
"""

import sqlite3
from contextlib import contextmanager
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger


class AuditLogger:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        connection = sqlite3.connect(str(self.db_path))
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
            conn.execute("CREATE TABLE IF NOT EXISTS ledger_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, destination TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0)")
            # A crash after claiming a send can hide a successful delivery.
            conn.execute("UPDATE notifications SET state='UNKNOWN' WHERE state='SENDING'")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
            for name, kind in [("is_outcome_one", "INTEGER"), ("settled_at", "TEXT"), ("closing_candidate", "REAL"), ("closing_observed_at", "REAL"), ("model_prob", "REAL"), ("event_id", "TEXT")]:
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
        model_prob: Optional[float] = None,
        event_id: Optional[str] = None,
        notification: Optional[dict] = None,
    ):
        """Log a trade and its alert atomically."""
        if not math.isfinite(stake_usdc) or stake_usdc <= 0 or not math.isfinite(decimal_odds) or decimal_odds <= 1:
            raise ValueError("Trade amounts and odds must be valid")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trades (
                    order_id, timestamp, is_paper, market_hash,
                    event_name, outcome_name, stake_usdc, decimal_odds, status, is_outcome_one, model_prob, event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    model_prob,
                    event_id,
                ),
            )
            if notification:
                self._queue_notification(conn, 'opened:' + order_id, 'opened', notification)
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
        notification: Optional[dict] = None,
    ):
        """Update trade with final settlement result."""
        if not math.isfinite(pnl_usdc):
            raise ValueError("Settlement PnL must be finite")
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
            changed = cursor.rowcount == 1
            if changed and notification:
                self._queue_notification(conn, "settled:" + order_id, "settled", notification)
            conn.commit()
        return changed

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
            conn.execute("INSERT OR IGNORE INTO ledger_meta VALUES ('initial_bankroll', ?)", (str(initial_bankroll),))
            original = float(conn.execute("SELECT value FROM ledger_meta WHERE key='initial_bankroll'").fetchone()[0])
            if original != initial_bankroll:
                raise ValueError(f"This ledger started with {original:.2f}; restore INITIAL_BANKROLL or use a separate ledger")
            daily_results = [row[0] for row in conn.execute("SELECT pnl_usdc FROM trades WHERE settled_at LIKE ? ORDER BY settled_at, id", (today + '%',))]
            pnl = conn.execute("SELECT COALESCE(SUM(pnl_usdc),0) FROM trades WHERE result != 'PENDING'").fetchone()[0]
            daily = conn.execute("SELECT COALESCE(SUM(pnl_usdc),0) FROM trades WHERE settled_at LIKE ?", (today + '%',)).fetchone()[0]
        pending = self.get_pending_trades()
        risk.pending_stakes = sum(t['stake_usdc'] for t in pending)
        risk.active_open_trades = len(pending)
        risk.current_bankroll = initial_bankroll + pnl - risk.pending_stakes
        risk.daily_pnl = daily
        risk.initial_daily_bankroll = initial_bankroll + pnl - daily
        running = 0.0
        risk.is_circuit_breaker_active = False
        for result in daily_results:
            running += result
            if running <= -risk.initial_daily_bankroll * risk.max_daily_drawdown_pct:
                risk.is_circuit_breaker_active = True

    def save_closing_candidate(self, order_id, odds, observed_at):
        with self._get_connection() as conn:
            conn.execute("UPDATE trades SET closing_candidate=?, closing_observed_at=? WHERE order_id=? AND closing_odds IS NULL", (odds, observed_at, order_id))

    def finalize_closing_candidate(self, order_id, kickoff, max_age=30):
        with self._get_connection() as conn:
            row = conn.execute("SELECT closing_candidate, closing_observed_at FROM trades WHERE order_id=? AND closing_odds IS NULL", (order_id,)).fetchone()
        if row and row[0] and row[1] is not None and 0 < kickoff-row[1] <= max_age:
            self.update_closing_line_value(order_id, row[0])

    @staticmethod
    def _queue_notification(conn, event_id, kind, notification):
        conn.execute("INSERT INTO notifications(id,kind,payload,destination) VALUES (?,?,?,?)", (event_id, kind, json.dumps(notification['payload']), notification['destination']))

    def get_notification_summary(self):
        with self._get_connection() as conn:
            counts = dict(conn.execute("SELECT state, COUNT(*) FROM notifications GROUP BY state"))
        return {
            'waiting': counts.get('PENDING', 0) + counts.get('RETRY', 0),
            'attention': counts.get('FAILED', 0) + counts.get('UNKNOWN', 0) + counts.get('SENDING', 0),
            'sent': counts.get('SENT', 0),
        }
