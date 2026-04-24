"""PreCompact hook: approve when memory count grew since last block."""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HOOK = Path(__file__).parent.parent / "src" / "radiomind" / "hooks" / "precompact_hook.py"


def _make_db(home: Path, row_count: int, last_ts: float | None) -> None:
    data = home / "data"
    data.mkdir(parents=True, exist_ok=True)
    db = data / "radiomind.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY,
            content TEXT,
            created_at REAL,
            timestamp REAL DEFAULT 0,
            domain TEXT DEFAULT '',
            level INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active'
        )
    """)
    for i in range(row_count):
        conn.execute(
            "INSERT INTO memories (content, created_at) VALUES (?, ?)",
            (f"row-{i}", (last_ts if last_ts is not None else time.time())),
        )
    conn.commit()
    conn.close()


def _write_state(home: Path, last_blocked_count: int) -> None:
    (home / "precompact_state.json").write_text(
        json.dumps({"last_blocked_count": last_blocked_count})
    )


def _run_hook(home: Path, fresh_s: str = "600") -> dict:
    env = os.environ.copy()
    env["RADIOMIND_HOME"] = str(home)
    env["RADIOMIND_COMPACT_FRESH_S"] = fresh_s
    out = subprocess.check_output([sys.executable, str(HOOK)], env=env, timeout=10)
    text = out.decode().strip() or "{}"
    return json.loads(text)


def test_approves_when_no_db(tmp_path: Path) -> None:
    assert _run_hook(tmp_path) == {}


def test_first_block_when_no_state_and_stale(tmp_path: Path) -> None:
    # No state file, most recent memory well outside fresh window.
    _make_db(tmp_path, row_count=5, last_ts=time.time() - 3600)
    result = _run_hook(tmp_path)
    assert result.get("decision") == "block"
    # Hook should have seeded state now
    state_file = tmp_path / "precompact_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["last_blocked_count"] == 5


def test_first_call_approves_within_fresh_window(tmp_path: Path) -> None:
    # No state yet, but a memory was just written → fresh fallback.
    _make_db(tmp_path, row_count=3, last_ts=time.time())
    assert _run_hook(tmp_path) == {}
    # Approve path must NOT write state — keeps subsequent /compact
    # in fresh-ladder mode instead of demanding another save.
    assert not (tmp_path / "precompact_state.json").exists()


def test_approves_when_count_grew_since_block(tmp_path: Path) -> None:
    # State says we last blocked with 5 memories; now there are 7.
    _make_db(tmp_path, row_count=7, last_ts=time.time() - 3600)
    _write_state(tmp_path, last_blocked_count=5)
    assert _run_hook(tmp_path) == {}
    # State cleared on approve — resets the ladder.
    assert not (tmp_path / "precompact_state.json").exists()


def test_blocks_when_count_unchanged_since_block(tmp_path: Path) -> None:
    _make_db(tmp_path, row_count=5, last_ts=time.time() - 3600)
    _write_state(tmp_path, last_blocked_count=5)
    result = _run_hook(tmp_path)
    assert result.get("decision") == "block"
    # State count must not drop; bookkeeping stays at 5.
    state = json.loads((tmp_path / "precompact_state.json").read_text())
    assert state["last_blocked_count"] == 5


def test_approves_with_empty_table(tmp_path: Path) -> None:
    _make_db(tmp_path, row_count=0, last_ts=None)
    assert _run_hook(tmp_path) == {}
