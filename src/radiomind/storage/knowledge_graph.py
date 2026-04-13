"""Knowledge Graph — SQLite triples with temporal validity.

Inspired by mempalace: (subject, relation, object, valid_from, valid_until)
Supports timeline queries: "what was user doing in March 2026?"
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KG_SCHEMA = """
CREATE TABLE IF NOT EXISTS triples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    relation TEXT NOT NULL,
    object TEXT NOT NULL,
    valid_from REAL,
    valid_until REAL,
    source_id INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subject ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_relation ON triples(relation);
CREATE INDEX IF NOT EXISTS idx_object ON triples(object);
CREATE INDEX IF NOT EXISTS idx_valid ON triples(valid_from, valid_until);
"""

TRIPLE_EXTRACTION_PATTERNS = [
    (r"我(?:叫|是)\s*(\S+)", "user", "name_is", None),
    (r"我在(.+?)(?:工作|上班)", "user", "works_at", None),
    (r"我(?:在|住在|来自)\s*(\S+)", "user", "located_in", None),
    (r"我(?:喜欢|爱)\s*(.+)", "user", "likes", None),
    (r"我(?:讨厌|不喜欢)\s*(.+)", "user", "dislikes", None),
    (r"我(?:有|养了)\s*(.+)", "user", "has", None),
    (r"我(?:正在|目前在)\s*(.+)", "user", "currently_doing", None),
]


@dataclass
class Triple:
    subject: str
    relation: str
    object: str
    valid_from: float | None = None
    valid_until: float | None = None
    source_id: int | None = None
    confidence: float = 1.0
    id: int | None = None
    created_at: float = 0.0


class KnowledgeGraph:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(KG_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("KnowledgeGraph not opened")
        return self._conn

    def add_triple(
        self,
        subject: str,
        relation: str,
        obj: str,
        valid_from: float | None = None,
        source_id: int | None = None,
        confidence: float = 1.0,
    ) -> int:
        """Add a triple. Auto-invalidates conflicting triples for unique relations."""
        now = time.time()
        valid_from = valid_from or now

        # For unique relations (name_is, works_at, located_in), invalidate old ones
        if relation in ("name_is", "works_at", "located_in", "currently_doing"):
            self.conn.execute(
                "UPDATE triples SET valid_until = ? WHERE subject = ? AND relation = ? AND valid_until IS NULL",
                (now, subject, relation),
            )

        cur = self.conn.execute(
            "INSERT INTO triples (subject, relation, object, valid_from, valid_until, source_id, confidence, created_at) "
            "VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
            (subject, relation, obj, valid_from, source_id, confidence, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def query_entity(self, entity: str, as_of: float | None = None) -> list[Triple]:
        """Query all facts about an entity, optionally at a point in time."""
        if as_of is not None:
            rows = self.conn.execute(
                "SELECT * FROM triples WHERE subject = ? AND valid_from <= ? AND (valid_until IS NULL OR valid_until > ?) ORDER BY valid_from DESC",
                (entity, as_of, as_of),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM triples WHERE subject = ? AND valid_until IS NULL ORDER BY created_at DESC",
                (entity,),
            ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def query_relation(self, subject: str, relation: str) -> list[Triple]:
        """Query specific relation for a subject."""
        rows = self.conn.execute(
            "SELECT * FROM triples WHERE subject = ? AND relation = ? AND valid_until IS NULL ORDER BY created_at DESC",
            (subject, relation),
        ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def timeline(self, entity: str) -> list[Triple]:
        """Get full timeline of an entity (including expired facts)."""
        rows = self.conn.execute(
            "SELECT * FROM triples WHERE subject = ? ORDER BY valid_from ASC",
            (entity,),
        ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def invalidate(self, subject: str, relation: str, obj: str) -> None:
        """Mark a triple as no longer valid."""
        self.conn.execute(
            "UPDATE triples SET valid_until = ? WHERE subject = ? AND relation = ? AND object = ? AND valid_until IS NULL",
            (time.time(), subject, relation, obj),
        )
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM triples WHERE valid_until IS NULL").fetchone()[0]

    def extract_triples_from_text(self, text: str) -> list[tuple[str, str, str]]:
        """Extract triples from text using pattern matching."""
        import re
        extracted = []
        for pattern, subject, relation, _ in TRIPLE_EXTRACTION_PATTERNS:
            match = re.search(pattern, text)
            if match:
                obj = match.group(1).strip()
                if obj and len(obj) > 0:
                    extracted.append((subject, relation, obj))
        return extracted

    @staticmethod
    def _row_to_triple(row: sqlite3.Row) -> Triple:
        return Triple(
            id=row["id"],
            subject=row["subject"],
            relation=row["relation"],
            object=row["object"],
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            source_id=row["source_id"],
            confidence=row["confidence"],
            created_at=row["created_at"],
        )
