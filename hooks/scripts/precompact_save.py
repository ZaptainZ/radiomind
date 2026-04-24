#!/usr/bin/env python3
"""Legacy copy of PreCompact hook kept for backward compat.

The canonical source is src/radiomind/hooks/precompact_hook.py.
This file mirrors the canonical behaviour: block compaction ONLY when
no fresh memory was ingested in the recent save window, otherwise
approve so /compact can proceed.
"""
import sys
from pathlib import Path

# Delegate to the packaged hook so behaviour stays in one place.
_here = Path(__file__).resolve()
_root = _here.parents[2]  # repo root
_pkg = _root / "src" / "radiomind" / "hooks"
sys.path.insert(0, str(_pkg))

from precompact_hook import main as _main  # noqa: E402


if __name__ == "__main__":
    _main()
