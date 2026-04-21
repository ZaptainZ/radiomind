"""Behavior log — self-observation of answer outcomes.

Each answered query can be logged: (timestamp, wants, answer_shape,
evidence_count, outcome?). Stats aggregate accuracy per wants shape,
abstention rate, and evidence-density correlations. ProfileManager's
calibration hint reads these stats to dial itself dynamically.

Persistence: JSON-lines file next to self_profile.json. Append-only.
Bounded to last 1000 entries via natural rotation on read.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class BehaviorEvent:
    ts: float
    wants: str
    answer_shape: str
    evidence_count: int
    abstained: bool
    correct: bool | None  # None when unknown (no judge)


class BehaviorLog:
    def __init__(self, data_dir: Path, max_entries: int = 1000):
        self._dir = data_dir
        self._path = data_dir / "behavior_log.jsonl"
        self._max = max_entries

    def record(
        self,
        wants: str,
        answer_shape: str,
        evidence_count: int,
        abstained: bool = False,
        correct: bool | None = None,
    ) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            event = BehaviorEvent(
                ts=time.time(),
                wants=wants or "lookup",
                answer_shape=answer_shape or "sentence",
                evidence_count=int(evidence_count or 0),
                abstained=bool(abstained),
                correct=correct,
            )
            with self._path.open("a") as f:
                f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _load(self) -> list[BehaviorEvent]:
        if not self._path.exists():
            return []
        events: list[BehaviorEvent] = []
        try:
            with self._path.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        events.append(BehaviorEvent(**d))
                    except Exception:
                        continue
        except Exception:
            return []
        if len(events) > self._max:
            events = events[-self._max:]
        return events

    def stats(self) -> dict:
        events = self._load()
        if not events:
            return {"n": 0}

        total = len(events)
        abstain_n = sum(1 for e in events if e.abstained)
        graded = [e for e in events if e.correct is not None]
        graded_n = len(graded)
        correct_n = sum(1 for e in graded if e.correct)

        # Accuracy by wants
        wants_counts: dict[str, Counter] = {}
        for e in graded:
            wc = wants_counts.setdefault(e.wants, Counter())
            wc["total"] += 1
            if e.correct:
                wc["correct"] += 1

        by_wants = {
            w: {
                "n": c["total"],
                "accuracy": c["correct"] / c["total"] if c["total"] else 0.0,
            }
            for w, c in wants_counts.items()
        }

        # Accuracy bucketed by evidence density
        by_density = {"low": {"n": 0, "correct": 0},
                      "mid": {"n": 0, "correct": 0},
                      "high": {"n": 0, "correct": 0}}
        for e in graded:
            bucket = (
                "low" if e.evidence_count < 3
                else "mid" if e.evidence_count < 10
                else "high"
            )
            by_density[bucket]["n"] += 1
            if e.correct:
                by_density[bucket]["correct"] += 1
        for k, v in by_density.items():
            v["accuracy"] = v["correct"] / v["n"] if v["n"] else 0.0

        return {
            "n": total,
            "abstention_rate": abstain_n / total,
            "accuracy_overall": correct_n / graded_n if graded_n else 0.0,
            "graded_n": graded_n,
            "by_wants": by_wants,
            "by_density": by_density,
        }
