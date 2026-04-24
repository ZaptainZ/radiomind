#!/usr/bin/env python3
"""RadioMind PreCompact Hook — remind-then-approve on retry.

Behavior:
  First /compact attempt:
    → Block with SAVE_PROMPT so the assistant has a chance to call
      radiomind_ingest before the context window shrinks.
  Retry within COOLDOWN (default 10 min):
    → Approve (user saw the reminder; they can decide whether to save).
  Retry after COOLDOWN:
    → Treat as a fresh attempt; block and remind again.

Rationale: the hook is a **reminder**, not a penalty. Blocking every
compact forever is hostile — users end up disabling the hook. Blocking
only the first attempt in a window preserves the nudge while letting
users proceed once they've acknowledged it.

Protocol:
  - Print "{}" to approve.
  - Print {"decision": "block", "reason": ...} to block.
"""

import json
import os
import time
from pathlib import Path


COOLDOWN_S = float(os.environ.get("RADIOMIND_COMPACT_COOLDOWN_S", "600"))

SAVE_PROMPT = """Context is about to be compressed. Save important memories NOW:

1. Call radiomind_ingest with key messages from this conversation
2. Important: after compression, earlier messages will be summarized —
   save any specific facts, preferences, or decisions before they're lost

After saving, compression will proceed."""


def _radiomind_home() -> Path:
    return Path(os.environ.get("RADIOMIND_HOME") or str(Path.home() / ".radiomind"))


def _state_path() -> Path:
    return _radiomind_home() / "precompact_state.json"


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
        state = _read_state(_state_path())
        last_blocked_ts = state.get("last_blocked_ts")

        if isinstance(last_blocked_ts, (int, float)):
            age = now - float(last_blocked_ts)
            if 0 <= age <= COOLDOWN_S:
                # Recent block — user is retrying after seeing the
                # reminder. Approve and reset so a later /compact (far
                # enough in the future) gets its own reminder.
                _clear_state(_state_path())
                _approve()
                return

        # First attempt in this cooldown window — block + seed state.
        _write_state(_state_path(), {"last_blocked_ts": now})
        _block()
    except Exception:
        # Never wedge the user on our own bug.
        _approve()


if __name__ == "__main__":
    main()
