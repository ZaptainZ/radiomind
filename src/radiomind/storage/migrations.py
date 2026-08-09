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

CURRENT_SCHEMA_VERSION = 8

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


@register(version=6)
def _add_lifelog(conn) -> None:
    """Add the Life Log (生活日志) tables — time-anchored episodes + day profiles
    derived from the user's ambient audio.

    A THIRD namespace, separate from `memories` (conversation) and `library`
    (collected documents): distinct tables so life-log recall never pollutes
    personal-memory or library recall. People reuse the knowledge_graph.

    FTS covers activity + summary + topics (WIDER than library's title+summary) so
    "when did I talk about X" finds episodes by topic, not only by summary text.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lifelog_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL DEFAULT '',
            start_clock TEXT NOT NULL DEFAULT '',
            end_clock TEXT NOT NULL DEFAULT '',
            activity TEXT NOT NULL DEFAULT '',
            participants TEXT NOT NULL DEFAULT '[]',
            topics TEXT NOT NULL DEFAULT '[]',
            topics_text TEXT NOT NULL DEFAULT '',
            media TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            user_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lifelog_day_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL DEFAULT '',
            narrative TEXT NOT NULL DEFAULT '',
            people TEXT NOT NULL DEFAULT '[]',
            topics TEXT NOT NULL DEFAULT '[]',
            activities TEXT NOT NULL DEFAULT '[]',
            highlights TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            user_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS lifelog_episodes_fts USING fts5("
        "activity, summary, topics_text, content='lifelog_episodes', content_rowid='id')"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ll_ep_date ON lifelog_episodes(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ll_ep_status ON lifelog_episodes(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ll_ep_user ON lifelog_episodes(user_id)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ll_ep_natural "
        "ON lifelog_episodes(user_id, date, start_clock)"
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ll_day_natural ON lifelog_day_profiles(user_id, date)")


@register(version=7)
def _add_speakers(conn) -> None:
    """Speaker identity (声纹身份) + absolute timestamps for the life log.

    `speaker_turns` is the SOURCE OF TRUTH: one row per speech turn, holding the
    voice embedding forever. `speakers.id` is only a mutable pointer, and both
    `speaker_exemplars` and `speaker_centroids` are derived caches that can be
    rebuilt from the turns at any time. That is what makes merge/split reversible
    — storing centroids alone would make a wrong merge unrecoverable.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS speaker_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at REAL NOT NULL,
            ended_at REAL NOT NULL,
            date TEXT NOT NULL DEFAULT '',
            tz TEXT NOT NULL DEFAULT '',
            embedding BLOB NOT NULL,
            model_id TEXT NOT NULL DEFAULT '',
            dim INTEGER NOT NULL DEFAULT 0,
            speech_s REAL NOT NULL DEFAULT 0,
            quality REAL NOT NULL DEFAULT 0,
            region_type TEXT NOT NULL DEFAULT 'conversation',
            speaker_id INTEGER,
            confidence REAL NOT NULL DEFAULT 0,
            binding TEXT NOT NULL DEFAULT 'unknown',
            episode_id INTEGER,
            source_file TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            user_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS speakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            name_confidence REAL NOT NULL DEFAULT 0,
            name_evidence TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            is_wearer INTEGER NOT NULL DEFAULT 0,
            first_seen_at REAL NOT NULL DEFAULT 0,
            last_seen_at REAL NOT NULL DEFAULT 0,
            turn_count INTEGER NOT NULL DEFAULT 0,
            total_speech_s REAL NOT NULL DEFAULT 0,
            days_seen INTEGER NOT NULL DEFAULT 0,
            model_id TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS speaker_exemplars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            speaker_id INTEGER NOT NULL,
            turn_id INTEGER NOT NULL,
            embedding BLOB NOT NULL,
            model_id TEXT NOT NULL DEFAULT '',
            speech_s REAL NOT NULL DEFAULT 0,
            added_at REAL NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS speaker_centroids (
            speaker_id INTEGER PRIMARY KEY,
            centroid BLOB NOT NULL,
            model_id TEXT NOT NULL DEFAULT '',
            dim INTEGER NOT NULL DEFAULT 0,
            n_exemplars INTEGER NOT NULL DEFAULT 0,
            rebuilt_at REAL NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS speaker_merges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            old_speaker_id INTEGER NOT NULL,
            old_label TEXT NOT NULL DEFAULT '',
            new_speaker_id INTEGER NOT NULL,
            merged_at REAL NOT NULL,
            reason TEXT NOT NULL DEFAULT ''
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spk_turn_speaker ON speaker_turns(speaker_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spk_turn_date ON speaker_turns(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spk_turn_user ON speaker_turns(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spk_ex_speaker ON speaker_exemplars(speaker_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_spk_label ON speakers(user_id, label)")
    # A turn is uniquely keyed by (user, source recording, start) — re-running the
    # audio tool over the same file must not duplicate turns.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_spk_turn_natural "
        "ON speaker_turns(user_id, source_file, started_at)"
    )

    # Life log gains absolute time. `start_clock`/`end_clock` stay as display
    # fields; clock strings alone can't express a recording that crosses midnight.
    for col, decl in (
        ("started_at", "REAL NOT NULL DEFAULT 0"),
        ("ended_at", "REAL NOT NULL DEFAULT 0"),
        ("tz", "TEXT NOT NULL DEFAULT ''"),
    ):
        try:
            conn.execute(f"ALTER TABLE lifelog_episodes ADD COLUMN {col} {decl}")
        except Exception:
            pass  # column already present (re-run on a partially migrated DB)


@register(version=8)
def _add_speaker_distinct(conn) -> None:
    """Remember that two speakers are NOT the same person.

    This is the other half of asking the owner a merge question. Without it the
    pair keeps scoring above `merge_propose_at` and comes back as a candidate
    every time — so "ask once and be done" would never hold, and a feature meant
    to be helpful would turn into a weekly nag.

    Pairs are stored ordered (a_id < b_id) so the relation is symmetric by
    construction, and by speaker id rather than label because ids survive the
    renames and tombstones that merge/split leave behind.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS speaker_distinct (
            a_id INTEGER NOT NULL,
            b_id INTEGER NOT NULL,
            user_id TEXT NOT NULL DEFAULT '',
            marked_at REAL NOT NULL,
            PRIMARY KEY (a_id, b_id)
        )"""
    )
