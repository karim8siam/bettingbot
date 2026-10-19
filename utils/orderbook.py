"""Strict parsing of aggregated integer book levels."""
import re


def integer(value):
    if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
        raise ValueError('Orderbook amounts must be unsigned integer strings')
    return int(value)


def levels(raw, require_size=True):
    if not isinstance(raw, list):
        raise ValueError('Orderbook side must be a list')
    result, seen = [], set()
    for level in raw:
        if not isinstance(level, dict):
            raise ValueError('Invalid orderbook level')
        price = integer(level.get('percentageOdds'))
        size = integer(level.get('size')) if require_size else integer(level.get('size', 1))
        if not 0 < price < 10**20 or size <= 0 or price in seen:
            raise ValueError('Invalid or duplicate aggregated orderbook level')
        seen.add(price)
        result.append({'percentageOdds': str(price), 'size': str(size)})
    return sorted(result, key=lambda level: int(level['percentageOdds']))


def calculate_vwap_odds(order_levels: list, required_stake_usdc: float):
    """
    Calculate the Volume-Weighted Average Price (VWAP) for a required stake size in USDC.
    Returns (effective_decimal_odds, available_fill_usdc, worst_percentage_odds).
    """
    from utils.conversions import percentage_odds_to_decimal
    if not order_levels or required_stake_usdc <= 0:
        return 0.0, 0.0, ""

    remaining_stake = required_stake_usdc
    total_cost = 0.0
    filled_stake = 0.0
    worst_price_odds = ""

    for lvl in order_levels:
        lvl_odds = percentage_odds_to_decimal(lvl['percentageOdds'])
        lvl_size_usdc = int(lvl.get('size', 0)) / 1_000_000.0
        if lvl_size_usdc <= 0 or lvl_odds <= 1.0:
            continue

        take = min(remaining_stake, lvl_size_usdc)
        total_cost += take * lvl_odds
        filled_stake += take
        remaining_stake -= take
        worst_price_odds = str(lvl['percentageOdds'])

        if remaining_stake <= 0.0001:
            break

    if filled_stake <= 0:
        return 0.0, 0.0, ""

    vwap_odds = total_cost / filled_stake
    return vwap_odds, filled_stake, worst_price_odds
