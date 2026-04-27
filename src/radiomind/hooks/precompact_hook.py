#!/usr/bin/env python3
"""RadioMind PreCompact Hook — always approve.

History note: this hook used to block /compact in various
"the assistant should save first" scenarios (stale ingest, first
attempt in a cooldown window, etc). Every iteration found a new edge
case where the block was hostile to a user who had explicitly typed
/compact. The actual save protection is the Stop hook
(`stop_hook.py`), which auto-ingests every ~15 messages — that's
what makes long sessions safe, not blocking compaction.

So this hook is now a no-op that always approves. The file is kept
because it is registered in settings.json and so future async
pre-compaction work (e.g. fire-and-forget snapshot) has a place to
live without re-wiring hook config.

Protocol: print "{}" to approve. Errors fall through to approve.
"""


def main() -> None:
    print("{}")


if __name__ == "__main__":
    main()
