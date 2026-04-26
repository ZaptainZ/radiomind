#!/usr/bin/env python3
"""RadioMind PreCompact Hook — fresh-ingest aware seatbelt.

Decision order (first match wins):
  1. Recent ingest? Look at memories DB MAX(created_at). If a memory
     was written within FRESH_S (default 1800s = 30 min), approve.
     Stop hook auto-saves every ~15 messages, so an active session
     almost always lands here and /compact never feels blocked.
  2. Inside cooldown? If we blocked recently (within COOLDOWN_S,
     default 600s), the user has already seen the reminder — approve
     and clear state. They own the decision now.
  3. Otherwise: block once with SAVE_PROMPT, seed cooldown state.
     The user sees the reminder; the next /compact attempt approves.

Any unexpected error falls through to approve. The hook must never
wedge the user's compaction flow on its own bug.

Protocol:
  - Print "{}" to approve.
  - Print {"decision": "block", "reason": ...} to block.
"""

import json
import os
import sqlite3
import time
from pathlib import Path


FRESH_S = float(os.environ.get("RADIOMIND_COMPACT_FRESH_S", "1800"))
COOLDOWN_S = float(os.environ.get("RADIOMIND_COMPACT_COOLDOWN_S", "600"))

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


def _most_recent_memory_ts(db_path: Path) -> float | None:
    """Return MAX(created_at) from memories, or None if unavailable.

    Returns None for: missing DB, missing table, empty table, or any
    SQLite error. Callers treat None as 'no fresh ingest evidence'.
    """
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
        try:
            row = conn.execute(
                "SELECT MAX(created_at) FROM memories"
            ).fetchone()
        finally:
            conn.close()
        if not row or row[0] is None:
            return None
        return float(row[0])
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


def _clear_state(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _approve() -> None:
    print("{}")


def _block() -> None:
    print(json.dumps({"decision": "block", "reason": SAVE_PROMPT}))


def main() -> None:
    try:
        now = time.time()

        # 1. Fresh ingest — assistant (or stop_hook) just saved.
        last_ingest = _most_recent_memory_ts(_db_path())
        if last_ingest is not None and 0 <= now - last_ingest <= FRESH_S:
            _approve()
            return

        # 2. Cooldown — user already saw the reminder, retry approves.
        state = _read_state(_state_path())
        last_blocked_ts = state.get("last_blocked_ts")
        if isinstance(last_blocked_ts, (int, float)):
            age = now - float(last_blocked_ts)
            if 0 <= age <= COOLDOWN_S:
                _clear_state(_state_path())
                _approve()
                return

        # 3. Stale + first attempt in window — block once.
        _write_state(_state_path(), {"last_blocked_ts": now})
        _block()
    except Exception:
        _approve()


if __name__ == "__main__":
    main()
