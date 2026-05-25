# LCO Stable-FAIL Audit — Round 1 (c2 financial + c5 Voyageurs)

**Date**: 2026-05-25
**Author**: Claude Code
**Type**: Read-only audit. **No code changes.** No new helpers.
**Inputs**: `sc3-locomo-flip10-run1` sandbox (NAR-on baseline,
already-ingested), LoCoMo dataset.

Per Codex's audit template, each qid gets four-column verdict:

1. gold-bearing memory in top-K?
2. prompt-side evidence sufficient?
3. error layer (retrieve / extract / skill / commit / out-of-scope)?
4. narrow-trigger deterministic fix path?

The two "stable FAIL" qids audited here:

| qid | question | gold |
|---|---|---|
| `c2_29183ecb5e` | What might John's financial status be? | Middle-class or wealthy |
| `c5_dac00a436e` | Which national park could Audrey and Andrew be referring to in their conversations? | Voyageurs National Park |

---

## c2_29183ecb5e — "John's financial status"

**Gold evidence**: D5:5 (John speaking to Maria, 28 Jan 2023): _"It's
definitely isn't, Maria. My kids have so much and others don't. We
really need to do something about it."_

The gold answer "Middle-class or wealthy" is an inference: "my kids
have so much" implies the family is not struggling.

### Audit

1. **D5:5 in top-K?** NO. D5:5 is present in the pyramid store
   (sqlite probe confirms 1 hit on "kids have so much"), but
   does NOT appear in top-30 retrieve for query "What might
   John's financial status be?".

2. **prompt-side evidence?** INSUFFICIENT. Top-14 retrieved
   memories are dominated by negative-financial signals that
   share lexical surface with the query word "financial":
   - D28:3 "It's been tough but I'm trying to stay up"
   - D28:5 "may have found a job at a tech company"
   - D14:14 "that's rough" (after car repair complaint)
   - Earlier D14 / D15 turns about "putting a strain on my wallet"
   - D28:1-7 about "lost my job"
   With only this evidence visible, the LLM (correctly given
   the prompt) commits to "financial difficulties / strain /
   unstable" answers. We saw the same in all 6 LCR runs.

3. **Error layer**: **RETRIEVAL** layer. The store has the
   gold-bearing turn, but the retrieve scorer can't bridge
   "financial status" (query) ↔ "my kids have so much" (gold).
   No lexical overlap, no obvious embedding bridge (different
   topical fields: "financial" vs "kids/family lifestyle").
   Atomic decomposition / cardinal view / typed-event helpers
   are not in scope here — the LLM never sees the relevant
   memory at all.

4. **Narrow deterministic fix path?** NO clean one.
   - Lexicon-expand the query ("financial" → also retrieve on
     "lifestyle / well-off / struggling / kids have / can
     afford / wealthy / poor / can't afford") would be
     fuzzy-LLM-ish, not deterministic.
   - Query decomposition into sub-queries each with different
     focus (financial-related, lifestyle-related, mention-of-
     possessions-related) is exactly the V6.x "atomic
     decomposition" direction; that path has been explored
     before and is more LLM-heavy than NAR-style.
   - A regex/keyword "wealth indicator" classifier at ingest
     time (turns containing _"have so much" / "can afford
     anything" / "vacation home" / "kids go to private school"_)
     is in principle possible, but the surface vocabulary is
     too open-ended to make a tight, generalizing regex.
   - This question's failure mode is "the inference link is in
     a topically-distant memory the retriever can't reach by
     lexical or embedding match alone." Not a NAR-shape problem.

### Verdict

**No narrow deterministic fix.** The right intervention is at
the retrieval layer (query expansion / multi-aspect
decomposition); that direction is LLM-heavy, not narrow.

But: the repo already has a generic LLM-heavy retrieval path
(`agentic_search` in `src/radiomind/storage/agentic.py`,
exposed by `run_locomo_mem0.py --benchmark-mode max`). Before
fully deferring this qid, a single-qid bounds experiment is
worth running: does the existing `--benchmark-mode max` path
pull D5:5 into top-K and shift the answer toward "middle-class
or wealthy"? Two outcomes:

  - YES on both → c2 is a "default path doesn't activate an
    already-available capability" issue, not a missing
    capability. The decision about whether to change the
    default activation is a separate (and load-bearing)
    question; this audit does not pre-commit to it.
  - NO → c2 stays as "no narrow fix, and the existing generic
    path also can't reach it", and we genuinely defer.

We are NOT proposing to enable `--benchmark-mode max` as the
new default based on a single-qid result; the experiment is
diagnostic only.

### Bounds experiment outcome (2026-05-25)

Ran `--benchmark-mode max` (activates `agentic_search`) on
c2_29183ecb5e alone. Sandbox `/tmp/rm-lco-c2-agentic/`,
`bench/end_to_end/lco-c2-agentic.json`, 1267s.

  - Decomposition produced 4 sub-queries, all in the financial
    semantic field: "John's financial situation",
    "John's income or salary", "John's debt or expenses",
    "John's savings or investments".
  - D5:5 ("my kids have so much") is **NOT** in agentic top-27
    either. Closest related rank-12 turn (D31:17, "family is
    awesome... times are hard...") still doesn't carry the
    positive-lifestyle inference the gold relies on.
  - LLM answer still commits to "financial difficulties":
    correct=false. Same failure mode as default a2a-practice.

**Verdict**: in the one max-path run observed today, the
agentic decomposition produced 4 financial-keyword sub-queries
and D5:5 did NOT surface in agentic top-27. Because the LLM-
driven decomposition is stochastic, this single run is NOT a
capability theorem about agentic_search; it is one observation
showing that, on today's deepseek-v3.2 decomposition, the
"kids have so much" → "wealthy" inference path was not
explored. This is enough to drop implementation work on
c2_financial in this round.

The architectural gap this exposes (decomposition expands
within the query's topical field but not toward reverse-
inference evidence categories) is genuine and worth a
separate methodology workstream — but should not be chased
single-qid, and not within LCO.

**Deferred.** No further work on c2_financial in this round.

---

## c5_dac00a436e — "Which national park (Voyageurs)"

**Gold evidence**: D5:8 (Audrey, 28 Jan 2023): _"That's a good plan!
I'm lucky to have a park near me - it's great for my pup's walks.
Last Friday we took a road trip - we went to a beautiful national
park and my dogs had a blast! It was an awesome trip!"_ +
D11:9 (Andrew): _"Looking forward to seeing them have fun hiking.
Let's get planning for next month! Here's the map for the trail."_

**Critical observation**: a full scan of conversation 5's `conversation`,
`session_summary`, `observation`, and `event_summary` fields for the
literal token `Voyageurs` returns **zero hits**. The store has
zero matches either.

Both gold-evidence turns carry image attachments
(D5:8 → pexels.com photo "three dogs running through a field of
grass", D11:9 → "a photo of a map of a park with a lot of trees")
but only the text + blip_caption is ingested by RadioMind — img_url
is not vision-parsed. The "Voyageurs" name presumably sits on the
trail-map image pixels in D11:9.

### Audit

1. **Gold turns in top-K?** D5:8 yes (rank 6). D11:9 no (absent
   from top-30). But moot: the literal answer "Voyageurs" isn't
   in either turn's text either way.

2. **prompt-side evidence?** NO turn text in the entire dataset
   names Voyageurs. The LLM's actual answer ("the memories do
   not specify the name of the national park") is
   architecturally correct given text-only ingestion.

3. **Error layer**: **non-text-groundable under current ingestion**.
   The "Voyageurs" token is absent from all text-channel content
   RadioMind currently ingests. The LLM's actual answer
   ("the memories do not specify the name of the national park")
   is faithful to the inputs it has. Where the gold token
   actually lives — on D11:9's trail-map image pixels, in
   external world knowledge, or in some other modality the
   benchmark expects — is a separate question we cannot
   conclude from this audit alone.

4. **Narrow deterministic fix path?** NO.
   - If the gold relies on image content, extracting it would
     require multimodal ingestion. That is a major extension,
     not a narrow helper.
   - If the gold relies on external world knowledge (geographic
     inference, etc.), it is also out of scope for a memory-
     system intervention.
   - Either way, no text-side deterministic trick can
     synthesize a place name that doesn't appear in the text.

### Verdict

**Non-text-groundable under current text-only ingestion.** Do
NOT add to an errata-exclusion list yet — first clarify whether
the LoCoMo benchmark's evaluation protocol actually requires
multimodal ingestion, or whether the gold relies on something
else (world knowledge, external context). Until that's resolved,
treat `c5_dac00a436e` as a known unscoreable-under-current-
inputs case but don't actively filter it.

---

## Round-1 Synthesis

| qid | layer | actionable now? |
|---|---|---|
| `c2_29183ecb5e` financial | retrieval recall gap under default a2a-practice path; also missed in one max-path run | **defer**: no narrow deterministic fix; one observed `--benchmark-mode max` run also did not surface D5:5 — agentic decomposition is stochastic so this is not a capability theorem, but it is enough to drop implementation for this round. |
| `c5_dac00a436e` Voyageurs | answer absent from ingested text | **defer**: outside the current text-only scoreable surface; root cause (vision/world-knowledge/other) is unresolved and not relevant to deferral. |

Neither qid is a good NAR-shape target. The stable-FAIL set
under our current text-only + narrow-deterministic constraints
is genuinely hard.

## What to Look At Next (other stable-FAIL qids)

The audit framework continues to be useful but the answer "no
narrow deterministic fix" was the same for both round-1 qids.
Recommend before doing more audits:

- `c3_2656e2c771` (count): pre-audit by checking whether the
  count gold matches a regex-recognizable "N times" phrase or
  requires LLM inference. If the latter, expect another "no
  narrow fix" verdict.
- `c3_a9fddfe69b` (Nate) + `c9_5ab522b5c7` (Calvin): single-
  audit each and see if a candidate-commit / temporal-selection
  intervention is even theoretically narrow.
- Likely outcome: 2/5 stable-FAIL qids will have a narrow path,
  3/5 won't. Worth knowing the ratio before committing to a
  new workstream.

## Files Used

- `/tmp/rm-sc3-locomo-flip10/data/{radiomind,knowledge}.db`
  (LCR-1 run-1 sandbox; NAR-on)
- `~/Library/Caches/radiomind-data/locomo10.json`
- SC-3 / LCR-* per-qid result JSONs

No new files created. No code touched.
