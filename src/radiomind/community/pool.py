"""Community Pool — sync, import, contribute, and filter.

Handles:
1. Import from RadioHeader community pool (community/pool/*.md)
2. Contribute personal insights back (with PII filtering)
3. Sync community entries into RadioMind L4
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from radiomind.adapters.radioheader import parse_shortwave_file
from radiomind.community.scoring import ScoringEngine
from radiomind.core.mind import RadioMind
from radiomind.core.types import MemoryEntry, MemoryLevel, PrivacyLevel

RADIOHEADER_COMMUNITY = Path.home() / ".claude" / "radioheader" / "community"

# PII patterns to detect and filter
PII_PATTERNS = [
    (r"(?<!\d)1[3-9]\d{9}(?!\d)", "phone_cn"),
    (r"(?<!\d)\d{3}[-.]?\d{3}[-.]?\d{4}(?!\d)", "phone_us"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "email"),
    (r"\b\d{15,18}[Xx]?\b", "id_card_cn"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "ssn_us"),
    (r"/(?:Users|home)/[^/\s]+", "file_path"),
    (r"(?:sk-|api[_-]?key[=:]\s*)[A-Za-z0-9_-]{20,}", "api_key"),
    (r"(?:password|passwd|pwd)[=:]\s*\S+", "password"),
]

# Project/personal identifiers to strip
STRIP_PATTERNS = [
    r"\[(?:source|来源):?\s*\w+\]",  # [source:ProjectName]
    r"~/[^\s]+",  # home directory paths
    r"/Users/\w+/[^\s]+",  # absolute paths
]


@dataclass
class ContributeResult:
    contributed: int = 0
    filtered_pii: int = 0
    skipped_privacy: int = 0
    skipped_duplicate: int = 0


@dataclass
class SyncResult:
    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def detect_pii(text: str) -> list[tuple[str, str]]:
    """Detect PII in text. Returns list of (matched_text, pii_type)."""
    found = []
    for pattern, pii_type in PII_PATTERNS:
        for match in re.finditer(pattern, text):
            found.append((match.group(), pii_type))
    return found


def sanitize_for_sharing(text: str) -> str:
    """Remove project-specific and personal identifiers from text."""
    result = text
    for pattern in STRIP_PATTERNS:
        result = re.sub(pattern, "", result)
    return result.strip()


def contributor_hash(user_id: str, salt: str = "radiomind") -> str:
    """Generate anonymous contributor hash (irreversible)."""
    return hashlib.sha256(f"{user_id}:{salt}".encode()).hexdigest()[:16]


class CommunityPool:
    """Manages community knowledge sharing."""

    def __init__(self, mind: RadioMind, community_dir: Path | None = None):
        self._mind = mind
        self._community_dir = community_dir or (mind.config.home / "community")
        self._scoring = ScoringEngine(self._community_dir)

    def open(self) -> None:
        self._community_dir.mkdir(parents=True, exist_ok=True)
        (self._community_dir / "pool").mkdir(exist_ok=True)
        (self._community_dir / "contributions").mkdir(exist_ok=True)
        self._scoring.open()

    def close(self) -> None:
        self._scoring.close()

    # --- Sync from RadioHeader community ---

    def sync_from_radioheader(self, rh_community: Path | None = None) -> SyncResult:
        """Import entries from RadioHeader's community pool."""
        pool_dir = (rh_community or RADIOHEADER_COMMUNITY) / "pool"
        result = SyncResult()

        if not pool_dir.exists():
            result.errors.append(f"Community pool not found: {pool_dir}")
            return result

        for path in sorted(pool_dir.glob("sw-*.md")):
            parsed = parse_shortwave_file(path)
            if not parsed:
                result.errors.append(f"Parse failed: {path.name}")
                continue

            content_parts = []
            if parsed["symptom"]:
                content_parts.append(f"symptom: {parsed['symptom']}")
            if parsed["fix"]:
                content_parts.append(f"fix: {parsed['fix']}")
            if parsed["context"]:
                content_parts.append(f"context: {parsed['context']}")
            if not content_parts:
                content_parts.append(parsed["body"][:200])

            content = " | ".join(content_parts)
            entry = MemoryEntry(
                content=content,
                domain=parsed["domain"].split(",")[0].strip().lower() if parsed["domain"] else "community",
                level=MemoryLevel.PATTERN,
                metadata={
                    "source": "community",
                    "sw_id": parsed["id"],
                    "tags": parsed["tags"],
                },
            )
            mid = self._mind._store.add(entry)
            if mid > 0:
                result.imported += 1
                self._scoring.record_usage(parsed["id"])
            else:
                result.skipped += 1

        return result

    # --- Contribute personal insights ---

    def contribute(self, min_confidence: float = 0.7) -> ContributeResult:
        """Extract shareable insights from personal memories and habits."""
        result = ContributeResult()

        habits = self._mind._habits.all_habits()
        for habit in habits:
            if habit.confidence < min_confidence:
                continue

            # Check privacy
            related = self._mind.search(habit.description, domain=None)
            has_sealed = any(
                r.entry.privacy == PrivacyLevel.SEALED for r in related
            )
            if has_sealed:
                result.skipped_privacy += 1
                continue

            # PII check
            pii = detect_pii(habit.description)
            if pii:
                result.filtered_pii += 1
                continue

            # Sanitize
            clean = sanitize_for_sharing(habit.description)
            if not clean or len(clean) < 10:
                continue

            # Write contribution
            contrib_id = f"c-{contributor_hash(clean)[:12]}"
            contrib_path = self._community_dir / "contributions" / f"{contrib_id}.md"

            if contrib_path.exists():
                result.skipped_duplicate += 1
                continue

            contrib_content = (
                f"---\n"
                f"id: {contrib_id}\n"
                f"domain: general\n"
                f"tags: {clean[:50]}\n"
                f"contributor: {contributor_hash('local')}\n"
                f"timestamp: {time.time()}\n"
                f"---\n\n"
                f"{clean}\n"
            )
            contrib_path.write_text(contrib_content, encoding="utf-8")
            result.contributed += 1

        return result

    # --- Voting ---

    def vote(self, entry_id: str, vote: int) -> dict[str, Any]:
        """Vote on a community entry (+1 or -1)."""
        score = self._scoring.vote(entry_id, vote)
        return {
            "entry_id": entry_id,
            "final_score": round(score.final_score, 2),
            "verified": score.should_verify,
        }

    # --- Stats ---

    def stats(self) -> dict[str, Any]:
        scoring_stats = self._scoring.stats()
        pool_count = len(list((self._community_dir / "pool").glob("*.md"))) if (self._community_dir / "pool").exists() else 0
        contrib_count = len(list((self._community_dir / "contributions").glob("*.md"))) if (self._community_dir / "contributions").exists() else 0

        return {
            **scoring_stats,
            "pool_files": pool_count,
            "contributions": contrib_count,
        }
