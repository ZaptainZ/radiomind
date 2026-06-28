"""Schema migrations for the memories database.

Each migration is a callable `(conn) -> None` registered against the target
schema version it upgrades TO. `apply_migrations(conn)` reads the current
`schema_version` and runs every migration strictly greater than it, in order,
committing between steps.

Adding a new migration:
    1. Append a `@register(version=N)` function below.
    2. Bump `CURRENT_SCHEMA_VERSION` to N.
    3. Do NOT edit previous migrations — they've already run on existing DBs.
"""

from __future__ import annotations

from typing import Callable

CURRENT_SCHEMA_VERSION = 5

_MIGRATIONS: list[tuple[int, Callable]] = []


def register(version: int):
    def _wrap(fn: Callable):
        _MIGRATIONS.append((version, fn))
        _MIGRATIONS.sort(key=lambda x: x[0])
        return fn
    return _wrap


def apply_migrations(conn) -> int:
    """Run all migrations above the DB's current schema_version.

    Returns the final schema version after migrations.
    """
    # Ensure version table exists
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    row = conn.execute(
        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
    ).fetchone()
    current = row[0] if row else 0

    for target_version, fn in _MIGRATIONS:
        if target_version <= current:
            continue
        fn(conn)
        # Record only the new version; keep the table single-row semantically
        if row is None and current == 0:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (target_version,))
            row = (target_version,)
        else:
            conn.execute("UPDATE schema_version SET version = ?", (target_version,))
        current = target_version
        conn.commit()

    return current


# --- Migration bodies -----------------------------------------------------

@register(version=2)
def _add_privacy(conn) -> None:
    """Add the privacy column introduced in schema v2."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    if "privacy" not in cols:
        conn.execute(
            "ALTER TABLE memories ADD COLUMN privacy TEXT NOT NULL DEFAULT 'open'"
        )


@register(version=3)
def _add_multi_user_and_history(conn) -> None:
    """Add user_id / agent_id / session_id / updated_at + memory_history."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    for col, ddl in [
        ("updated_at", "ALTER TABLE memories ADD COLUMN updated_at REAL NOT NULL DEFAULT 0"),
        ("user_id", "ALTER TABLE memories ADD COLUMN user_id TEXT NOT NULL DEFAULT ''"),
        ("agent_id", "ALTER TABLE memories ADD COLUMN agent_id TEXT NOT NULL DEFAULT ''"),
        ("session_id", "ALTER TABLE memories ADD COLUMN session_id TEXT NOT NULL DEFAULT ''"),
    ]:
        if col not in cols:
            conn.execute(ddl)
    conn.execute("UPDATE memories SET updated_at = created_at WHERE updated_at = 0")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            old_content TEXT,
            new_content TEXT,
            changed_at REAL NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user ON memories(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent ON memories(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON memories(session_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_mem ON memory_history(memory_id)")


@register(version=4)
def _add_tags(conn) -> None:
    """Add `tags` column — comma-separated semantic labels for lateral linking.

    Enables query-time filtering/boost along attention focus (wants / focus
    entity / event kind) independent of the level hierarchy. Stored as a
    flat TEXT for simplicity; indexed via FTS over the tags column.
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    if "tags" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tags ON memories(tags)")


@register(version=5)
def _add_knowledge_library(conn) -> None:
    """Add the Knowledge Library (信息收集库) tables — captured external sources.

    This is a SEPARATE namespace from `memories`: the library holds documents the
    user deliberately collected (articles / papers / notes), NOT conversational
    memory. Kept in the same DB file but distinct tables so library recall never
    pollutes personal-memory recall.

    Claims / entities / relations are NOT modelled here — they reuse the existing
    knowledge_graph (triples + entity_aliases) so we don't grow a second KG. A
    library claim is a triple whose source_id points at a library_items.id.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS library_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            source_domain TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT 'article',
            author TEXT NOT NULL DEFAULT '',
            published_at REAL,
            captured_at REAL NOT NULL,
            language TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            short_summary TEXT NOT NULL DEFAULT '',
            key_points TEXT NOT NULL DEFAULT '[]',
            why_it_matters TEXT NOT NULL DEFAULT '',
            useful_for TEXT NOT NULL DEFAULT '[]',
            open_questions TEXT NOT NULL DEFAULT '[]',
            user_id TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS library_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            facet TEXT NOT NULL DEFAULT 'topic',
            aliases TEXT NOT NULL DEFAULT '[]',
            parent_id INTEGER,
            status TEXT NOT NULL DEFAULT 'active',
            created_at REAL NOT NULL,
            UNIQUE(name, facet)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS library_item_tags (
            item_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            source TEXT NOT NULL DEFAULT 'llm',
            created_at REAL NOT NULL,
            PRIMARY KEY (item_id, tag_id)
        )"""
    )
    # Full-text over the captured document's title + summary for library search.
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS library_items_fts USING fts5("
        "title, short_summary, content='library_items', content_rowid='id')"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lib_url ON library_items(source_url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lib_hash ON library_items(content_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lib_status ON library_items(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lib_user ON library_items(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lib_item_tags_tag ON library_item_tags(tag_id)")
