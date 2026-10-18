import asyncio
import time
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch

import pytest
from bot import check_and_settle_pending_trades
from config import BotConfig
from client.rest_client import SXBetClient
from client.ws_client import SXBetRealtimeClient
from engine.audit_logger import AuditLogger
from engine.execution import ExecutionEngine
from engine.risk_manager import RiskManager
from engine.telegram_notifier import TelegramNotifier
from models.edge_calculator import EdgeCalculator
from strategy.multi_sport_ev import MultiSportEVStrategy
from strategy.live_football_ev import LiveFootballEVStrategy


def ledger(tmp_path):
    return AuditLogger(tmp_path / 'audit.db')


def engine(tmp_path):
    db = ledger(tmp_path)
    risk = RiskManager(1000)
    client = Mock()
    client.get_orderbook.return_value = {'outcomeOne': [{'percentageOdds': '50000000000000000000', 'size': '100000000'}]}
    return ExecutionEngine(client, Mock(), risk, db), db, risk


def place(e):
    return e.execute_bet('hash', 'A & B', 'Over 2.5', True, '50000000000000000000', .01)


@pytest.mark.parametrize('outcome,expected', [(1,1010), (2,990), (0,1000), ('1',1010)])
def test_settlement_cash_restart_and_idempotency(tmp_path, outcome, expected):
    e, db, risk = engine(tmp_path)
    place(e)
    assert risk.current_bankroll == 990
    assert risk.active_open_trades == 1
    restored = RiskManager(1000)
    db.restore_risk(restored, 1000)
    assert restored.current_bankroll == 990
    e.client.find_market.return_value = dict(status='INACTIVE', reportedDate=123, outcome=outcome)
    notifier = Mock(is_configured=False)
    for _ in range(2):
        check_and_settle_pending_trades(e.client, db, restored, notifier, True)
    assert restored.current_bankroll == expected
    assert restored.active_open_trades == 0
    again = RiskManager(1000)
    db.restore_risk(again, 1000)
    assert again.current_bankroll == expected
    assert again.daily_pnl == expected - 1000


def test_unknown_settlement_stays_pending(tmp_path):
    e, db, risk = engine(tmp_path)
    place(e)
    e.client.find_market.return_value = dict(status='SETTLED', outcome=None)
    check_and_settle_pending_trades(e.client, db, risk, Mock(is_configured=False), True)
    assert len(db.get_pending_trades()) == 1
    assert risk.current_bankroll == 990


def test_low_bankroll_does_not_round_up():
    r = RiskManager(10)
    assert not r.validate_and_size_stake(.01, 'hash')[0]
    assert r.active_open_trades == 0


def test_validation_does_not_reserve_and_pending_budget_is_enforced():
    r = RiskManager(100, max_stake_pct=.05, max_concurrent_trades=10)
    assert r.validate_and_size_stake(.05,'hash')[1] == 5
    assert r.active_open_trades == 0
    r.record_trade_opened(5)
    assert not r.validate_and_size_stake(.05,'hash')[0]


@pytest.mark.parametrize('fraction', [float('nan'), float('inf'), -1, 0])
def test_invalid_sizing(fraction):
    assert not RiskManager(1000).validate_and_size_stake(fraction,'hash')[0]


def test_no_fill_on_insufficient_or_stale_book(tmp_path):
    e, db, risk = engine(tmp_path)
    e.client.get_orderbook.return_value = {'outcomeOne': [{'percentageOdds':'60000000000000000000', 'size':'100000000'}]}
    assert place(e) is None
    assert risk.active_open_trades == 0
    assert db.get_pending_trades() == []


def test_live_guard_precedes_network_and_risk(tmp_path):
    e, db, risk = engine(tmp_path)
    e.dry_run=False
    with pytest.raises(RuntimeError, match='reconciliation'):
        place(e)
    e.client.get_orderbook.assert_not_called()
    assert risk.active_open_trades == 0


def test_duplicate_log_cannot_erase_result(tmp_path):
    db=ledger(tmp_path)
    args=dict(order_id='id',is_paper=True,market_hash='hash',event_name='A',outcome_name='B',stake_usdc=10,decimal_odds=2)
    db.log_trade(**args)
    assert db.settle_trade('id',True,10)
    assert not db.settle_trade('id',False,-10)
    with pytest.raises(Exception):
        db.log_trade(**args)
    assert db.get_trade_summary()['total_pnl']==10


@pytest.mark.parametrize('cls',[MultiSportEVStrategy, LiveFootballEVStrategy])
def test_strategy_missing_live_data_and_invalid_market(cls):
    strategy=cls(EdgeCalculator())
    m=dict(marketHash='h',type=2,status='ACTIVE',sportLabel='Soccer',line=2.5,gameTime=time.time()-3600,outcomeOneName='Over 2.5',outcomeTwoName='Under 2.5')
    book={'outcomeTwo':[{'percentageOdds':'50000000000000000000'}]}
    assert strategy.evaluate_market(m,book)==[]
    stats=dict(minute=80,home_score=0,away_score=0,updated_at=time.time())
    assert strategy.evaluate_market(m,book,stats)
    assert strategy.evaluate_market(m,book,dict(stats,updated_at=time.time()-60))==[]
    assert strategy.evaluate_market(dict(m,type=3),book,stats)==[]
    assert strategy.evaluate_market(dict(m,line=2),book,stats)==[]
    flipped=dict(m,outcomeOneName='Under 2.5',outcomeTwoName='Over 2.5')
    signal=strategy.evaluate_market(flipped,{'outcomeOne':book['outcomeTwo']},stats)[0]
    assert signal.is_outcome_one and signal.model_prob > .5


def test_telegram_labels_escape_and_api_failure():
    t=TelegramNotifier('token','channel')
    with patch('engine.telegram_notifier.requests.post') as post:
        post.return_value=Mock(status_code=200,json=lambda:{'ok':True})
        t.notify_trade_opened('A & <B>','Over <2.5>',1,2,.6,.2,100)
        message=post.call_args.kwargs['json']['text']
        assert 'SIMULATED' in message and 'A &amp; &lt;B&gt;' in message
        t.notify_trade_settled('A','B',1,2,None,0,100)
        assert 'VOID / REFUNDED' in post.call_args.kwargs['json']['text']
        post.return_value.json=lambda:{'ok':False}
        assert t.send_message('hello') is False


def test_sx_pagination_find_and_book_contract():
    c=SXBetClient('https://example.test')
    c.session=Mock()
    def response(data):
        return Mock(json=lambda:dict(status='success',data=data))
    c.session.get.side_effect=[response(dict(markets=[{'id':1}],nextKey='next')),response(dict(markets=[{'id':2}])),response([dict(marketHash='hash')]),response({'outcomeOne':[]})]
    assert len(c.get_active_markets())==2
    assert c.find_market('hash')=={'marketHash':'hash'}
    assert c.session.get.call_args.kwargs['params']=={'marketHashes':'hash'}
    c.get_orderbook('hash')
    assert c.session.get.call_args.args[0].endswith('/snapshot/market')


@pytest.mark.parametrize('kwargs',[dict(network_name='bad'),dict(max_stake_pct=2),dict(scan_interval_seconds=0),dict(initial_bankroll=float('nan')),dict(min_odds=5,max_odds=2)])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError): BotConfig(**kwargs)


def test_websocket_handler():
    c=SXBetRealtimeClient('wss://example.test')
    c.client=Mock()
    c.client.new_subscription.return_value=SimpleNamespace(subscribe=AsyncMock())
    callback=Mock()
    asyncio.run(c.subscribe_orderbook('hash',callback))
    handler=c.client.new_subscription.call_args.args[1]
    asyncio.run(handler.on_publication(SimpleNamespace(pub=SimpleNamespace(data={'version':'1'}))))
    callback.assert_called_once_with({'version':'1'})
