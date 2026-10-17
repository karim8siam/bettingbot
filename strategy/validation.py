"""Conservative input checks shared by both experimental strategies."""
import math
import re
import time


def validated_total(market):
    # Only full-match binary totals with half-point lines; push/split settlement
    # and period/team totals need dedicated models, not the full-match model.
    names = [str(market.get(k, '')) for k in ('outcomeOneName', 'outcomeTwoName')]
    parsed = [re.fullmatch(r'(Over|Under)\s+(\d+(?:\.\d+)?)(?:\s+(?:Goals|Points))?', n.strip(), re.I) for n in names]
    if not all(parsed) or {m[1].lower() for m in parsed} != {'over', 'under'}:
        return None
    lines = [float(m[2]) for m in parsed]
    if lines[0] != lines[1] or lines[0] % 1 != .5:
        return None
    try:
        if market.get('line') is not None and float(market['line']) != lines[0]:
            return None
    except (ValueError, TypeError):
        return None
    # SX type 2 is regulation full-game totals. Overtime is not modeled.
    if str(market.get('type')) != '2':
        return None
    return lines[0], parsed[0][1].lower(), parsed[1][1].lower()


def match_state(market, live_stats):
    now = time.time()
    try:
        start = float(market.get('gameTime', 0))
    except (ValueError, TypeError):
        return None
    if not math.isfinite(start) or start <= 0 or market.get('status') != 'ACTIVE':
        return None
    if start > now:
        return (0, 0, 0) if start - now <= 86400 else None
    # Never infer current score or clock from kickoff. Require a fresh feed.
    if not isinstance(live_stats, dict):
        return None
    try:
        minute, home, away, timestamp = [float(live_stats[k]) for k in ('minute', 'home_score', 'away_score', 'updated_at')]
    except (KeyError, ValueError, TypeError):
        return None
    if not all(math.isfinite(v) for v in (minute, home, away, timestamp)):
        return None
    if not 0 <= now - timestamp <= 30 or minute < 0 or home < 0 or away < 0 or not home.is_integer() or not away.is_integer():
        return None
    for key in ('home_red', 'away_red', 'rolling_sot'):
        value = live_stats.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value != int(value):
            return None
    return minute, int(home), int(away)
