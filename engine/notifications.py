"""Persistent notification dispatch without blindly retrying ambiguous sends."""
import json
import time


def dispatch_notifications(audit, notifier, limit=10, now=None):
    if not notifier.is_configured:
        return
    now = time.time() if now is None else now
    with audit._get_connection() as db:
        rows = db.execute("SELECT id, kind, payload, destination, attempts FROM notifications WHERE state IN ('PENDING','RETRY') AND next_attempt <= ? ORDER BY rowid LIMIT ?", (now, limit)).fetchall()
    handlers = {'opened': notifier.notify_trade_opened, 'settled': notifier.notify_trade_settled}
    for event_id, kind, payload, destination, attempts in rows:
        with audit._get_connection() as db:
            claimed = db.execute("UPDATE notifications SET state='SENDING', attempts=attempts+1 WHERE id=? AND state IN ('PENDING','RETRY')", (event_id,)).rowcount
        if not claimed:
            continue
        state, retry_after = 'UNKNOWN', 0
        if destination != notifier.channel_id or kind not in handlers:
            state = 'FAILED'
        else:
            try:
                delivered = handlers[kind](**json.loads(payload))
                state = 'SENT' if delivered else notifier.last_delivery['state']
                retry_after = notifier.last_delivery.get('retry_after', 0)
            except Exception:
                # The HTTP call may have reached Telegram. Do not resend blindly.
                state = 'UNKNOWN'
        if state == 'RETRY' and attempts + 1 >= 5:
            state = 'FAILED'
        with audit._get_connection() as db:
            db.execute("UPDATE notifications SET state=?, next_attempt=? WHERE id=?", (state, now + max(1, retry_after), event_id))
