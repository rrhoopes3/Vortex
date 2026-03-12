"""
Tests for the Personal Knowledge Graph.
Cross-pollinated from AgentOS (arXiv:2603.08938).

Covers: KnowledgeGraph, KGNode, KGEdge, graph traversal, persistence.
"""
import json
from pathlib import Path

import pytest

from forge.context_engine import KnowledgeGraph, KGNode, KGEdge


class TestKnowledgeGraph:
    def _make_kg(self, tmp_path):
        return KnowledgeGraph(path=tmp_path / "kg.json")

    def test_empty_graph(self, tmp_path):
        kg = self._make_kg(tmp_path)
        assert kg.node_count == 0
        assert kg.edge_count == 0

    def test_add_node(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_node("file:/app/main.py", "file", "main.py")
        assert kg.node_count == 1

    def test_add_edge(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_node("tool:read_file", "tool", "read_file")
        kg.add_node("file:/app/main.py", "file", "main.py")
        kg.add_edge("tool:read_file", "file:/app/main.py", "operated_on")
        assert kg.edge_count == 1

    def test_edge_strengthening(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_node("a", "test")
        kg.add_node("b", "test")
        kg.add_edge("a", "b", "related", weight=1.0)
        kg.add_edge("a", "b", "related", weight=1.0)  # same edge → strengthen
        assert kg.edge_count == 1
        assert kg._edges[0].weight == 1.5

    def test_record_task_knowledge(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.record_task_knowledge(
            task="Fix the login bug",
            tools_used=["read_file", "write_file", "run_command"],
            key_paths=["/app/auth.py", "/app/tests/test_auth.py"],
            outcome="Fixed auth bypass vulnerability",
        )
        assert kg.node_count > 0
        assert kg.edge_count > 0
        # Should have: task node, 3 tool nodes, 2 file nodes
        assert kg.node_count >= 6

    def test_query_related(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.record_task_knowledge(
            task="Fix auth bug",
            tools_used=["read_file", "write_file"],
            key_paths=["/app/auth.py"],
            outcome="Fixed",
        )
        related = kg.query_related("auth")
        assert len(related) > 0
        # Should find tools and files related to "auth"
        kinds = {r["kind"] for r in related}
        assert "tool" in kinds or "file" in kinds

    def test_query_related_no_match(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.record_task_knowledge(
            task="Fix auth bug",
            tools_used=["read_file"],
            key_paths=["/app/auth.py"],
            outcome="Fixed",
        )
        related = kg.query_related("zzz_no_match_zzz")
        assert len(related) == 0

    def test_recall_graph_context(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.record_task_knowledge(
            task="Refactor database models",
            tools_used=["read_file", "write_file", "grep_files"],
            key_paths=["/app/models.py", "/app/db.py"],
            outcome="Refactored 5 models to use Pydantic",
        )
        ctx = kg.recall_graph_context("update the database models")
        assert "KNOWLEDGE GRAPH" in ctx
        assert len(ctx) > 50

    def test_recall_empty_graph(self, tmp_path):
        kg = self._make_kg(tmp_path)
        ctx = kg.recall_graph_context("anything")
        assert ctx == ""

    def test_persistence(self, tmp_path):
        kg1 = self._make_kg(tmp_path)
        kg1.record_task_knowledge(
            task="Setup project",
            tools_used=["run_command"],
            key_paths=["/app/setup.py"],
            outcome="Done",
        )
        node_count = kg1.node_count
        edge_count = kg1.edge_count

        kg2 = self._make_kg(tmp_path)
        assert kg2.node_count == node_count
        assert kg2.edge_count == edge_count

    def test_node_update(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_node("x", "test", "X", version="1")
        kg.add_node("x", "test", "X", version="2")
        assert kg.node_count == 1
        assert kg._nodes["x"].properties["version"] == "2"

    def test_max_nodes_trim(self, tmp_path):
        kg = self._make_kg(tmp_path)
        # Override MAX_NODES for test
        import forge.context_engine as ce
        old_max = ce.MAX_NODES
        ce.MAX_NODES = 5
        try:
            for i in range(10):
                kg.add_node(f"n{i}", "test", f"Node {i}")
            kg._save()  # triggers trim
            kg2 = self._make_kg(tmp_path)
            assert kg2.node_count <= 5
        finally:
            ce.MAX_NODES = old_max

    def test_multi_hop_traversal(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_node("a", "test")
        kg.add_node("b", "test")
        kg.add_node("c", "test")
        kg.add_edge("a", "b", "link")
        kg.add_edge("b", "c", "link")
        kg._save()

        # Query from "a" should reach "c" in 2 hops
        related = kg.query_related("a", max_hops=2)
        ids = {r["id"] for r in related}
        assert "b" in ids
        assert "c" in ids

    def test_single_hop_traversal(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_node("a", "test")
        kg.add_node("b", "test")
        kg.add_node("c", "test")
        kg.add_edge("a", "b", "link")
        kg.add_edge("b", "c", "link")

        # Only 1 hop: should not reach "c"
        related = kg.query_related("a", max_hops=1)
        ids = {r["id"] for r in related}
        assert "b" in ids
        assert "c" not in ids


class TestKGNode:
    def test_create(self):
        n = KGNode(id="test", kind="file", label="test.py")
        assert n.id == "test"
        assert n.kind == "file"
        assert n.label == "test.py"
        assert n.properties == {}

    def test_properties(self):
        n = KGNode(id="x", kind="task", properties={"outcome": "success"})
        assert n.properties["outcome"] == "success"


class TestKGEdge:
    def test_create(self):
        e = KGEdge(source="a", target="b", relation="uses")
        assert e.source == "a"
        assert e.target == "b"
        assert e.weight == 1.0

    def test_custom_weight(self):
        e = KGEdge(source="a", target="b", relation="uses", weight=3.5)
        assert e.weight == 3.5
