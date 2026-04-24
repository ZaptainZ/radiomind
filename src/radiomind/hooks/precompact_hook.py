#!/usr/bin/env python3
"""RadioMind PreCompact Hook — emergency save before context compression.

Approves compaction ONLY when memory count grew since the previous
block — meaning the assistant actually called radiomind_ingest after
the last prompt. Falls back to a generous time window if no state
is available.

Protocol:
  - Print "{}" to approve.
  - Print {"decision": "block", "reason": ...} to block.

Decision logic:
  1. Fresh install (no DB / empty memories table) → approve; nothing
     to save yet.
  2. State file exists AND current count > last_blocked_count →
     approve (new memories written since the last block — save flow
     completed). Update state to current count.
  3. State file exists AND current count == last_blocked_count →
     block (user hit /compact again without ingesting). Keep state.
  4. No state file → treat as first-block: use a time window fallback
     (RADIOMIND_COMPACT_FRESH_S, default 600s) on MAX(created_at); if
     fresh, approve; otherwise block and seed state with current count.

Any unexpected exception falls through to approve — never wedge
compaction on a hook bug.
"""

import json
import os
import sqlite3
import time
from pathlib import Path


FRESH_INGEST_WINDOW_S = float(os.environ.get("RADIOMIND_COMPACT_FRESH_S", "1800"))

SAVE_PROMPT = """Context is about to be compressed. Save important memories NOW:

1. Call radiomind_ingest with key messages from this conversation
2. Important: after compression, earlier messages will be summarized —
   save any specific facts, preferences, or decisions before they're lost

After saving, compression will proceed."""


def _radiomind_home() -> Path:
    return Path(os.environ.get("RADIOMIND_HOME") or str(Path.home() / ".radiomind"))


def _db_path() -> Path:
    return _radiomind_home() / "data" / "radiomind.db"


def _state_path() -> Path:
    return _radiomind_home() / "precompact_state.json"


def _read_memories_snapshot(db_path: Path) -> tuple[int, float | None] | None:
    """Return (count, max_created_at) or None when DB/table missing."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT COUNT(*) AS n, MAX(created_at) AS ts FROM memories"
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return int(row["n"] or 0), (float(row["ts"]) if row["ts"] is not None else None)
    except sqlite3.OperationalError:
        return None
    except Exception:
        return None


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _write_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state))
    except Exception:
        pass


def _approve() -> None:
    print("{}")


def _block() -> None:
    print(json.dumps({"decision": "block", "reason": SAVE_PROMPT}))


def main() -> None:
    try:
        snapshot = _read_memories_snapshot(_db_path())
        if snapshot is None:
            # Fresh install / no DB / table missing — nothing to save.
            _approve()
            return
        count, ts = snapshot
        if count == 0:
            # Empty table — nothing to save yet.
            _approve()
            return

        state = _read_state(_state_path())
        last_blocked_count = state.get("last_blocked_count")

        if isinstance(last_blocked_count, int):
            if count > last_blocked_count:
                # Memories grew since the last block — save happened.
                # Clear state so we return to "fresh ladder" mode:
                # subsequent /compact within the time window still
                # approves without forcing another save.
                try:
                    _state_path().unlink()
                except FileNotFoundError:
                    pass
                except Exception:
                    pass
                _approve()
                return
            # Count unchanged → user hit /compact again without ingesting.
            # Keep state (don't bump) so future /compact still waits for
            # a real save.
            _block()
            return

        # No state yet: treat as first-ever compact request. Use time
        # window fallback — if the most recent memory is within the
        # fresh window, the user likely just ingested. Do NOT write
        # state on approve — keep the ladder in "fresh" mode.
        if ts is not None and (time.time() - ts) <= FRESH_INGEST_WINDOW_S:
            _approve()
            return

        # Stale and no state: block and seed state so the next call
        # can approve once the count grows.
        _write_state(_state_path(), {"last_blocked_count": count})
        _block()
    except Exception:
        # Never wedge the user.
        _approve()


if __name__ == "__main__":
    main()
