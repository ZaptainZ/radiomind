"""Knowledge Library (信息收集库) store — captured external sources.

Holds documents the user *deliberately collected* (articles / papers / notes),
distinct from conversational `memories`. Items + faceted tags live here; claims /
entities / relations reuse the existing knowledge_graph (triples + entity_aliases)
rather than growing a second graph.

Operates on the same SQLite connection as the memories DB (separate tables, added
by migration v5), so library recall never pollutes personal-memory recall.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


# Tracking params stripped during URL normalization so the same article shared
# with different ?utm_* / #anchor collapses to one library item.
_TRACKING_PREFIXES = ("utm_", "spm", "fbclid", "gclid", "from", "isappinstalled")


def normalize_url(url: str) -> str:
    """Canonicalize a URL for dedup: drop fragment + tracking query params, lowercase host."""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    host = parts.netloc.lower()
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/"), urlencode(query), ""))


def content_hash(text: str) -> str:
    """Stable hash of normalized body text (for content-level dedup)."""
    norm = " ".join((text or "").split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32] if norm else ""


@dataclass
class LibraryItem:
    title: str = ""
    source_url: str = ""
    source_domain: str = ""
    source_type: str = "article"
    author: str = ""
    published_at: float | None = None
    language: str = ""
    content_hash: str = ""
    short_summary: str = ""
    key_points: list[str] = field(default_factory=list)
    why_it_matters: str = ""
    useful_for: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class LibraryStore:
    """CRUD + search over library_items / library_tags / library_item_tags."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # --- items ------------------------------------------------------------

    def find_duplicate(self, source_url: str, chash: str, user_id: str = "") -> int | None:
        """Return an existing item id if this URL or content is already captured (strong dedup)."""
        norm = normalize_url(source_url)
        if norm:
            row = self._conn.execute(
                "SELECT id FROM library_items WHERE source_url = ? AND user_id = ? AND status != 'archived' LIMIT 1",
                (norm, user_id),
            ).fetchone()
            if row:
                return row[0]
        if chash:
            row = self._conn.execute(
                "SELECT id FROM library_items WHERE content_hash = ? AND user_id = ? AND status != 'archived' LIMIT 1",
                (chash, user_id),
            ).fetchone()
            if row:
                return row[0]
        return None

    def put_item(self, item: LibraryItem, dedup: bool = True) -> tuple[int, bool]:
        """Insert a captured item. Returns (item_id, was_duplicate).

        With dedup=True, an existing item (same normalized URL or content_hash) is
        returned untouched instead of inserting a copy.
        """
        norm_url = normalize_url(item.source_url)
        if dedup:
            existing = self.find_duplicate(norm_url, item.content_hash, item.user_id)
            if existing is not None:
                return existing, True
        now = time.time()
        cur = self._conn.execute(
            """INSERT INTO library_items
               (title, source_url, source_domain, source_type, author, published_at, captured_at,
                language, content_hash, status, short_summary, key_points, why_it_matters,
                useful_for, open_questions, user_id, metadata)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item.title, norm_url, item.source_domain, item.source_type, item.author,
                item.published_at, now, item.language, item.content_hash, "active",
                item.short_summary, json.dumps(item.key_points, ensure_ascii=False),
                item.why_it_matters, json.dumps(item.useful_for, ensure_ascii=False),
                json.dumps(item.open_questions, ensure_ascii=False), item.user_id,
                json.dumps(item.metadata, ensure_ascii=False),
            ),
        )
        item_id = cur.lastrowid
        self._conn.execute(
            "INSERT INTO library_items_fts (rowid, title, short_summary) VALUES (?,?,?)",
            (item_id, item.title, item.short_summary),
        )
        self._conn.commit()
        return item_id, False

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM library_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for jf in ("key_points", "useful_for", "open_questions"):
            d[jf] = json.loads(d.get(jf) or "[]")
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        d["tags"] = self.item_tags(item_id)
        return d

    def list_items(self, limit: int = 20, status: str = "active", user_id: str = "") -> list[dict[str, Any]]:
        where = ["status = ?"]
        params: list[Any] = [status]
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT id, title, source_domain, source_type, captured_at, status "
            f"FROM library_items WHERE {' AND '.join(where)} ORDER BY captured_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def set_status(self, item_id: int, status: str) -> None:
        self._conn.execute("UPDATE library_items SET status = ? WHERE id = ?", (status, item_id))
        self._conn.commit()

    def search_items(self, query: str, limit: int = 10, tag: str = "", user_id: str = "") -> list[dict[str, Any]]:
        """FTS over title+summary; falls back to LIKE. Optional tag filter."""
        ids: list[int] = []
        q = (query or "").strip()
        if q:
            try:
                rows = self._conn.execute(
                    "SELECT rowid FROM library_items_fts WHERE library_items_fts MATCH ? ORDER BY rank LIMIT ?",
                    (q, limit * 3),
                ).fetchall()
                ids = [r[0] for r in rows]
            except sqlite3.OperationalError:
                ids = []
            if not ids:
                rows = self._conn.execute(
                    "SELECT id FROM library_items WHERE (title LIKE ? OR short_summary LIKE ?) "
                    "AND status = 'active' LIMIT ?",
                    (f"%{q}%", f"%{q}%", limit * 3),
                ).fetchall()
                ids = [r[0] for r in rows]
        else:
            ids = [r[0] for r in self._conn.execute(
                "SELECT id FROM library_items WHERE status='active' ORDER BY captured_at DESC LIMIT ?",
                (limit * 3,),
            ).fetchall()]

        results: list[dict[str, Any]] = []
        for iid in ids:
            item = self.get_item(iid)
            if not item or item["status"] != "active":
                continue
            if user_id and item.get("user_id", "") != user_id:
                continue
            if tag and not any(t["name"] == tag for t in item["tags"]):
                continue
            results.append({
                "id": item["id"], "title": item["title"], "source_domain": item["source_domain"],
                "source_type": item["source_type"], "captured_at": item["captured_at"],
                "short_summary": item["short_summary"], "tags": [t["name"] for t in item["tags"]],
            })
            if len(results) >= limit:
                break
        return results

    # --- tags -------------------------------------------------------------

    def upsert_tag(self, name: str, facet: str = "topic", aliases: list[str] | None = None,
                   parent_id: int | None = None) -> int:
        """Create or fetch a tag by (name, facet). Resolves aliases to the canonical tag."""
        name = name.strip()
        # alias hit → return the tag that lists this name as an alias.
        for row in self._conn.execute("SELECT id, aliases FROM library_tags WHERE status='active'").fetchall():
            try:
                al = json.loads(row[1] or "[]")
            except json.JSONDecodeError:
                al = []
            if name in al:
                return row[0]
        row = self._conn.execute(
            "SELECT id FROM library_tags WHERE name = ? AND facet = ?", (name, facet)
        ).fetchone()
        if row:
            return row[0]
        cur = self._conn.execute(
            "INSERT INTO library_tags (name, facet, aliases, parent_id, status, created_at) VALUES (?,?,?,?,?,?)",
            (name, facet, json.dumps(aliases or [], ensure_ascii=False), parent_id, "active", time.time()),
        )
        self._conn.commit()
        return cur.lastrowid

    def tag_item(self, item_id: int, tag_id: int, confidence: float = 1.0, source: str = "llm") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO library_item_tags (item_id, tag_id, confidence, source, created_at) "
            "VALUES (?,?,?,?,?)",
            (item_id, tag_id, confidence, source, time.time()),
        )
        self._conn.commit()

    def item_tags(self, item_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT t.id, t.name, t.facet, it.confidence, it.source "
            "FROM library_item_tags it JOIN library_tags t ON t.id = it.tag_id "
            "WHERE it.item_id = ? AND t.status='active' ORDER BY it.confidence DESC",
            (item_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def merge_tag(self, alias_name: str, canonical_name: str, facet: str = "topic") -> int:
        """Merge alias tag into canonical: repoint item links, record the alias, archive the old tag."""
        canon_id = self.upsert_tag(canonical_name, facet)
        row = self._conn.execute(
            "SELECT id, aliases FROM library_tags WHERE name = ? AND facet = ?", (alias_name, facet)
        ).fetchone()
        if row and row[0] != canon_id:
            old_id = row[0]
            self._conn.execute(
                "UPDATE OR IGNORE library_item_tags SET tag_id = ? WHERE tag_id = ?", (canon_id, old_id)
            )
            self._conn.execute("DELETE FROM library_item_tags WHERE tag_id = ?", (old_id,))
            self._conn.execute("UPDATE library_tags SET status='archived' WHERE id = ?", (old_id,))
        crow = self._conn.execute("SELECT aliases FROM library_tags WHERE id = ?", (canon_id,)).fetchone()
        al = json.loads(crow[0] or "[]") if crow else []
        if alias_name not in al:
            al.append(alias_name)
            self._conn.execute("UPDATE library_tags SET aliases = ? WHERE id = ?",
                               (json.dumps(al, ensure_ascii=False), canon_id))
        self._conn.commit()
        return canon_id

    # --- stats ------------------------------------------------------------

    def stats(self, user_id: str = "") -> dict[str, Any]:
        uw = " WHERE user_id = ?" if user_id else ""
        up = (user_id,) if user_id else ()
        items = self._conn.execute(f"SELECT COUNT(*) FROM library_items{uw}", up).fetchone()[0]
        active = self._conn.execute(
            f"SELECT COUNT(*) FROM library_items WHERE status='active'" + (" AND user_id=?" if user_id else ""),
            up,
        ).fetchone()[0]
        tags = self._conn.execute("SELECT COUNT(*) FROM library_tags WHERE status='active'").fetchone()[0]
        return {"items": items, "active": active, "archived": items - active, "tags": tags}
