"""
Google Sheets Streaming Logger via Apps Script Webhook.
Streams trade signals, entries, settlements, and PnL metrics directly to Google Sheets
for institutional-grade post-trade analysis and model calibration.
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

    def setup_sheets(self) -> bool:
        """Remotely initialize or refresh the Analytics Dashboard and Trades sheets."""
        return self.send_payload({"action": "setup"})

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
        sport: str = "SOCCER",
        market_type: str = "TOTALS",
        market_prob: Optional[float] = None,
        strategy_tag: str = "MultiSportEV",
        notes: str = "",
    ) -> bool:
        """Stream new trade entry with rich quantitative diagnostics to Google Sheets."""
        m_prob_str = f"{market_prob:.1%}" if market_prob is not None else ""
        payload = {
            "action": "open",
            "order_id": order_id,
            "sport": sport.upper(),
            "event_name": event_name,
            "market_type": market_type.upper(),
            "outcome_name": outcome_name,
            "decimal_odds": round(decimal_odds, 2),
            "model_prob": f"{model_prob:.1%}",
            "market_prob": m_prob_str,
            "edge_pct": f"+{edge_pct:.2%}",
            "strategy_tag": strategy_tag,
            "stake_usdc": round(stake_usdc, 2),
            "bankroll": round(current_bankroll, 2),
            "notes": notes,
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
        }
        return self.send_payload(payload)
