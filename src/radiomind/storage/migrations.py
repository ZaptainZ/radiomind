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

CURRENT_SCHEMA_VERSION = 3

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
