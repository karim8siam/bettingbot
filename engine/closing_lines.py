"""Record the last observed executable pre-kickoff quote, not a post-result price."""
import time
from utils.conversions import percentage_odds_to_decimal


def collect_closing_lines(client, audit, now=None, max_age=30):
    now = time.time() if now is None else now
    for trade in audit.get_pending_trades():
        market = client.find_market(trade['market_hash'])
        if not market:
            continue
        start = market.get('gameTime')
        if not isinstance(start, (int, float)) or start <= 0:
            continue
        if now < start and market.get('status') == 'ACTIVE':
            book = client.get_orderbook(trade['market_hash'], show_taker_perspective=True)
            side = 'outcomeOne' if trade['is_outcome_one'] else 'outcomeTwo'
            prices = [int(l['percentageOdds']) for l in book.get(side, [])
                      if int(l.get('size', 0)) >= round(trade['stake_usdc'] * 1_000_000)
                      and 0 < int(l.get('percentageOdds', 0)) < 10**20]
            if prices:
                audit.save_closing_candidate(trade['order_id'], percentage_odds_to_decimal(min(prices)), now)
        elif now >= start:
            audit.finalize_closing_candidate(trade['order_id'], start, max_age)
