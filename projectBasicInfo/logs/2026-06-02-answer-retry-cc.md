# AnswerRetry — answer-LLM outer retry (1a audit + 1b fix)

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Done. Closes the harness-robustness gap the target-pack v1 baseline
exposed (two required qids spuriously red from transient answer-LLM DNS).
Deterministic-test-covered + 1-qid live sanity. judge / helpers / closures
untouched.

---

## 1a — read-only finding (corrects the initial framing)
The gap is NOT "the answer call has no retry". `llm_call` (run_longmemeval_mem0.py)
**already** retries transient errors internally (`max_retries=3`, backoff 1/2/4s,
catches `HTTPError`(non-4xx) + `URLError`/`ConnectionError`/`TimeoutError`/`OSError`
— comment explicitly lists "dns failure"). Both answer and judge call `llm_call`.

The real asymmetry: the **judge** wraps `llm_call` in an ADDITIONAL outer
3-attempt loop (V8.2.2b, with its own 1/2/4s backoff) → up to ~3×3 attempts;
the **answer** call had only `llm_call`'s inner 3. So a DNS/network blip longer
than the answer's inner-retry window (~7s) exhausts it and emits
`[answer error: <urlopen [Errno 8] nodename nor servname>]`, while the judge's
extra outer loop rides it out. That is exactly what reddened bb7c3b45 +
c18a7dc8 in the target-pack v1 baseline.

## 1b — fix (symmetry with the judge)
- New `_answer_with_retry(ans_prompt, config_path, *, model, profile,
  max_tokens=1500, attempts=3)`: outer loop mirroring the judge —
  `strip_thinking(llm_call(...))` on success; on exception, set
  `[answer error: …]` and backoff (1s, 2s) before the next attempt; return the
  error string only after attempts exhaust. A persistent / non-transient
  failure therefore still surfaces as `[answer error: …]` (a real FAIL), never
  a fabricated answer.
- The runner's inline answer try/except is replaced by a single
  `answer = _answer_with_retry(...)` call. Happy path is byte-equivalent
  (first attempt → `strip_thinking(llm_call(...))`, same as before).
- **judge loop, helpers, closures, llm_call internals: unchanged.**

Caveat (acceptable, not a blocker): the outer loop catches all `Exception`
(mirroring the judge), so a non-transient error also waits out the 1–2
retries before surfacing. It never fabricates an answer — terminal result is
still `[answer error: …]`. A future refinement could narrow the outer catch
to the same transient set `llm_call` retries; not worth blocking this change.

## Verification
- `tests/test_answer_retry.py` (3, deterministic — monkeypatch `llm_call`,
  patch `time.sleep`): (1) transient `URLError` then success → retried once,
  answer returned, `strip_thinking` applied; (2) first-try success → 1 call,
  no retry; (3) persistent `URLError` → 3 attempts then `[answer error: …]`
  (surfaced, not swallowed).
- Added to the regression pack as `harness:answer-retry`. Full pack:
  **15 categories ALL PASS**.
- 1-qid live sanity (`9aaed6a3`, fresh sandbox): e2e **acc 1.000** (367s) —
  the refactored answer path produces a correct answer end-to-end.

## Effect on the target-pack
The transient infra failure mode that made the v1 baseline gate-red
(answer-LLM DNS) is now retried the same way the judge already was. A future
target-pack run is far less likely to spuriously red a required qid on a
network blip. (The alternative — `target_pack.py` auto-re-running
`[answer error: …]` qids — is no longer needed for this cause, but remains a
possible future belt-and-suspenders.)

## Files
- `bench/end_to_end/run_longmemeval_mem0.py` (`_answer_with_retry` + call site)
- `tests/test_answer_retry.py` (new)
- `bench/end_to_end/regression_pack.py` (+`harness:answer-retry` category)
- this log
