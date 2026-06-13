"""SmallUserReadiness-1b — training-data diversity metrics.

A single-domain user should not be hard-refused (SmallUserReadiness-1a: the
>=2-domains guard blocks legitimate single-topic / technical users). But a
single domain CAN overfit if its examples are monotonous. These pure metrics
let data_gen allow a NARROW adapter only when the one domain is diverse
enough, and otherwise explain exactly why it still refused.

Pure / dependency-free → fully unit-testable without an LLM or store.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_STOP = {
    "the", "a", "an", "i", "you", "my", "your", "to", "of", "in", "on", "at",
    "and", "or", "for", "with", "is", "are", "am", "was", "were", "be", "it",
    "that", "this", "always", "usually", "often", "prefer", "like",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (s or "").lower())).strip()


def _tokens(s: str) -> list[str]:
    return [w for w in _norm(s).split() if len(w) > 2 and w not in _STOP]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class DiversityReport:
    habit_count: int
    example_count: int
    distinct_sources: int        # unique normalized source texts
    distinct_concept_tokens: int  # size of the content-word vocabulary
    near_dup_ratio: float        # fraction near-duplicate of an earlier source


def diversity_report(sources: list[str], habit_count: int,
                     near_dup_threshold: float = 0.8) -> DiversityReport:
    """Compute diversity over DISTINCT SOURCE statements (habit descriptions
    + facts), NOT the augmented examples — per-habit paraphrase variants are
    near-dups by construction and would falsely look monotonous.

    Vocabulary size (distinct content tokens) is used instead of a leading
    token: real habit descriptions share a common subject prefix ('The user
    …') so the lead token is almost always the same; vocabulary captures the
    actual concept spread."""
    norms = [_norm(a) for a in sources]
    token_sets = [set(_tokens(a)) for a in sources]
    near_dups = 0
    for i in range(len(sources)):
        for j in range(i):
            if norms[i] == norms[j] or _jaccard(token_sets[i], token_sets[j]) >= near_dup_threshold:
                near_dups += 1
                break
    n = len(sources)
    vocab: set[str] = set()
    for ts in token_sets:
        vocab |= ts
    return DiversityReport(
        habit_count=habit_count,
        example_count=n,
        distinct_sources=len({s for s in norms if s}),
        distinct_concept_tokens=len(vocab),
        near_dup_ratio=(near_dups / n) if n else 0.0,
    )


# Narrow-adapter diversity floor: conservative, only to block a monotonous
# single domain from overfitting. Does NOT lower the habit/example counts —
# those guards still apply; this only governs whether a 1-domain store may
# bypass the >=2-domains guard.
NARROW_MAX_NEAR_DUP = 0.5
NARROW_MIN_CONCEPTS = 12  # content-word vocabulary across distinct sources


def narrow_training_ok(report: DiversityReport) -> tuple[bool, str]:
    """Is a single-domain store diverse enough to train a narrow adapter?
    Returns (ok, reason-if-not)."""
    if report.near_dup_ratio > NARROW_MAX_NEAR_DUP:
        return False, (
            f"single domain too repetitive — {report.near_dup_ratio:.0%} of "
            f"sources are near-duplicates (max {NARROW_MAX_NEAR_DUP:.0%})"
        )
    if report.distinct_concept_tokens < NARROW_MIN_CONCEPTS:
        return False, (
            f"single domain too narrow — only {report.distinct_concept_tokens} "
            f"distinct concepts (need {NARROW_MIN_CONCEPTS})"
        )
    return True, ""
