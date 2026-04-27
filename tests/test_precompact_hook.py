"""PreCompact hook: always approves, never blocks."""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parent.parent / "src" / "radiomind" / "hooks" / "precompact_hook.py"


def _run_hook(home: Path) -> dict:
    env = os.environ.copy()
    env["RADIOMIND_HOME"] = str(home)
    out = subprocess.check_output([sys.executable, str(HOOK)], env=env, timeout=10)
    text = out.decode().strip() or "{}"
    return json.loads(text)


def test_approves_with_no_data(tmp_path: Path) -> None:
    """Fresh sandbox, no DB, no state — must approve."""
    assert _run_hook(tmp_path) == {}


def test_approves_regardless_of_state_or_db(tmp_path: Path) -> None:
    """Even with stale state and stale DB, must approve.

    The user just typed /compact — that's their explicit decision.
    The Stop hook is the actual save protection; this hook never
    second-guesses the user's compaction request.
    """
    (tmp_path / "precompact_state.json").write_text(
        json.dumps({"last_blocked_ts": 0})
    )
    data = tmp_path / "data"
    data.mkdir()
    # Empty file is enough to prove we don't open it / branch on it.
    (data / "radiomind.db").write_text("")
    assert _run_hook(tmp_path) == {}


def test_does_not_create_state_file(tmp_path: Path) -> None:
    """Approve path must not seed state — there's no state to track."""
    _run_hook(tmp_path)
    assert not (tmp_path / "precompact_state.json").exists()
