"""
Expected Value (+EV) and Staking Calculator.
Calculates statistical edge, implied probability, and Fractional Kelly sizing.
"""

from dataclasses import dataclass
import math
from typing import Optional
from utils.conversions import percentage_odds_to_decimal, percentage_odds_to_probability


@dataclass
class EdgeEvaluation:
    model_prob: float
    market_prob: float
    decimal_odds: float
    edge_pct: float             # EV percentage (e.g. 0.052 for +5.2%)
    is_positive_ev: bool
    recommended_stake_fraction: float
    reason: str


class EdgeCalculator:
    def __init__(
        self,
        min_edge_pct: float = 0.04,
        kelly_fraction: float = 0.25,
        max_stake_pct: float = 0.015,
        taker_fee_pct: float = 0.0,
    ):
        self.min_edge_pct = min_edge_pct
        self.kelly_fraction = kelly_fraction
        self.max_stake_pct = max_stake_pct
        self.taker_fee_pct = taker_fee_pct

    def get_net_decimal_odds(self, decimal_odds: float) -> float:
        """Calculate net odds after deducting exchange profit fee (SX Bet 1% taker fee)."""
        if self.taker_fee_pct > 0 and decimal_odds > 1.0:
            return 1.0 + (decimal_odds - 1.0) * (1.0 - self.taker_fee_pct)
        return decimal_odds

    def calculate_ev(self, model_prob: float, decimal_odds: float) -> float:
        """
        Calculate expected value percentage.
        Formula: EV = (model_prob * net_decimal_odds) - 1.0
        """
        net_odds = self.get_net_decimal_odds(decimal_odds)
        return (model_prob * net_odds) - 1.0

    def calculate_kelly_stake(self, model_prob: float, decimal_odds: float) -> float:
        """
        Calculate Fractional Kelly stake percentage of bankroll.
        Full Kelly: f* = (b * p - q) / b
        where b = net_decimal_odds - 1, p = model_prob, q = 1 - p.
        """
        net_odds = self.get_net_decimal_odds(decimal_odds)
        b = net_odds - 1.0
        if b <= 0 or model_prob <= 0 or model_prob >= 1.0:
            return 0.0

        p = model_prob
        q = 1.0 - p
        full_kelly = (b * p - q) / b

        if full_kelly <= 0:
            return 0.0

        fractional_kelly = full_kelly * self.kelly_fraction
        # Cap at max stake percentage to prevent tail risk
        return min(fractional_kelly, self.max_stake_pct)

    def evaluate_bet(
        self,
        model_prob: float,
        percentage_odds: str,
        min_odds: float = 1.20,
        max_odds: float = 4.50,
    ) -> EdgeEvaluation:
        """
        Evaluate if a betting opportunity meets the strict mathematical +EV rules.
        """
        if not math.isfinite(model_prob) or not 0 <= model_prob <= 1:
            raise ValueError("Model probability must be finite and between zero and one")
        decimal_odds = percentage_odds_to_decimal(percentage_odds)
        market_prob = percentage_odds_to_probability(percentage_odds)

        if decimal_odds < min_odds:
            return EdgeEvaluation(
                model_prob=model_prob,
                market_prob=market_prob,
                decimal_odds=decimal_odds,
                edge_pct=0.0,
                is_positive_ev=False,
                recommended_stake_fraction=0.0,
                reason=f"Odds {decimal_odds:.2f} below minimum threshold {min_odds:.2f}",
            )

        if decimal_odds > max_odds:
            return EdgeEvaluation(
                model_prob=model_prob,
                market_prob=market_prob,
                decimal_odds=decimal_odds,
                edge_pct=0.0,
                is_positive_ev=False,
                recommended_stake_fraction=0.0,
                reason=f"Odds {decimal_odds:.2f} above maximum threshold {max_odds:.2f}",
            )

        ev = self.calculate_ev(model_prob, decimal_odds)

        if ev < self.min_edge_pct:
            return EdgeEvaluation(
                model_prob=model_prob,
                market_prob=market_prob,
                decimal_odds=decimal_odds,
                edge_pct=ev,
                is_positive_ev=False,
                recommended_stake_fraction=0.0,
                reason=f"Edge {ev:.2%} below minimum required {self.min_edge_pct:.2%}",
            )

        stake_fraction = self.calculate_kelly_stake(model_prob, decimal_odds)

        return EdgeEvaluation(
            model_prob=model_prob,
            market_prob=market_prob,
            decimal_odds=decimal_odds,
            edge_pct=ev,
            is_positive_ev=True,
            recommended_stake_fraction=stake_fraction,
            reason=f"+EV opportunity! Edge: {ev:.2%}, Staking: {stake_fraction:.2%}",
        )
