# 03 — RadioMind Dev Workflow & Diagnostic Standard

> Operations manual for the stabilized tool-chain. **Read this before changing a
> helper, retrieval, or a closure.** Authored 2026-06-02 at the close of the
> stability/observability line (DX-2a/2b/2c + #3 fail-family audit + cohort
> audit). It standardizes *process*, not runtime behavior.

---

## 1. The three gates (run in this order)

| Gate | Command | What it proves | When |
|------|---------|----------------|------|
| **Deterministic gate** | `~/.radiomind-bench-venv/bin/python bench/end_to_end/regression_pack.py` | 16 behaviour categories (committers, suppressors, hints, SelfAnchor, JAB, skills, diagnostics) still pass. Fast, no ingest/LLM/benchmark. | **Every change.** Before and after. |
| **E2E gate** | `bench/end_to_end/target_pack.py` (answer=deepseek-v3.2/dashscope, judge=gpt-4o/openrouter) | A curated qid set still behaves end-to-end through the full ingest+answer+judge pipeline. Heavy (hours). | **Manual / authorized, after key-path changes only.** NOT in the default loop. |
| **Failure-path debugger** | `bench/end_to_end/diagnose_qid.py --qid <q> [--e2e-result <run.json>]` | *Where* a single qid fails: retrieval → helper proof → skill route → closure → final answer. | When a gate goes red, or to localize one qid. |

Rule of thumb: **regression_pack is the gate you must never skip; target_pack is
the gate you run on purpose; diagnose_qid is the microscope.**

### Environment (hard rules)
- Always use `~/.radiomind-bench-venv/bin/python` (py3.13). iCloud evicts
  in-project `.venv` symlinks; Homebrew py3.14 `pyexpat` is broken.
- Tests/probes must never pollute `~/.radiomind`. Sandboxes are
  `/tmp/rm-*`; pass `RADIOMIND_HOME=/tmp/...` for runs. `diagnose_qid` sandboxes
  itself under `/tmp/rm-diagnose-qid-<qid>`.

## 2. "Before you change X, run Y"

| You are changing… | First | After | Notes |
|-------------------|-------|-------|-------|
| A **helper** (hint or committer) | regression_pack | regression_pack; if ≥2-3 helpers accrued, a target smoke | New helper needs a pre-impl audit (trigger surface ≤3, same-item anchor alignment, deterministic-rejectable negative). |
| **Retrieval / reranker / window** | regression_pack | regression_pack + a target_pack run (retrieval is high blast-radius) | Confirm no PASS→FAIL on the e2e set before trusting a ranking change. |
| A **closure** (commit/suppress) | regression_pack | regression_pack | Respect the committer/suppressor boundary (§3). |
| A **skill** (routing/ordering) | regression_pack | regression_pack | OrderedEventList precision is PARKED (§4). |
| **diagnose / bench harness** | the relevant unit tests | regression_pack (diagnostics are gate categories) | Diagnostic-only changes never touch runtime. |

## 3. Closure / proof architecture boundaries

Two **opposite** closure families — do NOT merge them into one gate/abstraction
(an over-abstraction attempt in Phase-2 1a was rejected; no registry/dispatcher):

| Family | Members | Polarity | Shape |
|--------|---------|----------|-------|
| **COMMIT_ON_ABSTAIN** (committer) | cashback, age_interval | upgrade a *pure abstain* → a recomputed value | `commit_on_abstain(proof, llm_answer)` fires only when the answer is a pure abstain |
| **SUPPRESS_OVERCOMMIT** (suppressor) | role guard, temporal endpoint (TESG) | downgrade a *concrete overcommit* → abstain | rewrites a wrong concrete answer to abstain |

Key invariants (learned, not negotiable):
- **A committer only rescues abstains.** If the answer-LLM emits a *concrete
  wrong* value, `commit_on_abstain` never fires (that is the
  `concrete_wrong_bypassed_committer` mode — fixing it needs upstream hint-trust
  or a suppressor-shaped guard, not the committer). See c18a7dc8.
- **hint-only ≠ committer.** A hint (savings, person_age) only injects a prompt
  prefix; it has NO commit rescue. A bare abstain after a hint stays an abstain.
  See bb7c3b45 (savings is hint-only).
- **"closure_view ready" ≠ PASS.** `would_commit_on_abstain=true` means the
  committer *would* fire on an abstain — it says nothing about a concrete-wrong
  run. Verify with a fresh run, never assume.
- **absence-of-evidence ≠ negative-evidence.** A FACT miss must not become a
  factual assertion. Committers require *double* deterministic evidence.

### The proof carrier
- `src/radiomind/core/proof_result.py`: `ProofResult` / `Source` /
  `is_commit_abstain_candidate` / `commit_on_abstain`. Shared by cashback +
  age_interval committers only. Suppressors deliberately out.
- `SelfAnchor` / store-scan: supplements retrieval with an anchor probe; it is
  context, and must not by itself classify a failure unless a helper-specific
  proof confirms it.
- `closure_view` (in diagnose): projects both families with
  `would_commit_on_canonical_abstain` (committers) and detection/suppression
  what-ifs (suppressors). It is the decisive section for committer-vs-suppressor
  reasoning and only exists on current-build diagnose recs.

## 4. When a gate goes red — diagnose decision tree

1. **regression_pack red** → a behaviour regressed. The failing category names
   the test file; fix or revert. Never push past a red deterministic gate.
2. **target_pack red** → run
   `diagnose_qid.py --qid <q> --e2e-result <the-run.json>`. Read
   `path_summary.diagnosis.layer`:

| layer | meaning | direction |
|-------|---------|-----------|
| `pass` | e2e judged correct | nothing |
| `answer_or_judge_path` | proof ready / no infra error but answer wrong or abstained, OR `[answer error]` / judge fail | infra retry, or answer-LLM trust/prompt — NOT a logic gap |
| `concrete_wrong_bypassed_committer` | committer ready but answer is a concrete wrong value (not abstain) | upstream hint-trust or a suppressor-shaped guard |
| `proof_input_turn_missing` | a required anchor not found in retrieved turns (evidence turn out-ranked / not retrieved) | retrieval granularity/ranking — NOT an extraction-regex tweak |
| `helper_refusal` | a helper gate refused (trigger miss, etc.) | the named helper's gate |
| `retrieval_gap` | no gold sessions retrieved | retrieval breadth |
| `closure_ready` / `proof_ready` | deterministic layer ready (no e2e overlay) | overlay an e2e result to see the live outcome |
| `skill_route_gap` / `unknown` | DX needs more fields | improve the diagnostic, don't change business code |

Note a known DX limitation softened in DX-2c: the human `diagnosis.reason` is
driven by a refusal; DX-2c prefers a "missing-input" refusal over a generic one,
but for deep audits read `closure_view` + `helper_proofs[<relevant helper>]`
directly, not just the top label.

## 5. Parked directions — do NOT reopen without new evidence

| Direction | Why parked | Reopen if |
|-----------|-----------|-----------|
| **OrderedEventList precision** (1h name-canon/cardinality) | mechanics done through 1g; precision is curated-subset gold, diminishing returns | a real cohort of ordering qids with clean gold appears |
| **Quantitative-turn retrieval weighting** | cohort ≈ 1 (bb7c3b45); high blast-radius ranking change for ~1 qid | a stable cohort of "number turn out-ranked while gold session retrieved" emerges |
| **LME-S structural-floor families** (open-vocab cardinality, subjective preference, ordering) | ≈0% in all history; extractive-vs-preservative philosophy ceiling, not bugs | the architecture's preservation stance changes |
| **Local small models** (regex/MiniLM extractor/embedder) | abandoned; default to host/cloud LLM | n/a |
| **Adding more committers to chase tail score** | LME-S tail is many small distinct mechanisms, none cohort-large; lever is usually retrieval/trust, not closure coverage | a cohort audit shows a shared, sizable mechanism |

## 6. Where things live

- Gates: `bench/end_to_end/{regression_pack,target_pack,diagnose_qid}.py`
- Manifests: `target_pack.py` MANIFEST (required vs observe_only with `mode`)
- Proof: `src/radiomind/core/proof_result.py`,
  `arithmetic_hint.py` (cashback), `age_interval_commit.py`
- Audits / decisions: `projectBasicInfo/logs/2026-06-0*` (the 06-02 set:
  target-pack standard, DX-2a/2b/2c, #3 fail-family audit, probe results,
  cohort audit)
