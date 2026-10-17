"""
SX Bet EIP-712 Order Signer.
Handles cryptographic signing of order payloads using the account's private key.
"""

import secrets
import time
from typing import Dict, Any, Tuple
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak


SX_ORDER_TYPES = {
    "Order": [
        {"name": "marketHash", "type": "bytes32"},
        {"name": "baseToken", "type": "address"},
        {"name": "totalBetSize", "type": "uint256"},
        {"name": "percentageOdds", "type": "uint256"},
        {"name": "salt", "type": "uint256"},
        {"name": "expiry", "type": "uint256"},
        {"name": "maker", "type": "address"},
        {"name": "isMakerBettingOutcomeOne", "type": "bool"},
    ],
}


class SXOrderSigner:
    def __init__(self, private_key: str):
        if not private_key or private_key.startswith("0x000000"):
            self.account = None
            self.address = None
        else:
            self.account = Account.from_key(private_key)
            self.address = self.account.address

    def is_configured(self) -> bool:
        """Check if a valid private key is loaded."""
        return self.account is not None

    def sign_order(
        self,
        domain: Dict[str, Any],
        market_hash: str,
        base_token: str,
        total_bet_size: int,
        percentage_odds: str,
        is_maker_betting_outcome_one: bool,
        expiry_seconds: int = 3600,
        salt_hex: str = None,
    ) -> Tuple[Dict[str, Any], str, str]:
        """
        Build, sign, and compute the orderId for an SX Bet order.
        
        Returns:
            (order_payload, order_signature_hex, order_id_hex)
        """
        if not self.account:
            raise ValueError("Signer requires a valid private key to sign live orders.")

        salt = salt_hex or ("0x" + secrets.token_hex(32))
        expiry = int(time.time()) + expiry_seconds

        order = {
            "marketHash": market_hash,
            "baseToken": base_token,
            "totalBetSize": str(total_bet_size),
            "percentageOdds": str(percentage_odds),
            "salt": salt,
            "expiry": expiry,
            "maker": self.address,
            "isMakerBettingOutcomeOne": is_maker_betting_outcome_one,
        }

        # Typed data message requires integers for numerical uint256 types
        message = {
            **order,
            "totalBetSize": int(order["totalBetSize"]),
            "percentageOdds": int(order["percentageOdds"]),
            "salt": int(order["salt"], 16),
        }

        signable = encode_typed_data(domain, SX_ORDER_TYPES, message)
        signed = self.account.sign_message(signable)
        order_signature = signed.signature.to_0x_hex()

        # Order ID is the lowercased keccak256 EIP-712 digest
        order_id = "0x" + keccak(b"\x19" + signable.version + signable.header + signable.body).hex().lower()

        return order, order_signature, order_id
