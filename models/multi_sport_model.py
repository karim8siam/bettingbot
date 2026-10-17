"""
Multi-Sport Dynamic Probability and In-Play Scoring Models.
Provides quantitative models for Soccer, Basketball (NBA), American Football (NFL), Hockey, and Baseball.
"""

import math
from typing import Dict, Tuple, Optional
from models.inplay_poisson import InPlayPoissonModel


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


class InPlayBasketballModel:
    """
    Dynamic in-play scoring model for Basketball (NBA / College / EuroLeague).
    Uses pace-adjusted Gaussian distribution with late-game intentional foul surging.
    """
    def __init__(self, default_nba_total: float = 226.0, total_minutes: float = 48.0):
        self.default_nba_total = default_nba_total
        self.total_minutes = total_minutes
        self.points_per_minute = default_nba_total / total_minutes
        self.base_std_dev = 16.5  # Standard deviation for a full 48m NBA game

    def get_over_under_probabilities(
        self,
        minute: float,
        current_home_points: int,
        current_away_points: int,
        line: float,
        prematch_total: Optional[float] = None,
    ) -> Dict[str, float]:
        current_points = current_home_points + current_away_points
        if current_points > line:
            return {"over": 1.0, "under": 0.0}

        points_needed = line - current_points
        rem_minutes = max(0.0, self.total_minutes - min(self.total_minutes, minute))
        
        if rem_minutes <= 0.0:
            return {"over": 1.0 if current_points > line else 0.0, "under": 1.0 if current_points <= line else 0.0}

        base_total = prematch_total or self.default_nba_total
        base_pace = base_total / self.total_minutes

        # In the 4th quarter (last 4 minutes), if score is within 6 points,
        # pace surges by ~15% due to clock stoppages, intentional fouls, and free throws.
        if minute >= 44.0:
            score_diff = abs(current_home_points - current_away_points)
            if score_diff <= 8:
                base_pace *= 1.15

        expected_rem_points = base_pace * rem_minutes
        rem_std_dev = self.base_std_dev * math.sqrt(rem_minutes / self.total_minutes)
        rem_std_dev = max(1.0, rem_std_dev)

        # Z-score for points needed
        z = (points_needed - expected_rem_points) / rem_std_dev
        
        # P(Rem Points > points_needed) = 1 - CDF(z)
        p_over = max(0.01, min(0.99, 1.0 - _norm_cdf(z)))
        p_under = max(0.01, min(0.99, 1.0 - p_over))

        return {"over": p_over, "under": p_under}


class InPlayAmericanFootballModel:
    """
    Dynamic scoring model for American Football (NFL / NCAA).
    Standard total ~45.0 points across 60 minutes (4 quarters of 15 mins).
    """
    def __init__(self, default_nfl_total: float = 45.0, total_minutes: float = 60.0):
        self.default_nfl_total = default_nfl_total
        self.total_minutes = total_minutes
        self.base_std_dev = 13.5

    def get_over_under_probabilities(
        self,
        minute: float,
        current_home_points: int,
        current_away_points: int,
        line: float,
        prematch_total: Optional[float] = None,
    ) -> Dict[str, float]:
        current_points = current_home_points + current_away_points
        if current_points > line:
            return {"over": 1.0, "under": 0.0}

        points_needed = line - current_points
        rem_minutes = max(0.0, self.total_minutes - min(self.total_minutes, minute))

        if rem_minutes <= 0.0:
            return {"over": 1.0 if current_points > line else 0.0, "under": 1.0 if current_points <= line else 0.0}

        base_total = prematch_total or self.default_nfl_total
        base_pace = base_total / self.total_minutes

        expected_rem_points = base_pace * rem_minutes
        rem_std_dev = self.base_std_dev * math.sqrt(rem_minutes / self.total_minutes)
        rem_std_dev = max(1.0, rem_std_dev)

        z = (points_needed - expected_rem_points) / rem_std_dev
        p_over = max(0.01, min(0.99, 1.0 - _norm_cdf(z)))
        p_under = max(0.01, min(0.99, 1.0 - p_over))

        return {"over": p_over, "under": p_under}


class MultiSportModelManager:
    """Unified engine manager coordinating models across all sports."""
    def __init__(self):
        self.soccer_model = InPlayPoissonModel(default_match_xg=2.70)
        self.basketball_model = InPlayBasketballModel(default_nba_total=226.0)
        self.nfl_model = InPlayAmericanFootballModel(default_nfl_total=45.0)
