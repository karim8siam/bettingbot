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
  cash and today's realized losses are restored after restart. A triggered daily stop remains latched
  after later wins and restarts. Initial capital is stored and cannot silently change on restart. Daily boundaries use UTC.
- Ledgers are separate by network and mode: `data/audit_mainnet_paper.db`, etc. Old `audit.db`
  is preserved and is **not automatically migrated**: its mixed-mode records and missing outcome
  identity need manual reconciliation. Keep the same initial bankroll when resuming a ledger.
- A POSIX process lock prevents a second scanner from opening the same network ledger.
- Telegram messages identify simulations, escape market labels, and do not log token-bearing URLs.

## Limits and further work

There is no demonstrated betting edge. League/team priors, red-card feeds, overtime rules, calibration,
fees and historical validation need real inputs. Only NBA regulation basketball and NFL regulation football are admitted to their respective models.
Basketball/NFL models remain generic experiments,
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

72 tests pass, including a mocked full scan/restart, win/loss/void accounting, source expiry,
CLV timing, process locking, SX balance selection, partial-fill recovery, Telegram permissions,
WebSocket ordering and side conversion, and chronological evaluation without holdout leakage.
Authenticated SX/Telegram and real WebSocket connectivity still require locally configured credentials.

## Reliable alerts and collected forecast data

Trade/settlement records and their alert jobs are committed together in SQLite. Successful alerts
are marked SENT. Explicit Telegram rate limits are retried later (up to five attempts), without
sleeping in the scanner. Timeouts, server errors, or a crash during sending are UNKNOWN: they may
already have delivered, so the bot does not blindly resend them. Permanent failures are FAILED.
The dashboard shows waiting and attention counts. Changing the channel never reroutes old alerts.
Exactly-once delivery cannot be guaranteed by Telegram's sendMessage interface.

To inspect unresolved alerts without sending anything:

```sh
python -c "import sqlite3; c=sqlite3.connect('data/audit_mainnet_paper.db'); print(c.execute(\"SELECT id,state,attempts FROM notifications WHERE state != 'SENT'\").fetchall())"
```

New paper trades retain the probability seen at entry and the SX event ID. Export settled records:

```sh
python research/export.py data/audit_mainnet_paper.db --output forecasts.csv
python research/evaluate.py forecasts.csv --output evaluation.json --cost-per-unit 0.02
```

The export excludes voids, missing identifiers/probabilities, and duplicate event IDs. It does not
backfill old trades with invented predictions. Evaluation still requires sufficient real observations.

Additional reliability checks cover capital changes, latched daily stops, transactional alert creation,
rate limits, ambiguous delivery, changed destinations, malformed/duplicate depth, recovery lookup
failures, configured expected goals, unsupported leagues, and recorded-forecast export.

## Preview notifications without credentials

```sh
python preview_notifications.py
```

Open `data/notification-preview.html` to see two explicitly labeled fictional signal/result
examples. No order is submitted or written to the trading ledger. The preview checks a 10 USDC
balance against the configured risk limits: at the default 1.5% cap, the maximum 0.15 stake
is below the bot's 1.00 minimum, so actual execution is rejected. The illustrative result is
not an observed match result or evidence of profitability. This bot accounts in USDC, not USDT.

After configuring `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` in `.env`, explicitly send
the two labeled examples with `python preview_notifications.py --telegram`. A failed or
uncertain delivery stops the command; do not rerun blindly if the first message may have arrived.
Real market scans additionally require `SX_API_KEY`; in-play scans need a fresh score feed.

Read-only SX requests retry transient connection/read errors and HTTP 429/502/503/504 at most twice. Order submission and cancellation responses are never automatically retried. Unsupported markets and stale/missing score inputs are filtered before requesting order books.

For a bounded connectivity test, run `python bot.py --dry-run --single-scan --max-market-pages 3`.
This samples at most three market pages and explicitly reports truncated discovery. Omitting the
option scans all pages. Successful sampled discovery does not verify all markets or predict results.
Live routing and hidden simulation labels from the later main-branch change are intentionally
disabled here: a submission acknowledgement is not a confirmed fill, and simulated outcomes must
remain distinguishable from real trades. Stake sizing never bypasses the configured percentage cap.
