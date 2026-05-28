# Post-SavingsHint Remaining-Fail Audit

**Date**: 2026-05-28
**Author**: Claude Code
**Status**: Read-only. No implementation. NO n=100. Two
qids audited (`b46e15ed`, `gpt4_d6585ce8`); preference and
entity-norm directions remain out of scope per user
direction.

---

## b46e15ed — Event-Cluster Interval

Question: "How many months have passed since I participated
in two charity events in a row, on consecutive days?"
Gold: `2`.

### Cohort scan

LME-S 500 scanned for trigger patterns `consecutive | in a
row | back to back` AND `how long/how many ... since`.

**Result: 2 qids match.**

| qid | shape | gold |
|---|---|---|
| `d3ab962e` | "What is the total distance of the hikes I did on **two consecutive weekends**?" | 8 miles |
| `b46e15ed` | "How many months have passed since I participated in **two charity events in a row, on consecutive days**?" | 2 |

`d3ab962e` is an **aggregate-sum-of-distances** shape, NOT
the elapsed-since-cluster shape. The two questions share
the surface word "consecutive" but require completely
different operators.

**Conclusion**: b46e15ed's `event_cluster_interval_shape_gap`
remains a **single-qid** shape. LSA-3's defer
recommendation stands. No cohort to justify implementation.

### Recommendation

Hold defer. No further action on b46e15ed unless a future
LME-S re-sample surfaces another elapsed-since-cluster
qid.

## gpt4_d6585ce8 — Ordered-Event Sequence

Question: "What is the order of the concerts and musical
events I attended in the past two months, starting from
the earliest?"

Gold lists 5 events in chronological order:
1. Billie Eilish concert (Wells Fargo Center, Philly)
2. Free outdoor concert series in the park
3. Music festival in Brooklyn
4. Jazz night at a local bar
5. Queen + Adam Lambert (Prudential Center, Newark)

### Evidence-chain audit

5 gold sessions, 1:1 session-to-concert mapping:

| session_date | event mentioned | attendance marker |
|---|---|---|
| 2023-03-18 | Billie Eilish (Wells Fargo Philly) | "got back from" |
| 2023-03-25 | Free outdoor concert series | "I attended" |
| 2023-04-01 | Music festival in Brooklyn | "just got back from" |
| 2023-04-08 | Jazz night at local bar | "had such a great time at" |
| 2023-04-15 | Queen + Adam Lambert (Prudential Newark) | "just saw them live" |

Gold's order == ASCENDING session_date order. The
session_date metadata is reliable for chronological sort.

### Cohort scan

LME-S 500 scanned for ordering-question trigger
(`what is the order | in what/which order | chronological(ly) | sequence of`).

**Result: 7 qids — a meaningful cohort.**

| qid | shape | event type |
|---|---|---|
| `gpt4_7f6b06db` | 3 trips, earliest to latest | trip |
| `gpt4_18c2b244` | 3 specific events (reward signup / coupon / ...) | mixed |
| `gpt4_7abb270c` | 6 museums, earliest to latest | museum visit |
| `gpt4_45189cb4` | sports events in January | sports |
| `gpt4_e061b84f` | 3 sports events in past month | sports |
| **`gpt4_d6585ce8`** | **concerts in past 2 months** | **concert** |
| `gpt4_f420262c` | airlines flown, earliest to latest | airline |

This is structurally a **structured skill family** — 7
qids of the same operator shape (sort attended events by
date). Architecturally interesting.

### Where the deterministic operator can stand

The sort step is trivially deterministic:
`sort_by(session_date, ascending)`. The hard step is
**event extraction**:

1. Each qid uses a DIFFERENT event type
   (concert / trip / museum / sports / airline / mixed).
2. Within a haystack, multiple sessions may mention the
   same event repeatedly; dedup needed.
3. First-person past-tense attendance filter required to
   exclude future-tense planning ("thinking of attending")
   and third-party mentions ("my sister's concert").
4. Date scope filter: "past N months" requires
   question_date arithmetic.

Steps 1–4 are NOT trivially regexable across all 7 qids —
each event type has its own attendance verbs ("attended /
visited / flew with / saw / went on / participated in")
and its own entity-norm risks.

### Observation from n=100 baseline

Looking at the new baseline artifact (gpt4_d6585ce8 fail):
the LLM DID extract the 5 events and DID attach dates to
them, but produced the wrong order (started with the
outdoor concert at March 25 instead of Billie Eilish at
March 18). So the LLM has the raw data; it just doesn't
reliably sort.

This suggests a **deterministic-sort-only hint** could
help WITHOUT requiring new entity-extraction architecture:

- Identify which retrieved memories the LLM is using as
  the per-event source (this is the question of which
  memories pass first-person past-tense attendance
  filtering — non-trivial).
- Surface them in session_date ascending order as a
  prompt prefix.
- Hint-only, no commit override.

But this still requires the attendance-filter step, which
is the same open-vocab risk Codex flagged.

### Recommendation

**Hold defer for now**, but mark this as the cleanest
remaining candidate among the deferred fails:

- Cohort size (7) is meaningful — unlike b46e15ed (1) or
  the preference-advice family.
- Sort step is deterministic via session_date.
- Extraction step is NOT yet deterministic; requires
  either:
  - per-event-type attendance verb list + entity-norm
    (open-vocab risk, may degenerate into regex stacking)
  - OR a typed event_attended skill (architectural; out
    of scope for narrow helper)

A future workstream could open `OrderedEventList-1a`
audit to:
1. Hand-trace the 7 qids' attendance-marker phrases.
2. Test whether a small closed verb set
   (`attended | went to | visited | flew with | saw | took`)
   covers all 7 with low false-positive rate.
3. If yes, prototype a narrow hint that emits
   `[session_date] event_phrase` list sorted ASC.
4. If extraction is brittle, defer to typed-event
   architecture.

Not opening this workstream now per user's direction (no
new narrow-helper implementation until current closures
stabilize).

## Final Tally of Remaining Fails

After SavingsHint (expected +1 on bb7c3b45) lands, the
known-fail set on the current main against the V8.2.2a
n=100 sample is:

| qid | label | scope |
|---|---|---|
| `1c0ddc50` | preference advice | out (subjective; judge-elastic) |
| `d6233ab6` | preference advice | out |
| `gpt4_194be4b3` | instruments entity norm | out (open-vocab) |
| `gpt4_ab202e7f` | kitchen items entity norm | out (open-vocab) |
| `b46e15ed` | event_cluster_interval_shape_gap | **single-qid, defer confirmed** |
| `gpt4_d6585ce8` | ordered_event_sequence | **cohort=7, candidate for future workstream `OrderedEventList`** |

3 out-of-scope (preference + entity-norm), 2 confirmed
defers, 1 candidate for future structured-skill workstream
that requires more architectural investment than a narrow
helper.

**No n=100 rerun planned.** Per Codex's earlier guidance:
the +1 from SavingsHint is within stochastic band, and
n=100 won't validate the architectural value of a 1-qid
helper. Wait until at least 2–3 more target closures
accumulate before re-measuring.

## Files

- This log: `projectBasicInfo/logs/2026-05-28-post-savings-remaining-fail-audit-cc.md`
- Related:
  - LSA-3 (event_cluster_interval_shape_gap origin):
    `projectBasicInfo/logs/2026-05-25-lsa3-existing-path-audit-cc.md`
  - SavingsHint-1a audit:
    `projectBasicInfo/logs/2026-05-28-savings-hint-1a-audit-cc.md`
  - n=100 baseline: `projectBasicInfo/logs/2026-05-28-lme-s-n100-jab-protected-baseline-cc.md`
