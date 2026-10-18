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
