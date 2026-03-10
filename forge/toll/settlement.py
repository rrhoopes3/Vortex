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
