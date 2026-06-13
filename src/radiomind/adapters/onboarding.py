"""PersonalOnboarding-1c — host capabilities, authorization scopes, and a pure
readiness report for personal-agent onboarding.

Contract: projectBasicInfo/05_HOST_AGENT_CAPABILITIES_CONTRACT.md.

Governing rule: an undeclared capability or ungranted scope yields the
CONSERVATIVE behavior, never the permissive one. Defaults are all-off, so a
host that passes nothing gets no background side effects. No IO, no LLM, no
store access in this module — pure data + projection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class HostCapabilities:
    """What the host agent declares it can do. Fields describe ABILITY only —
    they never perform an action. All default conservative (no capability)."""
    host_name: str = "unknown"
    host_kind: str = "unknown"          # personal_agent | programming_agent | power_user | unknown
    # LLM
    has_host_llm: bool = False          # host has some LLM it could lend
    llm_call_available: bool = False    # a working (prompt, system)->str callable is wired now
    # User interaction
    can_prompt_user: bool = False
    # Data access (ability only; permission is AuthorizationState)
    can_import_memory: bool = False
    can_read_chat_history: bool = False
    can_read_files: bool = False
    # Background execution
    supports_background_hooks: bool = False
    supports_scheduled_tasks: bool = False
    # Retrieval
    has_embedding_provider: bool = False
    has_vector_store: bool = False
    # Misc host services
    can_open_external_url: bool = False
    can_store_persistent_config: bool = False


# Every side effect that requires user authorization (contract §2).
SCOPES = frozenset({
    "import_existing_memory",
    "ingest_new_turns",
    "write_long_term_memory",
    "background_refinement",
    "dream_after_session",
    "train_lora",
    "call_external_llm",
    "call_external_embedding",
    "export_or_upload_memory",
    "enable_background_hooks",
})


@dataclass(frozen=True)
class AuthorizationState:
    """Which scopes the user has granted. Deny-by-default: an absent scope is
    never treated as allowed."""
    granted: frozenset = field(default_factory=frozenset)

    @classmethod
    def from_iterable(cls, scopes: Iterable[str] | None) -> "AuthorizationState":
        if not scopes:
            return cls()
        # Keep only known scopes — an unknown string can never grant anything.
        return cls(granted=frozenset(s for s in scopes if s in SCOPES))

    def has(self, scope: str) -> bool:
        return scope in self.granted


@dataclass
class ReadinessReport:
    memory_import: str            # ready | skipped | blocked
    host_llm: str                 # ready | missing | degraded
    retrieval: str                # local_ready | fts_only | external_needed
    background_hooks: str         # authorized | not_authorized | unsupported
    lora: str                     # ready | needs_more_data | disabled
    privacy_status: str           # local_only | external_calls_authorized | export_authorized
    recommended_next_action: str

    def to_dict(self) -> dict:
        return {
            "memory_import": self.memory_import,
            "host_llm": self.host_llm,
            "retrieval": self.retrieval,
            "background_hooks": self.background_hooks,
            "lora": self.lora,
            "privacy_status": self.privacy_status,
            "recommended_next_action": self.recommended_next_action,
        }


# Thresholds mirror data_gen (kept local to avoid a training import here).
_LORA_MIN_HABITS = 5
_LORA_MIN_EXAMPLES = 30


def readiness_report(
    capabilities: HostCapabilities | None,
    authz: AuthorizationState | None,
    *,
    llm_available: bool,
    habit_count: int = 0,
    example_count: int = 0,
) -> ReadinessReport:
    """Pure projection of capabilities + grants + current state into a report.
    No IO, no LLM, no store access."""
    cap = capabilities or HostCapabilities()
    az = authz or AuthorizationState()

    # memory import
    if az.has("import_existing_memory") and cap.can_import_memory:
        memory_import = "ready"
    elif cap.can_import_memory:
        memory_import = "skipped"        # capable but not authorized
    else:
        memory_import = "blocked"        # host cannot import

    # host LLM
    if llm_available:
        host_llm = "ready"
    elif cap.has_host_llm:
        host_llm = "degraded"            # host has one but it's not wired
    else:
        host_llm = "missing"

    # retrieval
    if cap.has_vector_store or (cap.has_embedding_provider
                                and az.has("call_external_embedding")):
        retrieval = "local_ready"
    elif cap.has_embedding_provider:
        retrieval = "external_needed"    # embedder exists but call not authorized
    else:
        retrieval = "fts_only"

    # background hooks
    if not cap.supports_background_hooks:
        background_hooks = "unsupported"
    elif az.has("enable_background_hooks"):
        background_hooks = "authorized"
    else:
        background_hooks = "not_authorized"

    # lora
    if not az.has("train_lora"):
        lora = "disabled"
    elif habit_count >= _LORA_MIN_HABITS and example_count >= _LORA_MIN_EXAMPLES:
        lora = "ready"
    else:
        lora = "needs_more_data"

    # privacy ledger
    if az.has("export_or_upload_memory"):
        privacy_status = "export_authorized"
    elif az.has("call_external_llm") or az.has("call_external_embedding"):
        privacy_status = "external_calls_authorized"
    else:
        privacy_status = "local_only"

    # one recommended next action (most-blocking first)
    if host_llm == "missing":
        nxt = "wire a host LLM (connect with llm=...) to enable refinement"
    elif memory_import == "skipped":
        nxt = "grant import_existing_memory to bring in prior memory"
    elif not az.has("ingest_new_turns"):
        nxt = "grant ingest_new_turns so new conversations are remembered"
    elif not az.has("background_refinement"):
        nxt = "grant background_refinement to distill habits automatically"
    elif lora == "needs_more_data":
        nxt = "add more memories across topics, then train a LoRA adapter"
    else:
        nxt = "all set — memory, refinement, and retrieval are configured"

    return ReadinessReport(
        memory_import=memory_import,
        host_llm=host_llm,
        retrieval=retrieval,
        background_hooks=background_hooks,
        lora=lora,
        privacy_status=privacy_status,
        recommended_next_action=nxt,
    )
