# ManagedRetrieval-1a — Managed vector retrieval: product & security design audit

**Date:** 2026-06-14
**Author:** Claude Code (cc)
**Type:** Read-only design audit. **No code. No service. No upload. Runtime/hooks untouched.**
**Question:** Where is the boundary of a future hosted vector-retrieval service —
*what data may leave the device, when, under whose authorization, billed how, revoked how.*

---

## 0. Grounding — what the repo actually does today

Read before designing, so the boundary is drawn against reality not aspiration:

- **Default install = local + FTS only.** `database.py` returns `method="fts"`;
  vector (`knn`) search exists only when an embedder is loaded. Bare
  `pip install radiomind` ships **no embedder** (RC-1a). Storage is local SQLite.
- **Local embedding is opt-in, on-device.** `embedding.py` = ONNX MiniLM-L6-v2,
  384-dim, via `pip install 'radiomind[embedding]'`. Text never leaves the box.
- **Remote embedding/rerank already exist and already send plaintext.**
  `embedding_dashscope.py` posts `{"model", "input": text[:2048]}`;
  `reranker_dashscope.py` posts raw query-candidate text pairs. The DashScope
  embedder **auto-enables** when the local embedder fails to load *and* a
  dashscope-compatible `base_url`+key is in config. → **Today there is a
  plaintext-egress path the user never explicitly consented to as "retrieval
  upload."** This is the single most important finding and shapes every section.
- **Consent precedent already in code.** `onboard` prints
  `managed retrieval: future / not configured`, recommends *host LLM first*, and
  never writes config without `--yes`. The managed-retrieval consent model must
  be an *extension of this*, not a new paradigm.

---

## 1. Who actually needs hosted vector?

| Audience | Needs hosted vector for retrieval *quality*? | Real driver, if any |
|---|---|---|
| Personal agent user (single device) | **No.** Local ONNX embed + FTS covers semantic recall for the realistic corpus size (≤~10⁵ memories). | Cross-device **sync** (phone↔laptop), not vector quality. |
| RadioHeader coding-agent user | **No — and highest sensitivity.** Code memory is proprietary; local must be the hard default. | Only *team-shared project memory* (an enterprise feature), never solo dev. |
| Hardcore CLI / Python / MCP user | **No.** Power users self-host or bring their own key (dashscope fallback already serves the "local embedder won't install" case). | Convenience, not capability. |

**Where local FTS / host embedding is already sufficient (the majority):**
single-device, corpus up to ~10⁵ entries, semantic recall via the local ONNX
extra or the user's own remote-embed key. **Honest conclusion: almost nobody
needs *us* to run a vector DB for retrieval quality.** The only genuine pulls are
(a) cross-device sync, (b) constrained envs where the local embedder won't build,
(c) team-shared memory. None of these *require* a hosted retrieval product — they
require *sync* infrastructure. That reframes the whole effort.

---

## 2. Data boundary

Ranked by safety; the design target is the top row.

1. **Local embed → remote stores vectors + opaque IDs only (no text). ★ target.**
   Server is a dumb vector index; it never sees plaintext. Original memory stays
   in local SQLite. Re-hydration is local (ID → local row). This is the only form
   that lets us honestly say "your text never leaves your device."
2. **Remote embedding (text leaves device)** — acceptable **only** under explicit,
   per-scope opt-in by a user who has *already* chosen a remote embedder. This is
   exactly today's dashscope path; the gap is that it's silent/auto, not consented.
3. **Remote stores raw text** — **never by default**, gated behind a distinct,
   loud scope; primarily a team-share/enterprise concession.

**Sensitivity tiers (default upload posture):**

| Tier | Examples | Default |
|---|---|---|
| **Code memory (RadioHeader)** | source, repo paths, proprietary logic | **Never** auto-leaves device. Highest bar even for opt-in. |
| **Personal memory** | habits, preferences, personal notes | Local-only; vector-only sync opt-in. |
| **Business / project docs** | client docs, internal knowledge | Local-only; opt-in only with org-level policy ack. |
| **Public / shortwave knowledge** | shared library snippets | Low sensitivity; still opt-in to leave device. |

**Default — never uploaded under any circumstance without an explicit per-scope grant:**
raw memory text, code, business documents, the user/system meta-profiles
(双侧写), debug/telemetry payloads containing any of the above.

---

## 3. Authorization model

- **Default = local-only.** No network egress for retrieval. (FTS + local embed.)
- **First enable is a host-mediated, explained consent**, not a flag flip. The
  host AI (RadioHeader / personal agent) must surface the explanation and capture
  the grant — mirrors today's "host LLM first" onboard posture.
- **Scopes are independent and each has user-facing copy:**
  - `index_text` — "Send memory text to a remote service to build search
    embeddings. Your words leave this device." (the loud one)
  - `store_vector` — "Store only numeric embeddings + anonymous IDs remotely.
    Your text stays local; the server cannot read it."
  - `remote_rerank` — "Send your query and candidate snippets to a remote
    reranker for better ordering. These snippets leave this device per query."
  - `cross_device_sync` — "Sync vectors/IDs across your devices through our
    service." (text-free if paired with `store_vector` only)
- **Revocation = delete + tombstone + proof.** On revoke: stop egress
  immediately; issue remote delete for all vectors/IDs under that scope;
  propagate to replicas/backups within a stated window; surface a deletion
  receipt. Local data is untouched (it was always the source of truth).
- **Flag now (do not fix in 1a — runtime):** the auto-enabling dashscope
  embedder/reranker should be brought under `index_text` / `remote_rerank`
  consent before any managed product ships. Until then it is an un-scoped
  plaintext egress. → candidate for the 1b consent retrofit.

---

## 4. Technical form

- **local FTS fallback** — always present, always the floor. Never removed.
- **local embedding** — on-device ONNX; the recommended semantic default.
- **hosted embedding API** — opt-in `index_text`; text leaves device.
- **hosted vector DB** — opt-in `store_vector`; **vectors + opaque IDs only.**
- **hybrid (recommended): local stores原文 + remote stores vectors/anon-IDs.**
  Local embed → upload vector only → query embeds locally → ANN on server returns
  IDs → local re-hydration. Server is zero-knowledge w.r.t. content.
- **RadioHeader uses managed retrieval *only* indirectly, through RadioMind.**
  RadioHeader never talks to a vector service directly. One data-egress chokepoint
  = one place to audit, gate, and log. This is a hard architectural rule.

---

## 5. Billing / subscription

- **Sell infrastructure, not intelligence:** cross-device sync, hosted
  embedding/rerank *compute*, vector storage. **No generic LLM subscription** —
  host LLM first remains the doctrine.
- **Free tier = everything local** (already true today): FTS + local embed +
  local store. The free tier is genuinely useful, not crippleware.
- **Paid = sync + hosted vectors (+ optional hosted embed/rerank compute).**
- **Meter by user + storage footprint (vector count / GB), soft caps** — *not*
  per-query and *not* per-token. Per-query metering punishes the core action
  (retrieval); per-token re-creates an LLM-style bill we explicitly don't want.
  Predictable per-seat + storage tier is the right shape.

---

## 6. Risk & compliance

- **"Believes local, actually uploaded."** The headline risk — and it *already
  exists* via the silent dashscope fallback. Mitigation: no silent egress, ever;
  scope consent; a `radiomind status`/doctor line that always states the current
  egress posture in plain words.
- **Right to erasure.** Revocation must reach replicas + backups within a stated
  window with a deletion receipt; local remains source of truth.
- **Debug/telemetry leakage.** Logs, error reports, crash dumps must never carry
  memory text, code, or the meta-profiles. Vectors/IDs only; redact at the egress
  chokepoint.
- **Corporate/code compliance.** Code memory never auto-leaves; org policy ack
  required even for opt-in; vector-only (zero-knowledge) is the only posture that
  survives most corporate review.
- **Privacy leakage via embeddings.** Note (not block): embeddings are partially
  invertible. "Vector-only" reduces but does not eliminate exposure — say this
  honestly in the `store_vector` copy rather than overclaiming "fully private."

---

## Recommended MVP boundary

If anything proceeds, the **minimum defensible product is sync of a zero-knowledge
index, not a retrieval service**:

- Local stays the source of truth and the retrieval engine.
- **Server is a dumb, zero-knowledge vector store**: vectors + opaque IDs only;
  never plaintext, never rerank-on-text by default.
- Egress is **one chokepoint** (RadioMind), **consent-scoped**, **status-visible**,
  **revocable with a receipt**.
- The MVP's first deliverable is **honesty of the existing egress** (bring the
  dashscope auto-fallback under consent), *then* opt-in vector-only sync.

## "Do NOT do" list

- ❌ Don't build a hosted *retrieval-quality* product — nobody needs us to run a
  vector DB for quality; the pull is sync, not search.
- ❌ Don't upload raw memory text / code / business docs by default — ever.
- ❌ Don't let any silent/auto path send plaintext (close the current dashscope
  consent gap before shipping anything managed).
- ❌ Don't let RadioHeader reach a vector service directly — only via RadioMind.
- ❌ Don't sell a generic LLM subscription — host LLM first.
- ❌ Don't meter per-query or per-token.
- ❌ Don't overclaim "fully private" — embeddings are partially invertible; say so.
- ❌ Don't touch runtime/hooks in this phase (this is 1a, design only).

## Verdict — **PARK the hosted-vector product; narrow 1b candidate exists**

The hosted *retrieval product* is **PARKED**: the need is unproven (local covers
quality), the liability is high (plaintext egress, erasure, compliance), and the
genuine demand (sync) doesn't require it. Do not build a managed retrieval service
on speculation.

**If — and only if — the user wants a step**, the minimal, *defensible* 1b is not
a product but a **consent/data-boundary retrofit**:

> **ManagedRetrieval-1b (scoped, optional):** bring the *existing* remote
> embedding/rerank egress under the scope-consent model — default off, explained
> at first use, status-visible, revocable. No hosted service, no sync, no billing.
> Purely: make today's egress honest. ~runtime+onboard, small, testable.

Cross-device vector-only sync and any billing are deferred behind 1b and behind
real demand evidence. Until then: **PARK**.

See [[project_release_candidate_1a]] (clean-install posture),
[[project_host_llm_assumed]] (host-LLM-first doctrine),
[[feedback_sandbox_testing]] (no egress in tests).
