"""Tests for VortexChain extended modules: contracts, QKD, oracle, network, NFTs."""

import math
import time

import pytest

from forge.vortexchain.manifold import (
    MANIFOLD_DIM,
    NUM_EMBEDDED_SPHERES,
    TopologicalManifold,
    WrappingNumber,
)
from forge.vortexchain.toac import TOACKeypair, TopologicalHash


# ===========================================================================
# Qudit Smart Contract Runtime tests
# ===========================================================================

from forge.vortexchain.contracts import (
    ContractEvent,
    ContractRuntimeError,
    ExecutionContext,
    ExecutionResult,
    GasExhaustedError,
    Instruction,
    QuditContract,
    QuditOpcode,
    QuditVM,
    TopologicalGuardError,
)


class TestExecutionContext:
    def test_push_pop(self):
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        m = TopologicalManifold.from_seed(b"test")
        ctx.push(m)
        assert len(ctx.stack) == 1
        popped = ctx.pop()
        assert popped.topological_spectrum() == m.topological_spectrum()

    def test_pop_empty_raises(self):
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        with pytest.raises(ContractRuntimeError, match="underflow"):
            ctx.pop()

    def test_gas_exhaustion(self):
        ctx = ExecutionContext(caller="vx_alice", gas_limit=0.01)
        with pytest.raises(GasExhaustedError):
            ctx.consume_gas(0.02)

    def test_storage_operations(self):
        m = TopologicalManifold.from_seed(b"store_me")
        ctx = ExecutionContext(
            caller="vx_alice",
            gas_limit=1.0,
            storage={"key1": m},
        )
        assert "key1" in ctx.storage
        assert ctx.storage["key1"].topological_spectrum() == m.topological_spectrum()

    def test_state_changes_tracking(self):
        m1 = TopologicalManifold.from_seed(b"original")
        ctx = ExecutionContext(
            caller="vx_alice",
            gas_limit=1.0,
            storage={"slot": m1},
        )
        # Modify storage
        m2 = TopologicalManifold.from_seed(b"modified")
        ctx.storage["slot"] = m2
        changes = ctx.state_changes
        assert "slot" in changes


class TestQuditVM:
    def setup_method(self):
        self.vm = QuditVM()

    def test_push_and_halt(self):
        m = TopologicalManifold.from_seed(b"push_test")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success
        assert len(ctx.stack) == 1

    def test_push_from_seed(self):
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, b"seed_bytes"),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success

    def test_dup(self):
        m = TopologicalManifold.from_seed(b"dup_test")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.DUP),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success
        assert len(ctx.stack) == 2

    def test_swap(self):
        m1 = TopologicalManifold.from_seed(b"swap_a")
        m2 = TopologicalManifold.from_seed(b"swap_b")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m1),
            Instruction(QuditOpcode.PUSH_MANIFOLD, m2),
            Instruction(QuditOpcode.SWAP),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        self.vm.execute(instructions, ctx)
        # After swap, m1 should be on top
        assert ctx.stack[-1].topological_spectrum() == m1.topological_spectrum()

    def test_distance(self):
        m1 = TopologicalManifold.from_seed(b"dist_a")
        m2 = TopologicalManifold.from_seed(b"dist_b")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m1),
            Instruction(QuditOpcode.PUSH_MANIFOLD, m2),
            Instruction(QuditOpcode.DISTANCE),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success
        assert result.return_data > 0

    def test_merge(self):
        m1 = TopologicalManifold.from_seed(b"merge_a")
        m2 = TopologicalManifold.from_seed(b"merge_b")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m1),
            Instruction(QuditOpcode.PUSH_MANIFOLD, m2),
            Instruction(QuditOpcode.MERGE),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success
        assert len(ctx.stack) == 1
        merged = ctx.stack[0]
        # Merged components should be average
        for i in range(MANIFOLD_DIM):
            expected = (m1.components[i] + m2.components[i]) / 2.0
            assert abs(merged.components[i] - expected) < 1e-10

    def test_sstore_sload(self):
        m = TopologicalManifold.from_seed(b"storage_test")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.SSTORE, "my_slot"),
            Instruction(QuditOpcode.SLOAD, "my_slot"),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success
        assert len(ctx.stack) == 1
        assert ctx.stack[0].topological_spectrum() == m.topological_spectrum()

    def test_spectrum(self):
        m = TopologicalManifold.from_seed(b"spectrum_op_test")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.SPECTRUM),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success
        assert result.return_data == m.topological_spectrum()

    def test_hash_op(self):
        m = TopologicalManifold.from_seed(b"hash_op_test")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.HASH),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success
        assert isinstance(result.return_data, TopologicalHash)

    def test_topo_guard_pass(self):
        m = TopologicalManifold.from_seed(b"guard_test")
        spectrum = m.topological_spectrum()
        guard = {0: spectrum[0], 1: spectrum[1]}
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.TOPO_GUARD, guard),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success

    def test_topo_guard_fail(self):
        m = TopologicalManifold.from_seed(b"guard_fail")
        guard = {0: 99999}  # wrong value
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.TOPO_GUARD, guard),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert not result.success
        assert "guard failed" in result.error.lower() or "guard" in result.error.lower()

    def test_emit_event(self):
        m = TopologicalManifold.from_seed(b"emit_test")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.EMIT, "Transfer"),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success
        assert len(result.events) == 1
        assert result.events[0].name == "Transfer"

    def test_revert(self):
        instructions = [
            Instruction(QuditOpcode.REVERT, "intentional revert"),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert not result.success
        assert "reverted" in result.error.lower()

    def test_gas_exhaustion(self):
        m = TopologicalManifold.from_seed(b"gas_test")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.SSTORE, "slot"),
        ] * 100  # lots of expensive operations
        ctx = ExecutionContext(caller="vx_alice", gas_limit=0.01)
        result = self.vm.execute(instructions, ctx)
        assert not result.success
        assert "gas" in result.error.lower()

    def test_wrap_add(self):
        m1 = TopologicalManifold.from_seed(b"wrap_add_a")
        m2 = TopologicalManifold.from_seed(b"wrap_add_b")
        instructions = [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m1),
            Instruction(QuditOpcode.PUSH_MANIFOLD, m2),
            Instruction(QuditOpcode.WRAP_ADD),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_alice", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success
        # Verify wrapping numbers are added mod 997
        result_spectrum = ctx.stack[0].topological_spectrum()
        for i in range(NUM_EMBEDDED_SPHERES):
            expected = (m1.topological_spectrum()[i] + m2.topological_spectrum()[i]) % 997
            assert result_spectrum[i] == expected

    def test_caller_op(self):
        instructions = [
            Instruction(QuditOpcode.CALLER),
            Instruction(QuditOpcode.HALT),
        ]
        ctx = ExecutionContext(caller="vx_test_caller", gas_limit=1.0)
        result = self.vm.execute(instructions, ctx)
        assert result.success
        assert len(ctx.stack) == 1


class TestQuditContract:
    def test_create_contract(self):
        contract = QuditContract(
            address=QuditContract.create_address("vx_deployer", 0),
            creator="vx_deployer",
        )
        assert contract.address.startswith("vxc")
        assert len(contract.address) == 42

    def test_deploy_and_call_function(self):
        contract = QuditContract(
            address="vxc_test",
            creator="vx_deployer",
        )
        m = TopologicalManifold.from_seed(b"init_value")
        contract.deploy_function("initialize", [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.SSTORE, "state"),
            Instruction(QuditOpcode.HALT),
        ])
        result = contract.call("initialize", "vx_deployer")
        assert result.success
        assert "state" in contract.storage

    def test_call_nonexistent_function(self):
        contract = QuditContract(address="vxc_test", creator="vx_deployer")
        result = contract.call("nonexistent", "vx_caller")
        assert not result.success
        assert "not found" in result.error

    def test_storage_persistence(self):
        contract = QuditContract(address="vxc_test", creator="vx_deployer")
        m = TopologicalManifold.from_seed(b"persistent")

        # Store
        contract.deploy_function("store", [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.SSTORE, "data"),
            Instruction(QuditOpcode.HALT),
        ])
        contract.call("store", "vx_user")

        # Load
        contract.deploy_function("load", [
            Instruction(QuditOpcode.SLOAD, "data"),
            Instruction(QuditOpcode.SPECTRUM),
            Instruction(QuditOpcode.HALT),
        ])
        result = contract.call("load", "vx_user")
        assert result.success
        assert result.return_data == m.topological_spectrum()

    def test_revert_doesnt_persist_storage(self):
        contract = QuditContract(address="vxc_test", creator="vx_deployer")
        m = TopologicalManifold.from_seed(b"revert_test")

        contract.deploy_function("bad_store", [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.SSTORE, "data"),
            Instruction(QuditOpcode.REVERT, "nope"),
        ])
        result = contract.call("bad_store", "vx_user")
        assert not result.success
        assert "data" not in contract.storage


# ===========================================================================
# TopoQKD tests
# ===========================================================================

from forge.vortexchain.qkd import (
    ALL_BASES,
    ChannelParameters,
    EntangledOAMPair,
    OAMMeasurementBasis,
    QKDSession,
    TopoQKDNode,
)


class TestChannelParameters:
    def test_transmission(self):
        ch = ChannelParameters(loss_db_per_km=0.2, distance_km=10)
        assert 0 < ch.transmission < 1

    def test_effective_rate(self):
        ch = ChannelParameters()
        rate = ch.effective_rate
        assert rate > 0
        # Should be proportional to log2(48) * transmission * efficiency
        assert rate <= math.log2(MANIFOLD_DIM)

    def test_qber(self):
        ch = ChannelParameters(topological_fidelity=0.998)
        qber = ch.quantum_bit_error_rate
        assert 0 < qber < 0.5

    def test_longer_distance_lower_transmission(self):
        short = ChannelParameters(distance_km=1)
        long = ChannelParameters(distance_km=100)
        assert short.transmission > long.transmission


class TestEntangledOAMPair:
    def test_generate(self):
        pair = EntangledOAMPair.generate(b"test_entropy")
        assert len(pair.pair_id) == 32
        assert pair.shared_manifold is not None

    def test_measure_alice(self):
        pair = EntangledOAMPair.generate(b"measure_test")
        result = pair.measure_alice(OAMMeasurementBasis.CANONICAL)
        assert len(result) == NUM_EMBEDDED_SPHERES
        assert pair.alice_basis == OAMMeasurementBasis.CANONICAL

    def test_matching_bases_yield_matching_results(self):
        pair = EntangledOAMPair.generate(b"match_test")
        basis = OAMMeasurementBasis.VORTEX
        alice_result = pair.measure_alice(basis)
        bob_result = pair.measure_bob(basis)
        assert pair.bases_match
        assert pair.results_match
        assert alice_result == bob_result

    def test_different_bases(self):
        pair = EntangledOAMPair.generate(b"diff_basis")
        pair.measure_alice(OAMMeasurementBasis.CANONICAL)
        pair.measure_bob(OAMMeasurementBasis.PETAL)
        assert not pair.bases_match


class TestQKDSession:
    def test_create_session(self):
        session = QKDSession.create("node_alice", "node_bob")
        assert session.alice_node == "node_alice"
        assert session.bob_node == "node_bob"

    def test_generate_pairs(self):
        session = QKDSession.create("alice", "bob")
        count = session.generate_pairs(100)
        assert count == 100
        assert len(session.pairs) == 100

    def test_measure_all(self):
        session = QKDSession.create("alice", "bob")
        session.generate_pairs(100)
        total, matching = session.measure_all()
        assert total == 100
        assert 0 < matching <= 100  # some should match

    def test_sift_keys(self):
        session = QKDSession.create("alice", "bob")
        session.generate_pairs(500)
        session.measure_all()
        sifted = session.sift_keys()
        assert sifted > 0

    def test_full_protocol(self):
        session = QKDSession.create("alice", "bob")
        key = session.run_full_protocol(num_pairs=500, target_key_bytes=32)
        assert key is not None
        assert len(key) == 32
        assert session.completed

    def test_key_rate(self):
        session = QKDSession.create("alice", "bob")
        session.run_full_protocol(500)
        assert session.key_rate_bits_per_pair > 0

    def test_security_parameter(self):
        session = QKDSession.create("alice", "bob")
        session.run_full_protocol(500)
        assert session.security_parameter > 0


class TestTopoQKDNode:
    def test_create_node(self):
        node = TopoQKDNode("node_1")
        assert node.node_id == "node_1"
        assert not node.has_quantum_hardware

    def test_establish_key(self):
        node = TopoQKDNode("node_1")
        key = node.establish_key("node_2", num_pairs=200)
        assert key is not None
        assert len(key) == 32
        assert "node_2" in node.connected_peers

    def test_get_shared_key(self):
        node = TopoQKDNode("node_1")
        node.establish_key("node_2", num_pairs=200)
        key = node.get_shared_key("node_2")
        assert key is not None

    def test_refresh_key(self):
        node = TopoQKDNode("node_1")
        key1 = node.establish_key("node_2", num_pairs=200)
        key2 = node.refresh_key("node_2")
        assert key1 is not None
        assert key2 is not None
        # Keys should differ (different random entropy each time)
        assert key1 != key2


# ===========================================================================
# Quantum Entropy Oracle tests
# ===========================================================================

from forge.vortexchain.oracle import (
    EntropyAggregator,
    EntropyCommitment,
    EntropyRequest,
    EntropyReveal,
    OAMEntropySource,
    OracleNode,
)


class TestOAMEntropySource:
    def test_measure(self):
        source = OAMEntropySource(b"device_seed")
        entropy, proof = source.measure(32)
        assert len(entropy) == 32
        assert len(proof) == NUM_EMBEDDED_SPHERES

    def test_different_measurements(self):
        source = OAMEntropySource(b"device_seed")
        e1, _ = source.measure(32)
        e2, _ = source.measure(32)
        assert e1 != e2  # each measurement should be different
        assert source.measurement_count == 2


class TestOracleNode:
    def test_commit_and_reveal(self):
        oracle = OracleNode(address="vx_oracle_1", stake=5000.0)
        request = EntropyRequest.create("vx_requester", num_bytes=32)

        commitment = oracle.commit_entropy(request)
        assert commitment.oracle_address == "vx_oracle_1"

        reveal = oracle.reveal_entropy(request.request_id)
        assert reveal is not None
        assert reveal.verify_commitment(commitment)

    def test_reveal_wrong_request(self):
        oracle = OracleNode(address="vx_oracle_1", stake=5000.0)
        request = EntropyRequest.create("vx_requester")
        oracle.commit_entropy(request)

        reveal = oracle.reveal_entropy(b"wrong_id")
        assert reveal is None


class TestEntropyAggregator:
    def test_full_round(self):
        agg = EntropyAggregator()

        # Register 3 oracles
        for i in range(3):
            agg.register_oracle(OracleNode(
                address=f"vx_oracle_{i}",
                stake=5000.0,
            ))

        request = EntropyRequest.create("vx_requester", num_bytes=32, min_oracles=3)
        result = agg.run_full_round(request)

        assert result is not None
        assert len(result) == 32

    def test_insufficient_oracles(self):
        agg = EntropyAggregator()
        agg.register_oracle(OracleNode(address="vx_oracle_0", stake=5000.0))

        request = EntropyRequest.create("vx_requester", min_oracles=3)
        result = agg.run_full_round(request)
        assert result is None  # not enough oracles

    def test_commitment_verification(self):
        agg = EntropyAggregator()
        for i in range(3):
            agg.register_oracle(OracleNode(address=f"vx_o_{i}", stake=5000.0))

        request = EntropyRequest.create("vx_req", min_oracles=3)
        agg.request_entropy(request)

        # Commit phase
        for oracle in agg.oracles.values():
            commitment = oracle.commit_entropy(request)
            assert agg.submit_commitment(commitment)

        # Reveal phase
        for oracle in agg.oracles.values():
            reveal = oracle.reveal_entropy(request.request_id)
            assert reveal is not None
            assert agg.submit_reveal(reveal)

        result = agg.finalize(request.request_id)
        assert result is not None

    def test_oracle_reputation_increases(self):
        agg = EntropyAggregator()
        oracle = OracleNode(address="vx_good_oracle", stake=5000.0)
        agg.register_oracle(oracle)
        initial_rep = oracle.reputation

        # Add more oracles to meet min
        for i in range(2):
            agg.register_oracle(OracleNode(address=f"vx_o_{i}", stake=5000.0))

        request = EntropyRequest.create("vx_req", min_oracles=3)
        agg.run_full_round(request)

        assert oracle.reputation > initial_rep


# ===========================================================================
# P2P Network tests
# ===========================================================================

from forge.vortexchain.network import (
    MessageType,
    NetworkMessage,
    PeerInfo,
    VortexNetwork,
    VortexNode,
)


class TestNetworkMessage:
    def test_create_message(self):
        msg = NetworkMessage(
            msg_type=MessageType.BLOCK_ANNOUNCE,
            sender="node_1",
            payload={"block_hash": "abc123"},
        )
        assert msg.ttl == 10
        assert msg.hop_count == 0
        assert msg.should_relay()

    def test_relay_increments_hop(self):
        msg = NetworkMessage(
            msg_type=MessageType.TX_BROADCAST,
            sender="node_1",
            payload={},
        )
        relayed = msg.relay()
        assert relayed.hop_count == 1
        assert relayed.msg_id == msg.msg_id

    def test_ttl_limit(self):
        msg = NetworkMessage(
            msg_type=MessageType.PING,
            sender="node_1",
            payload={},
            ttl=1,
            hop_count=1,
        )
        assert not msg.should_relay()


class TestPeerInfo:
    def test_is_active(self):
        peer = PeerInfo(
            node_id="node_1",
            address="sim://node_1",
            vx_address="vx_node_1",
        )
        assert peer.is_active  # just created

    def test_update_seen(self):
        peer = PeerInfo(
            node_id="node_1",
            address="sim://node_1",
            vx_address="vx_node_1",
            last_seen=0,  # very old
        )
        assert not peer.is_active
        peer.update_seen()
        assert peer.is_active


class TestVortexNode:
    def test_create_node(self):
        node = VortexNode(
            node_id="node_1",
            vx_address="vx_addr_1",
            is_validator=True,
        )
        assert node.node_id == "node_1"
        assert node.is_validator

    def test_add_peer(self):
        node = VortexNode("node_1", "vx_1")
        peer = PeerInfo("node_2", "sim://node_2", "vx_2")
        assert node.add_peer(peer)
        assert node.peer_count == 1

    def test_cant_add_self(self):
        node = VortexNode("node_1", "vx_1")
        peer = PeerInfo("node_1", "sim://node_1", "vx_1")
        assert not node.add_peer(peer)

    def test_ban_peer(self):
        node = VortexNode("node_1", "vx_1")
        peer = PeerInfo("node_2", "sim://node_2", "vx_2")
        node.add_peer(peer)
        node.ban_peer("node_2")
        assert node.peer_count == 0
        # Can't re-add banned peer
        assert not node.add_peer(peer)

    def test_message_handler(self):
        node = VortexNode("node_1", "vx_1")
        received = []
        node.register_handler(MessageType.PING, lambda m: received.append(m))

        msg = NetworkMessage(
            msg_type=MessageType.PING,
            sender="node_2",
            payload={},
        )
        node.receive_message(msg)
        assert len(received) == 1

    def test_dedup_messages(self):
        node = VortexNode("node_1", "vx_1")
        received = []
        node.register_handler(MessageType.PING, lambda m: received.append(m))

        msg = NetworkMessage(
            msg_type=MessageType.PING,
            sender="node_2",
            payload={},
        )
        node.receive_message(msg)
        node.receive_message(msg)  # duplicate
        assert len(received) == 1  # only processed once


class TestVortexNetwork:
    def test_add_nodes(self):
        net = VortexNetwork()
        n1 = VortexNode("n1", "vx_1")
        n2 = VortexNode("n2", "vx_2")
        net.add_node(n1)
        net.add_node(n2)
        assert net.node_count == 2
        # Nodes should know about each other
        assert n1.peer_count == 1
        assert n2.peer_count == 1

    def test_broadcast(self):
        net = VortexNetwork()
        nodes = []
        for i in range(5):
            n = VortexNode(f"n{i}", f"vx_{i}")
            net.add_node(n)
            nodes.append(n)

        received = []
        for n in nodes[1:]:
            n.register_handler(MessageType.BLOCK_ANNOUNCE, lambda m: received.append(m))

        nodes[0].broadcast(MessageType.BLOCK_ANNOUNCE, {"block": 1})
        assert len(received) >= 4  # all others should receive

    def test_send_to_specific(self):
        net = VortexNetwork()
        n1 = VortexNode("n1", "vx_1")
        n2 = VortexNode("n2", "vx_2")
        n3 = VortexNode("n3", "vx_3")
        net.add_node(n1)
        net.add_node(n2)
        net.add_node(n3)

        received_n2 = []
        received_n3 = []
        n2.register_handler(MessageType.PING, lambda m: received_n2.append(m))
        n3.register_handler(MessageType.PING, lambda m: received_n3.append(m))

        n1.send_to("n2", MessageType.PING, {"hello": True})
        assert len(received_n2) == 1
        # n3 might receive via gossip relay, but the direct message went to n2

    def test_remove_node(self):
        net = VortexNetwork()
        n1 = VortexNode("n1", "vx_1")
        n2 = VortexNode("n2", "vx_2")
        net.add_node(n1)
        net.add_node(n2)
        net.remove_node("n2")
        assert net.node_count == 1
        assert n1.peer_count == 0

    def test_network_stats(self):
        net = VortexNetwork()
        net.add_node(VortexNode("n1", "vx_1", is_validator=True))
        net.add_node(VortexNode("n2", "vx_2", has_quantum=True))
        net.add_node(VortexNode("n3", "vx_3"))

        stats = net.network_stats()
        assert stats["total_nodes"] == 3
        assert stats["validators"] == 1
        assert stats["quantum_nodes"] == 1


# ===========================================================================
# Topological NFT tests
# ===========================================================================

from forge.vortexchain.nft import (
    TopoNFT,
    TopoNFTCollection,
    TopoNFTState,
    TopologicalFingerprint,
    fuse_nfts,
)


class TestTopologicalFingerprint:
    def test_from_manifold(self):
        m = TopologicalManifold.from_seed(b"fp_test")
        fp = TopologicalFingerprint.from_manifold(m)
        assert len(fp.spectrum) == NUM_EMBEDDED_SPHERES
        assert len(fp.projection_6d) == 6
        assert fp.dimension == MANIFOLD_DIM

    def test_similarity_self(self):
        m = TopologicalManifold.from_seed(b"sim_self")
        fp = TopologicalFingerprint.from_manifold(m)
        assert fp.similarity(fp) == 1.0

    def test_similarity_different(self):
        fp1 = TopologicalFingerprint.from_manifold(TopologicalManifold.from_seed(b"a"))
        fp2 = TopologicalFingerprint.from_manifold(TopologicalManifold.from_seed(b"b"))
        sim = fp1.similarity(fp2)
        assert 0.0 <= sim < 1.0

    def test_rarity(self):
        m = TopologicalManifold.from_seed(b"rarity_test")
        fp = TopologicalFingerprint.from_manifold(m)
        rarity = fp.topological_rarity()
        assert 0.0 <= rarity <= 1.0


class TestTopoNFT:
    def test_mint(self):
        nft = TopoNFT.mint("vx_creator", seed=b"mint_test_seed_64bytes" + b"\x00" * 42)
        assert nft.token_id.startswith("vxnft_")
        assert nft.owner == "vx_creator"
        assert nft.state == TopoNFTState.ACTIVE
        assert nft.fingerprint is not None

    def test_transfer(self):
        nft = TopoNFT.mint("vx_alice", seed=b"transfer_nft" + b"\x00" * 52)
        assert nft.transfer("vx_bob")
        assert nft.owner == "vx_bob"
        assert len(nft.transfer_history) == 1

    def test_transfer_frozen_fails(self):
        nft = TopoNFT.mint("vx_alice", seed=b"freeze_test" + b"\x00" * 53)
        nft.freeze()
        assert not nft.transfer("vx_bob")

    def test_freeze_unfreeze(self):
        nft = TopoNFT.mint("vx_alice", seed=b"fu_test" + b"\x00" * 57)
        assert nft.freeze()
        assert nft.state == TopoNFTState.FROZEN
        assert nft.unfreeze()
        assert nft.state == TopoNFTState.ACTIVE

    def test_burn(self):
        nft = TopoNFT.mint("vx_alice", seed=b"burn_test" + b"\x00" * 55)
        assert nft.burn()
        assert nft.state == TopoNFTState.BURNED
        assert not nft.burn()  # can't burn twice

    def test_rarity_score(self):
        nft = TopoNFT.mint("vx_alice", seed=b"rarity_nft" + b"\x00" * 54)
        assert 0.0 <= nft.rarity_score <= 1.0

    def test_verify_topology(self):
        nft = TopoNFT.mint("vx_alice", seed=b"verify_topo" + b"\x00" * 53)
        manifold_bytes = nft.manifold.to_bytes()
        assert nft.verify_topology(manifold_bytes)

        # Wrong manifold should fail
        wrong = TopologicalManifold.from_seed(b"wrong_manifold")
        assert not nft.verify_topology(wrong.to_bytes())


class TestNFTFusion:
    def test_fuse_nfts(self):
        nft_a = TopoNFT.mint("vx_owner", seed=b"fuse_a" + b"\x00" * 58)
        nft_b = TopoNFT.mint("vx_owner", seed=b"fuse_b" + b"\x00" * 58)

        child = fuse_nfts(nft_a, nft_b, "vx_owner")
        assert child is not None
        assert child.owner == "vx_owner"
        assert nft_a.state == TopoNFTState.FUSED
        assert nft_b.state == TopoNFTState.FUSED
        assert len(child.parent_tokens) == 2

    def test_fuse_different_owners_fails(self):
        nft_a = TopoNFT.mint("vx_alice", seed=b"fuse_a2" + b"\x00" * 57)
        nft_b = TopoNFT.mint("vx_bob", seed=b"fuse_b2" + b"\x00" * 57)

        child = fuse_nfts(nft_a, nft_b, "vx_alice")
        assert child is None

    def test_fuse_burned_fails(self):
        nft_a = TopoNFT.mint("vx_owner", seed=b"fuse_a3" + b"\x00" * 57)
        nft_b = TopoNFT.mint("vx_owner", seed=b"fuse_b3" + b"\x00" * 57)
        nft_a.burn()

        child = fuse_nfts(nft_a, nft_b, "vx_owner")
        assert child is None

    def test_fused_nft_has_unique_fingerprint(self):
        nft_a = TopoNFT.mint("vx_owner", seed=b"uniq_a" + b"\x00" * 58)
        nft_b = TopoNFT.mint("vx_owner", seed=b"uniq_b" + b"\x00" * 58)

        child = fuse_nfts(nft_a, nft_b, "vx_owner")
        assert child is not None
        # Child fingerprint should differ from both parents
        assert child.fingerprint.spectrum != nft_a.fingerprint.spectrum
        assert child.fingerprint.spectrum != nft_b.fingerprint.spectrum


class TestTopoNFTCollection:
    def test_create_collection(self):
        col = TopoNFTCollection("VortexArt", "VXART")
        assert col.name == "VortexArt"
        assert col.symbol == "VXART"

    def test_mint_in_collection(self):
        col = TopoNFTCollection("VortexArt", "VXART")
        nft = col.mint("vx_creator", seed=b"col_mint" + b"\x00" * 56)
        assert nft.token_id in col.tokens
        assert col.total_minted == 1

    def test_transfer_in_collection(self):
        col = TopoNFTCollection("VortexArt", "VXART")
        nft = col.mint("vx_alice", seed=b"col_transfer" + b"\x00" * 52)
        assert col.transfer(nft.token_id, "vx_alice", "vx_bob")
        assert col.tokens[nft.token_id].owner == "vx_bob"

    def test_burn_in_collection(self):
        col = TopoNFTCollection("VortexArt", "VXART")
        nft = col.mint("vx_alice", seed=b"col_burn" + b"\x00" * 56)
        assert col.burn(nft.token_id, "vx_alice")
        assert col.total_burned == 1

    def test_fuse_in_collection(self):
        col = TopoNFTCollection("VortexArt", "VXART")
        nft_a = col.mint("vx_alice", seed=b"col_fuse_a" + b"\x00" * 54)
        nft_b = col.mint("vx_alice", seed=b"col_fuse_b" + b"\x00" * 54)

        child = col.fuse(nft_a.token_id, nft_b.token_id, "vx_alice")
        assert child is not None
        assert col.total_minted == 3  # 2 parents + 1 child

    def test_find_similar(self):
        col = TopoNFTCollection("VortexArt", "VXART")
        for i in range(10):
            col.mint("vx_creator", seed=f"sim_search_{i}".encode() + b"\x00" * 50)

        first_id = list(col.tokens.keys())[0]
        similar = col.find_similar(first_id, top_k=3)
        assert len(similar) <= 3
        for tid, score in similar:
            assert 0.0 <= score <= 1.0

    def test_tokens_of_owner(self):
        col = TopoNFTCollection("VortexArt", "VXART")
        col.mint("vx_alice", seed=b"owner_a" + b"\x00" * 57)
        col.mint("vx_alice", seed=b"owner_b" + b"\x00" * 57)
        col.mint("vx_bob", seed=b"owner_c" + b"\x00" * 57)

        alice_tokens = col.tokens_of("vx_alice")
        assert len(alice_tokens) == 2

    def test_collection_stats(self):
        col = TopoNFTCollection("VortexArt", "VXART")
        for i in range(5):
            col.mint("vx_creator", seed=f"stats_{i}".encode() + b"\x00" * 55)

        stats = col.collection_stats()
        assert stats["total_minted"] == 5
        assert stats["active_supply"] == 5
        assert stats["unique_owners"] == 1


# ===========================================================================
# Full integration test
# ===========================================================================

class TestFullStackIntegration:
    def test_end_to_end_vortexchain_flow(self):
        """Complete flow: keygen → deploy contract → mint NFT → QKD → oracle."""

        # 1. Generate keypairs
        alice = TOACKeypair.generate(seed=b"alice_full_test" + b"\x00" * 49)
        bob = TOACKeypair.generate(seed=b"bob_full_test_x" + b"\x00" * 49)

        # 2. Set up network
        network = VortexNetwork()
        node_a = VortexNode("node_a", alice.address(), is_validator=True)
        node_b = VortexNode("node_b", bob.address(), is_validator=True)
        network.add_node(node_a)
        network.add_node(node_b)
        assert network.node_count == 2

        # 3. Deploy a contract
        contract = QuditContract(
            address=QuditContract.create_address(alice.address(), 0),
            creator=alice.address(),
        )
        m = TopologicalManifold.from_seed(b"contract_state")
        contract.deploy_function("init", [
            Instruction(QuditOpcode.PUSH_MANIFOLD, m),
            Instruction(QuditOpcode.SSTORE, "state"),
            Instruction(QuditOpcode.HALT),
        ])
        result = contract.call("init", alice.address())
        assert result.success

        # 4. Mint an NFT
        nft = TopoNFT.mint(alice.address(), seed=b"integration_nft" + b"\x00" * 49)
        assert nft.fingerprint is not None

        # 5. Transfer NFT
        assert nft.transfer(bob.address())
        assert nft.owner == bob.address()

        # 6. Establish QKD key
        qkd_node = TopoQKDNode(node_a.node_id)
        key = qkd_node.establish_key(node_b.node_id, num_pairs=200)
        assert key is not None

        # 7. Request oracle entropy
        agg = EntropyAggregator()
        for i in range(3):
            agg.register_oracle(OracleNode(address=f"oracle_{i}", stake=5000.0))

        request = EntropyRequest.create(alice.address(), num_bytes=32)
        entropy = agg.run_full_round(request)
        assert entropy is not None
        assert len(entropy) == 32

        # 8. Broadcast block
        node_a.broadcast(MessageType.BLOCK_ANNOUNCE, {
            "block_hash": TopologicalHash.hash(entropy).hex(),
        })
        assert node_a.messages_sent == 1
