"""PreCompact hook: remind once, approve on retry within cooldown."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOOK = Path(__file__).parent.parent / "src" / "radiomind" / "hooks" / "precompact_hook.py"


def _run_hook(home: Path, cooldown: str = "600") -> dict:
    env = os.environ.copy()
    env["RADIOMIND_HOME"] = str(home)
    env["RADIOMIND_COMPACT_COOLDOWN_S"] = cooldown
    out = subprocess.check_output([sys.executable, str(HOOK)], env=env, timeout=10)
    text = out.decode().strip() or "{}"
    return json.loads(text)


def _seed_state(home: Path, ts: float) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "precompact_state.json").write_text(
        json.dumps({"last_blocked_ts": ts})
    )


def test_first_attempt_blocks_and_seeds_state(tmp_path: Path) -> None:
    result = _run_hook(tmp_path)
    assert result.get("decision") == "block"
    state_file = tmp_path / "precompact_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert "last_blocked_ts" in state


def test_retry_within_cooldown_approves_and_clears(tmp_path: Path) -> None:
    _seed_state(tmp_path, ts=time.time() - 30)  # 30s ago, well within 600s
    assert _run_hook(tmp_path) == {}
    assert not (tmp_path / "precompact_state.json").exists()


def test_retry_after_cooldown_blocks_again(tmp_path: Path) -> None:
    _seed_state(tmp_path, ts=time.time() - 3600)  # 1h ago, past default cooldown
    result = _run_hook(tmp_path)
    assert result.get("decision") == "block"
    # State should be refreshed with a new ts
    state = json.loads((tmp_path / "precompact_state.json").read_text())
    assert state["last_blocked_ts"] >= time.time() - 5


def test_corrupt_state_falls_through_to_block(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "precompact_state.json").write_text("not-json")
    result = _run_hook(tmp_path)
    # Treats as fresh attempt — block and seed new state.
    assert result.get("decision") == "block"


def test_env_override_short_cooldown(tmp_path: Path) -> None:
    _seed_state(tmp_path, ts=time.time() - 60)
    # Cooldown = 30s; 60s-ago state is now past cooldown → block.
    result = _run_hook(tmp_path, cooldown="30")
    assert result.get("decision") == "block"
