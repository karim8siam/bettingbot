"""Durable order-intent journal and read-only exchange reconciliation.

This module deliberately exposes no network submission method. It supports testing
and recovery of externally submitted orders without accidentally resubmitting an
order whose HTTP acknowledgement was lost. Fill facts, not order acknowledgement,
are the source of truth. It is separate from the paper bankroll ledger.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class OrderRecovery:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS intents (order_id TEXT PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, market_hash TEXT NOT NULL, state TEXT NOT NULL, order_json TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)')
            db.execute('CREATE TABLE IF NOT EXISTS fills (fill_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, payload TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.path))
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def register(self, order_id, client_id, market_hash):
        """Persist identity before submission. Duplicate registration is rejected."""
        if not order_id or not client_id or not market_hash:
            raise ValueError('Complete order identity is required')
        with self.connect() as db:
            db.execute('INSERT INTO intents(order_id,client_id,market_hash,state) VALUES (?,?,?,?)', (order_id,client_id,market_hash,'UNKNOWN'))

    def reconcile(self, client, order_id):
        with self.connect() as db:
            intent = db.execute('SELECT market_hash FROM intents WHERE order_id=?', (order_id,)).fetchone()
        if intent is None:
            raise ValueError('Register the order identity before reconciliation')
        try:
            order = client.get_order(order_id)
        except Exception:
            self.mark_unknown(order_id)
            raise
        if order is None:
            # 404 can be transient. Never infer rejection or release exposure.
            self.mark_unknown(order_id)
            return 'UNKNOWN'
        if order.get('id') != order_id or order.get('marketHash') != intent[0]:
            raise ValueError('Order identity mismatch')
        try:
            fills = client.get_fills(order_id)
        except Exception:
            self.mark_unknown(order_id)
            raise
        if len({fill.get("id") for fill in fills}) != len(fills) or any(not fill.get("id") for fill in fills):
            self.mark_unknown(order_id)
            raise ValueError("Duplicate or missing fill identity")
        for fill in fills:
            if fill.get('orderId') != order_id or fill.get('marketHash') != intent[0]:
                raise ValueError('Fill identity mismatch')
        state = 'PENDING'
        if order.get('status') == 'INACTIVE':
            if not fills:
                # Even NO_LIQUIDITY is not sufficient to infer no earlier partial
                # fills; require an explicit unchanged remaining size as well.
                if order.get('inactiveReason') != 'FILLED' and str(order.get('remainingSize')) == str(order.get('totalBetSize')) and order.get('totalBetSize') is not None:
                    state = 'UNFILLED'
                else:
                    state = 'UNKNOWN'
            elif all(f.get('status') == 'SETTLED' and f.get('settlement') for f in fills):
                state = 'SETTLED'
            elif all(f.get('status') in ('LOCKED','SETTLED') for f in fills):
                state = 'FILLED'
            else:
                state = 'PENDING'
        # Do not declare a full/settled position from an eventually consistent
        # partial fills response. Filled units must reconcile with the order.
        if state in ('FILLED', 'SETTLED'):
            try:
                expected = int(order['totalBetSize']) - int(order['remainingSize'])
                observed = sum(int(fill['fillAmount']) for fill in fills)
                if expected <= 0 or observed != expected:
                    state = 'UNKNOWN'
            except (KeyError, TypeError, ValueError):
                state = 'UNKNOWN'
        with self.connect() as db:
            for fill in fills:
                db.execute('INSERT INTO fills VALUES (?,?,?) ON CONFLICT(fill_id) DO UPDATE SET payload=excluded.payload', (fill['id'],order_id,json.dumps(fill)))
            db.execute('UPDATE intents SET state=?,order_json=?,updated_at=CURRENT_TIMESTAMP WHERE order_id=?', (state,json.dumps(order),order_id))
        return state

    def snapshot(self, order_id):
        with self.connect() as db:
            row = db.execute('SELECT state, order_json FROM intents WHERE order_id=?',(order_id,)).fetchone()
            fills = [json.loads(r[0]) for r in db.execute('SELECT payload FROM fills WHERE order_id=?',(order_id,))]
        return {'state':row[0], 'order':json.loads(row[1]) if row[1] else None, 'fills':fills} if row else None

    def mark_unknown(self, order_id):
        with self.connect() as db:
            db.execute("UPDATE intents SET state='UNKNOWN', updated_at=CURRENT_TIMESTAMP WHERE order_id=?", (order_id,))
