#!/usr/bin/env python3

import json


def main():
    # The global Codex Stop hook already enforces actionable RadioHeader
    # follow-up. Keep the project-level hook silent to avoid repetitive UI
    # noise every turn.
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
