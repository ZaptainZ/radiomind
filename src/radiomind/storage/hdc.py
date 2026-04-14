"""Hyperdimensional Computing (HDC) for L3 habit memory.

Brain-inspired: fixed-width vectors, simple operations, zero dependencies beyond numpy.
10,000-bit bipolar vectors encode habits as holographic superpositions.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from radiomind.core.types import Habit, MemoryStatus

DEFAULT_DIM = 10000


class HDCCodebook:
    """Maps concept strings to random hypervectors (the 'alphabet')."""

    def __init__(self, dim: int = DEFAULT_DIM, seed: int = 42):
        self.dim = dim
        self._rng = np.random.default_rng(seed)
        self._vectors: dict[str, np.ndarray] = {}

    def get(self, concept: str) -> np.ndarray:
        if concept not in self._vectors:
            self._vectors[concept] = self._random_hv()
        return self._vectors[concept]

    def _random_hv(self) -> np.ndarray:
        return self._rng.choice(np.array([-1, 1], dtype=np.int8), size=self.dim)

    def save(self, path: Path) -> None:
        data = {k: v.tolist() for k, v in self._vectors.items()}
        path.write_text(json.dumps(data))

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        data = json.loads(path.read_text())
        self._vectors = {k: np.array(v, dtype=np.int8) for k, v in data.items()}


def bind(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Bind: encode association between A and B (like a synapse)."""
    return (a * b).astype(np.int8)


def bundle(*vecs: np.ndarray) -> np.ndarray:
    """Bundle: superpose multiple concepts (majority vote). Ties break to +1."""
    stacked = np.stack(vecs).astype(np.float32)
    summed = stacked.sum(axis=0)
    result = np.sign(summed)
    result[result == 0] = 1  # break ties to +1, preserving bipolar invariant
    return result.astype(np.int8)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two hypervectors."""
    dot = np.dot(a.astype(np.float32), b.astype(np.float32))
    return float(dot / len(a))


class HabitStore:
    """Persistent store for L3 habit memories using HDC."""

    def __init__(self, data_dir: Path, dim: int = DEFAULT_DIM):
        self.data_dir = data_dir
        self.dim = dim
        self.codebook = HDCCodebook(dim=dim)
        self._habits: list[Habit] = []
        self._vectors: list[np.ndarray] = []
        self._bundle: np.ndarray | None = None

    def open(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.codebook.load(self.data_dir / "codebook.json")
        self._load_habits()

    def close(self) -> None:
        self._save_habits()
        self.codebook.save(self.data_dir / "codebook.json")

    # --- Core Operations ---

    def add_habit(self, description: str, concepts: list[tuple[str, str]]) -> Habit:
        """Add a habit from concept pairs.

        concepts: list of (subject, predicate) pairs, e.g. [("user", "values autonomy")]
        """
        if not concepts:
            hv = self.codebook.get(description)
        else:
            parts = [bind(self.codebook.get(s), self.codebook.get(p)) for s, p in concepts]
            hv = bundle(*parts) if len(parts) > 1 else parts[0]

        habit = Habit(description=description)
        self._habits.append(habit)
        self._vectors.append(hv)
        self._bundle = None  # invalidate cache
        self._save_habits()
        return habit

    def query(self, query_concepts: list[str], top_k: int = 5) -> list[tuple[Habit, float]]:
        """Query habits by single-concept similarity."""
        if not self._vectors:
            return []

        if len(query_concepts) == 1:
            query_hv = self.codebook.get(query_concepts[0])
        else:
            parts = [self.codebook.get(c) for c in query_concepts]
            query_hv = bundle(*parts)

        scores = [(h, similarity(query_hv, v)) for h, v in zip(self._habits, self._vectors)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def query_by_pairs(
        self, concept_pairs: list[tuple[str, str]], top_k: int = 5
    ) -> list[tuple[Habit, float]]:
        """Query habits by bound concept pairs (matches encoding method)."""
        if not self._vectors:
            return []

        parts = [bind(self.codebook.get(s), self.codebook.get(p)) for s, p in concept_pairs]
        query_hv = bundle(*parts) if len(parts) > 1 else parts[0]

        scores = [(h, similarity(query_hv, v)) for h, v in zip(self._habits, self._vectors)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def get_bundle(self) -> np.ndarray | None:
        """Get the bundled superposition of all habits."""
        if self._bundle is None and self._vectors:
            self._bundle = bundle(*self._vectors)
        return self._bundle

    def remove(self, index: int) -> None:
        if 0 <= index < len(self._habits):
            self._habits.pop(index)
            self._vectors.pop(index)
            self._bundle = None
            self._save_habits()

    def confirm(self, index: int) -> None:
        if 0 <= index < len(self._habits):
            self._habits[index].status = MemoryStatus.CONFIRMED
            self._habits[index].verified_at = time.time()
            self._save_habits()

    @property
    def count(self) -> int:
        return len(self._habits)

    def all_habits(self) -> list[Habit]:
        return list(self._habits)

    # --- Persistence ---

    def _save_habits(self) -> None:
        habits_path = self.data_dir / "habits.json"
        vectors_path = self.data_dir / "habit_vectors.npy"

        data = []
        for h in self._habits:
            d = {
                "description": h.description,
                "status": h.status.value,
                "confidence": h.confidence,
                "source_ids": h.source_ids,
                "created_at": h.created_at,
                "verified_at": h.verified_at,
            }
            data.append(d)
        habits_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

        if self._vectors:
            np.save(str(vectors_path), np.stack(self._vectors))

    def _load_habits(self) -> None:
        habits_path = self.data_dir / "habits.json"
        vectors_path = self.data_dir / "habit_vectors.npy"

        if not habits_path.exists():
            return

        data = json.loads(habits_path.read_text())
        self._habits = [
            Habit(
                description=d["description"],
                status=MemoryStatus(d["status"]),
                confidence=d["confidence"],
                source_ids=d.get("source_ids", []),
                created_at=d["created_at"],
                verified_at=d.get("verified_at"),
            )
            for d in data
        ]

        if vectors_path.exists():
            arr = np.load(str(vectors_path))
            self._vectors = [arr[i] for i in range(arr.shape[0])]
        else:
            self._vectors = []

        self._bundle = None
