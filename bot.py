"""
SX Bet Quantitative Live Football Betting Bot.
Main entrypoint and interactive terminal runner.
"""

import sys
import time
import argparse
from typing import List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from loguru import logger

from config import config
from client.rest_client import SXBetClient
from client.signer import SXOrderSigner
from models.inplay_poisson import InPlayPoissonModel
from models.edge_calculator import EdgeCalculator
from engine.risk_manager import RiskManager
from engine.audit_logger import AuditLogger
from engine.execution import ExecutionEngine
from engine.telegram_notifier import TelegramNotifier
from strategy.live_football_ev import LiveFootballEVStrategy
from strategy.multi_sport_ev import MultiSportEVStrategy

console = Console()


def check_and_settle_pending_trades(
    client: SXBetClient,
    audit_logger: AuditLogger,
    risk_manager: RiskManager,
    telegram_notifier: TelegramNotifier,
    dry_run: bool,
):
    """Scan pending trades and settle those whose markets have resolved on SX Bet."""
    pending = audit_logger.get_pending_trades()
    if not pending:
        return

    for trade in pending:
        market_hash = trade.get("market_hash")
        order_id = trade.get("order_id")
        stake_usdc = trade.get("stake_usdc", 1.0)
        decimal_odds = trade.get("decimal_odds", 2.0)
        outcome_name = trade.get("outcome_name", "")
        event_name = trade.get("event_name", "")

        try:
            market_data = client.find_market(market_hash)
            if not market_data:
                continue

            # Check if market has settled/resolved
            is_settled = market_data.get("settled", False) or market_data.get("status") in ("RESOLVED", "SETTLED") or (market_data.get("status") == "INACTIVE" and bool(market_data.get("reportedDate")))
            if not is_settled:
                continue

            winning_outcome = market_data.get("outcome", market_data.get("winningOutcome"))
            if str(winning_outcome) not in ("0", "1", "2"):
                continue  # Unknown is not a loss.
            winning_outcome = int(winning_outcome)
            side = trade.get("is_outcome_one")
            if side is None or trade.get("status") not in ("SIMULATED", "FILLED"):
                continue  # Legacy unknown selection or unconfirmed submission.
            won = None if winning_outcome == 0 else winning_outcome == (1 if side else 2)
            pnl = 0.0 if won is None else (round(stake_usdc * (decimal_odds - 1.0), 2) if won else -stake_usdc)
            if not audit_logger.settle_trade(order_id=order_id, won=won, pnl_usdc=pnl):
                continue
            risk_manager.record_trade_result(pnl=pnl, stake_usdc=stake_usdc)

            # Send Telegram Notification #2: Settlement Result
            if telegram_notifier.is_configured:
                telegram_notifier.notify_trade_settled(
                    event_name=event_name,
                    outcome_name=outcome_name,
                    stake_usdc=stake_usdc,
                    decimal_odds=decimal_odds,
                    won=won,
                    pnl_usdc=pnl,
                    new_bankroll=risk_manager.current_bankroll,
                    is_demo=dry_run,
                )

        except Exception as err:
            logger.debug(f"Error checking settlement for trade {order_id}: {err}")


def render_banner(dry_run: bool, bankroll: float, daily_pnl: float):
    mode_text = "[bold green]PAPER TRADING (SIMULATION)[/bold green]" if dry_run else "[bold red]LIVE TRADING (REAL FUNDS)[/bold red]"
    banner_content = (
        f"[bold cyan]SX Bet Quantitative Live Betting Bot[/bold cyan]\n"
        f"Mode: {mode_text} | Network: [yellow]{config.network_name.upper()}[/yellow]\n"
        f"Bankroll: [bold white]${bankroll:.2f} USDC[/bold white] | Daily PnL: [{'green' if daily_pnl >= 0 else 'red'}]${daily_pnl:+.2f} USDC[/{'green' if daily_pnl >= 0 else 'red'}]\n"
        f"Rules: [italic]+EV Hurdle > {config.min_edge_pct:.1%}, Kelly Fraction {config.kelly_fraction:.2f}, Max Stake {config.max_stake_pct:.1%}[/italic]"
    )
    console.print(Panel(banner_content, border_style="cyan"))


def main():
    parser = argparse.ArgumentParser(description="SX Bet Quantitative Live Football Betting Bot")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", default=None, help="Force Paper Trading mode")
    modes.add_argument("--live", action="store_true", default=None, help="Force Live Trading mode (requires API credentials)")
    parser.add_argument("--single-scan", action="store_true", help="Run a single market scan and exit")
    args = parser.parse_args()

    # Determine mode: command line overrides config
    if args.live:
        dry_run = False
    elif args.dry_run:
        dry_run = True
    else:
        dry_run = config.dry_run

    if not dry_run:
        parser.error("Live execution disabled until durable order/fill reconciliation is implemented.")

    if not config.api_key or config.api_key.startswith("your_"):
        parser.error("Set SX_API_KEY: SX orderbook snapshots require authentication, including paper scans.")

    # Initialize components
    logger.info(f"Initializing SX Bet Bot on {config.network_name} (Dry Run = {dry_run})...")
    client = SXBetClient(base_url=config.rest_url, api_key=config.api_key)
    signer = SXOrderSigner(private_key="" if dry_run else config.private_key)
    audit_logger = AuditLogger(db_path=config.data_dir / f"audit_{config.network_name}_{'paper' if dry_run else 'live'}.db")

    current_bankroll = config.initial_bankroll

    risk_manager = RiskManager(
        current_bankroll=current_bankroll,
        kelly_fraction=config.kelly_fraction,
        max_stake_pct=config.max_stake_pct,
        max_daily_drawdown_pct=config.max_daily_drawdown_pct,
        max_concurrent_trades=config.max_concurrent_trades,
    )
    # Sync initial active trades count from database
    audit_logger.restore_risk(risk_manager, current_bankroll)

    edge_calculator = EdgeCalculator(
        min_edge_pct=config.min_edge_pct,
        kelly_fraction=config.kelly_fraction,
        max_stake_pct=config.max_stake_pct,
    )

    strategy = MultiSportEVStrategy(
        edge_calculator=edge_calculator,
        min_odds=config.min_odds,
        max_odds=config.max_odds,
    )

    telegram_notifier = TelegramNotifier(
        bot_token=config.telegram_bot_token,
        channel_id=config.telegram_channel_id,
    )

    execution_engine = ExecutionEngine(
        client=client,
        signer=signer,
        risk_manager=risk_manager,
        audit_logger=audit_logger,
        telegram_notifier=telegram_notifier,
        dry_run=dry_run,
    )

    render_banner(dry_run, risk_manager.current_bankroll, risk_manager.daily_pnl)

    # Scanner Loop
    scan_count = 0
    try:
        while True:
            scan_count += 1
            console.print(f"\n[cyan]---> Scan #{scan_count} at {time.strftime('%Y-%m-%d %H:%M:%S')} <---[/cyan]")

            try:
                # 0. Check and settle pending trades from previous scans
                check_and_settle_pending_trades(
                    client=client,
                    audit_logger=audit_logger,
                    risk_manager=risk_manager,
                    telegram_notifier=telegram_notifier,
                    dry_run=dry_run,
                )

                # 1. Fetch active markets
                all_markets = client.get_active_markets(only_main_line=False)
                now_ts = int(time.time())
                
                # Filter for target sports and kickoff within next 24 hours (or currently in-play)
                candidate_markets = []
                for m in all_markets:
                    gt = m.get("gameTime", 0)
                    if gt > 0 and (gt - now_ts) > 86400:
                        continue  # Skip games scheduled > 24 hours in future to prevent capital lock

                    if "all" in config.target_sports or "*" in config.target_sports:
                        candidate_markets.append(m)
                    elif any(target in str(m.get("sportLabel", "")).lower() or target in str(m.get("leagueLabel", "")).lower() for target in config.target_sports):
                        candidate_markets.append(m)

                console.print(f"Found [bold]{len(all_markets)}[/bold] total markets, evaluating [bold green]{len(candidate_markets)}[/bold green] matches within 24h window.")

                all_cycle_signals = []

                # 2. Evaluate markets across all sports
                for market in candidate_markets:
                    market_hash = market.get("marketHash")
                    if not market_hash:
                        continue

                    try:
                        # Fetch orderbook snapshot (taker perspective)
                        orderbook = client.get_orderbook(market_hash=market_hash, show_taker_perspective=True)
                        signals = strategy.evaluate_market(market=market, orderbook=orderbook)
                        all_cycle_signals.extend(signals)

                    except Exception as m_err:
                        logger.debug(f"Skipping market {market_hash}: {m_err}")

                # 3. Correlated Risk Shield: One Bet Per Match (Pick highest +EV line per event)
                best_signals_by_event = {}
                for signal in all_cycle_signals:
                    # Clean event name for deduplication (e.g. without sport tag)
                    base_event = signal.event_name
                    if base_event not in best_signals_by_event or signal.edge_pct > best_signals_by_event[base_event].edge_pct:
                        best_signals_by_event[base_event] = signal

                # Fetch currently open positions to prevent duplicate entries on the same match
                current_pending = audit_logger.get_pending_trades()
                pending_events = {t.get("event_name") for t in current_pending}
                pending_hashes = {t.get("market_hash") for t in current_pending}

                signals_found = len(best_signals_by_event)
                for event_name, signal in best_signals_by_event.items():
                    if signal.event_name in pending_events or signal.market_hash in pending_hashes:
                        console.print(f"[dim]Skipping {signal.event_name}: Position already active in portfolio.[/dim]")
                        continue

                    console.print(
                        f"[bold green]+EV Signal Selected (Best Line):[/bold green] {signal.event_name} | {signal.outcome_name} | "
                        f"Odds: [yellow]{signal.decimal_odds:.2f}[/yellow] | Model Prob: [cyan]{signal.model_prob:.1%}[/cyan] | "
                        f"Edge: [bold magenta]+{signal.edge_pct:.2%}[/bold magenta]"
                    )

                    # Log signal to audit database
                    audit_logger.log_signal(
                        market_hash=signal.market_hash,
                        event_name=signal.event_name,
                        outcome_name=signal.outcome_name,
                        minute=None,
                        score="",
                        model_prob=signal.model_prob,
                        market_prob=signal.market_prob,
                        decimal_odds=signal.decimal_odds,
                        edge_pct=signal.edge_pct,
                        decision="CANDIDATE",
                        reason=signal.reason,
                    )

                    # Execute bet (Paper or Live)
                    execution_engine.execute_bet(
                        market_hash=signal.market_hash,
                        event_name=signal.event_name,
                        outcome_name=signal.outcome_name,
                        is_outcome_one=signal.is_outcome_one,
                        percentage_odds=signal.percentage_odds,
                        recommended_stake_fraction=signal.recommended_stake_fraction,
                        model_prob=signal.model_prob,
                        edge_pct=signal.edge_pct,
                    )

                if signals_found == 0:
                    console.print("[dim]No markets satisfied the strict +EV hurdle and odds criteria. (Disciplined 'NO BET').[/dim]")

            except Exception as e:
                logger.error(f"Scan cycle encountered an error: {e}")

            # Performance summary table
            summary = audit_logger.get_trade_summary()
            table = Table(title="Bot Performance Summary", show_header=True, header_style="bold magenta")
            table.add_column("Total Trades")
            table.add_column("Wins")
            table.add_column("Losses")
            table.add_column("PnL ($ USDC)")
            table.add_column("Avg CLV (%)")
            table.add_row(
                str(summary["total_trades"]),
                str(summary["wins"]),
                str(summary["losses"]),
                f"${summary['total_pnl']:+.2f}",
                f"{summary['avg_clv_pct']:+.2f}%",
            )
            console.print(table)

            if args.single_scan:
                console.print("[yellow]Single scan completed. Exiting.[/yellow]")
                break

            console.print(f"[dim]Sleeping for {config.scan_interval_seconds}s until next scan... (Ctrl+C to stop)[/dim]")
            time.sleep(config.scan_interval_seconds)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Bot stopped by user. Gracefully shutting down...[/bold yellow]")


if __name__ == "__main__":
    main()
