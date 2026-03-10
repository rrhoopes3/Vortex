"""
Tests for Beat 7: CLI tool (forge.cli).

Tests the argument parsing and command dispatch without a running server.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forge.cli import main


# ── Argument Parsing ─────────────────────────────────────────────────────

class TestArgParsing:
    def test_no_args_prints_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 0

    def test_register_args(self):
        """Verify register subcommand parses correctly."""
        import argparse
        from forge.cli import main as cli_main
        # We'll mock the actual command handler
        with patch("forge.cli.cmd_register") as mock_cmd:
            main(["register", "test-bot", "--owner", "alice",
                  "--description", "A bot", "--capabilities", "code,search"])
            args = mock_cmd.call_args[0][0]
            assert args.name == "test-bot"
            assert args.owner == "alice"
            assert args.description == "A bot"
            assert args.capabilities == "code,search"

    def test_submit_args(self):
        with patch("forge.cli.cmd_submit") as mock_cmd:
            main(["submit", "list files", "--model", "grok-4-1-fast-reasoning", "--stream"])
            args = mock_cmd.call_args[0][0]
            assert args.task == "list files"
            assert args.model == "grok-4-1-fast-reasoning"
            assert args.stream is True

    def test_balance_args(self):
        with patch("forge.cli.cmd_balance") as mock_cmd:
            main(["balance"])
            mock_cmd.assert_called_once()

    def test_deposit_args(self):
        with patch("forge.cli.cmd_deposit") as mock_cmd:
            main(["deposit", "5.0"])
            args = mock_cmd.call_args[0][0]
            assert args.amount == 5.0

    def test_agents_args(self):
        with patch("forge.cli.cmd_agents") as mock_cmd:
            main(["agents"])
            mock_cmd.assert_called_once()

    def test_invoke_args(self):
        with patch("forge.cli.cmd_invoke") as mock_cmd:
            main(["invoke", "ext_other-bot", "do something", "--stream"])
            args = mock_cmd.call_args[0][0]
            assert args.target == "ext_other-bot"
            assert args.task == "do something"
            assert args.stream is True

    def test_status_args(self):
        with patch("forge.cli.cmd_status") as mock_cmd:
            main(["status", "inv_abc123"])
            args = mock_cmd.call_args[0][0]
            assert args.invoice_id == "inv_abc123"

    def test_rates_args(self):
        with patch("forge.cli.cmd_rates") as mock_cmd:
            main(["rates"])
            mock_cmd.assert_called_once()

    def test_me_args(self):
        with patch("forge.cli.cmd_me") as mock_cmd:
            main(["me"])
            mock_cmd.assert_called_once()


# ── Command Execution (Mocked SDK) ──────────────────────────────────────

class TestCommandExecution:
    def test_register_prints_output(self, capsys):
        mock_client = MagicMock()
        mock_client.register.return_value = {
            "agent_id": "ext_test-bot",
            "api_key": "forge_abc123",
            "wallet": {"balance_usd": 1.0},
        }
        with patch("forge.cli._get_client", return_value=mock_client):
            main(["register", "test-bot"])
        out = capsys.readouterr().out
        assert "ext_test-bot" in out
        assert "forge_abc123" in out

    def test_balance_prints_output(self, capsys):
        mock_client = MagicMock()
        mock_client.api_key = ""
        mock_client.get_wallet.return_value = {
            "wallet": {
                "agent_id": "ext_test",
                "balance_usd": 7.5,
                "total_deposited": 10.0,
                "total_spent": 2.5,
            },
        }
        with patch("forge.cli._get_client", return_value=mock_client), \
             patch("forge.cli._load_key", return_value="forge_key"):
            main(["balance"])
        out = capsys.readouterr().out
        assert "7.5" in out

    def test_deposit_prints_output(self, capsys):
        mock_client = MagicMock()
        mock_client.api_key = ""
        mock_client.deposit.return_value = {"new_balance_usd": 15.0}
        with patch("forge.cli._get_client", return_value=mock_client), \
             patch("forge.cli._load_key", return_value="forge_key"):
            main(["deposit", "5.0"])
        out = capsys.readouterr().out
        assert "15.0" in out

    def test_agents_prints_list(self, capsys):
        mock_client = MagicMock()
        mock_client.list_agents.return_value = [
            {"agent_id": "ext_bot-a", "description": "Bot A", "capabilities": ["code"]},
            {"agent_id": "ext_bot-b", "description": "", "capabilities": []},
        ]
        with patch("forge.cli._get_client", return_value=mock_client):
            main(["agents"])
        out = capsys.readouterr().out
        assert "ext_bot-a" in out
        assert "ext_bot-b" in out

    def test_agents_empty_list(self, capsys):
        mock_client = MagicMock()
        mock_client.list_agents.return_value = []
        with patch("forge.cli._get_client", return_value=mock_client):
            main(["agents"])
        out = capsys.readouterr().out
        assert "No agents" in out

    def test_rates_prints_output(self, capsys):
        mock_client = MagicMock()
        mock_client.get_rates.return_value = {
            "plan": {"base_rate_usd": 0.001},
            "execute": {"base_rate_usd": 0.005},
        }
        with patch("forge.cli._get_client", return_value=mock_client):
            main(["rates"])
        out = capsys.readouterr().out
        assert "plan" in out
        assert "execute" in out

    def test_submit_prints_task_id(self, capsys):
        mock_client = MagicMock()
        mock_client.api_key = ""
        mock_client.submit_task.return_value = {
            "task_id": "ext-abc12345",
            "stream_url": "/api/v1/tasks/ext-abc12345/stream",
        }
        with patch("forge.cli._get_client", return_value=mock_client), \
             patch("forge.cli._load_key", return_value="forge_key"):
            main(["submit", "hello world"])
        out = capsys.readouterr().out
        assert "ext-abc12345" in out

    def test_me_prints_info(self, capsys):
        mock_client = MagicMock()
        mock_client.api_key = ""
        mock_client.me.return_value = {
            "agent_id": "ext_my-bot",
            "owner_id": "alice",
            "wallet": {"balance_usd": 5.0},
        }
        with patch("forge.cli._get_client", return_value=mock_client), \
             patch("forge.cli._load_key", return_value="forge_key"):
            main(["me"])
        out = capsys.readouterr().out
        assert "ext_my-bot" in out
        assert "alice" in out

    def test_status_prints_invoice(self, capsys):
        mock_client = MagicMock()
        mock_client.api_key = ""
        mock_client.check_invoice.return_value = {
            "invoice_id": "inv_abc",
            "status": "pending",
            "amount_usd": 0.05,
        }
        with patch("forge.cli._get_client", return_value=mock_client), \
             patch("forge.cli._load_key", return_value="forge_key"):
            main(["status", "inv_abc"])
        out = capsys.readouterr().out
        assert "inv_abc" in out
        assert "pending" in out


# ── Error Handling ───────────────────────────────────────────────────────

class TestCLIErrors:
    def test_register_error_exits(self, capsys):
        mock_client = MagicMock()
        mock_client.register.side_effect = Exception("Connection refused")
        with patch("forge.cli._get_client", return_value=mock_client):
            with pytest.raises(SystemExit) as exc_info:
                main(["register", "fail-bot"])
            assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Connection refused" in err

    def test_balance_error_exits(self, capsys):
        mock_client = MagicMock()
        mock_client.api_key = ""
        mock_client.get_wallet.side_effect = Exception("401")
        with patch("forge.cli._get_client", return_value=mock_client), \
             patch("forge.cli._load_key", return_value=""):
            with pytest.raises(SystemExit):
                main(["balance"])


# ── Key Management ───────────────────────────────────────────────────────

class TestKeyManagement:
    def test_load_key_from_env(self):
        from forge.cli import _load_key
        with patch.dict(os.environ, {"FORGE_API_KEY": "forge_envkey"}):
            assert _load_key() == "forge_envkey"

    def test_load_key_from_file(self, tmp_path):
        from forge.cli import _load_key
        key_file = tmp_path / ".forge_key"
        key_file.write_text("forge_filekey")
        with patch.dict(os.environ, {}, clear=False), \
             patch("os.path.expanduser", return_value=str(key_file)), \
             patch.dict(os.environ, {"FORGE_API_KEY": ""}, clear=False):
            # Need to clear FORGE_API_KEY
            os.environ.pop("FORGE_API_KEY", None)
            result = _load_key()
            assert result == "forge_filekey"

    def test_save_key(self, tmp_path, capsys):
        from forge.cli import _save_key
        key_file = tmp_path / ".forge_key"
        with patch("os.path.expanduser", return_value=str(key_file)):
            _save_key("forge_savedkey")
        assert key_file.read_text() == "forge_savedkey"
