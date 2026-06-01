# OrderedEventList-1a — Read-Only Audit

**Date**: 2026-06-01
**Author**: Claude Code
**Status**: Read-only audit + proposal. No code change. **Headline: this is
NOT greenfield** — a `ListOrderingSkill` already exists and is registered but
is *silently dead on the real dataset* because of a date-parser bug (verified).
So the work is fix + harden an existing component, not build a new capability.

---

## 1. The cohort (verified against the dataset)
LongMemEval-S = 500 q. Types: multi-session 133, temporal-reasoning 133,
knowledge-update 78, single-session-user 70, single-session-assistant 56,
single-session-preference 30.

The OrderedEventList cohort is the **"what is the order of X from earliest to
latest" `temporal-reasoning` questions — ~7-8 qids** (≈1.5%). Verified hits:
`gpt4_7f6b06db, gpt4_18c2b244, gpt4_7abb270c, gpt4_45189cb4, gpt4_e061b84f,
gpt4_d6585ce8, gpt4_f420262c` (+ borderline `7405e8b1`, a first-vs-first
comparison that resolves to "Yes", not a list). Unordered "list all X" phrasing
has **0** hits — the capability is specifically *ordered* enumeration.

Each gold answer is an **N-item list sorted by event date** (N = 3-6), and the
answer events are **3-6 needles scattered across ~50 haystack sessions** (e.g.
gpt4_7abb270c: 6 items, 48 sessions, 6 gold session_ids). → a **recall-
completeness** problem, not a top-1 lookup.

## 2. Surprising finding — the capability exists and is silently dead
`src/radiomind/skills/list_ordering.py` (`ListOrderingSkill`) is registered in
the skill registry (`skills/registry.py` `_bootstrap`) and already:
triggers on "order of X … earliest/latest", LLM-extracts `{name, date}` per
item (Trinity debate), **sorts by date**, and renders the joined list.

**It cannot fire on this dataset because of its date parser.** Verified
directly with the bench venv:
```
list_ordering._parse_date("2022/12/19 (Mon) 19:53")  -> None
list_ordering._parse_date("2022/12/19")              -> 2022-12-19  ✓
list_ordering._parse_date("2022-12-19")              -> 2022-12-19  ✓
list_ordering._parse_date("March 5, 2023")           -> 2023-03-05  ✓
```
The dataset's dates are ALL `YYYY/MM/DD (Dow) HH:MM` (verified sample:
`['2022/10/20 (Thu) 00:52', …]`). The parser uses `s[:len(fmt)+4]` with
`_DATE_FORMATS=("%Y-%m-%d","%Y/%m/%d","%B %d, %Y","%b %d, %Y")` — the `+4`
slice swallows ` (` and every format raises → `None`. With every date `None`,
`ListOrderingSkill.resolve` hits `if len(dated) < 2: return None` → **silent
abstain on the entire intended cohort.** The identical parser (and bug) is
copied in `skills/event_interval.py._parse_date`, so its FACT-store tier is
broken the same way. *(Source-line citations below are from the read-only
audit; the parser behaviour + dataset format + cohort are independently
verified by me.)*

## 3. Existing machinery
- **`typed_event_hint.py` — wrong shape, do NOT reuse/route through it.** It is
  a scalar reducer over a closed kin set `{self,mom,dad,grandma,grandpa}`,
  computes a *mean* age, is explicitly date-blind, and **refuses on multiplicity**
  (a role with >1 value → None). That is the opposite of "keep all items,
  ordered."
- **`list_ordering.py`** — the right component (extract → sort → render),
  already registered; needs fixing not building.
- **FACT-layer full enumeration exists**: `Database.list_by_domain(domain,
  level=MemoryLevel.FACT, limit=N)` returns ALL active facts in a domain (used
  by diagnose_qid, event_interval, self_anchor, temporal_endpoint_guard). This
  is the route to completeness vs top-k.
- **Date survives ingest→retrieve**: turns are stored with `session_date` both
  prepended into content and in `metadata`; rehydrated on every retrieval. So
  chronological info flows end-to-end (per audit).
- `KnowledgeGraph.timeline(entity)` gives a per-subject dated ordering, but
  keyed on one entity, not a query-time category ("museums").

## 4. Why it is not a narrow helper
Contrast with cashback/age committers (gather 1-2 anchors → one deterministic
arithmetic reduction → one scalar; ambiguity → abstain). OrderedEventList is
structural on every axis:
1. **Open, unbounded item set** named in the query (no closed role table to
   complete-or-abstain against; N unknown, 2-6+).
2. **Recall completeness, not top-1** — 3-6 needles in ~50 sessions; dominant
   failure = *missing an event* → forces FACT-layer enumeration / iterative
   retrieval, not a single top-k search.
3. **Sort + render, not reduce** — output preserves every item in order; new
   failure mode = *wrong order* (date mis-attribution), which has no analogue
   for a scalar mean.
4. **Dedup across mentions** — same event across turns must collapse to one
   (the age helper deliberately refuses on duplicates).
5. **Per-item date attribution is load-bearing** — ordering correctness = N
   independent date resolutions; the age helper needs zero dates.
→ gather-ALL → dedup → date-attribute-each → sort → render: a retrieval+
aggregation+sort+completeness pipeline, not a single-value rescue closure.
This is why it must stay a routed **skill**, not a narrow committer/hint, and
must NOT be folded into the Phase-2 proof-carrier family.

## 5. Reuse verdict + smallest viable shape
**Extend + fix `ListOrderingSkill`; do not greenfield; do not route through
`typed_event_hint`.** Smallest viable, in dependency order:
1. **Fix the date parser** to accept `YYYY/MM/DD (Dow) HH:MM` (+ keep ISO / `-`
   / month-name). Replace the `s[:len(fmt)+4]` slice with a tolerant
   front-anchored normalize-then-parse. **This single fix is necessary for ANY
   cohort question to pass and also repairs `event_interval`'s store-scan
   tier.** Pure, deterministic, unit-testable, no LLM.
2. **Completeness via FACT enumeration** — feed the extractor the full domain
   (`list_by_domain(FACT, limit=500)`) and/or iterative category expansion,
   not just the passed-in top-k (which structurally cannot recover 6/50
   needles).
3. Keep the existing extract (Trinity `{name,date}`) → dedup → sort → render;
   emit `SkillResult` with `(name,date)` anchors.

**Open risks**: date attribution (session_date vs an in-text past date →
wrong order); dedup (over-merge two real events / under-merge one event's
turns); completeness window; soft-routing collision with `temporal` /
`chain_reasoning` (confirm `list_ordering` wins the Trinity vote on the cohort).

## 6. Recommended next step — OrderedEventList-1b (smallest, deterministic)
**Fix the date parser only**, as a pure bug-fix slice:
- normalize `YYYY/MM/DD (Dow) HH:MM` (and tolerate ISO / month-name) in
  `list_ordering._parse_date`; apply the same fix to `event_interval._parse_date`
  (shared bug). Consider a single shared `_parse_event_date` helper.
- guard with a unit test (no LLM): the four formats above + the verified dead
  case now parses; add to the regression pack.
- NO behaviour-on-LLM change beyond un-breaking the parse; NO benchmark.

Only after 1b (parser green) does a 1c completeness slice (FACT enumeration) +
a single cohort smoke (`diagnose_qid`/qid run, needs LLM) make sense — that is
where the real recall question lives, and it should be gated like the closures
were (deterministic unit first, ingest smoke only when wanted).

## Files inspected (read-only)
- `src/radiomind/skills/list_ordering.py` (parser bug, extract/sort/render)
- `src/radiomind/skills/event_interval.py` (same parser bug; FACT-scan pattern)
- `src/radiomind/skills/registry.py` (routing / soft-resolve)
- `src/radiomind/core/typed_event_hint.py` (wrong shape — scalar reducer)
- `src/radiomind/storage/database.py` (`list_by_domain` FACT enumeration)
- `src/radiomind/core/mind.py` (ingest preserves session_date; soft routing)
- dataset `longmemeval_s_cleaned.json` (cohort + date format — verified)
