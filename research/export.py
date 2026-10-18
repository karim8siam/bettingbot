"""Export settled paper forecasts for chronological research, one per event."""
import argparse
import csv
import sqlite3
from pathlib import Path


def export_forecasts(database, output):
    database = Path(database).resolve()
    if Path(output).resolve() == database:
        raise ValueError("Export output must not overwrite the audit database")
    # Read-only mode must not create an empty database on a typo.
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT event_id, timestamp, model_prob, decimal_odds, result FROM trades WHERE is_paper=1 AND result IN ('WON','LOST') AND event_id IS NOT NULL AND model_prob > 0 AND model_prob < 1 ORDER BY timestamp, id").fetchall()
    seen = set()
    count = 0
    with open(output, 'w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['event_id','timestamp','model_prob','decimal_odds','won'])
        for row in rows:
            if row['event_id'] in seen:
                continue
            seen.add(row['event_id'])
            writer.writerow([row['event_id'],row['timestamp']+'Z',row['model_prob'],row['decimal_odds'],int(row['result']=='WON')])
            count += 1
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    print(f'Exported {export_forecasts(args.database,args.output)} independent event forecasts')
