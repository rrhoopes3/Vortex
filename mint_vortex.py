"""Mint $VORTEX SPL token on Solana mainnet."""

import asyncio
import json
import os
import struct

import base58
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from solders.system_program import create_account, CreateAccountParams
from solana.rpc.async_api import AsyncClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
TOKEN_METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
SYSVAR_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

MINT_ACCOUNT_SIZE = 82  # Fixed size for SPL Token Mint accounts

# Token config
TOKEN_NAME = "Vortex"
TOKEN_SYMBOL = "VORTEX"
TOKEN_DECIMALS = 9
TOKEN_SUPPLY = 48_000_000  # 48M
TOKEN_URI = "https://vortex.arc-relay.com/token-metadata.json"

RPC_URL = "https://api.mainnet-beta.solana.com"
KEYPAIR_PATH = os.path.expanduser("~/.config/solana/id.json")


# ---------------------------------------------------------------------------
# SPL Token instruction builders (raw, no extra deps needed)
# ---------------------------------------------------------------------------

def build_initialize_mint_ix(
    mint: Pubkey,
    mint_authority: Pubkey,
    freeze_authority: Pubkey | None,
    decimals: int,
) -> Instruction:
    """InitializeMint instruction (index 0)."""
    data = struct.pack("<B", 0)  # instruction index
    data += struct.pack("<B", decimals)
    data += bytes(mint_authority)  # 32 bytes
    if freeze_authority:
        data += b"\x01" + bytes(freeze_authority)
    else:
        data += b"\x00" + b"\x00" * 32

    accounts = [
        AccountMeta(mint, False, True),       # [writable] mint
        AccountMeta(SYSVAR_RENT, False, False),  # [] rent sysvar
    ]
    return Instruction(TOKEN_PROGRAM_ID, data, accounts)


def get_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """Derive the associated token account address."""
    pda, _bump = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
        ASSOCIATED_TOKEN_PROGRAM_ID,
    )
    return pda


def build_create_ata_ix(
    payer: Pubkey,
    owner: Pubkey,
    mint: Pubkey,
) -> Instruction:
    """Create Associated Token Account instruction."""
    ata = get_associated_token_address(owner, mint)
    accounts = [
        AccountMeta(payer, True, True),                    # [signer, writable] payer
        AccountMeta(ata, False, True),                     # [writable] ATA
        AccountMeta(owner, False, False),                  # [] owner
        AccountMeta(mint, False, False),                   # [] mint
        AccountMeta(SYSTEM_PROGRAM, False, False),         # [] system program
        AccountMeta(TOKEN_PROGRAM_ID, False, False),       # [] token program
    ]
    return Instruction(ASSOCIATED_TOKEN_PROGRAM_ID, b"", accounts)


def build_mint_to_ix(
    mint: Pubkey,
    dest: Pubkey,
    mint_authority: Pubkey,
    amount: int,
) -> Instruction:
    """MintTo instruction (index 7)."""
    data = struct.pack("<B", 7)  # instruction index
    data += struct.pack("<Q", amount)  # u64 amount
    accounts = [
        AccountMeta(mint, False, True),            # [writable] mint
        AccountMeta(dest, False, True),            # [writable] destination token account
        AccountMeta(mint_authority, True, False),   # [signer] mint authority
    ]
    return Instruction(TOKEN_PROGRAM_ID, data, accounts)


# ---------------------------------------------------------------------------
# Metaplex metadata
# ---------------------------------------------------------------------------

def get_metadata_pda(mint: Pubkey) -> Pubkey:
    """Derive the metadata account PDA for a given mint."""
    pda, _bump = Pubkey.find_program_address(
        [b"metadata", bytes(TOKEN_METADATA_PROGRAM_ID), bytes(mint)],
        TOKEN_METADATA_PROGRAM_ID,
    )
    return pda


def _borsh_string(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def build_create_metadata_v3_ix(
    metadata_pda: Pubkey,
    mint: Pubkey,
    mint_authority: Pubkey,
    payer: Pubkey,
    update_authority: Pubkey,
    name: str,
    symbol: str,
    uri: str,
    seller_fee_basis_points: int = 0,
    is_mutable: bool = True,
) -> Instruction:
    """Build CreateMetadataAccountV3 instruction (discriminator 33)."""
    # Instruction discriminator
    data = struct.pack("B", 33)

    # DataV2 fields
    data += _borsh_string(name)
    data += _borsh_string(symbol)
    data += _borsh_string(uri)
    data += struct.pack("<H", seller_fee_basis_points)  # u16

    # creators: Option<Vec<Creator>> — one creator (us) with 100% share
    data += b"\x01"  # Some
    data += struct.pack("<I", 1)  # vec length = 1
    data += bytes(payer)  # creator address (32 bytes)
    data += struct.pack("?", True)  # verified
    data += struct.pack("B", 100)  # share = 100%

    data += b"\x00"  # collection: None
    data += b"\x00"  # uses: None

    # is_mutable
    data += struct.pack("?", is_mutable)

    # collection_details: None
    data += b"\x00"

    accounts = [
        AccountMeta(metadata_pda, False, True),       # [writable] metadata PDA
        AccountMeta(mint, False, False),               # [] mint
        AccountMeta(mint_authority, True, False),      # [signer] mint authority
        AccountMeta(payer, True, True),                # [signer, writable] payer
        AccountMeta(update_authority, False, False),   # [] update authority
        AccountMeta(SYSTEM_PROGRAM, False, False),     # [] system program
    ]
    return Instruction(TOKEN_METADATA_PROGRAM_ID, data, accounts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def mint_vortex():
    # Load keypair
    raw = open(KEYPAIR_PATH).read().strip()
    decoded = base58.b58decode(raw)
    payer = Keypair.from_bytes(decoded)
    print(f"Payer: {payer.pubkey()}")

    # New mint keypair
    mint_kp = Keypair()
    print(f"Mint address: {mint_kp.pubkey()}")

    client = AsyncClient(RPC_URL)

    # Check balance
    bal = await client.get_balance(payer.pubkey())
    lamports = bal.value
    print(f"Balance: {lamports / 1e9:.6f} SOL")

    if lamports < 20_000_000:  # 0.02 SOL minimum
        raise RuntimeError(f"Insufficient SOL: {lamports / 1e9:.6f}")

    # Get rent exemption for mint account
    rent = await client.get_minimum_balance_for_rent_exemption(MINT_ACCOUNT_SIZE)
    print(f"Mint rent: {rent.value} lamports ({rent.value / 1e9:.6f} SOL)")

    # Derive addresses
    metadata_pda = get_metadata_pda(mint_kp.pubkey())
    ata = get_associated_token_address(payer.pubkey(), mint_kp.pubkey())
    raw_amount = TOKEN_SUPPLY * (10 ** TOKEN_DECIMALS)

    print(f"Metadata PDA: {metadata_pda}")
    print(f"ATA: {ata}")
    print(f"Raw amount: {raw_amount}")
    print()

    # Build all instructions
    instructions = [
        # 1. Create the mint account
        create_account(CreateAccountParams(
            from_pubkey=payer.pubkey(),
            to_pubkey=mint_kp.pubkey(),
            lamports=rent.value,
            space=MINT_ACCOUNT_SIZE,
            owner=TOKEN_PROGRAM_ID,
        )),
        # 2. Initialize the mint
        build_initialize_mint_ix(
            mint=mint_kp.pubkey(),
            mint_authority=payer.pubkey(),
            freeze_authority=payer.pubkey(),
            decimals=TOKEN_DECIMALS,
        ),
        # 3. Attach Metaplex metadata
        build_create_metadata_v3_ix(
            metadata_pda=metadata_pda,
            mint=mint_kp.pubkey(),
            mint_authority=payer.pubkey(),
            payer=payer.pubkey(),
            update_authority=payer.pubkey(),
            name=TOKEN_NAME,
            symbol=TOKEN_SYMBOL,
            uri=TOKEN_URI,
        ),
        # 4. Create ATA for payer
        build_create_ata_ix(
            payer=payer.pubkey(),
            owner=payer.pubkey(),
            mint=mint_kp.pubkey(),
        ),
        # 5. Mint full supply to ATA
        build_mint_to_ix(
            mint=mint_kp.pubkey(),
            dest=ata,
            mint_authority=payer.pubkey(),
            amount=raw_amount,
        ),
    ]

    # Get recent blockhash
    blockhash_resp = await client.get_latest_blockhash()
    recent_blockhash = blockhash_resp.value.blockhash

    # Compile and sign
    msg = MessageV0.try_compile(
        payer=payer.pubkey(),
        instructions=instructions,
        address_lookup_table_accounts=[],
        recent_blockhash=recent_blockhash,
    )
    tx = VersionedTransaction(msg, [payer, mint_kp])

    print("Sending transaction...")
    resp = await client.send_transaction(tx)
    sig = str(resp.value)
    print(f"Signature: {sig}")
    print(f"Explorer: https://solscan.io/tx/{sig}")
    print()
    print("Waiting for confirmation...")

    await client.confirm_transaction(sig, commitment="confirmed")
    print("CONFIRMED!")
    print()
    print("=" * 60)
    print(f"  $VORTEX TOKEN MINTED ON SOLANA MAINNET")
    print(f"  Mint:     {mint_kp.pubkey()}")
    print(f"  Supply:   {TOKEN_SUPPLY:,} VORTEX")
    print(f"  Decimals: {TOKEN_DECIMALS}")
    print(f"  Holder:   {payer.pubkey()}")
    print(f"  ATA:      {ata}")
    print(f"  Metadata: {metadata_pda}")
    print(f"  Tx:       https://solscan.io/tx/{sig}")
    print(f"  Token:    https://solscan.io/token/{mint_kp.pubkey()}")
    print("=" * 60)

    # Save mint info for the project
    mint_info = {
        "mint": str(mint_kp.pubkey()),
        "supply": TOKEN_SUPPLY,
        "decimals": TOKEN_DECIMALS,
        "holder": str(payer.pubkey()),
        "ata": str(ata),
        "metadata_pda": str(metadata_pda),
        "signature": sig,
        "explorer": f"https://solscan.io/tx/{sig}",
        "token_page": f"https://solscan.io/token/{mint_kp.pubkey()}",
    }
    with open("vortex_mint.json", "w") as f:
        json.dump(mint_info, f, indent=2)
    print("\nMint info saved to vortex_mint.json")

    await client.close()
    return mint_info


if __name__ == "__main__":
    result = asyncio.run(mint_vortex())
