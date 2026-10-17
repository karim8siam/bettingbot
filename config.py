"""
Global Configuration for SX Bet Betting Bot.
Loads environment variables and validates risk parameters.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env file from project root
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class NetworkConfig(BaseModel):
    name: str
    rest_url: str
    ws_url: str


NETWORKS = {
    "mainnet": NetworkConfig(
        name="mainnet",
        rest_url="https://api.sx.bet",
        ws_url="wss://realtime.sx.bet/connection/websocket",
    ),
    "testnet": NetworkConfig(
        name="testnet",
        rest_url="https://api.toronto.sx.bet",
        ws_url="wss://realtime.toronto.sx.bet/connection/websocket",
    ),
}


class BotConfig(BaseModel):
    # Network
    network_name: str = Field(default_factory=lambda: os.getenv("SX_NETWORK", "mainnet").lower())
    
    # Credentials
    private_key: str = Field(default_factory=lambda: os.getenv("SX_PRIVATE_KEY", ""))
    api_key: str = Field(default_factory=lambda: os.getenv("SX_API_KEY", ""))
    
    # Modes
    dry_run: bool = Field(default_factory=lambda: os.getenv("DRY_RUN", "True").lower() in ("true", "1", "yes"))
    
    # Capital & Risk Controls
    initial_bankroll: float = Field(default_factory=lambda: float(os.getenv("INITIAL_BANKROLL", "10.00")))
    kelly_fraction: float = Field(default_factory=lambda: float(os.getenv("KELLY_FRACTION", "0.25")))
    max_stake_pct: float = Field(default_factory=lambda: float(os.getenv("MAX_STAKE_PCT", "0.10")))
    max_daily_drawdown_pct: float = Field(default_factory=lambda: float(os.getenv("MAX_DAILY_DRAWDOWN_PCT", "0.20")))
    max_concurrent_trades: int = Field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_TRADES", "10")))
    
    # Telegram Channel Alerts
    telegram_bot_token: str = Field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_channel_id: str = Field(default_factory=lambda: os.getenv("TELEGRAM_CHANNEL_ID", ""))
    
    # Quantitative Filters
    min_edge_pct: float = Field(default_factory=lambda: float(os.getenv("MIN_EDGE_PCT", "0.04")))
    min_odds: float = Field(default_factory=lambda: float(os.getenv("MIN_ODDS", "1.20")))
    max_odds: float = Field(default_factory=lambda: float(os.getenv("MAX_ODDS", "4.50")))
    target_sports: list[str] = Field(default_factory=lambda: [s.strip().lower() for s in os.getenv("TARGET_SPORTS", "soccer,football").split(",")])
    scan_interval_seconds: int = Field(default_factory=lambda: int(os.getenv("SCAN_INTERVAL_SECONDS", "15")))
    
    # Paths
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"

    @property
    def network(self) -> NetworkConfig:
        return NETWORKS.get(self.network_name, NETWORKS["mainnet"])

    @property
    def rest_url(self) -> str:
        return self.network.rest_url

    @property
    def ws_url(self) -> str:
        return self.network.ws_url


config = BotConfig()
