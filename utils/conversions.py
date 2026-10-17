"""
SX Bet Unit and Odds Conversion Utilities.

SX Bet represents odds on a 10^20 integer scale (percentageOdds) and USDC amounts
with 6 decimal places (1 USDC = 1,000,000 units).
"""

from typing import Union

PERCENTAGE_ODDS_SCALE = 10**20
USDC_DECIMALS = 6
USDC_SCALE = 10**USDC_DECIMALS


def usdc_to_units(amount_usdc: Union[float, int]) -> int:
    """Convert human USDC amount (e.g. 5.50) to integer contract units (5,500,000)."""
    return int(round(float(amount_usdc) * USDC_SCALE))


def units_to_usdc(units: Union[int, str]) -> float:
    """Convert integer contract units (e.g. 5,500,000) to human USDC amount (5.50)."""
    return float(units) / USDC_SCALE


def decimal_to_percentage_odds(decimal_odds: float) -> str:
    """
    Convert decimal odds (e.g. 2.00) to SX Bet percentageOdds string.
    Formula: percentageOdds = round(10^20 / decimalOdds)
    """
    if decimal_odds <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0, got {decimal_odds}")
    odds_int = int(round(PERCENTAGE_ODDS_SCALE / float(decimal_odds)))
    return str(odds_int)


def percentage_odds_to_decimal(percentage_odds: Union[str, int]) -> float:
    """
    Convert SX Bet percentageOdds (10^20 scale) to human decimal odds.
    Formula: decimalOdds = 10^20 / percentageOdds
    """
    p_int = int(percentage_odds)
    if not 0 < p_int < PERCENTAGE_ODDS_SCALE:
        raise ValueError(f"Percentage odds must be positive, got {p_int}")
    return PERCENTAGE_ODDS_SCALE / p_int


def percentage_odds_to_probability(percentage_odds: Union[str, int]) -> float:
    """
    Convert SX Bet percentageOdds to implied probability [0.0, 1.0].
    Formula: prob = percentageOdds / 10^20
    """
    p_int = int(percentage_odds)
    return p_int / PERCENTAGE_ODDS_SCALE


def probability_to_percentage_odds(prob: float) -> str:
    """
    Convert probability [0.0, 1.0] to SX Bet percentageOdds.
    """
    if not (0.0 < prob <= 1.0):
        raise ValueError(f"Probability must be in (0, 1], got {prob}")
    return str(int(round(prob * PERCENTAGE_ODDS_SCALE)))


def maker_odds_to_taker_odds(percentage_odds: Union[str, int]) -> str:
    """
    Convert maker perspective percentageOdds to taker perspective.
    takerOdds = 10^20 - makerOdds
    """
    p_int = int(percentage_odds)
    taker_int = PERCENTAGE_ODDS_SCALE - p_int
    return str(taker_int)
