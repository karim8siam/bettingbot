"""Read-only diagnostics. Never sends a Telegram message or submits an SX order."""
import sys
import requests
from rich.console import Console
from rich.table import Table
from config import config
from client.rest_client import SXBetClient


def telegram_check(token, chat_id):
    if not token or not chat_id:
        raise ValueError('Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID')

    def get(method, **params):
        try:
            response = requests.get(f'https://api.telegram.org/bot{token}/{method}', params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()
            if payload.get('ok') is not True:
                raise ValueError('Telegram rejected request')
            return payload['result']
        except requests.RequestException:
            # Requests exceptions may contain the token-bearing URL.
            raise ValueError('Telegram authentication/network request failed') from None

    me = get('getMe')
    chat = get('getChat', chat_id=chat_id)
    member = get('getChatMember', chat_id=chat_id, user_id=me['id'])
    status = member.get('status')
    if status in ('left', 'kicked'):
        raise ValueError('Bot is not a member of the destination')
    if chat.get('type') == 'channel' and not (status == 'creator' or (status == 'administrator' and member.get('can_post_messages'))):
        raise ValueError('Bot needs channel administrator permission to post messages')
    if status == 'restricted' and not member.get('can_send_messages', False):
        raise ValueError('Bot is restricted from sending messages')
    return 'Bot identity and destination membership verified (no message sent)'


def check_connection():
    table = Table('Check', 'Status', 'Details')
    client = SXBetClient(config.rest_url, config.api_key)
    failures = 0

    def check(name, action):
        nonlocal failures
        try:
            result = action()
            table.add_row(name, 'OK', str(result))
        except Exception as exc:
            failures += 1
            # Do not print request bodies, credentials, or exception URLs.
            detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            table.add_row(name, 'FAILED', detail)

    check('SX metadata', lambda: client.get_metadata()['domain']['name'])
    if config.api_key and not config.api_key.startswith('your_'):
        check('SX spendable balance', lambda: f'{client.get_balance():.6f} USDC')
        check('SX realtime authentication', lambda: 'Token received' if client.get_realtime_token() else (_ for _ in ()).throw(ValueError('Empty realtime token')))
    else:
        failures += 1
        table.add_row('SX authenticated access', 'NOT CONFIGURED', 'Set SX_API_KEY for orderbook access')
    if config.telegram_bot_token or config.telegram_channel_id:
        check('Telegram', lambda: telegram_check(config.telegram_bot_token, config.telegram_channel_id))
    else:
        table.add_row('Telegram', 'DISABLED', 'Optional token and channel ID not configured')
    Console().print(table)
    client.session.close()
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(check_connection())
