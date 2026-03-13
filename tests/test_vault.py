"""
Tests for the Persistent Agent Memory Vault.
Cross-pollinated from Ars Contexta (github.com/agenticnotetaking/arscontexta).

Covers: VaultSpace, AgentVault, 6Rs pipeline, recall, stats.
"""
import json
import time
from pathlib import Path

import pytest

from forge.vault import (
    VaultEntry, SelfEntry, NotesEntry, OpsEntry, SixRsResult,
    VaultSpace, AgentVault,
    MAX_SELF_ENTRIES, MAX_NOTES_ENTRIES, MAX_OPS_ENTRIES,
    STALE_THRESHOLD_SECONDS, _detect_domains,
)


# ── VaultEntry ─────────────────────────────────────────────────────────────

class TestVaultEntry:
    def test_defaults(self):
        e = VaultEntry(topic="test", content="hello")
        assert e.topic == "test"
        assert e.content == "hello"
        assert e.confidence == 1.0
        assert e.reinforcement_count == 1
        assert e.entry_id  # auto-generated
        assert e.source_tasks == []

    def test_to_dict_roundtrip(self):
        e = VaultEntry(topic="t", content="c", confidence=0.8, source_tasks=["a"])
        d = e.to_dict()
        e2 = VaultEntry.from_dict(d)
        assert e2.topic == "t"
        assert e2.confidence == 0.8
        assert e2.source_tasks == ["a"]

    def test_self_entry(self):
        e = SelfEntry(topic="strength:python", content="good", trait_type="strength")
        d = e.to_dict()
        assert d["trait_type"] == "strength"
        e2 = SelfEntry.from_dict(d)
        assert e2.trait_type == "strength"

    def test_notes_entry(self):
        e = NotesEntry(topic="python_task", content="did it", domain="python", pattern_type="technique")
        d = e.to_dict()
        assert d["domain"] == "python"
        e2 = NotesEntry.from_dict(d)
        assert e2.domain == "python"
        assert e2.pattern_type == "technique"

    def test_ops_entry(self):
        e = OpsEntry(topic="session:x", content="done", metrics={"success": True, "steps": 3})
        d = e.to_dict()
        assert d["metrics"]["steps"] == 3
        e2 = OpsEntry.from_dict(d)
        assert e2.metrics["success"] is True


# ── VaultSpace ─────────────────────────────────────────────────────────────

class TestVaultSpace:
    def _make_space(self, tmp_path, max_entries=10):
        return VaultSpace(tmp_path / "test.json", max_entries, VaultEntry)

    def test_empty(self, tmp_path):
        space = self._make_space(tmp_path)
        assert space.entry_count == 0

    def test_add_and_count(self, tmp_path):
        space = self._make_space(tmp_path)
        space.add(VaultEntry(topic="a", content="hello"))
        space.add(VaultEntry(topic="b", content="world"))
        assert space.entry_count == 2

    def test_find_by_keyword(self, tmp_path):
        space = self._make_space(tmp_path)
        space.add(VaultEntry(topic="python_debugging", content="Use pytest for testing python code"))
        space.add(VaultEntry(topic="javascript_build", content="Use npm for building"))
        results = space.find("python testing")
        assert len(results) >= 1
        assert results[0].topic == "python_debugging"

    def test_find_no_match(self, tmp_path):
        space = self._make_space(tmp_path)
        space.add(VaultEntry(topic="python", content="python stuff"))
        results = space.find("zzz_nomatch_zzz_nothing")
        assert len(results) == 0

    def test_deduplication(self, tmp_path):
        space = self._make_space(tmp_path)
        space.add(VaultEntry(topic="same_topic", content="same content here is long enough"))
        space.add(VaultEntry(topic="same_topic", content="same content here is long enough"))
        assert space.entry_count == 1
        assert space.entries[0].reinforcement_count == 2

    def test_different_content_not_deduped(self, tmp_path):
        space = self._make_space(tmp_path)
        space.add(VaultEntry(topic="same_topic", content="content A is different"))
        space.add(VaultEntry(topic="same_topic", content="content B is different"))
        assert space.entry_count == 2

    def test_max_entries_trim(self, tmp_path):
        space = self._make_space(tmp_path, max_entries=3)
        for i in range(6):
            space.add(VaultEntry(topic=f"topic_{i}", content=f"content {i}"))
        assert space.entry_count <= 3

    def test_prune_stale(self, tmp_path):
        space = self._make_space(tmp_path)
        old_entry = VaultEntry(topic="old", content="ancient")
        old_entry.last_seen = time.time() - (STALE_THRESHOLD_SECONDS + 100)
        space._entries.append(old_entry)
        space.add(VaultEntry(topic="new", content="fresh"))

        pruned = space.prune_stale()
        assert pruned == 1
        assert space.entry_count == 1
        assert space.entries[0].topic == "new"

    def test_persistence(self, tmp_path):
        space1 = self._make_space(tmp_path)
        space1.add(VaultEntry(topic="persist", content="test data"))

        space2 = self._make_space(tmp_path)
        assert space2.entry_count == 1
        assert space2.entries[0].topic == "persist"

    def test_update_entry(self, tmp_path):
        space = self._make_space(tmp_path)
        space.add(VaultEntry(entry_id="fixed_id", topic="t", content="old"))
        assert space.update_entry("fixed_id", content="new")
        assert space.entries[0].content == "new"

    def test_update_nonexistent(self, tmp_path):
        space = self._make_space(tmp_path)
        assert not space.update_entry("nope", content="x")

    def test_remove_entry(self, tmp_path):
        space = self._make_space(tmp_path)
        space.add(VaultEntry(entry_id="rm_me", topic="t", content="c"))
        assert space.remove("rm_me")
        assert space.entry_count == 0

    def test_remove_nonexistent(self, tmp_path):
        space = self._make_space(tmp_path)
        assert not space.remove("nope")


# ── AgentVault ─────────────────────────────────────────────────────────────

class TestAgentVault:
    def _make_vault(self, tmp_path, agent_id="test-agent"):
        return AgentVault(agent_id, base_dir=tmp_path)

    def test_create(self, tmp_path):
        vault = self._make_vault(tmp_path)
        assert vault.agent_id == "test-agent"

    def test_spaces_exist(self, tmp_path):
        vault = self._make_vault(tmp_path)
        assert vault.self_space.entry_count == 0
        assert vault.notes_space.entry_count == 0
        assert vault.ops_space.entry_count == 0

    def test_safe_id(self):
        assert AgentVault._safe_id("normal-agent") == "normal-agent"
        assert AgentVault._safe_id("has spaces!@#") == "has_spaces___"
        assert len(AgentVault._safe_id("x" * 100)) <= 64

    def test_directory_created(self, tmp_path):
        vault = self._make_vault(tmp_path, "my-agent")
        assert (tmp_path / "my-agent").is_dir()


# ── 6Rs Pipeline ──────────────────────────────────────────────────────────

class TestSixRsPipeline:
    def _make_vault(self, tmp_path):
        return AgentVault("test-agent", base_dir=tmp_path)

    def test_full_pipeline(self, tmp_path):
        vault = self._make_vault(tmp_path)
        result = vault.process_6rs(
            task="Fix the login bug in auth.py",
            tools_used=["read_file", "write_file", "run_command"],
            key_paths=["/app/auth.py", "/app/tests/test_auth.py"],
            outcome="Fixed authentication bypass vulnerability",
            success=True,
            latency_seconds=25.0,
            step_count=3,
        )
        assert isinstance(result, SixRsResult)
        assert result.recorded  # ops entry created
        assert len(result.reduced) > 0  # notes extracted
        assert len(result.reflected) > 0  # self entries created
        assert isinstance(result.verified, dict)
        assert isinstance(result.rethought, dict)

    def test_record_creates_ops_entry(self, tmp_path):
        vault = self._make_vault(tmp_path)
        vault.process_6rs(
            task="Deploy the service",
            tools_used=["run_command"],
            key_paths=[],
            outcome="Deployed successfully",
            success=True,
            latency_seconds=10.0,
        )
        assert vault.ops_space.entry_count >= 1
        entry = vault.ops_space.entries[0]
        assert "Deploy" in entry.content
        assert entry.metrics["success"] is True

    def test_reduce_extracts_domain(self, tmp_path):
        vault = self._make_vault(tmp_path)
        result = vault.process_6rs(
            task="Fix python test in pytest suite",
            tools_used=["read_file", "write_file"],
            key_paths=["/app/test_main.py"],
            outcome="Fixed failing pytest test",
            success=True,
        )
        domains = [e.domain for e in result.reduced if hasattr(e, "domain")]
        # Should detect python and/or testing domain
        assert any(d in ("python", "testing") for d in domains)

    def test_reduce_extracts_tool_combo(self, tmp_path):
        vault = self._make_vault(tmp_path)
        result = vault.process_6rs(
            task="Update configuration",
            tools_used=["read_file", "write_file", "run_command"],
            key_paths=["/app/config.py"],
            outcome="Updated",
            success=True,
        )
        combo_entries = [e for e in result.reduced if hasattr(e, "pattern_type") and e.pattern_type == "tool_combo"]
        assert len(combo_entries) >= 1

    def test_reflect_success_creates_strength(self, tmp_path):
        vault = self._make_vault(tmp_path)
        result = vault.process_6rs(
            task="Fix python bug",
            tools_used=["read_file"],
            key_paths=["/app/main.py"],
            outcome="Fixed",
            success=True,
            latency_seconds=15.0,
        )
        strengths = [e for e in result.reflected if hasattr(e, "trait_type") and e.trait_type == "strength"]
        assert len(strengths) >= 1

    def test_reflect_failure_creates_weakness(self, tmp_path):
        vault = self._make_vault(tmp_path)
        result = vault.process_6rs(
            task="Fix python bug",
            tools_used=["read_file"],
            key_paths=["/app/main.py"],
            outcome="Failed to fix",
            success=False,
            latency_seconds=30.0,
        )
        weaknesses = [e for e in result.reflected if hasattr(e, "trait_type") and e.trait_type == "weakness"]
        assert len(weaknesses) >= 1

    def test_reweave_reinforces_existing(self, tmp_path):
        vault = self._make_vault(tmp_path)
        # Run pipeline twice with similar tasks
        vault.process_6rs(
            task="Fix python testing issue",
            tools_used=["read_file", "write_file"],
            key_paths=["/app/test.py"],
            outcome="Fixed test",
            success=True,
        )
        count_after_first = vault.notes_space.entry_count

        vault.process_6rs(
            task="Fix python testing problem",
            tools_used=["read_file", "write_file"],
            key_paths=["/app/test.py"],
            outcome="Fixed test",
            success=True,
        )
        # Some entries should have been reinforced rather than all being new
        # So the count should grow less than double
        count_after_second = vault.notes_space.entry_count
        assert count_after_second <= count_after_first * 2

    def test_verify_prunes_stale(self, tmp_path):
        vault = self._make_vault(tmp_path)
        # Manually add a stale entry
        old = NotesEntry(topic="ancient", content="old stuff", domain="python")
        old.last_seen = time.time() - (STALE_THRESHOLD_SECONDS + 100)
        vault.notes_space._entries.append(old)
        vault.notes_space._save()

        result = vault.process_6rs(
            task="New task",
            tools_used=["read_file"],
            key_paths=[],
            outcome="Done",
            success=True,
        )
        assert result.verified["pruned"] >= 1

    def test_verify_resolves_contradictions(self, tmp_path):
        vault = self._make_vault(tmp_path)
        # Add contradictory entries
        vault.self_space.add(SelfEntry(
            topic="strength:python", content="Good at python",
            trait_type="strength", reinforcement_count=5,
        ))
        vault.self_space.add(SelfEntry(
            topic="weakness:python", content="Bad at python",
            trait_type="weakness", reinforcement_count=1,
        ))

        result = vault.process_6rs(
            task="Do something",
            tools_used=[],
            key_paths=[],
            outcome="Done",
            success=True,
        )
        assert result.verified["contradictions_resolved"] >= 1

    def test_rethink_updates_specializations(self, tmp_path):
        vault = self._make_vault(tmp_path)
        # Add several python notes
        for i in range(5):
            vault.notes_space.add(NotesEntry(
                topic=f"python_task_{i}", content=f"Python work {i}",
                domain="python", pattern_type="technique",
            ))
        # Add fewer JS notes
        for i in range(2):
            vault.notes_space.add(NotesEntry(
                topic=f"js_task_{i}", content=f"JS work {i}",
                domain="javascript", pattern_type="technique",
            ))

        result = vault.process_6rs(
            task="Another python task",
            tools_used=["read_file"],
            key_paths=["/app/main.py"],
            outcome="Done",
            success=True,
        )
        assert "python" in result.rethought["specializations"]

    def test_failed_task_no_reduce(self, tmp_path):
        vault = self._make_vault(tmp_path)
        result = vault.process_6rs(
            task="Try something",
            tools_used=["run_command"],
            key_paths=[],
            outcome="Failed miserably",
            success=False,
        )
        assert len(result.reduced) == 0  # reduce skips on failure


# ── Recall ─────────────────────────────────────────────────────────────────

class TestVaultRecall:
    def _make_vault(self, tmp_path):
        return AgentVault("test-agent", base_dir=tmp_path)

    def test_empty_vault_returns_empty(self, tmp_path):
        vault = self._make_vault(tmp_path)
        assert vault.recall_vault_context("anything") == ""

    def test_recall_with_matching_content(self, tmp_path):
        vault = self._make_vault(tmp_path)
        vault.notes_space.add(NotesEntry(
            topic="python_debugging", content="Use pytest with verbose flag for debugging",
            domain="python", pattern_type="technique",
        ))
        result = vault.recall_vault_context("python pytest verbose debugging")
        assert "AGENT VAULT" in result
        assert "pytest" in result

    def test_recall_format(self, tmp_path):
        vault = self._make_vault(tmp_path)
        vault.self_space.add(SelfEntry(
            topic="strength:python", content="Strong at python",
            trait_type="strength",
        ))
        vault.notes_space.add(NotesEntry(
            topic="python_patterns", content="Python pattern knowledge",
            domain="python", pattern_type="technique",
        ))
        result = vault.recall_vault_context("python task")
        assert "[AGENT VAULT" in result
        assert "Identity:" in result
        assert "Knowledge:" in result
        assert "[END AGENT VAULT]" in result


# ── Stats ──────────────────────────────────────────────────────────────────

class TestVaultStats:
    def _make_vault(self, tmp_path):
        return AgentVault("test-agent", base_dir=tmp_path)

    def test_stats_empty(self, tmp_path):
        vault = self._make_vault(tmp_path)
        stats = vault.vault_stats()
        assert stats["total_entries"] == 0

    def test_stats_after_pipeline(self, tmp_path):
        vault = self._make_vault(tmp_path)
        vault.process_6rs(
            task="Fix python bug",
            tools_used=["read_file", "write_file"],
            key_paths=["/app/main.py"],
            outcome="Fixed",
            success=True,
        )
        stats = vault.vault_stats()
        assert stats["total_entries"] > 0
        assert stats["ops_entries"] >= 1

    def test_get_specializations(self, tmp_path):
        vault = self._make_vault(tmp_path)
        vault.self_space.add(SelfEntry(
            topic="auto_spec:python", content="Top-1 specialization: python",
            trait_type="specialization",
        ))
        specs = vault.get_specializations()
        assert "python" in specs

    def test_get_expertise_areas(self, tmp_path):
        vault = self._make_vault(tmp_path)
        vault.notes_space.add(NotesEntry(
            topic="py1", content="Python stuff", domain="python", pattern_type="technique",
        ))
        vault.notes_space.add(NotesEntry(
            topic="py2", content="More python", domain="python", pattern_type="tool_combo",
        ))
        vault.notes_space.add(NotesEntry(
            topic="js1", content="JS stuff", domain="javascript", pattern_type="technique",
        ))
        areas = vault.get_expertise_areas()
        assert len(areas) == 2
        assert areas[0]["domain"] == "python"  # more entries
        assert areas[0]["entries"] == 2


# ── Domain Detection ──────────────────────────────────────────────────────

class TestDomainDetection:
    def test_python_detection(self):
        domains = _detect_domains("Fix the pytest test in main.py")
        assert "python" in domains

    def test_javascript_detection(self):
        domains = _detect_domains("Update the React component in app.js")
        assert "javascript" in domains

    def test_no_match(self):
        domains = _detect_domains("zzz nothing matches here")
        assert len(domains) == 0

    def test_multiple_domains(self):
        domains = _detect_domains("Deploy the docker container with python flask api")
        assert len(domains) >= 2
