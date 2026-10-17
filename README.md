# SX Bet Quantitative Live Betting Bot

A production-grade, mathematically sound live sports betting bot for [SX Bet](https://sx.bet), built on the 7 core principles of quantitative edge seeking:
1. **Mathematical +EV Barrier** (Only executes when $EV = P_{model} \times Odds - 1 > \text{Min Threshold}$).
2. **In-Play Poisson & Time-Decay Modeling** (Dynamic scoring intensity, non-linear late-game decay, red card penalties).
3. **Fractional Kelly Capital Allocation** (Quarter-Kelly staking with single-bet caps).
4. **Hard Drawdown Circuit Breakers** (Automatic emergency shutdown if daily loss reaches 5%).
5. **Zero Loss-Chasing** (Strict anti-martingale protection).
6. **3-Phase Deployment Lifecycle** (Phase 1 Paper Trading → Phase 2 Micro-Stakes → Phase 3 Scaling).
7. **Closing Line Value (CLV) & Audit Logging** (Tracks every signal, order, and closing price in SQLite).

---

## Architecture Overview

```
sx_betting_bot/
├── config.py                 # Bot configuration & risk parameters
├── client/
│   ├── rest_client.py        # SX Bet V3 REST API client (Markets, Orderbook snapshots, Balances)
│   ├── signer.py             # EIP-712 cryptographic signature engine (keccak256 order digests)
│   └── ws_client.py          # Real-time WebSocket streaming (Centrifuge) for live books
├── models/
│   ├── inplay_poisson.py     # Live football dynamic Poisson scoring rate & time decay
│   └── edge_calculator.py    # True vs. implied probabilities, EV hurdle, Quarter-Kelly sizing
├── strategy/
│   ├── base.py               # Abstract base strategy
│   └── live_football_ev.py   # In-play football +EV strategy (totals & game-state swings)
├── engine/
│   ├── risk_manager.py       # Quarter-Kelly staking, daily stop-loss, bankroll checks
│   ├── execution.py          # Dual-mode execution engine (Paper Trading vs Live FOK orders)
│   └── audit_logger.py       # SQLite database logging signals, trades, and CLV
├── bot.py                    # Interactive CLI runner with live dashboard
├── test_setup.py             # Diagnostic test suite
├── .env.example              # Configuration template
└── requirements.txt          # Verified dependencies
```

---

## Quickstart

### 1. Activate Environment
```bash
source /Users/karimsiam/.gemini/antigravity/scratch/sx_betting_bot/venv/bin/activate
cd /Users/karimsiam/.gemini/antigravity/scratch/sx_betting_bot
```

### 2. Run Verification Test Suite
```bash
python test_setup.py
```

### 3. Run in Paper Trading Mode (Default: $0 Risk)
```bash
python bot.py --dry-run
```
Or run a single diagnostic scan:
```bash
python bot.py --single-scan
```

### 4. Switch to Live Trading (When Ready)
1. In `.env`:
   - Set `DRY_RUN=False`
   - Set `SX_PRIVATE_KEY="0x..."` (from https://sx.bet/wallet/assets)
   - Set `SX_API_KEY="..."` (from https://sx.bet/account)
2. Run:
```bash
python bot.py --live
```
