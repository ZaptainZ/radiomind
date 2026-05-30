# TrustClosure-1c — Cashback Commit Closure Verification (close-out)

**Date**: 2026-05-30
**Author**: Claude Code
**Status**: Verified. The 1b cashback commit closure is proven
deterministically on the real 9aaed6a3 haystack text; 5/5 e2e PASS with
no regression. Verification is NOT gated on catching a stochastic
abstain. No source change to the 1b closure; this cycle adds one
real-data test file + the environment fix below.

---

## Goal (from TrustClosure-1a/1b)

1b shipped `resolve_cashback_proof` + `maybe_cashback_commit_closure`
(commit `8bba0fd`) — the cashback analogue of the TSI-1d age closure.
1c had to verify: 9aaed6a3 PASSes stably, the abstain→$0.75 rescue
actually works on the real field data, and the negatives never fire.

## What was done

### 1. e2e smokes — 9aaed6a3 × 5 (tc1c r1–r5)
Baseline matches tc1a: answer=deepseek-v3.2/dashscope,
judge=gpt-4o/openrouter, `--qids 9aaed6a3`, sandbox `/tmp/rm-sandbox-tc1c-r*`.

| run | correct | answer | pure_abstain | cashback_hint |
|---|---|---|---|---|
| r1 | ✅ | `$0.75` | False | True |
| r2 | ✅ | `$0.75` (store_scan) | False | True |
| r3 | ✅ | `You earned $0.75 in cashback from your SaveMart purchase…` | False | True |
| r4 | ✅ | `You earned $0.75 in cashback at SaveMart.` | False | True |
| r5 | ✅ | `You earned $0.75 in cashback at SaveMart last Thursday.` | False | True |

**5/5 PASS, abstention_rate 0.0** (vs tc1a ~1/3 abstain). Crucially, in
all 5 the LLM **committed on its own** (`answer_pure_abstain=False`),
so the closure correctly stayed dormant — i.e. these runs prove the
runner wiring is intact and the closure never corrupts a concrete
answer, but they did **not** naturally exercise the abstain→rewrite
path (that event is stochastic on the model and did not recur this
batch). The varied natural phrasings (r3/r4/r5) are the LLM's own,
not the closure template.

### 2. Deterministic real-data proof (the actual 1c gate)
Rather than burn long runs waiting for a random abstain, the rescue is
proven deterministically against the **verbatim** 9aaed6a3 haystack
sentences (from `longmemeval_data/longmemeval_s_cleaned.json`):

- `"I went grocery shopping at SaveMart last Thursday and spent $75 on my purchase."`
- `"By the way, SaveMart has this loyalty program where you get 1% cashback on all your purchases."`

New file `tests/test_cashback_closure_field_9aaed6a3.py` (4 tests):
- `resolve_cashback_proof` on the real text → merchant=SaveMart,
  amount=75.0, rate=0.01, product=$0.75, rate_source_turn_id set.
- pure canonical abstain + real text → rescued to
  `"You earned $0.75 in cashback at SaveMart."`
- concrete answer never overwritten (the path the 5 e2e runs took).
- store-scan supplies the rate when retrieve lacks it (the
  SelfAnchor-2b run11 trust-gap shape) → still $0.75.

This closes the "did the hand-authored fixtures match reality?" gap:
the parsers cope with the real, looser phrasing.

### Evidence chain
- **Field trust-gap is real**: SelfAnchor-2b run11 + tc1a r2 captured
  `hint_emitted=True + LLM abstain` on 9aaed6a3.
- **Parsing works on real data**: tc1c runner telemetry
  (`cashback_telemetry`) independently confirms merchant/amount/rate
  parse from the genuine haystack.
- **Rescue is deterministic**: the real-data unit tests prove that
  whenever the trust-gap recurs, the closure recomputes and commits
  $0.75 — and stays dormant otherwise.

## Test results
- Closure suite: **19/19 pass** (15 existing 1b + 4 new 1c), 0.40s.
- Full repo suite in the rebuilt bench venv: 199 passed / 23 failed /
  47 errors — **all failures are missing-optional-dep import errors**
  (sentence_transformers ×18, onnxruntime ×9, requests ×8, httpx ×5,
  mlx_lm ×2, …), none related to the closure or this change. The 1b
  "162/162 helper suite" figure was measured in the original full-dep
  environment.

## Environment fix (blocking, resolved)
The bench environment was broken and had to be rebuilt before any run:
- Homebrew `python@3.14.4` has a broken `pyexpat`
  (`Symbol not found: _XML_SetAllocTrackerActivationThreshold` vs
  system libexpat) → `pip` itself fails; the project `.venv` (built on
  3.14) was dead.
- Rebuilt `.venv` with healthy `python3.13` worked at first, but the
  venv lives **inside the iCloud-synced project dir**
  (`~/Library/Mobile Documents/com~apple~CloudDocs/…`); iCloud evicted
  the `.venv/bin/python` symlink to dataless mid-run, so long runs
  failed with `No such file or directory` after the precheck passed.
- **Fix**: bench venv now lives on local disk at
  `~/.radiomind-bench-venv` (python3.13 + `pip install -e .`), immune to
  iCloud eviction. Runner must be launched with that interpreter.
- Also fixed a non-blocking SessionStart hook error: `.claude/settings.json`
  used an unquoted `$CLAUDE_PROJECT_DIR` (path has spaces) → quoted it.

## Files
- `tests/test_cashback_closure_field_9aaed6a3.py` (new, 4 tests)
- `bench/end_to_end/tc1c-9aaed6a3-r{1..5}.json` (e2e telemetry)
- `.claude/settings.json` (hook quoting fix)
- No change to `src/radiomind/core/arithmetic_hint.py` or the runner.

## Conclusion / next
1b cashback closure is verified and closed. The closure family now has
four implemented contracts with real verification experience:
role (`maybe_rewrite_with_guard`), temporal
(`maybe_rewrite_with_temporal_guard`), age
(`maybe_age_interval_commit_closure`), cashback
(`maybe_cashback_commit_closure`). **Phase 2 registry** — a unified
`ProofResult -> commit_closure` contract — now has enough material to
abstract, and is the natural next step. Not started here.
