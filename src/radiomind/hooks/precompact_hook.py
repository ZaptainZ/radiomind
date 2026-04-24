#!/usr/bin/env python3
"""RadioMind PreCompact Hook — emergency save before context compression.

Blocks compaction ONLY when no fresh memory has been ingested in the
recent save window. When the assistant has just called
`radiomind_ingest`, the hook approves (prints empty JSON) and the
compact proceeds.

Protocol:
  - Print "{}" (empty JSON) to approve.
  - Print {"decision": "block", "reason": ...} to block.

Behaviour:
  1. Resolve RadioMind data directory via $RADIOMIND_HOME, falling
     back to ~/.radiomind.
  2. If the SQLite DB or the `memories` table is missing (fresh
     install) → approve; there's nothing to save yet.
  3. Else, SELECT MAX(created_at) FROM memories. If it was written in
     the last `FRESH_INGEST_WINDOW_S` seconds (default 120) → approve.
  4. Else → block with SAVE_PROMPT so the assistant calls
     radiomind_ingest, and the next compact attempt (after the user
     re-issues /compact) approves.

Any unexpected exception falls through to approve — never wedge
compaction on a hook bug.
"""

import json
import os
import sqlite3
import time
from pathlib import Path


FRESH_INGEST_WINDOW_S = float(os.environ.get("RADIOMIND_COMPACT_FRESH_S", "120"))

SAVE_PROMPT = """Context is about to be compressed. Save important memories NOW:

1. Call radiomind_ingest with key messages from this conversation
2. Important: after compression, earlier messages will be summarized —
   save any specific facts, preferences, or decisions before they're lost

After saving, compression will proceed."""


def _radiomind_db_path() -> Path:
    home = os.environ.get("RADIOMIND_HOME") or str(Path.home() / ".radiomind")
    return Path(home) / "data" / "radiomind.db"


def _most_recent_memory_ts(db_path: Path) -> float | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT MAX(created_at) AS ts FROM memories"
        ).fetchone()
        conn.close()
        if row is None or row["ts"] is None:
            return None
        return float(row["ts"])
    except sqlite3.OperationalError:
        # memories table missing on fresh install
        return None
    except Exception:
        return None


def main() -> None:
    try:
        ts = _most_recent_memory_ts(_radiomind_db_path())
        if ts is None:
            # Fresh install / empty DB — nothing to lose, approve.
            print("{}")
            return
        if time.time() - ts <= FRESH_INGEST_WINDOW_S:
            # Recent ingest — assistant already saved; approve.
            print("{}")
            return
    except Exception:
        # Never wedge the user; approve on any unexpected error.
        print("{}")
        return

    # Stale — ask for save first.
    result = {"decision": "block", "reason": SAVE_PROMPT}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
