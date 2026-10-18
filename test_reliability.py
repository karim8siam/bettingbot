import json
import sqlite3
from unittest.mock import Mock, patch
import pytest
import requests
from engine.audit_logger import AuditLogger
from engine.notifications import dispatch_notifications
from engine.risk_manager import RiskManager
from engine.telegram_notifier import TelegramNotifier
from engine.order_recovery import OrderRecovery


def opened():
    return {'destination':'channel','payload':dict(event_name='A',outcome_name='Over 2.5',stake_usdc=10,decimal_odds=2,model_prob=.6,edge_pct=.2,current_bankroll=990,is_demo=True)}


def add_trade(db, order_id='one', notification=None):
    db.log_trade(order_id,True,'hash','event','over',10,2,is_outcome_one=True,notification=notification)


def state(db):
    with db._get_connection() as conn:
        return conn.execute('SELECT state,attempts,next_attempt FROM notifications').fetchone()


def test_daily_stop_remains_latched_after_recovery_and_restart(tmp_path):
    db=AuditLogger(tmp_path/'audit.db')
    for name,pnl in [('loss',-60),('win',30)]:
        add_trade(db,name)
        db.settle_trade(name,pnl>0,pnl)
    risk=RiskManager(1000)
    db.restore_risk(risk,1000)
    assert risk.daily_pnl==-30
    assert risk.is_circuit_breaker_active
    assert not risk.validate_and_size_stake(.01,'hash')[0]


def test_bankroll_change_cannot_reset_ledger(tmp_path):
    db=AuditLogger(tmp_path/'audit.db')
    db.restore_risk(RiskManager(1000),1000)
    with pytest.raises(ValueError,match='ledger started'):
        db.restore_risk(RiskManager(2000),2000)


def test_alert_trade_atomicity_and_restart(tmp_path):
    path=tmp_path/'audit.db'
    db=AuditLogger(path)
    add_trade(db,notification=opened())
    with pytest.raises(sqlite3.IntegrityError):add_trade(db,notification=opened())
    assert state(db)==('PENDING',0,0)
    notifier=TelegramNotifier('test','channel')
    with patch('engine.telegram_notifier.requests.post',return_value=Mock(status_code=200,json=lambda:{'ok':True})) as post:
        dispatch_notifications(AuditLogger(path),notifier)
        dispatch_notifications(db,notifier)
        assert post.call_count==1
    assert state(db)[0]=='SENT'


def test_explicit_rate_limit_waits_without_blocking_scanner(tmp_path):
    db=AuditLogger(tmp_path/'audit.db');add_trade(db,notification=opened())
    notifier=TelegramNotifier('test','channel')
    with patch('engine.telegram_notifier.requests.post') as post:
        post.return_value=Mock(status_code=429,json=lambda:{'ok':False,'parameters':{'retry_after':60}})
        dispatch_notifications(db,notifier,now=100)
        assert state(db)==('RETRY',1,160)
        dispatch_notifications(db,notifier,now=120)
        assert post.call_count==1
        post.return_value=Mock(status_code=200,json=lambda:{'ok':True})
        dispatch_notifications(db,notifier,now=160)
        assert state(db)[0]=='SENT'


def test_unknown_delivery_never_blindly_retried(tmp_path):
    db=AuditLogger(tmp_path/'audit.db');add_trade(db,notification=opened())
    notifier=TelegramNotifier('test','channel')
    with patch('engine.telegram_notifier.requests.post',side_effect=requests.Timeout('token-bearing-url')) as post:
        dispatch_notifications(db,notifier)
        dispatch_notifications(db,notifier)
        assert post.call_count==1
    assert state(db)[0]=='UNKNOWN'


def test_crash_during_send_stays_unknown_on_restart(tmp_path):
    path=tmp_path/'audit.db';db=AuditLogger(path);add_trade(db,notification=opened())
    with db._get_connection() as conn:conn.execute("UPDATE notifications SET state='SENDING'")
    assert state(AuditLogger(path))[0]=='UNKNOWN'


def test_destination_change_never_reroutes_old_alerts(tmp_path):
    db=AuditLogger(tmp_path/'audit.db');add_trade(db,notification=opened())
    notifier=TelegramNotifier('test','different-channel')
    with patch('engine.telegram_notifier.requests.post') as post:
        dispatch_notifications(db,notifier)
        post.assert_not_called()
    assert state(db)[0]=='FAILED'


def test_order_404_updates_durable_status(tmp_path):
    journal=OrderRecovery(tmp_path/'orders.db');journal.register('o','c','m')
    with journal.connect() as conn:conn.execute("UPDATE intents SET state='FILLED'")
    client=Mock();client.get_order.return_value=None
    assert journal.reconcile(client,'o')=='UNKNOWN'
    assert journal.snapshot('o')['state']=='UNKNOWN'


def test_failed_fill_request_invalidates_old_state(tmp_path):
    journal=OrderRecovery(tmp_path/'orders.db');journal.register('o','c','m')
    client=Mock();client.get_order.return_value={'id':'o','marketHash':'m'}
    client.get_fills.side_effect=TimeoutError()
    with pytest.raises(TimeoutError):journal.reconcile(client,'o')
    assert journal.snapshot('o')['state']=='UNKNOWN'


@pytest.mark.parametrize('value',['nan','1.5',True,-1,None])
def test_bad_orderbook_units_are_rejected(value):
    from utils.orderbook import levels
    with pytest.raises(ValueError):levels([{'percentageOdds':str(5*10**19),'size':value}])


def test_duplicate_levels_cannot_double_count_liquidity():
    from utils.orderbook import levels
    level={'percentageOdds':str(5*10**19),'size':'1000000'}
    with pytest.raises(ValueError):levels([level,level])


def test_poisson_uses_configured_total_at_kickoff():
    import math
    from models.inplay_poisson import InPlayPoissonModel
    model=InPlayPoissonModel(default_match_xg=1)
    assert model.calculate_remaining_time_fraction(0)==1
    assert sum(model.estimate_remaining_lambdas(0,0,0))==pytest.approx(1)
    probs=model.get_over_under_probabilities(0,0,0,line=.5)
    assert probs['under']==pytest.approx(math.exp(-1))


def test_model_does_not_use_nba_clock_for_wnba_or_ncaa():
    from strategy.multi_sport_ev import MultiSportEVStrategy
    from models.edge_calculator import EdgeCalculator
    strategy=MultiSportEVStrategy(EdgeCalculator())
    assert strategy._detect_sport({'sportLabel':'Basketball','leagueLabel':'WNBA'})=='unsupported'
    assert strategy._detect_sport({'sportLabel':'Basketball','leagueLabel':'NBA'})=='basketball'
    assert strategy._detect_sport({'sportLabel':'Soccer','leagueLabel':'NCAA Soccer'})=='soccer'


def test_invalid_stream_update_does_not_replace_valid_book():
    from client.streaming_books import StreamingBooks
    stream=StreamingBooks('https://example.test','wss://example.test','key')
    book={'version':'2','outcomeOne':[{'percentageOdds':str(5*10**19),'size':'1000000'}],'outcomeTwo':[]}
    stream.apply('m',book)
    stream.apply('m',dict(book,version='3',outcomeOne=[{'percentageOdds':'bad'}]))
    assert stream.snapshot('m')['version']=='2'


def test_export_uses_recorded_probabilities_and_unique_events(tmp_path):
    from research.export import export_forecasts
    from research.evaluate import load_rows
    db=AuditLogger(tmp_path/'audit.db')
    for identifier in ['one','two']:
        db.log_trade(identifier,True,'hash','event','over',10,2,is_outcome_one=True,model_prob=.6,event_id='L123')
        db.settle_trade(identifier,True,10)
    destination=tmp_path/'forecasts.csv'
    assert export_forecasts(db.db_path,destination)==1
    rows=load_rows(destination)
    assert rows[0]['p']==.6 and rows[0]['won']==1


def test_alert_status_is_visible(tmp_path):
    db=AuditLogger(tmp_path/'audit.db');add_trade(db,notification=opened())
    assert db.get_notification_summary()=={'waiting':1,'attention':0,'sent':0}
