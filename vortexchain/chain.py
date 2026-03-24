"""VortexChain blockchain core.

Implements the block structure and chain management for VortexChain.
Each block is hashed using topological hashing (TOAC) instead of SHA-256,
and can encode state in high-dimensional "qudit blocks".
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from vortexchain.toac import TOACKeypair, TopologicalHash, TopologicalSignature


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    """A VortexChain transaction.

    Transactions can transfer $VORTEX, invoke smart contracts, or submit
    topological proofs for the Proof-of-Topology consensus.
    """
    sender: str                         # vx-address
    recipient: str                      # vx-address
    amount: float                       # $VORTEX amount
    tx_type: str = "transfer"           # transfer | contract | topology_proof
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    signature: Optional[TopologicalSignature] = None
    nonce: int = 0

    def to_bytes(self) -> bytes:
        """Canonical serialisation for hashing/signing."""
        payload = {
            "sender": self.sender,
            "recipient": self.recipient,
            "amount": self.amount,
            "tx_type": self.tx_type,
            "data": self.data,
            "timestamp": self.timestamp,
            "nonce": self.nonce,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def sign(self, keypair: TOACKeypair) -> None:
        """Sign this transaction with the sender's keypair."""
        self.signature = TopologicalSignature.sign(keypair, self.to_bytes())

    def tx_hash(self) -> TopologicalHash:
        """Compute the topological hash of this transaction."""
        return TopologicalHash.hash(self.to_bytes())


# ---------------------------------------------------------------------------
# Block
# ---------------------------------------------------------------------------

@dataclass
class Block:
    """A VortexChain block.

    Each block contains:
    - An ordered list of transactions
    - A topological hash (replacing SHA-256)
    - A reference to the previous block's hash
    - Validator info and topology proof
    """
    index: int
    transactions: List[Transaction]
    previous_hash: str                  # hex of previous block's topological hash
    timestamp: float = field(default_factory=time.time)
    validator: str = ""                 # vx-address of block validator
    topology_proof: Optional[Dict[str, Any]] = None
    nonce: int = 0
    block_hash: str = ""                # computed after creation

    def compute_hash(self) -> TopologicalHash:
        """Compute the topological hash for this block."""
        payload = {
            "index": self.index,
            "previous_hash": self.previous_hash,
            "timestamp": self.timestamp,
            "validator": self.validator,
            "nonce": self.nonce,
            "tx_hashes": [tx.tx_hash().hex() for tx in self.transactions],
        }
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return TopologicalHash.hash(data)

    def seal(self) -> str:
        """Compute and store the block hash. Returns the hex digest."""
        h = self.compute_hash()
        self.block_hash = h.hex()
        return self.block_hash


# ---------------------------------------------------------------------------
# VortexChain
# ---------------------------------------------------------------------------

class VortexChain:
    """The VortexChain blockchain.

    Maintains an ordered list of blocks with topological hashing and
    supports the hybrid PoS + PoT consensus mechanism.
    """

    def __init__(self) -> None:
        self.chain: List[Block] = []
        self.pending_transactions: List[Transaction] = []
        self.validators: Dict[str, float] = {}  # address → staked amount
        self._create_genesis_block()

    # ------------------------------------------------------------------
    # Genesis
    # ------------------------------------------------------------------

    def _create_genesis_block(self) -> None:
        genesis = Block(
            index=0,
            transactions=[],
            previous_hash="0" * 96,  # 48-byte zero hash in hex
            timestamp=0.0,
            validator="vx_genesis",
        )
        genesis.seal()
        self.chain.append(genesis)

    # ------------------------------------------------------------------
    # Chain queries
    # ------------------------------------------------------------------

    @property
    def latest_block(self) -> Block:
        return self.chain[-1]

    @property
    def height(self) -> int:
        return len(self.chain)

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    def add_transaction(self, tx: Transaction) -> TopologicalHash:
        """Add a transaction to the pending pool. Returns its hash."""
        self.pending_transactions.append(tx)
        return tx.tx_hash()

    # ------------------------------------------------------------------
    # Block creation
    # ------------------------------------------------------------------

    def create_block(self, validator: str, topology_proof: Optional[Dict[str, Any]] = None) -> Block:
        """Create a new block from pending transactions.

        Args:
            validator: The vx-address of the validator creating this block.
            topology_proof: Optional proof-of-topology data from the validator.
        """
        block = Block(
            index=self.height,
            transactions=list(self.pending_transactions),
            previous_hash=self.latest_block.block_hash,
            validator=validator,
            topology_proof=topology_proof,
        )
        block.seal()
        self.chain.append(block)
        self.pending_transactions.clear()
        return block

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_chain(self) -> bool:
        """Validate the entire chain's integrity."""
        for i in range(1, len(self.chain)):
            current = self.chain[i]
            previous = self.chain[i - 1]

            # Check hash linkage
            if current.previous_hash != previous.block_hash:
                return False

            # Verify block hash
            expected = current.compute_hash().hex()
            if current.block_hash != expected:
                return False

        return True

    # ------------------------------------------------------------------
    # Staking
    # ------------------------------------------------------------------

    def register_validator(self, address: str, stake: float) -> None:
        """Register a validator with a stake amount."""
        self.validators[address] = self.validators.get(address, 0.0) + stake

    def get_validator_stake(self, address: str) -> float:
        return self.validators.get(address, 0.0)
