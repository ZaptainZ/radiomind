# Decouple embedding/rerank config from [llm.openai]

**Date**: 2026-04-21
**Trigger**: user switched chat LLM to a new provider (TokenPlan) whose API key doesn't cover embedding/rerank SKUs. The existing code in `core/mind.py` gated the DashScope embedder on `"dashscope" in llm.openai.base_url`, so swapping the LLM silently killed semantic retrieval.

## Problem

`_try_dashscope()` for embedder and the reranker fallback both read `[llm.openai]` and activated only when the URL pointed at DashScope. This implicitly tied three independent services — chat LLM, embedding, rerank — to one config section and one provider.

Host LLMs (Claude Code / Codex / Cursor) don't expose an embedding or rerank API. So even under the "host-LLM-assumed" policy, these two still need a separate cloud endpoint (or a local model). Forcing them onto the same key as the chat LLM is wrong: users who legitimately want to try a chat-only provider get their vector recall silently disabled.

## Change

Dedicated `[embedding]` and `[reranker]` sections in `config.toml`. `mind.py` reads these first; falls back to the legacy "piggyback on `[llm.openai]` if DashScope" path for backward compatibility.

### Files
- `src/radiomind/core/mind.py` — `_try_dashscope()` and the reranker fallback now prefer the dedicated sections, legacy path kept.
- `~/.radiomind/config.toml` — added `[embedding]` (DashScope text-embedding-v4, 2048-dim) and `[reranker]` (gte-rerank-v2). `[llm.openai]` switched to TokenPlan / qwen3.6-plus.

### Verification
- DashScope embedder live-call: HTTP 200, returns 8192-byte payload = 2048 × 4 bytes float32.
- DashScope reranker live-call: relevant pair 0.1786, irrelevant pair 0.0059 (~30× separation).
- `RadioMind.initialize()` end-to-end: `_embedder` resolves to `DashScopeEmbedder` from the new section.
- `pytest tests/ -k "embed or rerank or config or llm_auto"` → 28 passed, 0 failed.

## Non-changes (intentional)

- `DashScopeEmbedder` and `DashScopeReranker` constructor signatures untouched.
- No `provider` enum / abstract factory introduced — user has one embedding vendor (DashScope) and will keep it; abstraction would be speculative.
- Reranker still defaults to `retrieval.reranker.enabled = false`. `[reranker]` section exists but doesn't auto-activate.

## Implication for host-LLM-assumed policy

The memory note `project_host_llm_assumed.md` states hosts always have a capable LLM. This is true for chat/extraction/atomization, but **embedding and rerank are out of scope**: no major host exposes them. Chat LLM provider choice and embedding/rerank provider choice are now independently configurable, matching reality.
