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

**Out of scope for a narrow ingest- or output-side helper.** The
right intervention is at the retrieval layer (query rewrite /
expansion / multi-aspect decomposition) and that is LLM-heavy,
not deterministic. Defer; do not open a workstream for this qid
alone.

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

3. **Error layer**: **OUT OF SCOPE** for current RadioMind
   text-only ingestion. The gold requires visual understanding
   of the trail-map image. RadioMind does not ingest image
   pixels. Strict-judge marks this FAIL because the LLM didn't
   emit "Voyageurs", but the LLM has no way to obtain that
   token from its inputs.

4. **Narrow deterministic fix path?** NO.
   - Adding a vision model to ingest img_url + extract text from
     trail-map images would close it, but that's a major
     multimodal extension, not a narrow helper.
   - There is no deterministic ingest- or retrieval-side trick
     that produces a place-name absent from all text.

### Verdict

**Architectural ceiling, not a fixable failure.** This qid is
effectively in the same category as the dataset-errata qids we
filter at run-time. Recommend:

- Treat as a known architectural-ceiling miss; do not chase.
- If wanting to remove from future strict-mean noise, add
  `c5_dac00a436e` to a "vision-required" exclusion list (parallel
  to the existing `370a8ff4` LME-S errata mechanism), but only
  after confirming on at least one more qid that vision is the
  identifier (avoid one-off exclusion).

---

## Round-1 Synthesis

| qid | layer | actionable now? |
|---|---|---|
| `c2_29183ecb5e` financial | retrieval recall gap | **no** — would need query expansion / decomposition (LLM-heavy, not narrow) |
| `c5_dac00a436e` Voyageurs | vision-required (text doesn't contain answer) | **no** — architectural ceiling |

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
