"""
Order Execution Engine.
Handles trade routing for both Paper Trading (Dry-Run) and Live SX Bet Orderbook submission.
"""

import uuid
import time
from engine.notifications import dispatch_notifications
from utils.orderbook import levels as parse_levels
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
        event_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Validate, size, and execute a bet (Paper or Live).
        """
        if not self.dry_run and not getattr(self, "enable_live_execution", False):
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
        levels = parse_levels(book.get("outcomeOne" if is_outcome_one else "outcomeTwo", []))
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
            notification = None
            if self.telegram_notifier and self.telegram_notifier.is_configured:
                notification = {
                    'destination': self.telegram_notifier.channel_id,
                    'payload': dict(event_name=event_name, outcome_name=outcome_name,
                                    stake_usdc=stake_usdc, decimal_odds=decimal_odds,
                                    model_prob=model_prob, edge_pct=edge_pct,
                                    current_bankroll=self.risk_manager.current_bankroll-stake_usdc,
                                    minute=minute, score=score, is_demo=True),
                }
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
                model_prob=model_prob,
                event_id=event_id,
                notification=notification,
            )

            # Deduct stake from simulated bankroll
            self.risk_manager.record_trade_opened(stake_usdc)

            if self.telegram_notifier:
                dispatch_notifications(self.audit_logger, self.telegram_notifier)

            return {
                "order_id": simulated_order_id,
                "is_paper": True,
                "status": "SIMULATED",
                "stake_usdc": stake_usdc,
                "decimal_odds": decimal_odds,
            }

        # --- LIVE SX BET ORDER SUBMISSION ---
        if not self.signer or not self.signer.is_configured():
            logger.error("Live trading enabled but no valid SX_PRIVATE_KEY provided.")
            return None

        try:
            domain = self.client.domain
            base_token = self.client.base_token
            total_bet_units = usdc_to_units(stake_usdc)

            # Build and sign EIP-712 order
            order, order_sig, order_id = self.signer.sign_order(
                domain=domain,
                market_hash=market_hash,
                base_token=base_token,
                total_bet_size=total_bet_units,
                percentage_odds=percentage_odds,
                is_maker_betting_outcome_one=is_outcome_one,
                expiry_seconds=3600,
            )

            # Submit with FOK (Fill or Kill)
            submission_payload = [{
                **order,
                "timeInForce": "FOK",
                "orderSignature": order_sig,
            }]

            logger.info(f"Submitting LIVE order {order_id} to SX Bet...")
            resp = self.client.submit_orders(submission_payload)
            logger.success(f"Live order response: {resp}")

            notification = None
            if self.telegram_notifier and self.telegram_notifier.is_configured:
                notification = {
                    'destination': self.telegram_notifier.channel_id,
                    'payload': dict(
                        event_name=event_name, outcome_name=outcome_name,
                        stake_usdc=stake_usdc, decimal_odds=decimal_odds,
                        model_prob=model_prob, edge_pct=edge_pct,
                        current_bankroll=self.risk_manager.current_bankroll - stake_usdc,
                        minute=minute, score=score, is_demo=False,
                    ),
                }

            self.audit_logger.log_trade(
                order_id=order_id,
                is_paper=False,
                market_hash=market_hash,
                event_name=event_name,
                outcome_name=outcome_name,
                stake_usdc=stake_usdc,
                decimal_odds=decimal_odds,
                status="SUBMITTED",
                is_outcome_one=is_outcome_one,
                model_prob=model_prob,
                event_id=event_id,
                notification=notification,
            )

            self.risk_manager.record_trade_opened(stake_usdc)

            if self.telegram_notifier:
                dispatch_notifications(self.audit_logger, self.telegram_notifier)

            return {
                "order_id": order_id,
                "is_paper": False,
                "status": "SUBMITTED",
                "stake_usdc": stake_usdc,
                "decimal_odds": decimal_odds,
                "api_response": resp,
            }

        except Exception as e:
            logger.error(f"Failed to submit live order: {e}")
            return None
