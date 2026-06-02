# #3 LME-S Fail-Family Audit (read-only, HISTORICAL stability map)

**Date**: 2026-06-02
**Author**: Claude Code
**Status**: Read-only attribution. No code change, no fix workstream opened.
**Scope caveat (important):** this is a **historical cross-run stability map,
NOT a current-main failure inventory.** The 13 artifacts below span
pre-fix / post-fix / judge-fixed / FINAL builds, so a per-qid pass-rate here
describes *how jittery that qid has been across the project's history*, not
"what main fails today". To get a current-main fail list you must run a fresh
n=100 on HEAD; that is deliberately NOT done here.

---

## Artifact set (single consistent set — 13 LME-S n=100 runs)

Selected by: contains the LME-S anchor qid `c18a7dc8`, 90-110 `per_query` rows,
excluding checkpoints and locomo. All 13:

```
lme-s-FINAL-gpt4o-n100.json            lme-s-n100-v4-deepseek-judge4o.json
lme-s-deepseek-judge4o-n100-v2.json    lme-s-n100-v5-deepseek-judge4o.json
lme-s-deepseek-judge4o-n100.json       lme-s-n100-v6.1.1-deepseek-judge4o.json
lme-s-n100-2026-05-26.json             lme-s-n100-v6.2.2-deepseek-judge4o.json
lme-s-n100-post-refactor.json          lme-s-v82-1-n100.json
lme-s-n100-v3-deepseek-judge4o.json    lme-s-v822a-n100.json
                                       lme-s-v822a-n100.judge-fixed.json
```

All pass-rates below are computed on **this one set** (denominator = number of
those 13 runs in which the qid appears; `gpt4_`-prefixed / newer qids appear in
fewer runs, shown as actual n).

## Chronic failers (historical pass-rate ascending)

| pass-rate | qid | qtype | family |
|-----------|-----|-------|--------|
| 0% (0/13) | gpt4_ab202e7f | multi-session | A: open-vocab cardinality |
| 0% (0/13) | d6233ab6 | single-session-preference | A: subjective preference |
| 0% (0/8) | gpt4_d6585ce8 | temporal | A: OrderedEventList ordering |
| 0% (0/5) | 370a8ff4 | temporal | B: multi-hop temporal count |
| 0% (0/5) | gpt4_59149c78 | temporal | B: relative-time anchored recall |
| 20% (1/5) | 6e984301 | temporal | B: interval count |
| 38% (5/13) | bb7c3b45 | multi-session | C: savings (hint-only) |
| 38% (5/13) | c18a7dc8 | multi-session | C: age_interval (committer) |
| 38% (5/13) | b46e15ed | temporal | B: event_cluster_interval (deferred) |
| 40% (2/5) | gpt4_f420262c | temporal | A/B: airline ordering (omits item) |
| 46% (6/13) | d851d5ba | multi-session | C: NAR charity sum |
| 46% (6/13) | gpt4_93159ced_abs | temporal | C: TESG suppressor |
| 54% (7/13) | 778164c6 | single-session-assistant | C: assistant-turn recall |
| 54% (7/13) | 95228167 | single-session-preference | A: subjective preference |
| 62% (8/13) | 031748ae_abs | knowledge-update | C: role suppressor |

## The three families

### Family A — structural / philosophical floor (≈0% across all history)
Open-vocab entity cardinality (gpt4_ab202e7f 0/13), subjective preference
(d6233ab6 0/13, 95228167 54%), OrderedEventList ordering precision
(gpt4_d6585ce8 0/8, gpt4_f420262c 40%). These essentially never pass in any
historical build. They are the lines already PARKED / deliberately excluded
from the target-pack, and match the MEMORY note: *gap to Mem0 is extractive-vs-
preservative architectural philosophy, not quality.* **No action** — ceiling,
not bug.

### Family B — temporal multi-hop, uncovered capability (0-40%)
nth-event resolution + interval arithmetic (370a8ff4 "weeks since flu at 10th
jog" 0/5, 6e984301 "weeks of classes at tool purchase" 20%), relative-time
anchored entity retrieval (gpt4_59149c78 "event two weeks ago — where?" 0/5,
answers wrong entity), event-cluster interval (b46e15ed 38%, deferred).
No committer/hint covers these; they need multi-hop temporal resolution
(resolve the *nth* / *relative-time* event, then compute). Genuinely hard;
**candidate capability line only if a temporal workstream is ever opened.**

### Family C — intermittent: capability exists, fails on retrieval/trust jitter
age_interval (c18a7dc8 38%), NAR sum (d851d5ba 46%), savings (bb7c3b45 38%),
assistant recall (778164c6 54%), suppressors TESG/role (46-62%). The logic is
present (passing unit tests + passes e2e a third-to-half the time). This is the
historical-jitter band — the **realistic headroom**, IF a fresh current-main
run confirms these still flip.

## Key finding — the lever is retrieval reliability, NOT "add a committer"

Committer-vs-hint contrast on the same consistent 13-set **refutes** the
tempting fix:

| line | kind | pass-rate (same 13-set) |
|------|------|--------------------------|
| cashback | committer | 77% (10/13) |
| person_age | hint-only | 85% (11/13) |
| savings | hint-only | 38% (5/13) |
| age_interval | **committer** | 38% (5/13) |

A commit-on-abstain closure does **not** explain pass-rate: the age_interval
*committer* sits at 38% while the person_age *hint* sits at 85%; the cashback
*committer* (77%) is no higher than the person_age *hint* (85%). So promoting
savings to a committer would NOT reliably fix bb7c3b45. The real differentiator
is **whether that qid's proof inputs are reliably retrieved into the answer
window**, plus whether the answer-LLM trusts them. age_interval's 6 answer-
independent gates often can't be satisfied from the retrieved window
(graduation date + current-date across distant sessions); person_age's single
evidence is reliably retrieved.

Consistent with the **第四律 (Attention / retrieval-side)** memory: remaining
headroom is a retrieval-attention problem for multi-hop proof inputs, not a
closure-coverage problem. AnswerRetry fixed only infra DNS errors; it does not
address proof inputs missing from the window, nor answer-LLM distrust of
present-but-scattered evidence.

## Conclusion (no fix opened, per "或者先停")

1. The historical 0.9x band is bounded below by Family A (structural floor) —
   parked by design, not actionable.
2. Family B (temporal multi-hop) is the largest *uncovered* capability but is
   hard and out of current scope.
3. Family C is the realistic headroom IF a current-main run reproduces the
   jitter — but the lever is **retrieval reliability of multi-hop proof
   inputs**, not more committers.

## Suggested next probe (read-only, authorized separately)
Pick a concrete *failing* historical artifact for each and run DX-2b overlay:
```
diagnose_qid.py --qid c18a7dc8 --e2e-result <a-run-where-c18a7dc8-failed>.json
diagnose_qid.py --qid bb7c3b45 --e2e-result <a-run-where-bb7c3b45-failed>.json
```
DX-2b will classify each as `retrieval_gap` (proof inputs absent) vs
`answer_or_judge_path` (present but distrusted). That single read-only check
decides whether the headroom is a retrieval fix or a trust/prompt fix — before
any workstream is opened. (Note: this still requires ingest for the
deterministic probe sections; authorize separately.)
