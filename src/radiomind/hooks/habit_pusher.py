"""Push confirmed habits to host platform's native memory layer.

Supports:
  Claude Code → ~/.claude/projects/{project}/memory/radiomind_habits.md
  Codex CLI   → .codex/AGENTS.md (append section)
  Cursor      → .cursorrules (append section)

Markers:
  Each habit is wrapped in start/end markers keyed by a stable 12-char
  hash of the description. All habits live inside a section wrapper.
  This lets RadioMind update/remove individual habits without disturbing
  user-written content around them.

  Markdown (CC / Codex):
    <!-- radiomind:habit:start:{hash} -->
    - {description} (confidence: 0.9, hits: 5)
    <!-- radiomind:habit:end:{hash} -->

  Plain text (Cursor):
    # radiomind:habit:start:{hash}
    # {description} (confidence: 0.9, hits: 5)
    # radiomind:habit:end:{hash}

Idempotent: safe to call multiple times.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from radiomind.core.types import Habit, MemoryStatus
from radiomind.hooks.setup import detect_platform


def habit_hash(habit: Habit) -> str:
    return hashlib.sha256(habit.description.encode()).hexdigest()[:12]


class HabitPusher:
    def __init__(self, platform: str | None = None, project_dir: Path | None = None):
        self.platform = platform or detect_platform()
        self.project_dir = project_dir or Path.cwd()

    def push(self, habits: list[Habit], dry_run: bool = False) -> dict:
        confirmed = [h for h in habits if h.status in (MemoryStatus.CONFIRMED, MemoryStatus.CANDIDATE)]
        target = self._resolve_target()
        if target is None:
            return {"path": None, "error": f"No writable target for platform '{self.platform}'"}

        use_md = target.suffix == ".md" or target.name.endswith(".md")
        existing = target.read_text() if target.exists() else ""
        existing_hashes = self._parse_hashes(existing, use_md)
        new_hashes = {habit_hash(h) for h in confirmed}

        content = existing
        written = updated = removed = 0

        for h_hash in existing_hashes - new_hashes:
            content = self._remove_block(content, h_hash, use_md)
            removed += 1

        for h in confirmed:
            h_hash = habit_hash(h)
            block = self._format_block(h, h_hash, use_md)
            if h_hash in existing_hashes:
                content = self._replace_block(content, h_hash, block, use_md)
                updated += 1
            else:
                content = self._insert(content, block, use_md)
                written += 1

        if not dry_run and content != existing:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        return {
            "path": str(target),
            "platform": self.platform,
            "written": written,
            "updated": updated,
            "removed": removed,
            "total_confirmed": len(confirmed),
            "dry_run": dry_run,
        }

    # --- Target resolution ---

    def _resolve_target(self) -> Path | None:
        if self.platform == "claude-code":
            project_key = str(self.project_dir).replace("/", "-").lstrip("-")
            return (
                Path.home() / ".claude" / "projects" / project_key
                / "memory" / "radiomind_habits.md"
            )
        elif self.platform == "codex":
            return self.project_dir / ".codex" / "AGENTS.md"
        elif self.platform == "cursor":
            return self.project_dir / ".cursorrules"
        return None

    # --- Marker parsing ---

    def _parse_hashes(self, content: str, md: bool) -> set[str]:
        pat = r"<!-- radiomind:habit:start:(\w+) -->" if md else r"# radiomind:habit:start:(\w+)"
        return set(re.findall(pat, content))

    def _format_block(self, h: Habit, h_hash: str, md: bool) -> str:
        desc = f"{h.description} (confidence: {h.confidence:.1f}, hits: {h.hit_count})"
        if md:
            return (
                f"<!-- radiomind:habit:start:{h_hash} -->\n"
                f"- {desc}\n"
                f"<!-- radiomind:habit:end:{h_hash} -->"
            )
        return (
            f"# radiomind:habit:start:{h_hash}\n"
            f"# {desc}\n"
            f"# radiomind:habit:end:{h_hash}"
        )

    def _remove_block(self, content: str, h_hash: str, md: bool) -> str:
        if md:
            pat = rf"<!-- radiomind:habit:start:{h_hash} -->.*?<!-- radiomind:habit:end:{h_hash} -->\n?"
        else:
            pat = rf"# radiomind:habit:start:{h_hash}\n.*?# radiomind:habit:end:{h_hash}\n?"
        return re.sub(pat, "", content, flags=re.DOTALL)

    def _replace_block(self, content: str, h_hash: str, block: str, md: bool) -> str:
        if md:
            pat = rf"<!-- radiomind:habit:start:{h_hash} -->.*?<!-- radiomind:habit:end:{h_hash} -->"
        else:
            pat = rf"# radiomind:habit:start:{h_hash}\n.*?# radiomind:habit:end:{h_hash}"
        return re.sub(pat, block, content, flags=re.DOTALL)

    def _insert(self, content: str, block: str, md: bool) -> str:
        end = "<!-- radiomind:section:end -->" if md else "# radiomind:section:end"
        if end in content:
            return content.replace(end, block + "\n\n" + end)
        # Create section
        if md:
            section = (
                "\n\n<!-- radiomind:section:start -->\n"
                "## RadioMind — Confirmed Habits\n\n"
                f"{block}\n\n"
                "<!-- radiomind:section:end -->\n"
            )
        else:
            section = (
                "\n\n# radiomind:section:start\n"
                "# === RadioMind — Confirmed Habits ===\n\n"
                f"{block}\n\n"
                "# radiomind:section:end\n"
            )
        return content + section
