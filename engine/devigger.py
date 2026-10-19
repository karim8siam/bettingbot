"""
Devigging Engine for Extracting True Market-Implied Probabilities.
Implements Multiplicative, Power, and Shin's algorithms to remove bookmaker/exchange margin.
"""

import math
from typing import Tuple, Dict, Optional
from utils.conversions import percentage_odds_to_probability, percentage_odds_to_decimal


def devig_proportional(p1_implied: float, p2_implied: float) -> Tuple[float, float]:
    """
    Multiplicative (proportional) devigging for a two-way market.
    Normalizes probabilities so P1 + P2 = 1.0.
    """
    total = p1_implied + p2_implied
    if total <= 0:
        return 0.5, 0.5
    return p1_implied / total, p2_implied / total


def devig_power(p1_implied: float, p2_implied: float) -> Tuple[float, float]:
    """
    Power Method devigging.
    Finds exponent k such that p1^k + p2^k = 1.0.
    More accurate than proportional for longshots/favorites.
    """
    if p1_implied <= 0 or p2_implied <= 0 or p1_implied >= 1.0 or p2_implied >= 1.0:
        return devig_proportional(p1_implied, p2_implied)

    # Binary search for k
    low, high = 0.01, 10.0
    for _ in range(40):
        mid = (low + high) / 2.0
        val = math.pow(p1_implied, mid) + math.pow(p2_implied, mid)
        if val > 1.0:
            low = mid
        else:
            high = mid
    k = (low + high) / 2.0
    fair1 = math.pow(p1_implied, k)
    fair2 = math.pow(p2_implied, k)
    total = fair1 + fair2
    return fair1 / total, fair2 / total


def devig_shin(p1_implied: float, p2_implied: float) -> Tuple[float, float]:
    """
    Shin's Method devigging.
    Accounts for the favorite-longshot bias and informed trader presence (z parameter).
    """
    if p1_implied <= 0 or p2_implied <= 0 or p1_implied >= 1.0 or p2_implied >= 1.0:
        return devig_proportional(p1_implied, p2_implied)

    total_prob = p1_implied + p2_implied
    if total_prob <= 1.0:
        # No vig or negative vig (arbitrage exists)
        return devig_proportional(p1_implied, p2_implied)

    # Shin's formula for two-way markets
    # z solves the quadratic relation for informed trading proportion
    diff = abs(p1_implied - p2_implied)
    z = (total_prob - 1.0) / (total_prob - diff) if (total_prob - diff) > 0 else 0.0
    z = max(0.0, min(0.40, z))

    def shin_prob(p: float) -> float:
        inside = (z ** 2) + 4 * (1.0 - z) * ((p ** 2) / total_prob)
        return (math.sqrt(max(0.0, inside)) - z) / (2.0 * (1.0 - z))

    f1 = shin_prob(p1_implied)
    f2 = shin_prob(p2_implied)
    tot = f1 + f2
    if tot <= 0:
        return devig_proportional(p1_implied, p2_implied)
    return f1 / tot, f2 / tot


def calculate_two_way_fair_odds(
    odds_one_str: str,
    odds_two_str: str,
    method: str = "shin",
) -> Optional[Dict[str, float]]:
    """
    Given the best resting percentageOdds for Outcome 1 and Outcome 2,
    extract the exact fair probabilities and vig-free fair odds.
    """
    p1 = percentage_odds_to_probability(odds_one_str)
    p2 = percentage_odds_to_probability(odds_two_str)

    if p1 <= 0 or p2 <= 0 or p1 >= 1.0 or p2 >= 1.0:
        return None

    if method == "power":
        fair1, fair2 = devig_power(p1, p2)
    elif method == "shin":
        fair1, fair2 = devig_shin(p1, p2)
    else:
        fair1, fair2 = devig_proportional(p1, p2)

    return {
        "p1_fair": fair1,
        "p2_fair": fair2,
        "odds1_fair": 1.0 / fair1 if fair1 > 0 else 0.0,
        "odds2_fair": 1.0 / fair2 if fair2 > 0 else 0.0,
        "overround": (p1 + p2) - 1.0,
    }
