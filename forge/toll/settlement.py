"""
Settlement backend abstraction.

Beat 2: LocalSettlement (SQLite — instant).
Beat 3: Swap in BaseSettlement / SolanaSettlement (smart contract).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.toll.models import Transaction


class SettlementBackend(ABC):
    """Abstract settlement backend — swap local for blockchain in Beat 3."""

    @abstractmethod
    def settle(self, transactions: list[Transaction]) -> list[str]:
        """Settle a batch of transactions. Returns list of settlement hashes/IDs."""
        ...

    @abstractmethod
    def verify(self, chain_tx_hash: str) -> bool:
        """Verify a settlement was committed."""
        ...

    @abstractmethod
    def get_balance(self, wallet_address: str) -> float:
        """Get on-chain balance for a wallet address."""
        ...


class LocalSettlement(SettlementBackend):
    """Local settlement — transactions are settled immediately in SQLite.

    Beat 3 replaces this with:
    - BaseSettlement  (Base L2 smart contract, USDC)
    - SolanaSettlement (Solana program)
    """

    def settle(self, transactions: list[Transaction]) -> list[str]:
        return [tx.tx_id for tx in transactions]

    def verify(self, chain_tx_hash: str) -> bool:
        return True

    def get_balance(self, wallet_address: str) -> float:
        return 0.0  # not applicable for local


class SolanaSettlement(SettlementBackend):
    """Solana USDC settlement — read-only verification.

    Beat 4: Verifies incoming USDC transfers on Solana.
    Does not send transactions (no private key needed).
    """

    def __init__(self, rpc_url: str, usdc_mint: str):
        self.rpc_url = rpc_url
        self.usdc_mint = usdc_mint

    def settle(self, transactions: list[Transaction]) -> list[str]:
        raise NotImplementedError(
            "SolanaSettlement is read-only. Agents deposit USDC directly."
        )

    def verify(self, chain_tx_hash: str) -> bool:
        """Verify a Solana transaction exists and succeeded."""
        import requests
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getTransaction",
            "params": [chain_tx_hash, {"encoding": "jsonParsed",
                                        "maxSupportedTransactionVersion": 0}],
        }
        try:
            resp = requests.post(self.rpc_url, json=payload, timeout=10)
            data = resp.json()
            result = data.get("result")
            if not result:
                return False
            return result.get("meta", {}).get("err") is None
        except Exception:
            return False

    def get_balance(self, wallet_address: str) -> float:
        """Get USDC balance for a Solana wallet address."""
        import requests
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet_address,
                {"mint": self.usdc_mint},
                {"encoding": "jsonParsed"},
            ],
        }
        try:
            resp = requests.post(self.rpc_url, json=payload, timeout=10)
            data = resp.json()
            accounts = data.get("result", {}).get("value", [])
            if not accounts:
                return 0.0
            info = accounts[0]["account"]["data"]["parsed"]["info"]
            return float(info["tokenAmount"]["uiAmount"] or 0)
        except Exception:
            return 0.0
