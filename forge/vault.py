"""
Persistent Agent Memory Vault — three-space knowledge system with 6Rs pipeline.

Cross-pollinated from Ars Contexta (github.com/agenticnotetaking/arscontexta):
  - Three-space separation: self (identity), notes (knowledge), ops (operational)
  - 6Rs processing pipeline: Record → Reduce → Reflect → Reweave → Verify → Rethink

Agents accumulate expertise across sessions rather than starting fresh each time.
Vault data enriches marketplace profiles so experienced agents can charge premium tolls.
"""
from __future__ import annotations

import json
import logging
import re
import time as _time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from forge.config import VAULTS_DIR

log = logging.getLogger("forge.vault")

# ── Limits ─────────────────────────────────────────────────────────────────

MAX_SELF_ENTRIES = 20     # identity changes slowly
MAX_NOTES_ENTRIES = 100   # knowledge accumulates
MAX_OPS_ENTRIES = 30      # recent sessions only

STALE_THRESHOLD_SECONDS = 30 * 24 * 3600  # 30 days


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Domain detection ───────────────────────────────────────────────────────

DOMAIN_SIGNALS: dict[str, list[str]] = {
    "python": [r"\.py\b", r"\bpython\b", r"\bpip\b", r"\bdjango\b", r"\bflask\b", r"\bpytest\b"],
    "javascript": [r"\.js\b", r"\.ts\b", r"\bnode\b", r"\bnpm\b", r"\breact\b"],
    "devops": [r"\bdocker\b", r"\bkubernetes\b", r"\bci/?cd\b", r"\bdeploy\b"],
    "database": [r"\bsql\b", r"\bpostgres\b", r"\bmigrat\b", r"\bschema\b", r"\bsqlite\b"],
    "testing": [r"\btest\b", r"\bpytest\b", r"\bjest\b", r"\bspec\b"],
    "security": [r"\bauth\b", r"\bsecurity\b", r"\bvulnerab\b", r"\bfirewall\b"],
    "git": [r"\bgit\b", r"\bcommit\b", r"\bbranch\b", r"\bmerge\b"],
    "web": [r"\bhttp\b", r"\bapi\b", r"\brest\b", r"\bendpoint\b", r"\bflask\b"],
}


def _detect_domains(text: str) -> list[str]:
    """Detect domains from text using regex signal matching."""
    text_lower = text.lower()
    hits: dict[str, int] = {}
    for domain, patterns in DOMAIN_SIGNALS.items():
        count = sum(1 for p in patterns if re.search(p, text_lower))
        if count > 0:
            hits[domain] = count
    return sorted(hits, key=hits.get, reverse=True)  # type: ignore[arg-type]


# ── Data Structures ────────────────────────────────────────────────────────

@dataclass
class VaultEntry:
    """A single entry in any vault space."""
    entry_id: str = field(default_factory=_short_id)
    topic: str = ""
    content: str = ""
    confidence: float = 1.0
    reinforcement_count: int = 1
    created_at: float = field(default_factory=_time.time)
    last_seen: float = field(default_factory=_time.time)
    source_tasks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "topic": self.topic,
            "content": self.content,
            "confidence": round(self.confidence, 3),
            "reinforcement_count": self.reinforcement_count,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "source_tasks": self.source_tasks[:10],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VaultEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SelfEntry(VaultEntry):
    """Agent identity entry (self_space)."""
    trait_type: str = ""  # specialization | strength | weakness | preference

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["trait_type"] = self.trait_type
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SelfEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class NotesEntry(VaultEntry):
    """Knowledge entry (notes_space)."""
    domain: str = ""
    pattern_type: str = ""  # technique | tool_combo | anti_pattern

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["domain"] = self.domain
        d["pattern_type"] = self.pattern_type
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "NotesEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class OpsEntry(VaultEntry):
    """Operational entry (ops_space)."""
    session_id: str = ""
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["session_id"] = self.session_id
        d["metrics"] = self.metrics
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OpsEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SixRsResult:
    """Result of the 6Rs pipeline execution."""
    recorded: dict = field(default_factory=dict)
    reduced: list = field(default_factory=list)
    reflected: list = field(default_factory=list)
    rewoven: int = 0
    verified: dict = field(default_factory=dict)
    rethought: dict = field(default_factory=dict)


# ── VaultSpace ─────────────────────────────────────────────────────────────

class VaultSpace:
    """Manages a single vault space (self, notes, or ops)."""

    def __init__(self, path: Path, max_entries: int, entry_cls: type):
        self._path = path
        self._max = max_entries
        self._entry_cls = entry_cls
        self._entries: list = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = [self._entry_cls.from_dict(d) for d in raw]
        except Exception:
            log.warning("Failed to load vault space %s, starting fresh", self._path)
            self._entries = []

    def _save(self) -> None:
        # Trim: keep entries with highest score = confidence * 0.3 + recency * 0.7
        if len(self._entries) > self._max:
            now = _time.time()
            max_age = max((now - e.created_at) for e in self._entries) or 1.0

            def _score(e):
                recency = 1.0 - min((now - e.last_seen) / max_age, 1.0)
                return e.confidence * 0.3 + recency * 0.7

            self._entries.sort(key=_score, reverse=True)
            self._entries = self._entries[: self._max]

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps([e.to_dict() for e in self._entries], indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            log.warning("Failed to save vault space %s", self._path)

    def add(self, entry) -> None:
        """Add entry, deduplicating by topic + content prefix."""
        for existing in self._entries:
            if (existing.topic == entry.topic
                    and existing.content[:80] == entry.content[:80]):
                # Reinforce existing entry
                existing.reinforcement_count += 1
                existing.last_seen = _time.time()
                existing.confidence = min(existing.confidence + 0.05, 1.0)
                if entry.source_tasks:
                    for t in entry.source_tasks:
                        if t not in existing.source_tasks:
                            existing.source_tasks.append(t)
                    existing.source_tasks = existing.source_tasks[:10]
                self._save()
                return
        self._entries.append(entry)
        self._save()

    def find(self, query: str, limit: int = 5) -> list:
        """Find entries by keyword overlap with query."""
        query_words = set(re.findall(r"\w{3,}", query.lower()))
        if not query_words:
            return self._entries[:limit]

        scored = []
        for entry in self._entries:
            entry_words = set(re.findall(r"\w{3,}", f"{entry.topic} {entry.content}".lower()))
            overlap = len(query_words & entry_words)
            if overlap > 0:
                scored.append((overlap * entry.confidence, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def prune_stale(self, threshold_seconds: float = STALE_THRESHOLD_SECONDS) -> int:
        """Remove entries older than threshold. Returns count pruned."""
        cutoff = _time.time() - threshold_seconds
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.last_seen >= cutoff]
        pruned = before - len(self._entries)
        if pruned > 0:
            self._save()
        return pruned

    def update_entry(self, entry_id: str, **updates) -> bool:
        """Update fields on an entry by ID."""
        for entry in self._entries:
            if entry.entry_id == entry_id:
                for k, v in updates.items():
                    if hasattr(entry, k):
                        setattr(entry, k, v)
                self._save()
                return True
        return False

    def remove(self, entry_id: str) -> bool:
        """Remove an entry by ID."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.entry_id != entry_id]
        if len(self._entries) < before:
            self._save()
            return True
        return False

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> list:
        return list(self._entries)


# ── AgentVault ─────────────────────────────────────────────────────────────

class AgentVault:
    """Three-space persistent memory vault for an agent.

    Cross-pollinated from Ars Contexta (github.com/agenticnotetaking/arscontexta):
      self/  — agent identity and capability evolution
      notes/ — distilled knowledge and patterns
      ops/   — operational session history and metrics
    """

    def __init__(self, agent_id: str, base_dir: Path | None = None):
        self._agent_id = agent_id
        self._dir = (base_dir or VAULTS_DIR) / self._safe_id(agent_id)
        self._dir.mkdir(parents=True, exist_ok=True)

        self.self_space = VaultSpace(self._dir / "self_space.json", MAX_SELF_ENTRIES, SelfEntry)
        self.notes_space = VaultSpace(self._dir / "notes_space.json", MAX_NOTES_ENTRIES, NotesEntry)
        self.ops_space = VaultSpace(self._dir / "ops_space.json", MAX_OPS_ENTRIES, OpsEntry)

    @staticmethod
    def _safe_id(agent_id: str) -> str:
        """Sanitize agent_id for filesystem use."""
        return re.sub(r"[^\w.\-]", "_", agent_id)[:64]

    @property
    def agent_id(self) -> str:
        return self._agent_id

    # ── 6Rs Pipeline ───────────────────────────────────────────────────

    def process_6rs(
        self,
        task: str,
        tools_used: list[str],
        key_paths: list[str],
        outcome: str,
        success: bool,
        latency_seconds: float = 0.0,
        step_count: int = 1,
        directives: list | None = None,
        judge_scores: list | None = None,
    ) -> SixRsResult:
        """Run the 6Rs post-task processing pipeline.

        All stages use lightweight string processing — no LLM calls.

        OpenClaw-RL extensions (arXiv:2603.10165):
          - directives: contrastive NotesEntry objects from reassignment analysis
          - judge_scores: JudgeScore objects from background PRM judge
        """
        try:
            recorded = self._record(task, tools_used, key_paths, outcome, success, latency_seconds, step_count)
            reduced = self._reduce(task, tools_used, key_paths, outcome, success)
            reflected = self._reflect(task, tools_used, outcome, success, latency_seconds, judge_scores=judge_scores)
            rewoven = self._reweave(reduced, reflected, directives=directives)
            verified = self._verify()
            rethought = self._rethink()

            log.info("6Rs pipeline complete for %s: %d reduced, %d reflected, %d rewoven",
                     self._agent_id, len(reduced), len(reflected), rewoven)

            return SixRsResult(
                recorded=recorded,
                reduced=reduced,
                reflected=reflected,
                rewoven=rewoven,
                verified=verified,
                rethought=rethought,
            )
        except Exception:
            log.warning("6Rs pipeline error for %s", self._agent_id, exc_info=True)
            return SixRsResult()

    def _record(self, task, tools_used, key_paths, outcome, success, latency, step_count) -> dict:
        """R1: Record — capture raw session data into ops_space."""
        task_prefix = task[:40].strip().replace(" ", "_").lower()
        entry = OpsEntry(
            topic=f"session:{task_prefix}",
            content=f"Task: {task[:100]} | Outcome: {outcome[:100]} | Tools: {','.join(tools_used[:5])}",
            source_tasks=[task[:60]],
            metrics={
                "success": success,
                "latency_s": round(latency, 2),
                "steps": step_count,
                "tools_count": len(tools_used),
            },
        )
        self.ops_space.add(entry)
        return entry.to_dict()

    def _reduce(self, task, tools_used, key_paths, outcome, success) -> list:
        """R2: Reduce — extract reusable patterns from the outcome."""
        if not success:
            return []

        entries: list[NotesEntry] = []
        combined_text = f"{task} {outcome} {' '.join(key_paths)}"
        domains = _detect_domains(combined_text)
        task_prefix = task[:60]

        # Domain knowledge entries
        for domain in domains[:2]:
            entries.append(NotesEntry(
                topic=f"{domain}_task",
                content=f"Successfully handled {domain} task: {task[:80]}",
                domain=domain,
                pattern_type="technique",
                source_tasks=[task_prefix],
            ))

        # Tool combination patterns
        unique_tools = sorted(set(tools_used))
        if len(unique_tools) >= 2:
            combo_key = "+".join(unique_tools[:4])
            primary_domain = domains[0] if domains else "general"
            entries.append(NotesEntry(
                topic=f"tool_combo:{combo_key}",
                content=f"Effective tool combination: {combo_key} for {primary_domain} tasks",
                domain=primary_domain,
                pattern_type="tool_combo",
                source_tasks=[task_prefix],
            ))

        # File structure knowledge
        if key_paths:
            extensions = set()
            for p in key_paths:
                ext = Path(p).suffix.lower()
                if ext:
                    extensions.add(ext)
            if extensions:
                entries.append(NotesEntry(
                    topic=f"file_types:{','.join(sorted(extensions)[:5])}",
                    content=f"Worked with {', '.join(sorted(extensions)[:5])} files in: {', '.join(key_paths[:3])}",
                    domain=domains[0] if domains else "general",
                    pattern_type="technique",
                    source_tasks=[task_prefix],
                ))

        return entries

    def _reflect(self, task, tools_used, outcome, success, latency,
                 judge_scores: list | None = None) -> list:
        """R3: Reflect — evaluate what worked/failed and why.

        OpenClaw-RL: if judge_scores provided, use average score to
        adjust confidence of strength/weakness entries.
        """
        entries: list[SelfEntry] = []
        domains = _detect_domains(f"{task} {outcome}")
        task_prefix = task[:60]

        # Compute judge-informed confidence adjustment
        judge_avg = None
        if judge_scores:
            scores = [getattr(js, "score", 5.0) for js in judge_scores]
            if scores:
                judge_avg = sum(scores) / len(scores)

        if success:
            # Strength: fast successful completion
            # Judge-adjusted confidence: high scores (>7) boost, low scores (<4) reduce
            base_confidence = 1.0 if latency < 60.0 else 0.7
            if judge_avg is not None:
                if judge_avg >= 7.0:
                    base_confidence = min(1.0, base_confidence + 0.15)
                elif judge_avg < 4.0:
                    base_confidence = max(0.3, base_confidence - 0.2)

            for domain in domains[:1]:
                if latency < 60.0:
                    entries.append(SelfEntry(
                        topic=f"strength:{domain}",
                        content=f"Efficient at {domain} tasks (completed in {latency:.0f}s)",
                        trait_type="strength",
                        confidence=base_confidence,
                        source_tasks=[task_prefix],
                    ))
                else:
                    entries.append(SelfEntry(
                        topic=f"capable:{domain}",
                        content=f"Capable at {domain} tasks (completed in {latency:.0f}s)",
                        trait_type="strength",
                        confidence=base_confidence,
                        source_tasks=[task_prefix],
                    ))
        else:
            # Weakness: failed task
            weakness_confidence = 0.6
            if judge_avg is not None and judge_avg < 3.0:
                weakness_confidence = 0.8  # strong weakness signal from judge

            for domain in domains[:1]:
                entries.append(SelfEntry(
                    topic=f"weakness:{domain}",
                    content=f"Struggled with {domain} task: {task[:60]}",
                    trait_type="weakness",
                    confidence=weakness_confidence,
                    source_tasks=[task_prefix],
                ))

        # Tool preference: most-used tools
        if tools_used:
            from collections import Counter
            top_tools = Counter(tools_used).most_common(2)
            for tool_name, count in top_tools:
                if count >= 2:
                    entries.append(SelfEntry(
                        topic=f"preference:{tool_name}",
                        content=f"Frequently uses {tool_name} (used {count}x in single task)",
                        trait_type="preference",
                        confidence=0.5,
                        source_tasks=[task_prefix],
                    ))

        return entries

    def _reweave(self, reduced: list, reflected: list,
                 directives: list | None = None) -> int:
        """R4: Reweave — integrate new knowledge, reinforce existing entries.

        OpenClaw-RL: also weaves in hindsight directives from reassignment analysis.
        """
        merged = 0
        for entry in reduced:
            # add() handles dedup internally — if topic+content prefix matches,
            # it reinforces rather than creating new
            before = self.notes_space.entry_count
            self.notes_space.add(entry)
            if self.notes_space.entry_count == before:
                merged += 1  # existing entry was reinforced

        for entry in reflected:
            before = self.self_space.entry_count
            self.self_space.add(entry)
            if self.self_space.entry_count == before:
                merged += 1

        # OpenClaw-RL: weave in contrastive directives
        if directives:
            for entry in directives:
                before = self.notes_space.entry_count
                self.notes_space.add(entry)
                if self.notes_space.entry_count == before:
                    merged += 1
            log.info("Wove %d directives into notes_space", len(directives))

        return merged

    def _verify(self) -> dict:
        """R5: Verify — check consistency, prune contradictions and stale entries."""
        pruned = 0
        contradictions = 0

        # Prune stale entries across all spaces
        pruned += self.self_space.prune_stale()
        pruned += self.notes_space.prune_stale()
        pruned += self.ops_space.prune_stale()

        # Resolve contradictions in self_space: strength vs weakness for same domain
        strength_topics: dict[str, VaultEntry] = {}
        weakness_topics: dict[str, VaultEntry] = {}

        for entry in self.self_space.entries:
            if not isinstance(entry, SelfEntry):
                continue
            # Extract domain from topic like "strength:python" or "weakness:python"
            parts = entry.topic.split(":", 1)
            if len(parts) == 2:
                trait, domain = parts
                if trait == "strength":
                    strength_topics[domain] = entry
                elif trait == "weakness":
                    weakness_topics[domain] = entry

        for domain in set(strength_topics) & set(weakness_topics):
            s = strength_topics[domain]
            w = weakness_topics[domain]
            # Keep the one with higher reinforcement, reduce confidence of other
            if s.reinforcement_count >= w.reinforcement_count:
                self.self_space.update_entry(w.entry_id, confidence=max(w.confidence - 0.3, 0.1))
            else:
                self.self_space.update_entry(s.entry_id, confidence=max(s.confidence - 0.3, 0.1))
            contradictions += 1

        return {"pruned": pruned, "contradictions_resolved": contradictions}

    def _rethink(self) -> dict:
        """R6: Rethink — recalculate specializations from accumulated knowledge."""
        # Count entries per domain in notes_space, weighted by confidence
        domain_scores: dict[str, float] = {}
        for entry in self.notes_space.entries:
            if isinstance(entry, NotesEntry) and entry.domain:
                domain_scores[entry.domain] = (
                    domain_scores.get(entry.domain, 0.0) + entry.confidence * entry.reinforcement_count
                )

        # Top 3 become specializations
        sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
        specializations = [d for d, _ in sorted_domains[:3]]

        # Update self_space with specialization entries
        # First, remove old auto-specializations
        for entry in list(self.self_space.entries):
            if isinstance(entry, SelfEntry) and entry.topic.startswith("auto_spec:"):
                self.self_space.remove(entry.entry_id)

        for i, spec in enumerate(specializations):
            score = domain_scores[spec]
            self.self_space.add(SelfEntry(
                topic=f"auto_spec:{spec}",
                content=f"Top-{i + 1} specialization: {spec} (score={score:.1f})",
                trait_type="specialization",
                confidence=min(score / 10.0, 1.0),
            ))

        return {
            "specializations": specializations,
            "total_knowledge_entries": self.notes_space.entry_count,
        }

    # ── Recall ─────────────────────────────────────────────────────────

    def recall_vault_context(self, task: str, limit: int = 5) -> str:
        """Query vault for relevant context, returning formatted string."""
        self_hits = self.self_space.find(task, limit=2)
        notes_hits = self.notes_space.find(task, limit=3)

        if not self_hits and not notes_hits:
            return ""

        lines = ["[AGENT VAULT — persistent knowledge from previous sessions]"]

        if self_hits:
            lines.append("  Identity:")
            for entry in self_hits:
                trait = getattr(entry, "trait_type", "")
                lines.append(f"  - [{trait}] {entry.content} (confidence={entry.confidence:.1f})")

        if notes_hits:
            lines.append("  Knowledge:")
            for entry in notes_hits:
                domain = getattr(entry, "domain", "")
                ptype = getattr(entry, "pattern_type", "")
                if ptype == "directive":
                    lines.append(f"  - [DIRECTIVE/{domain}] {entry.content}")
                else:
                    lines.append(
                        f"  - [{domain}/{ptype}] {entry.content} (reinforced x{entry.reinforcement_count})"
                    )

        lines.append("[END AGENT VAULT]\n")
        return "\n".join(lines)

    # ── Stats / Marketplace ────────────────────────────────────────────

    def vault_stats(self) -> dict:
        """Return stats for marketplace profile enrichment."""
        return {
            "self_entries": self.self_space.entry_count,
            "notes_entries": self.notes_space.entry_count,
            "ops_entries": self.ops_space.entry_count,
            "total_entries": (
                self.self_space.entry_count
                + self.notes_space.entry_count
                + self.ops_space.entry_count
            ),
        }

    def get_specializations(self) -> list[str]:
        """Extract top specializations from self_space."""
        specs = []
        for entry in self.self_space.entries:
            if isinstance(entry, SelfEntry) and entry.trait_type == "specialization":
                specs.append(entry.topic.replace("auto_spec:", ""))
        return specs

    def get_expertise_areas(self) -> list[dict]:
        """Extract domain expertise from notes_space with confidence scores."""
        domain_data: dict[str, dict] = {}
        for entry in self.notes_space.entries:
            if isinstance(entry, NotesEntry) and entry.domain:
                if entry.domain not in domain_data:
                    domain_data[entry.domain] = {"domain": entry.domain, "confidence": 0.0, "entries": 0}
                d = domain_data[entry.domain]
                d["confidence"] = max(d["confidence"], entry.confidence)
                d["entries"] += 1

        return sorted(domain_data.values(), key=lambda x: x["entries"], reverse=True)
