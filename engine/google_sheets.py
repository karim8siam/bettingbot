"""
Google Sheets Streaming Logger via Apps Script Webhook.
Streams trade signals, entries, settlements, and PnL metrics directly to Google Sheets.
"""

from typing import Optional, Dict, Any
import requests
from loguru import logger


class GoogleSheetsLogger:
    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url.strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.webhook_url and self.webhook_url.startswith("https://script.google.com/macros/s/"))

    def send_payload(self, payload: Dict[str, Any]) -> bool:
        """Send JSON payload to Google Apps Script Web App (follows redirects)."""
        if not self.is_configured:
            return False

        try:
            # Google Apps Script Web Apps return a 302 redirect on POST
            resp = requests.post(
                self.webhook_url,
                json=payload,
                timeout=15,
                allow_redirects=True,
            )
            if resp.status_code in (200, 302):
                logger.info("Successfully synced trade data with Google Sheets.")
                return True
            else:
                logger.warning(f"Google Sheets webhook returned status {resp.status_code}")
                return False
        except Exception as e:
            logger.warning(f"Google Sheets sync failed: {e}")
            return False

    def log_trade_opened(
        self,
        order_id: str,
        event_name: str,
        outcome_name: str,
        decimal_odds: float,
        model_prob: float,
        edge_pct: float,
        stake_usdc: float,
        current_bankroll: float,
        sport: str = "Unknown",
    ) -> bool:
        """Stream trade opening to Google Sheets."""
        payload = {
            "action": "open",
            "order_id": order_id,
            "event_name": event_name,
            "sport": sport.upper(),
            "outcome_name": outcome_name,
            "decimal_odds": round(decimal_odds, 2),
            "model_prob": f"{model_prob:.1%}",
            "edge_pct": f"+{edge_pct:.2%}",
            "stake_usdc": round(stake_usdc, 2),
            "bankroll": round(current_bankroll, 2),
            "status": "OPEN",
        }
        return self.send_payload(payload)

    def log_trade_settled(
        self,
        order_id: str,
        won: Optional[bool],
        pnl_usdc: float,
        new_bankroll: float,
        closing_odds: Optional[float] = None,
    ) -> bool:
        """Update trade settlement in Google Sheets."""
        result_str = "VOID" if won is None else ("WON" if won else "LOST")
        payload = {
            "action": "settle",
            "order_id": order_id,
            "result": result_str,
            "pnl_usdc": round(pnl_usdc, 2),
            "bankroll": round(new_bankroll, 2),
            "closing_odds": round(closing_odds, 2) if closing_odds else "",
            "status": "SETTLED",
        }
        return self.send_payload(payload)
