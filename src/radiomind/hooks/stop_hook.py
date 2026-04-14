#!/usr/bin/env python3
"""RadioMind Stop Hook — auto-ingest conversations into memory.

Fires after every AI response. Counts human messages since last save.
When threshold reached, blocks the AI and asks it to save to RadioMind.

Works with both Claude Code and Codex CLI.

Logic:
  1. Read JSONL transcript, count human messages since last save
  2. < SAVE_INTERVAL → allow stop (return {})
  3. ≥ SAVE_INTERVAL → block stop, ask AI to call radiomind_ingest
  4. On second attempt (after save) → allow stop
"""

import json
import os
import sys
from pathlib import Path

SAVE_INTERVAL = int(os.environ.get("RADIOMIND_SAVE_INTERVAL", "15"))
STATE_FILE = Path.home() / ".radiomind" / ".hook-state.json"

SAVE_PROMPT = """You have accumulated {count} messages since your last memory save.
Before stopping, save the key information from this conversation to RadioMind:

1. Call radiomind_ingest with the important messages from this session
   (user preferences, decisions, facts worth remembering — skip greetings and noise)
2. If you notice recurring patterns, call radiomind_refine_step("prepare") to start refinement

After saving, you may stop."""


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_save_count": 0, "hook_active": False}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def count_human_messages(transcript_path: str) -> int:
    """Count human messages in JSONL transcript."""
    count = 0
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "human" or entry.get("role") == "user":
                        count += 1
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return count


def main():
    state = load_state()

    # Second attempt after save — allow stop
    if state.get("hook_active"):
        state["hook_active"] = False
        save_state(state)
        print("{}")
        return

    # Find transcript — passed as env var or argument
    transcript = os.environ.get("CLAUDE_TRANSCRIPT", "")
    if not transcript and len(sys.argv) > 1:
        transcript = sys.argv[1]

    if not transcript:
        # No transcript available — try to find it
        # Claude Code stores transcripts in session dirs
        print("{}")
        return

    total = count_human_messages(transcript)
    since_save = total - state.get("last_save_count", 0)

    if since_save < SAVE_INTERVAL:
        print("{}")
        return

    # Threshold reached — block and ask AI to save
    state["hook_active"] = True
    state["last_save_count"] = total
    save_state(state)

    result = {
        "decision": "block",
        "reason": SAVE_PROMPT.format(count=since_save),
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
