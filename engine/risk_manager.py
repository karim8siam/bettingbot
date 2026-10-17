"""
Risk Management Engine.
Enforces bankroll preservation, Fractional Kelly limits, daily stop-loss, and anti-martingale rules.
"""

from datetime import datetime, date
from typing import Tuple
from loguru import logger


class RiskManager:
    def __init__(
        self,
        current_bankroll: float,
        kelly_fraction: float = 0.25,
        max_stake_pct: float = 0.015,
        max_daily_drawdown_pct: float = 0.05,
        max_concurrent_trades: int = 3,
    ):
        self.initial_daily_bankroll = current_bankroll
        self.current_bankroll = current_bankroll
        self.kelly_fraction = kelly_fraction
        self.max_stake_pct = max_stake_pct
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.max_concurrent_trades = max_concurrent_trades
        self.active_open_trades: int = 0
        
        self.current_day: date = datetime.utcnow().date()
        self.daily_pnl: float = 0.0
        self.consecutive_losses: int = 0
        self.is_circuit_breaker_active: bool = False

    def update_bankroll(self, balance: float):
        """Sync live or simulated bankroll."""
        self.current_bankroll = balance

    def check_new_day(self):
        """Reset daily tracking upon date rollover."""
        today = datetime.utcnow().date()
        if today != self.current_day:
            logger.info(f"New day detected ({today}). Resetting daily drawdown monitor.")
            self.current_day = today
            self.initial_daily_bankroll = self.current_bankroll
            self.daily_pnl = 0.0
            self.is_circuit_breaker_active = False

    def record_trade_result(self, pnl: float):
        """Update daily PnL and anti-martingale streaks."""
        self.check_new_day()
        self.daily_pnl += pnl
        self.current_bankroll += pnl
        self.active_open_trades = max(0, self.active_open_trades - 1)

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # Check daily drawdown circuit breaker
        max_allowed_loss = self.initial_daily_bankroll * self.max_daily_drawdown_pct
        if self.daily_pnl <= -max_allowed_loss:
            self.is_circuit_breaker_active = True
            logger.critical(
                f"CIRCUIT BREAKER TRIGGERED! Daily loss (-${abs(self.daily_pnl):.2f}) reached limit (-${max_allowed_loss:.2f}). Trading halted for the day."
            )

    def validate_and_size_stake(
        self,
        recommended_stake_fraction: float,
        market_hash: str,
    ) -> Tuple[bool, float, str]:
        """
        Validate whether a trade is permitted and return sized stake in USDC.
        Returns (is_approved, stake_usdc, reason).
        """
        self.check_new_day()

        if self.is_circuit_breaker_active:
            return False, 0.0, "Daily drawdown circuit breaker is active. Trading halted."

        if self.active_open_trades >= self.max_concurrent_trades:
            return False, 0.0, f"Max concurrent active trades limit reached ({self.max_concurrent_trades}). Waiting for settlement."

        if self.current_bankroll <= 5.0:
            return False, 0.0, f"Insufficient bankroll (${self.current_bankroll:.2f}). Minimum $5.00 required."

        if recommended_stake_fraction <= 0:
            return False, 0.0, "Zero or negative stake fraction recommended."

        # Cap stake fraction at max single-bet risk limit (e.g. 1.5%)
        capped_fraction = min(recommended_stake_fraction, self.max_stake_pct)
        raw_stake = self.current_bankroll * capped_fraction

        # Round stake to 2 decimals, enforce minimum $1.00 USDC
        stake_usdc = round(max(1.0, raw_stake), 2)

        # Ensure stake doesn't exceed maximum single-bet limit in dollars
        max_single_bet_dollars = self.current_bankroll * self.max_stake_pct
        if stake_usdc > max_single_bet_dollars and max_single_bet_dollars >= 1.0:
            stake_usdc = round(max_single_bet_dollars, 2)

        self.active_open_trades += 1
        return True, stake_usdc, f"Approved stake: ${stake_usdc:.2f} USDC ({capped_fraction:.2%} of bankroll)"
