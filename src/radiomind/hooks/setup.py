"""Setup RadioMind for any AI coding agent.

Auto-detects platform and configures accordingly:
  Claude Code → plugin hooks + MCP (or settings.json fallback)
  Codex CLI   → .codex/hooks.json + MCP
  Cursor      → MCP config in settings
  Others      → MCP config instructions

Also detects RadioHeader and avoids conflict.

Usage:
  radiomind setup              # auto-detect platform and configure
  radiomind setup --force      # overwrite existing config
  radiomind setup --remove     # remove RadioMind config
  radiomind setup --platform codex  # force specific platform
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any


# --- Platform detection ---

def detect_platform() -> str:
    """Detect which AI coding platform is available."""
    # Claude Code
    if (Path.home() / ".claude").exists() or shutil.which("claude"):
        return "claude-code"
    # Codex CLI
    if (Path.home() / ".codex").exists() or shutil.which("codex"):
        return "codex"
    # Cursor
    cursor_paths = [
        Path.home() / ".cursor",
        Path.home() / "Library/Application Support/Cursor",
    ]
    if any(p.exists() for p in cursor_paths):
        return "cursor"
    # Windsurf
    if (Path.home() / ".windsurf").exists():
        return "windsurf"
    return "generic"


def detect_radioheader() -> bool:
    """Check if RadioHeader is installed."""
    hooks_dir = Path.home() / ".claude" / "hooks"
    if hooks_dir.exists():
        for f in hooks_dir.iterdir():
            if "radioheader" in f.name.lower():
                return True
    if (Path.home() / ".claude" / "radioheader").exists():
        return True
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
            for hooks_list in settings.get("hooks", {}).values():
                if isinstance(hooks_list, list):
                    for h in hooks_list:
                        if isinstance(h, dict) and "radioheader" in h.get("command", "").lower():
                            return True
        except Exception:
            pass
    return shutil.which("radioheader") is not None


def get_hook_paths() -> dict[str, Path]:
    hooks_dir = Path(__file__).parent
    return {
        "stop": hooks_dir / "stop_hook.py",
        "precompact": hooks_dir / "precompact_hook.py",
        "session_start": hooks_dir / "session_start_hook.sh",
    }


# --- Setup per platform ---

def setup(platform: str = "", force: bool = False) -> dict[str, Any]:
    """Setup RadioMind for the detected or specified platform."""
    if not platform:
        platform = detect_platform()

    has_rh = detect_radioheader()
    result = {
        "platform": platform,
        "radioheader_detected": has_rh,
        "actions": [],
    }

    if platform == "claude-code":
        _setup_claude_code(result, has_rh, force)
    elif platform == "codex":
        _setup_codex(result, has_rh, force)
    elif platform == "cursor":
        _setup_cursor(result, force)
    elif platform == "windsurf":
        _setup_mcp_generic(result, "windsurf", force)
    else:
        _setup_mcp_generic(result, "generic", force)

    return result


def remove(platform: str = "") -> dict[str, Any]:
    """Remove RadioMind configuration."""
    if not platform:
        platform = detect_platform()

    result = {"platform": platform, "removed": []}

    if platform == "claude-code":
        _remove_claude_code(result)
    elif platform == "codex":
        _remove_codex(result)

    return result


# --- Claude Code ---

def _setup_claude_code(result: dict, has_rh: bool, force: bool) -> None:
    hooks = get_hook_paths()
    python = shutil.which("python3") or "python3"
    radiomind_cmd = shutil.which("radiomind") or "radiomind"

    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}

    if "hooks" not in settings:
        settings["hooks"] = {}

    # Ensure executable
    for p in hooks.values():
        if p.exists():
            _ensure_executable(p)

    # Stop hook — always (ingest)
    _add_hook(settings, "Stop", f"{python} {hooks['stop']}", "radiomind-ingest", force)
    result["actions"].append("Stop hook: auto-ingest every 15 messages")

    # PreCompact — always (emergency save)
    _add_hook(settings, "PreCompact", f"{python} {hooks['precompact']}", "radiomind-precompact", force)
    result["actions"].append("PreCompact hook: emergency save before compression")

    # SessionStart — only without RadioHeader
    if not has_rh:
        _add_hook(settings, "SessionStart", f"bash {hooks['session_start']}", "radiomind-digest", force)
        result["actions"].append("SessionStart hook: inject context digest")
    else:
        result["actions"].append("SessionStart: skipped (RadioHeader handles)")

    # MCP
    if "mcpServers" not in settings:
        settings["mcpServers"] = {}
    if "radiomind" not in settings["mcpServers"] or force:
        settings["mcpServers"]["radiomind"] = {"command": radiomind_cmd, "args": ["mcp-server"]}
        result["actions"].append("MCP server: 9 tools registered")
    else:
        result["actions"].append("MCP server: already registered")

    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False))
    result["config_path"] = str(settings_path)


def _remove_claude_code(result: dict) -> None:
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return

    settings = json.loads(settings_path.read_text())

    for event, hooks_list in settings.get("hooks", {}).items():
        if isinstance(hooks_list, list):
            before = len(hooks_list)
            hooks_list[:] = [h for h in hooks_list if not (isinstance(h, dict) and "radiomind" in h.get("command", "").lower())]
            if len(hooks_list) < before:
                result["removed"].append(f"hook:{event}")

    if "radiomind" in settings.get("mcpServers", {}):
        del settings["mcpServers"]["radiomind"]
        result["removed"].append("MCP server")

    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False))


# --- Codex CLI ---

def _setup_codex(result: dict, has_rh: bool, force: bool) -> None:
    hooks = get_hook_paths()
    python = shutil.which("python3") or "python3"

    codex_dir = Path.home() / ".codex"
    codex_dir.mkdir(exist_ok=True)

    # Codex uses .codex/hooks.json
    hooks_path = codex_dir / "hooks.json"
    existing = json.loads(hooks_path.read_text()) if hooks_path.exists() else {}

    # Ensure executable
    for p in hooks.values():
        if p.exists():
            _ensure_executable(p)

    # Stop hook
    if "Stop" not in existing or force:
        existing["Stop"] = existing.get("Stop", [])
        existing["Stop"].append({
            "command": f"{python} {hooks['stop']}",
            "name": "radiomind-ingest",
        })
        result["actions"].append("Stop hook: auto-ingest")

    # SessionStart
    if not has_rh and ("SessionStart" not in existing or force):
        existing["SessionStart"] = existing.get("SessionStart", [])
        existing["SessionStart"].append({
            "command": f"bash {hooks['session_start']}",
            "name": "radiomind-digest",
        })
        result["actions"].append("SessionStart hook: inject digest")

    hooks_path.write_text(json.dumps(existing, indent=2))
    result["actions"].append("Codex hooks.json configured")
    result["config_path"] = str(hooks_path)

    # MCP via config.toml
    config_path = codex_dir / "config.toml"
    result["actions"].append(f"MCP: add to {config_path} manually if needed")


def _remove_codex(result: dict) -> None:
    hooks_path = Path.home() / ".codex" / "hooks.json"
    if not hooks_path.exists():
        return
    existing = json.loads(hooks_path.read_text())
    for event, hooks_list in existing.items():
        if isinstance(hooks_list, list):
            before = len(hooks_list)
            hooks_list[:] = [h for h in hooks_list if not (isinstance(h, dict) and "radiomind" in h.get("name", "").lower())]
            if len(hooks_list) < before:
                result["removed"].append(f"codex:{event}")
    hooks_path.write_text(json.dumps(existing, indent=2))


# --- Cursor ---

def _setup_cursor(result: dict, force: bool) -> None:
    radiomind_cmd = shutil.which("radiomind") or "radiomind"

    # Cursor uses MCP via settings
    cursor_mcp = Path.home() / ".cursor" / "mcp.json"
    cursor_mcp.parent.mkdir(parents=True, exist_ok=True)

    existing = json.loads(cursor_mcp.read_text()) if cursor_mcp.exists() else {}
    if "mcpServers" not in existing:
        existing["mcpServers"] = {}

    if "radiomind" not in existing["mcpServers"] or force:
        existing["mcpServers"]["radiomind"] = {"command": radiomind_cmd, "args": ["mcp-server"]}
        cursor_mcp.write_text(json.dumps(existing, indent=2))
        result["actions"].append("MCP server: registered in Cursor")
    else:
        result["actions"].append("MCP server: already registered in Cursor")

    result["config_path"] = str(cursor_mcp)


# --- Generic MCP ---

def _setup_mcp_generic(result: dict, platform: str, force: bool) -> None:
    radiomind_cmd = shutil.which("radiomind") or "radiomind"
    mcp_config = {
        "mcpServers": {
            "radiomind": {"command": radiomind_cmd, "args": ["mcp-server"]}
        }
    }
    result["actions"].append(f"Add this to your {platform} MCP config:")
    result["actions"].append(json.dumps(mcp_config, indent=2))
    result["config_path"] = "(manual — see above)"


# --- Helpers ---

def _ensure_executable(path: Path) -> None:
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _add_hook(settings: dict, event: str, command: str, name: str, force: bool) -> None:
    if event not in settings["hooks"]:
        settings["hooks"][event] = []
    hooks_list = settings["hooks"][event]
    if not isinstance(hooks_list, list):
        hooks_list = []
        settings["hooks"][event] = hooks_list

    for h in hooks_list:
        if isinstance(h, dict) and "radiomind" in h.get("command", "").lower():
            if force:
                hooks_list.remove(h)
                break
            else:
                return

    hooks_list.append({"command": command, "name": name})
