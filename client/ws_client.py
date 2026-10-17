"""
SX Bet Centrifuge WebSocket Client.
Streams live orderbook and account updates in real-time.
"""

import asyncio
from typing import Callable, Optional
from loguru import logger

try:
    from centrifuge import Client, PublicationContext, SubscriptionEventHandler
    CENTRIFUGE_AVAILABLE = True
except ImportError:
    CENTRIFUGE_AVAILABLE = False


class SXBetRealtimeClient:
    def __init__(self, ws_url: str, token_provider: Optional[Callable] = None):
        self.ws_url = ws_url
        self.token_provider = token_provider
        self.client: Optional["Client"] = None
        self._subscriptions = {}

    async def connect(self):
        """Establish connection to the SX Bet Centrifuge WebSocket."""
        if not CENTRIFUGE_AVAILABLE:
            logger.warning("centrifuge-python is not installed. WebSocket streaming disabled.")
            return

        if self.token_provider:
            self.client = Client(self.ws_url, get_token=self.token_provider)
        else:
            self.client = Client(self.ws_url)

        logger.info(f"Connecting to SX Bet WebSocket at {self.ws_url}...")
        await self.client.connect()
        logger.info("Connected to SX Bet WebSocket.")

    async def subscribe_orderbook(self, market_hash: str, callback: Callable[[dict], None]):
        """Subscribe to real-time orderbook updates for a market."""
        if not self.client:
            return

        channel = f"orderbook_v3:{market_hash}"

        async def on_publication(ctx: "PublicationContext"):
            try:
                callback(ctx.data)
            except Exception as e:
                logger.error(f"Error handling orderbook update: {e}")

        sub = self.client.new_subscription(
            channel,
            SubscriptionEventHandler(on_publication=on_publication),
        )
        await sub.subscribe()
        self._subscriptions[channel] = sub
        logger.info(f"Subscribed to {channel}")

    async def disconnect(self):
        """Gracefully disconnect WebSocket."""
        if self.client:
            await self.client.disconnect()
            logger.info("Disconnected from SX Bet WebSocket.")
