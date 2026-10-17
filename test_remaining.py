import json
import time
from unittest.mock import Mock,patch
import pytest
from engine.process_lock import ProcessLock
from engine.order_recovery import OrderRecovery
from engine.closing_lines import collect_closing_lines
from client.live_stats import LiveStatsFeed
from client.streaming_books import StreamingBooks
from client.rest_client import SXBetClient
from engine.audit_logger import AuditLogger
from check_connection import telegram_check
from research.evaluate import evaluate,load_rows
from strategy.validation import match_state,validated_total


def test_exclusive_lock_and_release(tmp_path):
    path=tmp_path/'scanner.lock'
    with ProcessLock(path):
        with pytest.raises(RuntimeError):
            with ProcessLock(path):pass
    with ProcessLock(path):pass


def test_timestamped_feed_stale_and_wrong_event(tmp_path):
    path=tmp_path/'scores.json'
    market={'gameTime':time.time()-60,'status':'ACTIVE','sportXeventId':'event'}
    stats=dict(minute=1,home_score=0,away_score=0,updated_at=time.time())
    feed=LiveStatsFeed(path)
    path.write_text(json.dumps({'event':stats}))
    assert feed.get(market)==stats
    assert feed.get(dict(market,sportXeventId='other')) is None
    path.write_text(json.dumps({'event':dict(stats,updated_at=time.time()-31)}))
    assert feed.get(market) is None
    path.write_text('{')
    assert feed.get(market) is None


@pytest.mark.parametrize('bad',[None,'bad',{},float('nan')])
def test_bad_start_fails_closed(bad):
    assert match_state({'gameTime':bad},None) is None


def test_clv_uses_only_fresh_pre_kickoff_quote(tmp_path):
    audit=AuditLogger(tmp_path/'audit.db')
    audit.log_trade('p',True,'hash','event','over',10,2,status='SIMULATED',is_outcome_one=True)
    client=Mock()
    client.find_market.return_value={'gameTime':100,'status':'ACTIVE'}
    client.get_orderbook.return_value={'outcomeOne':[{'percentageOdds':str(10**20//2),'size':'10000000'}]}
    collect_closing_lines(client,audit,now=90)
    client.get_orderbook.return_value={'outcomeOne':[{'percentageOdds':str(10**20//4),'size':'10000000'}]}
    collect_closing_lines(client,audit,now=110)
    assert audit.get_pending_trades()[0]['closing_odds']==2
    assert client.get_orderbook.call_count==1


def test_clv_does_not_claim_stale_close(tmp_path):
    audit=AuditLogger(tmp_path/'audit.db')
    audit.log_trade('p',True,'hash','event','over',10,2,is_outcome_one=True)
    audit.save_closing_candidate('p',2,10)
    audit.finalize_closing_candidate('p',100)
    assert audit.get_pending_trades()[0]['closing_odds'] is None


def test_balance_selects_active_asset_spendable():
    client=SXBetClient('https://example.test','key')
    client.get_metadata=Mock(return_value={'activeAsset':{'baseToken':'token','escrowAddress':'escrow'}})
    client.session=Mock()
    client.session.get.return_value=Mock(json=lambda:{'status':'success','data':{'balances':[
        {'tokenAddress':'other','escrowAddress':'escrow','availableAmount':'999000000'},
        {'tokenAddress':'TOKEN','escrowAddress':'ESCROW','availableAmount':'123000000','escrowedAmount':'90000000'}]}})
    assert client.get_balance()==123


def test_order_recovery_unknown_ack_and_partial_fill(tmp_path):
    journal=OrderRecovery(tmp_path/'orders.db')
    journal.register('order','client','market')
    client=Mock()
    client.get_order.return_value=None
    assert journal.reconcile(client,'order')=='UNKNOWN'
    client.submit_orders.assert_not_called()
    client.get_order.return_value={'id':'order','marketHash':'market','status':'INACTIVE','inactiveReason':'FILLED','totalBetSize':'1000000','remainingSize':'0'}
    fill={'id':'fill','orderId':'order','marketHash':'market','fillAmount':'500000','status':'LOCKED'}
    client.get_fills.return_value=[fill]
    assert journal.reconcile(client,'order')=='UNKNOWN'
    client.get_fills.return_value=[dict(fill,fillAmount='1000000')]
    assert journal.reconcile(client,'order')=='FILLED'
    assert journal.reconcile(client,'order')=='FILLED'
    assert len(journal.snapshot('order')['fills'])==1
    client.get_fills.return_value=[dict(fill,fillAmount='1000000',status='SETTLED',settlement={'settleReturnAmount':'2000000','settleFeeAmount':'10000'})]
    assert journal.reconcile(client,'order')=='SETTLED'
    restarted=OrderRecovery(tmp_path/'orders.db')
    assert restarted.snapshot('order')['fills'][0]['settlement']['settleFeeAmount']=='10000'


def test_no_liquidity_with_remaining_size(tmp_path):
    j=OrderRecovery(tmp_path/'orders.db');j.register('o','c','m')
    client=Mock()
    client.get_order.return_value={'id':'o','marketHash':'m','status':'INACTIVE','inactiveReason':'NO_LIQUIDITY','totalBetSize':'100','remainingSize':'100'}
    client.get_fills.return_value=[]
    assert j.reconcile(client,'o')=='UNFILLED'


def test_telegram_channel_permissions_and_no_send():
    with patch('check_connection.requests.get') as get:
        get.side_effect=[Mock(json=lambda:{'ok':True,'result':{'id':1}}),Mock(json=lambda:{'ok':True,'result':{'type':'channel'}}),Mock(json=lambda:{'ok':True,'result':{'status':'member'}})]
        with pytest.raises(ValueError,match='administrator'):
            telegram_check('secret','channel')
        assert all('sendMessage' not in call.args[0] for call in get.call_args_list)


def test_websocket_version_orientation_and_expiry():
    stream=StreamingBooks('http://example.test','wss://example.test','key')
    book={'version':'2','outcomeOne':[{'percentageOdds':str(4*10**19),'size':'4000000'}],'outcomeTwo':[]}
    stream.apply('m',book)
    stream.apply('m',dict(book,version='1',outcomeOne=[]))
    snap=stream.snapshot('m')
    assert snap['outcomeTwo']==[{'percentageOdds':str(6*10**19),'size':'6000000'}]
    assert stream.snapshot('m',max_age=-1) is None


def test_chronological_calibration_holdout_does_not_change_fit():
    rows=[dict(timestamp=i,p=.6,odds=2,won=i%2) for i in range(200)]
    report=evaluate(rows,.01)
    changed=[dict(r,won=1-r['won']) if i>=140 else r for i,r in enumerate(rows)]
    assert evaluate(changed,.01)['calibration']==report['calibration']
    assert report['training_events']==140 and report['holdout_events']==60
    with pytest.raises(ValueError):evaluate(rows[:100])


def test_duplicate_historical_event_rejected(tmp_path):
    path=tmp_path/'history.csv'
    path.write_text('event_id,timestamp,model_prob,decimal_odds,won\nx,2026-01-01T00:00:00Z,.5,2,1\nx,2026-01-02T00:00:00Z,.5,2,0\n')
    with pytest.raises(ValueError,match='independent'):load_rows(path)


def test_signal_expiry_during_price_refresh(tmp_path):
    from test_regressions import engine
    e,audit,risk=engine(tmp_path)
    expiry=time.time()+5
    with patch('engine.execution.time.time',side_effect=[expiry-1,expiry+1]):
        result=e.execute_bet('hash','A','Over 2.5',True,'50000000000000000000',.01,expires_at=expiry)
    assert result is None
    assert audit.get_pending_trades()==[]
    assert risk.current_bankroll==1000


def test_runner_scan_and_restart_do_not_duplicate(tmp_path, monkeypatch):
    import bot
    monkeypatch.setattr(bot.config,'api_key','test-key')
    monkeypatch.setattr(bot.config,'data_dir',tmp_path)
    monkeypatch.setattr(bot.config,'initial_bankroll',1000)
    monkeypatch.setattr(bot.config,'use_websocket',False)
    monkeypatch.setattr(bot.config,'telegram_bot_token','')
    monkeypatch.setattr(bot.config,'telegram_channel_id','')
    monkeypatch.setattr('sys.argv',['bot.py','--dry-run','--single-scan'])
    market=dict(marketHash='h',type=2,status='ACTIVE',sportLabel='Soccer',teamOneName='A',teamTwoName='B',line=2.5,gameTime=time.time()+3600,outcomeOneName='Over 2.5',outcomeTwoName='Under 2.5')
    client=Mock()
    client.get_active_markets.return_value=[market]
    client.find_market.return_value=market
    client.get_orderbook.return_value={'outcomeTwo':[{'percentageOdds':str(4*10**19),'size':'100000000'}]}
    monkeypatch.setattr(bot,'SXBetClient',Mock(return_value=client))
    bot.main()
    bot.main()
    audit=AuditLogger(tmp_path/f'audit_{bot.config.network_name}_paper.db')
    assert len(audit.get_pending_trades())==1
    client.submit_orders.assert_not_called()


def test_single_scan_failure_exits_nonzero(tmp_path,monkeypatch):
    import bot
    monkeypatch.setattr(bot.config,'api_key','test-key')
    monkeypatch.setattr(bot.config,'data_dir',tmp_path)
    monkeypatch.setattr(bot.config,'use_websocket',False)
    monkeypatch.setattr('sys.argv',['bot.py','--dry-run','--single-scan'])
    client=Mock()
    client.get_active_markets.side_effect=ValueError('bad API response')
    monkeypatch.setattr(bot,'SXBetClient',Mock(return_value=client))
    with pytest.raises(SystemExit) as exc:bot.main()
    assert exc.value.code==1
