"""
Base Strategy Interface.
Defines the structure for all quantitative betting strategies.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
from typing import Dict, Any, List, Optional


@dataclass
class TradeSignal:
    market_hash: str
    event_name: str
    outcome_name: str
    is_outcome_one: bool
    percentage_odds: str
    decimal_odds: float
    model_prob: float
    market_prob: float
    edge_pct: float
    recommended_stake_fraction: float
    strategy_name: str
    reason: str
    expires_at: float = field(default_factory=lambda: time.time() + 30)


class BaseStrategy(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def evaluate_market(
        self,
        market: Dict[str, Any],
        orderbook: Dict[str, Any],
        live_stats: Optional[Dict[str, Any]] = None,
    ) -> List[TradeSignal]:
        """
        Evaluate an active market and its orderbook to find +EV trading opportunities.
        """
        pass
