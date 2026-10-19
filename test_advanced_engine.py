"""
Tests for Advanced Quantitative Engine:
- Multiplicative, Power, and Shin devigging
- Ensemble structural + devigged market consensus blending
- VWAP multi-level orderbook depth and slippage calculations
"""

import pytest
import math
from engine.devigger import devig_proportional, devig_power, devig_shin, calculate_two_way_fair_odds
from models.ensemble import EnsemblePredictor
from utils.orderbook import calculate_vwap_odds


def test_devig_methods():
    # Symmetric 50/50 test with 5% vig (52.5% each side)
    p1, p2 = 0.525, 0.525
    f1_prop, f2_prop = devig_proportional(p1, p2)
    assert abs(f1_prop - 0.50) < 1e-4
    assert abs(f2_prop - 0.50) < 1e-4

    f1_pow, f2_pow = devig_power(p1, p2)
    assert abs(f1_pow - 0.50) < 1e-4

    f1_shin, f2_shin = devig_shin(p1, p2)
    assert abs(f1_shin - 0.50) < 1e-4


def test_shin_asymmetric_favorite_longshot():
    # Favorite 70%, Longshot 35% (overround 5%)
    p1, p2 = 0.70, 0.35
    f1, f2 = devig_shin(p1, p2)
    assert f1 + f2 == pytest.approx(1.0)
    # Shin accounts for insider trading on longshots -> fair longshot prob is lower than proportional
    f1_prop, f2_prop = devig_proportional(p1, p2)
    assert f1 > f1_prop  # Favorite has higher fair prob under Shin
    assert f2 < f2_prop  # Longshot has lower fair prob under Shin


def test_calculate_two_way_fair_odds():
    # Percentage odds on SX Bet: 50% = 5 * 10^19
    half = "50000000000000000000"
    res = calculate_two_way_fair_odds(half, half, method="shin")
    assert res is not None
    assert abs(res["p1_fair"] - 0.50) < 1e-4
    assert abs(res["odds1_fair"] - 2.00) < 1e-4


def test_ensemble_blending():
    ensemble = EnsemblePredictor(prematch_market_weight=0.50, inplay_market_weight=0.25)
    model_probs = {"over": 0.60, "under": 0.40}
    # Book with 50/50 consensus
    half = "50000000000000000000"
    orderbook = {
        "outcomeOne": [{"percentageOdds": half, "size": "100000000"}],
        "outcomeTwo": [{"percentageOdds": half, "size": "100000000"}],
    }

    # Pre-match: 50% model (0.60) + 50% devigged market (0.50) = 0.55
    pre_blended = ensemble.blend_probabilities(model_probs, orderbook, minute=0)
    assert abs(pre_blended["over"] - 0.55) < 1e-3

    # In-play: 75% model (0.60) + 25% devigged market (0.50) = 0.575
    inplay_blended = ensemble.blend_probabilities(model_probs, orderbook, minute=45)
    assert abs(inplay_blended["over"] - 0.575) < 1e-3


def test_vwap_orderbook_depth():
    # Two levels:
    # Level 1: $0.50 USDC @ 2.40 odds (pct odds ~ 41.67%)
    # Level 2: $1.50 USDC @ 2.00 odds (pct odds 50%)
    levels = [
        {"percentageOdds": "41666666666666666667", "size": "500000"},   # 0.5 USDC
        {"percentageOdds": "50000000000000000000", "size": "1500000"},  # 1.5 USDC
    ]

    # Stake $1.00 USDC: takes $0.50 @ 2.40 + $0.50 @ 2.00 -> VWAP = (1.20 + 1.00)/1.0 = 2.20
    vwap, filled, worst = calculate_vwap_odds(levels, required_stake_usdc=1.0)
    assert abs(vwap - 2.20) < 0.01
    assert abs(filled - 1.0) < 1e-4
    assert worst == "50000000000000000000"
