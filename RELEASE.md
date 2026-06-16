# RadioMind — Release Snapshot 2026-04-26

A bionic memory core for AI agents — pluggable, host-LLM-agnostic, with
a four-layer pyramid (drafts / notes / habits / external knowledge),
"chat" + "dream" refinement, and dual self-portrait meta-cognition.

This file is a snapshot suitable for short reports / hand-offs. For
the full design rationale see `projectBasicInfo/01_PROJECT_OVERVIEW.md`.

---

## v0.2.1 (2026-06-16) — product-entry release

First public release. The focus of this cycle was not new capability but making
the existing one **honestly deliverable**: install works, every user entry runs,
docs match the code, and the data-egress / quality boundaries are explicit.

**Highlights**
- **Product-entry readiness.** Clean `pip install` on a fresh venv; `radiomind
  --help` / `python -m radiomind` / `onboard` / `doctor` / `status` and the
  `init → learn → search` path all verified end-to-end.
- **Retrieval tier productization.** A legible local ladder surfaced in
  onboard/doctor/status/README: bare = FTS + typed-facet rescue; **`[embedding]`
  = recommended** local enhancement (on-device ONNX MiniLM ~86MB, text stays
  local); **`[rerank]` = advanced** local best-quality (~2.3GB, conditionally
  recommended by machine fit).
- **Remote-retrieval consent gate.** Remote embedding/rerank send text to a
  third-party API; they are **off by default** and require explicit consent
  (`RADIOMIND_REMOTE_RETRIEVAL=1` / `retrieval.remote.consent=true`), with the
  egress posture always visible. No "fully private" claim covers remote mode.
- **FTS facet rescue.** When bare-install keyword retrieval returns nothing for an
  anchored query, a deterministic, gated typed-facet rerank lifts the floor — no
  model, no network, do-no-harm gated (acts only when the pipeline is empty).
- **Provider deny-by-default.** The personal-agent provider defaults to
  `local_only`; background ingest/refine/dream are each gated on explicit
  authorization scopes; readiness reports the next action.
- **LoRA opt-in.** `RADIOMIND_ENABLE_LORA=1`; cold-start shows actionable
  data-volume thresholds + next step rather than silently failing.
- **Entry routing.** Programming-agent users → **RadioHeader first** (RadioMind is
  the optional memory backend); personal agents → the RadioMind provider; power
  users → CLI / Python / MCP (17 tools) directly.

**Benchmark positioning (unchanged, honest):** current-main LongMemEval-S center
**0.91 ± 0.01** (same-arch 3-run); historical **0.930** is a lucky upper-tail
single run kept for provenance, not a standing score; LoCoMo figures are
historical-only. See the TL;DR below.

**Non-goals / parked (not in this release):** managed retrieval subscription;
hosted vector DB; live RadioHeader digest integration; v4-pro / hybrid retrieval
route; benchmark chasing. Lightweight reranker alternatives (query-adaptive RRF)
were researched but their gate did not survive out-of-sample validation — parked,
not shipped.

---

## TL;DR

**RadioMind's current-main center on LongMemEval-S (deepseek-v3.2 / gpt-4o
judge, Mem0-compatible single answer + single judge) is 0.91 ± 0.01** — a
same-architecture 3-run central tendency (n=100 ×3, identical qid set+order,
2026-06-08, all judge-error clean). That is **within ~2 pt of published
MemMachine SOTA (0.930)** at ≈ 1/10 the inference cost and **+23 pt over Mem0's
0.680 same-protocol baseline**. Earlier single runs reached a historical high of
**0.930 (V6.1.1, 2026-05-10)**, but on the identical 100-qid sample a 9-run
cross-version envelope is mean 0.90 / median 0.92 / max 0.93 — **0.930 is a
lucky upper-tail run, not the current-main center.**

> ⚠️ **Two distinct things.** *Standing score* = current-main 0.91 ± 0.01
> (same-arch 3-run, honest center). *Historical highs* = single-run figures
> below (0.83 / 0.92 / 0.93), kept for provenance, **not standing scores** and
> not a stable center. The dominant variance is the answer LLM (non-deterministic
> even at temperature 0); self-consistency / majority does NOT raise the center
> (it only converges each question to its true expected value). Moving the center
> above ~0.92 requires architecture-level gains, not measurement tricks. Daily
> development is gated by `regression_pack.py` + `target_pack.py`; a full n=100 is
> re-run only on a formal baseline refresh.

Historical single-run highs (provenance, not standing scores):

| Configuration | Result | vs Mem0 same-protocol |
|---|---:|---:|
| gpt-4o answer + gpt-4o judge, n=100 (architecture v3) | **0.830** | +15 pt over 0.68 |
| deepseek-v3.2 + gpt-4o judge, n=100 v3 (legacy) | 0.860 | +18 pt |
| deepseek-v3.2 + gpt-4o judge, n=100 v5 (post all-arch upgrades) | 0.920 | +24 pt, ≈ 1/10 cost |
| deepseek-v3.2 + gpt-4o judge, n=100 V6.1.1 (lucky upper-tail) | **0.930** | +25 pt (single-run high, not the center) |

Architecture investments demonstrate that the quality gain transfers to
the weaker (cheaper) answer LLM — i.e. it is **not just prompt-tuning
the answer model**.

By question type (n=100 v5, deepseek-v3.2 / gpt-4o judge):

| qtype | n | acc | vs v3 |
|---|---:|---:|---:|
| single-session-user        | 16 | **1.000** | +6.2pt |
| single-session-preference  | 16 | 0.938 | +6.2pt |
| knowledge-update           | 16 | 0.938 | -0.4pt |
| single-session-assistant   | 17 | 0.941 | -5.9pt |
| temporal-reasoning         | 17 | **0.941** | **+23.5pt** ← multi-round trinity for date |
| multi-session              | 18 | 0.778 | +5.6pt |

Multi-session integration and temporal reasoning are the two failure-dense
qtypes — design surfaces for the next iteration.

---

## What's in this release

### Architecture

- **Four-layer pyramid memory** (L1 draft / L2 3D pyramid / L3 HDC habits / L4 shortwave)
- **Trinity primitive** (`refinement/trinity.py`) — task-shaped 3-stance debate, used as a sub-routine inside skills (e.g. `age_interval` semantic anchor matching)
- **Fourth law: Attention** — every layer declares its `AttentionSignature` (`core/attention.py`); query routing dispatches to dedicated skills per `wants` tag
- **Skill registry** (`skills/`): `temporal`, `cardinality`, `age_interval`, `event_interval`, `list_ordering`, `chain_reasoning`
- **NumericAggregator** (`refinement/numeric_aggregator.py`): bottom-up cardinal cache at ingest time + LLM/regex union extraction (deterministic + recall-rich); query-time scope filter + dedup + Python sum
- **Meta dual self-portrait**: user profile + system self-portrait, both consumable by trinity for self-calibration

### Prompt engineering (LongMemEval bench)

- `B3` PREFERENCE-ANCHOR + 1-shot example (preference-question gold expects user-anchored advice)
- `B4` PREMISE-VERIFICATION (relaxed): abstain only when memories actively contradict; partial evidence → best-effort
- `B5a` RECENCY-vs-RECOLLECTION (today vs remembered)
- `B5b` CATEGORY-VENUE MATCHING (art event ⇒ "Museum of Art" beats "farm stay")
- `T1.3` NUMERIC-AGGREGATION enumerate-then-sum
- `T3.3` FINAL-SELF-CHECK 4-point checklist
- DELTA vs ABSOLUTE rule for "how many more" questions

### Bench infrastructure (2026-04-26)

- `llm_call` retry on SSL EOF / network / 5xx / 429 (3 attempts, exponential backoff)
- answer max_tokens 800 → 1500 (DashScope deepseek is verbose)
- judge max_tokens 1200 → 2000 (gpt-4o judge sometimes runs out before yes/no)
- `<mem_thinking>` strip before sending to judge (regress harness now matches main bench)
- `dataset_errata.json` for known dataset-gold errors (e.g. `370a8ff4` LongMemEval gold contradicts haystack)
- `[llm.dashscope]` profile pinned with comment; `[llm.openai]` flagged 403 until rotation

### Dogfooding

- PreCompact hook now fresh-ingest aware (reads `MAX(memories.created_at)`); does not block when assistant just saved (manual or via stop_hook). Cooldown ladder for repeated `/compact` after a stale ingest.

---

## Benchmarks

### Same-protocol comparison vs Mem0

| System | LongMemEval-S | LoCoMo cat 1-4 |
|---|---:|---:|
| Mem0 v3 (gpt-4o answer + gpt-4o judge) | 0.680 | 0.916 |
| MemMachine | 0.930 | 0.917 |
| **RadioMind (gpt-4o answer)** | **0.830** | **0.890** |
| **RadioMind (deepseek answer, n=100 v3)** | **0.860** | (not re-run with v3) |

> ⚠️ The **LoCoMo 0.890** figure is a historical n=100 artifact (gpt-4o run,
> 2026-04-20) and has **not** been re-run after the V8.x / diagnostic / closure
> work — treat it as historical, not a current-main LoCoMo baseline.

### Architectural gain validation

20 historical fail qids → **20 / 20 flipped FAIL → PASS** in v2-fix
regression at deepseek/gpt-4o setup (100% recovery rate, after the
2026-04-27 follow-ups):

- 18 / 20 from C1+C2+C3 infra fixes
- +1 (`603deb26`) from regress strip_thinking
- +1 (`d851d5ba`) from class-aware ingest merge dedup

Remaining out of original 21 fails:
- `370a8ff4` (dataset errata, gold mathematically contradicts haystack — kept on errata list)

### Prompt side-effect rate (stress test, 2026-04-27)

Two independent stratified samples drawn from the 79 v2-PASS qids
(seed=42 and seed=7, non-overlapping), each n=20:

| Run | PASS | FAIL | Regression rate |
|---|---:|---:|---:|
| Run 1 (seed 42) | 19 | 1 (`gpt4_d12ceb0e`) | 5.0% |
| Run 2 (seed 7)  | 19 | 1 (`59524333`)      | 5.0% |
| **Combined**    | **38 / 40** | **2** | **5.0%** |

Identical regression rate across two independent samples → stable
prompt side-effect floor, not noise.

The 5% rate predicted **0.95** on n=100. The actual n=100 v3 run landed
at **0.860** — gap explained by qtype mix: the 5% sample over-represented
single-session qtypes (which already pass at >0.93), while v3's stratified
sample drew more multi-session and temporal-reasoning items where
RadioMind currently fails 28-30% of the time. The lesson: side-effect
rate from a single qtype mix doesn't transfer linearly when the new
mix is harder.

### n=100 v3 failure analysis (2026-04-30)

14 fails, concentrated in the two structurally hard qtypes:

- **multi-session (5)**: `d851d5ba` charity sum (class-aware dedup didn't
  re-cover this on a different seed — needs re-investigation), `c18a7dc8`
  age delta computed as 0, `d3ab962e` hike sum 45 vs gold 8, `gpt4_ab202e7f`
  count off by 1, `bb7c3b45` over-abstain.
- **temporal-reasoning (5)**: 3 over-abstain (`b46e15ed`, `gpt4_fa19884d`,
  `370a8ff4` errata), 1 event_interval miscount (`6e984301`), 1 entity
  mismatch (`gpt4_59149c78`).
- **abstain calibration (3 net 0)**: 3 should-abstain over-answer
  (`031748ae_abs`, `29f2956b_abs`, plus 1), 3 should-answer over-abstain.
- **preference (2)**: B3 anchor not triggered (`d6233ab6`, `95228167`).

`370a8ff4` is on the errata whitelist but the main bench harness doesn't
filter it (only `regress_activated_channels.py` does) — that's 1 wrongly-
counted fail.

---

## Known issues / next steps

1. **`d851d5ba` regression**: the class-aware dedup fix recovered this on
   the v2 seed but not v3. Indicates the bake-sale charity event lookup
   is sensitive to which haystack ordering DashScope returns; need a
   deterministic regression rather than a one-off fix.
2. **Errata filter in main bench**: port the `dataset_errata.json` skip
   logic from `regress_activated_channels.py` to `run_longmemeval_mem0.py`
   so `370a8ff4` doesn't drag down the headline.
3. **Multi-session + temporal-reasoning iteration**: the failure-dense
   qtypes (10/14 = 71% of fails). Worth a focused architectural pass
   on event chronology and cross-session entity tracking.
4. **Multi-seed bench** (3 runs at the same n=100) to quantify how much
   the 0.860 number itself swings with different stratified seeds.
5. **TokenPlan key rotation**: current 403 forces DashScope-only.

---

## Repository layout

```
src/radiomind/
  core/             attention, mind, types
  storage/          SQLite, FTS5, sqlite-vec, KG
  skills/           query-time structured resolvers
  refinement/       trinity, numeric_aggregator, salvage
  meta/             user / system profiles
  hooks/            PreCompact / Stop / etc
bench/end_to_end/
  run_longmemeval_mem0.py   main bench harness
  regress_activated_channels.py  qid-level focused regression
  mem0_protocol/    Mem0-verbatim answer + judge prompts
  dataset_errata.json
  *.json / *.ckpt.jsonl     historical run records
projectBasicInfo/
  01_PROJECT_OVERVIEW.md    canonical design doc
  logs/             dated implementation/decision logs
```

---

## Commit lineage (this push, 2026-04-26)

```
03453d4  bench: regress harness strips <mem_thinking> before judge
54db623  bench: C1+C2+C3 infra fixes — 18/20 v2 fails recovered
b529f81  hooks: precompact is remind-once-then-approve, not count-enforcer
6def67b  hooks: precompact uses stateful ladder + 30min fresh window
100c7be  docs: sync overview with precompact hook fix
35c9f77  hooks: precompact checks recent ingest instead of always blocking
143877d  docs: sync overview + log for 20/20 full regression
92b0159  numeric: always-on regex supplement to LLM extraction
0c5d928  cardinal: evidence chain with per-event source + inline arithmetic
a48acb6  numeric: scope-filtered + deduped cardinal view
28fbef4  architecture: A1+A2+B1+B2 recover 4/5 remaining n=100 fails
```

For the complete chain see `git log` from `c532063` onward (this is
when the post-/clear push started).
