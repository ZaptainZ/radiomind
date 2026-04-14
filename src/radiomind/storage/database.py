"""SQLite 3D pyramid storage for L2 memory notes."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from radiomind.core.types import MemoryEntry, MemoryLevel, MemoryStatus, PrivacyLevel, SearchResult

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    timestamp REAL NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    parent_id INTEGER REFERENCES memories(id),
    status TEXT NOT NULL DEFAULT 'active',
    privacy TEXT NOT NULL DEFAULT 'open',
    embedding BLOB,
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_hit_at REAL NOT NULL DEFAULT 0,
    decay_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_3d ON memories(domain, level, timestamp);
CREATE INDEX IF NOT EXISTS idx_parent ON memories(parent_id);
CREATE INDEX IF NOT EXISTS idx_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_domain_level ON memories(domain, level);

CREATE TABLE IF NOT EXISTS domains (
    name TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    memory_count INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    tokenize='unicode61'
);
"""


class MemoryStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("MemoryStore not opened")
        return self._conn

    # --- Schema ---

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)

        row = self.conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        current_version = row[0] if row else 0

        if current_version < 2:
            # Migration: add privacy column if missing
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(memories)").fetchall()]
            if "privacy" not in cols:
                self.conn.execute("ALTER TABLE memories ADD COLUMN privacy TEXT NOT NULL DEFAULT 'open'")

        if row is None:
            self.conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
        elif current_version < SCHEMA_VERSION:
            self.conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        self.conn.commit()

    # --- CRUD ---

    def exists(self, content: str, domain: str = "") -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM memories WHERE content = ? AND domain = ? AND status = 'active' LIMIT 1",
            (content, domain),
        ).fetchone()
        return row is not None

    def add(self, entry: MemoryEntry, dedup: bool = True) -> int:
        if dedup and self.exists(entry.content, entry.domain):
            return -1

        cur = self.conn.execute(
            """INSERT INTO memories
               (content, domain, timestamp, level, parent_id, status, privacy, embedding,
                hit_count, last_hit_at, decay_count, created_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.content,
                entry.domain,
                entry.created_at,
                int(entry.level),
                entry.parent_id,
                entry.status.value,
                entry.privacy.value,
                entry.embedding,
                entry.hit_count,
                entry.last_hit_at,
                entry.decay_count,
                entry.created_at,
                json.dumps(entry.metadata),
            ),
        )
        row_id = cur.lastrowid
        self.conn.execute(
            "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
            (row_id, entry.content),
        )
        self.conn.commit()
        entry.id = row_id

        self._ensure_domain(entry.domain)
        return row_id

    def get(self, memory_id: int) -> MemoryEntry | None:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def update(self, entry: MemoryEntry) -> None:
        if entry.id is None:
            raise ValueError("Cannot update entry without id")
        self.conn.execute(
            """UPDATE memories SET content=?, domain=?, level=?, parent_id=?,
               status=?, privacy=?, embedding=?, hit_count=?, last_hit_at=?,
               decay_count=?, metadata=?
               WHERE id=?""",
            (
                entry.content,
                entry.domain,
                int(entry.level),
                entry.parent_id,
                entry.status.value,
                entry.privacy.value,
                entry.embedding,
                entry.hit_count,
                entry.last_hit_at,
                entry.decay_count,
                json.dumps(entry.metadata),
                entry.id,
            ),
        )
        self.conn.execute(
            "UPDATE memories_fts SET content=? WHERE rowid=?",
            (entry.content, entry.id),
        )
        self.conn.commit()

    def delete(self, memory_id: int) -> None:
        self.conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
        self.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.conn.commit()

    # --- Query ---

    def list_by_domain(
        self, domain: str, level: MemoryLevel | None = None, limit: int = 50
    ) -> list[MemoryEntry]:
        if level is not None:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE domain=? AND level=? AND status='active' "
                "ORDER BY timestamp DESC LIMIT ?",
                (domain, int(level), limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE domain=? AND status='active' "
                "ORDER BY level DESC, timestamp DESC LIMIT ?",
                (domain, limit),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def list_by_level(self, level: MemoryLevel, limit: int = 50) -> list[MemoryEntry]:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE level=? AND status='active' "
            "ORDER BY hit_count DESC, timestamp DESC LIMIT ?",
            (int(level), limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_children(self, parent_id: int) -> list[MemoryEntry]:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE parent_id=? AND status='active' ORDER BY timestamp DESC",
            (parent_id,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def count_by_domain_level(self, domain: str, level: MemoryLevel) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE domain=? AND level=? AND status='active'",
            (domain, int(level)),
        ).fetchone()
        return row[0]

    # --- Search ---

    def search_fts(self, query: str, limit: int = 10) -> list[SearchResult]:
        # Escape special FTS5 characters to prevent parse errors
        safe_query = self._sanitize_fts_query(query)
        if not safe_query:
            return []
        rows = self.conn.execute(
            """SELECT m.*, rank FROM memories_fts
               JOIN memories m ON memories_fts.rowid = m.id
               WHERE memories_fts MATCH ? AND m.status = 'active'
               ORDER BY rank LIMIT ?""",
            (safe_query, limit),
        ).fetchall()
        return [
            SearchResult(entry=self._row_to_entry(r), score=-r["rank"], method="fts")
            for r in rows
        ]

    def search_like(self, query: str, limit: int = 10) -> list[SearchResult]:
        escaped = query.replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE content LIKE ? ESCAPE '\\' AND status='active' "
            "ORDER BY timestamp DESC LIMIT ?",
            (pattern, limit),
        ).fetchall()
        return [SearchResult(entry=self._row_to_entry(r), score=1.0, method="like") for r in rows]

    def record_hit(self, memory_id: int) -> None:
        now = time.time()
        self.conn.execute(
            "UPDATE memories SET hit_count = hit_count + 1, last_hit_at = ? WHERE id = ?",
            (now, memory_id),
        )
        self.conn.commit()

    def increment_decay(self, memory_id: int) -> None:
        self.conn.execute(
            "UPDATE memories SET decay_count = decay_count + 1 WHERE id = ?",
            (memory_id,),
        )
        self.conn.commit()

    def archive(self, memory_id: int) -> None:
        self.conn.execute(
            "UPDATE memories SET status = 'archived' WHERE id = ?",
            (memory_id,),
        )
        self.conn.commit()

    # --- Domains ---

    def _ensure_domain(self, domain: str) -> None:
        if not domain:
            return
        existing = self.conn.execute(
            "SELECT name FROM domains WHERE name = ?", (domain,)
        ).fetchone()
        if existing is None:
            self.conn.execute(
                "INSERT INTO domains (name, created_at, memory_count) VALUES (?, ?, 1)",
                (domain, time.time()),
            )
        else:
            self.conn.execute(
                "UPDATE domains SET memory_count = memory_count + 1 WHERE name = ?",
                (domain,),
            )
        self.conn.commit()

    def list_domains(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT name, memory_count, created_at FROM domains ORDER BY memory_count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Stats ---

    def stats(self) -> dict[str, Any]:
        total = self.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status='active'"
        ).fetchone()[0]
        by_level = {}
        for lvl in MemoryLevel:
            by_level[lvl.name.lower()] = self.conn.execute(
                "SELECT COUNT(*) FROM memories WHERE level=? AND status='active'",
                (int(lvl),),
            ).fetchone()[0]
        archived = self.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status='archived'"
        ).fetchone()[0]
        domains = self.list_domains()
        return {
            "total_active": total,
            "by_level": by_level,
            "archived": archived,
            "domain_count": len(domains),
            "domains": domains,
        }

    # --- Internal ---

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Escape special FTS5 operators to prevent parse errors."""
        import re
        tokens = query.split()
        safe_tokens = []
        for t in tokens:
            cleaned = re.sub(r'[^\w\u4e00-\u9fff]', ' ', t).strip()
            if cleaned:
                safe_tokens.append(f'"{cleaned}"' if ' ' in cleaned else cleaned)
        return " ".join(safe_tokens)

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
        privacy_val = row["privacy"] if "privacy" in row.keys() else "open"
        return MemoryEntry(
            id=row["id"],
            content=row["content"],
            domain=row["domain"],
            level=MemoryLevel(row["level"]),
            parent_id=row["parent_id"],
            status=MemoryStatus(row["status"]),
            privacy=PrivacyLevel(privacy_val),
            embedding=row["embedding"],
            hit_count=row["hit_count"],
            last_hit_at=row["last_hit_at"],
            decay_count=row["decay_count"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
