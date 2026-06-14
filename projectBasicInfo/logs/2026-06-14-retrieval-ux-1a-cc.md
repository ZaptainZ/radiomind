# RetrievalUX-1a — position embedding as default enhancement, reranker as conditional advanced

**Date:** 2026-06-14
**Author:** Claude Code (cc)
**Scope:** Product UX / onboarding / doctor / docs only. **No subscription, no
hosted vector DB, no billing, no managed retrieval, no auto pip install, no auto
model download, no benchmark-scoring change, no retrieval-ordering change.** The
only runtime touch is read-only state detection + copy + a packaging extra.

## Goal

Make the local retrieval ladder legible so users know the right next step:
1. **embedding = recommended** local enhancement (bare-install is FTS+facet, fine,
   but `radiomind[embedding]` is the quality default).
2. **reranker = advanced**, best local quality — recommended only when the machine
   is a good fit; quietly skipped otherwise (never pushed/scary).
3. remote = BYOK, consent-gated, NOT default, NOT a subscription.

## Implementation

**New `src/radiomind/core/retrieval_tier.py`** (pure, testable):
- `detect_retrieval_tier(config, …)` → tier label: `FTS-only (+ typed-facet
  fallback)` / `local embedding` / `local embedding + local reranker` /
  `remote (consented)`. Overridable args for tests; uses
  `check_embedding_available` / `check_reranker_available` + `remote_retrieval_consented`.
- `local_reranker_recommendation(home, machine, system, free_bytes)` → env-checked
  advice: `{recommended, reason, install_command, estimated_disk}`. Recommends on
  Apple Silicon with ≥5GB free, or any platform with ≥8GB free; low disk / other
  → not recommended with a reassuring "advanced reranker skipped for this machine"
  reason (never an error tone). Pure — machine/system/free_bytes injectable.
- Copy constants: `EMBEDDING_INSTALL`, `RERANKER_INSTALL`, notes, disk estimate.

**`pyproject.toml`** — added the `rerank = ["sentence-transformers>=3.0"]` extra
(the code already referenced `radiomind[rerank]` but the extra didn't exist).
Deliberately NOT added to `all` — reranker is heavy and opt-in, not a default.

**`cli/main.py`:**
- `_onboard_state()` now includes `retrieval_tier`, `embedding_installed`,
  `reranker_installed`, `reranker_reco` (reuses the new pure module; no live mind).
- `_render_retrieval_tier(state)` (new helper) → onboard lines: current tier;
  embedding nudge only when FTS-only and not consented; reranker line conditional
  on the env recommendation (offer install only when recommended, else quiet skip).
- `doctor` gains a `retrieval tier` PASS + `local embedding` WARN-if-missing +
  `local reranker` PASS (recommend or quiet-skip). Pure detection — no model load.
- Existing `retrieval egress` (consent) and `embedding model` checks kept.

**Docs:** README / README_zh (retrieval-ladder install block + tier table),
quickstart (ladder note), api-reference (`search` = retrieval ladder + note).
Consistent message: bare = FTS+facet; recommended = `[embedding]` (on-device,
text stays local); advanced = `[rerank]` (~2.3GB, Apple Silicon/ample disk);
remote = consent-gated BYOK, no subscription.

## Deferred (NOT in this round)

Background auto-install of the reranker. pip install + 2.3GB download is a heavy
side effect needing explicit authorization, progress, cancel, failure recovery →
**RetrievalInstall-1b** if pursued. 1a only emits suggestions + copy-paste commands.

## Verification

- Live `onboard` (FTS-only): shows `retrieval tier: FTS-only (+ typed-facet
  fallback)` + recommends `[embedding]` + (this machine = Apple Silicon) offers
  `[rerank]`. Under the embedding-installed venv: tier `local embedding`, embedding
  nudge gone, reranker still offered. `doctor` mirrors it.
- `tests/test_retrieval_tier.py` — 14 tests: tier detection (4 tiers incl. remote
  wins); reranker reco (Apple Silicon recommend / low-disk skip / non-arm needs
  generous disk / reassuring tone); onboard copy (FTS→recommend embedding,
  installed→no nudge, unsuitable→quiet skip, consented→no local nudge); live
  onboard shows tier; config template remote consent=false.
- regression_pack ALL PASS (+ `retrieval:tier-ux`); existing CLI/consent suites
  unaffected (58 passed together).

## Conclusion

**PASS.** The retrieval ladder is now legible across onboard/doctor/README/
README_zh/quickstart/api-reference: embedding is the recommended local default,
reranker is conditionally-recommended advanced, remote is consent-gated BYOK (not
a subscription). No runtime retrieval behavior changed; no installs/downloads
performed. Auto-install deferred to a future authorized 1b.

See [[project_biolocal_retrieval]] (why local embedder is the quality lever),
[[project_managed_retrieval]] (remote consent / hosted PARK).
