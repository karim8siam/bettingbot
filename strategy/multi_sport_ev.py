"""
Universal Multi-Sport Quantitative +EV Strategy.
Analyzes active markets across all sports on SX Bet (Soccer, Basketball, American Football, Baseball, Hockey).
Enforces the same strict +EV hurdle and Quarter-Kelly sizing across all sports.
"""

import re
from strategy.validation import validated_total, match_state
import time
from typing import Dict, Any, List, Optional
from loguru import logger

from strategy.base import BaseStrategy, TradeSignal
from models.edge_calculator import EdgeCalculator
from models.multi_sport_model import MultiSportModelManager


class MultiSportEVStrategy(BaseStrategy):
    def __init__(
        self,
        edge_calculator: EdgeCalculator,
        min_odds: float = 1.25,
        max_odds: float = 4.20,
    ):
        super().__init__(name="MultiSportEVStrategy")
        self.edge_calculator = edge_calculator
        self.models = MultiSportModelManager()
        self.min_odds = min_odds
        self.max_odds = max_odds

    def _parse_total_line(self, market: Dict[str, Any]) -> Optional[float]:
        """Extract line number from market."""
        line = market.get("line")
        if line is not None:
            try:
                return float(line)
            except (ValueError, TypeError):
                pass

        name1 = market.get("outcomeOneName", "")
        name2 = market.get("outcomeTwoName", "")
        match = re.search(r"(\d+\.?\d*)", f"{name1} {name2}")
        if match:
            return float(match.group(1))

        return None

    def _detect_sport(self, market: Dict[str, Any]) -> str:
        """Identify sport type from market metadata."""
        sport_label = str(market.get("sportLabel", "")).lower()
        league_label = str(market.get("leagueLabel", "")).lower()

        if "soccer" in sport_label or "football" in sport_label:
            # Distinguish Association Football vs American Football by league or line
            line = self._parse_total_line(market)
            if "nfl" in league_label or "ncaa" in league_label or (line and line > 15.0):
                return "american_football"
            return "soccer"

        if "basketball" in sport_label or "nba" in league_label or "wnba" in league_label:
            return "basketball"

        if "baseball" in sport_label or "mlb" in league_label:
            return "baseball"

        if "hockey" in sport_label or "nhl" in league_label:
            return "hockey"

        return sport_label or "unknown"

    def _estimate_elapsed_minute(self, market: Dict[str, Any], sport: str) -> float:
        """Estimate in-play minute from game start time."""
        game_time = market.get("gameTime", 0)
        now = int(time.time())
        if game_time == 0 or now < game_time:
            return 0.0

        elapsed_seconds = now - game_time
        elapsed_minutes = elapsed_seconds / 60.0

        if sport == "soccer":
            if elapsed_minutes < 45.0:
                return elapsed_minutes
            elif 45.0 <= elapsed_minutes <= 60.0:
                return 45.0
            else:
                return min(95.0, elapsed_minutes - 15.0)

        elif sport == "basketball":
            # 48m regulation NBA game typically takes ~130 real minutes
            return min(48.0, elapsed_minutes * (48.0 / 130.0))

        elif sport == "american_football":
            # 60m regulation NFL game typically takes ~190 real minutes
            return min(60.0, elapsed_minutes * (60.0 / 190.0))

        return elapsed_minutes

    def evaluate_market(
        self,
        market: Dict[str, Any],
        orderbook: Dict[str, Any],
        live_stats: Optional[Dict[str, Any]] = None,
    ) -> List[TradeSignal]:
        signals: List[TradeSignal] = []
        market_hash = market.get("marketHash", "")
        team1 = market.get("teamOneName", "Team 1")
        team2 = market.get("teamTwoName", "Team 2")
        event_name = f"{team1} vs {team2}"

        sport = self._detect_sport(market)
        line = self._parse_total_line(market)

        if line is None:
            return signals

        total = validated_total(market)
        state = match_state(market, live_stats)
        if total is None or state is None:
            return signals
        line, side_one, side_two = total
        minute, home_score, away_score = state
        home_red = live_stats.get("home_red", 0) if live_stats else 0
        away_red = live_stats.get("away_red", 0) if live_stats else 0
        rolling_sot = live_stats.get("rolling_sot", 0) if live_stats else 0

        probs = None

        # 1. Evaluate by sport
        if sport == "soccer" and 0.5 <= line <= 7.5:
            probs = self.models.soccer_model.get_over_under_probabilities(
                minute=int(minute),
                current_home_goals=home_score,
                current_away_goals=away_score,
                line=line,
                home_red_cards=home_red,
                away_red_cards=away_red,
                rolling_sot=rolling_sot,
            )

        elif sport == "basketball" and 120.0 <= line <= 260.0:
            probs = self.models.basketball_model.get_over_under_probabilities(
                minute=minute,
                current_home_points=home_score,
                current_away_points=away_score,
                line=line,
            )

        elif sport == "american_football" and 25.0 <= line <= 75.0:
            probs = self.models.nfl_model.get_over_under_probabilities(
                minute=minute,
                current_home_points=home_score,
                current_away_points=away_score,
                line=line,
            )

        if not probs:
            return signals

        # 2. Check Outcome 1 (Typically "Over")
        out1_levels = orderbook.get("outcomeOne", [])
        if out1_levels:
            best1 = out1_levels[0]
            pct_odds = str(best1.get("percentageOdds", 0))
            if int(pct_odds) > 0:
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
                            event_name=f"[{sport.upper()}] {event_name}",
                            outcome_name=market.get("outcomeOneName", f"Over {line}"),
                            is_outcome_one=True,
                            percentage_odds=pct_odds,
                            decimal_odds=eval1.decimal_odds,
                            model_prob=p_model,
                            market_prob=eval1.market_prob,
                            edge_pct=eval1.edge_pct,
                            recommended_stake_fraction=eval1.recommended_stake_fraction,
                            strategy_name=f"{self.name}_{sport}",
                            reason=eval1.reason,
                        )
                    )

        # 3. Check Outcome 2 (Typically "Under")
        out2_levels = orderbook.get("outcomeTwo", [])
        if out2_levels:
            best2 = out2_levels[0]
            pct_odds = str(best2.get("percentageOdds", 0))
            if int(pct_odds) > 0:
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
                            event_name=f"[{sport.upper()}] {event_name}",
                            outcome_name=market.get("outcomeTwoName", f"Under {line}"),
                            is_outcome_one=False,
                            percentage_odds=pct_odds,
                            decimal_odds=eval2.decimal_odds,
                            model_prob=p_model,
                            market_prob=eval2.market_prob,
                            edge_pct=eval2.edge_pct,
                            recommended_stake_fraction=eval2.recommended_stake_fraction,
                            strategy_name=f"{self.name}_{sport}",
                            reason=eval2.reason,
                        )
                    )

        deadline = (float(live_stats['updated_at']) + 30) if live_stats else float(market['gameTime'])
        for signal in signals:
            signal.expires_at = min(signal.expires_at, deadline)
        return signals
