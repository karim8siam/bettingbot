"""
SX Bet Connection Diagnostic Utility.
Verifies your API Key, Private Key, Proxy Wallet, and USDC Balance.
"""

import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import config
from client.rest_client import SXBetClient
from client.signer import SXOrderSigner

console = Console()


def check_connection():
    console.print(Panel("[bold cyan]SX Bet Connection & Account Diagnostic[/bold cyan]", border_style="cyan"))

    client = SXBetClient(base_url=config.rest_url, api_key=config.api_key)
    signer = SXOrderSigner(private_key=config.private_key)

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    # 1. Network & Public Metadata
    try:
        meta = client.get_metadata(force_refresh=True)
        domain_name = meta.get("domain", {}).get("name", "SX Bet")
        base_token = meta.get("activeAsset", {}).get("baseToken", "Unknown")
        table.add_row(
            "1. Network Metadata",
            "[bold green]OK[/bold green]",
            f"Network: {config.network_name} | Token: {base_token[:10]}...",
        )
    except Exception as e:
        table.add_row("1. Network Metadata", "[bold red]FAILED[/bold red]", str(e))

    # 2. Private Key Configuration
    if signer.is_configured():
        table.add_row(
            "2. Private Key (Maker)",
            "[bold green]CONFIGURED[/bold green]",
            f"Address: {signer.address}",
        )
    else:
        table.add_row(
            "2. Private Key (Maker)",
            "[bold yellow]NOT SET[/bold yellow]",
            "Using paper trading placeholder key in .env",
        )

    # 3. API Key & Proxy Wallet
    if config.api_key and config.api_key != "paper_trading_key":
        try:
            proxy_address = client.get_proxy_wallet()
            if proxy_address:
                table.add_row(
                    "3. Proxy Wallet",
                    "[bold green]DEPLOYED[/bold green]",
                    f"Proxy: {proxy_address}",
                )
            else:
                table.add_row(
                    "3. Proxy Wallet",
                    "[bold yellow]PENDING / NOT DEPLOYED[/bold yellow]",
                    "Login to sx.bet once to automatically deploy your proxy wallet",
                )
        except Exception as e:
            table.add_row("3. Proxy Wallet", "[bold red]ERROR[/bold red]", str(e))

        # 4. Spendable USDC Balance
        try:
            balance = client.get_balance()
            table.add_row(
                "4. Spendable Balance",
                "[bold green]ACTIVE[/bold green]" if balance > 0 else "[bold yellow]0.00 USDC[/bold yellow]",
                f"${balance:.2f} USDC",
            )
        except Exception as e:
            table.add_row("4. Spendable Balance", "[bold red]ERROR[/bold red]", str(e))
    else:
        table.add_row(
            "3. Proxy Wallet & Balance",
            "[bold yellow]SKIPPED[/bold yellow]",
            "Requires valid SX_API_KEY in .env",
        )

    console.print(table)


if __name__ == "__main__":
    check_connection()
