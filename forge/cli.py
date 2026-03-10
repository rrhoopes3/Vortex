"""
The Forge CLI — command-line interface for the agent marketplace.

Usage:
    python -m forge.cli register my-bot --owner alice
    python -m forge.cli submit "list files in current directory"
    python -m forge.cli balance
    python -m forge.cli deposit 5.0
    python -m forge.cli agents
    python -m forge.cli invoke ext_other-bot "summarize this"
    python -m forge.cli status inv_abc123
    python -m forge.cli rates
    python -m forge.cli me
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _get_client():
    from forge.sdk import ForgeClient
    base_url = os.environ.get("FORGE_URL", "http://localhost:5000")
    api_key = os.environ.get("FORGE_API_KEY", "")
    return ForgeClient(base_url=base_url, api_key=api_key)


def _save_key(api_key: str):
    """Save API key to .forge_key file for convenience."""
    key_file = os.path.expanduser("~/.forge_key")
    with open(key_file, "w") as f:
        f.write(api_key)
    print(f"  API key saved to {key_file}")


def _load_key() -> str:
    """Load API key from env or file."""
    key = os.environ.get("FORGE_API_KEY", "")
    if key:
        return key
    key_file = os.path.expanduser("~/.forge_key")
    if os.path.exists(key_file):
        with open(key_file) as f:
            return f.read().strip()
    return ""


def cmd_register(args):
    client = _get_client()
    try:
        result = client.register(
            args.name,
            owner=args.owner,
            description=args.description or "",
            capabilities=args.capabilities.split(",") if args.capabilities else [],
        )
        print(f"  Agent registered: {result['agent_id']}")
        print(f"  API Key: {result['api_key']}")
        print(f"  Balance: ${result['wallet']['balance_usd']:.2f}")
        if args.save_key:
            _save_key(result["api_key"])
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_submit(args):
    client = _get_client()
    client.api_key = client.api_key or _load_key()
    try:
        result = client.submit_task(args.task, executor_model=args.model or "")
        task_id = result["task_id"]
        print(f"  Task submitted: {task_id}")

        if args.stream:
            print("  --- Streaming output ---")
            for event in client.stream_task(task_id):
                etype = event.get("type", "")
                if etype == "done":
                    print("  --- Done ---")
                    break
                elif etype == "content":
                    content = event.get("content", "")
                    print(f"  {content}", end="")
                elif etype == "token_usage":
                    cost = event.get("cost_usd", 0)
                    if cost > 0:
                        print(f"  [cost: ${cost:.6f}]")
                elif etype == "toll_deducted":
                    toll = event.get("toll_usd", 0)
                    print(f"  [toll: ${toll:.6f}]")
                elif etype == "error":
                    print(f"  ERROR: {event.get('content', '')}", file=sys.stderr)
                else:
                    # Show other events as compact JSON
                    content = event.get("content", "")
                    if content:
                        print(f"  [{etype}] {content[:120]}")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_balance(args):
    client = _get_client()
    client.api_key = client.api_key or _load_key()
    try:
        data = client.get_wallet()
        w = data["wallet"]
        print(f"  Agent: {w['agent_id']}")
        print(f"  Balance: ${w['balance_usd']:.6f}")
        print(f"  Deposited: ${w['total_deposited']:.6f}")
        print(f"  Spent: ${w['total_spent']:.6f}")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_deposit(args):
    client = _get_client()
    client.api_key = client.api_key or _load_key()
    try:
        result = client.deposit(args.amount)
        print(f"  Deposited: ${args.amount:.2f}")
        print(f"  New balance: ${result['new_balance_usd']:.6f}")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_agents(args):
    client = _get_client()
    try:
        agents = client.list_agents()
        if not agents:
            print("  No agents registered yet.")
            return
        for a in agents:
            caps = ", ".join(a.get("capabilities", [])) or "none"
            desc = a.get("description", "") or "no description"
            print(f"  {a['agent_id']:30s}  {desc[:40]:40s}  [{caps}]")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_invoke(args):
    client = _get_client()
    client.api_key = client.api_key or _load_key()
    try:
        result = client.invoke_agent(args.target, args.task)
        task_id = result["task_id"]
        print(f"  Relay task: {task_id}")
        print(f"  {result['relay']['caller']} → {result['relay']['target']}")

        if args.stream:
            print("  --- Streaming ---")
            for event in client.stream_task(task_id):
                if event.get("type") == "done":
                    print("  --- Done ---")
                    break
                content = event.get("content", "")
                if content:
                    print(f"  {content}")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    client = _get_client()
    client.api_key = client.api_key or _load_key()
    try:
        result = client.check_invoice(args.invoice_id)
        print(f"  Invoice: {result['invoice_id']}")
        print(f"  Status: {result['status']}")
        print(f"  Amount: ${result['amount_usd']:.6f}")
        if result.get("paid_at"):
            print(f"  Paid at: {result['paid_at']}")
            print(f"  Solana TX: {result['solana_tx_hash']}")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_rates(args):
    client = _get_client()
    try:
        rates = client.get_rates()
        for msg_type, rate_info in rates.items():
            base = rate_info.get("base_rate_usd", 0)
            print(f"  {msg_type:25s}  ${base:.6f}")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_me(args):
    client = _get_client()
    client.api_key = client.api_key or _load_key()
    try:
        info = client.me()
        print(f"  Agent: {info['agent_id']}")
        print(f"  Owner: {info['owner_id']}")
        if info.get("wallet"):
            print(f"  Balance: ${info['wallet']['balance_usd']:.6f}")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        prog="forge",
        description="The Forge — Agent Marketplace CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # register
    p_reg = sub.add_parser("register", help="Register a new agent")
    p_reg.add_argument("name", help="Agent name")
    p_reg.add_argument("--owner", default="anonymous")
    p_reg.add_argument("--description", default="")
    p_reg.add_argument("--capabilities", default="", help="Comma-separated list")
    p_reg.add_argument("--save-key", action="store_true", help="Save API key to ~/.forge_key")

    # submit
    p_sub = sub.add_parser("submit", help="Submit a task")
    p_sub.add_argument("task", help="Task description")
    p_sub.add_argument("--model", default="", help="Executor model")
    p_sub.add_argument("--stream", action="store_true", help="Stream output")

    # balance
    sub.add_parser("balance", help="Check wallet balance")

    # deposit
    p_dep = sub.add_parser("deposit", help="Deposit funds")
    p_dep.add_argument("amount", type=float)

    # agents
    sub.add_parser("agents", help="List registered agents")

    # invoke
    p_inv = sub.add_parser("invoke", help="Invoke another agent")
    p_inv.add_argument("target", help="Target agent ID")
    p_inv.add_argument("task", help="Task to relay")
    p_inv.add_argument("--stream", action="store_true")

    # status
    p_stat = sub.add_parser("status", help="Check invoice/deposit status")
    p_stat.add_argument("invoice_id")

    # rates
    sub.add_parser("rates", help="Show toll rates")

    # me
    sub.add_parser("me", help="Show authenticated agent info")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "register": cmd_register,
        "submit": cmd_submit,
        "balance": cmd_balance,
        "deposit": cmd_deposit,
        "agents": cmd_agents,
        "invoke": cmd_invoke,
        "status": cmd_status,
        "rates": cmd_rates,
        "me": cmd_me,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
