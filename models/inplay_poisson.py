"""
In-Play Dynamic Poisson and Time-Decay Model for Live Football.
Models in-play goal intensities, remaining time decay, and micro-state adjustments.
"""

import math
from typing import Dict, Tuple


class InPlayPoissonModel:
    def __init__(self, default_match_xg: float = 2.70):
        if not math.isfinite(default_match_xg) or default_match_xg <= 0:
            raise ValueError("Expected goals must be positive and finite")
        self.default_match_xg = default_match_xg

    def _poisson_pmf(self, k: int, lam: float) -> float:
        """Standard Poisson probability mass function: P(X = k) = (lam^k * e^-lam) / k!"""
        if lam <= 0:
            return 1.0 if k == 0 else 0.0
        return (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)

    def calculate_remaining_time_fraction(self, minute: int) -> float:
        """
        Calculate non-linear remaining match fraction.
        Accounts for stoppage time (effective 95 mins) and late-game fatigue surge.
        """
        minute = max(0, min(minute, 95))
        remaining_minutes = max(0, 95 - minute)
        
        # Base linear remaining fraction
        base_fraction = remaining_minutes / 95.0

        # Non-linear adjustment: After minute 70, goal rates increase by ~20-30%
        # due to defensive fatigue, broken structures, and desperate attacks.
        if minute >= 70 and remaining_minutes > 0:
            surge_multiplier = 1.18
            return min(1.0, base_fraction * surge_multiplier)
        
        return base_fraction

    def estimate_remaining_lambdas(
        self,
        minute: int,
        home_score: int,
        away_score: int,
        home_red_cards: int = 0,
        away_red_cards: int = 0,
        rolling_sot: int = 0,               # shots on target in last 15 mins
        prematch_home_xg: float = None,
        prematch_away_xg: float = None,
    ) -> Tuple[float, float]:
        """
        Estimate the expected goals (lambda) for both teams for the REMAINING minutes.
        """
        prematch_home_xg = self.default_match_xg * .54 if prematch_home_xg is None else prematch_home_xg
        prematch_away_xg = self.default_match_xg * .46 if prematch_away_xg is None else prematch_away_xg
        rem_fraction = self.calculate_remaining_time_fraction(minute)

        # Baseline remaining lambdas
        rem_home = prematch_home_xg * rem_fraction
        rem_away = prematch_away_xg * rem_fraction

        # Adjust for red cards
        if home_red_cards > 0:
            rem_home *= math.pow(0.60, home_red_cards)
            rem_away *= math.pow(1.35, home_red_cards)
        if away_red_cards > 0:
            rem_away *= math.pow(0.60, away_red_cards)
            rem_home *= math.pow(1.35, away_red_cards)

        # Adjust for game-state urgency:
        # If trailing by 1 goal after 65th minute, team pushes forward
        if minute >= 65:
            goal_diff = home_score - away_score
            if goal_diff == 1:
                # Away is trailing by 1 -> high attacking pressure, leaves counter-attack gaps
                rem_away *= 1.20
                rem_home *= 1.10
            elif goal_diff == -1:
                # Home is trailing by 1
                rem_home *= 1.20
                rem_away *= 1.10

        # Momentum modifier from rolling shots on target
        if rolling_sot >= 4:
            rem_home *= 1.15
            rem_away *= 1.15

        return rem_home, rem_away

    def get_over_under_probabilities(
        self,
        minute: int,
        current_home_goals: int,
        current_away_goals: int,
        line: float = 2.5,
        home_red_cards: int = 0,
        away_red_cards: int = 0,
        rolling_sot: int = 0,
        prematch_total_xg: float = None,
    ) -> Dict[str, float]:
        """
        Calculate in-play probability for Over/Under {line} total match goals.
        """
        prematch_total_xg = self.default_match_xg if prematch_total_xg is None else prematch_total_xg
        if not math.isfinite(prematch_total_xg) or prematch_total_xg <= 0:
            raise ValueError("Expected goals must be positive and finite")
        current_total = current_home_goals + current_away_goals
        
        # If current total already exceeds line, Over is 100%
        if current_total > line:
            return {"over": 1.0, "under": 0.0}

        goals_needed_for_over = math.floor(line - current_total) + 1
        
        rem_home, rem_away = self.estimate_remaining_lambdas(
            minute=minute,
            home_score=current_home_goals,
            away_score=current_away_goals,
            home_red_cards=home_red_cards,
            away_red_cards=away_red_cards,
            rolling_sot=rolling_sot,
            prematch_home_xg=prematch_total_xg * 0.54,
            prematch_away_xg=prematch_total_xg * 0.46,
        )
        total_remaining_lambda = rem_home + rem_away

        # Sum Poisson PMF for remaining goals < goals_needed_for_over (which means Under)
        p_under = sum(
            self._poisson_pmf(k, total_remaining_lambda)
            for k in range(0, goals_needed_for_over)
        )
        p_over = max(0.0, 1.0 - p_under)

        return {"over": p_over, "under": p_under}

    def get_match_result_probabilities(
        self,
        minute: int,
        current_home_goals: int,
        current_away_goals: int,
        home_red_cards: int = 0,
        away_red_cards: int = 0,
        max_additional_goals: int = 6,
    ) -> Dict[str, float]:
        """
        Calculate in-play Home / Draw / Away probabilities given current score and minute.
        """
        rem_home, rem_away = self.estimate_remaining_lambdas(
            minute=minute,
            home_score=current_home_goals,
            away_score=current_away_goals,
            home_red_cards=home_red_cards,
            away_red_cards=away_red_cards,
        )

        p_home = 0.0
        p_draw = 0.0
        p_away = 0.0

        for h in range(max_additional_goals):
            p_h = self._poisson_pmf(h, rem_home)
            for a in range(max_additional_goals):
                p_a = self._poisson_pmf(a, rem_away)
                prob = p_h * p_a
                
                final_home = current_home_goals + h
                final_away = current_away_goals + a

                if final_home > final_away:
                    p_home += prob
                elif final_home == final_away:
                    p_draw += prob
                else:
                    p_away += prob

        total = p_home + p_draw + p_away
        if total > 0:
            return {
                "home": p_home / total,
                "draw": p_draw / total,
                "away": p_away / total,
            }
        return {"home": 0.333, "draw": 0.333, "away": 0.333}
