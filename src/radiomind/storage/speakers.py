"""Speaker identity (声纹身份) store — who keeps showing up in the life log.

A FOURTH namespace alongside `memories`, `library` and `lifelog`. Holds voice
embeddings produced by an external, stateless audio tool and resolves them into
stable speaker identities that accumulate across days — the mechanism behind
"the female voice that keeps appearing is the same person".

Design invariants (see HackWare `projectBasicInfo/lifelog-identity-design.md`):

- `speaker_turns` is the SOURCE OF TRUTH. Embeddings are never thrown away, so a
  wrong merge can always be undone. `speaker_id` is a mutable pointer; exemplars
  and centroids are derived caches, rebuildable from turns at any time.
- Matching is MULTI-EXEMPLAR, not single-centroid: one person sounds different
  across the room vs. next to the mic, and a single centroid averages those
  modes into a point that matches neither well. Centroids are only a coarse filter.
- Three-tier binding (high / gray / unknown). Only `high` turns may become
  exemplars — that admission gate matters more than the threshold itself, because
  it is what keeps a centroid from drifting onto someone else.
- Thresholds are a property of the EMBEDDING MODEL, not of the task. The defaults
  here are conservative placeholders; they must be calibrated on real recordings
  (see `manual()['calibration']`). Bias high: splitting one person into two IDs is
  visible and reversible, merging two people into one is silent and destroys the
  centroid.

The audio tool computes embeddings; this store only validates and matches. Turns
arrive already vectorized so there is never a "written but not embedded" state.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

DAY_S = 86400.0


def clock(epoch: float, tz: str = "") -> str:
    """Render a turn's absolute time the way a person would say it.

    The store otherwise keeps time as epoch + a `tz` string and leaves display to
    the caller, but a question shown to the owner needs wall-clock context to be
    answerable at all ("上周三晚上在饭馆" beats an epoch). Clips keep the raw
    epoch alongside, so nothing is lost to the formatting.
    """
    try:
        zone = ZoneInfo(tz) if tz else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    return datetime.fromtimestamp(epoch, zone).strftime("%Y-%m-%d %H:%M")


# --- vectors ------------------------------------------------------------------

def normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize so cosine similarity degrades to a dot product (same
    convention as `memories.embedding`, see storage/embedding.py)."""
    v = np.asarray(vec, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def to_blob(vec: np.ndarray) -> bytes:
    return normalize(vec).astype(np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def decode_embedding(value: Any) -> np.ndarray:
    """Accept base64(float32 bytes) — the wire format — or a plain list of floats."""
    if isinstance(value, str):
        return np.frombuffer(base64.b64decode(value), dtype=np.float32)
    return np.asarray(value, dtype=np.float32)


def encode_embedding(vec: np.ndarray) -> str:
    return base64.b64encode(normalize(vec).astype(np.float32).tobytes()).decode("ascii")


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# --- policy -------------------------------------------------------------------

@dataclass
class MatchPolicy:
    """Calibrated 2026-08-05 against `3dspeaker_campplus_zh` on real recordings
    (see RadioMind `logs/2026-08-05-calibration-run1-cc.md`). Owner-labelled clips
    separated cleanly: confirmed impostors topped out at 0.31, the lowest confirmed
    same-speaker segment sat at 0.39.

    These numbers belong to that embedding model. Swapping models invalidates them,
    which is what `calibrated_for` records.
    """

    t_high: float = 0.50          # >= : bind, and may become an exemplar
    t_low: float = 0.35           # <  : bind nothing, goes to the pending pool
    # t_high sits well above the 0.39 floor on purpose: a segment containing the
    # wearer AND a second person measured 0.44, and such mixtures must never
    # become exemplars. Binding still happens in the gray band; only the gallery
    # is protected.
    #
    # The wearer gets NO stricter threshold. The close-talk-mic assumption ("their
    # own voice varies less") is false for a worn recorder: the same person
    # measured 0.21–0.90 across skateboarding wind noise and restaurant babble —
    # a wider spread than anyone else's.
    wearer_t_high: float = 0.50
    wearer_t_low: float = 0.35
    # The exact weights the thresholds were measured against, including the file
    # fingerprint — different weights are a different measuring instrument.
    calibrated_for: str = "3dspeaker_speech_campplus_sv_zh-cn_16k-common@f682b514"
    min_speech_s: float = 1.5           # below this an embedding is noise, no decision
    min_new_id_speech_s: float = 3.0    # below this may match, never create an identity
    exemplar_min_speech_s: float = 3.0
    short_turn_penalty: float = 0.05    # 1.5–3s turns must clear a higher bar
    max_exemplars: int = 30
    promote_min_turns: int = 5
    promote_min_speech_s: float = 60.0
    promote_min_days: int = 2           # spanning ≥2 days is what kills TV voices
    pending_ttl_days: float = 14.0
    coarse_top_k: int = 5
    merge_propose_at: float = 0.85      # centroid similarity worth proposing a merge

    @classmethod
    def from_config(cls, cfg: Any) -> "MatchPolicy":
        p = cls()
        for f in cls.__dataclass_fields__:
            val = cfg.get(f"speakers.{f}", None) if cfg is not None else None
            if val is not None:
                setattr(p, f, type(getattr(p, f))(val))
        return p


@dataclass
class SpeakerTurn:
    started_at: float = 0.0
    ended_at: float = 0.0
    date: str = ""
    tz: str = ""
    embedding: np.ndarray | None = None
    model_id: str = ""
    speech_s: float = 0.0
    quality: float = 0.0
    region_type: str = "conversation"
    source_file: str = ""
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelMismatch(ValueError):
    """Incoming vectors were produced by a different model than the gallery.

    Silently mixing models makes every similarity meaningless, so this is a hard
    refusal rather than a warning.
    """


class SpeakerStore:
    def __init__(self, conn: sqlite3.Connection, policy: MatchPolicy | None = None):
        self._conn = conn
        self.policy = policy or MatchPolicy()

    # --- gallery reads ----------------------------------------------------

    def gallery_model(self, user_id: str = "") -> tuple[str, int]:
        """The (model_id, dim) the existing gallery was built with. ('', 0) if empty."""
        row = self._conn.execute(
            "SELECT model_id, dim FROM speaker_turns WHERE user_id=? AND model_id!='' "
            "ORDER BY id DESC LIMIT 1", (user_id,),
        ).fetchone()
        return (row[0], row[1]) if row else ("", 0)

    def _speakers(self, user_id: str = "", statuses: tuple[str, ...] = ("active", "pending")) -> list[dict]:
        q = ",".join("?" * len(statuses))
        rows = self._conn.execute(
            f"SELECT * FROM speakers WHERE user_id=? AND status IN ({q})",
            (user_id, *statuses),
        ).fetchall()
        return [dict(r) for r in rows]

    def _exemplars(self, speaker_id: int) -> list[tuple[int, np.ndarray]]:
        rows = self._conn.execute(
            "SELECT id, embedding FROM speaker_exemplars WHERE speaker_id=?", (speaker_id,),
        ).fetchall()
        return [(r[0], from_blob(r[1])) for r in rows]

    def _centroid(self, speaker_id: int) -> np.ndarray | None:
        row = self._conn.execute(
            "SELECT centroid FROM speaker_centroids WHERE speaker_id=?", (speaker_id,),
        ).fetchone()
        return from_blob(row[0]) if row else None

    # --- matching ---------------------------------------------------------

    def match(self, vec: np.ndarray, user_id: str = "", speech_s: float = 0.0,
              candidates: list[dict] | None = None) -> tuple[dict | None, float, str]:
        """Best speaker for one embedding → (speaker_row|None, score, binding).

        Coarse-filters by centroid, then scores precisely as max-over-exemplars.
        """
        pol = self.policy
        if speech_s and speech_s < pol.min_speech_s:
            return None, 0.0, "unknown"

        # `ignored` speakers stay in the matching pool on purpose. Dropping them
        # would not make the passer-by go away — their next turn would simply fail
        # to match and mint a fresh pending identity, which is exactly the nagging
        # `ignore` exists to stop. They are excluded from questions and promotion,
        # not from recognition.
        people = candidates if candidates is not None else self._speakers(
            user_id, statuses=("active", "pending", "ignored"))
        if not people:
            return None, 0.0, "unknown"

        if len(people) > pol.coarse_top_k:
            scored = []
            for sp in people:
                c = self._centroid(sp["id"])
                scored.append((cosine(vec, c) if c is not None else 1.0, sp))
            scored.sort(key=lambda x: -x[0])
            people = [sp for _, sp in scored[: pol.coarse_top_k]]

        best, best_score = None, -1.0
        for sp in people:
            ex = self._exemplars(sp["id"])
            if not ex:
                c = self._centroid(sp["id"])
                score = cosine(vec, c) if c is not None else -1.0
            else:
                score = max(cosine(vec, e) for _, e in ex)
            if score > best_score:
                best, best_score = sp, score

        if best is None:
            return None, 0.0, "unknown"

        t_high = pol.wearer_t_high if best.get("is_wearer") else pol.t_high
        t_low = pol.wearer_t_low if best.get("is_wearer") else pol.t_low
        if speech_s and speech_s < pol.min_new_id_speech_s:
            t_high += pol.short_turn_penalty   # short turns must clear a higher bar

        if best_score >= t_high:
            return best, best_score, "high"
        if best_score >= t_low:
            return best, best_score, "gray"
        return None, best_score, "unknown"

    # --- writing ----------------------------------------------------------

    def put_turns(self, turns: list[SpeakerTurn], user_id: str = "",
                  model_id: str = "", dry_run: bool = False) -> dict[str, Any]:
        """Store turns, resolve identities and refresh the derived caches — one
        call, one write path. Splitting "write" from "index" is how these systems
        silently rot, so resolution is never deferred.
        """
        pol = self.policy
        summary: dict[str, Any] = {
            "turns_in": len(turns), "stored": 0, "duplicate": 0,
            "bound_high": 0, "bound_gray": 0, "unknown": 0, "too_short": 0,
            "media_skipped": 0, "new_pending": 0, "exemplars_added": 0,
            "by_speaker": {}, "warnings": [], "dry_run": dry_run,
        }
        if not turns:
            return summary

        model_id = model_id or turns[0].model_id
        dims = {len(t.embedding) for t in turns if t.embedding is not None}
        if len(dims) > 1:
            raise ModelMismatch(f"turns carry mixed dimensions: {sorted(dims)}")
        dim = dims.pop() if dims else 0
        models = {t.model_id for t in turns if t.model_id}
        if len(models) > 1:
            raise ModelMismatch(f"turns carry mixed model_id: {sorted(models)}")

        known_model, known_dim = self.gallery_model(user_id)
        if known_model and (model_id != known_model or (known_dim and dim != known_dim)):
            raise ModelMismatch(
                f"gallery was built with {known_model} (dim {known_dim}), "
                f"got {model_id} (dim {dim}) — re-embed the gallery or use a new user_id"
            )

        now = time.time()
        touched: set[int] = set()
        for t in turns:
            vec = normalize(t.embedding) if t.embedding is not None else None
            if vec is None:
                summary["warnings"].append(f"turn at {t.started_at} has no embedding")
                continue

            if self._find_turn(user_id, t.source_file, t.started_at) is not None:
                summary["duplicate"] += 1
                continue

            speaker, score, binding = None, 0.0, "unknown"
            if t.region_type == "media":
                # Voices from a TV must never reach the gallery.
                summary["media_skipped"] += 1
            elif t.speech_s < pol.min_speech_s:
                summary["too_short"] += 1
            else:
                speaker, score, binding = self.match(vec, user_id, t.speech_s)

            if binding == "unknown" and t.region_type == "conversation" \
                    and t.speech_s >= pol.min_new_id_speech_s:
                if not dry_run:
                    speaker = self._create_pending(user_id, model_id, now)
                    binding, score = "high", 1.0
                summary["new_pending"] += 1

            if dry_run:
                summary[{"high": "bound_high", "gray": "bound_gray"}.get(binding, "unknown")] += 1
                continue

            turn_id = self._insert_turn(t, vec, model_id, dim, user_id,
                                        speaker["id"] if speaker else None, score, binding, now)
            summary["stored"] += 1
            summary[{"high": "bound_high", "gray": "bound_gray"}.get(binding, "unknown")] += 1

            if speaker is not None:
                label = speaker["label"]
                summary["by_speaker"][label] = summary["by_speaker"].get(label, 0) + 1
                touched.add(speaker["id"])
                # Admission gate: only confident, long-enough, non-media turns may
                # shape the gallery. This is the main defence against drift.
                if binding == "high" and t.speech_s >= pol.exemplar_min_speech_s:
                    if self._add_exemplar(speaker["id"], turn_id, vec, model_id, t.speech_s, now):
                        summary["exemplars_added"] += 1

        if not dry_run:
            for sid in touched:
                self.rebuild(sid)
            self._conn.commit()
        return summary

    def _find_turn(self, user_id: str, source_file: str, started_at: float) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM speaker_turns WHERE user_id=? AND source_file=? AND started_at=?",
            (user_id, source_file, started_at),
        ).fetchone()
        return row[0] if row else None

    def _insert_turn(self, t: SpeakerTurn, vec: np.ndarray, model_id: str, dim: int,
                     user_id: str, speaker_id: int | None, score: float,
                     binding: str, now: float) -> int:
        cur = self._conn.execute(
            """INSERT INTO speaker_turns
               (started_at, ended_at, date, tz, embedding, model_id, dim, speech_s, quality,
                region_type, speaker_id, confidence, binding, source_file, status, user_id,
                created_at, metadata)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t.started_at, t.ended_at, t.date, t.tz, vec.astype(np.float32).tobytes(),
             model_id, dim, t.speech_s, t.quality, t.region_type, speaker_id,
             round(score, 4), binding, t.source_file, "active", user_id, now,
             json.dumps(t.metadata, ensure_ascii=False)),
        )
        return cur.lastrowid

    def _create_pending(self, user_id: str, model_id: str, now: float) -> dict:
        n = self._conn.execute(
            "SELECT COUNT(*) FROM speakers WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        label = f"spk_{n + 1:03d}"
        while self._conn.execute(
            "SELECT 1 FROM speakers WHERE user_id=? AND label=?", (user_id, label)
        ).fetchone():
            n += 1
            label = f"spk_{n + 1:03d}"
        cur = self._conn.execute(
            """INSERT INTO speakers (label, status, model_id, first_seen_at, last_seen_at,
                                     user_id, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (label, "pending", model_id, now, now, user_id, now),
        )
        return dict(self._conn.execute(
            "SELECT * FROM speakers WHERE id=?", (cur.lastrowid,)).fetchone())

    def _add_exemplar(self, speaker_id: int, turn_id: int, vec: np.ndarray,
                      model_id: str, speech_s: float, now: float) -> bool:
        self._conn.execute(
            """INSERT INTO speaker_exemplars (speaker_id, turn_id, embedding, model_id,
                                              speech_s, added_at) VALUES (?,?,?,?,?,?)""",
            (speaker_id, turn_id, vec.astype(np.float32).tobytes(), model_id, speech_s, now),
        )
        self._evict_exemplars(speaker_id)
        return True

    def _evict_exemplars(self, speaker_id: int) -> None:
        """Keep the set diverse, not recent. FIFO would wipe out a whole acoustic
        environment after one week of the person speaking somewhere else, so the
        most REDUNDANT exemplar (highest mean similarity to the rest) is dropped."""
        ex = self._exemplars(speaker_id)
        while len(ex) > self.policy.max_exemplars:
            mat = np.stack([v for _, v in ex])
            sims = mat @ mat.T
            np.fill_diagonal(sims, 0.0)
            drop = int(np.argmax(sims.mean(axis=1)))
            self._conn.execute("DELETE FROM speaker_exemplars WHERE id=?", (ex[drop][0],))
            ex.pop(drop)

    # --- derived caches ---------------------------------------------------

    def rebuild(self, speaker_id: int) -> dict[str, Any]:
        """Recompute centroid + rollup stats from the turns. Always safe to call."""
        ex = self._exemplars(speaker_id)
        now = time.time()
        if ex:
            mat = np.stack([v for _, v in ex])
            centroid = normalize(mat.mean(axis=0))
            row = self._conn.execute(
                "SELECT model_id FROM speaker_exemplars WHERE speaker_id=? LIMIT 1",
                (speaker_id,)).fetchone()
            self._conn.execute(
                """INSERT INTO speaker_centroids (speaker_id, centroid, model_id, dim,
                                                  n_exemplars, rebuilt_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(speaker_id) DO UPDATE SET centroid=excluded.centroid,
                     model_id=excluded.model_id, dim=excluded.dim,
                     n_exemplars=excluded.n_exemplars, rebuilt_at=excluded.rebuilt_at""",
                (speaker_id, centroid.astype(np.float32).tobytes(), row[0] if row else "",
                 len(centroid), len(ex), now),
            )
        else:
            self._conn.execute("DELETE FROM speaker_centroids WHERE speaker_id=?", (speaker_id,))

        stats = self._conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(speech_s),0), COUNT(DISTINCT date),
                      MIN(started_at), MAX(started_at)
               FROM speaker_turns WHERE speaker_id=? AND status='active'""",
            (speaker_id,),
        ).fetchone()
        self._conn.execute(
            """UPDATE speakers SET turn_count=?, total_speech_s=?, days_seen=?,
                                   first_seen_at=?, last_seen_at=? WHERE id=?""",
            (stats[0], round(stats[1], 1), stats[2], stats[3] or 0, stats[4] or 0, speaker_id),
        )
        self._conn.commit()
        return {"speaker_id": speaker_id, "exemplars": len(ex), "turns": stats[0],
                "speech_s": round(stats[1], 1), "days": stats[2]}

    # --- lifecycle --------------------------------------------------------

    def promote(self, user_id: str = "", now: float | None = None) -> dict[str, Any]:
        """Pending → active for clusters that look like a real recurring person,
        and expire the ones that never grew.

        The "seen on ≥2 distinct days" rule is what separates someone who lives in
        your life from a TV character or a one-off passer-by.
        """
        pol = self.policy
        now = now or time.time()
        out: dict[str, Any] = {"promoted": [], "expired": []}
        for sp in self._speakers(user_id, statuses=("pending",)):
            self.rebuild(sp["id"])
            row = dict(self._conn.execute(
                "SELECT * FROM speakers WHERE id=?", (sp["id"],)).fetchone())
            if (row["turn_count"] >= pol.promote_min_turns
                    and row["total_speech_s"] >= pol.promote_min_speech_s
                    and row["days_seen"] >= pol.promote_min_days):
                self._conn.execute("UPDATE speakers SET status='active' WHERE id=?", (sp["id"],))
                out["promoted"].append(row["label"])
            elif now - row["created_at"] > pol.pending_ttl_days * DAY_S:
                self._conn.execute("UPDATE speakers SET status='archived' WHERE id=?", (sp["id"],))
                out["expired"].append(row["label"])
        self._conn.commit()
        return out

    def name(self, label: str, display_name: str, user_id: str = "",
             confidence: float = 1.0, evidence: str = "") -> dict[str, Any]:
        """Bind a human identity to a voice. Low-confidence names are proposals
        (inferred from how people are addressed); confirmation raises them."""
        sp = self.get(label, user_id)
        if not sp:
            return {"error": f"unknown speaker {label}"}
        self._conn.execute(
            "UPDATE speakers SET display_name=?, name_confidence=?, name_evidence=? WHERE id=?",
            (display_name, confidence, evidence, sp["id"]),
        )
        self._conn.commit()
        return {"label": label, "display_name": display_name, "confidence": confidence}

    def merge(self, from_label: str, into_label: str, user_id: str = "",
              reason: str = "", dry_run: bool = False) -> dict[str, Any]:
        """Repoint every turn, then rebuild. Reversible precisely because the turn
        embeddings were kept.

        If the absorbed identity was the wearer, the survivor becomes the wearer.
        Losing that flag is not a cosmetic loss: the exported gallery would carry
        no wearer centroid, so the audio tool could no longer tell conversation
        from ambient media, and the owner would silently vanish from every future
        episode's participants.
        """
        # Follow tombstones on BOTH sides. A merge command is often composed long
        # before it runs — a question sitting in a chat, answered after a different
        # merge already moved one of its subjects — and repointing turns onto an
        # identity that has since been archived would drop them out of the gallery
        # entirely. "X is Y" plus "Y is Z" means X is Z.
        from_label = self.resolve_label(from_label, user_id)
        into_label = self.resolve_label(into_label, user_id)
        a = self.get(from_label, user_id)
        b = self.get(into_label, user_id)
        if not a or not b:
            return {"error": "unknown speaker label"}
        if a["id"] == b["id"]:
            # Both sides already resolved to the same person: the answer this
            # command carries has effectively been applied. Say so rather than
            # failing, because the caller pressed a button and deserves a result.
            return {"from": from_label, "into": into_label, "turns_moved": 0,
                    "already_merged": True}
        n = self._conn.execute(
            "SELECT COUNT(*) FROM speaker_turns WHERE speaker_id=?", (a["id"],)).fetchone()[0]
        if dry_run:
            return {"from": from_label, "into": into_label, "turns": n, "dry_run": True}

        self._conn.execute("UPDATE speaker_turns SET speaker_id=? WHERE speaker_id=?",
                           (b["id"], a["id"]))
        self._conn.execute("DELETE FROM speaker_exemplars WHERE speaker_id=?", (a["id"],))
        self._conn.execute("DELETE FROM speaker_centroids WHERE speaker_id=?", (a["id"],))
        self._conn.execute(
            """INSERT INTO speaker_merges (old_speaker_id, old_label, new_speaker_id,
                                           merged_at, reason) VALUES (?,?,?,?,?)""",
            (a["id"], a["label"], b["id"], time.time(), reason),
        )
        self._conn.execute("UPDATE speakers SET status='archived', is_wearer=0 WHERE id=?",
                           (a["id"],))
        wearer_moved = bool(a["is_wearer"]) and not b["is_wearer"]
        if wearer_moved:
            self._conn.execute("UPDATE speakers SET is_wearer=1, status='active' WHERE id=?",
                               (b["id"],))
        self._reseed_exemplars(b["id"])
        self.rebuild(b["id"])
        self._conn.commit()
        out = {"from": from_label, "into": into_label, "turns_moved": n}
        if wearer_moved:
            out["wearer_moved_to"] = into_label
        return out

    def merge_candidates(self, user_id: str = "") -> list[dict[str, Any]]:
        """Pairs similar enough to be worth PROPOSING a merge. Never auto-applied:
        a wrong merge is silent and unrecoverable from the centroid alone.

        Only `active` speakers are compared — the pending pool is full of
        passers-by, and proposing merges among strangers is noise, not insight.
        Pairs the owner has already told apart are excluded.
        """
        people = self._speakers(user_id, statuses=("active",))
        known_distinct = self._distinct_ids(user_id)
        out = []
        for i, a in enumerate(people):
            ca = self._centroid(a["id"])
            if ca is None:
                continue
            for b in people[i + 1:]:
                if self._pair_key(a["id"], b["id"]) in known_distinct:
                    continue
                cb = self._centroid(b["id"])
                if cb is None:
                    continue
                s = cosine(ca, cb)
                if s >= self.policy.merge_propose_at:
                    out.append({"a": a["label"], "b": b["label"], "similarity": round(s, 4)})
        return sorted(out, key=lambda x: -x["similarity"])

    @staticmethod
    def _pair_key(a_id: int, b_id: int) -> tuple[int, int]:
        """Order a pair so the relation is symmetric however it was asked."""
        return (a_id, b_id) if a_id <= b_id else (b_id, a_id)

    def _distinct_ids(self, user_id: str = "") -> set[tuple[int, int]]:
        rows = self._conn.execute(
            "SELECT a_id, b_id FROM speaker_distinct WHERE user_id=?", (user_id,)).fetchall()
        return {(r[0], r[1]) for r in rows}

    def mark_distinct(self, a_label: str, b_label: str, user_id: str = "") -> dict[str, Any]:
        """Record the owner's "no, those are two different people".

        The answer has to outlive the question: these two centroids will stay
        similar forever, so without this the same pair resurfaces on every scan.
        """
        a = self.get(self.resolve_label(a_label, user_id), user_id)
        b = self.get(self.resolve_label(b_label, user_id), user_id)
        if not a:
            return {"error": f"unknown speaker {a_label}"}
        if not b:
            return {"error": f"unknown speaker {b_label}"}
        if a["id"] == b["id"]:
            return {"error": "a speaker cannot be distinct from itself", "label": a["label"]}
        x, y = self._pair_key(a["id"], b["id"])
        self._conn.execute(
            "INSERT OR REPLACE INTO speaker_distinct (a_id, b_id, user_id, marked_at) "
            "VALUES (?,?,?,?)", (x, y, user_id, time.time()))
        self._conn.commit()
        return {"a": a["label"], "b": b["label"], "distinct": True}

    def ignore(self, label: str, user_id: str = "") -> dict[str, Any]:
        """"Don't bother recording this person" — never asked about, never promoted.

        Their turns keep resolving to this identity (see `match`), so an ignored
        regular stays recognised instead of fragmenting into new pending ids.
        """
        sp = self.get(self.resolve_label(label, user_id), user_id)
        if not sp:
            return {"error": f"unknown speaker {label}"}
        if sp["is_wearer"]:
            return {"error": "refusing to ignore the wearer", "label": sp["label"]}
        self._conn.execute("UPDATE speakers SET status='ignored' WHERE id=?", (sp["id"],))
        self._conn.commit()
        return {"label": sp["label"], "status": "ignored"}

    def split(self, label: str, user_id: str = "", dry_run: bool = False) -> dict[str, Any]:
        """Re-cluster one speaker's turns into two (seeded by the two least similar
        turns) and move the smaller cluster to a new identity."""
        sp = self.get(label, user_id)
        if not sp:
            return {"error": f"unknown speaker {label}"}
        rows = self._conn.execute(
            "SELECT id, embedding FROM speaker_turns WHERE speaker_id=? AND status='active'",
            (sp["id"],)).fetchall()
        if len(rows) < 4:
            return {"error": "not enough turns to split", "turns": len(rows)}

        ids = [r[0] for r in rows]
        mat = np.stack([from_blob(r[1]) for r in rows])
        sims = mat @ mat.T
        i, j = np.unravel_index(int(np.argmin(sims)), sims.shape)
        for _ in range(5):
            ca, cb = normalize(mat[i]), normalize(mat[j])
            assign = (mat @ ca) < (mat @ cb)
            if assign.all() or (~assign).all():
                break
            ca = normalize(mat[~assign].mean(axis=0))
            cb = normalize(mat[assign].mean(axis=0))
            i, j = int(np.argmax(mat @ ca)), int(np.argmax(mat @ cb))
        moving = [ids[k] for k in range(len(ids)) if assign[k]]
        if not moving or len(moving) == len(ids):
            return {"error": "turns did not separate"}
        if dry_run:
            return {"label": label, "would_move": len(moving), "keeps": len(ids) - len(moving),
                    "dry_run": True}

        new = self._create_pending(user_id, sp["model_id"], time.time())
        q = ",".join("?" * len(moving))
        self._conn.execute(
            f"UPDATE speaker_turns SET speaker_id=? WHERE id IN ({q})", (new["id"], *moving))
        self._conn.execute(
            f"DELETE FROM speaker_exemplars WHERE turn_id IN ({q})", tuple(moving))
        self._reseed_exemplars(new["id"])
        self.rebuild(new["id"])
        self.rebuild(sp["id"])
        self._conn.commit()
        return {"label": label, "new_label": new["label"], "turns_moved": len(moving)}

    def _reseed_exemplars(self, speaker_id: int) -> None:
        """Rebuild the exemplar set from the speaker's own turns (after merge/split)."""
        pol = self.policy
        have = {r[0] for r in self._conn.execute(
            "SELECT turn_id FROM speaker_exemplars WHERE speaker_id=?", (speaker_id,))}
        rows = self._conn.execute(
            """SELECT id, embedding, model_id, speech_s FROM speaker_turns
               WHERE speaker_id=? AND status='active' AND binding='high'
                 AND region_type!='media' AND speech_s>=?
               ORDER BY speech_s DESC LIMIT ?""",
            (speaker_id, pol.exemplar_min_speech_s, pol.max_exemplars * 2),
        ).fetchall()
        now = time.time()
        for r in rows:
            if r[0] in have:
                continue
            self._conn.execute(
                """INSERT INTO speaker_exemplars (speaker_id, turn_id, embedding, model_id,
                                                  speech_s, added_at) VALUES (?,?,?,?,?,?)""",
                (speaker_id, r[0], r[1], r[2], r[3], now),
            )
        self._evict_exemplars(speaker_id)

    def forget(self, label: str, user_id: str = "", dry_run: bool = False) -> dict[str, Any]:
        """Erase a person: turns, embeddings, exemplars, centroid, tombstones.

        Callers must also anonymize `@<label>` references in already-generated
        text — that is why generated prose refers to people by label rather than
        by name (see the design doc).
        """
        sp = self.get(label, user_id)
        if not sp:
            return {"error": f"unknown speaker {label}"}
        n = self._conn.execute(
            "SELECT COUNT(*) FROM speaker_turns WHERE speaker_id=?", (sp["id"],)).fetchone()[0]
        if dry_run:
            return {"label": label, "turns": n, "dry_run": True}
        self._conn.execute("DELETE FROM speaker_turns WHERE speaker_id=?", (sp["id"],))
        self._conn.execute("DELETE FROM speaker_exemplars WHERE speaker_id=?", (sp["id"],))
        self._conn.execute("DELETE FROM speaker_centroids WHERE speaker_id=?", (sp["id"],))
        self._conn.execute(
            "DELETE FROM speaker_merges WHERE old_speaker_id=? OR new_speaker_id=?",
            (sp["id"], sp["id"]))
        self._conn.execute(
            "DELETE FROM speaker_distinct WHERE a_id=? OR b_id=?", (sp["id"], sp["id"]))
        self._conn.execute("DELETE FROM speakers WHERE id=?", (sp["id"],))
        self._conn.commit()
        return {"label": label, "turns_deleted": n, "forgotten": True}

    # --- reads ------------------------------------------------------------

    def resolve_label(self, label: str, user_id: str = "") -> str:
        """Follow merge tombstones so old labels in historical text still resolve."""
        seen = set()
        cur = label
        while cur not in seen:
            seen.add(cur)
            row = self._conn.execute(
                """SELECT s.label FROM speaker_merges m JOIN speakers s ON s.id=m.new_speaker_id
                   WHERE m.old_label=? ORDER BY m.merged_at DESC LIMIT 1""", (cur,)).fetchone()
            if not row:
                return cur
            cur = row[0]
        return cur

    def get(self, label: str, user_id: str = "") -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM speakers WHERE user_id=? AND label=?", (user_id, label)).fetchone()
        return dict(row) if row else None

    def list_speakers(self, user_id: str = "", status: str = "") -> list[dict[str, Any]]:
        where, params = ["user_id=?"], [user_id]
        if status:
            where.append("status=?"); params.append(status)
        rows = self._conn.execute(
            f"SELECT id, label, display_name, name_confidence, status, is_wearer, turn_count, "
            f"total_speech_s, days_seen, first_seen_at, last_seen_at FROM speakers "
            f"WHERE {' AND '.join(where)} ORDER BY total_speech_s DESC", params,
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self, user_id: str = "") -> dict[str, Any]:
        c = self._conn
        turns = c.execute("SELECT COUNT(*) FROM speaker_turns WHERE user_id=?", (user_id,)).fetchone()[0]
        bound = c.execute(
            "SELECT COUNT(*) FROM speaker_turns WHERE user_id=? AND speaker_id IS NOT NULL",
            (user_id,)).fetchone()[0]
        model, dim = self.gallery_model(user_id)
        by_status = {s: c.execute(
            "SELECT COUNT(*) FROM speakers WHERE user_id=? AND status=?", (user_id, s)).fetchone()[0]
            for s in ("active", "pending", "archived", "ignored")}
        return {"turns": turns, "turns_bound": bound, "speakers": by_status,
                "model_id": model, "dim": dim}

    def export_known(self, user_id: str = "", status: tuple[str, ...] = ("active",)) -> dict[str, Any]:
        """The gallery in the shape the audio tool consumes.

        Centroids only — the tool gets just enough to route a recording (which
        stretches are the wearer talking) and never enough to hold an identity.
        """
        model_id, dim = self.gallery_model(user_id)
        out = []
        for sp in self._speakers(user_id, statuses=status):
            c = self._centroid(sp["id"])
            if c is None:
                continue
            out.append({"label": sp["label"], "display_name": sp["display_name"],
                        "is_wearer": bool(sp["is_wearer"]),
                        "centroid": encode_embedding(c)})
        return {"model_id": model_id, "dim": dim, "speakers": out}

    def set_wearer(self, label: str, user_id: str = "") -> dict[str, Any]:
        """Mark which speaker is the wearer. Exactly one per user."""
        sp = self.get(label, user_id)
        if not sp:
            return {"error": f"unknown speaker {label}"}
        self._conn.execute("UPDATE speakers SET is_wearer=0 WHERE user_id=?", (user_id,))
        self._conn.execute("UPDATE speakers SET is_wearer=1, status='active' WHERE id=?", (sp["id"],))
        self._conn.commit()
        return {"label": label, "is_wearer": True}

    def present_between(self, started_at: float = 0.0, ended_at: float = 0.0,
                        user_id: str = "", date: str = "",
                        include_pending: bool = False,
                        min_speech_s: float = 0.0) -> dict[str, Any]:
        """Who was actually in the room during a stretch of time.

        Exists so that whoever writes an episode never has to invent participants.
        A transcription model renames speakers from scratch in every chunk — its
        "speaker A" in one chunk is a different person from "speaker A" in the
        next — so a summary built over many chunks lists everyone it ever saw
        (one real episode ended up with 85 participants). Voice identity is the
        only thing that survives across chunks, and it lives here.

        Give a `date` when the episode has no absolute window: several real
        episodes carry the clock string "不确定" and `started_at = 0`, and a
        whole-day answer beats a fabricated one.

        `unbound_turns` is reported rather than hidden — it says how much speech
        in the window could NOT be attributed, so the caller can tell a short
        list from a confident one.
        """
        statuses = ("active", "pending") if include_pending else ("active",)
        where = ["t.user_id=?", "t.status='active'", "t.region_type!='media'"]
        params: list[Any] = [user_id]
        if started_at or ended_at:
            # overlap, not containment: a turn straddling the boundary was present
            where.append("t.started_at < ? AND t.ended_at > ?")
            params += [ended_at if ended_at else float("inf"), started_at]
        if date:
            where.append("t.date=?")
            params.append(date)
        clause = " AND ".join(where)

        q = ",".join("?" * len(statuses))
        rows = self._conn.execute(
            f"""SELECT s.label, s.display_name, s.is_wearer, s.status,
                       COUNT(*), COALESCE(SUM(t.speech_s),0),
                       MIN(t.started_at), MAX(t.ended_at)
                FROM speaker_turns t JOIN speakers s ON s.id=t.speaker_id
                WHERE {clause} AND s.status IN ({q})
                GROUP BY s.id HAVING COALESCE(SUM(t.speech_s),0) >= ?
                ORDER BY 6 DESC""",
            (*params, *statuses, min_speech_s),
        ).fetchall()
        unbound = self._conn.execute(
            f"SELECT COUNT(*) FROM speaker_turns t WHERE {clause} AND t.speaker_id IS NULL",
            params).fetchone()[0]

        return {
            "window": {"from": started_at, "to": ended_at, "date": date},
            "present": [{"label": r[0], "display_name": r[1], "is_wearer": bool(r[2]),
                         "status": r[3], "turns": r[4], "speech_s": round(r[5], 1),
                         "first_at": r[6], "last_at": r[7]} for r in rows],
            "unbound_turns": unbound,
        }

    # --- name candidates ------------------------------------------------------

    def set_name_candidates(self, label: str, candidates: list[dict[str, Any]],
                            user_id: str = "") -> dict[str, Any]:
        """Store name PROPOSALS for a speaker. Never touches `display_name`.

        Being talked about and being in the room are different things, so a
        candidate is only ever an option to offer the owner — the naming itself
        stays a deliberate act.
        """
        sp = self.get(self.resolve_label(label, user_id), user_id)
        if not sp:
            return {"error": f"unknown speaker {label}"}
        meta = json.loads(sp["metadata"] or "{}")
        meta["name_candidates"] = candidates
        self._conn.execute("UPDATE speakers SET metadata=? WHERE id=?",
                           (json.dumps(meta, ensure_ascii=False), sp["id"]))
        self._conn.commit()
        return {"label": sp["label"], "candidates": [c["name"] for c in candidates]}

    @staticmethod
    def _name_candidates(sp: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            return json.loads(sp.get("metadata") or "{}").get("name_candidates", []) or []
        except (json.JSONDecodeError, AttributeError):
            return []

    # --- questions ----------------------------------------------------------

    def _turn_facets(self, speaker_id: int, clips: int = 2) -> dict[str, Any]:
        """The evidence a person needs to recognise who is being asked about:
        which days, how much talking, and where to find a listenable moment."""
        rows = self._conn.execute(
            """SELECT source_file, started_at, ended_at, speech_s, date, tz
               FROM speaker_turns
               WHERE speaker_id=? AND status='active' AND region_type!='media'
               ORDER BY speech_s DESC""", (speaker_id,)).fetchall()
        days = sorted({r[4] for r in rows if r[4]})
        return {
            "days": days,
            "turns": len(rows),
            "speech_s": round(sum(r[3] for r in rows), 1),
            # Longest turns first: the clearest thing this person ever said is the
            # best three seconds to play back.
            "clips": [{"source_file": r[0], "started_at": r[1], "ended_at": r[2],
                       "speech_s": round(r[3], 1), "tz": r[5]} for r in rows[:clips]],
            "contexts": [clock(r[1], r[5]) for r in rows[:clips]],
        }

    def pending_questions(self, user_id: str = "", limit: int = 20) -> dict[str, Any]:
        """What this namespace is unsure about, as questions the owner can answer
        in one tap. Mind decides WHAT is worth asking; the caller decides WHEN.

        Two rules make this a feature rather than a nuisance:

        - **Only `active` speakers are ever asked about.** The pending pool is
          mostly strangers picked up in public — one restaurant evening minted two
          identities with 600+ turns each — and asking the owner to name a passer-by
          is harassment, not help.
        - **Clips carry coordinates, never audio.** The recordings stay on the
          capture machine; a question says where to listen, and whoever delivers it
          cuts the audio locally if it is needed at all.

        Every question carries its own `apply` map, so the deliverer can turn a
        button press into the right write without understanding any of the
        semantics. Ids are stable so a restart re-asks nothing.
        """
        questions: list[dict[str, Any]] = []

        for cand in self.merge_candidates(user_id):
            a = self.get(cand["a"], user_id)
            b = self.get(cand["b"], user_id)
            if not a or not b:
                continue
            # Merge the quieter identity INTO the more established one, so the
            # label that already appears in generated text is the one that lives on.
            src, dst = ((a, b) if (a["total_speech_s"], a["id"])
                        <= (b["total_speech_s"], b["id"]) else (b, a))
            # ...except that the wearer always survives, however little they said.
            # They are an anchor the owner set by hand and the audio pipeline reads
            # (no wearer centroid → conversation and ambient media stop being
            # separable), so the direction cannot be left to a speech-time tally.
            if src["is_wearer"]:
                src, dst = dst, src
            fa, fb = self._turn_facets(src["id"]), self._turn_facets(dst["id"])
            questions.append({
                "id": f"merge:{src['label']}:{dst['label']}",
                "kind": "merge",
                "subjects": [src["label"], dst["label"]],
                "confidence": cand["similarity"],
                "evidence": {
                    "days": sorted(set(fa["days"]) | set(fb["days"])),
                    "turns": fa["turns"] + fb["turns"],
                    "speech_s": round(fa["speech_s"] + fb["speech_s"], 1),
                    "contexts": fa["contexts"] + fb["contexts"],
                    "by_subject": {src["label"]: fa, dst["label"]: fb},
                },
                "question": "这两段是同一个人吗？",
                "options": [{"key": "same", "label": "是"},
                            {"key": "diff", "label": "不是"},
                            {"key": "unsure", "label": "听不出"}],
                "clips": ([{"label": src["label"], **c} for c in fa["clips"]]
                          + [{"label": dst["label"], **c} for c in fb["clips"]]),
                "apply": {
                    "same": f"speakers merge {src['label']} {dst['label']}",
                    "diff": f"speakers mark-distinct {src['label']} {dst['label']}",
                },
            })

        # Someone who has been around for days and is still a number is worth a
        # name. Loudest first — the people you actually live with come before the
        # ones you merely passed.
        for sp in sorted(self._speakers(user_id, statuses=("active",)),
                         key=lambda s: -s["total_speech_s"]):
            if sp["display_name"] or sp["is_wearer"]:
                continue
            f = self._turn_facets(sp["id"])
            label = sp["label"]
            # Candidates turn this from "type a name" into "tap one" — the whole
            # point of harvesting them (see refinement/name_hints.py). They stay
            # proposals: "都不是" is always available and never pre-selected.
            cands = self._name_candidates(sp)
            # Only candidates we would stand behind become tap targets. A weak
            # co-occurrence (someone discussed once while this speaker happened to
            # be around) still gets recorded as evidence below, because the owner
            # may recognise it — but offering it as a button invites a mis-tap that
            # writes the wrong name, and it dilutes the one good guess.
            strong = [c for c in cands if c.get("strong")]
            options = [{"key": c["name"], "label": c["name"]} for c in strong]
            apply_map = {c["name"]: f"speakers name {label} {c['name']}" for c in strong}
            if options:
                options.append({"key": "other", "label": "都不是"})
            options.append({"key": "skip", "label": "不用记这个人"})
            # `other`/`text` is a template — the one place a deliverer must
            # substitute rather than execute verbatim.
            apply_map["other"] = apply_map["text"] = f"speakers name {label} {{answer}}"
            apply_map["skip"] = f"speakers ignore {label}"

            evidence = {"days": f["days"], "turns": f["turns"],
                        "speech_s": f["speech_s"], "contexts": f["contexts"]}
            if cands:
                # Provenance, so the owner can see what the guess rests on rather
                # than being asked to trust it.
                evidence["name_candidates"] = cands
            questions.append({
                "id": f"name:{label}",
                "kind": "name",
                "subjects": [label],
                "confidence": max((c["confidence"] for c in strong), default=0.0),
                "evidence": evidence,
                "question": "这个人是谁？",
                "options": options,
                # Still accepts free text even when options exist — the candidates
                # are a shortcut, not the full set of possible answers.
                "answer_type": "choice_or_text" if strong else "text",
                "clips": [{"label": label, **c} for c in f["clips"]],
                "apply": apply_map,
            })

        return {"questions": questions[:limit], "total": len(questions),
                "truncated": len(questions) > limit}

    def manual(self, user_id: str = "") -> dict[str, Any]:
        """Machine-readable self-description, for an agent deciding whether and how
        to use this namespace (same contract shape as other self-describing tools)."""
        st = self.stats(user_id)
        active = st["speakers"]["active"]
        return {
            "namespace": "speakers",
            "division_of_labor": {
                "use_me_for": "resolving a voice embedding to a stable person, and "
                              "accumulating who recurs across days",
                "not_me": "audio processing and embedding extraction (the audio tool does that); "
                          "episode/day narrative (lifelog); durable facts (memories)",
            },
            "coverage": {"model_id": st["model_id"], "dim": st["dim"],
                         "active_speakers": active, "pending": st["speakers"]["pending"],
                         "turns": st["turns"]},
            "policy": {k: getattr(self.policy, k) for k in MatchPolicy.__dataclass_fields__},
            "calibration": {
                "calibrated": bool(self.policy.calibrated_for
                                   and self.policy.calibrated_for == (st["model_id"] or "")),
                "calibrated_for": self.policy.calibrated_for,
                "gallery_model": st["model_id"],
                "note": "thresholds are a property of the embedding model, not of the task. "
                        "They hold only while the gallery model matches `calibrated_for`; "
                        "swapping models requires re-measuring from labelled recordings. "
                        "Bias high: a split is visible and reversible, a merge is silent.",
            },
            "health": {
                "ok": st["turns"] == 0 or st["turns_bound"] > 0,
                "unbound_turns": st["turns"] - st["turns_bound"],
                "merge_candidates": len(self.merge_candidates(user_id)),
            },
            "maintenance": {"recommended_actions": self._recommended(st, user_id)},
        }

    def _recommended(self, st: dict, user_id: str) -> list[dict[str, str]]:
        out = []
        if st["speakers"]["pending"]:
            out.append({"why": "pending speakers may be ready to promote",
                        "command": "radiomind speakers promote"})
        cands = self.merge_candidates(user_id)
        if cands:
            out.append({"why": f"{len(cands)} speaker pair(s) look like the same person",
                        "command": f"radiomind speakers merge {cands[0]['b']} {cands[0]['a']} --dry-run"})
        unnamed = sum(1 for s in self._speakers(user_id, statuses=("active",))
                      if not s["display_name"] and not s["is_wearer"])
        if cands or unnamed:
            out.append({"why": "there are things only the owner can answer "
                               "(same person? who is this?)",
                        "command": "radiomind speakers pending-questions"})
        return out
