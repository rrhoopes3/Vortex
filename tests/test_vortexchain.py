"""Tests for VortexChain: Topological OAM Cryptography Blockchain."""

import struct
import time

import pytest

from vortexchain.manifold import (
    MANIFOLD_DIM,
    NUM_EMBEDDED_SPHERES,
    TopologicalManifold,
    WrappingNumber,
)
from vortexchain.toac import TOACKeypair, TopologicalHash, TopologicalSignature
from vortexchain.chain import Block, Transaction, VortexChain
from vortexchain.consensus import (
    HybridConsensus,
    ProofOfTopology,
    TopologyChallenge,
    TopologyResponse,
)
from vortexchain.tokenomics import (
    TOTAL_SUPPLY,
    AllocationCategory,
    TokenDistribution,
    VestingSchedule,
    VortexToken,
)


# ===========================================================================
# Manifold tests
# ===========================================================================

class TestWrappingNumber:
    def test_valid_creation(self):
        wn = WrappingNumber(sphere_index=0, value=42)
        assert wn.sphere_index == 0
        assert wn.value == 42

    def test_invalid_sphere_index(self):
        with pytest.raises(ValueError):
            WrappingNumber(sphere_index=24, value=1)
        with pytest.raises(ValueError):
            WrappingNumber(sphere_index=-1, value=1)

    def test_frozen(self):
        wn = WrappingNumber(sphere_index=0, value=1)
        with pytest.raises(AttributeError):
            wn.value = 2


class TestTopologicalManifold:
    def test_from_seed_dimensions(self):
        m = TopologicalManifold.from_seed(b"test_seed")
        assert len(m.components) == MANIFOLD_DIM  # 48
        assert len(m.wrapping_numbers) == NUM_EMBEDDED_SPHERES  # 24

    def test_from_seed_deterministic(self):
        m1 = TopologicalManifold.from_seed(b"same_seed")
        m2 = TopologicalManifold.from_seed(b"same_seed")
        assert m1.components == m2.components
        assert m1.topological_spectrum() == m2.topological_spectrum()

    def test_different_seeds_different_manifolds(self):
        m1 = TopologicalManifold.from_seed(b"seed_a")
        m2 = TopologicalManifold.from_seed(b"seed_b")
        assert m1.topological_spectrum() != m2.topological_spectrum()

    def test_components_normalized(self):
        m = TopologicalManifold.from_seed(b"normalize_test")
        for c in m.components:
            assert -1.0 <= c <= 1.0  # tanh output

    def test_projection(self):
        m = TopologicalManifold.from_seed(b"proj_test")
        proj = m.project((0, 1, 2))
        assert len(proj) == 3
        assert proj == [m.components[0], m.components[1], m.components[2]]

    def test_topological_spectrum(self):
        m = TopologicalManifold.from_seed(b"spectrum_test")
        spectrum = m.topological_spectrum()
        assert len(spectrum) == NUM_EMBEDDED_SPHERES
        assert all(isinstance(v, int) for v in spectrum)

    def test_serialisation_roundtrip(self):
        m = TopologicalManifold.from_seed(b"serial_test")
        data = m.to_bytes()
        m2 = TopologicalManifold.from_bytes(data)
        assert m.components == m2.components
        assert m.topological_spectrum() == m2.topological_spectrum()

    def test_topological_distance_self_zero(self):
        m = TopologicalManifold.from_seed(b"dist_test")
        assert m.topological_distance(m) == 0

    def test_topological_distance_different(self):
        m1 = TopologicalManifold.from_seed(b"dist_a")
        m2 = TopologicalManifold.from_seed(b"dist_b")
        assert m1.topological_distance(m2) > 0


# ===========================================================================
# TOAC tests
# ===========================================================================

class TestTopologicalHash:
    def test_hash_deterministic(self):
        h1 = TopologicalHash.hash(b"hello vortex")
        h2 = TopologicalHash.hash(b"hello vortex")
        assert h1 == h2
        assert h1.hex() == h2.hex()

    def test_hash_different_data(self):
        h1 = TopologicalHash.hash(b"data_a")
        h2 = TopologicalHash.hash(b"data_b")
        assert h1 != h2

    def test_hash_digest_length(self):
        h = TopologicalHash.hash(b"length_test")
        assert len(h.digest) == 48  # 24 spheres × 2 bytes

    def test_hash_spectrum_length(self):
        h = TopologicalHash.hash(b"spectrum_test")
        assert len(h.spectrum) == NUM_EMBEDDED_SPHERES

    def test_verify(self):
        h = TopologicalHash.hash(b"verify_me")
        assert h.verify(b"verify_me")
        assert not h.verify(b"wrong_data")


class TestTOACKeypair:
    def test_generate_deterministic(self):
        kp1 = TOACKeypair.generate(seed=b"deterministic_seed" + b"\x00" * 46)
        kp2 = TOACKeypair.generate(seed=b"deterministic_seed" + b"\x00" * 46)
        assert kp1.public_spectrum == kp2.public_spectrum
        assert kp1.public_projection == kp2.public_projection

    def test_generate_random(self):
        kp1 = TOACKeypair.generate()
        kp2 = TOACKeypair.generate()
        assert kp1.address() != kp2.address()

    def test_address_format(self):
        kp = TOACKeypair.generate(seed=b"addr_test" + b"\x00" * 55)
        addr = kp.address()
        assert addr.startswith("vx")
        assert len(addr) == 42  # "vx" + 40 hex chars

    def test_public_key_bytes(self):
        kp = TOACKeypair.generate(seed=b"pub_test" + b"\x00" * 56)
        pub = kp.public_key_bytes()
        # 24 spheres × 2 bytes + 6 projection axes × 8 bytes = 48 + 48 = 96
        assert len(pub) == 96

    def test_public_projection_length(self):
        kp = TOACKeypair.generate(seed=b"proj_test" + b"\x00" * 55)
        assert len(kp.public_projection) == 6


class TestTopologicalSignature:
    def test_sign_produces_signature(self):
        kp = TOACKeypair.generate(seed=b"sign_test" + b"\x00" * 55)
        sig = TopologicalSignature.sign(kp, b"test message")
        assert len(sig.commitment) == 64
        assert len(sig.challenge_response) == 48
        assert sig.signer_address == kp.address()

    def test_sign_deterministic(self):
        kp = TOACKeypair.generate(seed=b"det_sign" + b"\x00" * 56)
        sig1 = TopologicalSignature.sign(kp, b"same message")
        sig2 = TopologicalSignature.sign(kp, b"same message")
        assert sig1.commitment == sig2.commitment

    def test_different_messages_different_signatures(self):
        kp = TOACKeypair.generate(seed=b"diff_sign" + b"\x00" * 55)
        sig1 = TopologicalSignature.sign(kp, b"message_a")
        sig2 = TopologicalSignature.sign(kp, b"message_b")
        assert sig1.commitment != sig2.commitment


# ===========================================================================
# Chain tests
# ===========================================================================

class TestTransaction:
    def test_transaction_creation(self):
        tx = Transaction(sender="vx_alice", recipient="vx_bob", amount=100.0)
        assert tx.tx_type == "transfer"
        assert tx.amount == 100.0

    def test_transaction_hash(self):
        tx = Transaction(sender="vx_alice", recipient="vx_bob", amount=100.0, timestamp=1000.0)
        h = tx.tx_hash()
        assert isinstance(h, TopologicalHash)

    def test_transaction_sign(self):
        kp = TOACKeypair.generate(seed=b"tx_sign" + b"\x00" * 57)
        tx = Transaction(sender=kp.address(), recipient="vx_bob", amount=50.0)
        tx.sign(kp)
        assert tx.signature is not None
        assert tx.signature.signer_address == kp.address()


class TestBlock:
    def test_block_seal(self):
        block = Block(
            index=1,
            transactions=[],
            previous_hash="0" * 96,
        )
        h = block.seal()
        assert block.block_hash == h
        assert len(h) == 96  # 48 bytes = 96 hex chars

    def test_block_hash_deterministic(self):
        block1 = Block(index=1, transactions=[], previous_hash="0" * 96, timestamp=1000.0)
        block2 = Block(index=1, transactions=[], previous_hash="0" * 96, timestamp=1000.0)
        assert block1.seal() == block2.seal()


class TestVortexChain:
    def test_genesis_block(self):
        chain = VortexChain()
        assert chain.height == 1
        assert chain.latest_block.index == 0
        assert chain.latest_block.validator == "vx_genesis"

    def test_add_transaction(self):
        chain = VortexChain()
        tx = Transaction(sender="vx_alice", recipient="vx_bob", amount=10.0)
        h = chain.add_transaction(tx)
        assert isinstance(h, TopologicalHash)
        assert len(chain.pending_transactions) == 1

    def test_create_block(self):
        chain = VortexChain()
        tx = Transaction(sender="vx_alice", recipient="vx_bob", amount=10.0)
        chain.add_transaction(tx)
        block = chain.create_block(validator="vx_validator_1")
        assert chain.height == 2
        assert block.index == 1
        assert len(block.transactions) == 1
        assert len(chain.pending_transactions) == 0

    def test_chain_validation(self):
        chain = VortexChain()
        for i in range(5):
            tx = Transaction(sender="vx_alice", recipient="vx_bob", amount=float(i + 1))
            chain.add_transaction(tx)
            chain.create_block(validator="vx_val")
        assert chain.validate_chain()

    def test_chain_tamper_detection(self):
        chain = VortexChain()
        tx = Transaction(sender="vx_alice", recipient="vx_bob", amount=10.0)
        chain.add_transaction(tx)
        chain.create_block(validator="vx_val")

        # Tamper with block hash
        chain.chain[1].block_hash = "f" * 96
        assert not chain.validate_chain()

    def test_validator_registration(self):
        chain = VortexChain()
        chain.register_validator("vx_val1", 1000.0)
        assert chain.get_validator_stake("vx_val1") == 1000.0
        chain.register_validator("vx_val1", 500.0)
        assert chain.get_validator_stake("vx_val1") == 1500.0


# ===========================================================================
# Consensus tests
# ===========================================================================

class TestProofOfTopology:
    def test_challenge_generation(self):
        challenge = TopologyChallenge.generate(epoch=0)
        assert len(challenge.challenge_id) == 32
        assert len(challenge.sphere_indices) == 6
        assert all(0 <= i < NUM_EMBEDDED_SPHERES for i in challenge.sphere_indices)
        # No duplicates
        assert len(set(challenge.sphere_indices)) == 6

    def test_challenge_response_verification(self):
        pot = ProofOfTopology()
        manifold = TopologicalManifold.from_seed(b"validator_seed")
        pot.register_validator("vx_val", manifold)

        challenge = TopologyChallenge.generate(epoch=0)
        response = TopologyResponse.create(challenge, manifold)

        assert pot.verify_response("vx_val", challenge, response)

    def test_wrong_response_fails(self):
        pot = ProofOfTopology()
        manifold = TopologicalManifold.from_seed(b"validator_seed")
        wrong_manifold = TopologicalManifold.from_seed(b"wrong_seed")
        pot.register_validator("vx_val", manifold)

        challenge = TopologyChallenge.generate(epoch=0)
        wrong_response = TopologyResponse.create(challenge, wrong_manifold)

        assert not pot.verify_response("vx_val", challenge, wrong_response)

    def test_unregistered_validator_fails(self):
        pot = ProofOfTopology()
        challenge = TopologyChallenge.generate(epoch=0)
        manifold = TopologicalManifold.from_seed(b"any")
        response = TopologyResponse.create(challenge, manifold)
        assert not pot.verify_response("vx_unknown", challenge, response)


class TestHybridConsensus:
    def test_register_validator(self):
        hc = HybridConsensus()
        manifold = TopologicalManifold.from_seed(b"hc_val")
        assert hc.register_validator("vx_val", 1000.0, manifold)
        assert "vx_val" in hc.validators

    def test_min_stake_enforced(self):
        hc = HybridConsensus()
        manifold = TopologicalManifold.from_seed(b"low_stake")
        assert not hc.register_validator("vx_poor", 100.0, manifold)

    def test_challenge_and_response_flow(self):
        hc = HybridConsensus()
        manifold = TopologicalManifold.from_seed(b"flow_test")
        hc.register_validator("vx_val", 5000.0, manifold)

        challenge = hc.issue_challenge("vx_val")
        assert challenge is not None

        response = TopologyResponse.create(challenge, manifold)
        assert hc.process_response("vx_val", challenge, response)
        assert hc.validators["vx_val"].challenges_passed == 1

    def test_select_proposer(self):
        hc = HybridConsensus()
        for i in range(3):
            m = TopologicalManifold.from_seed(f"proposer_{i}".encode())
            hc.register_validator(f"vx_val_{i}", 1000.0 * (i + 1), m)

        proposer = hc.select_proposer()
        assert proposer is not None
        assert proposer.startswith("vx_val_")

    def test_quantum_bonus(self):
        hc = HybridConsensus()
        m1 = TopologicalManifold.from_seed(b"classical")
        m2 = TopologicalManifold.from_seed(b"quantum")
        hc.register_validator("vx_classical", 1000.0, m1, has_quantum=False)
        hc.register_validator("vx_quantum", 1000.0, m2, has_quantum=True)

        classical_weight = hc.validators["vx_classical"].effective_weight
        quantum_weight = hc.validators["vx_quantum"].effective_weight
        assert quantum_weight == classical_weight * 1.5

    def test_advance_epoch(self):
        hc = HybridConsensus()
        assert hc.current_epoch == 0
        hc.advance_epoch()
        assert hc.current_epoch == 1


# ===========================================================================
# Tokenomics tests
# ===========================================================================

class TestTokenDistribution:
    def test_total_supply(self):
        assert TOTAL_SUPPLY == 48_000_000

    def test_allocations_sum_to_100(self):
        from vortexchain.tokenomics import ALLOCATIONS
        assert abs(sum(ALLOCATIONS.values()) - 1.0) < 1e-10

    def test_allocation_amounts(self):
        td = TokenDistribution()
        assert td.allocation_for(AllocationCategory.ECOSYSTEM) == 14_400_000
        assert td.allocation_for(AllocationCategory.STAKING_REWARDS) == 12_000_000
        assert td.allocation_for(AllocationCategory.TEAM) == 7_200_000
        assert td.allocation_for(AllocationCategory.QUANTUM_RESEARCH) == 2_400_000

    def test_distribute(self):
        td = TokenDistribution()
        assert td.distribute(AllocationCategory.ECOSYSTEM, "vx_alice", 1000.0)
        assert td.balance_of("vx_alice") == 1000.0
        assert td.distributed_for("ecosystem") == 1000.0

    def test_distribute_exceeds_cap(self):
        td = TokenDistribution()
        cap = td.allocation_for(AllocationCategory.QUANTUM_RESEARCH)
        assert td.distribute(AllocationCategory.QUANTUM_RESEARCH, "vx_lab", cap)
        assert not td.distribute(AllocationCategory.QUANTUM_RESEARCH, "vx_lab2", 1.0)

    def test_transfer(self):
        td = TokenDistribution()
        td.distribute(AllocationCategory.ECOSYSTEM, "vx_alice", 1000.0)
        assert td.transfer("vx_alice", "vx_bob", 400.0)
        assert td.balance_of("vx_alice") == 600.0
        assert td.balance_of("vx_bob") == 400.0

    def test_transfer_insufficient(self):
        td = TokenDistribution()
        td.distribute(AllocationCategory.ECOSYSTEM, "vx_alice", 100.0)
        assert not td.transfer("vx_alice", "vx_bob", 200.0)

    def test_summary(self):
        td = TokenDistribution()
        td.distribute(AllocationCategory.ECOSYSTEM, "vx_alice", 1000.0)
        summary = td.summary()
        assert summary["ecosystem"]["distributed"] == 1000.0
        assert summary["ecosystem"]["allocated"] == 14_400_000


class TestVestingSchedule:
    def test_before_cliff(self):
        vs = VestingSchedule(
            recipient="vx_team",
            total_amount=100_000,
            cliff_months=6,
            vesting_months=24,
            start_time=1000.0,
        )
        # 3 months later (before cliff)
        three_months = 1000.0 + 3 * 30 * 24 * 3600
        assert vs.vested_amount(three_months) == 0.0

    def test_after_cliff(self):
        vs = VestingSchedule(
            recipient="vx_team",
            total_amount=240_000,
            cliff_months=6,
            vesting_months=24,
            start_time=0.0,
        )
        # 12 months later (halfway through vesting)
        twelve_months = 12 * 30 * 24 * 3600
        vested = vs.vested_amount(twelve_months)
        assert 110_000 < vested < 130_000  # ~50% of total

    def test_fully_vested(self):
        vs = VestingSchedule(
            recipient="vx_team",
            total_amount=100_000,
            cliff_months=6,
            vesting_months=24,
            start_time=0.0,
        )
        far_future = 36 * 30 * 24 * 3600  # 36 months
        assert vs.vested_amount(far_future) == 100_000

    def test_claim(self):
        vs = VestingSchedule(
            recipient="vx_team",
            total_amount=100_000,
            cliff_months=0,
            vesting_months=12,
            start_time=0.0,
        )
        six_months = 6 * 30 * 24 * 3600
        claimed = vs.claim(six_months)
        assert claimed > 0
        assert vs.claimed == claimed
        # Second claim at same time should be ~0
        assert vs.claimable(six_months) == pytest.approx(0.0)


class TestVortexToken:
    def test_gas_calculation(self):
        vt = VortexToken()
        gas_1d = vt.calculate_gas(qudit_dimensions=1, complexity=1)
        gas_48d = vt.calculate_gas(qudit_dimensions=48, complexity=1)
        assert gas_48d > gas_1d

    def test_governance_weight(self):
        vt = VortexToken()
        vt.distribution.distribute(AllocationCategory.ECOSYSTEM, "vx_voter", 10_000.0)
        # Without topology score
        w0 = vt.governance_weight("vx_voter", topology_score=0.0)
        # With topology score
        w5 = vt.governance_weight("vx_voter", topology_score=5.0)
        assert w5 == w0 * 6.0  # 1 + 5.0 topology

    def test_create_vesting(self):
        vt = VortexToken()
        vs = vt.create_vesting("vx_team_member", 50_000.0)
        assert len(vt.vesting_schedules) == 1
        assert vs.total_amount == 50_000.0


# ===========================================================================
# Integration tests
# ===========================================================================

class TestVortexChainIntegration:
    def test_full_flow(self):
        """End-to-end: keygen → transaction → block → validation."""
        # Generate keypairs
        alice = TOACKeypair.generate(seed=b"alice_key" + b"\x00" * 55)
        bob = TOACKeypair.generate(seed=b"bob_key_x" + b"\x00" * 55)

        # Create chain
        chain = VortexChain()

        # Create and sign transaction
        tx = Transaction(
            sender=alice.address(),
            recipient=bob.address(),
            amount=100.0,
        )
        tx.sign(alice)
        assert tx.signature is not None

        # Add to chain
        chain.add_transaction(tx)

        # Create block
        block = chain.create_block(validator=alice.address())
        assert block.block_hash != ""
        assert chain.height == 2

        # Validate
        assert chain.validate_chain()

    def test_consensus_integrated_with_chain(self):
        """Consensus engine selects proposer, proposer creates block."""
        hc = HybridConsensus()
        chain = VortexChain()

        # Register validators
        for i in range(3):
            m = TopologicalManifold.from_seed(f"int_val_{i}".encode())
            addr = f"vx_validator_{i}"
            hc.register_validator(addr, 2000.0, m)
            chain.register_validator(addr, 2000.0)

        # Add transactions
        for i in range(5):
            tx = Transaction(sender="vx_alice", recipient="vx_bob", amount=float(i))
            chain.add_transaction(tx)

        # Select proposer and create block
        proposer = hc.select_proposer()
        assert proposer is not None
        block = chain.create_block(validator=proposer)
        assert block.validator == proposer
        assert chain.validate_chain()

    def test_tokenomics_with_chain(self):
        """Token distribution integrates with chain operations."""
        token = VortexToken()
        chain = VortexChain()

        # Distribute tokens
        alice_addr = "vx_alice_addr"
        token.distribution.distribute(AllocationCategory.ECOSYSTEM, alice_addr, 10_000.0)

        # Calculate gas for a transaction
        gas = token.calculate_gas(qudit_dimensions=7, complexity=2)
        assert gas > 0

        # Governance weight
        weight = token.governance_weight(alice_addr, topology_score=3.0)
        assert weight == 10_000.0 * 4.0  # balance * (1 + score)
