"""
Ensemble Probability Engine.
Combines Structural Physical Time-Decay Models with Orderbook Devigged Consensus
to achieve optimal predictive accuracy and minimize false-positive edges.
"""

from typing import Dict, Any, Optional
from engine.devigger import calculate_two_way_fair_odds


class EnsemblePredictor:
    """
    Blends physical simulation models with real-time devigged market consensus.
    """
    def __init__(
        self,
        prematch_market_weight: float = 0.50,
        inplay_market_weight: float = 0.25,
    ):
        self.prematch_market_weight = prematch_market_weight
        self.inplay_market_weight = inplay_market_weight

    def blend_probabilities(
        self,
        model_probs: Dict[str, float],
        orderbook: Dict[str, Any],
        minute: float,
        side_one_key: str = "over",
        side_two_key: str = "under",
    ) -> Dict[str, float]:
        """
        Produce ensemble probabilities combining model output and market consensus.
        """
        # 1. Attempt to extract devigged consensus from orderbook
        out1_levels = orderbook.get("outcomeOne", [])
        out2_levels = orderbook.get("outcomeTwo", [])

        if not out1_levels or not out2_levels:
            # Fall back to structural model if book is one-sided
            return model_probs

        best1 = str(out1_levels[0].get("percentageOdds", "0"))
        best2 = str(out2_levels[0].get("percentageOdds", "0"))

        fair_res = calculate_two_way_fair_odds(best1, best2, method="shin")
        if not fair_res:
            return model_probs

        # 2. Determine weighting: in-play markets rely more heavily on physical decay
        w_market = self.inplay_market_weight if minute > 0 else self.prematch_market_weight
        w_model = 1.0 - w_market

        m1 = model_probs.get(side_one_key, 0.50)
        m2 = model_probs.get(side_two_key, 0.50)

        f1 = fair_res["p1_fair"]
        f2 = fair_res["p2_fair"]

        blended1 = (w_model * m1) + (w_market * f1)
        blended2 = (w_model * m2) + (w_market * f2)

        total = blended1 + blended2
        if total > 0:
            blended1 /= total
            blended2 /= total

        return {
            side_one_key: blended1,
            side_two_key: blended2,
            f"{side_one_key}_raw_model": m1,
            f"{side_two_key}_raw_model": m2,
            f"{side_one_key}_devig": f1,
            f"{side_two_key}_devig": f2,
        }
