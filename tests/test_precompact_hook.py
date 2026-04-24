"""PreCompact hook: approve when fresh ingest, block otherwise."""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HOOK = Path(__file__).parent.parent / "src" / "radiomind" / "hooks" / "precompact_hook.py"


def _make_db(home: Path, last_ts: float | None) -> None:
    """Build a minimal ~/.radiomind/data/radiomind.db with optional row."""
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
    if last_ts is not None:
        conn.execute(
            "INSERT INTO memories (content, created_at) VALUES (?, ?)",
            ("hook-test", last_ts),
        )
    conn.commit()
    conn.close()


def _run_hook(home: Path) -> dict:
    env = os.environ.copy()
    env["RADIOMIND_HOME"] = str(home)
    # Force a tight window so stale mode is reliable across CI timing
    env["RADIOMIND_COMPACT_FRESH_S"] = "5"
    out = subprocess.check_output([sys.executable, str(HOOK)], env=env, timeout=10)
    text = out.decode().strip() or "{}"
    return json.loads(text)


def test_approves_when_no_db(tmp_path: Path) -> None:
    # Fresh install — no DB yet; hook should approve (empty JSON).
    result = _run_hook(tmp_path)
    assert result == {}


def test_approves_with_fresh_ingest(tmp_path: Path) -> None:
    _make_db(tmp_path, last_ts=time.time())
    result = _run_hook(tmp_path)
    assert result == {}, f"expected approve, got {result}"


def test_blocks_when_stale(tmp_path: Path) -> None:
    _make_db(tmp_path, last_ts=time.time() - 600)  # 10 min old
    result = _run_hook(tmp_path)
    assert result.get("decision") == "block"
    assert "radiomind_ingest" in result.get("reason", "")


def test_approves_when_empty_table(tmp_path: Path) -> None:
    _make_db(tmp_path, last_ts=None)  # table exists, no rows
    result = _run_hook(tmp_path)
    assert result == {}
