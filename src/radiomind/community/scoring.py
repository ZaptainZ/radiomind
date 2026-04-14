"""Stigmergy scoring — bio-inspired pheromone decay model.

Like ant trails: frequently-used knowledge grows stronger,
abandoned knowledge fades naturally. No human curation needed.

Score formula:
  raw = positive_votes - negative_votes × 2
  decay = e^(-age_days / 180)     (half-life ~125 days)
  final = raw × decay

Verification threshold: usage ≥ 5 AND final_score ≥ 8
Archive threshold: age > 180 days with no votes, OR usage ≥ 10 AND score ≤ 0
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DECAY_HALF_LIFE = 125  # days
DECAY_LAMBDA = math.log(2) / DECAY_HALF_LIFE
VERIFY_MIN_USAGE = 5
VERIFY_MIN_SCORE = 8
ARCHIVE_MAX_AGE_DAYS = 180
NEGATIVE_WEIGHT = 2


@dataclass
class EntryScore:
    entry_id: str
    positive: int = 0
    negative: int = 0
    usage_count: int = 0
    first_seen: float = 0.0
    last_vote: float = 0.0
    verified: bool = False

    @property
    def raw_score(self) -> float:
        return self.positive - self.negative * NEGATIVE_WEIGHT

    @property
    def age_days(self) -> float:
        return (time.time() - self.first_seen) / 86400 if self.first_seen else 0

    @property
    def decay(self) -> float:
        return math.exp(-DECAY_LAMBDA * self.age_days)

    @property
    def final_score(self) -> float:
        return self.raw_score * self.decay

    @property
    def should_verify(self) -> bool:
        return self.usage_count >= VERIFY_MIN_USAGE and self.final_score >= VERIFY_MIN_SCORE

    @property
    def should_archive(self) -> bool:
        if self.age_days > ARCHIVE_MAX_AGE_DAYS and self.last_vote == 0:
            return True
        if self.usage_count >= 10 and self.final_score <= 0:
            return True
        return False


class ScoringEngine:
    """Manages votes and scores for community entries."""

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._scores: dict[str, EntryScore] = {}

    def open(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        (self._data_dir / "votes").mkdir(exist_ok=True)
        self._load_scores()

    def close(self) -> None:
        self._save_scores()

    def vote(self, entry_id: str, vote: int, user_hash: str = "") -> EntryScore:
        """Record a vote (+1 or -1) for an entry."""
        score = self._scores.setdefault(entry_id, EntryScore(entry_id=entry_id, first_seen=time.time()))
        now = time.time()

        if vote > 0:
            score.positive += 1
        elif vote < 0:
            score.negative += 1

        score.last_vote = now

        # Append to vote log
        month = time.strftime("%Y-%m")
        log_path = self._data_dir / "votes" / f"{month}.jsonl"
        log_entry = {
            "id": entry_id,
            "vote": vote,
            "ts": now,
            "hash": user_hash or self._anonymous_hash(),
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

        self._save_scores()
        return score

    def record_usage(self, entry_id: str) -> None:
        """Record that an entry was used (hit in search)."""
        score = self._scores.setdefault(entry_id, EntryScore(entry_id=entry_id, first_seen=time.time()))
        score.usage_count += 1

    def get_score(self, entry_id: str) -> EntryScore | None:
        return self._scores.get(entry_id)

    def get_verified(self) -> list[EntryScore]:
        return [s for s in self._scores.values() if s.should_verify]

    def get_archivable(self) -> list[EntryScore]:
        return [s for s in self._scores.values() if s.should_archive]

    def get_top(self, limit: int = 20) -> list[EntryScore]:
        scored = sorted(self._scores.values(), key=lambda s: s.final_score, reverse=True)
        return scored[:limit]

    def stats(self) -> dict[str, Any]:
        total = len(self._scores)
        verified = sum(1 for s in self._scores.values() if s.should_verify)
        archivable = sum(1 for s in self._scores.values() if s.should_archive)
        total_votes = sum(s.positive + s.negative for s in self._scores.values())
        return {
            "total_entries": total,
            "verified": verified,
            "archivable": archivable,
            "total_votes": total_votes,
        }

    def _load_scores(self) -> None:
        path = self._data_dir / "scores.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for entry_id, s in data.items():
                self._scores[entry_id] = EntryScore(
                    entry_id=entry_id,
                    positive=s.get("positive", 0),
                    negative=s.get("negative", 0),
                    usage_count=s.get("usage_count", 0),
                    first_seen=s.get("first_seen", 0),
                    last_vote=s.get("last_vote", 0),
                    verified=s.get("verified", False),
                )
        except Exception:
            pass

    def _save_scores(self) -> None:
        path = self._data_dir / "scores.json"
        data = {}
        for entry_id, s in self._scores.items():
            data[entry_id] = {
                "positive": s.positive,
                "negative": s.negative,
                "usage_count": s.usage_count,
                "first_seen": s.first_seen,
                "last_vote": s.last_vote,
                "verified": s.should_verify,
                "final_score": round(s.final_score, 2),
            }
        path.write_text(json.dumps(data, indent=2))

    @staticmethod
    def _anonymous_hash() -> str:
        return hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]
