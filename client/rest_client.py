"""
SX Bet V3 REST API Client.
Provides typed access to public market data, orderbook snapshots, and authenticated trading endpoints.
"""

from typing import Dict, Any, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger
from utils.conversions import units_to_usdc
from utils.orderbook import levels


class SXBetClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        # Retry transient read-only failures, never an order submission/cancellation.
        retries = Retry(total=2, connect=2, read=2, status=2, backoff_factor=0.5,
                        allowed_methods=frozenset({'GET'}),
                        status_forcelist=(429, 502, 503, 504),
                        respect_retry_after_header=False)
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 SXBetBot/1.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        if self.api_key:
            self.session.headers["x-sx-api-key"] = self.api_key

        self._metadata: Optional[Dict[str, Any]] = None

    def get_metadata(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Fetch exchange metadata including EIP-712 domain and active token contract."""
        if self._metadata and not force_refresh:
            return self._metadata
        
        url = f"{self.base_url}/metadata/obv3"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "success":
            raise ValueError("SX metadata request failed")
        data = payload["data"]
        self._metadata = data
        return data

    @property
    def domain(self) -> Dict[str, Any]:
        """EIP-712 domain dictionary."""
        return self.get_metadata().get("domain", {})

    @property
    def base_token(self) -> str:
        """Active collateral token contract address (USDC)."""
        active_asset = self.get_metadata().get("activeAsset", {})
        return active_asset.get("baseToken", "")

    def get_active_markets(
        self,
        sport_id: Optional[int] = None,
        league_id: Optional[int] = None,
        only_main_line: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fetch currently active betting markets."""
        url = f"{self.base_url}/markets/active"
        params: Dict[str, Any] = {"onlyMainLine": str(only_main_line).lower()}
        if sport_id:
            params["sportId"] = sport_id
        if league_id:
            params["leagueId"] = league_id

        markets, seen = [], set()
        while True:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") != "success":
                raise ValueError("SX active markets request failed")
            data = payload["data"]
            markets.extend(data.get("markets", []))
            key = data.get("nextKey")
            if not key:
                return markets
            if key in seen:
                raise ValueError("SX repeated pagination cursor")
            seen.add(key)
            params["paginationKey"] = key

    def find_market(self, market_hash: str) -> Optional[Dict[str, Any]]:
        """Look up a specific market by its market hash (including settlement details)."""
        url = f"{self.base_url}/markets/find"
        params = {"marketHashes": market_hash}
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            raise ValueError("SX market lookup failed")
        return next((m for m in data.get("data", []) if m.get("marketHash") == market_hash), None)

    def get_orderbook(self, market_hash: str, show_taker_perspective: bool = True) -> Dict[str, Any]:
        """
        Fetch orderbook snapshot for a specific market.
        With show_taker_perspective=True, percentageOdds is the price to bet that outcome.
        """
        url = f"{self.base_url}/orderbook-v3/snapshot/market"
        params = {
            "marketHash": market_hash,
            "showTakerPerspective": str(show_taker_perspective).lower(),
        }
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get('status') != 'success':
            raise ValueError('SX orderbook request failed')
        book = payload['data']
        if book.get('marketHash', market_hash) != market_hash:
            raise ValueError('SX orderbook market mismatch')
        for side in ('outcomeOne', 'outcomeTwo'):
            book[side] = levels(book.get(side, []))
        return book

    def get_best_odds(self, market_hashes: List[str]) -> Dict[str, Any]:
        """Fetch best resting odds for a batch of market hashes."""
        url = f"{self.base_url}/orders-v3/odds/best"
        params = {"marketHashes": ",".join(market_hashes)}
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("data", {})

    def get_proxy_wallet(self) -> Optional[str]:
        """Get the deployed proxy wallet address for authenticated account."""
        if not self.api_key:
            return None
        url = f"{self.base_url}/user/proxy"
        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            return data.get("obv3ProxyWalletAddress") or data.get("proxyWalletAddress") or data.get("proxyAddress")
        return None

    def get_balance(self) -> float:
        """Get spendable USDC balance in the proxy wallet."""
        if not self.api_key:
            return 0.0
        url = f"{self.base_url}/user/balance-v3"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "success":
            raise ValueError("SX balance request failed")
        asset = self.get_metadata()["activeAsset"]
        rows = [row for row in payload["data"]["balances"]
                if row["tokenAddress"].lower() == asset["baseToken"].lower()
                and row["escrowAddress"].lower() == asset["escrowAddress"].lower()]
        if len(rows) > 1:
            raise ValueError("Ambiguous active-asset balance")
        return units_to_usdc(rows[0]["availableAmount"]) if rows else 0.0

    def submit_orders(self, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Submit one or more signed orders to the SX Bet orderbook.
        Orders should include 'orderSignature' and 'timeInForce' ('FOK' or 'GTC').
        """
        if not self.api_key:
            raise ValueError("API key required to submit live orders.")
        
        url = f"{self.base_url}/orders-v3"
        payload = {"orders": orders}
        resp = self.session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def cancel_orders(self, order_ids: List[str]) -> Dict[str, Any]:
        """Cancel resting orders by their IDs."""
        if not self.api_key:
            raise ValueError("API key required to cancel orders.")
        url = f"{self.base_url}/orders-v3"
        payload = {"orderIds": order_ids}
        resp = self.session.delete(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_realtime_token(self) -> str:
        """Fetch a short-lived JWT for Centrifuge WebSocket streaming."""
        url = f"{self.base_url}/user/realtime-token-v3/api-key"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("token", "")

    def get_order(self, order_id):
        """Read an authenticated order, including inactive orders. 404 is unknown."""
        from urllib.parse import quote
        resp = self.session.get(f'{self.base_url}/orders-v3/{quote(order_id, safe="")}', timeout=self.timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        payload = resp.json()
        if payload.get('status') != 'success':
            raise ValueError('SX order lookup failed')
        return payload['data']['order']

    def get_fills(self, order_id):
        """Read all fill pages for one order; no status filter hides partial state."""
        params = {'orderId':order_id}
        fills, seen = {}, set()
        while True:
            resp = self.session.get(f'{self.base_url}/fills-v3', params=dict(params), timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get('status') != 'success':
                raise ValueError('SX fill lookup failed')
            data = payload['data']
            for fill in data['fills']:
                fills[fill['id']] = fill
            key = data.get('nextKey')
            if not key:
                return list(fills.values())
            if key in seen:
                raise ValueError('SX repeated fill pagination cursor')
            seen.add(key)
            params['nextKey'] = key
