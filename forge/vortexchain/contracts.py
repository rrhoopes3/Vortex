"""Qudit Smart Contract Runtime for VortexChain.

Unlike classical smart contracts that operate on binary state (bits), VortexChain
contracts encode state in high-dimensional "qudit blocks" — each storage slot
can hold a point on the 48D topological manifold, giving contracts access to
exponentially denser state encoding.

Key features:
  - **Qudit Storage**: Each contract variable is a manifold point, not a word.
  - **Topological Guards**: Functions can require callers to prove knowledge of
    specific wrapping-number subsets before execution (like Solidity's modifiers,
    but backed by topology).
  - **Deterministic Execution**: All manifold operations are deterministic in
    classical simulation mode, ensuring consensus across nodes.
  - **Gas Model**: Gas scales with qudit dimensionality used (1-48D).

Architecture mirrors the EVM but with a topological twist:
  - Opcodes operate on manifold points instead of 256-bit words
  - The "stack" holds TopologicalManifold objects
  - Storage maps bytes32 keys to manifold points
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple

from forge.vortexchain.manifold import (
    MANIFOLD_DIM,
    NUM_EMBEDDED_SPHERES,
    TopologicalManifold,
)
from forge.vortexchain.toac import TOACKeypair, TopologicalHash, TopologicalSignature


# ---------------------------------------------------------------------------
# Opcodes
# ---------------------------------------------------------------------------

class QuditOpcode(Enum):
    """Opcodes for the Qudit Virtual Machine (QVM)."""
    # Stack operations
    PUSH_MANIFOLD = auto()    # Push a manifold point onto the stack
    POP = auto()              # Pop top of stack
    DUP = auto()              # Duplicate top of stack
    SWAP = auto()             # Swap top two stack elements

    # Manifold operations
    PROJECT = auto()          # Project manifold onto subspace
    DISTANCE = auto()         # Topological distance between two manifold points
    MERGE = auto()            # Merge two manifold points (component-wise avg)
    HASH = auto()             # Topological hash of top-of-stack

    # Storage
    SLOAD = auto()            # Load manifold from storage
    SSTORE = auto()           # Store manifold to storage

    # Arithmetic (on wrapping numbers)
    WRAP_ADD = auto()         # Add wrapping numbers (mod 997)
    WRAP_MUL = auto()         # Multiply wrapping numbers (mod 997)
    SPECTRUM = auto()         # Extract topological spectrum as integers

    # Control flow
    TOPO_GUARD = auto()       # Assert wrapping number equals expected value
    HALT = auto()             # Stop execution
    REVERT = auto()           # Revert all state changes

    # I/O
    EMIT = auto()             # Emit an event with manifold data
    CALLER = auto()           # Push caller's address manifold onto stack


# ---------------------------------------------------------------------------
# Execution context
# ---------------------------------------------------------------------------

@dataclass
class ContractEvent:
    """An event emitted during contract execution."""
    name: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    block_index: int = 0


@dataclass
class ExecutionResult:
    """Result of contract execution."""
    success: bool
    gas_used: float
    return_data: Optional[Any] = None
    events: List[ContractEvent] = field(default_factory=list)
    error: Optional[str] = None
    state_changes: Dict[str, Any] = field(default_factory=dict)


class ExecutionContext:
    """Runtime context for qudit contract execution.

    Holds the manifold stack, storage, gas counter, and event log.
    """

    def __init__(
        self,
        caller: str,
        gas_limit: float,
        storage: Optional[Dict[str, TopologicalManifold]] = None,
    ):
        self.caller = caller
        self.gas_limit = gas_limit
        self.gas_used: float = 0.0
        self.stack: List[TopologicalManifold] = []
        self.storage: Dict[str, TopologicalManifold] = dict(storage or {})
        self._original_storage: Dict[str, bytes] = {
            k: v.to_bytes() for k, v in self.storage.items()
        }
        self.events: List[ContractEvent] = []
        self.halted: bool = False
        self.reverted: bool = False
        self.return_value: Optional[Any] = None

    def consume_gas(self, amount: float) -> None:
        """Consume gas; raises if limit exceeded."""
        self.gas_used += amount
        if self.gas_used > self.gas_limit:
            raise GasExhaustedError(
                f"Gas exhausted: used {self.gas_used:.4f}, limit {self.gas_limit:.4f}"
            )

    def push(self, manifold: TopologicalManifold) -> None:
        self.stack.append(manifold)

    def pop(self) -> TopologicalManifold:
        if not self.stack:
            raise ContractRuntimeError("Stack underflow")
        return self.stack.pop()

    def peek(self) -> TopologicalManifold:
        if not self.stack:
            raise ContractRuntimeError("Stack empty")
        return self.stack[-1]

    @property
    def state_changes(self) -> Dict[str, Any]:
        """Return keys whose storage changed during execution."""
        changes = {}
        for key, manifold in self.storage.items():
            original = self._original_storage.get(key)
            current = manifold.to_bytes()
            if original != current:
                changes[key] = {
                    "spectrum": manifold.topological_spectrum(),
                }
        # Deleted keys
        for key in self._original_storage:
            if key not in self.storage:
                changes[key] = {"deleted": True}
        return changes


class ContractRuntimeError(Exception):
    """Raised when a contract execution error occurs."""
    pass


class GasExhaustedError(ContractRuntimeError):
    """Raised when a contract runs out of gas."""
    pass


class TopologicalGuardError(ContractRuntimeError):
    """Raised when a topological guard check fails."""
    pass


# ---------------------------------------------------------------------------
# Gas costs per opcode
# ---------------------------------------------------------------------------

GAS_COSTS: Dict[QuditOpcode, float] = {
    QuditOpcode.PUSH_MANIFOLD: 0.003,
    QuditOpcode.POP: 0.001,
    QuditOpcode.DUP: 0.002,
    QuditOpcode.SWAP: 0.001,
    QuditOpcode.PROJECT: 0.005,
    QuditOpcode.DISTANCE: 0.010,
    QuditOpcode.MERGE: 0.008,
    QuditOpcode.HASH: 0.020,
    QuditOpcode.SLOAD: 0.050,
    QuditOpcode.SSTORE: 0.200,
    QuditOpcode.WRAP_ADD: 0.004,
    QuditOpcode.WRAP_MUL: 0.004,
    QuditOpcode.SPECTRUM: 0.003,
    QuditOpcode.TOPO_GUARD: 0.015,
    QuditOpcode.HALT: 0.000,
    QuditOpcode.REVERT: 0.000,
    QuditOpcode.EMIT: 0.010,
    QuditOpcode.CALLER: 0.002,
}


# ---------------------------------------------------------------------------
# Instruction
# ---------------------------------------------------------------------------

@dataclass
class Instruction:
    """A single QVM instruction."""
    opcode: QuditOpcode
    operand: Any = None  # opcode-specific data


# ---------------------------------------------------------------------------
# Qudit Virtual Machine (QVM)
# ---------------------------------------------------------------------------

class QuditVM:
    """The Qudit Virtual Machine — executes topological smart contracts.

    Instead of 256-bit EVM words, the QVM operates on 48-dimensional
    topological manifold points.  This enables contracts to encode
    exponentially more state per storage slot and leverage topological
    invariants for access control and verification.
    """

    def __init__(self) -> None:
        self._instruction_handlers: Dict[QuditOpcode, Callable] = {
            QuditOpcode.PUSH_MANIFOLD: self._op_push_manifold,
            QuditOpcode.POP: self._op_pop,
            QuditOpcode.DUP: self._op_dup,
            QuditOpcode.SWAP: self._op_swap,
            QuditOpcode.PROJECT: self._op_project,
            QuditOpcode.DISTANCE: self._op_distance,
            QuditOpcode.MERGE: self._op_merge,
            QuditOpcode.HASH: self._op_hash,
            QuditOpcode.SLOAD: self._op_sload,
            QuditOpcode.SSTORE: self._op_sstore,
            QuditOpcode.WRAP_ADD: self._op_wrap_add,
            QuditOpcode.WRAP_MUL: self._op_wrap_mul,
            QuditOpcode.SPECTRUM: self._op_spectrum,
            QuditOpcode.TOPO_GUARD: self._op_topo_guard,
            QuditOpcode.HALT: self._op_halt,
            QuditOpcode.REVERT: self._op_revert,
            QuditOpcode.EMIT: self._op_emit,
            QuditOpcode.CALLER: self._op_caller,
        }

    def execute(
        self,
        instructions: List[Instruction],
        ctx: ExecutionContext,
    ) -> ExecutionResult:
        """Execute a sequence of QVM instructions."""
        try:
            for instr in instructions:
                if ctx.halted or ctx.reverted:
                    break

                # Charge gas
                cost = GAS_COSTS.get(instr.opcode, 0.01)
                ctx.consume_gas(cost)

                # Dispatch
                handler = self._instruction_handlers.get(instr.opcode)
                if handler is None:
                    raise ContractRuntimeError(
                        f"Unknown opcode: {instr.opcode}"
                    )
                handler(ctx, instr.operand)

            if ctx.reverted:
                return ExecutionResult(
                    success=False,
                    gas_used=ctx.gas_used,
                    error="Execution reverted",
                    events=[],
                )

            return ExecutionResult(
                success=True,
                gas_used=ctx.gas_used,
                return_data=ctx.return_value,
                events=ctx.events,
                state_changes=ctx.state_changes,
            )

        except GasExhaustedError as e:
            return ExecutionResult(
                success=False,
                gas_used=ctx.gas_used,
                error=str(e),
            )
        except ContractRuntimeError as e:
            return ExecutionResult(
                success=False,
                gas_used=ctx.gas_used,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Opcode implementations
    # ------------------------------------------------------------------

    def _op_push_manifold(self, ctx: ExecutionContext, operand: Any) -> None:
        if isinstance(operand, TopologicalManifold):
            ctx.push(operand)
        elif isinstance(operand, bytes):
            ctx.push(TopologicalManifold.from_seed(operand))
        else:
            raise ContractRuntimeError("PUSH_MANIFOLD requires manifold or seed bytes")

    def _op_pop(self, ctx: ExecutionContext, _: Any) -> None:
        ctx.pop()

    def _op_dup(self, ctx: ExecutionContext, _: Any) -> None:
        m = ctx.peek()
        # Create a copy via serialization roundtrip
        ctx.push(TopologicalManifold.from_bytes(m.to_bytes()))

    def _op_swap(self, ctx: ExecutionContext, _: Any) -> None:
        if len(ctx.stack) < 2:
            raise ContractRuntimeError("SWAP requires 2 stack elements")
        ctx.stack[-1], ctx.stack[-2] = ctx.stack[-2], ctx.stack[-1]

    def _op_project(self, ctx: ExecutionContext, operand: Any) -> None:
        m = ctx.pop()
        axes = operand if isinstance(operand, tuple) else (0, 1, 2)
        projection = m.project(axes)
        # Store projection as return value (projections are lossy)
        ctx.return_value = projection

    def _op_distance(self, ctx: ExecutionContext, _: Any) -> None:
        b = ctx.pop()
        a = ctx.pop()
        dist = a.topological_distance(b)
        ctx.return_value = dist

    def _op_merge(self, ctx: ExecutionContext, _: Any) -> None:
        b = ctx.pop()
        a = ctx.pop()
        # Component-wise average
        merged_components = [
            (ca + cb) / 2.0 for ca, cb in zip(a.components, b.components)
        ]
        merged_wrapping = []
        for wa, wb in zip(a.wrapping_numbers, b.wrapping_numbers):
            from forge.vortexchain.manifold import WrappingNumber
            merged_wrapping.append(WrappingNumber(
                sphere_index=wa.sphere_index,
                value=(wa.value + wb.value) % 997,
            ))
        merged = TopologicalManifold(
            components=merged_components,
            wrapping_numbers=merged_wrapping,
        )
        ctx.push(merged)

    def _op_hash(self, ctx: ExecutionContext, _: Any) -> None:
        m = ctx.pop()
        h = TopologicalHash.hash(m.to_bytes())
        ctx.return_value = h

    def _op_sload(self, ctx: ExecutionContext, operand: Any) -> None:
        key = str(operand)
        if key in ctx.storage:
            ctx.push(ctx.storage[key])
        else:
            # Push zero manifold
            ctx.push(TopologicalManifold.from_seed(b"\x00" * 32))

    def _op_sstore(self, ctx: ExecutionContext, operand: Any) -> None:
        key = str(operand)
        m = ctx.pop()
        ctx.storage[key] = m

    def _op_wrap_add(self, ctx: ExecutionContext, _: Any) -> None:
        b = ctx.pop()
        a = ctx.pop()
        from forge.vortexchain.manifold import WrappingNumber
        result_wrapping = []
        for wa, wb in zip(a.wrapping_numbers, b.wrapping_numbers):
            result_wrapping.append(WrappingNumber(
                sphere_index=wa.sphere_index,
                value=(wa.value + wb.value) % 997,
            ))
        result = TopologicalManifold(
            components=a.components,  # preserve a's geometry
            wrapping_numbers=result_wrapping,
        )
        ctx.push(result)

    def _op_wrap_mul(self, ctx: ExecutionContext, _: Any) -> None:
        b = ctx.pop()
        a = ctx.pop()
        from forge.vortexchain.manifold import WrappingNumber
        result_wrapping = []
        for wa, wb in zip(a.wrapping_numbers, b.wrapping_numbers):
            result_wrapping.append(WrappingNumber(
                sphere_index=wa.sphere_index,
                value=(wa.value * wb.value) % 997,
            ))
        result = TopologicalManifold(
            components=a.components,
            wrapping_numbers=result_wrapping,
        )
        ctx.push(result)

    def _op_spectrum(self, ctx: ExecutionContext, _: Any) -> None:
        m = ctx.pop()
        ctx.return_value = m.topological_spectrum()

    def _op_topo_guard(self, ctx: ExecutionContext, operand: Any) -> None:
        """Check that the top-of-stack manifold has expected wrapping numbers.

        operand: dict mapping sphere_index → expected_value
        """
        if not isinstance(operand, dict):
            raise ContractRuntimeError("TOPO_GUARD requires {sphere_idx: value} dict")
        m = ctx.peek()
        spectrum = m.topological_spectrum()
        for idx, expected in operand.items():
            idx = int(idx)
            if idx >= len(spectrum):
                raise TopologicalGuardError(
                    f"Sphere index {idx} out of range"
                )
            if spectrum[idx] != expected:
                raise TopologicalGuardError(
                    f"Topological guard failed: sphere[{idx}] = {spectrum[idx]}, "
                    f"expected {expected}"
                )

    def _op_halt(self, ctx: ExecutionContext, _: Any) -> None:
        ctx.halted = True

    def _op_revert(self, ctx: ExecutionContext, operand: Any) -> None:
        ctx.reverted = True
        if operand:
            ctx.return_value = str(operand)

    def _op_emit(self, ctx: ExecutionContext, operand: Any) -> None:
        name = str(operand) if operand else "Event"
        m = ctx.pop()
        ctx.events.append(ContractEvent(
            name=name,
            data={
                "spectrum": m.topological_spectrum(),
                "projection_3d": m.project((0, 1, 2)),
            },
        ))

    def _op_caller(self, ctx: ExecutionContext, _: Any) -> None:
        caller_manifold = TopologicalManifold.from_seed(ctx.caller.encode())
        ctx.push(caller_manifold)


# ---------------------------------------------------------------------------
# Smart Contract
# ---------------------------------------------------------------------------

@dataclass
class QuditContract:
    """A VortexChain smart contract with qudit state encoding.

    Contracts are deployed with bytecode (list of Instructions) and
    maintain persistent storage as a mapping from keys to manifold points.
    """
    address: str                                    # vx-contract address
    creator: str                                    # deployer's vx-address
    bytecode: List[Instruction] = field(default_factory=list)
    storage: Dict[str, TopologicalManifold] = field(default_factory=dict)
    abi: Dict[str, List[Instruction]] = field(default_factory=dict)  # named functions
    deployed_at: float = field(default_factory=time.time)

    def deploy_function(self, name: str, instructions: List[Instruction]) -> None:
        """Register a named function on this contract."""
        self.abi[name] = instructions

    def call(
        self,
        function: str,
        caller: str,
        gas_limit: float = 10.0,
    ) -> ExecutionResult:
        """Call a named function on this contract."""
        if function not in self.abi:
            return ExecutionResult(
                success=False,
                gas_used=0,
                error=f"Function '{function}' not found",
            )

        instructions = self.abi[function]
        ctx = ExecutionContext(
            caller=caller,
            gas_limit=gas_limit,
            storage=self.storage,
        )

        vm = QuditVM()
        result = vm.execute(instructions, ctx)

        # Persist storage changes on success
        if result.success:
            self.storage = ctx.storage

        return result

    def execute_raw(
        self,
        instructions: List[Instruction],
        caller: str,
        gas_limit: float = 10.0,
    ) -> ExecutionResult:
        """Execute raw instructions against this contract."""
        ctx = ExecutionContext(
            caller=caller,
            gas_limit=gas_limit,
            storage=self.storage,
        )

        vm = QuditVM()
        result = vm.execute(instructions, ctx)

        if result.success:
            self.storage = ctx.storage

        return result

    @classmethod
    def create_address(cls, creator: str, nonce: int) -> str:
        """Derive a contract address from creator + nonce."""
        raw = hashlib.sha256(f"{creator}:{nonce}".encode()).hexdigest()
        return "vxc" + raw[:39]  # vxc prefix for contracts, 42 chars total
