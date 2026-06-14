# ManagedRetrieval-1b — Remote embedding/rerank consent hardening

**Date:** 2026-06-14
**Author:** Claude Code (cc)
**Scope:** Fix the *existing* plaintext-egress path found in 1a. **NOT** a hosted
vector product — no vector DB, no sync, no billing, no RadioHeader direct egress,
no benchmark-scoring change, no new data uploaded for tests.

## Background

1a (design audit) found a live privacy/authorization gap, not a future one:
- `embedding_dashscope.py` sends raw memory `text[:2048]` to a remote /embeddings API.
- `reranker_dashscope.py` / `reranker_openai_compat.py` send query + candidate text.
- The remote embedder **auto-enabled** whenever a DashScope-style key was present
  (`_try_dashscope()` ran first, `retrieval_provider.enabled` defaulted true, and
  the `[llm.openai]` piggyback activated remote embedding from a mere *LLM* key).
  A user with a DashScope chat key could believe retrieval was local while memory
  text was leaving the device.

## Goal

Bring the existing remote embedding/rerank egress under **explicit consent** and
make the retrieval data-egress posture **visible**. Default = local-only.

## Approach

**Consent gate (new module `src/radiomind/core/retrieval_consent.py`):**
- `remote_retrieval_consented(config)` — default False. Precedence:
  env `RADIOMIND_REMOTE_RETRIEVAL` (1/true/yes/on → grant, 0/false/no/off → deny)
  > config `retrieval.remote.consent`.
- `remote_retrieval_key_present(config)` — is a remote retrieval credential
  configured (so we can show "available but disabled until consent"). The
  `[llm.openai]` piggyback counts only when the base_url is DashScope-style.
- `retrieval_egress_status(config, embedder, reranker)` — pure projection
  (mode + remote_consented + remote_key_present + remote_active) for status/doctor/onboard.

**`is_remote` class-attribute contract** on the four backends (avoids importing
classes / surviving renames): `EmbeddingEncoder`/`CrossEncoderReranker` =`False`
(on-device); `DashScopeEmbedder`/`DashScopeReranker`/`OpenAICompatReranker` =`True`.

**Gate wiring in `mind.py` (`initialize()`):**
- `_try_dashscope()` returns None immediately when not consented → falls through
  to local ONNX, else FTS. The local embedder path is untouched.
- The remote reranker fallback block runs only `if self._reranker is None and
  remote_retrieval_consented(...)`. The **local** CrossEncoder attempt above it is
  ungated (it is on-device).
- Updated the stale "privacy bet abandoned / prefer remote" comment block to
  state the consent precondition.

**Visibility:**
- `status` prints a `retrieval:` line (live mode + egress warning / consent hint).
- `doctor` adds a `retrieval egress` check: WARN when remote is active (text
  leaves device), PASS otherwise (local-only / available-but-disabled).
- `onboard` prints a config-only posture line (no live mind): local-only /
  available-but-OFF / CONSENTED. Kept the existing
  `managed retrieval: future / not configured` line (that refers to the PARKED
  hosted product, a different thing).
- `search` no-result hint updated: local semantic = `[embedding]` extra; remote
  embedding requires provider config **AND** consent.
- Config template gains a `[retrieval.remote]` section (`consent = false`) with an
  explanatory comment.

**Copy rules honored:** never says "private"; explicitly says remote sends
memory/query/candidate text to a third-party API; does not push普通用户 toward a
subscription or "fill an API key first".

## Files changed

- `src/radiomind/core/retrieval_consent.py` (new) — consent + projection.
- `src/radiomind/core/mind.py` — gate `_try_dashscope()` + remote reranker block;
  comment refresh.
- `src/radiomind/storage/embedding.py`, `embedding_dashscope.py`, `reranker.py`,
  `reranker_dashscope.py`, `reranker_openai_compat.py` — `is_remote` attr.
- `src/radiomind/cli/main.py` — `_render_retrieval_status` / `_render_retrieval_consent`
  helpers; status/doctor/onboard/search wiring; config-template `[retrieval.remote]`.
- `tests/test_managed_retrieval_consent.py` (new) — 28 tests.
- `bench/end_to_end/regression_pack.py` — register `retrieval:remote-consent`.

## Verification

- New suite: **28 passed** (consent env+config both paths + default-off; key
  detection incl. dashscope-only piggyback; egress projection; CLI copy 3 states;
  live gate: no-consent→never remote, consent/env→remote embedder+reranker).
- No regression: `test_cli_product_ux` + `test_mind` + `test_iterative_search` =
  33 passed. **regression_pack = ALL PASS** (incl. new entry, 28).
- Live CLI smoke (3 scenarios): (A) no key → "local-only (no credentials)";
  (B) key, no consent → onboard/status/doctor all show "available but disabled
  until consent", embedder stays local/FTS; (C) consent via env → "remote
  embedding/rerank enabled — text sent to a third-party API", embedder is remote.

## Conclusion

**PASS.** The pre-existing silent plaintext egress is now consent-gated
(default OFF) and visible across status/doctor/onboard/search. Local FTS / local
embedding behavior unchanged; remote retrieval preserved for users who opt in.
Hosted vector DB / sync / billing remain **PARKED** (see 1a log). No runtime
architecture beyond the gate; RadioHeader untouched.
