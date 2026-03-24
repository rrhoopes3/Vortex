"""$VORTEX tokenomics model.

Total supply: 48,000,000 (honoring the 48-dimensional discovery).

Distribution:
  - 30% Ecosystem & Community  (14,400,000)
  - 25% Staking Rewards         (12,000,000)
  - 15% Team & Advisors         ( 7,200,000) — 2yr vest, 6mo cliff
  - 15% Development Fund        ( 7,200,000)
  - 10% Liquidity               ( 4,800,000)
  -  5% Quantum Research Grant   ( 2,400,000)

Utility:
  - Gas fees for smart contracts (qudit block execution)
  - Staking for validators and quantum entropy oracles
  - Governance weighted by topological contribution score
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOTAL_SUPPLY = 48_000_000
TICKER = "VORTEX"


class AllocationCategory(Enum):
    ECOSYSTEM = "ecosystem"
    STAKING_REWARDS = "staking_rewards"
    TEAM = "team"
    DEVELOPMENT = "development"
    LIQUIDITY = "liquidity"
    QUANTUM_RESEARCH = "quantum_research"


# Allocation percentages
ALLOCATIONS: Dict[AllocationCategory, float] = {
    AllocationCategory.ECOSYSTEM: 0.30,
    AllocationCategory.STAKING_REWARDS: 0.25,
    AllocationCategory.TEAM: 0.15,
    AllocationCategory.DEVELOPMENT: 0.15,
    AllocationCategory.LIQUIDITY: 0.10,
    AllocationCategory.QUANTUM_RESEARCH: 0.05,
}


# ---------------------------------------------------------------------------
# Token Distribution
# ---------------------------------------------------------------------------

@dataclass
class TokenDistribution:
    """Tracks the distribution of $VORTEX tokens across categories."""

    total_supply: int = TOTAL_SUPPLY
    distributed: Dict[str, float] = field(default_factory=dict)
    balances: Dict[str, float] = field(default_factory=dict)  # address → balance

    def allocation_for(self, category: AllocationCategory) -> float:
        """Get the total allocation for a category."""
        return self.total_supply * ALLOCATIONS[category]

    def distributed_for(self, category: str) -> float:
        return self.distributed.get(category, 0.0)

    def distribute(self, category: AllocationCategory, recipient: str, amount: float) -> bool:
        """Distribute tokens from a category to a recipient."""
        cat_key = category.value
        already = self.distributed.get(cat_key, 0.0)
        cap = self.allocation_for(category)

        if already + amount > cap:
            return False

        self.distributed[cat_key] = already + amount
        self.balances[recipient] = self.balances.get(recipient, 0.0) + amount
        return True

    def transfer(self, sender: str, recipient: str, amount: float) -> bool:
        """Transfer tokens between addresses."""
        if self.balances.get(sender, 0.0) < amount:
            return False
        self.balances[sender] -= amount
        self.balances[recipient] = self.balances.get(recipient, 0.0) + amount
        return True

    def balance_of(self, address: str) -> float:
        return self.balances.get(address, 0.0)

    @property
    def total_distributed(self) -> float:
        return sum(self.distributed.values())

    @property
    def remaining_supply(self) -> float:
        return self.total_supply - self.total_distributed

    def summary(self) -> Dict[str, Dict[str, float]]:
        """Return a summary of all allocations and distributions."""
        result = {}
        for cat in AllocationCategory:
            allocated = self.allocation_for(cat)
            distributed = self.distributed.get(cat.value, 0.0)
            result[cat.value] = {
                "allocated": allocated,
                "distributed": distributed,
                "remaining": allocated - distributed,
                "pct_distributed": (distributed / allocated * 100) if allocated > 0 else 0,
            }
        return result


# ---------------------------------------------------------------------------
# Vesting Schedule
# ---------------------------------------------------------------------------

@dataclass
class VestingSchedule:
    """Token vesting schedule (e.g., for team allocations)."""
    recipient: str
    total_amount: float
    cliff_months: int = 6           # no tokens before cliff
    vesting_months: int = 24        # total vesting period
    start_time: float = field(default_factory=time.time)
    claimed: float = 0.0

    def vested_amount(self, current_time: Optional[float] = None) -> float:
        """Calculate how many tokens have vested by the given time."""
        if current_time is None:
            current_time = time.time()

        elapsed_seconds = current_time - self.start_time
        elapsed_months = elapsed_seconds / (30 * 24 * 3600)  # approximate

        if elapsed_months < self.cliff_months:
            return 0.0

        fraction = min(elapsed_months / self.vesting_months, 1.0)
        return self.total_amount * fraction

    def claimable(self, current_time: Optional[float] = None) -> float:
        """Calculate how many tokens can be claimed now."""
        return self.vested_amount(current_time) - self.claimed

    def claim(self, current_time: Optional[float] = None) -> float:
        """Claim all available vested tokens. Returns amount claimed."""
        available = self.claimable(current_time)
        if available > 0:
            self.claimed += available
        return available


# ---------------------------------------------------------------------------
# VortexToken
# ---------------------------------------------------------------------------

@dataclass
class VortexToken:
    """$VORTEX token with gas fee calculation and governance weight.

    Gas fees are denominated in $VORTEX and scale with the dimensionality
    of the qudit block being executed.
    """
    distribution: TokenDistribution = field(default_factory=TokenDistribution)
    vesting_schedules: List[VestingSchedule] = field(default_factory=list)

    # Gas pricing
    base_gas_price: float = 0.001           # base price per unit of gas
    qudit_dimension_multiplier: float = 0.0001  # additional cost per qudit dim

    def calculate_gas(self, qudit_dimensions: int = 1, complexity: int = 1) -> float:
        """Calculate gas cost for a transaction.

        Args:
            qudit_dimensions: number of qudit dimensions used (1-48)
            complexity: computational complexity factor
        """
        return (
            self.base_gas_price
            + self.qudit_dimension_multiplier * qudit_dimensions
        ) * complexity

    def governance_weight(self, address: str, topology_score: float = 0.0) -> float:
        """Calculate governance voting weight.

        Weight = token_balance * (1 + topology_contribution_score)
        This ensures that validators who contribute verified topological
        data have proportionally more governance influence.
        """
        balance = self.distribution.balance_of(address)
        return balance * (1.0 + topology_score)

    def create_vesting(
        self,
        recipient: str,
        amount: float,
        cliff_months: int = 6,
        vesting_months: int = 24,
    ) -> VestingSchedule:
        """Create a vesting schedule for a recipient."""
        schedule = VestingSchedule(
            recipient=recipient,
            total_amount=amount,
            cliff_months=cliff_months,
            vesting_months=vesting_months,
        )
        self.vesting_schedules.append(schedule)
        return schedule
