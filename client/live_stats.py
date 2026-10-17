"""Adapter for a provider's explicit, timestamped match state.

File shape: {"SX event ID": {"minute": 67, "home_score": 1, "away_score": 0,
"updated_at": 1780000000, "home_red": 0, "away_red": 0}}.
The provider must write atomically. No clock is inferred from kickoff or receipt time.
"""
import json
from pathlib import Path
from strategy.validation import match_state


class LiveStatsFeed:
    def __init__(self, path=''):
        self.path = Path(path) if path else None

    def get(self, market):
        if self.path is None:
            return None
        try:
            # Reload per market, so long scans cannot reuse an old in-memory feed.
            data = json.loads(self.path.read_text())
            event_id = market.get('sportXeventId')
            stats = data.get(event_id) if isinstance(data, dict) else None
            if not isinstance(stats, dict) or match_state(market, stats) is None:
                return None
            return stats
        except (OSError, ValueError, TypeError):
            return None
