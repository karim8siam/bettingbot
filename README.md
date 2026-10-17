# SX Bet paper research bot

Experimental totals-market scanner with simulated positions and optional Telegram alerts.
The generic Poisson/Gaussian models are **not calibrated evidence of profitability**.
Live execution is disabled until durable submission, fill, fee, and wallet reconciliation exists.

## Setup

Use Python 3.11+ with OpenSSL, then run from the repository directory:

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pytest
cp .env.example .env
python -m pytest -q
python bot.py --dry-run --single-scan
```

Set `SX_API_KEY` for authenticated orderbook access, including paper scans. No private key is
needed for paper mode. Optional `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` enable outbound
notifications; this repository has no Telegram command handler. Tests mock Telegram and do
not send messages. The bot must have permission to post to the configured destination.

## Enforced rules

- Quarter-Kelly by default, capped at 1.5% per position; 5% daily loss budget and three open positions.
- Open stake consumes the remaining daily risk budget. A $1 minimum never overrides a risk cap.
  Consequently a $10 bankroll cannot open a position at a 1.5% cap. The example uses $1,000 of simulated capital.
- Only type-2 regulation full-match Over/Under markets with half-point lines are modeled.
  Handicap, team/period totals, overtime, integer pushes, and quarter-line splits are excluded.
- Match start time is not a live score feed. In-play evaluation requires explicit score, clock,
  and an `updated_at` Unix timestamp no older than 30 seconds. Set `LIVE_STATS_FILE` to a
  provider JSON file keyed by SX event ID. Without a feed, in-play markets are skipped.
  Signals expire after 30 seconds, at kickoff, or when their source data expires, whichever is first.
- Prices and depth are checked again before simulated execution. This is still a snapshot simulation,
  not a latency/fee/queue-position execution backtest.
- Outcome identity is stored with each trade. Unknown settlement stays pending; void returns stake.
- Cash equals initial capital plus realized net PnL minus pending stakes. Settlement happens once;
  cash and today's realized losses are restored after restart. Daily boundaries use UTC.
- Ledgers are separate by network and mode: `data/audit_mainnet_paper.db`, etc. Old `audit.db`
  is preserved and is **not automatically migrated**: its mixed-mode records and missing outcome
  identity need manual reconciliation. Keep the same initial bankroll when resuming a ledger.
- A POSIX process lock prevents a second scanner from opening the same network ledger.
- Telegram messages identify simulations, escape market labels, and do not log token-bearing URLs.

## Limits and further work

There is no demonstrated betting edge. League/team priors, red-card feeds, overtime rules, calibration,
fees and historical validation need real inputs. Basketball/NFL models remain generic experiments,
not league-validated forecasts. The runner records the last observed executable quote before kickoff
when it is within 30 seconds of kickoff; this is sampled CLV, not a guaranteed market close.
Optional `USE_WEBSOCKET=true` enables a bounded, versioned cache with polling fallback; execution
always rechecks REST depth. The cache holds at most 100 markets per run; other markets use REST.

Before reintroducing live execution, implement persistent order intent, idempotent client order IDs,
unknown-response recovery, actual fill/fee reconciliation, verified available balance, and exchange
integration tests. A successful POST is not a confirmed filled bet. `--live` fails explicitly.

## API references checked during review

- [Orderbook snapshot](https://docs.sx.bet/api-reference/get-market-orderbook-snapshot)
- [Find markets and settlement outcomes](https://docs.sx.bet/api-reference/get-markets-find)
- [Active-market pagination](https://docs.sx.bet/api-reference/get-markets-active)
- [Market types](https://docs.sx.bet/api-reference/market-types)
- [Create orders](https://docs.sx.bet/api-reference/post-orders-v3)

## Diagnostics and inputs

`python check_connection.py` checks SX metadata, the active token/escrow's spendable balance,
realtime authentication, and Telegram identity/destination posting permissions. It sends no messages
or orders and returns a nonzero exit code for failed required checks. Do not paste secrets in chat.

The live-score adapter accepts an atomically replaced JSON file like this (use a current Unix
source timestamp, actual SX event ID, and actual match state; these are illustrative values):

```json
{"L12345": {"minute": 67, "home_score": 1, "away_score": 0, "updated_at": 1780000000,
             "home_red": 0, "away_red": 0}}
```

This adapter does not generate scores. SX's raw `periodTime` field does not fully specify the
sport-specific clock convention; this implementation deliberately requires an explicit match minute
from your provider rather than guessing. Missing, stale, malformed, or mismatched events are skipped.

## Historical evaluation

Supply CSV columns `event_id,timestamp,model_prob,decimal_odds,won`, with one independent event per
row and timezone-aware ISO timestamps. Forecasts and odds must have been recorded before the result.
Do not substitute invented probabilities or use future information.

```sh
python research/evaluate.py forecasts.csv --output evaluation.json --cost-per-unit 0.02
```

This fits a logistic probability calibration on the earliest 70% and evaluates only on later events.
It requires at least 200 events and 30 holdout events, rejects duplicate event IDs, and reports Brier
score, log loss, flat-unit return, and drawdown with the supplied cost sensitivity. Equal timestamps
stay in the same partition. It does not automatically activate a model or certify profitability.
No real dataset was supplied during this review, so no real profitability result is claimed.

## Existing-order recovery (read-only)

```sh
python reconcile_orders.py --order-id 0x... --client-id original-id --market-hash 0x...
```

This persists order identity, reads all fill pages, deduplicates fills, and stores settlement/fee facts
in `data/orders_<network>.db`. Missing acknowledgement or incomplete fill accounting remains UNKNOWN.
A fully filled order is `INACTIVE` with an inactive reason, not an exchange `FILLED` status. The
recovery command never submits, retries, or cancels an order. It does not credit a paper balance.
It is preparation for account reconciliation, not a complete automated live execution system.

## Validation status

48 tests pass, including a mocked full scan/restart, win/loss/void accounting, source expiry,
CLV timing, process locking, SX balance selection, partial-fill recovery, Telegram permissions,
WebSocket ordering and side conversion, and chronological evaluation without holdout leakage.
Authenticated SX/Telegram and real WebSocket connectivity still require locally configured credentials.
