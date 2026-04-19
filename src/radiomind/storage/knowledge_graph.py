"""Knowledge Graph — SQLite triples with temporal validity.

Inspired by mempalace: (subject, relation, object, valid_from, valid_until)
Supports timeline queries: "what was user doing in March 2026?"
"""

from __future__ import annotations

import re as _re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _re_strip_fence(text: str) -> str:
    """Drop markdown ```json fences LLMs tend to wrap around JSON output."""
    text = _re.sub(r"^```(?:json|JSON)?\s*\n?", "", text.strip())
    text = _re.sub(r"\n?```\s*$", "", text)
    return text.strip()

KG_SCHEMA = """
CREATE TABLE IF NOT EXISTS triples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    relation TEXT NOT NULL,
    object TEXT NOT NULL,
    valid_from REAL,
    valid_until REAL,
    source_id INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    alias TEXT NOT NULL,
    canonical TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (alias)
);

CREATE INDEX IF NOT EXISTS idx_subject ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_relation ON triples(relation);
CREATE INDEX IF NOT EXISTS idx_object ON triples(object);
CREATE INDEX IF NOT EXISTS idx_valid ON triples(valid_from, valid_until);
CREATE INDEX IF NOT EXISTS idx_alias_canonical ON entity_aliases(canonical);
"""


# Common Chinese location suffixes we strip during canonicalization so that
# "北京市 / 北京" and "杭州 / 杭州市" collapse to the same entity.
_CN_LOC_SUFFIXES = ("市", "省", "县", "区", "镇")
_CN_ORG_SUFFIXES = ("公司", "有限公司", "股份有限公司")


def canonicalize(entity: str) -> str:
    """Normalize an entity string to its canonical form.

    - Strip whitespace and common punctuation
    - Lowercase ASCII (CJK is case-insensitive inherently)
    - Strip common Chinese location/org suffixes
    Does NOT do cross-entity merging (that's in KnowledgeGraph.resolve()).
    """
    s = entity.strip().strip("，。,.()[]【】「」\"'『』")
    if not s:
        return ""
    # Lowercase only ASCII letters; leave CJK untouched
    ascii_lower = "".join(ch.lower() if ch.isascii() else ch for ch in s)
    s = ascii_lower
    # Strip common suffixes for locations / orgs
    for suf in _CN_LOC_SUFFIXES + _CN_ORG_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf) + 1:
            s = s[: -len(suf)]
            break
    return s

TRIPLE_EXTRACTION_PATTERNS = [
    (r"我(?:叫|是)\s*(\S+)", "user", "name_is", None),
    (r"我在(.+?)(?:工作|上班)", "user", "works_at", None),
    (r"我(?:在|住在|来自)\s*(\S+)", "user", "located_in", None),
    (r"我(?:喜欢|爱)\s*(.+)", "user", "likes", None),
    (r"我(?:讨厌|不喜欢)\s*(.+)", "user", "dislikes", None),
    (r"我(?:有|养了)\s*(.+)", "user", "has", None),
    (r"我(?:正在|目前在)\s*(.+)", "user", "currently_doing", None),
]


@dataclass
class Triple:
    subject: str
    relation: str
    object: str
    valid_from: float | None = None
    valid_until: float | None = None
    source_id: int | None = None
    confidence: float = 1.0
    id: int | None = None
    created_at: float = 0.0


class KnowledgeGraph:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(KG_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("KnowledgeGraph not opened")
        return self._conn

    def add_triple(
        self,
        subject: str,
        relation: str,
        obj: str,
        valid_from: float | None = None,
        source_id: int | None = None,
        confidence: float = 1.0,
    ) -> int:
        """Add a triple. Auto-invalidates conflicting triples for unique relations.

        Subject and object are canonicalized + alias-resolved before insert
        so that "杭州市" and "杭州" collapse to the same node.
        """
        subject = self.resolve(subject)
        obj = self.resolve(obj)
        if not subject or not obj:
            return -1

        now = time.time()
        valid_from = valid_from or now

        # State relations (UPDATE semantics) — new fact supersedes old.
        # Event relations (visited, bought, attended, etc.) are additive.
        #
        # Heuristic: state verbs describe "current reality" (latest wins);
        # event verbs describe "something that happened at a point in time"
        # (all history matters). Action verbs never invalidate each other.
        #
        # Benchmark motivation: knowledge-update questions like "How many
        # dozen eggs do we CURRENTLY have?" require this distinction —
        # if user said 30 in turn 1 and 20 in turn 7, retrieving both is
        # noise; only 20 is the current state.
        _STATE_RELATIONS = {
            "name_is", "works_at", "located_in", "lives_in", "currently_doing",
            "current_weight", "current_height", "current_role", "current_age",
            "personal_best", "best_time", "record", "rank",
            "has_count_of", "currently_has", "owns", "pet_name",
            "favorite", "favourite", "preferred",
            "current_status", "marital_status",
        }
        if relation in _STATE_RELATIONS:
            self.conn.execute(
                "UPDATE triples SET valid_until = ? WHERE subject = ? AND relation = ? AND valid_until IS NULL",
                (now, subject, relation),
            )

        cur = self.conn.execute(
            "INSERT INTO triples (subject, relation, object, valid_from, valid_until, source_id, confidence, created_at) "
            "VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
            (subject, relation, obj, valid_from, source_id, confidence, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def resolve(self, entity: str) -> str:
        """Return the canonical form for an entity, following the alias chain."""
        c = canonicalize(entity)
        if not c:
            return ""
        row = self.conn.execute(
            "SELECT canonical FROM entity_aliases WHERE alias = ?", (c,)
        ).fetchone()
        return row["canonical"] if row else c

    def add_alias(self, alias: str, canonical: str) -> None:
        """Register an alias so future triples referencing `alias` map to `canonical`.

        Also rewrites existing triples (subject/object) so the graph is
        consistent immediately. Idempotent on repeat calls.
        """
        alias_c = canonicalize(alias)
        canonical_c = canonicalize(canonical)
        if not alias_c or not canonical_c or alias_c == canonical_c:
            return
        now = time.time()
        self.conn.execute(
            "INSERT OR REPLACE INTO entity_aliases (alias, canonical, created_at) VALUES (?, ?, ?)",
            (alias_c, canonical_c, now),
        )
        # Rewrite existing triples
        self.conn.execute(
            "UPDATE triples SET subject = ? WHERE subject = ?", (canonical_c, alias_c)
        )
        self.conn.execute(
            "UPDATE triples SET object = ? WHERE object = ?", (canonical_c, alias_c)
        )
        self.conn.commit()

    def query_entity(self, entity: str, as_of: float | None = None) -> list[Triple]:
        """Query all facts about an entity, optionally at a point in time."""
        entity = self.resolve(entity)
        if as_of is not None:
            rows = self.conn.execute(
                "SELECT * FROM triples WHERE subject = ? AND valid_from <= ? AND (valid_until IS NULL OR valid_until > ?) ORDER BY valid_from DESC",
                (entity, as_of, as_of),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM triples WHERE subject = ? AND valid_until IS NULL ORDER BY created_at DESC",
                (entity,),
            ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def query_relation(self, subject: str, relation: str) -> list[Triple]:
        """Query specific relation for a subject."""
        subject = self.resolve(subject)
        rows = self.conn.execute(
            "SELECT * FROM triples WHERE subject = ? AND relation = ? AND valid_until IS NULL ORDER BY created_at DESC",
            (subject, relation),
        ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def timeline(self, entity: str) -> list[Triple]:
        """Get full timeline of an entity (including expired facts)."""
        entity = self.resolve(entity)
        rows = self.conn.execute(
            "SELECT * FROM triples WHERE subject = ? ORDER BY valid_from ASC",
            (entity,),
        ).fetchall()
        return [self._row_to_triple(r) for r in rows]

    def invalidate(self, subject: str, relation: str, obj: str) -> None:
        """Mark a triple as no longer valid."""
        self.conn.execute(
            "UPDATE triples SET valid_until = ? WHERE subject = ? AND relation = ? AND object = ? AND valid_until IS NULL",
            (time.time(), subject, relation, obj),
        )
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM triples WHERE valid_until IS NULL").fetchone()[0]

    def extract_triples_from_text(self, text: str) -> list[tuple[str, str, str]]:
        """Regex fallback: only catches a narrow set of Chinese patterns.

        Kept for the "no LLM available" degradation path only. For any
        English content this returns very few triples (essentially zero
        on typical benchmark conversations). Callers should prefer
        `extract_triples_llm(text, llm)` when an LLM is wired in —
        the LLM version handles both English and Chinese, catches
        action verbs (visited / bought / cancelled / moved), and links
        entity references that regex can't.
        """
        import re
        extracted = []
        for pattern, subject, relation, _ in TRIPLE_EXTRACTION_PATTERNS:
            match = re.search(pattern, text)
            if match:
                obj = match.group(1).strip()
                if obj and len(obj) > 0:
                    extracted.append((subject, relation, obj))
        return extracted

    def extract_triples_batch_llm(
        self,
        turns: list[tuple[int, str]],
        llm,
        max_triples_per_turn: int = 5,
    ) -> dict[int, list[tuple[str, str, str]]]:
        """Batch LLM-based triple extractor — use for bulk ingest.

        turns: list of (turn_id, text) pairs. All user turns from one
        conversation/domain; LLM sees the whole chunk and outputs a map
        keyed by turn_id → triples. One LLM call for the batch vs one
        per turn (~250× fewer calls per benchmark question).

        Returns: {turn_id: [(subject, relation, object), ...]}
        Missing turn_id = no triples extracted for that turn.
        """
        if not turns or llm is None:
            return {}
        try:
            is_avail = getattr(llm, "is_available", None)
            if is_avail is None or not llm.is_available():
                return {}
        except Exception:
            return {}

        # Format the batch — turn ids as indices for LLM to reference.
        # Truncate per-turn text to avoid blowing the context window; KG-
        # worthy facts are usually in the first ~200 chars of a turn.
        lines = []
        for idx, (tid, text) in enumerate(turns):
            snippet = (text or "").strip().replace("\n", " ")[:400]
            lines.append(f"[{idx}] {snippet}")
        batch_text = "\n".join(lines)

        prompt = f"""Extract knowledge triples from each user turn below.

Turns (one per line, prefixed by [index]):

{batch_text}

Output format: strict JSON array, each entry is
{{"i": <index>, "s": "subject", "r": "relation", "o": "object"}}

Rules:
- "user" is the speaker in all turns; use "user" as subject when the
  fact is about them ("I visited Dr. Smith" → s="user").
- Relations: short snake_case tokens. Distinguish STATE from EVENT:
  * State (updatable — should overwrite previous value): lives_in,
    works_at, name_is, current_role, current_weight, personal_best,
    has_count_of, currently_has, favorite, marital_status, pet_name
  * Event (additive history): visited, bought, cancelled, attended,
    completed, read, met, took_medication, had_procedure, saw_doctor
  Pick STATE for "what's my X right now" facts; EVENT for "at some
  time user did X" facts. This distinction drives retrieval correctness
  for knowledge-update questions.
- Use literal entity names from the text.
- Skip uncertainty-qualified statements ("I might X", "if I Y") unless
  the same turn later confirms.
- At most {max_triples_per_turn} triples per turn.
- If a turn has no extractable facts, simply omit it from the output.
- Output JSON array only, no markdown, no prose."""

        try:
            resp = llm.generate(
                prompt,
                system="You extract knowledge triples from conversation turns. Output strict JSON only.",
            )
            raw = (resp.text or "").strip()
        except Exception:
            return {}

        if raw.startswith("```"):
            raw = _re_strip_fence(raw)

        import json
        try:
            start = raw.find("[")
            end = raw.rfind("]")
            if start < 0 or end <= start:
                return {}
            arr = json.loads(raw[start : end + 1])
            if not isinstance(arr, list):
                return {}
        except Exception:
            return {}

        out: dict[int, list[tuple[str, str, str]]] = {}
        idx_to_tid = {i: turns[i][0] for i in range(len(turns))}
        for item in arr:
            if not isinstance(item, dict):
                continue
            try:
                i = int(item.get("i", -1))
            except (ValueError, TypeError):
                continue
            tid = idx_to_tid.get(i)
            if tid is None:
                continue
            s = str(item.get("s", "")).strip()
            r = str(item.get("r", "")).strip()
            o = str(item.get("o", "")).strip()
            if not s or not r or not o:
                continue
            if o.lower() in ("something", "thing", "anything", "null", "none"):
                continue
            out.setdefault(tid, []).append((s, r, o))
        return out

    def extract_triples_llm(
        self,
        text: str,
        llm,
        speaker: str = "user",
        max_triples: int = 10,
    ) -> list[tuple[str, str, str]]:
        """LLM-based triple extractor — default path when an LLM is available.

        English-primary prompt that handles both English and Chinese input.
        Returns (subject, relation, object) triples. Designed to be called
        from `RadioMind.ingest_turns_raw` for every user turn; low-latency
        (~100-200 tokens output), runs in parallel to the turn storage.

        speaker: typically "user" — used as the default subject when the
                 extracted fact is about the speaker themselves (e.g.
                 "I visited Dr. Smith" → subject = "user").

        Returns empty list on any error — caller falls back to the regex
        path or just proceeds without KG enrichment for this turn.
        """
        if not text or llm is None:
            return []
        try:
            is_avail = getattr(llm, "is_available", None)
            if is_avail is None or not llm.is_available():
                return []
        except Exception:
            return []

        prompt = f"""Extract knowledge triples from the following text.

Text (from speaker "{speaker}"): {text}

Output format: strict JSON array of triples, each as
{{"s": "subject", "r": "relation", "o": "object"}}

Rules:
- Use "user" as subject when the text is about the speaker themselves
  (e.g. "I visited X" → s="user").
- Relations should be short, normalized, snake_case verbs: "visited",
  "bought", "cancelled", "planned_to", "likes", "works_at", "lives_in",
  "owns", "saw_doctor", "had_procedure", "took_medication", etc.
- Use literal entity names from the text (keep "Dr. Smith", not "my doctor").
- Include temporal markers when the text specifies them (e.g. object
  "Dr. Smith on 2023-05-10" rather than just "Dr. Smith") only when
  date is explicit in the sentence.
- Skip triples where object would be empty, placeholder, or generic
  ("something", "thing"). Skip uncertainty-qualified statements
  ("I might X" → do not extract unless it's a completed action).
- Extract at most {max_triples} triples per call.
- If no extractable facts, return []."""

        try:
            resp = llm.generate(
                prompt,
                system="You extract knowledge triples. Output strict JSON array only, no markdown, no prose.",
            )
            raw = (resp.text or "").strip()
        except Exception:
            return []

        # Strip markdown fencing if present
        if raw.startswith("```"):
            raw = _re_strip_fence(raw)

        import json
        try:
            # Find the first JSON array in the response
            start = raw.find("[")
            end = raw.rfind("]")
            if start < 0 or end <= start:
                return []
            arr = json.loads(raw[start : end + 1])
            if not isinstance(arr, list):
                return []
        except Exception:
            return []

        out: list[tuple[str, str, str]] = []
        for item in arr[:max_triples]:
            if not isinstance(item, dict):
                continue
            s = str(item.get("s", "")).strip()
            r = str(item.get("r", "")).strip()
            o = str(item.get("o", "")).strip()
            if not s or not r or not o:
                continue
            # Reject placeholder objects
            if o.lower() in ("something", "thing", "anything", "null", "none"):
                continue
            out.append((s, r, o))
        return out

    @staticmethod
    def _row_to_triple(row: sqlite3.Row) -> Triple:
        return Triple(
            id=row["id"],
            subject=row["subject"],
            relation=row["relation"],
            object=row["object"],
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            source_id=row["source_id"],
            confidence=row["confidence"],
            created_at=row["created_at"],
        )
