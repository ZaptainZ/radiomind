# Benchmark Claim Hygiene (docs-only)

**Date**: 2026-06-03
**Author**: Claude Code
**Status**: Docs only. **No benchmark run, no runtime change.** Makes the public
benchmark claims in README / README_zh / RELEASE unambiguous: published numbers
are historical version-dated artifacts, current main is gated by
regression_pack + target_pack, full n=100 only on a formal baseline refresh.

---

## Why
After the #3 audit framed the LME-S 0.930 / LoCoMo 0.890 runs as *historical
stability artifacts, not current-main baselines*, the README badge/headline
still read as a standing current score. This closes that gap in the public docs.

## Changes
**README.md / README_zh.md**
- Badge: `LongMemEval-S` → `LongMemEval-S V6.1.1` with `0.930 (historical)`, so
  the badge ties the number to a version, not "current".
- v0.2.0-rc1 note: added "This 0.930 is a historical V6.1.1 n=100 artifact, not
  a standing current-main score — current main is gated by regression_pack +
  target_pack; full n=100 only on a formal baseline refresh."
- LongMemEval-S section: added a ⚠️ caveat block (historical artifacts; gate
  story; formal-refresh policy); relabeled rows to mark `architecture v3
  (historical)`, `v5 (historical)`, `V6.1.1 historical n=100`; changed
  "MemMachine (current SOTA)" → "MemMachine (SOTA, published)" to drop the
  "current" ambiguity. Table still shows 0.930.
- LoCoMo section: unchanged (already historical-only from the prior commit).

**RELEASE.md**
- TL;DR: softened to past tense + "at this snapshot"; added a ⚠️ note that all
  figures are dated n=100 artifacts tied to a version, not standing current-main
  scores, and current main is gated by regression_pack + target_pack with full
  n=100 only on a formal baseline refresh.
- LoCoMo 0.890 caveat: already present from the prior commit.

## Completion check (the 5 criteria)
1. Badge/headline no longer reads as a current-main score — badge says
   `V6.1.1 … 0.930 (historical)`; rc1 note explicitly historical. ✓
2. LME-S table keeps 0.930, row + caveat say `historical V6.1.1 n=100`. ✓
3. LoCoMo kept as historical artifact. ✓
4. Docs state current main = regression_pack + target_pack gates; full n=100 only
   on formal baseline refresh. ✓
5. Full-text sweep of `0.930 / 0.890 / current / baseline`: every score is
   version-dated/historical; "current" only appears as "not a current-main
   score" or "current main is gated by…"; "baseline" = Mem0's baseline or the new
   "formal baseline refresh" term. No "current main is verified at these scores"
   ambiguity. (Residual "currently" at RELEASE.md L133/L172 are historical
   failure-rate narrative / API-key notes, not score claims — left as-is.) ✓

## Not done (out of scope, per instruction)
No LME-S n=100, no LoCoMo run, no helper/retrieval fix, no runtime change.
