"""
In-Play Quantitative Football +EV Strategy.
Targets in-play goal totals and game-state swing mispricings.
"""

import time
import re
from utils.orderbook import levels
from strategy.validation import validated_total, match_state
from typing import Dict, Any, List, Optional
from loguru import logger

from strategy.base import BaseStrategy, TradeSignal
from models.inplay_poisson import InPlayPoissonModel
from models.edge_calculator import EdgeCalculator
from utils.conversions import percentage_odds_to_decimal


class LiveFootballEVStrategy(BaseStrategy):
    def __init__(
        self,
        edge_calculator: EdgeCalculator,
        poisson_model: Optional[InPlayPoissonModel] = None,
        min_odds: float = 1.25,
        max_odds: float = 4.20,
    ):
        super().__init__(name="LiveFootballEVStrategy")
        self.edge_calculator = edge_calculator
        self.poisson = poisson_model or InPlayPoissonModel()
        self.min_odds = min_odds
        self.max_odds = max_odds

    def _parse_over_under_line(self, market: Dict[str, Any]) -> Optional[float]:
        """Extract goal line from market details or outcome names."""
        line = market.get("line")
        if line is not None:
            try:
                return float(line)
            except (ValueError, TypeError):
                pass

        # Try parsing from outcome names (e.g. 'Over 2.5 Goals')
        name1 = market.get("outcomeOneName", "")
        name2 = market.get("outcomeTwoName", "")
        match = re.search(r"(\d+\.?\d*)", f"{name1} {name2}")
        if match:
            return float(match.group(1))

        return None

    def evaluate_market(
        self,
        market: Dict[str, Any],
        orderbook: Dict[str, Any],
        live_stats: Optional[Dict[str, Any]] = None,
    ) -> List[TradeSignal]:
        """
        Evaluate live football market against dynamic in-play Poisson model.
        """
        signals: List[TradeSignal] = []
        if str(market.get("sportLabel", "")).lower() not in ("soccer", "association football"):
            return signals
        market_hash = market.get("marketHash", "")
        team1 = market.get("teamOneName", "Team 1")
        team2 = market.get("teamTwoName", "Team 2")
        event_name = f"{team1} vs {team2}"

        # Current match state
        total = validated_total(market)
        state = match_state(market, live_stats)
        if total is None or state is None:
            return signals
        line, side_one, side_two = total
        minute, home_score, away_score = state
        if minute >= 95:
            return signals
        home_red = live_stats.get("home_red", 0) if live_stats else 0
        away_red = live_stats.get("away_red", 0) if live_stats else 0
        rolling_sot = live_stats.get("rolling_sot", 0) if live_stats else 0

        # We evaluate: Total Goals (Over/Under) for Soccer (lines typically 0.5 to 6.5)
        line = self._parse_over_under_line(market)
        if line is not None and 0.5 <= line <= 6.5:
            probs = self.poisson.get_over_under_probabilities(
                minute=minute,
                current_home_goals=home_score,
                current_away_goals=away_score,
                line=line,
                home_red_cards=home_red,
                away_red_cards=away_red,
                rolling_sot=rolling_sot,
            )

            # Check outcome 1 (Typically "Over")
            out1_levels = levels(orderbook.get("outcomeOne", []), require_size=False)
            if out1_levels:
                best1 = out1_levels[0]
                pct_odds = str(best1["percentageOdds"])
                p_model = probs[side_one]
                eval1 = self.edge_calculator.evaluate_bet(
                    model_prob=p_model,
                    percentage_odds=pct_odds,
                    min_odds=self.min_odds,
                    max_odds=self.max_odds,
                )

                if eval1.is_positive_ev:
                    signals.append(
                        TradeSignal(
                            market_hash=market_hash,
                            event_name=event_name,
                            outcome_name=market.get("outcomeOneName", f"Over {line}"),
                            is_outcome_one=True,
                            percentage_odds=pct_odds,
                            decimal_odds=eval1.decimal_odds,
                            model_prob=p_model,
                            market_prob=eval1.market_prob,
                            edge_pct=eval1.edge_pct,
                            recommended_stake_fraction=eval1.recommended_stake_fraction,
                            strategy_name=self.name,
                            reason=eval1.reason,
                        )
                    )

            # Check outcome 2 (Typically "Under")
            out2_levels = levels(orderbook.get("outcomeTwo", []), require_size=False)
            if out2_levels:
                best2 = out2_levels[0]
                pct_odds = str(best2["percentageOdds"])
                p_model = probs[side_two]
                eval2 = self.edge_calculator.evaluate_bet(
                    model_prob=p_model,
                    percentage_odds=pct_odds,
                    min_odds=self.min_odds,
                    max_odds=self.max_odds,
                )

                if eval2.is_positive_ev:
                    signals.append(
                        TradeSignal(
                            market_hash=market_hash,
                            event_name=event_name,
                            outcome_name=market.get("outcomeTwoName", f"Under {line}"),
                            is_outcome_one=False,
                            percentage_odds=pct_odds,
                            decimal_odds=eval2.decimal_odds,
                            model_prob=p_model,
                            market_prob=eval2.market_prob,
                            edge_pct=eval2.edge_pct,
                            recommended_stake_fraction=eval2.recommended_stake_fraction,
                            strategy_name=self.name,
                            reason=eval2.reason,
                        )
                    )

        deadline = (float(live_stats['updated_at']) + 30) if live_stats else float(market['gameTime'])
        for signal in signals:
            signal.event_id = market.get("sportXeventId")
            signal.expires_at = min(signal.expires_at, deadline)
        return signals
