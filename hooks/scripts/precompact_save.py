#!/usr/bin/env python3
"""RadioMind PreCompact Hook — emergency save before context compression.

Always blocks. Forces the AI to save everything to RadioMind before
the context window shrinks. This prevents memory loss during long sessions.
"""

import json

SAVE_PROMPT = """Context is about to be compressed. Save important memories NOW:

1. Call radiomind_ingest with key messages from this conversation
2. Important: after compression, earlier messages will be summarized —
   save any specific facts, preferences, or decisions before they're lost

After saving, compression will proceed."""


def main():
    result = {
        "decision": "block",
        "reason": SAVE_PROMPT,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
