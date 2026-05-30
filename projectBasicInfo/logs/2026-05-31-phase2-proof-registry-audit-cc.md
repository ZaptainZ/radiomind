# Phase2-1a — Proof / Commit-Closure Registry Audit (read-only)

**Date**: 2026-05-31
**Author**: Claude Code
**Status**: Read-only audit + schema proposal. NO source change. Inventories
the four shipped post-LLM rewrite closures, extracts their field
intersection, and proposes a scoped unified `ProofResult` + commit contract.
**Key correction vs first instinct:** the four are NOT one symmetric family —
they split into TWO families with *inverted* abstain polarity (see §3). A
single `ProofResult → commit_closure` cleanly fits only TWO of them.

> Line numbers are approximate. cashback + age claims cross-checked against
> direct source reads; role/temporal verified via grep (filenames,
> signatures, runner args) + a read-only sub-agent that read the bodies.

---

## 1. The four closures (corrected inventory)

All four run **post-LLM**, before the judge, in `run_longmemeval_mem0.py`,
each in a `try/except: pass`, each reassigning `answer = closure(...)`.
None returns `None` (always a `str`; age/cashback) or `(str, telemetry)`
in the suppressor pair — see per-closure note.

| # | Closure | File (real name) | Family | Acts on | Effect |
|---|---|---|---|---|---|
| 1 | role | `core/role_mismatch_guard.py` · `maybe_rewrite_with_guard` | **SUPPRESS_OVERCOMMIT** | a CONCRETE over-committed answer | downgrade → abstain |
| 2 | temporal (TESG) | `core/temporal_endpoint_guard.py` · `maybe_rewrite_with_temporal_guard` | **SUPPRESS_OVERCOMMIT** | a CONCRETE duration answer | downgrade → abstain |
| 3 | age | `core/age_interval_commit.py` · `maybe_age_interval_commit_closure` | **COMMIT_ON_ABSTAIN** | a PURE abstain | upgrade → concrete value |
| 4 | cashback | `core/arithmetic_hint.py` · `maybe_cashback_commit_closure` (+`resolve_cashback_proof`) | **COMMIT_ON_ABSTAIN** | a PURE abstain | upgrade → concrete value |

Runner wiring (verified args):
1. `answer = maybe_rewrite_with_guard(question, mem_results, answer)` — **3 args, no mind/domain**
2. `answer = maybe_rewrite_with_temporal_guard(question, mem_results, answer, mind=mind, domain=domain)`
3. `answer = maybe_age_interval_commit_closure(question, mem_results, answer, temporal_section, mind=mind, domain=domain)`
4. `answer = maybe_cashback_commit_closure(question, mem_results, answer, mind=mind, domain=domain)`

### 1 · role — SUPPRESSOR
- Detector `detect_role_mismatch` → `{q_role, m_roles, q_track}`
  (`q_track` ∈ leadership/ic/unknown). Fires when the question's role track
  conflicts with the memory roles' track.
- Gate: mismatch detected **AND** `_looks_over_committed(answer)` True (answer
  names a concrete role/headcount/$). **Bypasses when the answer already
  abstains.** No abstain-commit; this is the inverse.
- No committed value, **no recompute**. Output = templated abstain:
  `"The information provided is not enough. You mentioned starting the role as <m_role> but not <q_role>."`
- Provenance: none stored (`q_role`/`m_roles`/`q_track` only).

### 2 · temporal (TESG) — SUPPRESSOR
- Detector `detect_temporal_endpoint_mismatch` → `{employer, evidence_hits(=0),
  has_explicit_negative}`. Fires when question asks a "before I started at Y"
  endpoint, evidence for having started at Y is **absent** in retrieve AND in
  the FACT store (`list_by_domain` level=FACT, limit=500), and the answer
  commits to a duration (`_looks_over_committed`, a duration regex).
- **Bypasses when answer already abstains.** No committed value, **no
  recompute** (absence-of-evidence, not a re-derived number).
- Output = templated abstain (two wordings keyed on `has_explicit_negative`).
- Provenance: none stored; scan scope implicit (retrieve + FACT cap-500).

### 3 · age — COMMITTER
- Gate (ALL): `skill_name=="age_interval"`; `conf>=0.85`; `computed` parses
  int; `mode∈{older,younger}`; **`_is_pure_abstain(llm_answer)` True**
  (never overwrites concrete); `at_age` found; `current_age` found (retrieve
  or SelfAnchor store-scan).
- **Genuine recompute**: re-derives `current_age−at_age` (or reverse) from
  matched anchor regexes and requires `== skill_value` before committing.
- Proof = local vars (no dict): `at_age`, `current_age`, `interval`(value),
  `past_evidence`(quote), `current_evidence`(quote); on store-scan also
  `source_turn_id`+`scan_scope` via a `SelfAnchorProof`. **Dual provenance.**
- Output = `"<interval> <unit>. (Verified: … sources …)"`. `_is_pure_abstain`
  is defined here and is the shared detector cashback reuses.

### 4 · cashback — COMMITTER (cleanest)
- Gate: `_is_pure_abstain(llm_answer)` True (imports age's detector);
  `resolve_cashback_proof(...)` not None; recompute `round(rate*amount,2)==product`.
- `resolve_cashback_proof` → the **only explicit proof dict**:
  `{merchant, amount, rate, product, rate_source_turn_id, rate_scan_scope}`.
  amount must be in retrieve; rate retrieve-scoped or store-scan; competing
  merchant / conflicting rate → no rate → None.
- Output = `"You earned $X in cashback at <merchant>."`
- Note: its recompute re-rounds the SAME rate×amount → tautological self-check
  (weaker than age's two-source cross-check).

Shared infra: `SelfAnchorProof` (`self_anchor.py`: `kind, value,
source_turn_id, quote, scan_scope`) — the only real proof dataclass — is
consumed by the store-scan paths of #3 and #4 (and the savings hint).

---

## 2. Field intersection matrix

PRESENT(name) / IMPLICIT(computed, not stored) / ABSENT.

| Candidate field | role (S) | temporal (S) | age (C) | cashback (C) |
|---|---|---|---|---|
| `kind` | ABSENT | ABSENT | IMPLICIT (skill_name) | IMPLICIT (SelfAnchorProof.kind) |
| `value` / committed | ABSENT (suppress) | ABSENT (suppress) | PRESENT (`interval`) | PRESENT (`product`) |
| `confidence` | ABSENT | ABSENT | PRESENT (`conf`≥0.85) | ABSENT |
| `source_turn_id` | ABSENT | ABSENT | PARTIAL (store-scan only) | PRESENT (rate, store-scan only) |
| `quote` | ABSENT | ABSENT | IMPLICIT (in output string) | ABSENT |
| `scan_scope` | ABSENT | IMPLICIT (retrieve+FACT) | PARTIAL (store-scan) | PRESENT (`rate_scan_scope`) |
| `inputs` | PRESENT-ish (q_role,m_roles,q_track) | PRESENT-ish (employer,flags) | IMPLICIT (at_age,current_age,mode) | PRESENT (merchant,amount,rate) |
| `recompute_check` | ABSENT | ABSENT | **PRESENT (2-source)** | PRESENT (tautological) |
| `refusal_reason` | ABSENT | ABSENT | ABSENT (only in `diagnose_*`) | ABSENT (only in `diagnose_*`) |
| `commit_allowed_on_abstain` | **INVERTED** (acts on over-commit) | **INVERTED** | required True | required True |
| *(extra)* subject anchor | `q_role` | `employer` | — (none) | `merchant` |
| *(extra)* evidence-absence flag | — | `evidence_hits`,`has_explicit_negative` | — | — |

**Universal gaps:** `confidence` only in age; `kind` never explicit;
`refusal_reason` lives only in the parallel read-only `diagnose_*` functions,
never in the live closures; flat `source_turn_id`/`quote` are insufficient
(age dual, cashback amount-side unattributed).

---

## 3. The two structural blockers

1. **Inverted abstain polarity (the decisive split).** Suppressors (role,
   temporal) fire on a CONCRETE over-commit and downgrade it to abstain,
   and *bypass when the answer already abstains*. Committers (age, cashback)
   fire ONLY on a pure abstain and upgrade it to concrete, *never touching
   concrete*. A single boolean `commit_allowed_on_abstain` cannot model
   opposite invariants — needs a `policy` discriminator, and the two paths
   have contradictory safety rules.
2. **Suppressors have no value and no recompute.** They carry a *subject*
   (`q_role`/`employer`) + an *evidence-absence* judgement, not a derived
   value. Committers carry a *value* + *inputs* + *recompute*. Forcing both
   into one `ProofResult` would leave half its fields meaningless for each
   side.

Secondary frictions: 3 different over-commit/abstain detectors
(`_looks_over_committed`×2 distinct pattern sets + shared `_is_pure_abstain`);
heterogeneous context args (`temporal_section`, `mind`, `domain`); age is
coupled to a rendered prompt string it reverse-parses (`parse_temporal_section`,
flagged fragile); provenance unevenly carried and never uniformly stored.

---

## 4. Proposed `ProofResult` — scoped to the COMMITTER family

A unified proof carrier fits **age + cashback** cleanly. role/temporal are a
*different* abstraction (suppression guards) and should NOT be force-fit.

```python
@dataclass(frozen=True)
class Source:
    turn_id: str | None
    quote: str | None
    role: str | None = None          # "amount"/"rate"/"at_age"/"current_age"

@dataclass(frozen=True)
class ProofResult:                   # COMMIT_ON_ABSTAIN family only
    kind: str                        # "age_interval" | "cashback"
    value: Any                       # raw derived value (int/float)
    inputs: dict                     # operands {at_age,current_age} / {amount,rate}
    sources: list[Source]            # >=1; covers age-dual / cashback-split
    recompute_ok: bool               # re-derived value matched
    rendered: str                    # committed answer string
    scan_scope: str | None = None    # store-scan provenance else None
    confidence: float | None = None  # age sets it; cashback leaves None
    # refusal_reason intentionally omitted (lives in diagnose_*, not live path)
```

Decisions vs the 11 candidates: fold `source_turn_id`+`quote` → `sources`
list; replace `commit_allowed_on_abstain` bool → the family IS the policy
(this dataclass is the abstain-committer); split committed → `value`(raw) +
`rendered`(string); keep `confidence` (age uses it); drop `refusal_reason`
from the live struct.

The suppressor pair, if ever unified, wants a *separate* tiny shape, e.g.
`SuppressionVerdict{subject, evidence_present: bool, detector: str, rendered}`
— out of scope for the proof registry.

## 5. Commit contract

Keep the gate WITH each family — share the carrier + provenance/recompute
helpers, not a god-function:

```python
def commit_on_abstain(proof: ProofResult | None, llm_answer: str) -> str:
    if not _is_pure_abstain(llm_answer): return llm_answer   # never overwrite concrete
    if proof is None or not proof.recompute_ok: return llm_answer
    return proof.rendered
```

A single `commit_closure(proof, llm_answer)` spanning both families would
obscure the inverted-polarity gate and risk breaking the abstain-only safety
of age/cashback — the explicit Phase-2 risk.

---

## 6. Answers to the Phase2-1a questions

- **Minimal `ProofResult` schema?** → §4, scoped to the committer family
  (age + cashback). `sources` is a list; no `refusal_reason`; `confidence`
  optional.
- **Which migrate directly?** → **cashback first** (already a real proof dict
  + scan_scope + source_turn_id; cleanest pilot). **age second** (real
  recompute + dual `sources` — exercises the list design).
- **Which need new fields first?** → role & temporal don't "need fields" —
  they're a **different family** (suppressors, no value/recompute). Don't
  migrate them into `ProofResult`; if unified at all, give them their own
  `SuppressionVerdict`. Migrating them into the proof registry is the wrong
  abstraction.
- **`commit_closure` hard-gate?** → `commit_on_abstain` only (§5); the
  suppressors keep their own `_looks_over_committed`-gated path.
- **Is Phase2-1b worth it?** → **Yes, narrowly.** Build ONLY
  `ProofResult`/`Source` + have **cashback** also *return* a `ProofResult`
  for telemetry, with **zero change to the commit decision or output bytes**.
  Do NOT touch role/temporal, do NOT add a dispatcher. Then 1c = age adopts
  the same carrier. Gate every step on the full closure suite staying green
  (byte-path unchanged or diff explainable).

---

## 7. Files (read-only)
- `src/radiomind/core/role_mismatch_guard.py` · `temporal_endpoint_guard.py`
  · `age_interval_commit.py` · `arithmetic_hint.py` · `self_anchor.py`
- `bench/end_to_end/run_longmemeval_mem0.py` (post-LLM wiring)
- Prior: `2026-05-30-trustclosure-1c-closeout-cc.md`,
  `2026-05-30-trustclosure-1a-audit-cc.md`.

## 8. Next
Phase2-1b = `ProofResult`/`Source` dataclasses + cashback adapter (telemetry
only, no behavior change), suppressors untouched. Gated on the closure suite
staying green. Not started.
