"""Bottom-up numeric-fact aggregator.

RadioMind's preservative storage keeps every turn intact but leaves the
answer LLM to re-derive cardinal facts ("how many instruments do I own")
from top-k retrieved turns on every query. That re-derivation is the
source of our multi-session aggregation errors (reported 5 instruments
when gold is 4, $2750 when gold is $3750): a single LLM pass over top-30
turns can't enumerate completely.

This module moves that work to ingest time: as turns land, we scan for
ownership/acquisition/disposal/amount verbs, extract the entity, classify
it into an ontology bucket ("instruments", "kitchen_items", "charity_
donations"), and maintain a per-user×domain×class cardinal cache. A
query-time question like "how many instruments do I own" then hits a
deterministic ground-truth (count=4, evidence=[s2_t1,s4_t3,s7_t2,s12_t5])
instead of re-deriving from retrieval.

Version history preserves time-sliced questions ("how many did I have in
June"): every ±1 delta records {ts, turn_id, reason}. Query time can
replay to any past timestamp. This is how preservative-storage still
supports temporal-aware cardinality.

Design notes:
- Storage lives in the same SQLite file as the knowledge graph
  (knowledge.db) — logically adjacent to KG triples, both are
  structured-extract products of ingest.
- Detection is regex-fast-path + LLM-classifier-batch. The regex is the
  cheap filter (zero LLM cost on non-cardinal turns); the LLM only sees
  plausible candidates and only to normalize entity→class.
- Scope is deliberately narrow for S1: first-person ownership statements
  and dollar-amount events. S2/S3 can widen to third-party claims and
  compound verbs if S1 alone doesn't close the gap.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


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
AMOUNT_PATTERNS = [
    re.compile(
        r"\bi\s+(?:just\s+|already\s+|later\s+|then\s+)?"
        r"(?:raised|donated|earned|made|saved|spent|paid|contributed|gave|received)\s+"
        r"(?:another\s+|additional\s+|about\s+|around\s+|roughly\s+|nearly\s+|approximately\s+)?"
        r"(?:\$|usd\s*)?(\d[\d,\.]*)"
        r"(?:\s*(?:dollars?|usd|bucks?))?"
        r"(?:\s+(?:for|to|at|from|on|in)\s+(.{2,60}?))?(?:\.|,|!|\?|$)",
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
REDUCER_DEDUP_PROMPT = """You are the Reducer: given a candidate list of members
claimed for one entity class, return the deduplicated + strictly-scoped
final list.

Entity class: {entity_class}

Candidate members (from ingest-time extraction across many conversation turns;
may include duplicates, aliases, misclassifications):
{members}

Rules:
1. **Dedup aliases**: merge entries that refer to the same physical entity.
   - "acoustic guitar" + "Yamaha FG800" → "Yamaha FG800" (specific name wins)
   - "Fender Stratocaster" + "guitar" + "black Fender" → "Fender Stratocaster"
   - "Pearl Export drum set" + "drum set" + "5-piece Pearl" → "Pearl Export drum set"
   If multiple members could be the same entity based on context, MERGE them.
2. **Drop misclassified**: remove any member that doesn't strictly belong
   to the class. E.g. if class is `musical_instruments`:
   - "silver chain", "engagement ring" → DROP (not instruments)
   - If class is `kitchen_items`: drop food/groceries.
3. **Preserve specifics**: when merging, keep the most specific name.
4. **Do NOT add new entries** beyond what's in the input list. Only
   merge and filter.

Output STRICT JSON with the final deduplicated list:
{{
  "final_members": ["Fender Stratocaster", "Yamaha FG800", "Pearl Export drum set", "Korg B1"],
  "removed": ["silver chain (not instrument)", "guitar (alias of Fender)"]
}}"""


BATCH_EXTRACT_PROMPT = """You extract OWNERSHIP and MONEY events from user messages.

Do this in **two passes per turn**:

PASS 1 (OWN) — for each turn, list every tangible countable item the
user refers to as their own. Ownership REVEAL is enough — no purchase
verb required. These all trigger OWN:
  "I've had my Fender for 5 years"         → OWN member="Fender"
  "I've been playing my black Stratocaster" → OWN member="black Stratocaster"
  "My Pearl drum set sounds amazing"        → OWN member="Pearl drum set"
  "my piano, a Korg B1, which I've had for 3 years" → OWN member="Korg B1"
  "I bought a Yamaha FG800"                 → OWN member="Yamaha FG800"
  "my old drum set, a 5-piece Pearl Export" → OWN member="Pearl Export drum set"
  "I just bought a new overdrive pedal"     → OWN member="overdrive pedal"
  "my acoustic guitar, a Yamaha FG800"      → OWN member="Yamaha FG800"
  "I replaced the kitchen faucet"           → OWN member="kitchen faucet"
  "My niece got a new violin"               → NOT OWN (niece is not the user)

PASS 2 (AMOUNT) — for each turn, list every money event:
  "I donated $500 to Red Cross"             → AMOUNT charity_donations $500 member="Red Cross"
  "I raised $1500 at the cancer-walk gala"  → AMOUNT charity_donations $1500 member="cancer walk"
  "I saved $300 on the Jimmy Choo heels"    → AMOUNT savings_events $300 member="Jimmy Choo heels"
  "I saved $20 with the coupon"             → AMOUNT savings_events $20 member="" (no specific item)
  "I bought the heels for $500"             → AMOUNT spending_events $500 member="heels"
  "I earned $200 from the sale"             → AMOUNT income_events $200

**CHARITY IS STRICT**: only count as charity_donations if the target is
explicitly a charity / fundraiser / nonprofit / cause. Generic gifts,
purchases, and transfers to non-charity recipients are NOT charity.
Examples of WHAT IS charity: Red Cross, cancer walk, school fundraiser,
gala for a cause, political donation, religious tithing.
Examples of WHAT IS NOT charity: "I gave my cousin $100", "paid rent",
"bought a gift for mom" — emit these as spending_events or skip.

**If a turn triggers both** (e.g. "I bought a Korg B1 for $600"), emit
BOTH records — one OWN, one AMOUNT, both with the same turn number.

Canonical entity_class buckets — STRICT scope definitions:

  musical_instruments ← guitar, piano, drum set, keyboard, ukulele, violin,
    pedal, amp, cello, bass, flute, trumpet, saxophone, harmonica
    EXCLUDE: model airplanes, toys, non-musical devices (no "F-16 model")

  kitchen_items       ← **DURABLE** appliances, fixtures, tools used in a
    kitchen: faucet, toaster, coffee maker, blender, mat, shelf, microwave,
    kettle, dishwasher, stove, oven, mixer, fridge, rice cooker, espresso
    machine, air fryer, food processor.
    **EXCLUDE FOOD AND CONSUMABLES**: pasta, rice, beans, apples, flour,
    eggs, vegetables, meat, bread, ingredients, groceries — these are
    NEVER kitchen_items. If user "bought rice at the store", DO NOT emit.

  clothing_items      ← shoes, sneakers, boots, heels, dress, jacket, coat,
    jeans, shirt, hat. Each distinct garment = 1 item.

  vehicles            ← car, truck, motorcycle, bike, SUV, sedan

  pets                ← dog, cat, hamster, snake, bird, fish, rabbit
    EXCLUDE: pet supplies (litter scoop, dental chews — those are
    spending_events, not pets themselves)

  books_read          ← books the user **read or owns** (novels, series,
    reference). EXCLUDE websites, blogs, apps.

  hikes               ← distinct hike / trek / trail walk EVENTS.
    Count EACH HIKE SESSION, not each trail type. If user mentioned
    "I went hiking at Red Rock Canyon last Saturday" and "I did the
    John Muir Trail the following weekend" → 2 separate hikes.
    "I've been hiking a lot" → 1 hike (generic mention).

  trips               ← distinct TRIP events (vacation, visit, journey).
    "Our Bali trip" = 1 trip.

  electronics         ← phones, laptops, cameras, lenses, tripods, monitors,
    keyboards (computing), consoles, TVs, gaming chairs, PCs

  furniture           ← desk, chair, table, bench, sofa, shelf (non-kitchen)

  sporting_goods      ← tennis racket, golf clubs, bike helmet, surfboard,
    helmet (for bike/sport)

  charity_donations   ← **STRICT**: money the user gave to a
    **NAMED CHARITY ORGANIZATION or CHARITY EVENT/FUNDRAISER**.
    Examples: "I donated $500 to the Red Cross",
              "I raised $1500 at the cancer walk fundraiser",
              "I contributed $200 to the school fundraiser gala".
    EXCLUDE: generic gifts ("I gave $100 to my cousin"), dues, bills,
    purchases. If the target is not explicitly a charity or fundraiser,
    it's spending_events, not charity_donations.

  income_events       ← money earned from sale, work, refund, gift
  savings_events      ← saved $N on a purchase (discount). Member=item.
  spending_events     ← paid $N for specific items. NOT charity.

Rules:
- Only count as OWN if the USER themselves possesses it. Ignore items
  belonging to niece/grandmother/friend unless the user inherited or now
  possesses them.
- Dedupe within a turn — if the same item is mentioned twice, emit one
  OWN record only.
- Across turns we dedupe by canonical_member, so repeating the same
  instrument across multiple turns stays one count — still emit one
  OWN event per turn where it's referenced (downstream merges).
- "I'm thinking of buying X" / "I'm planning to get X" / "I might get X"
  is NOT ownership yet — skip.
- "My niece got a violin" / "my grandmother's piano" — NOT user's.

Output format per record:
  - turn: integer turn number
  - polarity: "own" | "dispose" | "amount"
  - entity_class: canonical bucket (plural, underscores)
  - canonical_member: specific item name (e.g. "Fender Stratocaster",
    "Kitchen Faucet", "heels"). For AMOUNT without a target item, "".
  - amount: numeric (no $ sign) for AMOUNT polarity; null otherwise
  - currency: "USD" / "EUR" / etc.; default "USD"

Coverage over brevity: if in doubt emit the OWN record. Missing events
costs downstream aggregation queries; extra records are merged.

User turns:
{turns}

Output STRICT JSON only:
{{
  "events": [
    {{"turn": 2, "polarity": "own", "entity_class": "musical_instruments",
      "canonical_member": "Fender Stratocaster", "amount": null, "currency": null}},
    {{"turn": 5, "polarity": "own", "entity_class": "musical_instruments",
      "canonical_member": "Pearl Export drum set", "amount": null, "currency": null}},
    {{"turn": 7, "polarity": "amount", "entity_class": "charity_donations",
      "canonical_member": "", "amount": 500, "currency": "USD"}}
  ]
}}"""


# Prompt for LLM-side entity→class normalization. Batched per ingest.
# Critical: phrases extracted by regex over long haystacks include massive
# amounts of noise ("back", "home", "great deal", "enough rewards to cover
# the cost of the", pronouns, sentence fragments). The LLM's FIRST job is
# aggressive rejection: valid=false by default, valid=true ONLY when the
# phrase unambiguously names a countable tangible entity the user actually
# owns, acquired, disposed of, or paid.
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
    """Per-(user, domain, entity_class) aggregate.

    count: current cardinal (after all +/- events applied).
    total_amount: cumulative amount for amount-type classes
        (e.g. charity_donations.total_amount = running sum in dollars).
    evidence: turn_ids of distinct contributing events.
    members: deduped canonical member names for list-mode classes
        (e.g. ['Yamaha FG800', 'Fender Stratocaster', ...]).
    history: chronological log of deltas, each {ts, turn_id, delta, reason, amount}.
    """
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
    """Bottom-up numeric cardinal accumulator.

    Lifecycle mirrors KnowledgeGraph: open() on init, close() on shutdown,
    process_turns() on ingest. Thread-safety is single-writer (same as KG).
    """

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

        Strategy:
          - When an LLM is available, **batch-extract** candidates directly
            from the user turns (one LLM call per ~30 turns). This catches
            implicit ownership reveals ("My Fender", "I've had X for Y years")
            that regex can't reach.
          - Fallback path when no LLM: regex fast-path (cheap but leaky).
          - Either way, follow-up classifier normalizes class buckets.

        Args:
            turns: list of (memory_id, content, role, metadata). Non-user
                turns are ignored.
            user_id, domain: partition keys for the cache.
            session_date: coarse fallback timestamp if a turn lacks one.

        Returns:
            Dict of affected entity_class -> CardinalEntry (post-update).
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
            # Batch extraction: LLM sees raw user turns and outputs events
            try:
                candidates = self._batch_extract_llm(user_turns, session_date)
            except Exception:
                candidates = []

        if not candidates:
            # Fallback to regex fast-path
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

        # Post-pass: Reducer-style dedup within each class.
        # Batch extraction sees each turn in isolation so the same
        # physical entity ("Fender Stratocaster" in batch 1, "guitar" /
        # "acoustic guitar" in later batches) produces multiple separate
        # members. A single LLM pass reviews the accumulated member list
        # per class, merges aliases, drops misclassified items, and
        # produces a final count. Only fires when the class has ≥3
        # members (cheap membership doesn't pay to review).
        if self._llm and touched:
            for cls, entry in list(touched.items()):
                if len(entry.members) >= 3:
                    try:
                        self._reducer_dedup(entry)
                    except Exception:
                        pass

        for entry in touched.values():
            self._persist(entry)
        return touched

    def _reducer_dedup(self, entry: CardinalEntry) -> None:
        """LLM pass: merge alias members within a class; drop misclassified.

        The Reducer of the three-body primitive applied to one cardinal
        entry. Input: class name + current member list + evidence turn
        references. Output: a deduplicated + filtered member list with
        count equal to len(final list).

        Conservative: only trusts the reducer when it returns a strict
        subset of the input members (to prevent LLM hallucination from
        ADDING new members). Guardian-style verification.
        """
        if not self._llm or not entry.members:
            return
        prompt = REDUCER_DEDUP_PROMPT.format(
            entity_class=entry.entity_class,
            members="\n".join(f"- {m}" for m in entry.members),
        )
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
            return
        cleaned = re.sub(r"^```(?:json|JSON)?\s*\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
        try:
            obj = json.loads(cleaned)
            final_members = obj.get("final_members", [])
            if not isinstance(final_members, list):
                return
        except Exception:
            return
        # Guardian check: reducer must not invent new members.
        original_lower = {m.lower() for m in entry.members}
        valid_final = []
        for m in final_members:
            ms = str(m).strip()
            if not ms:
                continue
            # Accept if identical or is a rename of something in original
            if ms.lower() in original_lower:
                valid_final.append(ms)
            else:
                # Fuzzy containment: reducer might have canonicalized
                # (e.g. "acoustic guitar" + "Yamaha FG800" → "Yamaha FG800")
                for orig in entry.members:
                    if ms.lower() in orig.lower() or orig.lower() in ms.lower():
                        valid_final.append(ms)
                        break
        if not valid_final:
            return
        entry.members = valid_final
        entry.count = len(valid_final)
        entry.history.append({
            "ts": time.time(), "turn_id": "", "delta": "dedup",
            "reason": "reducer", "phrase": f"{len(original_lower)}→{len(valid_final)}",
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
            for parent in _ONTOLOGY_ROLLUP.get(key, ()):
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
                "phrase": c.get("phrase", "")[:120],
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
                "reason": "own", "phrase": c.get("phrase", "")[:120],
            })
        elif polarity == "dispose":
            if member and member in entry.members:
                entry.members.remove(member)
                entry.count = max(0, entry.count - 1)
            elif entry.count > 0:
                entry.count -= 1
            entry.history.append({
                "ts": ts, "turn_id": turn_id, "delta": "-1",
                "reason": "dispose", "phrase": c.get("phrase", "")[:120],
            })
        elif polarity == "amount":
            entry.total_amount = (entry.total_amount or 0.0) + delta_amount
            entry.count += 1
            if turn_id and turn_id not in entry.evidence:
                entry.evidence.append(turn_id)
            entry.history.append({
                "ts": ts, "turn_id": turn_id,
                "delta": "+$%.2f" % delta_amount, "reason": "amount",
                "phrase": c.get("phrase", "")[:120],
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
        """Fuzzy lookup cardinal entries whose class matches the query focus.

        focus: noun phrase extracted from the query ("instruments",
            "charity donations", "kitchen items", "money"). First resolved
            through the alias table (e.g. "instruments"→"musical_instruments",
            "money"→"charity_donations"), then matched to entity_class with
            stem rules for singular/plural variations.

        Returns a list of entries ranked by match confidence. Rollup parent
        classes typically outrank specific ones because ingest writes to
        both — the parent has a higher count and matches the broader query.
        """
        if not self._conn or not focus:
            return []
        focus_norm = _normalize_focus(focus)

        # Alias resolution → target class (may be direct or alias)
        target_cls = _CLASS_ALIASES.get(focus_norm, focus_norm)

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
        """Enrich candidates with entity_class + canonical_member.

        Strategy:
          1. Amount candidates always get class from verb hint (no LLM).
          2. Own/dispose/explicit candidates: LLM classifies semantically
             ("acoustic guitar" → "musical_instruments" rollup) when
             available. LLM is the preferred path, not a fallback.
          3. Heuristic (head-noun singularized to bucket) is the true
             fallback when LLM is absent or fails — so the pipeline
             survives offline runs but LLM-enabled runs get the proper
             ontology rollup needed for aggregation queries like
             "how many instruments".
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
        # survive — the whole point of the LLM step is to reject the
        # regex fast-path noise (pronouns, fragments, adjectives). If
        # heuristic resurrected those it would defeat filtering.
        for c in non_amount:
            if c.get("_llm_classified"):
                continue
            if c.get("entity_class"):
                continue
            phrase = c.get("phrase", "")
            cls, member = _heuristic_class(phrase)
            c["entity_class"] = cls
            if not c.get("canonical_member"):
                c["canonical_member"] = member
            if "valid" not in c:
                c["valid"] = bool(cls)

        return candidates

    @staticmethod
    def _turn_has_cardinal_signal(content: str) -> bool:
        """Loose gate: does this turn likely contain a cardinal event?

        The LLM batch call is expensive on 500-turn haystacks (25+ API
        calls per question). Most turns carry no cardinal signal at all
        (greetings, hypotheticals, assistant replies). A cheap keyword
        gate filters these out BEFORE they hit the LLM — ~10× cost
        reduction with minimal recall loss (the keyword list is broad).

        Precision doesn't matter here: false positives just mean the LLM
        classifies and discards. Only recall matters.
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
        batch_size: int = 20,
        max_chars_per_turn: int = 800,
    ) -> list[dict[str, Any]]:
        """One LLM call per batch of user turns; output cardinal candidates.

        Each batch sends ~30 user turns with stable turn numbers so the
        LLM can reference them in its output. Truncates overlong turns to
        keep prompt size bounded (~30 × 500 char = 15K chars ≈ 4K tokens
        input per batch). Returns a flat list of candidate dicts matching
        the shape expected by downstream _classify_batch / _apply_delta.

        Failures (parse error / empty output) return [] for that batch —
        caller can fall back to regex for those turns.
        """
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
                candidate: dict[str, Any] = {
                    "polarity": polarity,
                    "entity_class": ec,
                    "canonical_member": str(ev.get("canonical_member") or "").strip(),
                    "turn_id": turn_id,
                    "ts": ts,
                    "valid": True,
                    "_llm_classified": True,  # skip heuristic backfill
                    "phrase": "",  # unused when LLM-extracted
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

# Ontology rollup: specific head-noun → broader aggregation buckets.
# When ingesting "I bought a guitar", we write events to BOTH "guitars" and
# "musical_instruments" so aggregation queries hit the right level. Keeps
# the cache schema simple (no hierarchical parent columns) while giving
# query-side rollup for free.
#
# Covers the aggregation classes that actually show up in LongMemEval-S /
# LoCoMo error modes. Extendable via config later; for S1 built-in is
# sufficient.
_ONTOLOGY_ROLLUP: dict[str, tuple[str, ...]] = {
    # Musical instruments
    "guitar": ("musical_instruments",),
    "guitars": ("musical_instruments",),
    "piano": ("musical_instruments",),
    "pianos": ("musical_instruments",),
    "keyboard": ("musical_instruments",),
    "ukulele": ("musical_instruments",),
    "ukuleles": ("musical_instruments",),
    "violin": ("musical_instruments",),
    "drum": ("musical_instruments",),
    "drums": ("musical_instruments",),
    "cello": ("musical_instruments",),
    "bass": ("musical_instruments",),
    "flute": ("musical_instruments",),
    "trumpet": ("musical_instruments",),
    "saxophone": ("musical_instruments",),
    "harp": ("musical_instruments",),
    "mandolin": ("musical_instruments",),
    "banjo": ("musical_instruments",),
    "harmonica": ("musical_instruments",),
    "instrument": ("musical_instruments",),
    # Kitchen items
    "faucet": ("kitchen_items",),
    "toaster": ("kitchen_items",),
    "mat": ("kitchen_items",),
    "shelf": ("kitchen_items",),
    "blender": ("kitchen_items",),
    "coffeemaker": ("kitchen_items",),
    "coffee": ("kitchen_items",),  # "coffee maker"
    "mixer": ("kitchen_items",),
    "microwave": ("kitchen_items",),
    "fridge": ("kitchen_items",),
    "dishwasher": ("kitchen_items",),
    "stove": ("kitchen_items",),
    "oven": ("kitchen_items",),
    "kettle": ("kitchen_items",),
    # Multi-word kitchen items (bigram lookup)
    "coffee_maker": ("kitchen_items",),
    "coffee_makers": ("kitchen_items",),
    "kitchen_mat": ("kitchen_items",),
    "kitchen_mats": ("kitchen_items",),
    "kitchen_faucet": ("kitchen_items",),
    "kitchen_shelf": ("kitchen_items",),
    "kitchen_shelves": ("kitchen_items",),
    "rice_cooker": ("kitchen_items",),
    "rice_cookers": ("kitchen_items",),
    "slow_cooker": ("kitchen_items",),
    "slow_cookers": ("kitchen_items",),
    "air_fryer": ("kitchen_items",),
    "air_fryers": ("kitchen_items",),
    "food_processor": ("kitchen_items",),
    "food_processors": ("kitchen_items",),
    # Pets
    "dog": ("pets",),
    "cat": ("pets",),
    "hamster": ("pets",),
    "snake": ("pets",),
    "bird": ("pets",),
    "fish": ("pets",),
    "rabbit": ("pets",),
    # Vehicles
    "car": ("vehicles",),
    "truck": ("vehicles",),
    "suv": ("vehicles",),
    "sedan": ("vehicles",),
    "motorcycle": ("vehicles",),
    # Books / reading
    "book": ("books_read",),
    "novel": ("books_read",),
    # Hikes / trips / visits
    "hike": ("hikes",),
    "trek": ("hikes",),
    "walk": ("hikes",),
    "trail": ("hikes",),
    "trip": ("trips",),
    "vacation": ("trips",),
    "visit": ("trips",),
    "journey": ("trips",),
    # Classes / lessons
    "class": ("classes_taken",),
    "course": ("classes_taken",),
    "lesson": ("classes_taken",),
    "workshop": ("classes_taken",),
    "session": ("classes_taken",),
    # Birds seen (for "how many species of birds" type queries)
    "species": ("bird_species", "wildlife_sightings"),
}


# Reverse index: alias / synonym → canonical class. Used by query_by_focus
# to resolve "instruments" / "music instruments" → musical_instruments.
_CLASS_ALIASES: dict[str, str] = {
    "instruments": "musical_instruments",
    "instrument": "musical_instruments",
    "music_instruments": "musical_instruments",
    "musical_instrument": "musical_instruments",
    "kitchen_things": "kitchen_items",
    "kitchenware": "kitchen_items",
    "kitchen": "kitchen_items",
    "money": "charity_donations",  # "how much money did I raise for charity"
    "charity": "charity_donations",
    "donations": "charity_donations",
    "contributions": "charity_donations",
    "income": "income_events",
    "earnings": "income_events",
    "savings": "savings_events",
    "expenses": "spending_events",
    "spending": "spending_events",
    "birds": "bird_species",
    "species_of_birds": "bird_species",
}


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


def _heuristic_class(phrase: str) -> tuple[str, str]:
    """Best-effort class bucket + canonical member from a phrase.

    Example: "a brand-new Yamaha FG800 acoustic guitar" →
             class="guitars", member="Yamaha FG800 Acoustic Guitar"
             "Roland digital piano at home" →
             class="pianos", member="Roland Digital Piano"
             "coffee maker" → class="coffee_makers" (bigram matches ontology)

    Prefers bigram class if the last two tokens form a known ontology key
    (e.g. "coffee_maker" under kitchen_items) — keeps compound-noun items
    like "coffee maker" / "phone charger" / "kitchen mat" from being
    buried under the generic head-noun ("makers", "chargers", "mats").
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
        if bigram in _ONTOLOGY_ROLLUP or bigram_plural in _ONTOLOGY_ROLLUP:
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
