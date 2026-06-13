"""Hermes Agent Memory Provider — plugs RadioMind into the Hermes ecosystem.

Hermes Memory Provider API (from NousResearch/hermes-agent):
  Required: name, is_available, initialize, get_tool_schemas, handle_tool_call,
            get_config_schema, save_config
  Optional: system_prompt_block, prefetch, sync_turn, on_session_end,
            on_memory_write, queue_prefetch, on_pre_compress, shutdown

RadioMind provides cross-domain experience distillation that Hermes's
built-in MEMORY.md/USER.md doesn't have.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from radiomind.adapters.onboarding import (
    AuthorizationState,
    HostCapabilities,
    readiness_report,
)
from radiomind.core.config import Config
from radiomind.core.mind import RadioMind
from radiomind.core.types import Message

logger = logging.getLogger(__name__)


PROVIDER_NAME = "radiomind"

TOOL_SCHEMAS = [
    {
        "name": "radiomind_search",
        "description": "Search RadioMind's bionic memory (pyramid search across facts, patterns, principles + HDC habits)",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "domain": {"type": "string", "description": "Optional domain filter"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "radiomind_learn",
        "description": "Add external knowledge to RadioMind's memory (enters L2 facts, walks normal consolidation path)",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Knowledge to learn"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "radiomind_habits",
        "description": "Query RadioMind's L3 habit memories (deep, distilled patterns about the user)",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Query to match against habits"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "radiomind_status",
        "description": "Get RadioMind memory statistics",
        "parameters": {"type": "object", "properties": {}},
    },
]

CONFIG_SCHEMA = [
    {
        "key": "radiomind_home",
        "description": "RadioMind data directory (default: ~/.radiomind)",
        "default": str(Path.home() / ".radiomind"),
    },
    {
        "key": "cost_mode",
        "description": "Refinement cost mode",
        "choices": ["economy", "standard", "deep"],
        "default": "economy",
    },
    {
        "key": "auto_dream",
        "description": "Auto-trigger dream refinement on session end",
        "choices": ["true", "false"],
        "default": "true",
    },
]


class RadioMindProvider:
    """Hermes Agent Memory Provider implementation.

    Usage in Hermes:
        hermes memory setup  → select "radiomind"
        hermes config set memory.provider radiomind

    Or in plugin register():
        def register(ctx):
            ctx.register_memory_provider(RadioMindProvider())
    """

    def __init__(self):
        self._mind: RadioMind | None = None
        self._turn_count = 0
        self._lock = threading.Lock()
        # PersonalOnboarding-1c: background side effects are deny-by-default.
        # _auto_dream stays False until dream_after_session is granted.
        self._auto_dream = False
        self._hermes_home: Path | None = None
        self._capabilities = HostCapabilities()
        self._authz = AuthorizationState()

    # --- Required Methods ---

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        hermes_home = kwargs.get("hermes_home", "")
        self._hermes_home = Path(hermes_home) if hermes_home else None

        # PersonalOnboarding-1c: accept host capabilities + granted scopes
        # (additive; absent = most conservative). Accept either a
        # HostCapabilities / AuthorizationState instance or a plain mapping/
        # iterable, so hosts that only know dicts still work.
        caps = kwargs.get("capabilities")
        if isinstance(caps, HostCapabilities):
            self._capabilities = caps
        elif isinstance(caps, dict):
            known = {f for f in HostCapabilities().__dataclass_fields__}
            self._capabilities = HostCapabilities(
                **{k: v for k, v in caps.items() if k in known})
        else:
            self._capabilities = HostCapabilities()

        scopes = kwargs.get("authorized_scopes")
        if isinstance(scopes, AuthorizationState):
            self._authz = scopes
        else:
            self._authz = AuthorizationState.from_iterable(scopes)

        # dream_after_session grant flips the auto-dream default on.
        self._auto_dream = self._authz.has("dream_after_session")

        cfg = Config.load()
        llm_fn = kwargs.get("llm")
        self._mind = RadioMind(config=cfg, llm=llm_fn)
        self._mind.initialize()
        self._turn_count = 0

    def get_tool_schemas(self) -> list[dict]:
        return TOOL_SCHEMAS

    def handle_tool_call(self, name: str, args: dict) -> Any:
        if self._mind is None:
            return {"error": "RadioMind not initialized"}

        if name == "radiomind_search":
            results = self._mind.search(args["query"], domain=args.get("domain"))
            return [
                {
                    "content": r.entry.content,
                    "domain": r.entry.domain,
                    "level": r.entry.level.name,
                    "score": r.score,
                }
                for r in results[:10]
            ]

        elif name == "radiomind_learn":
            entries = self._mind.learn(args["text"])
            return {"learned": len(entries)}

        elif name == "radiomind_habits":
            habits = self._mind.query_habits(args["query"])
            return [
                {
                    "description": h.description,
                    "confidence": h.confidence,
                    "status": h.status.value,
                }
                for h in habits
            ]

        elif name == "radiomind_status":
            return self._mind.stats()

        return {"error": f"Unknown tool: {name}"}

    def get_config_schema(self) -> list[dict]:
        return CONFIG_SCHEMA

    def save_config(self, values: dict, hermes_home: str) -> None:
        if "cost_mode" in values:
            self._mind.update_config("refinement.cost_mode", values["cost_mode"])
        if "auto_dream" in values:
            self._auto_dream = values["auto_dream"].lower() == "true"

    # --- Optional Lifecycle Hooks ---

    def system_prompt_block(self) -> str:
        """Inject Context Digest into Hermes's system prompt."""
        if self._mind is None:
            return ""
        return self._mind.get_context_digest(token_budget=250)

    def prefetch(self, query: str) -> str:
        """Pre-fetch relevant memories before each turn."""
        if self._mind is None:
            return ""

        results = self._mind.search(query, domain=None)
        habits = self._mind.query_habits(query)

        parts = []
        if results:
            parts.append("Relevant memories:")
            for r in results[:5]:
                parts.append(f"  [{r.entry.level.name}/{r.entry.domain}] {r.entry.content}")

        if habits:
            parts.append("User habits:")
            for h in habits[:3]:
                parts.append(f"  - {h.description} (confidence={h.confidence:.1f})")

        return "\n".join(parts) if parts else ""

    def sync_turn(self, user_msg: str, assistant_msg: str) -> None:
        """Sync conversation turn to RadioMind (must be non-blocking).

        PersonalOnboarding-1c: deny-by-default. No auto-write unless
        `ingest_new_turns` is granted; no background refinement unless
        `background_refinement` is also granted.
        """
        if self._mind is None:
            return
        if not self._authz.has("ingest_new_turns"):
            logger.debug("sync_turn skipped_by_authorization (ingest_new_turns)")
            return

        refine_ok = self._authz.has("background_refinement")

        def _sync():
            with self._lock:
                messages = [
                    Message(role="user", content=user_msg),
                    Message(role="assistant", content=assistant_msg),
                ]
                self._mind.ingest(messages)
                self._turn_count += 1

            # Background refinement every 10 turns — only when authorized.
            if (refine_ok and self._turn_count % 10 == 0
                    and self._mind._llm.is_available()):
                try:
                    self._mind.trigger_chat()
                except Exception:
                    pass

        thread = threading.Thread(target=_sync, daemon=True)
        thread.start()

    def on_session_end(self, messages: list[dict]) -> None:
        """Run dream refinement on session end.

        PersonalOnboarding-1c: no-op unless `dream_after_session` is granted
        (_auto_dream is set from that grant at init; default off).
        """
        if self._mind is None or not self._auto_dream:
            if self._mind is not None:
                logger.debug("on_session_end skipped_by_authorization (dream_after_session)")
            return

        if self._mind._llm.is_available():
            try:
                self._mind.trigger_dream()
            except Exception:
                pass

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        """Mirror Hermes built-in memory writes to RadioMind.

        PersonalOnboarding-1c: mirroring host memory is an ongoing import —
        gated on `import_existing_memory`. No silent mirror by default.
        """
        if self._mind is None:
            return
        if not self._authz.has("import_existing_memory"):
            logger.debug("on_memory_write skipped_by_authorization (import_existing_memory)")
            return

        self._mind.learn(f"[hermes/{target}] {content}")

    def readiness(self) -> dict:
        """PersonalOnboarding-1c: project current capabilities + grants +
        state into a readiness report (pure — no IO/LLM/store writes)."""
        habit_count = example_count = 0
        llm_available = False
        if self._mind is not None:
            llm_available = self._mind.is_llm_available()
            habits = self._mind._habits.all_habits() if self._mind._habits else []
            habit_count = sum(
                1 for h in habits if h.status.value != "archived")
        return readiness_report(
            self._capabilities, self._authz,
            llm_available=llm_available,
            habit_count=habit_count, example_count=example_count,
        ).to_dict()

    def shutdown(self) -> None:
        if self._mind:
            self._mind.shutdown()
            self._mind = None


def register(ctx) -> None:
    """Hermes plugin discovery entry point."""
    ctx.register_memory_provider(RadioMindProvider())
