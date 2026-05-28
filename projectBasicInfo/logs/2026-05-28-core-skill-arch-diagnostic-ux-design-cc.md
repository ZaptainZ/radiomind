# Core Skill Architecture / Diagnostic UX — Phase 1 Design

**Date**: 2026-05-28
**Author**: Claude Code
**Status**: Read-only design + minimal diagnostic tool.
NO behavior change. Bench chasing paused per user direction.

---

## Why This Workstream

V8.2 → V8.4 cycle (just closed at `177b0ee`) proved a small
deterministic-helper architecture works for narrow LME-S
target qids. But the implementation is **scattered and ad-hoc**:

- Helpers live in 4 different files (`arithmetic_hint.py`,
  `typed_event_hint.py`, `age_interval_commit.py`,
  `temporal_endpoint_guard.py`).
- Each helper is hand-wired into the runner separately.
- Each ships with its own pre-implementation audit script,
  its own log format, its own test layout.
- Debugging a single qid requires running 4–6 ad-hoc
  scripts (ingest, retrieve probe, helper-by-helper probe,
  full e2e, judge inspect).
- No structured proof chain — helpers emit prose hints;
  proof lives in source-quote strings that are fragile
  to render-text parsing.

The next 2–3 helpers would compound this debt. Codex's
review fatigue across the cycle is largely about asking
the same questions repeatedly because no diagnostic
surface answers them automatically.

User's call (2026-05-28): **stop chasing bench, productize
what works**. The 4 pillars below frame the next phase;
Phase 1 (this commit) delivers the design + a minimal
diagnostic tool.

## Four Pillars

### Pillar 1 — Deterministic Skill Registry

Today's shape:

```
arithmetic_hint.cashback_arithmetic_hint(q, mems) → str
arithmetic_hint.savings_arithmetic_hint(q, mems) → str
typed_event_hint.person_age_average_hint(q, mems) → str
role_mismatch_guard.role_mismatch_guard(q, mems) → str
role_mismatch_guard.maybe_rewrite_with_guard(q, mems, ans) → str
temporal_endpoint_guard.temporal_endpoint_support_guard(q, mems, mind, domain) → str
temporal_endpoint_guard.maybe_rewrite_with_temporal_guard(q, mems, ans, mind, domain) → str
age_interval_commit.maybe_age_interval_commit_closure(q, mems, ans, temporal_section) → str
```

Each has a different signature, a different concept of
"input context", a different rewrite policy. The runner
manually orders them.

Target contract (Phase 2 — NOT in this commit):

```python
class DeterministicSkill(Protocol):
    name: str
    family: str  # "arithmetic" / "structural" / "presupposition"

    def match(self, q: Query, ctx: Context) -> bool: ...
    def extract(self, q: Query, ctx: Context) -> ExtractedEvidence | None: ...
    def prove(self, ev: ExtractedEvidence) -> Proof | None: ...
    def render_hint(self, proof: Proof) -> str: ...

    # Optional commit-side rewrite policy
    rewrite_policy: RewritePolicy  # never / on-over-commit / on-pure-abstain
    def maybe_rewrite(self, proof: Proof, llm_answer: str) -> str | None: ...
```

Then the runner becomes a single loop:

```python
for skill in skill_registry:
    if not skill.match(query, ctx): continue
    ev = skill.extract(query, ctx)
    if ev is None: continue
    proof = skill.prove(ev)
    if proof is None: continue
    prompt_prefix += skill.render_hint(proof)
    proofs.append((skill, proof))

# ... LLM call ...

for skill, proof in proofs:
    rewrite = skill.maybe_rewrite(proof, llm_answer)
    if rewrite is not None: llm_answer = rewrite
```

This is what we'd refactor INTO. Phase 1 only documents it.

### First diagnostic finding (Phase 1 smoke surface)

Running `diagnose_qid --qid bb7c3b45` against a fresh
sandbox produced an immediately useful insight:

- `mind.search(..., max_results=200)` returned only 119
  entries (FACT-layer events squeezed user turns out of
  top-119).
- The user turn containing `"got at the outlet mall for
  $200"` (`answer_de64539a_1_t0`) was **not in the
  retrieved set**. Only an assistant echo ("Jimmy Choo
  heels for $200 is a steal!", rank 96) carried the $200
  number.
- `savings_arithmetic_hint`'s user-turn-only filter
  correctly rejected the assistant echo → helper emitted
  empty string.

**This is finding worth surfacing**: SavingsHint's
production reliability is sensitive to retrieve recall.
The earlier SavingsHint-1b smoke passed because *that*
run's retrieve happened to surface the user turn (or the
answer-LLM inferred $200 from the assistant echo); the
audit log overstated the deterministic guarantee. The
helper still works on the audited evidence structure;
it just doesn't trigger every time the question is asked.

This is exactly the type of insight Phase 2's `Proof`
shape will make visible at run-time (proofs would carry
`refusal_reason = "paid anchor not in retrieved memories"`).
For now, the diagnostic tool exposes it after-the-fact.
No code change to the helper — by design Phase 1 doesn't
mutate behavior.

### Second diagnostic finding (c18a7dc8) — RETRACTED ATTRIBUTION 2026-05-28

Original attribution claim: "FACT extraction stripped
the age qualifier". **RETRACTED.** Codex re-read the
diagnose JSON and found that rank 1's preview actually
reads:

> `event: completed Bachelor's degree in Business
> Administration with a concentration in Marketing from
> University of California, Berkeley **at age 25**
> [date=2023-05-26]`

The FACT extractor **DID preserve the age info** — it
just normalized the raw user phrasing `"completed at the
age of 25"` into `"at age 25"` (no "the", no "of").

The age_interval skill's `_age_at_event` regex requires
`at\s+the\s+age\s+of` / `when\s+I\s+was` / `aged` — none
of which matches `"at age N"`. So the helper failure is
a **phrase-variant mismatch** at the helper regex,
NOT a FACT extraction loss.

The correct refusal reason (now exposed by Phase 1.5):
`age_phrase_variant_unsupported`. Different fix shape:
either widen the `_age_at_event` regex to include the
`at age N` form, or normalize FACT phrasings back to the
canonical "at the age of" pattern.

Earlier AAS-2 probe got `STRUCTURED SKILL` because the
LSA-3 sandbox had raw user turns (not FACT events) in
its retrieve top-K. Same skill, same memories shape,
different proximity outcome.

### Combined implication (revised)

Both findings still reinforce Pillar 2 (Proof-Carrying
Result) and Pillar 4 (Diagnostic UX). The diagnostic
tool's first-pass attribution was **too strong** — it
took the helper's empty-string output and inferred a
specific upstream cause without verifying. Phase 1.5
(refusal-reason instrumentation) fixes exactly this: the
helper itself now reports which gate it failed and what
related signals it found nearby, so attribution is
mechanical rather than inferential.

### Phase 1.5 4-qid re-run — confirmed and refined

After implementing `diagnose_*` parallel functions on
each helper (and adding per-qid sandbox + full-store
anchor probe), re-ran 4 representative qids:

| qid | helper | fired | refusal_reason | proof state |
|---|---|---|---|---|
| `9aaed6a3` | cashback | **TRUE** ✓ | — | rate=0.01, merchant=SaveMart, amount=$75, product=$0.75 |
| `bb7c3b45` | savings | False | `paid_anchor_not_found_in_user_turns` | anchor="jimmy choo heels", retail=$500 found, paid not in user-turn memories |
| `gpt4_d12ceb0e` | person_age | False | `kin_role_missing=['self']` | grandpa=78, dad=58, grandma=75, mom=55 — self age missing |
| `c18a7dc8` | age_interval | False | `current_age_not_in_retrieved` | skill DID fire conf=0.9→"7"; strict `_age_at_event=25` matched a raw user turn; user's current-age (32) self-id missing |

### Findings — accurate this time

1. **9aaed6a3 cashback is reliably retrievable.** Helper
   fires deterministically; serves as the positive
   anchor.

2. **c18a7dc8 attribution corrected (again).** The
   earlier "FACT extraction stripped age qualifier" was
   wrong (retraction above). The new "phrase variant
   unsupported" attribution is ALSO wrong: the `_age_at_
   event` strict regex did match a raw user turn (the
   raw turn IS in retrieve top-200 alongside the FACT
   event). The actual refusal is at the rewrite layer:
   **the user's current-age self-id ("as a 32-year-old
   Digital Marketing Specialist") was NOT in retrieve
   top-200**. Without current age, the recompute-match
   gate can't validate.

3. **gpt4_d12ceb0e (person_age) shows the same shape**:
   4 of 5 kin ages retrieved, but `self` is missing.

4. **bb7c3b45 retrieve recall sensitivity confirmed**:
   user-turn-with-$200 ranks outside top-200; only the
   assistant echo of "$200" is retrieved (filtered).

### Architectural pattern

Three of four helper failures share the SAME root cause:
**the user's first-person self-statement anchor (paid
price / current age / etc.) ranks outside retrieve
top-200, even when the haystack carries it.**

- bb7c3b45: paid anchor user-turn ranks out
- gpt4_d12ceb0e: self-age statement ranks out
- c18a7dc8: current-age self-id ranks out

This is NOT a helper design problem. The helpers
correctly refuse to commit. It's a **retrieval recall
problem** that's invisible until Phase 1.5 instrumented
the refusal reasons.

### Implications for Phase 2+

- The right next workstream is not refactoring helpers
  into a registry. The retrieval layer is leaking
  first-person self-statements. Pillar 2's `Proof`
  schema would carry `retrieve_window` snapshots, but
  the actual fix is on the **retrieval side** —
  potentially boost first-person `i\s+(am|'m|was)\s+
  \d` self-id patterns OR add a domain-store-scan
  fallback for current-age / paid-price anchors.
- Phase 1.5 already de-risks Phase 2 / 3 by surfacing
  this pattern. Without it, refactoring helpers into a
  registry would have looked clean while production
  remained quietly retrieve-recall-fragile.

These findings are not implementation directives — they
are observations the tool generated. The user/Codex
review will decide whether to open a retrieve-recall
workstream, a store-scan-fallback workstream, or stay
paused.

### Pillar 2 — Proof-Carrying Result

Today, helpers emit prose text and the LLM is asked to
trust it. Proof is implicit (the regex match positions).

Target shape:

```python
@dataclass
class Proof:
    skill_name: str
    family: str
    operation: str  # "retail-paid", "rate*amount", "current-past"
    inputs: list[ProofInput]  # each = (label, value, source_quote, session_id)
    output: Any  # the computed answer
    confidence: float
    refusal_reason: str | None  # populated when prove() returns None

@dataclass
class ProofInput:
    label: str  # "paid_price" / "retail_price" / "past_age"
    value: Any
    source_quote: str  # ~140 chars around the regex hit
    session_id: str | None
    turn_id: str | None
```

Benefits:

- TSI-1d-style recompute-match is a one-line check on
  `Proof.output == recompute(Proof.inputs)`.
- The diagnostic tool can render proofs as evidence tables
  without hand-parsing helper output.
- Judge integrity audits get structured data, not string
  scraping.

Phase 1 does not implement `Proof`. Phase 2 will.

### Pillar 3 — Evaluation Harness Hygiene

Done in V8.4:

- JAB-1a/b deterministic veto in runner
- runner checkpoint resume rebuild of judge stats
- rejudge utility with artifact + checkpoint schema sync
- `is_abstain_response` with concrete-commitment safety

Codified into runner default behavior (already shipped):

- `bench/end_to_end/run_longmemeval_mem0.py` veto block at
  line 749-758
- `bench/end_to_end/jab1_abstain_veto.py` shared detector
- Resume-stats fix at line 347-359

Outstanding (Phase 2):

- A runner-end "self-check" that asserts `raw_accuracy ==
  derived_from_per_query`, fails LOUDLY if not. Today an
  invariant violation requires manual diff.
- A standard `--artifact-normalize` flag that re-derives
  all aggregate fields from per_query before write.
- Make rejudge utility part of the runner subcommand, not
  a separate script.

### Pillar 4 — Diagnostic UX

This is the Phase 1 deliverable: **`diagnose_qid.py`**, a
single-qid layered probe.

Inputs: `--qid X` (any LME-S qid).
Outputs: structured JSON + human-readable summary.

Captures all layers' state for one qid:

1. Question, gold, qtype, answer_session_ids.
2. Ingest stats (turns, sessions).
3. Retrieve top-30 (turn_id, score, snippet, is-gold).
4. Per-helper signal: did it fire? what string did it
   emit? (run each helper in isolation against the
   retrieved memories.)
5. Skill registry probe via `mind.run_temporal_precision`:
   does any skill produce a `STRUCTURED SKILL` block?
6. JAB-1a what-if: would the veto fire on this qid's
   gold against a synthesized canonical-abstain response?

NOT in Phase 1:

- Full e2e (~10 min/qid). Use existing runner `--qids X`
  for that.
- Judge call. Diagnostic tool stays free.
- Diff-against-baseline. Phase 1.5 will add `--baseline
  artifact.json` for diff vs prior verdict on same qid.

The tool's value: any future audit (Codex-style review,
helper trigger debug, retrieve recall investigation)
starts from a single JSON snapshot, not 4 ad-hoc scripts.

## Phase Scoping

| phase | scope | timing |
|---|---|---|
| **Phase 1** (this commit) | Design doc + `diagnose_qid.py` (read-only layered probe) | 2026-05-28 |
| Phase 1.5 | `diagnose_qid --baseline` for diff vs artifact verdict | future |
| Phase 2a | `Proof` dataclass + 1 helper refactored to emit `Proof` | future |
| Phase 2b | `DeterministicSkill` Protocol + registry; runner loop replaces manual wiring | future |
| Phase 2c | Runner self-check assertions + `--artifact-normalize` | future |
| Phase 3 | All existing helpers (role, cashback, savings, person_age, TESG, TSI) migrated to the registry | future |
| Phase 4 (optional) | OrderedEventList-1a architecture audit (if needed) | future |

Each phase has its own audit + smoke checkpoint. No
phase is allowed to ship without:

- pre-implementation audit log
- unit tests
- target smoke on at least 2 representative qids
- no model-behavior change unless explicitly scoped

## Constraints (carried forward from V8.4)

1. **Pre-implementation audit before ship.**
2. **Strict gate; default hint-only; commit-side rewrite
   requires multiple deterministic proofs.**
3. **Absence of evidence ≠ negative evidence.**
4. **No cross-family expansion at first ship.**
5. **Evaluation hygiene is bench-side responsibility.**
6. **N=100 is for consolidation, not validation.**

## Phase 1 Deliverable Spec

`bench/end_to_end/diagnose_qid.py`:

- CLI: `python diagnose_qid.py --qid <qid> [--sandbox PATH] [--out JSON]`
- Loads LME-S dataset, finds the qid.
- Reuses sandbox if `--sandbox` provided and ingested;
  otherwise fresh ingest.
- Probes each layer (retrieve / each helper / temporal
  precision / open-domain).
- Writes a structured JSON and prints a human-readable
  summary.

Out of Phase 1:

- Mutating helpers (no behavior change).
- Adding new skill registrations.
- Running full e2e or judge.
- Inferring helper proofs from prose (Phase 2 introduces
  `Proof` then helpers can emit it directly).

## Files

- This design log: `projectBasicInfo/logs/2026-05-28-core-skill-arch-diagnostic-ux-design-cc.md`
- Phase 1 tool: `bench/end_to_end/diagnose_qid.py`
- Related: V8.2 → V8.4 cycle close-out
  (`projectBasicInfo/logs/2026-05-28-v82-v84-cycle-closeout-cc.md`)
