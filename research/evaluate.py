"""Chronological evaluation and calibration of externally supplied forecasts.

CSV: event_id,timestamp,model_prob,decimal_odds,won
Timestamps are ISO-8601 with a timezone; one independent event per row. Predictions
must have been recorded before results. This tool cannot establish their provenance.
"""
import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path


def load_rows(path):
    with open(path, newline='') as handle:
        rows = list(csv.DictReader(handle))
    events = set()
    for row in rows:
        if not row['event_id'] or row['event_id'] in events:
            raise ValueError('Require one forecast per independent event')
        events.add(row['event_id'])
        stamp = datetime.fromisoformat(row['timestamp'].replace('Z','+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Timestamp must include timezone')
        row['timestamp'] = stamp.timestamp()
        row['p'] = float(row['model_prob'])
        row['odds'] = float(row['decimal_odds'])
        row['won'] = int(row['won'])
        if not 0 < row['p'] < 1 or not math.isfinite(row['odds']) or row['odds'] <= 1 or row['won'] not in (0,1):
            raise ValueError('Invalid forecast, decimal odds, or binary result')
    rows.sort(key=lambda row: row['timestamp'])
    return rows


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-30,min(30,x))))


def fit(rows):
    a, b = 1.0, 0.0
    for _ in range(1500):
        da, db = 0.0, 0.0
        for row in rows:
            x = math.log(row['p'] / (1-row['p']))
            err = sigmoid(a*x+b)-row['won']
            da += err*x
            db += err
        a -= .05*(da/len(rows)+.01*(a-1))
        b -= .05*(db/len(rows)+.01*b)
    return {'slope':a,'intercept':b}


def metrics(rows, model=None, cost_per_unit=0):
    brier=logloss=pnl=peak=drawdown=0.0
    bets=0
    for row in rows:
        p=row['p'] if model is None else sigmoid(model['slope']*math.log(row['p']/(1-row['p']))+model['intercept'])
        y=row['won']
        brier += (p-y)**2
        logloss -= y*math.log(max(p,1e-12))+(1-y)*math.log(max(1-p,1e-12))
        if p*row['odds']-1-cost_per_unit >= .04:
            bets+=1
            pnl += (row['odds']-1 if y else -1)-cost_per_unit
            peak=max(peak,pnl)
            drawdown=max(drawdown,peak-pnl)
    return dict(rows=len(rows),brier=brier/len(rows),log_loss=logloss/len(rows),flat_unit_bets=bets,net_units=pnl,max_drawdown_units=drawdown)


def evaluate(rows, cost_per_unit=0):
    if len(rows)<200:
        raise ValueError('At least 200 independent event forecasts required')
    if not math.isfinite(cost_per_unit) or cost_per_unit < 0:
        raise ValueError('Cost must be finite and nonnegative')
    split=int(len(rows)*.7)
    # Equal timestamps stay together to keep the holdout strictly later.
    while split<len(rows) and rows[split]['timestamp']==rows[split-1]['timestamp']:
        split+=1
    if split>=len(rows) or len(rows)-split<30:
        raise ValueError('Need at least 30 strictly later holdout events')
    train,test=rows[:split],rows[split:]
    model=fit(train)
    return dict(training_events=len(train),holdout_events=len(test),cost_per_unit=cost_per_unit,
                calibration=model,raw_holdout=metrics(test,cost_per_unit=cost_per_unit),
                calibrated_holdout=metrics(test,model,cost_per_unit),
                warning='Research only: forecasts must be recorded pre-result. No live activation or profit guarantee. Costs are a user-supplied per-stake sensitivity, not an exchange fee model.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('csv')
    parser.add_argument('--output',required=True)
    parser.add_argument('--cost-per-unit',type=float,default=0)
    args=parser.parse_args()
    report=evaluate(load_rows(args.csv),args.cost_per_unit)
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
