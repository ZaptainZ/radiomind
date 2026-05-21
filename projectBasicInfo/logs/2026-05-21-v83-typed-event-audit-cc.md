# V8.3 Typed Event / Computation Layer — Read-Only Audit

**Date**: 2026-05-21
**Author**: Claude Code
**Scope**: Audit only. No code changes. Diagnostic feasibility analysis.
**Trigger**: After V8.2.3a merge, Codex proposed V8.3 typed-event layer as the next architectural direction. Before implementing, audit 6 representative LME-S FAIL cases to determine whether typed events can deterministically yield gold without excessive LLM semantic judgment.

---

## Audit Method

For each qid I (a) loaded the LME-S haystack, (b) pulled the gold-marked `answer_session_ids` evidence, (c) read the raw conversation text, (d) classified the fail type, (e) judged whether the gold answer can be obtained by extracting typed events + applying a deterministic operator (sum / count / order / lookup / arithmetic), and (f) noted the risks that would survive into implementation.

Decision rule (from Codex):
- **GREEN** = typed events stably extractable + deterministic operator yields gold → V8.3 implementation viable for this case
- **YELLOW** = typed events extractable but operator depends on fuzzy normalization or temporal interpretation → V8.3 needs careful scoping
- **RED** = gold requires LLM semantic synthesis or non-trivial entity normalization → keep V8.2.x / pure LLM, don't try typed-event

---

## Per-qid Audit Table

| qid | fail type | gold event(s) needed | raw memory evidence | current extraction possible? | deterministic answer possible? | risk | verdict |
|---|---|---|---|---|---|---|---|
| `d851d5ba` | arithmetic aggregation (sum) | 4 × `fundraise_event{amount:$, beneficiary, date?}` | `$1,000 for the local children's hospital at a charity bake sale`; `raising $250 for a local food bank` (Run for Hunger); `raise $500 for the American Cancer Society` (Feb fitness challenge); `helped raise $2,000 for the local animal shelter on January 20th` | YES — `raise/raising/raised $X for Y` is a tight regex; beneficiary is the np after `for` | YES — sum 4 distinct event amounts: 1000+250+500+2000 = $3,750 ✓ matches gold | **Dedup**: bake sale ($1,000) is referenced from multiple sessions (session 2 original mention + session 1 cross-ref `over $1,000`); need stable `dedup_key=(amount, beneficiary, normalized_event_type)` so cross-session mentions of the same event don't double-count. **Scope**: "total" must trigger sum operator; question word disambiguation. | **GREEN** |
| `gpt4_ab202e7f` | distinct entity count | 5 × `kitchen_item_action{item, action∈{replace,fix}, dedup_key}` | `replaced my old kitchen faucet`; `new kitchen mat in front of the sink from IKEA`; `got rid of the old toaster and replaced it with a toaster oven` (×3 sessions); `fixed the kitchen shelves last weekend`; gold also lists coffee maker (not visible in shown evidence — likely in another session) | PARTIAL — explicit verbs `replace/replaced/fixed/got rid of` are regex-able; but implicit forms like `got a new kitchen mat` or `new faucet` rely on adjective `new` + item + verb-of-acquisition, which is fuzzier; espresso machine (`gift from sister`) must NOT count | PARTIAL — count distinct items, but entity normalization is the bottleneck: `faucet` ≡ `kitchen faucet` ≡ `Moen faucet`; `toaster` → `toaster oven` is ONE replacement event, not two items | **Entity normalization**: requires either an LLM normalizer or a hand-curated synonym table. **Implicit verbs**: `got a new X` semantics. **Same-event dedup**: toaster→toaster oven mentioned in 3 sessions but same physical event. **Action classification**: `decluttering` ≠ replace/fix. | **YELLOW–RED** — typed events extractable in principle but entity normalization is LLM territory; don't try as the V8.3 launch case |
| `gpt4_d6585ce8` | temporal ordering (with implicit dates) | N × `music_event{venue, artist_or_type, event_date}` | Billie Eilish @ Wells Fargo Center Philly (session_id ts); music festival Brooklyn; Queen+Adam Lambert @ Prudential Center Newark NJ; free outdoor concert series in park `today`; jazz night at local bar `today` | PARTIAL — entities (venue, artist, event_type) extract cleanly via NER + concert-keyword regex; but dates depend on session timestamp + relative markers (`today`, `recently`, `got back from`) — same machinery as V7 temporal_provenance | PARTIAL — IF `event_date := relative_resolve(session_ts, "today"|"recently"|absent→session_ts)` works, then sorting events by event_date yields gold ordering. Question filter `past two months` requires `now - 60d ≤ event_date ≤ now`. | **Multi-event-per-session**: one session may mention 2 events. **Bare past-tense ambiguity**: `got back from Billie Eilish concert` with no explicit relative marker — fallback to session timestamp. **Question phrase `past two months`** must trigger the filter. | **YELLOW** — feasible because V7 temporal_provenance already handles relative resolution; the typed event addition is the entity+date binding. Worth piloting AFTER the GREEN cases. |
| `9a707b82` | temporal loose match | 1 × `cooking_event{item, recipient, event_date}` | session 1 [10] `I just baked a chocolate cake for my friend's birthday` (the canonical mention) | YES — `baked/cooked X for Y` is a tight verb-object-recipient regex; recipient extraction `for my friend('s …)` is regular | PARTIAL — gold requires recognizing `couple of days ago` ≈ `session_ts - 2d` AND that `my friend's birthday` cake is the cake `for my friend`. Both are doable but each is one inferential step. | **Temporal fuzz**: `a couple of days` → tolerance window ±3d? Needs explicit policy. **Recipient identity**: `friend's birthday` cake counts as `for friend`? Almost always yes, but should be a logged rule. **Already partially solved by V8.2.1 retrieve** — retrieve finds chocolate cake at rank 4; the failure was LLM not soft-matching the temporal phrase. V8.3 typed event with explicit event_date could let a deterministic temporal filter answer without LLM date judgment. | **YELLOW** — clean typed event, but only marginally better than V8.2.x because retrieval already finds the candidate; the win is removing LLM date judgment |
| `gpt4_d12ceb0e` | arithmetic (average over typed facts) | 5 × `person_age{relation∈{self,mom,dad,grandma,grandpa}, age:int}` | `grandma is 75 and grandpa is 78`; `mom is 55 and dad is 58`; `I just turned 32 on February 12th` | YES — `<relation> is <N>` and `I just turned <N>` are very tight regexes; relation vocabulary is closed-set (~6 kin terms) | YES — extract 5 typed facts, mean = (32+55+58+75+78)/5 = 59.6 ✓ matches gold exactly | **Stale ages**: if user references different ages over time, latest-wins or session-clustered. In this dataset all ages are within a few sessions, no conflict. **Self detection**: `I just turned 32` ⇒ relation=self. **Question word `parents and grandparents`** maps to {mom,dad,grandma,grandpa} — closed mapping. | **GREEN** — cleanest case in the audit. Person-age facts + average operator is textbook typed-event territory. |
| `d6233ab6` | preference advice (subjective synthesis) | personal_history themes / preference flags, NOT a factual lookup | `I still remember the happy high school experiences such as being part of the debate team and taking advanced placement courses in economics` | NO useful TYPED event — could model `personal_memory_topic{topic=high school, sentiment=positive, examples=[debate, AP econ]}` but the gold answer is style guidance (`prefer responses that draw upon personal experiences and positive high school memories`), not a fact to look up | NO — there is no operator that yields advice from a memory event; the LLM must synthesize empathetic advice that references the positive memories | **Category mismatch**: this isn't an information-extraction problem, it's an LLM advice/preference task. Forcing a typed event here would either be a no-op or a vacuous flag. | **RED** — typed event layer should NOT try to solve this; keep V8.2.x + LLM. Out of scope. |

---

## Decision Summary

Cases sorted by V8.3 typed-event implementation priority:

1. **`gpt4_d12ceb0e` (average age) — GREEN, do first.** Closed-vocabulary kin relations + integer ages + average operator. Smallest blast radius, deterministic, easy to test on isolated fixtures. This is the strongest signal that V8.3 has value.
2. **`d851d5ba` (charity sum) — GREEN, do second.** Extends the same arithmetic family. Adds the dedup_key challenge (same event mentioned across sessions), which is real but solvable with `(amount, beneficiary)` keying.
3. **`9a707b82` (cooking temporal) — YELLOW, optional.** Already mostly fixed by V8.2.1 retrieval; the V8.3 win is removing LLM date-fuzz judgment. Worth adding only if temporal_provenance already has the machinery (it does — V7 Step 3).
4. **`gpt4_d6585ce8` (concert ordering) — YELLOW, defer.** Feasible but the typed-event surface is larger (multi-event-per-session, date filter, ordering operator); a good V8.3.2 follow-up, not V8.3.1.
5. **`gpt4_ab202e7f` (kitchen count) — YELLOW–RED, do not pilot.** Entity normalization is LLM-shaped; typed events here would either degrade to LLM-call or use a brittle synonym table. Leave to LLM.
6. **`d6233ab6` (preference advice) — RED, out of scope.** Not an information-extraction problem. Keep on LLM.

### V8.3 scope recommendation

**Pilot V8.3.1 on the arithmetic-aggregation family** (`person_age` and `fundraise_event`), with:

- Event schema: `{event_type, subject, object, amount, unit, date, source_quote, confidence, dedup_key}`
- Operators: `sum`, `mean`, `count_distinct` — pure functions over typed events
- Wire-in: hint-only (same pattern as V8.2.3a), zero blast radius — if extraction confidence is low or operator can't bind, emit no hint and fall through to current LLM path
- Test fixture: the two GREEN qids above as targeted PASS, plus negative controls (`d6233ab6`-style preference questions must NOT trigger)

**Do NOT** in V8.3.1:
- Entity normalization synonym tables (kitchen items case)
- Multi-event-per-session ordering (concert case) — leave for V8.3.2 if V8.3.1 proves out
- Subjective / advice questions (preference case) — never typed-event territory

### Risk register

- **Dedup key brittleness**: cross-session same-event mentions; need conservative key (amount + beneficiary or amount + relation) and a "skip when ambiguous" rule (same instinct as V8.2.3a's no-merchant guard)
- **Operator trigger word** ambiguity: `total / how much / average / how many` map to operators, but `how much did I save` doesn't mean sum — needs the same query-intent regex care V8.2.3a got
- **Confidence threshold**: if any required typed event has confidence < threshold, abort hint (same hint-only philosophy)
- **Hint-vs-rewrite**: V8.2.3a is a HINT injected into the LLM context, not an answer override. V8.3.1 should follow the same pattern; never assert "the answer is $3,750" — instead `[TYPED EVENT HINT] sum = 1000+250+500+2000 = $3,750`
- **Test gate**: before any wire-in, the typed extractor must hit ≥0.9 precision on a held-out fixture covering the negative-control questions; precision matters more than recall (false positives override LLM, false negatives just fall through)

### What this audit does not commit to

This is an audit, not a green-light. Even on the GREEN cases, V8.3.1 should ship behind a separate config flag and be benchmarked alongside the current V8.2.x baseline. If LME-S deltas on the GREEN qids are <2 cases improved and any other case regresses, V8.3.1 stays off by default.

---

## Appendix A — Evidence Source

Audit script: ad-hoc Python over `bench/data/longmemeval_s.json`, dumped `answer_session_ids` evidence for each qid. Raw dump persisted at the tool-result store; not committed.

## Appendix B — Cross-reference

- V8.2.3 retrieval-premise falsification log: `2026-05-21-v823-retrieval-premise-falsified-cc.md`
- V8.2.x scoreboard: `2026-05-21-v82x-scoreboard-cc.md`
- V8.2.x FAIL classification: `2026-05-21-v823-fail-classification-cc.md`
