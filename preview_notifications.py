"""Preview invented notification examples without placing or recording any bets."""
import argparse
from html import escape
from pathlib import Path

from config import config
from engine.risk_manager import RiskManager
from engine.telegram_notifier import TelegramNotifier


def build_preview():
    messages = []
    notifier = TelegramNotifier()
    def capture(text):
        messages.append(
            '<b>ILLUSTRATIVE EXAMPLE — NO ORDER SUBMITTED</b>\n'
            'Invented match and result. This is a notification layout test, not a forecast.\n\n' + text
        )
        return True
    notifier.send_message = capture
    # Fixed example values: never infer a market signal or an actual result.
    notifier.notify_trade_opened('Example Team A vs Example Team B', 'Over 2.5',
                                 0.15, 2.0, 0.55, 0.10, 9.85, is_demo=True)
    notifier.notify_trade_settled('Example Team A vs Example Team B', 'Over 2.5',
                                  0.15, 2.0, True, 0.15, 10.15, is_demo=True)
    risk = RiskManager(10.0, max_stake_pct=config.max_stake_pct,
                       max_daily_drawdown_pct=config.max_daily_drawdown_pct,
                       max_concurrent_trades=config.max_concurrent_trades)
    approved, stake, reason = risk.validate_and_size_stake(config.max_stake_pct, 'preview-only')
    status = f'10.00 USDC risk check: approved={approved}; stake={stake:.2f}; {reason}'
    return messages, status


def write_preview(path, messages, status):
    cards = ''.join('<article>' + m.replace('\n', '<br>') + '</article>' for m in messages)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<!doctype html><html lang="en"><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>Bot notification preview</title><style>'
                    'body{font:17px/1.6 system-ui;background:#101925;color:#edf3fa;max-width:850px;margin:40px auto;padding:20px}'
                    'article{background:#20334b;padding:24px;border-radius:16px;margin:24px 0}'
                    'aside{background:#493e20;padding:20px;border-radius:12px}code{color:#a4e8e0}'
                    '</style><h1>Telegram notification preview</h1>'
                    '<p>These examples show a fictional 10.00 USDC balance. No funds, orders, '
                    'market data or Telegram delivery are involved in this HTML preview.</p>'
                    '<aside>' + escape(status) + '<br>The example 0.15 stake is below the bot’s '
                    '1.00 minimum and cannot be executed under its default rules. '
                    'USDT deposits or conversions are not implemented.</aside>' + cards + '</html>', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='data/notification-preview.html')
    parser.add_argument('--telegram', action='store_true', help='Send two explicitly labeled fictional examples to configured Telegram')
    args = parser.parse_args(argv)
    messages, status = build_preview()
    write_preview(args.output, messages, status)
    print(status)
    print(f'Local preview: {Path(args.output).resolve()}')
    if args.telegram:
        notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_channel_id)
        if not notifier.is_configured:
            parser.exit(2, 'Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID in .env. No messages sent.\n')
        for message in messages:
            if not notifier.send_message(message):
                parser.exit(1, f'Delivery state: {notifier.last_delivery["state"]}. Stopped; do not blindly retry an uncertain delivery.\n')
        print('Telegram confirmed both example messages. No bet was placed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
