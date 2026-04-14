"""Setup RadioMind hooks for Claude Code / Codex CLI.

Detects RadioHeader and avoids conflict:
  - With RadioHeader: only adds Stop hook (ingest) + PreCompact
  - Without RadioHeader: adds Stop + PreCompact + SessionStart + MCP

Usage:
  radiomind setup-cc          # auto-detect and configure
  radiomind setup-cc --force  # overwrite existing config
  radiomind setup-cc --remove # remove RadioMind hooks
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any


def detect_radioheader() -> bool:
    """Check if RadioHeader is installed (hooks, CLI, or settings)."""
    # Check hooks directory
    hooks_dir = Path.home() / ".claude" / "hooks"
    if hooks_dir.exists():
        for f in hooks_dir.iterdir():
            if "radioheader" in f.name.lower():
                return True

    # Check settings.json for hook registrations
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
            hooks = settings.get("hooks", {})
            for event_hooks in hooks.values():
                if isinstance(event_hooks, list):
                    for h in event_hooks:
                        cmd = h.get("command", "") if isinstance(h, dict) else str(h)
                        if "radioheader" in cmd.lower():
                            return True
        except Exception:
            pass

    # Check RadioHeader data directory
    if (Path.home() / ".claude" / "radioheader").exists():
        return True

    # Check CLI
    return shutil.which("radioheader") is not None


def get_hook_paths() -> dict[str, Path]:
    """Get paths to hook scripts (installed alongside the package)."""
    hooks_dir = Path(__file__).parent
    return {
        "stop": hooks_dir / "stop_hook.py",
        "precompact": hooks_dir / "precompact_hook.py",
        "session_start": hooks_dir / "session_start_hook.sh",
    }


def ensure_executable(path: Path) -> None:
    """Make a file executable."""
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def setup_claude_code(force: bool = False) -> dict[str, Any]:
    """Register RadioMind hooks in Claude Code settings.json."""
    has_rh = detect_radioheader()
    hooks = get_hook_paths()
    result = {"radioheader_detected": has_rh, "hooks_added": [], "mcp_added": False}

    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        settings = {}

    if "hooks" not in settings:
        settings["hooks"] = {}

    # Ensure scripts are executable
    for path in hooks.values():
        if path.exists():
            ensure_executable(path)

    python = shutil.which("python3") or "python3"

    # --- Stop hook: always add (ingest conversations) ---
    stop_cmd = f"{python} {hooks['stop']}"
    _add_hook(settings, "Stop", stop_cmd, "radiomind-ingest", force)
    result["hooks_added"].append("Stop (auto-ingest every 15 messages)")

    # --- PreCompact hook: always add (emergency save) ---
    precompact_cmd = f"{python} {hooks['precompact']}"
    _add_hook(settings, "PreCompact", precompact_cmd, "radiomind-precompact", force)
    result["hooks_added"].append("PreCompact (emergency save before compression)")

    # --- SessionStart hook: only if NO RadioHeader ---
    if not has_rh:
        session_cmd = f"bash {hooks['session_start']}"
        _add_hook(settings, "SessionStart", session_cmd, "radiomind-digest", force)
        result["hooks_added"].append("SessionStart (inject context digest)")
    else:
        result["hooks_added"].append("SessionStart — skipped (RadioHeader handles this)")

    # --- MCP server: register if not already ---
    if "mcpServers" not in settings:
        settings["mcpServers"] = {}

    radiomind_cmd = shutil.which("radiomind") or "radiomind"
    if "radiomind" not in settings["mcpServers"] or force:
        settings["mcpServers"]["radiomind"] = {
            "command": radiomind_cmd,
            "args": ["mcp-server"],
        }
        result["mcp_added"] = True

    # Write settings
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False))
    result["settings_path"] = str(settings_path)

    return result


def remove_hooks() -> dict[str, Any]:
    """Remove RadioMind hooks from Claude Code settings."""
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return {"removed": False, "reason": "settings.json not found"}

    settings = json.loads(settings_path.read_text())
    removed = []

    # Remove hooks
    for event, hooks_list in settings.get("hooks", {}).items():
        if isinstance(hooks_list, list):
            before = len(hooks_list)
            hooks_list[:] = [
                h for h in hooks_list
                if not (isinstance(h, dict) and "radiomind" in h.get("command", "").lower())
            ]
            if len(hooks_list) < before:
                removed.append(event)

    # Remove MCP server
    if "radiomind" in settings.get("mcpServers", {}):
        del settings["mcpServers"]["radiomind"]
        removed.append("MCP server")

    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False))
    return {"removed": True, "items": removed}


def _add_hook(settings: dict, event: str, command: str, name: str, force: bool) -> None:
    """Add a hook entry, avoiding duplicates."""
    if event not in settings["hooks"]:
        settings["hooks"][event] = []

    hooks_list = settings["hooks"][event]
    if not isinstance(hooks_list, list):
        hooks_list = []
        settings["hooks"][event] = hooks_list

    # Check for existing radiomind hook
    for h in hooks_list:
        if isinstance(h, dict) and "radiomind" in h.get("command", "").lower():
            if force:
                hooks_list.remove(h)
                break
            else:
                return  # already registered

    hooks_list.append({
        "command": command,
        "name": name,
    })
