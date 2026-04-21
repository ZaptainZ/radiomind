"""Meta Layer — Dual Profiling (双侧写).

User Profile: WHO / HOW / WHAT — learned from conversations
Self Profile: IDENTITY / STATE / CAPABILITY — runtime introspection
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from radiomind.core.config import Config
from radiomind.core.types import MemoryStatus, SelfProfile, UserProfile
from radiomind.storage.database import MemoryStore

# Patterns for user profile extraction
WHO_PATTERNS = [
    (r"我(?:叫|是|名字是)\s*(\S+)", "name"),
    (r"我在(.+?)(?:工作|上班|上学|实习)", "occupation"),
    (r"我(?:在|来自|住在)\s*(.+?)(?:[，。,.\s]|$)", "location"),
    (r"我(?:做|从事)\s*(.+?)(?:工作|的|$)", "occupation"),
    (r"我(?:今年|已经)?(\d+)岁", "age"),
]

HOW_PATTERNS = [
    (r"我(?:喜欢|偏好|倾向于)\s*(.+)", "preference"),
    (r"我(?:不喜欢|讨厌|避免)\s*(.+)", "aversion"),
    (r"我(?:习惯|通常|一般)\s*(.+)", "habit"),
]

WHAT_PATTERNS = [
    (r"我(?:想要|打算|计划)\s*(.+)", "goal"),
    (r"我(?:正在|目前在)\s*(.+)", "current_focus"),
    (r"我(?:关注|关心)\s*(.+)", "interest"),
]


class ProfileManager:
    def __init__(self, data_dir: Path, config: Config, store: MemoryStore | None = None, habits=None):
        self._data_dir = data_dir
        self._config = config
        self._store = store
        self._habits = habits  # optional HabitStore for digest injection
        self._user = UserProfile()
        self._self = SelfProfile()
        # Self-observation — feeds dynamic calibration
        from radiomind.meta.behavior_log import BehaviorLog
        self._behavior = BehaviorLog(data_dir)

    @property
    def behavior(self):
        return self._behavior

    def open(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._load_user()
        self._load_self()
        self.refresh_self()

    def close(self) -> None:
        self._save_user()
        self._save_self()

    # --- User Profile ---

    @property
    def user(self) -> UserProfile:
        return self._user

    def update_from_text(self, text: str) -> bool:
        """Extract user profile info from a message. Returns True if updated."""
        updated = False

        for pattern, key in WHO_PATTERNS:
            match = re.search(pattern, text)
            if match:
                self._user.who[key] = match.group(1).strip()
                updated = True

        for pattern, key in HOW_PATTERNS:
            match = re.search(pattern, text)
            if match:
                val = match.group(1).strip()
                existing = self._user.how.get(key, "")
                if val not in existing:
                    self._user.how[key] = f"{existing}; {val}".lstrip("; ") if existing else val
                    updated = True

        for pattern, key in WHAT_PATTERNS:
            match = re.search(pattern, text)
            if match:
                self._user.what[key] = match.group(1).strip()
                updated = True

        if updated:
            self._user.updated_at = time.time()
            self._save_user()

        return updated

    def merge_profile_fragments(self, fragments: dict) -> bool:
        """Merge LLM-extracted fragments into persisted profile.

        fragments = {"who": {...}, "how": {...list[str]...}, "what": {...}}
        who: scalar fields (last non-empty wins).
        how/what: list fields (accumulate deduplicated, keep str for JSON).
        """
        if not isinstance(fragments, dict):
            return False
        updated = False

        for k, v in (fragments.get("who") or {}).items():
            if isinstance(v, str) and v.strip() and self._user.who.get(k) != v.strip():
                self._user.who[k] = v.strip()
                updated = True

        for category, target in (("how", self._user.how), ("what", self._user.what)):
            cat = fragments.get(category) or {}
            if not isinstance(cat, dict):
                continue
            for field, values in cat.items():
                if isinstance(values, str):
                    values = [values]
                if not isinstance(values, list):
                    continue
                existing_str = target.get(field, "")
                existing_parts = [p.strip() for p in existing_str.split(";") if p.strip()]
                merged_changed = False
                for v in values:
                    vs = str(v).strip()
                    if vs and vs not in existing_parts:
                        existing_parts.append(vs)
                        merged_changed = True
                if merged_changed:
                    target[field] = "; ".join(existing_parts)
                    updated = True

        if updated:
            self._user.updated_at = time.time()
            self._save_user()
        return updated

    def profile_hint(self, query: str, token_budget: int = 180) -> str:
        """Return a compact user-context prefix for answer prompts.

        Injects when the query seems preference-anchored (recommendation,
        suggestion, advice, personal style). Returns "" when profile is
        empty or query doesn't benefit. Kept short — doesn't blanket every
        answer prompt with context.
        """
        if not (self._user.who or self._user.how or self._user.what):
            return ""
        ql = (query or "").lower()
        preference_signals = (
            "recommend", "suggest", "advice", "tip", "prefer", "like",
            "should i", "what should", "any ideas", "建议", "推荐",
            "偏好", "喜欢",
        )
        if not any(s in ql for s in preference_signals):
            return ""

        parts = [
            "USER CONTEXT (accumulated profile — use as background when relevant to the question):",
        ]
        if self._user.who:
            who_str = ", ".join(f"{k}: {v}" for k, v in self._user.who.items() if v)
            if who_str:
                parts.append(f"- identity: {who_str}")
        for field, val in self._user.how.items():
            if val:
                parts.append(f"- {field}: {val}")
        for field, val in self._user.what.items():
            if val:
                parts.append(f"- {field}: {val}")
        text = "\n".join(parts) + "\n\n"
        # Rough budget
        if len(text) > token_budget * 4:
            text = text[: token_budget * 4] + "...\n\n"
        return text

    # --- Self Profile ---

    @property
    def self_profile(self) -> SelfProfile:
        return self._self

    def refresh_self(self) -> None:
        """Runtime introspection — update self-awareness."""
        backend = self._config.get("llm.default_backend", "ollama")
        model = self._config.get(f"llm.{backend}.model", "unknown")
        cost_mode = self._config.get("refinement.cost_mode", "economy")
        active_model = self._config.get(f"llm.models.{cost_mode}", model)

        self._self.identity = {
            "backend": backend,
            "model": model,
            "active_model": active_model,
            "cost_mode": cost_mode,
            "version": "0.1.0",
        }

        if self._store:
            stats = self._store.stats()
            self._self.state = {
                "memory_total": stats["total_active"],
                "memory_by_level": stats["by_level"],
                "memory_archived": stats["archived"],
                "domain_count": stats["domain_count"],
                "domains": [d["name"] for d in stats["domains"]],
            }
        else:
            self._self.state = {"memory_total": 0}

        self._self.capability = {
            "ollama_configured": bool(self._config.get("llm.ollama.host")),
            "cloud_configured": bool(self._config.get("llm.openai.api_key")),
            "cost_mode": self._config.get("refinement.cost_mode", "economy"),
        }

        self._self.updated_at = time.time()
        self._save_self()

    # --- Context Digest ---

    def get_calibration_hint(self) -> str:
        """Answer-side self-correction injected into answer prompts.

        The meta layer's role here: observe the system's own habits +
        identity and emit a short calibration directive that counters
        the downstream LLM's systematic biases.

        Current directives are static (qwen/gpt models both over-abstain
        on inferable questions; we ask the model to commit when signals
        converge). A future version could track per-run abstain rate via
        self._self.state and dial the directive up/down dynamically.

        Meant to be concatenated onto a Mem0-style answer prompt as a
        final paragraph — so the base prompt rules still apply, but the
        meta layer has the last word.
        """
        parts = [
            "CALIBRATION (from the memory system's self-observation):",
            "- If 3 or more retrieved memories point to the same fact, "
            "commit to that fact even when no single memory states it verbatim.",
            "- Prefer specific inferences over abstention when the question "
            "is answerable from the pattern of evidence, not just a literal match.",
            "- When a question uses 'previous' / 'former' / 'old', prefer the "
            "value whose memory date precedes any newer contradicting memory — "
            "that is the one that was superseded.",
        ]

        # Dynamic adjustment from behavior log (last N graded outcomes):
        # - If abstaining too often relative to accuracy, push to commit
        # - If low-evidence accuracy is poor, push to abstain instead
        try:
            stats = self._behavior.stats()
            if stats.get("n", 0) >= 20 and stats.get("graded_n", 0) >= 10:
                ar = stats.get("abstention_rate", 0.0)
                acc = stats.get("accuracy_overall", 0.0)
                # Over-abstaining when overall accuracy is still low → commit more
                if ar > 0.3 and acc < 0.85:
                    parts.append(
                        "- RECENT-SELF: abstention rate {:.0%} across {} answers; "
                        "when 2+ retrieved memories agree, commit rather than say "
                        "'information not enough'.".format(ar, stats['graded_n'])
                    )
                low = stats.get("by_density", {}).get("low", {})
                if low.get("n", 0) >= 10 and low.get("accuracy", 1.0) < 0.5:
                    parts.append(
                        "- RECENT-SELF: low-evidence answers are unreliable "
                        "({:.0%} on {} samples); when fewer than 3 memories support "
                        "an answer, prefer honest abstention over confabulation."
                        .format(low['accuracy'], low['n'])
                    )
        except Exception:
            pass
        # If we've accumulated habits, give the answer agent a one-line
        # summary so it anchors its answer on the user's established patterns.
        if self._habits is not None:
            try:
                confirmed = [
                    h for h in self._habits.all_habits()
                    if getattr(h, "status", "") == MemoryStatus.CONFIRMED
                ]
                if confirmed:
                    top = confirmed[:3]
                    lines = "; ".join(h.description[:60] for h in top)
                    parts.append(
                        f"- Known user patterns (lean on these): {lines}"
                    )
            except Exception:
                pass
        return "\n".join(parts)

    def get_digest(self, token_budget: int = 250) -> str:
        """Generate a compressed context digest for system prompt injection."""
        parts = []

        # User identity (L0 — always load, ~50 tokens)
        if self._user.who:
            who_str = ", ".join(f"{k}: {v}" for k, v in self._user.who.items())
            parts.append(f"User: {who_str}")

        # User preferences and goals (L1 — always load, ~120 tokens)
        if self._user.how:
            prefs = "; ".join(f"{v}" for v in self._user.how.values())
            parts.append(f"Style: {prefs}")

        if self._user.what:
            goals = "; ".join(f"{v}" for v in self._user.what.values())
            parts.append(f"Focus: {goals}")

        # System state (brief)
        if self._self.state.get("memory_total", 0) > 0:
            total = self._self.state["memory_total"]
            domains = self._self.state.get("domains", [])
            parts.append(f"Memory: {total} entries across {', '.join(domains[:5])}")

        parts.append(f"Model: {self._self.identity.get('model', '?')}")

        # Confirmed habits first (highest signal), then candidates.
        # Truncation cuts from the bottom → candidates get trimmed first.
        if self._habits is not None:
            all_h = self._habits.all_habits()
            confirmed = sorted(
                [h for h in all_h if h.status == MemoryStatus.CONFIRMED],
                key=lambda h: h.confidence, reverse=True,
            )
            candidates = sorted(
                [h for h in all_h if h.status == MemoryStatus.CANDIDATE],
                key=lambda h: h.confidence, reverse=True,
            )
            habit_lines = []
            for h in confirmed:
                habit_lines.append(f"  [confirmed] {h.description}")
            for h in candidates:
                habit_lines.append(f"  [candidate] {h.description}")
            if habit_lines:
                parts.append("Habits:\n" + "\n".join(habit_lines))

        digest = "\n".join(parts)

        # Rough token estimate: 1 token ≈ 2 Chinese chars or 4 English chars
        estimated_tokens = len(digest) // 2
        if estimated_tokens > token_budget:
            ratio = token_budget / estimated_tokens
            digest = digest[: int(len(digest) * ratio)]

        return digest

    # --- Persistence ---

    def _save_user(self) -> None:
        path = self._data_dir / "user_profile.json"
        data = {
            "who": self._user.who,
            "how": self._user.how,
            "what": self._user.what,
            "updated_at": self._user.updated_at,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load_user(self) -> None:
        path = self._data_dir / "user_profile.json"
        if not path.exists():
            return
        data = json.loads(path.read_text())
        self._user = UserProfile(
            who=data.get("who", {}),
            how=data.get("how", {}),
            what=data.get("what", {}),
            updated_at=data.get("updated_at", 0),
        )

    def _save_self(self) -> None:
        path = self._data_dir / "self_profile.json"
        data = {
            "identity": self._self.identity,
            "state": self._self.state,
            "capability": self._self.capability,
            "updated_at": self._self.updated_at,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load_self(self) -> None:
        path = self._data_dir / "self_profile.json"
        if not path.exists():
            return
        data = json.loads(path.read_text())
        self._self = SelfProfile(
            identity=data.get("identity", {}),
            state=data.get("state", {}),
            capability=data.get("capability", {}),
            updated_at=data.get("updated_at", 0),
        )
