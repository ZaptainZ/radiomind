"""Bottom-up numeric-fact aggregator.

Moves aggregation work (counting instruments, summing donations) from
query time to ingest time. Maintains a per-(user, domain, entity_class)
cardinal cache so "how many X do I own" hits deterministic state
instead of re-deriving from top-k retrieval on every query.

Extraction: LLM batch-extract (one call per ~12 user turns) with regex
keyword gate to filter ~70% of non-cardinal turns. Regex fallback when
LLM is unavailable. Ontology rollup writes each event to both specific
and parent classes (guitars → musical_instruments).

Query-time refinement: trinity.debate() over candidate members / amount
events to dedup and filter misclassified.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from radiomind.refinement.ontology import ROLLUP, ALIASES


NUMERIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS cardinal_entries (
    user_id TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    entity_class TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    total_amount REAL,
    currency TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    history_json TEXT NOT NULL DEFAULT '[]',
    members_json TEXT NOT NULL DEFAULT '[]',
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, domain, entity_class)
);

CREATE INDEX IF NOT EXISTS idx_cardinal_domain ON cardinal_entries(domain);
CREATE INDEX IF NOT EXISTS idx_cardinal_class ON cardinal_entries(entity_class);
"""


# Regex fast path. These patterns cheaply identify turns that MIGHT carry
# a cardinal delta; an LLM normalizer later confirms + classifies. We
# intentionally over-match here (false positives are harmless — LLM
# filters them out), but under-match is expensive (LLM never sees those
# turns).
#
# Groups captured:
#   (1) the object phrase (entity candidate)
# The verb polarity is carried separately via the pattern's bucket.
OWN_PATTERNS = [
    # "I bought / got / purchased / picked up / brought home / adopted / acquired
    #  / replaced / fixed / installed / assembled / upgraded / set up ..."
    # Allows intervening adverbs: "I also got", "I just bought", "I later picked up".
    # Determiner prefixes are ordered longest-first so "a new X" captures
    # "X" rather than "new X".
    re.compile(
        r"\bi\s+(?:just\s+|also\s+|then\s+|later\s+|recently\s+|finally\s+|already\s+)?"
        r"(?:bought|got|picked\s+up|brought\s+home|purchased|acquired|adopted|"
        r"received|added|ordered|replaced|fixed|repaired|installed|assembled|"
        r"upgraded|set\s+up|put\s+up|put\s+in)\s+"
        r"(?:a\s+brand[\- ]new\s+|a\s+new\s+|a\s+nice\s+|a\s+cheap\s+|a\s+fancy\s+|"
        r"an\s+old\s+|the\s+old\s+|my\s+old\s+|"
        r"a\s+|an\s+|some\s+|my\s+|another\s+|the\s+|new\s+|old\s+)?"
        r"(.{2,80}?)"
        r"(?:\.|,|!|\?|$|\s+(?:from|at|for|on|to|with|yesterday|today|"
        r"last|this|myself))",
        re.IGNORECASE,
    ),
    # "I have / own / keep ..."  (statement-of-ownership).
    # Stop capture before relative-clause markers OR pronoun subjects
    # introducing a new clause ("I own a violin my grandmother gave me").
    re.compile(
        r"\bi\s+(?:currently\s+|now\s+)?(?:have|own|keep|possess)\s+"
        r"(?:a\s+|an\s+|my\s+|the\s+)?(.{2,80}?)"
        r"(?:\.|,|!|\?|$|\s+(?:that|which|who|"
        r"my|your|his|her|their|our|he|she|they|it|from|at|in\s+my))",
        re.IGNORECASE,
    ),
    # Chinese: "我买了 / 我有 / 我入手了 / 我新买了 / 我修好了 / 我装了 ..."
    re.compile(r"我(?:新?买了|入手了|拥有|有了|新购了|修好了|装了|换了)\s*(.{1,40}?)(?:[，。！？,\.\!\?]|$)"),
]

DISPOSE_PATTERNS = [
    # Physical disposal only. "donated" / "gave away" stay out because
    # "I donated $500" is an amount event (money), not a tangible-item
    # disposal. If a turn says "I donated my old guitar to the shelter",
    # "gave away" below still catches that.
    re.compile(
        r"\bi\s+(?:just\s+)?(?:sold|gave\s+away|threw\s+(?:out|away)|"
        r"returned|lost|broke|got\s+rid\s+of|traded\s+in)\s+"
        r"(?:my\s+|the\s+|a\s+|an\s+)?(.{2,80}?)(?:\.|,|!|\?|$|\s+to|\s+for|\s+at)",
        re.IGNORECASE,
    ),
    re.compile(r"我(?:卖了|送掉了?|丢了|扔了|退了|不再使用|不再有)\s*(.{1,40}?)(?:[，。！？,\.\!\?]|$)"),
]

# Dollar-amount events — "how much did I donate/earn/raise/save".
# Tolerates intervening adverbs/quantifiers ("another", "about", "around",
# "roughly", "nearly") between the verb and the amount, which otherwise
# would dodge the regex (e.g. "I donated another $500 to the shelter").
#
# Variants we explicitly catch (previously missed on d851d5ba charity
# total, where half the events slipped past the narrow "i + verb" form):
#   - "we raised $X"           → subject {i|we}
#   - "I helped raise $X"      → helped modifier + base-form "raise"
#   - "...and raised $X for Y" → conjunction-initiated "raised" at clause start
AMOUNT_PATTERNS = [
    re.compile(
        r"\b(?:i|we)\s+(?:just\s+|already\s+|later\s+|then\s+|helped\s+)?"
        r"(?:raised?|donated|earned|made|saved|spent|paid|contributed|gave|received)\s+"
        r"(?:another\s+|additional\s+|about\s+|around\s+|roughly\s+|nearly\s+|approximately\s+|over\s+)?"
        r"(?:\$|usd\s*)?(\d[\d,\.]*)"
        r"(?:\s*(?:dollars?|usd|bucks?))?"
        r"(?:\s+(?:for|to|at|from|on|in)\s+(.{2,60}?))?(?:\.|,|!|\?|$)",
        re.IGNORECASE,
    ),
    # Conjunction-led clause: "...5 km and raised $250 for a local food bank"
    re.compile(
        r"\b(?:and|then|also)\s+raised\s+"
        r"(?:another\s+|about\s+|around\s+|over\s+)?"
        r"(?:\$|usd\s*)?(\d[\d,\.]*)"
        r"(?:\s+for\s+(.{2,60}?))?(?:\.|,|!|\?|$)",
        re.IGNORECASE,
    ),
]


# Fixed-cardinal assertions ("I have 4 instruments") — use these as
# ground-truth override when the user explicitly states the count.
EXPLICIT_COUNT_PATTERNS = [
    re.compile(
        r"\bi\s+(?:currently\s+|now\s+)?(?:have|own|keep)\s+(\d+)\s+(?:different\s+)?"
        r"([a-z][a-z\-\s]{2,40}?)(?:\.|,|!|\?|$)",
        re.IGNORECASE,
    ),
    re.compile(r"我(?:有|拥有)(\d+)\s*(?:个|件|种|款|只|条|把|台|部)?(.{1,20}?)(?:[，。！？,\.\!\?]|$)"),
]


# Prompt for LLM-side BATCH extraction from raw user turns. When an LLM
# is available this replaces the regex fast-path because regex cannot
# catch ownership reveals phrased as "I've had my Fender for 5 years"
# / "My Pearl drum set" / descriptive mentions embedded in longer
# sentences. A single LLM call per ~30 turns outputs the full candidate
# set directly — same batching pattern as KG triple extraction.
CLASS_DEFINITIONS = {
    "charity_donations": (
        "Money the user gave to a NAMED CHARITY ORGANIZATION, fundraiser, "
        "nonprofit, gala for a cause, political cause, or religious tithing. "
        "Generic gifts, purchases, rent, bills, family transfers are NOT charity."
    ),
    "savings_events": (
        "Money the user SAVED on a specific purchase, typically phrased as "
        "'saved $N on X' / 'got $N off X' / 'discount of $N'. Not general "
        "thrift or budget-cutting."
    ),
    "income_events": (
        "Money the user EARNED from a sale, job, refund, or gift received. "
        "Not purchase-related money movements."
    ),
    "spending_events": (
        "Money the user SPENT on a specific purchase of goods/services. "
        "Not donations, not savings."
    ),
}


BATCH_EXTRACT_PROMPT = """Extract OWNERSHIP and MONEY events from user turns.

OWN — every tangible countable item the USER owns or has. Ownership
reveals are enough, no purchase verb required:
  "I've had my Fender for 5 years"   → OWN Fender (musical_instruments)
  "My Pearl drum set sounds amazing" → OWN Pearl drum set
  "I replaced the kitchen faucet"    → OWN kitchen faucet (kitchen_items)
  "My niece got a new violin"        → NOT OWN (niece is not the user)
  "I'm thinking of buying X"         → NOT OWN (intention, not possession)

AMOUNT — every money event. Class depends on target:
  "I donated $500 to Red Cross"         → charity_donations $500
  "I raised $1500 at the fundraiser"    → charity_donations $1500
  "I saved $300 on the Jimmy Choo heels"→ savings_events $300 (member=heels)
  "I bought the heels for $500"         → spending_events $500
  "I earned $200 from the sale"         → income_events $200

A single purchase can emit BOTH (OWN + AMOUNT) with the same turn index.

Entity class scope (strict):
  musical_instruments: guitar/piano/drums/ukulele/violin/pedal/etc. (NOT toy models)
  kitchen_items:       DURABLE tools — faucet/toaster/blender/microwave/etc.
                       NEVER food, groceries, ingredients
  clothing_items:      shoes/jacket/boots/heels/dress/etc.
  vehicles, pets, books_read, hikes, trips, electronics, furniture, sporting_goods
  charity_donations:   ONLY named charities/fundraisers/nonprofits
                       NOT gifts to family, rent, bills
  income_events, savings_events, spending_events

Turns:
{turns}

Output STRICT JSON — one record per event (a turn may yield multiple):
{{
  "events": [
    {{"turn": 2, "polarity": "own", "entity_class": "musical_instruments",
      "canonical_member": "Fender Stratocaster", "amount": null, "currency": null}},
    {{"turn": 7, "polarity": "amount", "entity_class": "charity_donations",
      "canonical_member": "", "amount": 500, "currency": "USD"}}
  ]
}}"""


# Filter stage for regex-extracted candidates (no LLM batch). Rejects
# pronoun/fragment/abstract phrases that the regex fast-path picks up
# from long haystacks.
CLASSIFY_PROMPT = """You normalize cardinality candidates into ontology buckets.

Given a list of (turn_id, polarity, object_phrase) items extracted from user messages
by a regex fast-path, for each one output a JSON record:
  - valid: true ONLY if the phrase is a concrete countable entity the user owns,
    acquired, disposed of, or paid for (e.g. "guitar", "coffee maker", "Yamaha piano",
    "charity donation"). **Default false.** Reject if:
       * the phrase is a pronoun, preposition, or sentence fragment ("back", "home",
         "around", "to", "on", "them", "it", "this")
       * the phrase is a generic quantifier ("a lot", "more", "enough")
       * the phrase is abstract ("confidence", "idea", "problem", "time", "knowing")
       * the phrase is a sentence with a relative clause ("rewards to cover the cost of")
       * any phrase shorter than 3 characters
       * verb form or adjective with no head noun ("new", "great", "recently")
  - entity_class: a stable lowercase bucket name (plural form, underscores). Use an
    existing canonical bucket when one fits:
       musical_instruments / kitchen_items / pets / vehicles / books_read /
       hikes / trips / classes_taken / charity_donations / income_events /
       savings_events / spending_events
    Introduce a new bucket only when none fits and the entity class is clearly useful
    across many events. Use "" when valid=false.
  - canonical_member: deduplicated member name for list-mode classes (e.g.
    "Yamaha FG800", "Kitchen Faucet"). "" for amount polarity or when no
    specific member is named.

Candidates:
{candidates}

Output STRICT JSON — a list of records in the same order, no prose, no fence:
{{
  "results": [
    {{"valid": true, "entity_class": "musical_instruments", "canonical_member": "Yamaha FG800"}},
    {{"valid": false, "entity_class": "", "canonical_member": ""}}
  ]
}}"""


@dataclass
class CardinalEntry:
    """Per-(user, domain, entity_class) cardinal aggregate with evidence trail."""
    user_id: str
    domain: str
    entity_class: str
    count: int = 0
    total_amount: float | None = None
    currency: str | None = None
    evidence: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


class NumericAggregator:
    """Bottom-up numeric cardinal accumulator. Single-writer SQLite."""

    def __init__(self, db_path: Path, llm: Any | None = None):
        self._db_path = db_path
        self._llm = llm
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(NUMERIC_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("NumericAggregator not opened")
        return self._conn

    def is_available(self) -> bool:
        return self._conn is not None

    # ---------- Detection ----------

    def process_turns(
        self,
        turns: list[tuple[int, str, str, dict]],
        user_id: str = "",
        domain: str = "",
        session_date: str | None = None,
    ) -> dict[str, CardinalEntry]:
        """Scan user turns for cardinal signals; update the cache.

        LLM batch-extract when available; regex fast-path otherwise.
        Returns dict of affected entity_class -> CardinalEntry (post-update).
        """
        if not self._conn:
            return {}

        # Build the user-turn list with stable turn numbers for LLM refs
        user_turns: list[tuple[int, str, dict]] = []
        for mid, content, role, meta in turns:
            if role != "user" or not content:
                continue
            user_turns.append((mid, content, meta))

        if not user_turns:
            return {}

        llm_available = False
        if self._llm is not None:
            try:
                llm_available = (
                    self._llm.is_available()
                    if hasattr(self._llm, "is_available") else True
                )
            except Exception:
                llm_available = False

        candidates: list[dict[str, Any]] = []
        if llm_available:
            # Batch extraction: LLM reads raw user turns → event list
            try:
                candidates = self._batch_extract_llm(user_turns, session_date)
            except Exception:
                candidates = []

        if not candidates:
            # LLM batch returned no candidates (LLM unavailable, per-batch
            # failures, or genuine "no events in haystack"). Fall back to
            # regex so users without an LLM still get *something*; a strict
            # quality filter downstream drops the obviously noise members
            # ("Those", "In The Fridge", single pronouns).
            for mid, content, meta in user_turns:
                turn_id = self._turn_id(mid, meta)
                ts = self._turn_ts(meta, session_date)
                candidates.extend(self._regex_extract(content, turn_id, ts))

        if not candidates:
            return {}

        # Classify / normalize each candidate's entity_class (covers
        # regex-only candidates; LLM-extracted candidates already carry
        # class from the batch extractor).
        enriched = self._classify_batch(candidates)

        # Phase 3: apply deltas to cache.
        # touched acts as the primary source-of-truth during this call —
        # DB is only read on FIRST encounter of each class. Without this
        # caching, multiple events targeting the same class within one
        # process_turns call each re-read stale state from disk and only
        # the last event's mutation survives the final persist.
        #
        # Rollup: when an event targets a specific class (e.g. "guitars"),
        # also mirror it to any parent classes in the ontology (e.g.
        # "musical_instruments"). This powers aggregation queries at the
        # broader level without hierarchical schema changes.
        touched: dict[str, CardinalEntry] = {}
        for c in enriched:
            if not c.get("valid", True):
                continue
            cls = (c.get("entity_class") or "").strip().lower()
            if not cls:
                continue
            # Expand to ontology parents, always including the direct class
            for target_cls in self._expand_rollup(cls):
                if target_cls in touched:
                    entry = touched[target_cls]
                else:
                    entry = self._get_or_new(user_id, domain, target_cls)
                    touched[target_cls] = entry
                self._apply_delta(entry, c)

        # Build turn_id → content lookup for Guardian evidence examination.
        turn_text_by_id = {self._turn_id(mid, meta): content
                           for mid, content, meta in user_turns}

        # Trinity refinement over amount events: fires on classes with
        # a strict rubric (charity_donations / savings_events / ...) and
        # ≥3 events — triangulates precision-vs-recall-vs-skepticism via
        # trinity.debate() to revoke misclassified amounts.
        if self._llm and touched:
            for cls, entry in list(touched.items()):
                if cls in CLASS_DEFINITIONS and entry.count >= 3 and entry.total_amount:
                    try:
                        self._refine_amount_events(entry, turn_text_by_id)
                    except Exception:
                        pass

        # Trinity refinement over members: dedup aliases, drop misclassified,
        # strict-subset guardrail. Triggers when ≥3 members accumulated.
        if self._llm and touched:
            for cls, entry in list(touched.items()):
                if len(entry.members) >= 3:
                    try:
                        self._refine_members(entry)
                    except Exception:
                        pass

        for entry in touched.values():
            self._persist(entry)
        return touched

    def _refine_amount_events(
        self, entry: CardinalEntry, turn_text_by_id: dict[str, str],
    ) -> None:
        """Trinity over amount events: revoke those not matching the class rubric."""
        if not self._llm or not entry.total_amount:
            return
        class_def = CLASS_DEFINITIONS.get(entry.entity_class)
        if not class_def:
            return

        amount_events: list[dict[str, Any]] = []
        for i, h in enumerate(entry.history):
            if h.get("reason") != "amount":
                continue
            m = re.match(r"\+\$([\d.]+)", h.get("delta", ""))
            if not m:
                continue
            try:
                amt = float(m.group(1))
            except ValueError:
                continue
            tid = h.get("turn_id") or ""
            ev = (turn_text_by_id.get(tid) or h.get("phrase") or "")[:500].replace("\n", " ")
            if not ev:
                continue
            amount_events.append({
                "history_idx": i, "event_id": len(amount_events),
                "turn_id": tid, "amount": amt, "evidence": ev,
            })
        if len(amount_events) < 3:
            return

        evidence_block = "\n\n".join(
            f"event_id={e['event_id']} | amount=${e['amount']} | {e['evidence']}"
            for e in amount_events
        )
        from radiomind.refinement.trinity import debate
        result = debate(
            task=(
                f"Decide which extracted {entry.entity_class} events match "
                f"the class rubric and which to revoke.\n"
                f"Class rubric: {class_def}\n"
                f"KEEP an event when the evidence clearly shows the user "
                f"performing the class action (e.g. for charity_donations, "
                f"the evidence names a charity/fundraiser/nonprofit or cause).\n"
                f"REVOKE only when the evidence's target is explicitly NOT "
                f"what the class describes (e.g. a gift to a cousin, a "
                f"personal purchase, a rent payment — when classified as "
                f"charity_donations)."
            ),
            evidence=evidence_block,
            llm=self._llm,
            extra_schema='  "revoke_ids": [int, ...]',
        )
        if not result:
            return
        revoke_ids = set()
        for r in result.get("revoke_ids") or []:
            try:
                revoke_ids.add(int(r))
            except (ValueError, TypeError):
                continue
        if not revoke_ids:
            return

        revoked_idx: set[int] = set()
        revoked_amount = 0.0
        revoked_turns: set[str] = set()
        for e in amount_events:
            if e["event_id"] in revoke_ids:
                revoked_idx.add(e["history_idx"])
                revoked_amount += e["amount"]
                revoked_turns.add(e["turn_id"])
        if not revoked_idx:
            return

        entry.count = max(0, entry.count - len(revoked_idx))
        entry.total_amount = (entry.total_amount or 0) - revoked_amount
        entry.history = [h for i, h in enumerate(entry.history) if i not in revoked_idx]
        entry.history.append({
            "ts": time.time(), "turn_id": "", "delta": "trinity_revoke",
            "reason": "trinity_amount_refine",
            "phrase": f"-{len(revoked_idx)} events (-${revoked_amount:.2f})",
        })
        entry.evidence = [t for t in entry.evidence if t not in revoked_turns]
        entry.updated_at = time.time()

    def _refine_members(self, entry: CardinalEntry) -> None:
        """Trinity over the member list: dedup aliases, drop misclassified."""
        if not self._llm or not entry.members:
            return
        from radiomind.refinement.trinity import debate
        result = debate(
            task=(
                f"From this candidate member list for class "
                f"{entry.entity_class!r}, produce a deduplicated final list.\n"
                f"MERGE aliases aggressively — entries that refer to the "
                f"same physical entity collapse into one. Keep the most "
                f"specific name:\n"
                f"  'guitar' + 'Fender Stratocaster electric guitar' → "
                f"'Fender Stratocaster electric guitar'\n"
                f"  'piano' + 'Korg B1' + 'Korg B1 piano' → 'Korg B1 piano'\n"
                f"  'drum set' + 'Pearl Export drum set' → 'Pearl Export drum set'\n"
                f"DROP members that don't belong to the class.\n"
                f"DO NOT invent members not in the input."
            ),
            evidence="\n".join(f"- {m}" for m in entry.members),
            llm=self._llm,
            extra_schema='  "final_members": [str, ...]',
        )
        if not result:
            return
        final = result.get("final_members") or []
        if not isinstance(final, list):
            return
        originals = [m for m in entry.members]
        originals_low = {m.lower() for m in originals}
        kept: list[str] = []
        for m in final:
            ms = str(m).strip()
            if not ms:
                continue
            if ms.lower() in originals_low:
                kept.append(ms)
                continue
            # Allow rename when the new name is a substring of an original
            for orig in originals:
                if ms.lower() in orig.lower() or orig.lower() in ms.lower():
                    kept.append(ms)
                    break
        if not kept:
            return
        entry.members = kept
        entry.count = len(kept)
        entry.history.append({
            "ts": time.time(), "turn_id": "", "delta": "dedup",
            "reason": "trinity_member_refine",
            "phrase": f"{len(originals)}→{len(kept)}",
        })

    @staticmethod
    def _expand_rollup(cls: str) -> list[str]:
        """Given a direct class, return [direct, parent_1, parent_2, ...].

        Looks up both the direct class AND its singular form in the rollup
        table so "guitars" and "guitar" both yield musical_instruments.
        """
        direct = cls.strip().lower()
        out = [direct]
        seen = {direct}
        for key in (direct, _singularize(direct)):
            for parent in ROLLUP.get(key, ()):
                if parent not in seen:
                    out.append(parent)
                    seen.add(parent)
        return out

    @staticmethod
    def _apply_delta(entry: CardinalEntry, c: dict[str, Any]) -> None:
        """Mutate entry in place to reflect one extracted event."""
        polarity = c["polarity"]
        delta_amount = float(c.get("amount") or 0.0)
        member = (c.get("canonical_member") or "").strip()
        turn_id = c["turn_id"]
        ts = c["ts"] or time.time()

        if polarity == "explicit":
            target = int(c["count"])
            entry.count = target
            if member and member not in entry.members:
                entry.members.append(member)
            if turn_id and turn_id not in entry.evidence:
                entry.evidence.append(turn_id)
            entry.history.append({
                "ts": ts, "turn_id": turn_id,
                "delta": "=%d" % target, "reason": "explicit_count",
                "phrase": c.get("phrase", "")[:260],
            })
        elif polarity == "own":
            if member:
                if member in entry.members:
                    return
                entry.members.append(member)
                entry.count += 1
            else:
                if turn_id in entry.evidence:
                    return
                entry.count += 1
            if turn_id and turn_id not in entry.evidence:
                entry.evidence.append(turn_id)
            entry.history.append({
                "ts": ts, "turn_id": turn_id, "delta": "+1",
                "reason": "own", "phrase": c.get("phrase", "")[:260],
            })
        elif polarity == "dispose":
            if member and member in entry.members:
                entry.members.remove(member)
                entry.count = max(0, entry.count - 1)
            elif entry.count > 0:
                entry.count -= 1
            entry.history.append({
                "ts": ts, "turn_id": turn_id, "delta": "-1",
                "reason": "dispose", "phrase": c.get("phrase", "")[:260],
            })
        elif polarity == "amount":
            entry.total_amount = (entry.total_amount or 0.0) + delta_amount
            entry.count += 1
            if turn_id and turn_id not in entry.evidence:
                entry.evidence.append(turn_id)
            entry.history.append({
                "ts": ts, "turn_id": turn_id,
                "delta": "+$%.2f" % delta_amount, "reason": "amount",
                "phrase": c.get("phrase", "")[:260],
            })
        entry.updated_at = time.time()

    # ---------- Query ----------

    def get_cardinal(
        self, user_id: str, domain: str, entity_class: str
    ) -> CardinalEntry | None:
        if not self._conn:
            return None
        row = self._conn.execute(
            "SELECT * FROM cardinal_entries WHERE user_id = ? AND domain = ? AND entity_class = ?",
            (user_id, domain, entity_class),
        ).fetchone()
        return self._row_to_entry(row) if row else None

    def query_by_focus(
        self, user_id: str, domain: str, focus: str, max_results: int = 5
    ) -> list[CardinalEntry]:
        """Fuzzy lookup by query focus: alias-resolve then stem-match."""
        if not self._conn or not focus:
            return []
        focus_norm = _normalize_focus(focus)

        # Alias resolution → target class (may be direct or alias)
        target_cls = ALIASES.get(focus_norm, focus_norm)

        rows = self._conn.execute(
            "SELECT * FROM cardinal_entries WHERE user_id = ? AND domain = ? ORDER BY updated_at DESC",
            (user_id, domain),
        ).fetchall()
        hits: list[tuple[float, CardinalEntry]] = []
        for row in rows:
            cls = row["entity_class"]
            # Direct or alias-mapped equality gets max score
            if cls == target_cls:
                hits.append((1.0, self._row_to_entry(row)))
                continue
            score = _fuzzy_class_match(focus_norm, cls)
            if score > 0:
                hits.append((score, self._row_to_entry(row)))
        hits.sort(key=lambda x: -x[0])
        return [e for _, e in hits[:max_results]]

    def list_all(self, user_id: str, domain: str) -> list[CardinalEntry]:
        if not self._conn:
            return []
        rows = self._conn.execute(
            "SELECT * FROM cardinal_entries WHERE user_id = ? AND domain = ?",
            (user_id, domain),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def clear(self, user_id: str = "", domain: str = "") -> int:
        if not self._conn:
            return 0
        cur = self._conn.execute(
            "DELETE FROM cardinal_entries WHERE user_id = ? AND domain = ?",
            (user_id, domain),
        )
        self._conn.commit()
        return cur.rowcount

    # ---------- Internals ----------

    @staticmethod
    def _turn_id(mid: int, meta: dict) -> str:
        return str(meta.get("turn_id") or meta.get("evidence_id") or f"mem{mid}")

    @staticmethod
    def _turn_ts(meta: dict, session_date: str | None) -> float:
        sd = meta.get("session_date") or session_date
        if sd:
            try:
                # Accept "YYYY-MM-DD" or numeric epoch
                if isinstance(sd, (int, float)):
                    return float(sd)
                if isinstance(sd, str) and "-" in sd:
                    import datetime
                    dt = datetime.datetime.strptime(sd[:10], "%Y-%m-%d")
                    return dt.timestamp()
            except Exception:
                pass
        try:
            return float(meta.get("created_at") or 0.0) or time.time()
        except Exception:
            return time.time()

    @staticmethod
    def _regex_extract(
        content: str, turn_id: str, ts: float
    ) -> list[dict[str, Any]]:
        """Pull (polarity, phrase) tuples from a turn. Low precision OK."""
        out: list[dict[str, Any]] = []

        for pat in EXPLICIT_COUNT_PATTERNS:
            for m in pat.finditer(content):
                try:
                    count = int(m.group(1))
                    phrase = m.group(2).strip()
                except Exception:
                    continue
                if count < 0 or count > 100:
                    continue
                out.append({
                    "polarity": "explicit",
                    "count": count,
                    "phrase": phrase,
                    "turn_id": turn_id,
                    "ts": ts,
                })

        for pat in OWN_PATTERNS:
            for m in pat.finditer(content):
                phrase = m.group(1).strip()
                if _is_bad_phrase(phrase):
                    continue
                out.append({
                    "polarity": "own",
                    "phrase": phrase,
                    "turn_id": turn_id,
                    "ts": ts,
                })

        for pat in DISPOSE_PATTERNS:
            for m in pat.finditer(content):
                phrase = m.group(1).strip()
                if _is_bad_phrase(phrase):
                    continue
                out.append({
                    "polarity": "dispose",
                    "phrase": phrase,
                    "turn_id": turn_id,
                    "ts": ts,
                })

        for pat in AMOUNT_PATTERNS:
            for m in pat.finditer(content):
                amount_str = m.group(1).replace(",", "")
                try:
                    amount = float(amount_str)
                except ValueError:
                    continue
                verb = (m.group(0) or "").lower()
                # Infer class from verb
                cls_hint = _amount_verb_to_class(verb)
                phrase = (m.group(2) or "").strip() if m.lastindex and m.lastindex >= 2 else ""
                out.append({
                    "polarity": "amount",
                    "amount": amount,
                    "phrase": phrase or verb,
                    "cls_hint": cls_hint,
                    "turn_id": turn_id,
                    "ts": ts,
                })
        return out

    def _classify_batch(
        self, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Enrich each candidate with entity_class + canonical_member.

        Amount events take class from verb hint; own/dispose prefer LLM
        classification, with heuristic (head-noun singularized) as fallback.
        """
        # Amount candidates: class from verb hint (regex path) or from
        # LLM batch extraction. Don't overwrite if an entity_class is
        # already set (LLM-extracted amounts carry e.g. charity_donations).
        for c in candidates:
            if c["polarity"] == "amount":
                if not c.get("entity_class"):
                    c["entity_class"] = c.get("cls_hint") or "amount_events"
                if "canonical_member" not in c:
                    c["canonical_member"] = ""
                if "valid" not in c:
                    c["valid"] = True

        # Only secondary-classify candidates that came from the regex
        # fast-path and still lack a class. Candidates already marked
        # `_llm_classified=True` by _batch_extract_llm arrive with a
        # canonical class from the batch prompt — running them through
        # the secondary CLASSIFY_PROMPT would destroy that context
        # (it expects `phrase` input which batch-extracted candidates
        # don't carry).
        needs_classify = [
            c for c in candidates
            if c["polarity"] != "amount"
            and not c.get("_llm_classified")
            and not c.get("entity_class")
        ]

        llm_available = False
        if self._llm is not None and needs_classify:
            try:
                llm_available = (
                    self._llm.is_available()
                    if hasattr(self._llm, "is_available") else True
                )
            except Exception:
                llm_available = False

        if llm_available and needs_classify:
            try:
                self._llm_classify(needs_classify)
            except Exception:
                # LLM failure → fall through to heuristic
                pass

        non_amount = [c for c in candidates if c["polarity"] != "amount"]

        # Heuristic backfill ONLY for candidates the LLM did not see
        # (LLM off / partial output). An LLM-judged `valid=False` must
        # survive. Heuristic candidates are STRICTLY filtered — only
        # accepted when the head noun maps to a known ontology bucket
        # (musical_instruments / kitchen_items / ...). This prevents
        # noise like "Back", "Home", "Those Kitchen Shelves" from
        # leaking through when LLM is silently unavailable.
        for c in non_amount:
            if c.get("_llm_classified"):
                continue
            if c.get("entity_class"):
                continue
            phrase = c.get("phrase", "")
            cls, member = _heuristic_class(phrase)
            if not _heuristic_class_is_recognized(cls, member):
                c["valid"] = False
                c["entity_class"] = ""
                c["canonical_member"] = ""
                continue
            c["entity_class"] = cls
            if not c.get("canonical_member"):
                c["canonical_member"] = member
            if "valid" not in c:
                c["valid"] = bool(cls)

        return candidates

    @staticmethod
    def _turn_has_cardinal_signal(content: str) -> bool:
        """Loose gate: drop turns with no ownership/money/acquisition signal.

        Precision-unimportant (LLM downstream will re-filter); recall must
        be high — any missing keyword silently drops that turn from the
        cardinal pipeline.
        """
        if not content:
            return False
        low = content.lower()
        # Ownership / acquisition / disposal / money signals. Broad list;
        # missing a keyword means the turn is silently dropped from the
        # cardinal pipeline, so the cost of adding extras is ~zero while
        # the cost of missing one is fatal.
        return any(
            kw in low for kw in (
                # Explicit possession
                " my ", "my ", "i've ", "i have ", "i own", "i possess",
                # Acquisition / purchase
                " bought", "purchas", "picked up", "brought home", "acquired",
                " got ", "getting", "received", "received a", "picked a",
                "ordered", "installed", "assembl",
                # Disposal
                "sold ", "gave away", "got rid", "threw out", "threw away",
                "returned ", "donated my", "lost my", "broke my",
                # Repair / replace
                "replaced", "fixed", "repaired", "upgraded", "set up",
                # Money
                " raised ", "raise $", "donated $", "donated to", "donation",
                "earned ", " earn ", "saved $", " save $", "spent $",
                "paid $", " pay $", "bought for", " for $",
                # Event count signals
                " hike", "went hiking", "my trip", "my trips", "i visited",
                "i went", "my class", "my course", "my lesson", "enrolled",
                # Chinese
                "我买", "我有", "我拥有", "我卖", "我送", "我捐", "我筹",
            )
        )

    def _batch_extract_llm(
        self,
        user_turns: list[tuple[int, str, dict]],
        session_date: str | None,
        batch_size: int = 12,
        max_chars_per_turn: int = 600,
    ) -> list[dict[str, Any]]:
        """One LLM call per batch of user turns; output cardinal candidates."""
        if not self._llm:
            return []
        # Pre-filter turns via cheap keyword gate so ~80% of haystack
        # (greetings, assistant-style phrasings, Q/A about hypotheticals)
        # never pays LLM cost.
        filtered = [
            (mid, content, meta)
            for (mid, content, meta) in user_turns
            if self._turn_has_cardinal_signal(content)
        ]
        if not filtered:
            return []
        out: list[dict[str, Any]] = []

        for start in range(0, len(filtered), batch_size):
            chunk = filtered[start : start + batch_size]
            lines = []
            chunk_turn_info = {}  # batch_idx -> (turn_id, ts)
            for batch_idx, (mid, content, meta) in enumerate(chunk):
                snippet = content[:max_chars_per_turn].replace("\n", " ")
                # Strip the "[role] " prefix the harness prepends for
                # readability — the LLM already knows these are user turns
                if snippet.startswith("[user] ") or snippet.startswith("[USER] "):
                    snippet = snippet[7:]
                lines.append(f"{batch_idx}. {snippet}")
                chunk_turn_info[batch_idx] = (
                    self._turn_id(mid, meta), self._turn_ts(meta, session_date),
                )
            prompt = BATCH_EXTRACT_PROMPT.format(turns="\n".join(lines))
            raw = ""
            try:
                if hasattr(self._llm, "generate"):
                    resp = self._llm.generate(
                        prompt, system="Output only strict JSON.",
                    )
                    raw = getattr(resp, "text", "") or ""
                else:
                    raw = self._llm(prompt, "Output only strict JSON.")
            except Exception:
                continue
            cleaned = re.sub(r"^```(?:json|JSON)?\s*\n?", "", raw.strip())
            cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
            try:
                obj = json.loads(cleaned)
                events = obj.get("events", []) if isinstance(obj, dict) else []
            except Exception:
                continue
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                try:
                    batch_idx = int(ev.get("turn", -1))
                except Exception:
                    continue
                if batch_idx not in chunk_turn_info:
                    continue
                polarity = str(ev.get("polarity") or "").lower()
                if polarity not in ("own", "dispose", "amount"):
                    continue
                ec = str(ev.get("entity_class") or "").strip().lower()
                if not ec:
                    continue
                turn_id, ts = chunk_turn_info[batch_idx]
                # Keep a snippet of the source turn text so query-time
                # scope filtering (get_numeric_cardinal) can re-verify
                # whether the event actually mentions the query's
                # scope word (e.g. "charity"). Without this, LLM-
                # extracted events had empty phrases and were invisible
                # to the scope filter.
                _source_snippet = chunk[batch_idx][1][:240].replace("\n", " ").strip()
                candidate: dict[str, Any] = {
                    "polarity": polarity,
                    "entity_class": ec,
                    "canonical_member": str(ev.get("canonical_member") or "").strip(),
                    "turn_id": turn_id,
                    "ts": ts,
                    "valid": True,
                    "_llm_classified": True,  # skip heuristic backfill
                    "phrase": _source_snippet,
                }
                if polarity == "amount":
                    try:
                        amt = float(ev.get("amount") or 0.0)
                    except Exception:
                        amt = 0.0
                    candidate["amount"] = amt
                    candidate["currency"] = str(ev.get("currency") or "USD")
                out.append(candidate)
        return out

    def _llm_classify(self, candidates: list[dict[str, Any]]) -> None:
        """Call the LLM once for a batch; mutate candidates in place."""
        if not candidates or self._llm is None:
            return
        prompt_items = []
        for i, c in enumerate(candidates):
            prompt_items.append(
                f"{i}. turn={c['turn_id']} polarity={c['polarity']} phrase=\"{c['phrase']}\""
            )
        prompt = CLASSIFY_PROMPT.format(candidates="\n".join(prompt_items))

        raw = ""
        if hasattr(self._llm, "generate"):
            resp = self._llm.generate(prompt, system="Output only strict JSON.")
            raw = getattr(resp, "text", "") or ""
        else:
            raw = self._llm(prompt, "Output only strict JSON.")
        cleaned = re.sub(r"^```(?:json|JSON)?\s*\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
        obj = json.loads(cleaned)
        results = obj.get("results", []) if isinstance(obj, dict) else []
        for i, c in enumerate(candidates):
            if i >= len(results):
                break
            r = results[i] or {}
            # Mark LLM-classified so heuristic backfill skips it.
            c["_llm_classified"] = True
            # LLM's valid verdict is authoritative.
            c["valid"] = bool(r.get("valid", False))
            if not c["valid"]:
                c["entity_class"] = ""
                c["canonical_member"] = ""
                continue
            ec = str(r.get("entity_class") or "").strip().lower()
            if ec:
                c["entity_class"] = ec
            if r.get("canonical_member"):
                c["canonical_member"] = str(r["canonical_member"]).strip()

    def _get_or_new(
        self, user_id: str, domain: str, entity_class: str
    ) -> CardinalEntry:
        cached = self.get_cardinal(user_id, domain, entity_class)
        if cached:
            return cached
        return CardinalEntry(
            user_id=user_id, domain=domain, entity_class=entity_class,
        )

    def _persist(self, entry: CardinalEntry) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO cardinal_entries
                (user_id, domain, entity_class, count, total_amount, currency,
                 evidence_json, history_json, members_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.user_id, entry.domain, entity_class := entry.entity_class,
                entry.count, entry.total_amount, entry.currency,
                json.dumps(entry.evidence[-50:], ensure_ascii=False),
                json.dumps(entry.history[-200:], ensure_ascii=False),
                json.dumps(entry.members[-100:], ensure_ascii=False),
                entry.updated_at,
            ),
        )
        self.conn.commit()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> CardinalEntry:
        try:
            evidence = json.loads(row["evidence_json"]) if row["evidence_json"] else []
            history = json.loads(row["history_json"]) if row["history_json"] else []
            members = json.loads(row["members_json"]) if row["members_json"] else []
        except Exception:
            evidence, history, members = [], [], []
        return CardinalEntry(
            user_id=row["user_id"],
            domain=row["domain"],
            entity_class=row["entity_class"],
            count=int(row["count"] or 0),
            total_amount=(float(row["total_amount"]) if row["total_amount"] is not None else None),
            currency=row["currency"],
            evidence=evidence,
            members=members,
            history=history,
            updated_at=float(row["updated_at"] or 0.0),
        )


# ---------- helpers ----------



_AMOUNT_VERB_CLASS = {
    "raised": "charity_donations",
    "donated": "charity_donations",
    "contributed": "charity_donations",
    "gave": "charity_donations",
    "earned": "income_events",
    "made": "income_events",
    "received": "income_events",
    "saved": "savings_events",
    "spent": "spending_events",
    "paid": "spending_events",
}


def _amount_verb_to_class(verb_context: str) -> str:
    for k, v in _AMOUNT_VERB_CLASS.items():
        if k in verb_context:
            return v
    return "amount_events"


_BAD_PHRASES = {
    "a", "an", "the", "some", "any", "it", "them", "one",
    "idea", "thought", "moment", "time", "chance", "feeling",
    "problem", "issue", "question",  # abstract
    "a lot", "much", "more",
    # Bare adjectives that sometimes slip past the determiner-strip
    "new", "old", "nice", "cheap", "fancy", "simple", "great", "good", "bad",
    # Pronouns / auxiliaries leaking into the capture tail
    "me", "you", "him", "her", "us", "them", "myself", "yourself",
    "this", "that", "these", "those",
}


def _is_bad_phrase(phrase: str) -> bool:
    p = phrase.strip().lower()
    if not p or len(p) < 2:
        return True
    if p in _BAD_PHRASES:
        return True
    # Bail on pure pronoun / generic quantifier phrases
    if p.startswith("it ") or p.startswith("them "):
        return True
    return False


# Very light lemmatizer for phrase → class heuristic. Full NLP overkill
# for S1; we want a sane default class when LLM is skipped.
_SINGULAR_RULES = [
    (re.compile(r"(ches|shes)$", re.I), lambda m: m.group(0)[:-2]),  # "watches" → "watch"
    (re.compile(r"ves$", re.I), "f"),  # "shelves" → "shelf", "knives" → "knife"
    (re.compile(r"ies$", re.I), "y"),
    (re.compile(r"ses$", re.I), "s"),
    (re.compile(r"s$", re.I), ""),
]

# Irregular plural → singular overrides. Extendable via config later.
_IRREGULAR_PLURALS = {
    "shelves": "shelf",
    "knives": "knife",
    "wolves": "wolf",
    "children": "child",
    "people": "person",
    "men": "man",
    "women": "woman",
    "mice": "mouse",
    "teeth": "tooth",
    "feet": "foot",
}


def _singularize(word: str) -> str:
    w = word.lower()
    if w in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[w]
    for pat, repl in _SINGULAR_RULES:
        if callable(repl):
            m = pat.search(word)
            if m:
                return pat.sub(repl(m), word)
        else:
            if pat.search(word):
                return pat.sub(repl, word)
    return word


def _pluralize(word: str) -> str:
    """Rough reverse of singularize for class-bucket naming."""
    w = word.lower()
    # Already plural
    if w.endswith("s") and not w.endswith("ss"):
        return w
    if w.endswith("f"):
        return w[:-1] + "ves"
    if w.endswith("sh") or w.endswith("ch") or w.endswith("x"):
        return w + "es"
    if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
        return w[:-1] + "ies"
    return w + "s"


# Location / context phrases that should be stripped from the tail of a
# noun phrase so "Roland digital piano at home" → "Roland digital piano".
# Conservative list — only trailing prepositional phrases with common
# generic objects.
_PHRASE_TAIL_CLEANUP = re.compile(
    r"\s+(?:at|in|on|from|for)\s+"
    r"(?:home|work|the\s+(?:office|house|store|shop|gym|park|thrift\s+store)"
    r"|my\s+(?:home|house|place|office|apartment))\b.*$",
    re.IGNORECASE,
)


def _heuristic_class_is_recognized(cls: str, member: str) -> bool:
    """Keep only heuristic outputs whose class is in the ontology.

    Rejects noise like "backs"/"thes"/"news" and stray determiners.
    """
    if not cls or not member:
        return False
    cls_low = cls.lower()
    # Known ontology keys / parents
    parent_classes = {v for vs in ROLLUP.values() for v in vs}
    if cls_low in ROLLUP:
        return True
    if cls_low in parent_classes:
        return True
    # Accept singular-form lookup as well
    if _singularize(cls_low) in ROLLUP:
        return True
    # Reject when member is a single non-capitalized common word
    mtokens = member.split()
    if len(mtokens) == 1 and mtokens[0][0].islower():
        return False
    # Reject when member starts with a determiner / adjective that
    # leaked through ("Those ...", "This ...", "New ...")
    if mtokens and mtokens[0].lower() in {"those", "these", "this", "that", "a", "an", "the", "my", "your", "our", "their", "new", "old", "great", "nice"}:
        return False
    return False


def _heuristic_class(phrase: str) -> tuple[str, str]:
    """Best-effort class bucket + canonical member from a phrase.

    Prefers a bigram class when the last two tokens match the ontology
    (e.g. "coffee maker" → coffee_makers) so compound-noun items don't
    collapse to the head-noun bucket ("makers"/"chargers").
    """
    p = phrase.strip().lower()
    if not p:
        return "", ""
    # Drop leading determiners + size/color adjectives that don't classify
    p = re.sub(
        r"^(?:a\s+|an\s+|the\s+|some\s+|my\s+|another\s+|brand[\- ]new\s+|"
        r"new\s+|old\s+|cheap\s+|fancy\s+|simple\s+)+",
        "", p,
    )
    # Kill trailing clauses after "that"/"which"/"my grandmother gave..."
    p = re.split(
        r"\s+(?:that|which|who|but|and|or|my|your|his|her|their|he|she|they|it)\b",
        p, maxsplit=1,
    )[0].strip()
    # Kill trailing location phrases ("at home", "at the thrift store")
    p = _PHRASE_TAIL_CLEANUP.sub("", p).strip()
    p = p.rstrip(".,!?:;'\"")
    if not p:
        return "", ""

    tokens = p.split()
    if not tokens:
        return "", ""

    # Bigram check: "coffee maker" / "kitchen mat" / "phone charger"
    if len(tokens) >= 2:
        head_singular = _singularize(tokens[-1])
        bigram = f"{tokens[-2]}_{head_singular}"
        bigram_plural = f"{tokens[-2]}_{tokens[-1]}"
        if bigram in ROLLUP or bigram_plural in ROLLUP:
            cls = f"{tokens[-2]}_{_pluralize(head_singular)}"
            member = " ".join(
                t.capitalize() if t.isalpha() and len(t) > 1 else t for t in tokens
            )
            return cls, member

    head = tokens[-1]
    cls = _pluralize(_singularize(head))
    member = " ".join(
        t.capitalize() if t.isalpha() and len(t) > 1 else t for t in tokens
    )
    return cls, member


def _normalize_focus(focus: str) -> str:
    s = focus.strip().lower()
    s = re.sub(r"[^a-z0-9_\s]", "", s)
    s = s.replace(" ", "_")
    return s


def _fuzzy_class_match(focus_norm: str, entity_class: str) -> float:
    """Score 0..1 of how likely the query focus refers to this class."""
    if not focus_norm or not entity_class:
        return 0.0
    cls = entity_class.lower()
    if focus_norm == cls:
        return 1.0
    # Substring match either way
    if focus_norm in cls or cls in focus_norm:
        return 0.85
    # Singular / plural tolerance
    fs = _singularize(focus_norm)
    cs = _singularize(cls)
    if fs and cs and (fs == cs or fs in cs or cs in fs):
        return 0.75
    # Token overlap
    focus_toks = set(focus_norm.split("_"))
    cls_toks = set(cls.split("_"))
    overlap = focus_toks & cls_toks
    if overlap:
        return 0.5 * len(overlap) / max(len(focus_toks), len(cls_toks))
    return 0.0
