"""RadioHeader Adapter — bridge RadioMind as RadioHeader's memory backend.

Handles:
1. Migration: import existing topics/shortwave into RadioMind L2
2. Search bridge: replace fts-search.py with RadioMind pyramid search
3. Consolidate bridge: replace attn-consolidate.py with RadioMind dream + digest
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from radiomind.core.mind import RadioMind
from radiomind.core.types import MemoryEntry, MemoryLevel

RADIOHEADER_HOME = Path.home() / ".claude" / "radioheader"


@dataclass
class MigrationResult:
    topics_imported: int = 0
    shortwave_imported: int = 0
    projects_imported: int = 0
    skipped_duplicates: int = 0
    errors: list[str] = field(default_factory=list)


def parse_topic_file(path: Path) -> list[dict[str, str]]:
    """Parse a RadioHeader topic file into entries.

    Format: free text with [source:ProjectName] tags and ## headings.
    """
    entries = []
    text = path.read_text(encoding="utf-8")
    current_section = path.stem

    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            if line.startswith("##"):
                current_section = line.lstrip("#").strip()
            continue

        source_match = re.match(r"\[(?:source|来源):?\s*(\w+)\]\s*(.*)", line)
        if source_match:
            project = source_match.group(1)
            content = source_match.group(2).strip()
        else:
            project = ""
            content = line

        if content and len(content) > 5:
            entries.append({
                "content": content,
                "source_project": project,
                "section": current_section,
                "file": path.name,
            })

    return entries


def parse_shortwave_file(path: Path) -> dict[str, Any] | None:
    """Parse a RadioHeader shortwave file (YAML frontmatter + body).

    Returns dict with id, domain, tags, refs, and body fields.
    """
    text = path.read_text(encoding="utf-8")

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not fm_match:
        return None

    frontmatter_text = fm_match.group(1)
    body = fm_match.group(2).strip()

    fm: dict[str, str] = {}
    for line in frontmatter_text.split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()

    context = ""
    symptom = ""
    fix_parts: list[str] = []
    in_fix = False

    for line in body.split("\n"):
        line_stripped = line.strip()
        if line_stripped.startswith("context:"):
            context = line_stripped[len("context:"):].strip()
            in_fix = False
        elif line_stripped.startswith("symptom:"):
            symptom = line_stripped[len("symptom:"):].strip()
            in_fix = False
        elif line_stripped.startswith("fix:"):
            inline = line_stripped[len("fix:"):].strip()
            if inline:
                fix_parts.append(inline)
            in_fix = True
        elif in_fix and line_stripped.startswith("- "):
            fix_parts.append(line_stripped[2:])
        elif in_fix and not line_stripped:
            in_fix = False

    fix = "; ".join(fix_parts)

    return {
        "id": fm.get("id", path.stem),
        "domain": fm.get("domain", ""),
        "tags": fm.get("tags", ""),
        "refs": fm.get("refs", ""),
        "context": context,
        "symptom": symptom,
        "fix": fix,
        "body": body,
    }


class RadioHeaderAdapter:
    """Bridge between RadioHeader and RadioMind."""

    def __init__(self, mind: RadioMind, radioheader_home: Path | None = None):
        self._mind = mind
        self._rh_home = radioheader_home or RADIOHEADER_HOME

    # --- Migration ---

    def migrate(self) -> MigrationResult:
        """Import all existing RadioHeader data into RadioMind."""
        result = MigrationResult()

        self._migrate_topics(result)
        self._migrate_shortwave(result)
        self._migrate_registry(result)

        return result

    def _migrate_topics(self, result: MigrationResult) -> None:
        topics_dir = self._rh_home / "topics"
        if not topics_dir.exists():
            return

        for path in sorted(topics_dir.glob("*.md")):
            entries = parse_topic_file(path)
            for entry_data in entries:
                domain = self._infer_domain(entry_data["file"], entry_data.get("section", ""))
                entry = MemoryEntry(
                    content=entry_data["content"],
                    domain=domain,
                    level=MemoryLevel.FACT,
                    metadata={
                        "source": "radioheader-topic",
                        "file": entry_data["file"],
                        "source_project": entry_data["source_project"],
                    },
                )
                mid = self._mind._store.add(entry)
                if mid > 0:
                    result.topics_imported += 1
                else:
                    result.skipped_duplicates += 1

    def _migrate_shortwave(self, result: MigrationResult) -> None:
        sw_dir = self._rh_home / "shortwave"
        if not sw_dir.exists():
            return

        for path in sorted(sw_dir.glob("sw-*.md")):
            parsed = parse_shortwave_file(path)
            if not parsed:
                result.errors.append(f"Failed to parse: {path.name}")
                continue

            content_parts = []
            if parsed["symptom"]:
                content_parts.append(f"symptom: {parsed['symptom']}")
            if parsed["fix"]:
                content_parts.append(f"fix: {parsed['fix']}")
            if parsed["context"]:
                content_parts.append(f"context: {parsed['context']}")
            if not content_parts:
                content_parts.append(parsed["body"][:200])

            content = " | ".join(content_parts)
            domain_raw = parsed["domain"].split(",")[0].strip().lower() if parsed["domain"] else ""
            domain = self._normalize_domain(domain_raw)

            entry = MemoryEntry(
                content=content,
                domain=domain,
                level=MemoryLevel.PATTERN,
                metadata={
                    "source": "radioheader-shortwave",
                    "sw_id": parsed["id"],
                    "tags": parsed["tags"],
                    "refs": parsed["refs"],
                },
            )
            mid = self._mind._store.add(entry)
            if mid > 0:
                result.shortwave_imported += 1
            else:
                result.skipped_duplicates += 1

    def _migrate_registry(self, result: MigrationResult) -> None:
        reg_path = self._rh_home / "project-registry.json"
        if not reg_path.exists():
            return

        try:
            data = json.loads(reg_path.read_text())
            for proj in data.get("projects", []):
                content = f"项目: {proj['name']} | 技术栈: {proj.get('tech_stack', '?')} | 关注: {', '.join(proj.get('problems', []))}"
                entry = MemoryEntry(
                    content=content,
                    domain="projects",
                    level=MemoryLevel.FACT,
                    metadata={
                        "source": "radioheader-registry",
                        "project_name": proj["name"],
                        "path": proj.get("path", ""),
                    },
                )
                mid = self._mind._store.add(entry)
                if mid > 0:
                    result.projects_imported += 1
        except Exception as e:
            result.errors.append(f"Registry parse error: {e}")

    # --- Search Bridge ---

    def search(self, query: str, limit: int = 10, attention: bool = False) -> dict[str, Any]:
        """Search interface compatible with RadioHeader's fts-search.py output format."""
        results = self._mind.search_pyramid(query)

        formatted_results = []
        for r in results[:limit]:
            meta = r.entry.metadata or {}
            formatted_results.append({
                "id": meta.get("sw_id", str(r.entry.id)),
                "source": meta.get("source", "radiomind"),
                "domain": r.entry.domain,
                "tags": meta.get("tags", ""),
                "title": r.entry.content[:50],
                "symptom": "",
                "fix": "",
                "rank": -r.score,
                "content": r.entry.content,
                "level": r.entry.level.name.lower(),
            })

        return {
            "query": query,
            "count": len(formatted_results),
            "results": formatted_results,
            "backend": "radiomind",
        }

    # --- Consolidate Bridge ---

    def consolidate(self) -> dict[str, Any]:
        """Replace attn-consolidate.py — run dream + refresh digest."""
        dream_result = self._mind.trigger_dream()
        digest = self._mind.get_context_digest(token_budget=250)

        # Write context-digest.md to RadioHeader's expected location
        digest_path = self._rh_home / "context-digest.md"
        if digest_path.parent.exists():
            full_digest = self._build_full_digest()
            digest_path.write_text(full_digest, encoding="utf-8")

        return {
            "merged": dream_result.merged,
            "pruned": dream_result.pruned,
            "insights": len(dream_result.new_insights),
            "digest_written": str(digest_path),
        }

    def _build_full_digest(self) -> str:
        """Build a full context-digest.md compatible with RadioHeader format."""
        parts = ["# 环境认知摘要\n"]
        parts.append(f"> 由 RadioMind 于 {time.strftime('%Y-%m-%d')} 生成。\n")

        profile = self._mind.get_user_profile()
        if profile.who:
            parts.append("## 用户特征\n")
            for k, v in profile.who.items():
                parts.append(f"- {k}: {v}")

        if profile.how:
            parts.append("\n## 工作方式\n")
            for k, v in profile.how.items():
                parts.append(f"- {k}: {v}")

        stats = self._mind.stats()
        if stats.get("domains"):
            parts.append("\n## 活跃领域\n")
            for d in stats["domains"]:
                parts.append(f"- **{d['name']}**: {d['memory_count']} 条记忆")

        parts.append(f"\n## 记忆统计\n")
        parts.append(f"- 总记忆: {stats['total_active']} 条")
        parts.append(f"- 习惯(L3): {stats['habits']} 条")
        parts.append(f"- 已归档: {stats['archived']} 条")

        digest = "\n".join(parts)

        # Enforce 3.5K char budget (RadioHeader's limit)
        if len(digest) > 3500:
            digest = digest[:3450] + "\n\n> [截断: 超出 3.5K 字符预算]"

        return digest

    # --- Helpers ---

    @staticmethod
    def _infer_domain(filename: str, section: str = "") -> str:
        """Infer domain from topic filename or section."""
        name = filename.lower().replace(".md", "").replace("-", " ")
        domain_map = {
            "ios": "ios", "swift": "ios", "swiftui": "ios",
            "rust": "rust", "cargo": "rust",
            "python": "python", "pip": "python",
            "3d": "3d", "blender": "3d", "game": "3d",
            "web": "web", "css": "web", "html": "web",
            "git": "devtools", "cli": "devtools",
            "npu": "hardware", "arm": "hardware",
            "network": "network", "proxy": "network", "dns": "network",
        }
        for keyword, domain in domain_map.items():
            if keyword in name:
                return domain
        return "general"

    @staticmethod
    def _normalize_domain(raw: str) -> str:
        """Normalize domain names from shortwave format."""
        if not raw:
            return "general"
        clean = raw.lower().strip()
        normalize_map = {
            "ios": "ios", "swift": "ios", "swiftui": "ios",
            "3d": "3d", "blender": "3d",
            "rust": "rust", "python": "python",
            "shell": "devtools", "cli": "devtools",
        }
        return normalize_map.get(clean, clean)
