"""Inspect an existing SX order without sending, retrying, or cancelling it."""
import argparse
import json
from config import config
from client.rest_client import SXBetClient
from engine.order_recovery import OrderRecovery


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--order-id',required=True)
    parser.add_argument('--client-id',required=True)
    parser.add_argument('--market-hash',required=True)
    args=parser.parse_args()
    if not config.api_key or config.api_key.startswith('your_'):
        parser.error('Set SX_API_KEY locally')
    journal=OrderRecovery(config.data_dir/f'orders_{config.network_name}.db')
    if journal.snapshot(args.order_id) is None:
        journal.register(args.order_id,args.client_id,args.market_hash)
    client=SXBetClient(config.rest_url,config.api_key)
    try:
        journal.reconcile(client,args.order_id)
        print(json.dumps(journal.snapshot(args.order_id),indent=2))
    finally:
        client.session.close()


if __name__=='__main__':
    main()
