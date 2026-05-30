"""Phase2-1b: a unified proof carrier for the COMMIT_ON_ABSTAIN closure
family (age_interval, cashback) — NOT the suppressor family (role,
temporal), which downgrade a concrete over-commit to an abstain and carry
no derived value (see 2026-05-31-phase2-proof-registry-audit-cc.md §3).

This module is intentionally domain-agnostic: it defines the dataclasses
only. Per-closure adapters (e.g. `cashback_proof_to_result` in
arithmetic_hint.py) build a ProofResult from that closure's existing proof.

Phase2-1b scope: carrier + cashback adapter as telemetry only. It does NOT
change any commit decision or output byte; closures still gate on their own
proof. 1c will migrate age (the real stress test — dual-source provenance).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Source:
    """One backing evidence pointer. `role` distinguishes which operand it
    supports when a proof has several (e.g. cashback rate vs amount, age
    at-event vs current). A list of these replaces the closures' flat
    source_turn_id/quote, which could not express dual/split provenance.
    """
    turn_id: str | None
    quote: str | None
    role: str | None = None


@dataclass(frozen=True)
class ProofResult:
    """Deterministic proof behind a commit-on-abstain rewrite.

    Fields are the audited intersection of the age + cashback proofs:
      kind          discriminator ("cashback" | "age_interval")
      value         raw derived value (e.g. 0.75, 7)
      inputs        operands used to derive value (e.g. {amount, rate})
      sources       >=1 evidence pointers (covers dual/split provenance)
      recompute_ok  the value was independently re-derived and matched
      rendered      the exact committed answer string
      subject       the question's subject anchor (merchant / person / None)
      scan_scope    SelfAnchor store-scan provenance, else None
      confidence    optional skill confidence (age sets it; cashback None)
    """
    kind: str
    value: Any
    inputs: dict
    sources: list[Source]
    recompute_ok: bool
    rendered: str
    subject: str | None = None
    scan_scope: str | None = None
    confidence: float | None = None
