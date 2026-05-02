"""Generic three-way debate primitive — single-round and multi-round.

The trinity is the primitive: **three opposing analytical stances
triangulate a conclusion**. It is NOT a fixed cast of named roles. The
stances are task-dependent and picked by the LLM based on what tensions
the task surfaces.

Examples of stance triples that emerge from different tasks:
- counting evidence:  conservative / inclusive / consolidative
- timeline question:  anchor-based / chain-based / window-based
- open-domain pick:   literal-from-evidence / inferred / abstention-safe
- habit mining:       stability-first / novelty-first / parsimony-first

`debate(...)` is the entry point. By default it runs ONE round (single
LLM call) — the legacy behavior every existing call site relies on.
Pass `max_rounds > 1` to enable multi-round refinement: each subsequent
round shows the previous round's stances and asks for revision; the
debate stops when stances converge (unanimous) or `confidence` clears
the convergence threshold or `max_rounds` is exhausted. This is the
fractal "deeper trinity" mode used for arithmetic-precision tasks
(date intervals, age computations) where a single round can produce
wrong-by-a-factor results.

Sub-trinity recursion is a CALLER pattern, not a primitive feature.
A caller wanting fractal depth can invoke `debate()` inside one of
its own stance reasonings — for example, a date-anchor stance can
call `debate()` internally to triangulate WHICH date to anchor on,
then return its own conclusion to the outer trinity.

Call sites pass a TASK description; the LLM picks the three opposing
stances that matter for that task. Callers that need extra structured
output (e.g. "revoke": [ids], "final_members": [names]) pass
`extra_schema` to have the LLM include those keys alongside
`stances` + `final_answer`.
"""
from __future__ import annotations

import json
import re
from typing import Any


_PROMPT = """You triangulate an answer by arguing from three distinct opposing stances.

Task: {task}

Evidence:
{evidence}

Work in three passes:
1. Identify three opposing analytical stances a careful analyst could take
   on THIS task. Each stance: SHORT_NAME + one-line emphasis. They must
   genuinely oppose (not rewordings of one view).
2. For each stance, independently derive its conclusion from the evidence.
3. Reconcile into one final answer. When two stances partially agree,
   synthesize; when evidence is thin, abstain ("insufficient"). Always
   include a `confidence` (0..1) field — your honest probability that
   the final_answer is correct.

Return STRICT JSON only with these keys{extra_keys_summary}:
{{
  "stances": [
    {{"name": "...", "emphasis": "...", "conclusion": "..."}},
    {{"name": "...", "emphasis": "...", "conclusion": "..."}},
    {{"name": "...", "emphasis": "...", "conclusion": "..."}}
  ],
  "final_answer": "...",
  "confidence": 0.0{extra_schema_block}
}}"""


_REFINE_PROMPT = """You are in REFINEMENT ROUND {round_idx} of a multi-round trinity debate.

Task: {task}

Evidence:
{evidence}

Round {prior_idx} produced these stances (the LAST round's view):
{prior_block}
Round {prior_idx} final_answer was: {prior_final}
Round {prior_idx} confidence was: {prior_conf}

Your job in this round:
- Each stance reconsiders its position given the others' arguments
  and the evidence. If the evidence supports a different conclusion,
  CHANGE your mind and say so. If you stand firm, strengthen with new
  reasoning the prior round didn't surface.
- The three stances must remain genuinely opposing (you can re-pick
  the stance triple if the prior triple wasn't the best fit).
- Re-derive the final_answer with full self-honesty. If you now
  realise the prior answer was wrong, say so and give the corrected
  answer. Update confidence accordingly — higher only if the new
  reasoning is genuinely more grounded.

Return STRICT JSON in the SAME schema as round {prior_idx}{extra_keys_summary}:
{{
  "stances": [
    {{"name": "...", "emphasis": "...", "conclusion": "..."}},
    {{"name": "...", "emphasis": "...", "conclusion": "..."}},
    {{"name": "...", "emphasis": "...", "conclusion": "..."}}
  ],
  "final_answer": "...",
  "confidence": 0.0{extra_schema_block}
}}"""


def _format_extra(extra_schema: str) -> tuple[str, str]:
    """Return (extra_keys_summary, extra_schema_block) for prompt injection."""
    if not extra_schema.strip():
        return "", ""
    return (
        " plus the caller-requested keys",
        f",\n{extra_schema.rstrip(',')}",
    )


def _call_llm(prompt: str, llm: Any) -> str:
    """Invoke either an llm with .generate(prompt, system) or a callable."""
    try:
        if hasattr(llm, "generate"):
            raw = getattr(
                llm.generate(prompt, system="Output only strict JSON."),
                "text", "",
            ) or ""
        else:
            raw = llm(prompt, "Output only strict JSON.")
    except Exception:
        return ""
    return raw or ""


def _parse_json(raw: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json|JSON)?\s*\n?", "", (raw or "").strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
    try:
        obj = json.loads(cleaned)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if not str(obj.get("final_answer") or "").strip():
        return None
    return obj


def _is_converged(result: dict, threshold: float) -> bool:
    """A round 'converges' when:
      - confidence ≥ threshold (the LLM self-reports high certainty)
      - OR all three stances reach the same conclusion (unanimous)
    """
    try:
        conf = float(result.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if conf >= threshold:
        return True
    stances = result.get("stances") or []
    if len(stances) >= 3:
        conclusions = {
            str(s.get("conclusion", "")).strip().lower()
            for s in stances
            if isinstance(s, dict)
        }
        if len(conclusions) == 1 and next(iter(conclusions), ""):
            return True
    return False


def _format_prior_stances(result: dict) -> str:
    out = []
    for s in result.get("stances") or []:
        if not isinstance(s, dict):
            continue
        out.append(
            f"  - {s.get('name','?')} ({s.get('emphasis','')}): "
            f"{s.get('conclusion','')}"
        )
    return "\n".join(out) or "(no stances surfaced)"


def debate(
    task: str,
    evidence: str,
    llm: Any,
    extra_schema: str = "",
    max_evidence_chars: int = 6000,
    max_rounds: int = 1,
    converge_threshold: float = 0.7,
) -> dict | None:
    """Run a three-stance debate and return parsed JSON.

    Returns the parsed JSON dict with at least `stances` + `final_answer`
    + `confidence`, plus any additional fields the caller requested via
    `extra_schema`. `extra_schema` is a short schema fragment injected
    into the prompt template, e.g.:
        extra_schema='  "revoke_ids": [int, int, ...]'

    Single-round (default `max_rounds=1`) preserves the legacy single
    LLM-call behavior every existing call site relies on.

    Multi-round (`max_rounds > 1`) is the fractal "deeper trinity"
    mode. Each round after the first receives the prior round's
    stances + final_answer + confidence and is explicitly asked to
    reconsider. The debate stops as soon as a round converges
    (unanimous stances OR confidence ≥ `converge_threshold`) or
    `max_rounds` is exhausted. Use this for tasks where single-round
    accuracy is insufficient — e.g. date arithmetic, age intervals,
    multi-hop entity matches.

    On any failure (LLM error, JSON parse fail, missing final_answer),
    returns None for round 1; for later rounds, returns the most
    recent successfully-parsed round.
    """
    if not llm:
        return None
    extra_keys_summary, extra_schema_block = _format_extra(extra_schema)

    # --- Round 1 (legacy behavior) ---
    prompt_r1 = _PROMPT.format(
        task=task,
        evidence=evidence[:max_evidence_chars],
        extra_keys_summary=extra_keys_summary,
        extra_schema_block=extra_schema_block,
    )
    raw = _call_llm(prompt_r1, llm)
    result = _parse_json(raw)
    if result is None:
        return None
    if max_rounds <= 1:
        return result

    # --- Refinement rounds (multi-round mode) ---
    for round_idx in range(2, int(max_rounds) + 1):
        if _is_converged(result, converge_threshold):
            return result
        prior_block = _format_prior_stances(result)
        prior_final = str(result.get("final_answer") or "")[:300]
        try:
            prior_conf = float(result.get("confidence") or 0.0)
        except (TypeError, ValueError):
            prior_conf = 0.0
        prompt_rN = _REFINE_PROMPT.format(
            round_idx=round_idx,
            prior_idx=round_idx - 1,
            task=task,
            evidence=evidence[:max_evidence_chars],
            prior_block=prior_block,
            prior_final=prior_final,
            prior_conf=f"{prior_conf:.2f}",
            extra_keys_summary=extra_keys_summary,
            extra_schema_block=extra_schema_block,
        )
        raw_n = _call_llm(prompt_rN, llm)
        new_result = _parse_json(raw_n)
        if new_result is not None:
            result = new_result
        # If a refinement round fails to parse, KEEP the prior result
        # (better than returning None and losing what we already had).
    return result
