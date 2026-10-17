"""
Order Execution Engine.
Handles trade routing for both Paper Trading (Dry-Run) and Live SX Bet Orderbook submission.
"""

import uuid
import time
from typing import Dict, Any, Optional
from loguru import logger

from client.rest_client import SXBetClient
from client.signer import SXOrderSigner
from engine.risk_manager import RiskManager
from engine.audit_logger import AuditLogger
from engine.telegram_notifier import TelegramNotifier
from utils.conversions import usdc_to_units, percentage_odds_to_decimal


class ExecutionEngine:
    def __init__(
        self,
        client: SXBetClient,
        signer: SXOrderSigner,
        risk_manager: RiskManager,
        audit_logger: AuditLogger,
        telegram_notifier: Optional[TelegramNotifier] = None,
        dry_run: bool = True,
    ):
        self.client = client
        self.signer = signer
        self.risk_manager = risk_manager
        self.audit_logger = audit_logger
        self.telegram_notifier = telegram_notifier
        self.dry_run = dry_run

    def execute_bet(
        self,
        market_hash: str,
        event_name: str,
        outcome_name: str,
        is_outcome_one: bool,
        percentage_odds: str,
        recommended_stake_fraction: float,
        model_prob: float = 0.0,
        edge_pct: float = 0.0,
        minute: Optional[int] = None,
        score: Optional[str] = None,
        expires_at: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Validate, size, and execute a bet (Paper or Live).
        """
        if not self.dry_run:
            raise RuntimeError("Live execution disabled: durable order/fill reconciliation is not implemented.")

        if expires_at is not None and not time.time() < expires_at:
            return None

        # Step 1: Risk Manager Validation & Sizing
        approved, stake_usdc, reason = self.risk_manager.validate_and_size_stake(
            recommended_stake_fraction=recommended_stake_fraction,
            market_hash=market_hash,
        )

        decimal_odds = percentage_odds_to_decimal(percentage_odds)

        if not approved:
            logger.warning(f"Trade Rejected by Risk Manager: {reason}")
            return None

        # Re-fetch immediately before paper execution: a scan may take minutes.
        book = self.client.get_orderbook(market_hash, show_taker_perspective=True)
        levels = book.get("outcomeOne" if is_outcome_one else "outcomeTwo", [])
        available_units = sum(int(level.get("size", 0)) for level in levels
                              if 0 < int(level.get("percentageOdds", 0)) <= int(percentage_odds)
                              and int(level.get("size", 0)) > 0)
        if available_units < usdc_to_units(stake_usdc):
            logger.info("Skipping stale or insufficient orderbook liquidity")
            return None

        if expires_at is not None and not time.time() < expires_at:
            return None

        # Step 2: Route by Execution Mode
        if self.dry_run:
            # --- PAPER TRADING EXECUTION ---
            simulated_order_id = f"paper_{uuid.uuid4().hex[:16]}"
            logger.success(
                f"[DRY-RUN SIMULATION] Bet Placed: {event_name} | {outcome_name} | ${stake_usdc:.2f} USDC @ {decimal_odds:.2f} odds (Order ID: {simulated_order_id})"
            )
            self.audit_logger.log_trade(
                order_id=simulated_order_id,
                is_paper=True,
                market_hash=market_hash,
                event_name=event_name,
                outcome_name=outcome_name,
                stake_usdc=stake_usdc,
                decimal_odds=decimal_odds,
                status="SIMULATED",
                is_outcome_one=is_outcome_one,
            )

            # Deduct stake from simulated bankroll
            self.risk_manager.record_trade_opened(stake_usdc)

            # Telegram Notification #1: Trade Opened
            if self.telegram_notifier:
                self.telegram_notifier.notify_trade_opened(
                    event_name=event_name,
                    outcome_name=outcome_name,
                    stake_usdc=stake_usdc,
                    decimal_odds=decimal_odds,
                    model_prob=model_prob,
                    edge_pct=edge_pct,
                    current_bankroll=self.risk_manager.current_bankroll,
                    minute=minute,
                    score=score,
                    is_demo=True,
                )

            return {
                "order_id": simulated_order_id,
                "is_paper": True,
                "status": "SIMULATED",
                "stake_usdc": stake_usdc,
                "decimal_odds": decimal_odds,
            }
