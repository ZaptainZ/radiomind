# Diagnostic UX Standard Output — Read-Only Audit

**Date**: 2026-06-02
**Author**: Codex
**Status**: Read-only audit complete. No code changes to runtime or diagnostics.

---

## Goal

Define the next `diagnose_qid.py` improvement after the proof-aware
`closure_view` work: a standard failure-location output that can answer, in
one pass, where a qid failed:

`retrieval -> helper proof -> skill route -> closure decision -> final answer`

The goal is not to add new skills or run benchmarks. It is to make existing
diagnostic data easier to read and compare.

## Current State

`bench/end_to_end/diagnose_qid.py` already captures most raw material:

- `ingest_stats`
- `retrieve_window` and `retrieve_top_30_preview`
- `helper_signals`
- `helper_proofs` with refusal reasons for savings, cashback, person_age, and
  age_interval
- `self_anchor_probe`
- `store_anchor_probe`
- `structured_skill_section`
- `jab_what_if`
- `closure_view`

The important Phase 2 addition is `closure_view`, which preserves the two
opposite closure families:

- committers: cashback and age_interval, with ProofResult projections and
  `would_commit_on_canonical_abstain`
- suppressors: role and temporal endpoint, with detection and overcommit
  suppression what-ifs

## Problem

The current diagnostic is a set of useful sections, not a path. A human still
has to mentally join these questions:

1. Did retrieval surface the necessary evidence?
2. Did a helper or skill have enough proof?
3. If not, which refusal reason was decisive?
4. If yes, would the closure rewrite a pure abstain or suppress an overcommit?
5. If the real e2e answer failed, was it an answer-LLM/judge issue outside the
   deterministic layer?

That is workable for deep audits, but too slow for the target use case:
post-regression triage in minutes.

## Proposed Standard Output

Add a derived, read-only `path_summary` field to the JSON and human summary.
It should not replace existing raw sections; it should summarize them.

Suggested JSON shape:

```json
{
  "path_summary": {
    "qid": "9aaed6a3",
    "retrieval": {
      "gold_hits_top_200": 3,
      "gold_hits_top_30": 1,
      "likely_issue": null
    },
    "deterministic_layer": {
      "fired": ["cashback"],
      "refused": [
        {"helper": "savings", "reason": "no_trigger_match"}
      ],
      "proofs_available": ["cashback"]
    },
    "skill_route": {
      "temporal_precision": "silent",
      "open_domain_specific": "silent",
      "list_ordering": "not_probed"
    },
    "closure_decision": {
      "committers": {
        "cashback": {
          "proof_available": true,
          "would_commit_on_abstain": true,
          "would_overwrite_concrete": false
        },
        "age_interval": {"proof_available": false}
      },
      "suppressors": {
        "role": {"detected": false},
        "temporal_endpoint": {"detected": false}
      }
    },
    "diagnosis": {
      "layer": "closure_ready",
      "reason": "cashback proof is complete; if e2e abstains, this is a trust-gap or answer-path issue"
    }
  }
}
```

Human output should be one compact block before detailed sections:

```text
PATH SUMMARY
  retrieval: gold 3/200, 1/30
  deterministic: cashback proof ready ($0.75), savings refused no_trigger_match
  skill route: none
  closure: cashback would commit on pure abstain; no suppressor fires
  diagnosis: closure_ready
```

## Layer Classification Rules

Use conservative labels. Do not infer more than the captured evidence proves.

Recommended `diagnosis.layer` values:

- `retrieval_gap`: required evidence exists in store/probes but not retrieved.
- `helper_refusal`: trigger matched but helper refused, with a decisive
  `refusal_reason`.
- `proof_ready`: helper proof exists but no closure applies because the line is
  hint-only.
- `closure_ready`: committer/suppressor proof is ready and would act on the
  appropriate answer polarity.
- `skill_route_gap`: a known routed skill should apply but no route/section is
  present.
- `skill_precision_gap`: routed skill fires but output is incomplete or
  imprecise, e.g. OrderedEventList 1g.
- `parked_or_deferred`: qid belongs to an intentionally parked line.
- `answer_or_judge_path`: deterministic layer looks ready, but saved e2e
  failure came from answer error, judge error, or answer-LLM ignoring a hint.
- `unknown`: insufficient evidence.

## Gaps Before Implementation

1. `diagnose_qid.py` does not currently run or display `run_list_ordering`.
   OrderedEventList has its own path in `mind.run_list_ordering`, but the
   diagnostic only probes temporal precision and open-domain specific routes.
   If the standard output claims to cover `skill route`, list ordering needs a
   read-only probe.

2. The diagnostic does not accept a saved e2e result artifact. Therefore it
   cannot directly compare deterministic readiness with the actual final
   answer. A useful optional flag would be:

   ```text
   --e2e-result bench/end_to_end/target-pack-result.json
   ```

   Then `path_summary.final_answer` can distinguish:
   - deterministic proof ready + final answer error string
   - deterministic proof ready + pure abstain
   - suppressor ready + concrete overcommit
   - judge failure

3. `helper_signals` are raw strings. The standard summary should prefer
   `helper_proofs` and `closure_view`, using raw signals only as fallback.

4. `store_anchor_probe` is generic and sample-capped. It is useful context, but
   should not by itself classify a failure unless a helper-specific proof or
   self-anchor probe confirms the missing anchor.

## Recommended Implementation Slice

Implement this in two small steps:

### DX-2a: Standard path summary, no e2e artifact

- Add pure function `build_path_summary(rec) -> dict`.
- Add `_print_path_summary(summary)`.
- Include retrieval, helper proof/refusal, self-anchor, structured skill, and
  closure readiness.
- Add deterministic tests using synthetic `rec` dicts.
- No ingest, no LLM, no runner behavior change.

### DX-2b: Optional e2e-result overlay

- Add `--e2e-result <json>` to load a saved runner artifact.
- If the qid is present, include `final_answer`, `correct`, `judge_failed`,
  and `helper_hints` in `path_summary`.
- Classify answer-path issues such as `[answer error: ...]` separately from
  helper/closure failures.

## Decision

Proceed with DX-2a first. It is low risk and turns existing diagnostic sections
into a triage path without changing runtime behavior. DX-2b is valuable after
DX-2a because target-pack failures are exactly where final answer overlay pays
off.

Do not add new helper logic, new closures, or a dispatcher in this workstream.

