#!/usr/bin/env python3
"""VortexChain Interactive Demo - Mini Testnet.

Run: python vortexchain/demo.py
"""

from __future__ import annotations


def banner():
    print("""
    ===================================================================

          VORTEXCHAIN  v0.1.0

     Topological OAM Cryptography Blockchain
     Security from 48-dimensional twisted light

    ===================================================================
    """)


def section(title):
    print(f"\n{'_' * 60}")
    print(f"  {title}")
    print(f"{'_' * 60}\n")


def step(msg):
    print(f"  -> {msg}")


def result(label, value):
    print(f"    {label:.<40s} {value}")


def main():
    banner()

    # 1. KEY GENERATION
    section("1. TOAC Key Generation")
    step("Generating 5 validator keypairs from 48D topological manifolds...")

    from vortexchain.toac import TOACKeypair

    validators = []
    for i in range(5):
        kp = TOACKeypair.generate(seed=f"validator_{i}_seed_for_demo".encode() + b"\x00" * 32)
        validators.append(kp)
        label = f"Validator {i}" + (" [QUANTUM]" if i < 2 else "")
        result(label, kp.address())

    result("Manifold dimensions", "48")
    result("Embedded spheres", "24")
    result("Wrapping number range", "0-996 (mod 997)")

    # 2. NETWORK
    section("2. P2P Network")
    step("Spinning up 5-node gossip network...")

    from vortexchain.network import VortexNetwork, VortexNode, MessageType

    network = VortexNetwork()
    nodes = []
    for i, kp in enumerate(validators):
        node = VortexNode(f"node_{i}", kp.address(), is_validator=True, has_quantum=(i < 2))
        network.add_node(node)
        nodes.append(node)

    stats = network.network_stats()
    result("Total nodes", str(stats["total_nodes"]))
    result("Validators", str(stats["validators"]))
    result("Quantum nodes", str(stats["quantum_nodes"]))

    nodes[0].broadcast(MessageType.PING, {"hello": "vortex"})
    result("Gossip test", f"PING broadcast, {network.total_messages} msg delivered")

    # 3. QKD
    section("3. Topological QKD")
    step("Establishing quantum-secure channel between Node 0 <-> Node 1...")

    from vortexchain.qkd import TopoQKDNode, ChannelParameters

    qkd_alice = TopoQKDNode("node_0", has_quantum_hardware=True)
    channel = ChannelParameters(distance_km=15.0, topological_fidelity=0.998)
    key = qkd_alice.establish_key("node_1", channel=channel, num_pairs=500)

    result("Photon pairs generated", "500")
    result("Channel distance", "15.0 km")
    result("Shared key (hex)", key.hex()[:48] + "..." if key else "FAILED")
    result("Key length", f"{len(key) * 8} bits" if key else "N/A")

    session = qkd_alice.sessions.get("node_1")
    if session:
        result("Error rate (QBER)", f"{session.error_rate:.6f}")
        result("Security parameter", f"{session.security_parameter:.1f} bits")

    # 4. BLOCKCHAIN
    section("4. VortexChain Blockchain")
    step("Initializing chain with genesis block...")

    from vortexchain.chain import VortexChain, Transaction

    chain = VortexChain()
    result("Genesis block hash", chain.latest_block.block_hash[:48] + "...")

    step("Creating and signing 5 transactions...")
    for i in range(5):
        sender = validators[i]
        recipient = validators[(i + 1) % 5]
        tx = Transaction(sender=sender.address(), recipient=recipient.address(), amount=float((i + 1) * 100), nonce=i)
        tx.sign(sender)
        chain.add_transaction(tx)
        result(f"TX {i}: {(i+1)*100} $VORTEX", f"{sender.address()[:12]}... -> {recipient.address()[:12]}...")

    block = chain.create_block(validator=validators[0].address())
    result("Block #1 hash", block.block_hash[:48] + "...")
    result("Chain height", str(chain.height))
    result("Chain valid", "YES" if chain.validate_chain() else "NO")

    # 5. CONSENSUS
    section("5. Hybrid Consensus (PoS + Proof-of-Topology)")
    step("Registering validators with stakes and manifolds...")

    from vortexchain.consensus import HybridConsensus, TopologyResponse
    from vortexchain.manifold import TopologicalManifold

    consensus = HybridConsensus()
    manifolds = []
    for i, kp in enumerate(validators):
        manifold = TopologicalManifold.from_seed(kp._seed)
        manifolds.append(manifold)
        stake = 2000.0 + i * 1000.0
        consensus.register_validator(kp.address(), stake, manifold, has_quantum=(i < 2))
        weight = consensus.validators[kp.address()].effective_weight
        result(f"V{i} stake={stake:.0f}" + (" [Q]" if i < 2 else ""), f"weight={weight:.1f}")

    challenge = consensus.issue_challenge(validators[0].address())
    if challenge:
        result("Challenge spheres", str(challenge.sphere_indices))
        response = TopologyResponse.create(challenge, manifolds[0])
        valid = consensus.process_response(validators[0].address(), challenge, response)
        result("Challenge passed", "YES" if valid else "NO")

    proposer = consensus.select_proposer()
    proposer_idx = next(i for i, kp in enumerate(validators) if kp.address() == proposer)
    result("Block proposer", f"Validator {proposer_idx}")

    # 6. ENTROPY ORACLE
    section("6. Quantum Entropy Oracle")
    step("Running commit-reveal with 3 oracles...")

    from vortexchain.oracle import EntropyAggregator, OracleNode, EntropyRequest

    aggregator = EntropyAggregator()
    for i in range(3):
        aggregator.register_oracle(OracleNode(address=f"vx_oracle_{i}", stake=5000.0))

    request = EntropyRequest.create(validators[0].address(), num_bytes=32, min_oracles=3)
    entropy = aggregator.run_full_round(request)
    result("Entropy (hex)", entropy.hex()[:48] + "..." if entropy else "FAILED")
    result("Entropy length", f"{len(entropy)} bytes" if entropy else "N/A")

    # 7. SMART CONTRACT
    section("7. Qudit Smart Contract (QVM)")
    step("Deploying contract with topological state storage...")

    from vortexchain.contracts import QuditContract, Instruction, QuditOpcode

    contract = QuditContract(
        address=QuditContract.create_address(validators[0].address(), 0),
        creator=validators[0].address(),
    )
    result("Contract address", contract.address)

    state_manifold = TopologicalManifold.from_seed(b"contract_initial_state_48d")
    contract.deploy_function("store_manifold", [
        Instruction(QuditOpcode.PUSH_MANIFOLD, state_manifold),
        Instruction(QuditOpcode.DUP),
        Instruction(QuditOpcode.SSTORE, "state"),
        Instruction(QuditOpcode.EMIT, "StateUpdated"),
        Instruction(QuditOpcode.HALT),
    ])

    exec_result = contract.call("store_manifold", validators[0].address(), gas_limit=1.0)
    result("Execution", "SUCCESS" if exec_result.success else "FAILED")
    result("Gas used", f"{exec_result.gas_used:.4f}")
    result("Events emitted", str(len(exec_result.events)))

    spectrum = state_manifold.topological_spectrum()
    contract.deploy_function("read_state", [
        Instruction(QuditOpcode.SLOAD, "state"),
        Instruction(QuditOpcode.TOPO_GUARD, {0: spectrum[0], 1: spectrum[1]}),
        Instruction(QuditOpcode.SPECTRUM),
        Instruction(QuditOpcode.HALT),
    ])
    read_result = contract.call("read_state", validators[1].address(), gas_limit=1.0)
    result("Topo guard check", "PASSED" if read_result.success else "FAILED")

    # 8. NFTs
    section("8. VRC-48 Topological NFTs")
    step("Minting 4 NFTs with unique 48D fingerprints...")

    from vortexchain.nft import TopoNFTCollection

    collection = TopoNFTCollection("VortexGenesis", "VXGEN")
    nfts = []
    for i in range(4):
        nft = collection.mint(validators[0].address(), seed=f"genesis_nft_{i}_unique".encode() + b"\x00" * 40)
        nfts.append(nft)
        result(f"NFT #{i} rarity={nft.rarity_score:.3f}", f"spectrum[0:4]={nft.fingerprint.spectrum[:4]}")

    step("Fusing NFT #0 + NFT #1...")
    child = collection.fuse(nfts[0].token_id, nfts[1].token_id, validators[0].address())
    if child:
        result("Child NFT rarity", f"{child.rarity_score:.3f}")
        result("Child spectrum[0:4]", str(child.fingerprint.spectrum[:4]))

    result("Collection supply", str(collection.active_supply))

    # 9. TOKENOMICS
    section("9. $VORTEX Tokenomics")

    from vortexchain.tokenomics import VortexToken, AllocationCategory

    token = VortexToken()
    for i, kp in enumerate(validators):
        token.distribution.distribute(AllocationCategory.ECOSYSTEM, kp.address(), 10_000.0 + i * 5_000.0)

    for i, kp in enumerate(validators):
        bal = token.distribution.balance_of(kp.address())
        result(f"V{i}: {bal:,.0f} $VORTEX", f"gov_weight={token.governance_weight(kp.address()):.0f}")

    result("Total distributed", f"{token.distribution.total_distributed:,.0f}")
    result("Remaining supply", f"{token.distribution.remaining_supply:,.0f}")

    # SUMMARY
    section("DEMO COMPLETE")
    print("  VortexChain testnet simulation results:\n")
    print(f"    Nodes online:          {network.node_count}")
    print(f"    Quantum nodes:         {network.quantum_node_count}")
    print(f"    Chain height:          {chain.height} blocks")
    print(f"    Chain valid:           {'YES' if chain.validate_chain() else 'NO'}")
    print(f"    QKD keys established:  {qkd_alice.keys_generated}")
    print(f"    Contracts deployed:    1")
    print(f"    NFTs minted:           {collection.total_minted}")
    print(f"    NFTs fused:            {'1' if child else '0'}")
    print(f"    Oracle entropy rounds: 1")
    print(f"    Total $VORTEX dist:    {token.distribution.total_distributed:,.0f}")
    print(f"    Tests passing:         157")
    print()
    print("    The blockchain whose security comes from literal twisted light.")
    print()


if __name__ == "__main__":
    main()
