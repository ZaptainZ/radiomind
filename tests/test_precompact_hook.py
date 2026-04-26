"""PreCompact hook: fresh-ingest aware seatbelt."""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HOOK = Path(__file__).parent.parent / "src" / "radiomind" / "hooks" / "precompact_hook.py"


def _run_hook(home: Path, cooldown: str = "600", fresh: str = "1800") -> dict:
    env = os.environ.copy()
    env["RADIOMIND_HOME"] = str(home)
    env["RADIOMIND_COMPACT_COOLDOWN_S"] = cooldown
    env["RADIOMIND_COMPACT_FRESH_S"] = fresh
    out = subprocess.check_output([sys.executable, str(HOOK)], env=env, timeout=10)
    text = out.decode().strip() or "{}"
    return json.loads(text)


def _seed_state(home: Path, ts: float) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "precompact_state.json").write_text(
        json.dumps({"last_blocked_ts": ts})
    )


def _seed_db(home: Path, last_created_at: float | None) -> None:
    """Create a minimal memories table; insert a row if ts is given."""
    data_dir = home / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db = data_dir / "radiomind.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS memories ("
            "id INTEGER PRIMARY KEY, content TEXT, created_at REAL)"
        )
        if last_created_at is not None:
            conn.execute(
                "INSERT INTO memories (content, created_at) VALUES (?, ?)",
                ("seed", last_created_at),
            )
        conn.commit()
    finally:
        conn.close()


def test_fresh_ingest_approves(tmp_path: Path) -> None:
    """Recent ingest (within FRESH_S) → approve, no state file written."""
    _seed_db(tmp_path, last_created_at=time.time() - 60)  # 1 min ago
    assert _run_hook(tmp_path) == {}
    assert not (tmp_path / "precompact_state.json").exists()


def test_no_db_falls_through_to_seatbelt(tmp_path: Path) -> None:
    """No DB at all → first attempt blocks (seatbelt path)."""
    result = _run_hook(tmp_path)
    assert result.get("decision") == "block"
    assert (tmp_path / "precompact_state.json").exists()


def test_empty_db_falls_through_to_seatbelt(tmp_path: Path) -> None:
    """Empty memories table → first attempt blocks (no fresh evidence)."""
    _seed_db(tmp_path, last_created_at=None)
    result = _run_hook(tmp_path)
    assert result.get("decision") == "block"


def test_stale_ingest_falls_through_to_seatbelt(tmp_path: Path) -> None:
    """Old ingest (past FRESH_S) → first attempt blocks."""
    _seed_db(tmp_path, last_created_at=time.time() - 7200)  # 2h ago
    result = _run_hook(tmp_path)
    assert result.get("decision") == "block"
    state_file = tmp_path / "precompact_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert "last_blocked_ts" in state


def test_retry_within_cooldown_approves_and_clears(tmp_path: Path) -> None:
    """No fresh ingest but recent block → approve and clear state."""
    _seed_db(tmp_path, last_created_at=time.time() - 7200)  # stale
    _seed_state(tmp_path, ts=time.time() - 30)  # 30s ago, well within 600s
    assert _run_hook(tmp_path) == {}
    assert not (tmp_path / "precompact_state.json").exists()


def test_retry_after_cooldown_blocks_again(tmp_path: Path) -> None:
    """Past cooldown + stale ingest → block again, refresh state."""
    _seed_db(tmp_path, last_created_at=time.time() - 7200)
    _seed_state(tmp_path, ts=time.time() - 3600)  # 1h ago, past 600s cooldown
    result = _run_hook(tmp_path)
    assert result.get("decision") == "block"
    state = json.loads((tmp_path / "precompact_state.json").read_text())
    assert state["last_blocked_ts"] >= time.time() - 5


def test_corrupt_state_falls_through_to_block(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "precompact_state.json").write_text("not-json")
    result = _run_hook(tmp_path)
    assert result.get("decision") == "block"


def test_env_override_short_cooldown(tmp_path: Path) -> None:
    """Past short cooldown → block again."""
    _seed_state(tmp_path, ts=time.time() - 60)
    result = _run_hook(tmp_path, cooldown="30")
    assert result.get("decision") == "block"


def test_env_override_short_fresh_window(tmp_path: Path) -> None:
    """Ingest just outside short fresh window → seatbelt blocks."""
    _seed_db(tmp_path, last_created_at=time.time() - 120)  # 2 min ago
    result = _run_hook(tmp_path, fresh="60")  # 1 min window
    assert result.get("decision") == "block"


def test_fresh_ingest_overrides_stale_cooldown(tmp_path: Path) -> None:
    """Fresh ingest wins even when cooldown state would also approve."""
    _seed_db(tmp_path, last_created_at=time.time() - 60)
    _seed_state(tmp_path, ts=time.time() - 30)
    assert _run_hook(tmp_path) == {}
    # Fresh path doesn't touch cooldown state — leaves it alone.
    assert (tmp_path / "precompact_state.json").exists()
