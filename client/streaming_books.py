"""Optional bounded WebSocket cache. REST remains the execution authority."""
import asyncio
import copy
import threading
import time
import aiohttp
from centrifuge import Client, SubscriptionEventHandler


class StreamingBooks:
    def __init__(self, rest_url, ws_url, api_key, max_books=100):
        self.rest_url,self.ws_url,self.api_key=rest_url,ws_url,api_key
        self.max_books=max_books
        self.cache={}
        self.lock=threading.Lock()
        self.loop=None
        self.client=None
        self.subscriptions={}
        self.thread=None

    def apply(self, market_hash, data):
        try:
            version=int(data['version'])
            with self.lock:
                previous=self.cache.get(market_hash)
                if previous and version<=previous[0]:
                    return
                self.cache[market_hash]=(version,time.monotonic(),copy.deepcopy(data))
        except (ValueError,KeyError,TypeError):
            return

    def snapshot(self, market_hash, max_age=5):
        if self.loop is not None and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.subscribe(market_hash),self.loop)
        with self.lock:
            row=self.cache.get(market_hash)
            if not row or time.monotonic()-row[1]>max_age:
                return None
            data=copy.deepcopy(row[2])
        # Public channel uses maker perspective. Flip sides and price; restate
        # the opposing stake that consumes that level, using integer units.
        converted={'outcomeOne':[],'outcomeTwo':[],'version':data['version']}
        for source,target in [('outcomeOne','outcomeTwo'),('outcomeTwo','outcomeOne')]:
            for level in data.get(source,[]):
                p,size=int(level['percentageOdds']),int(level['size'])
                if 0<p<10**20 and size>0:
                    converted[target].append({'percentageOdds':str(10**20-p),'size':str(size*(10**20-p)//p)})
            converted[target].sort(key=lambda level:int(level['percentageOdds']))
        return converted

    async def subscribe(self, market_hash):
        if self.client is None or market_hash in self.subscriptions or len(self.subscriptions)>=self.max_books:
            return
        owner=self
        class Handler(SubscriptionEventHandler):
            async def on_subscribed(self, ctx):
                # Seed on every subscribe/reconnect; version guard prevents a
                # delayed seed from replacing a newer publication.
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(owner.rest_url+'/orderbook-v3/snapshot/market',params={'marketHash':market_hash},headers={'x-sx-api-key':owner.api_key},timeout=aiohttp.ClientTimeout(total=10)) as response:
                            response.raise_for_status()
                            payload=await response.json()
                            if payload.get('status')=='success':owner.apply(market_hash,payload['data'])
                except Exception:
                    with owner.lock:owner.cache.pop(market_hash,None)

            async def on_publication(self, ctx):
                owner.apply(market_hash,ctx.pub.data)

            async def on_unsubscribed(self, ctx):
                with owner.lock:owner.cache.pop(market_hash,None)

        sub=self.client.new_subscription('orderbook_v3:'+market_hash,Handler())
        self.subscriptions[market_hash]=sub
        try:
            await sub.subscribe()
        except Exception:
            self.subscriptions.pop(market_hash,None)

    def start(self):
        def run():
            self.loop=asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            async def token(*args):
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.rest_url+'/user/realtime-token-v3/api-key',headers={'x-sx-api-key':self.api_key},timeout=aiohttp.ClientTimeout(total=10)) as response:
                        response.raise_for_status()
                        return (await response.json())['token']
            self.client=Client(self.ws_url,get_token=token)
            try:
                self.loop.run_until_complete(self.client.connect())
                self.loop.run_forever()
            except Exception:
                pass # Polling continues; cached books expire in five seconds.
            finally:
                self.loop.run_until_complete(self.client.disconnect())
                pending=asyncio.all_tasks(self.loop)
                for task in pending:task.cancel()
                self.loop.run_until_complete(asyncio.gather(*pending,return_exceptions=True))
                self.loop.close()
                with self.lock:self.cache.clear()
        self.thread=threading.Thread(target=run,daemon=True)
        self.thread.start()

    def close(self):
        if self.loop and self.loop.is_running():self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:self.thread.join(timeout=12)
