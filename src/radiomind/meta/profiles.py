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
from radiomind.core.types import SelfProfile, UserProfile
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
    def __init__(self, data_dir: Path, config: Config, store: MemoryStore | None = None):
        self._data_dir = data_dir
        self._config = config
        self._store = store
        self._user = UserProfile()
        self._self = SelfProfile()

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
