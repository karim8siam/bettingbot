import pytest
import preview_notifications as preview


def test_preview_does_not_send_and_explains_small_balance(monkeypatch, tmp_path):
    monkeypatch.setattr(preview.config, 'max_stake_pct', 0.015)
    monkeypatch.setattr(preview.config, 'max_daily_drawdown_pct', 0.05)
    def forbidden(*args, **kwargs):
        pytest.fail('Offline preview attempted Telegram delivery')
    monkeypatch.setattr(preview.TelegramNotifier, 'send_message', forbidden)
    messages, status = preview.build_preview()
    assert len(messages) == 2
    assert all('NO ORDER SUBMITTED' in m and 'SIMULATED' in m for m in messages)
    assert 'approved=False' in status
    output = tmp_path / 'preview.html'
    assert preview.main(['--output', str(output)]) == 0
    assert 'below the bot’s' in output.read_text()


def test_telegram_preview_requires_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(preview.config, 'telegram_bot_token', '')
    monkeypatch.setattr(preview.config, 'telegram_channel_id', '')
    with pytest.raises(SystemExit) as result:
        preview.main(['--telegram', '--output', str(tmp_path / 'preview.html')])
    assert result.value.code == 2


def test_telegram_preview_stops_on_uncertain_delivery(monkeypatch, tmp_path):
    monkeypatch.setattr(preview.config, 'telegram_bot_token', 'test-token')
    monkeypatch.setattr(preview.config, 'telegram_channel_id', 'test-chat')
    sent = []
    def uncertain(self, text):
        sent.append(text)
        self.last_delivery = {'state': 'UNKNOWN'}
        return False
    monkeypatch.setattr(preview.TelegramNotifier, 'send_message', uncertain)
    with pytest.raises(SystemExit) as result:
        preview.main(['--telegram', '--output', str(tmp_path / 'preview.html')])
    assert result.value.code == 1
    assert len(sent) == 1
