"""
Telegram Channel Notifier for SX Bet Betting Bot.
Sends rich formatted alerts when trades are opened and when results are settled.
"""

from typing import Optional
from html import escape
import requests
from loguru import logger


class TelegramNotifier:
    def __init__(self, bot_token: str = "", channel_id: str = "", hide_demo_tag: bool = False):
        self.bot_token = bot_token.strip()
        self.channel_id = channel_id.strip()
        self.hide_demo_tag = hide_demo_tag
        self.last_delivery = {"state": "UNKNOWN"}

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.channel_id and not self.bot_token.startswith("your_"))

    def send_message(self, text: str) -> bool:
        """Send HTML formatted message to Telegram channel."""
        self.last_delivery = {"state": "UNKNOWN"}
        if not self.is_configured:
            logger.debug(f"[Telegram Notifier Disabled] Would have sent:\n{text}")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.channel_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if resp.status_code == 429 or data.get('error_code') == 429:
                delay = data.get('parameters', {}).get('retry_after', 30)
                self.last_delivery = {'state': 'RETRY', 'retry_after': min(86400, max(1, int(delay)))}
                return False
            if resp.status_code == 200 and data.get("ok") is True:
                self.last_delivery = {'state': 'SENT'}
                logger.info("Telegram notification delivered successfully.")
                return True
            else:
                self.last_delivery = {"state": "FAILED" if 400 <= resp.status_code < 500 else "UNKNOWN"}
                logger.error(f"Telegram rejected notification (HTTP {resp.status_code}).")
                return False
        except Exception as e:
            logger.error(f"Telegram request failed ({type(e).__name__}).")
            return False

    def notify_trade_opened(
        self,
        event_name: str,
        outcome_name: str,
        stake_usdc: float,
        decimal_odds: float,
        model_prob: float,
        edge_pct: float,
        current_bankroll: float,
        minute: Optional[int] = None,
        score: Optional[str] = None,
        is_demo: bool = True,
    ):
        """Notification #1: Sent immediately when a trade is placed."""
        event_name, outcome_name = escape(event_name), escape(outcome_name)
        score = escape(str(score)) if score is not None else None
        mode_prefix = "" if self.hide_demo_tag else f"{'PAPER / SIMULATED' if is_demo else 'LIVE'}: "
        time_info = f" | ⏱ {minute}'" if minute is not None else ""
        score_info = f" | ⚽ Score: {score}" if score else ""

        message = (
            f"🎯 <b>{mode_prefix}NEW SIGNAL TAKEN</b>\n\n"
            f"🏆 <b>Match:</b> {event_name}{time_info}{score_info}\n"
            f"📌 <b>Selection:</b> <code>{outcome_name}</code>\n"
            f"📊 <b>Odds:</b> <code>{decimal_odds:.2f}</code>\n"
            f"🧠 <b>Model Probability:</b> <code>{model_prob:.1%}</code>\n"
            f"📈 <b>Edge (+EV):</b> <b>+{edge_pct:.2%}</b>\n\n"
            f"💵 <b>Stake:</b> ${stake_usdc:.2f} USDC\n"
            f"🏦 <b>Bankroll:</b> ${current_bankroll:.2f} USDC\n"
            f"🕒 <i>Awaiting settlement</i>"
        )
        return self.send_message(message)

    def notify_trade_settled(
        self,
        event_name: str,
        outcome_name: str,
        stake_usdc: float,
        decimal_odds: float,
        won: Optional[bool],
        pnl_usdc: float,
        new_bankroll: float,
        closing_odds: Optional[float] = None,
        is_demo: bool = True,
    ):
        """Notification #2: Sent when the match finishes and the trade is settled."""
        event_name, outcome_name = escape(event_name), escape(outcome_name)
        mode_prefix = "" if self.hide_demo_tag else f"{'PAPER / SIMULATED' if is_demo else 'LIVE'}: "
        status_icon = "↩️ <b>VOID / REFUNDED</b>" if won is None else ("✅ <b>WON</b>" if won else "❌ <b>LOST</b>")
        pnl_str = f"+${pnl_usdc:.2f}" if pnl_usdc >= 0 else f"-${abs(pnl_usdc):.2f}"
        
        clv_info = ""
        if closing_odds and closing_odds > 0:
            clv_pct = ((decimal_odds / closing_odds) - 1.0) * 100
            clv_info = f"\n🎯 <b>Closing Line Value (CLV):</b> {clv_pct:+.1f}%"

        message = (
            f"🏁 <b>{mode_prefix}TRADE RESULT</b>\n\n"
            f"🏆 <b>Match:</b> {event_name}\n"
            f"📌 <b>Selection:</b> <code>{outcome_name}</code> @ {decimal_odds:.2f}\n"
            f"Outcome: {status_icon}\n"
            f"💵 <b>Net PnL:</b> <b>{pnl_str} USDC</b>\n"
            f"🏦 <b>Updated Bankroll:</b> <b>${new_bankroll:.2f} USDC</b>{clv_info}"
        )
        return self.send_message(message)
