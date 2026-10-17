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
  and an `updated_at` Unix timestamp no older than 30 seconds. The CLI has no live-score adapter
  yet, so it skips in-play opportunities and can research pre-match markets within 24 hours.
- Prices and depth are checked again before simulated execution. This is still a snapshot simulation,
  not a latency/fee/queue-position execution backtest.
- Outcome identity is stored with each trade. Unknown settlement stays pending; void returns stake.
- Cash equals initial capital plus realized net PnL minus pending stakes. Settlement happens once;
  cash and today's realized losses are restored after restart. Daily boundaries use UTC.
- Ledgers are separate by network and mode: `data/audit_mainnet_paper.db`, etc. Old `audit.db`
  is preserved and is **not automatically migrated**: its mixed-mode records and missing outcome
  identity need manual reconciliation. Keep the same initial bankroll when resuming a ledger.
- Run only one scanner process per ledger. Concurrent-process execution is not supported.
- Telegram messages identify simulations, escape market labels, and do not log token-bearing URLs.

## Limits and further work

There is no demonstrated betting edge. League/team priors, red-card feeds, overtime rules, calibration,
fees, historical validation, and closing-price collection need further work. Basketball/NFL models
remain generic experiments, not league-validated forecasts. CLV storage exists but the runner does
not collect closing prices automatically. The WebSocket wrapper is not wired into the polling runner.

Before reintroducing live execution, implement persistent order intent, idempotent client order IDs,
unknown-response recovery, actual fill/fee reconciliation, verified available balance, and exchange
integration tests. A successful POST is not a confirmed filled bet. `--live` fails explicitly.

## API references checked during review

- [Orderbook snapshot](https://docs.sx.bet/api-reference/get-market-orderbook-snapshot)
- [Find markets and settlement outcomes](https://docs.sx.bet/api-reference/get-markets-find)
- [Active-market pagination](https://docs.sx.bet/api-reference/get-markets-active)
- [Market types](https://docs.sx.bet/api-reference/market-types)
- [Create orders](https://docs.sx.bet/api-reference/post-orders-v3)
