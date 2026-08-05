"""Life Log (生活日志) store — time-anchored episodes + day profiles.

A THIRD namespace alongside `memories` (conversation) and `library` (collected
documents). Holds episodes of the user's day (derived from ambient audio by an
external pipeline) and rolled-up day profiles. Separate tables (migration v6) so
life-log recall never pollutes personal-memory or library recall.

Design vs. library:
- Facets (participants / topics / media) are stored as JSON columns, not a
  separate tag table — the life log doesn't need library's tag-hygiene machinery.
- FTS covers activity + summary + topics_text (topics ARE searchable), so
  "when did I mention X" works even when X is only a topic.
- People (participants) reuse the knowledge_graph via `library link`-style triples
  when cross-day identity binding is wanted; not modelled here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any


def content_hash(text: str) -> str:
    norm = " ".join((text or "").split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32] if norm else ""


def _topics_text(topics: list[str], media: list[str]) -> str:
    """Flatten topics + media into one FTS-indexable string."""
    return " ".join(str(t) for t in (list(topics or []) + list(media or [])) if t)


@dataclass
class LifelogEpisode:
    date: str = ""
    start_clock: str = ""
    end_clock: str = ""
    # Absolute time (epoch) is authoritative; the clock strings are for display.
    # A recording that runs past midnight has no valid clock representation.
    started_at: float = 0.0
    ended_at: float = 0.0
    tz: str = ""
    activity: str = ""
    participants: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    media: list[str] = field(default_factory=list)
    summary: str = ""
    content_hash: str = ""
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DayProfile:
    date: str = ""
    narrative: str = ""
    people: list[dict[str, Any]] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class LifelogStore:
    """CRUD + search over lifelog_episodes / lifelog_day_profiles."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # --- episodes ---------------------------------------------------------

    def find_duplicate(self, date: str, start_clock: str, user_id: str = "") -> int | None:
        """An episode is uniquely keyed by (user, date, start_clock)."""
        row = self._conn.execute(
            "SELECT id FROM lifelog_episodes WHERE user_id=? AND date=? AND start_clock=? "
            "AND status!='archived' LIMIT 1",
            (user_id, date, start_clock),
        ).fetchone()
        return row[0] if row else None

    def put_episode(self, ep: LifelogEpisode, dedup: bool = True) -> tuple[int, bool]:
        """Insert an episode. Returns (id, was_duplicate). Dedup on (user, date, start)."""
        if dedup:
            existing = self.find_duplicate(ep.date, ep.start_clock, ep.user_id)
            if existing is not None:
                return existing, True
        chash = ep.content_hash or content_hash(ep.activity + " " + ep.summary)
        ttext = _topics_text(ep.topics, ep.media)
        cur = self._conn.execute(
            """INSERT INTO lifelog_episodes
               (date, start_clock, end_clock, started_at, ended_at, tz, activity,
                participants, topics, topics_text,
                media, summary, content_hash, status, user_id, created_at, metadata)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ep.date, ep.start_clock, ep.end_clock,
                ep.started_at, ep.ended_at, ep.tz, ep.activity,
                json.dumps(ep.participants, ensure_ascii=False),
                json.dumps(ep.topics, ensure_ascii=False), ttext,
                json.dumps(ep.media, ensure_ascii=False), ep.summary, chash,
                "active", ep.user_id, time.time(),
                json.dumps(ep.metadata, ensure_ascii=False),
            ),
        )
        eid = cur.lastrowid
        self._conn.execute(
            "INSERT INTO lifelog_episodes_fts (rowid, activity, summary, topics_text) VALUES (?,?,?,?)",
            (eid, ep.activity, ep.summary, ttext),
        )
        self._conn.commit()
        return eid, False

    def get_episode(self, eid: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM lifelog_episodes WHERE id=?", (eid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for jf in ("participants", "topics", "media"):
            d[jf] = json.loads(d.get(jf) or "[]")
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        return d

    def list_episodes(self, date: str = "", limit: int = 50, user_id: str = "") -> list[dict[str, Any]]:
        where = ["status='active'"]
        params: list[Any] = []
        if date:
            where.append("date=?"); params.append(date)
        if user_id:
            where.append("user_id=?"); params.append(user_id)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT id, date, start_clock, end_clock, activity, participants, summary "
            f"FROM lifelog_episodes WHERE {' AND '.join(where)} ORDER BY date, start_clock LIMIT ?",
            params,
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["participants"] = json.loads(d.get("participants") or "[]")
            out.append(d)
        return out

    def episodes_for_dates(self, dates: list[str], user_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        """Episodes across several dates, oldest first — the raw evidence a
        consolidation pass reads under each day profile."""
        if not dates:
            return []
        where = ["status='active'", f"date IN ({','.join('?' * len(dates))})"]
        params: list[Any] = list(dates)
        if user_id:
            where.append("user_id=?"); params.append(user_id)
        rows = self._conn.execute(
            f"SELECT id, date, start_clock, end_clock, activity, participants, topics, media, summary "
            f"FROM lifelog_episodes WHERE {' AND '.join(where)} ORDER BY date, start_clock LIMIT ?",
            (*params, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for jf in ("participants", "topics", "media"):
                d[jf] = json.loads(d.get(jf) or "[]")
            out.append(d)
        return out

    def search_episodes(self, query: str, limit: int = 10, date: str = "",
                        person: str = "", user_id: str = "") -> list[dict[str, Any]]:
        """FTS over activity+summary+topics; falls back to LIKE. Optional date/person filters."""
        ids: list[int] = []
        q = (query or "").strip()
        if q:
            try:
                rows = self._conn.execute(
                    "SELECT rowid FROM lifelog_episodes_fts WHERE lifelog_episodes_fts MATCH ? "
                    "ORDER BY rank LIMIT ?", (q, limit * 4),
                ).fetchall()
                ids = [r[0] for r in rows]
            except sqlite3.OperationalError:
                ids = []
            if not ids:
                rows = self._conn.execute(
                    "SELECT id FROM lifelog_episodes WHERE (activity LIKE ? OR summary LIKE ? "
                    "OR topics_text LIKE ?) AND status='active' LIMIT ?",
                    (f"%{q}%", f"%{q}%", f"%{q}%", limit * 4),
                ).fetchall()
                ids = [r[0] for r in rows]
        else:
            ids = [r[0] for r in self._conn.execute(
                "SELECT id FROM lifelog_episodes WHERE status='active' ORDER BY date DESC, start_clock LIMIT ?",
                (limit * 4,),
            ).fetchall()]

        results: list[dict[str, Any]] = []
        for eid in ids:
            ep = self.get_episode(eid)
            if not ep or ep["status"] != "active":
                continue
            if user_id and ep.get("user_id", "") != user_id:
                continue
            if date and ep.get("date") != date:
                continue
            if person and person not in ep.get("participants", []):
                continue
            results.append({
                "id": ep["id"], "date": ep["date"], "start_clock": ep["start_clock"],
                "end_clock": ep["end_clock"], "started_at": ep.get("started_at", 0),
                "ended_at": ep.get("ended_at", 0), "tz": ep.get("tz", ""),
                "activity": ep["activity"],
                "participants": ep["participants"], "topics": ep["topics"],
                "summary": ep["summary"],
            })
            if len(results) >= limit:
                break
        return results

    # --- day profiles -----------------------------------------------------

    def put_day(self, day: DayProfile) -> tuple[int, bool]:
        """Upsert a day profile keyed by (user, date). Returns (id, was_update)."""
        row = self._conn.execute(
            "SELECT id FROM lifelog_day_profiles WHERE user_id=? AND date=?",
            (day.user_id, day.date),
        ).fetchone()
        payload = (
            day.narrative, json.dumps(day.people, ensure_ascii=False),
            json.dumps(day.topics, ensure_ascii=False), json.dumps(day.activities, ensure_ascii=False),
            json.dumps(day.highlights, ensure_ascii=False), json.dumps(day.metadata, ensure_ascii=False),
        )
        if row:
            self._conn.execute(
                "UPDATE lifelog_day_profiles SET narrative=?, people=?, topics=?, activities=?, "
                "highlights=?, metadata=? WHERE id=?", (*payload, row[0]),
            )
            self._conn.commit()
            return row[0], True
        cur = self._conn.execute(
            "INSERT INTO lifelog_day_profiles (date, narrative, people, topics, activities, highlights, "
            "status, user_id, created_at, metadata) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (day.date, day.narrative, *payload[1:5], "active", day.user_id, time.time(), payload[5]),
        )
        self._conn.commit()
        return cur.lastrowid, False

    def recent_days(self, limit: int = 7, user_id: str = "", since: str = "", until: str = "",
                    include_consolidated: bool = False) -> list[dict[str, Any]]:
        """Most recent day profiles, newest first. Skips already-consolidated days
        unless asked — consolidation is the only caller and must not re-distil."""
        where = ["status='active'"]
        params: list[Any] = []
        if user_id:
            where.append("user_id=?"); params.append(user_id)
        if since:
            where.append("date>=?"); params.append(since)
        if until:
            where.append("date<=?"); params.append(until)
        rows = self._conn.execute(
            f"SELECT * FROM lifelog_day_profiles WHERE {' AND '.join(where)} "
            f"ORDER BY date DESC LIMIT ?", (*params, max(limit, 1) * 4),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for jf in ("people", "topics", "activities", "highlights"):
                d[jf] = json.loads(d.get(jf) or "[]")
            d["metadata"] = json.loads(d.get("metadata") or "{}")
            if not include_consolidated and d["metadata"].get("consolidated_at"):
                continue
            out.append(d)
            if len(out) >= limit:
                break
        return out

    def mark_consolidated(self, date: str, user_id: str = "", info: dict[str, Any] | None = None) -> bool:
        """Stamp a day profile as distilled so the next run skips it."""
        row = self._conn.execute(
            "SELECT id, metadata FROM lifelog_day_profiles WHERE date=? AND user_id=?",
            (date, user_id),
        ).fetchone()
        if not row:
            return False
        meta = json.loads(row[1] or "{}")
        meta["consolidated_at"] = time.time()
        if info:
            meta["consolidated"] = info
        self._conn.execute(
            "UPDATE lifelog_day_profiles SET metadata=? WHERE id=?",
            (json.dumps(meta, ensure_ascii=False), row[0]),
        )
        self._conn.commit()
        return True

    def get_day(self, date: str, user_id: str = "") -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM lifelog_day_profiles WHERE date=? AND user_id=? AND status='active' LIMIT 1",
            (date, user_id),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        for jf in ("people", "topics", "activities", "highlights"):
            d[jf] = json.loads(d.get(jf) or "[]")
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        return d

    # --- stats ------------------------------------------------------------

    def stats(self, user_id: str = "") -> dict[str, Any]:
        uw = " WHERE user_id=?" if user_id else ""
        up = (user_id,) if user_id else ()
        eps = self._conn.execute(f"SELECT COUNT(*) FROM lifelog_episodes{uw}", up).fetchone()[0]
        days = self._conn.execute(f"SELECT COUNT(*) FROM lifelog_day_profiles{uw}", up).fetchone()[0]
        dates = self._conn.execute(
            f"SELECT COUNT(DISTINCT date) FROM lifelog_episodes{uw}", up).fetchone()[0]
        return {"episodes": eps, "day_profiles": days, "days_covered": dates}
