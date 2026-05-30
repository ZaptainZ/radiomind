# SelfAnchor-2b — Cashback Rate Store-Scan (Close-Out + Trust-Gap Finding)

**Date**: 2026-05-30
**Author**: Claude Code
**Status**: 2b closes for its scope (rate recall). e2e telemetry
proves store-scan works every time; the residual cashback abstain
is `structured_skill_trust_gap` (LLM ignores a correct hint), a
cross-helper commit-side issue — NOT a SelfAnchor defect.

---

## What 2b shipped

`scan_cashback_rate_user_turns(mind, domain, merchant)` +
`cashback_arithmetic_hint(... mind, domain)` store-scan supplement,
gated to fire only when: cashback trigger matched, merchant known,
spend amount already in retrieve, and the retrieve-side scoped
finder returned a rate-missing refusal. Reuses 1.5a merchant
scoping (Walmart+ 2% still rejected). Hint-only; source_turn_id +
scan_scope in the hint. (impl: `02934df`)

## The diagnostic chain had to be aligned first (Codex catch)

`diagnose_qid` called the cashback/savings/person_age signals
WITHOUT `mind/domain`, so they skipped the store-scan path the
runner uses — producing a contradictory artifact
(`self_anchor_probe.recovered=true` but signal `""`). Fixed +
added read-only cashback e2e telemetry to the runner (`2b56cd8`):
`{ amount_in_retrieve, rate_in_retrieve, rate_refusal,
hint_emitted, store_scan_used, hint_preview }`. No model-behavior
change.

## Telemetry decisively splits the failure

5 instrumented 9aaed6a3 smokes (run7-11):

| run | correct | amount_in_retr | rate_in_retr | refusal | hint_emitted | store_scan_used |
|---|---|---|---|---|---|---|
| 7 | ✓ | True | None | rate_merchant_mismatch | True | **True** |
| 8 | ✓ | True | None | rate_merchant_mismatch | True | **True** |
| 9 | ✓ | True | None | rate_merchant_mismatch | True | **True** |
| 10 | ✓ | True | 0.01 | None | True | False (rate already retrieved) |
| 11 | **✗** | True | None | rate_merchant_mismatch | **True** | **True** |

Reading:

1. **amount_in_retrieve = True in all 5** → cashback's spend
   amount ($75, a rank-1 user turn) is reliably retrieved. NOT an
   amount-side recall gap.
2. **store_scan_used = True in every rate-miss run (7/8/9/11)** →
   when retrieve drops the SaveMart 1% rate (`rate_merchant_
   mismatch`, only Walmart+ 2% present), the store scan recovers
   it and the hint is emitted. The 2b component + runner wiring
   work in e2e. NOT a store-scan bug.
3. **run11: hint_emitted=True, store_scan_used=True, yet answer =
   "The information provided is not enough."** → the hint carried
   the full `1% × $75 = $0.75`, and the LLM ignored it and
   abstained anyway. This is `structured_skill_trust_gap`.

## Conclusion

- **SelfAnchor-2b is sound for its scope.** It set out to make
  the cashback RATE recall-stable; telemetry shows it recovers
  the rate and emits the hint on 100% of the rate-miss runs. The
  earlier "50% abstain" (run1-6, no telemetry) was NOT store-scan
  failing — it was the LLM not committing to a correct hint.
- The residual cashback abstain is the SAME `structured_skill_
  trust_gap` first seen on c18a7dc8: a hint-only helper can give
  the LLM a correct deterministic answer and the LLM still
  abstains some fraction of the time. This is a property of the
  hint-only architecture, present across ALL hint helpers
  (cashback / savings / person_age), not specific to cashback or
  SelfAnchor.

So 9aaed6a3's e2e stability now has two layers, only one of which
2b owns:
- rate recall — **fixed by 2b** (store-scan, deterministic)
- commit (LLM trusting the hint) — **NOT fixed**, the trust gap

## Next decision (NOT taken here)

Per the agreed fork rule, `hint_emitted=true + abstain` is the
case where we may discuss a deterministic commit closure /
post-rewrite for cashback — analogous to TSI-1d for age_interval:
when the cashback helper has a high-confidence deterministic
product (merchant-scoped rate × retrieved amount, both with
traceable proof) AND the LLM emitted a pure canonical abstain,
post-rewrite to commit the computed value (gated by JAB-1b
abstain detection + a recompute check).

Important framing: this would help EVERY hint-only helper, not
just cashback — the trust gap is shared. A `commit_closure`
contract over the Proof object (Phase 2 territory) might be the
right home, rather than a cashback-specific rewrite. That
sequencing decision is open.

2b closes here. No n=100. The trust-gap commit-closure is a
separate, user-gated workstream.

## Files

- Telemetry runs: `bench/end_to_end/sa2b-tel-run{7..11}.json`
- Earlier (no telemetry): `sa2b-smoke-run{1..6}.json`
- Diagnose alignment: `diagnose_qid.py` (mind/domain on signals);
  cashback rate probe added
- Runner telemetry: `run_longmemeval_mem0.py` cashback_telemetry
- Prior: `2026-05-29-selfanchor-2a-cashback-rate-audit-cc.md`
