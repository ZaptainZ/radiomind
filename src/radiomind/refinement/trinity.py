"""Trinity — the core composable decision primitive.

The trinity is **the** decision primitive in RadioMind. Every place
that needs to triangulate a conclusion from competing pulls — at any
abstraction level, in any layer — should reach for `debate()` rather
than ad-hoc voting / single-LLM calls. Three independent dimensions
let it adapt to the task at hand:

  ┌─ 多方  n_stances ──── how many opposing views (default 3 = trinity)
  │     2 = adversarial pair (rare; tends to merge or one dominates)
  │     3 = trinity (the sweet spot — see DMAD paper)
  │     4-5 = multi-interest balance (e.g. ROI/risk/liquidity/opportunity)
  │     6-7 = strategic council (rare; mainly for high-stakes governance)
  │
  ├─ 多轮  max_rounds ─── refinement passes (default 1)
  │     1 = one-shot debate (legacy)
  │     2-3 = iterative refinement; round N sees round N-1's stances
  │            and is asked to reconsider. Stops on convergence
  │            (unanimous OR confidence ≥ threshold).
  │
  └─ 多层  sub_trinity_depth ─ recursive depth (default 0)
        0 = flat (no recursion)
        1 = stances with low individual confidence spawn an inner
            trinity to deepen their reasoning
        ≥2 = inner trinities can themselves recurse

Stances are NOT a fixed cast of named roles — the LLM picks the
opposing stances task-by-task. Examples:

  counting evidence:    conservative / inclusive / consolidative
  timeline question:    anchor-based / chain-based / window-based
  open-domain pick:     literal-from-evidence / inferred / abstention-safe
  habit mining:         stability-first / novelty-first / parsimony-first
  abstain decision:     literal-support / plausible-inference / strict-abstain
  entity disambiguation: frequency / context / attribute

Convenience profiles for common shapes:

  debate.fast(...)     = (1 round,  no recursion)
  debate.balanced(...) = (2 rounds, no recursion)
  debate.deep(...)     = (3 rounds, depth=1)
  debate.parties(N,..) = (N stances, 1 round)

Callers that need extra structured output (e.g. "revoke": [ids],
"final_members": [names]) pass `extra_schema` to have the LLM include
those keys alongside the standard schema.
"""
from __future__ import annotations

import json
import re
from typing import Any


# Agent role library. Each role is an "agent 侧写" — telling the LLM
# WHO it is and WHAT TASK it is performing in this trinity call.
# This is RadioMind's "agent 侧写" methodology elevated to a first-class
# trinity parameter. Without it, trinity.debate defaults to the V5
# "answerer" role whose prompt instructs LLM to abstain on thin evidence
# — which silently broke V6.5 question-intent trinity (the LLM thought
# it was answering, not decomposing).
_AGENT_ROLES: dict[str, str] = {
    "answerer": (
        "You triangulate an answer by arguing from {n_stances} distinct opposing "
        "stances. The task names a question to ANSWER; the evidence is your "
        "source of truth. When stances partially agree, synthesize; when "
        "evidence is thin, abstain (\"insufficient\")."
    ),
    "question-intent-analyzer": (
        "You are a QUESTION INTENT ANALYZER — a LINGUIST examining the "
        "structure and intent of a question, NOT an answerer.\n"
        "\n"
        "ROLE BOUNDARY (read carefully):\n"
        "- The text under 'Question:' is the OBJECT you analyze, like a "
        "sentence handed to a syntactician. It is NOT a question directed "
        "at you to answer.\n"
        "- Your output describes the SHAPE the answer should take "
        "(granularity, form, focus_entity_type). You produce ZERO answer "
        "content. You never name the answer, never guess at the answer, "
        "never assess whether the answer is knowable.\n"
        "- 'Evidence: (question-only)' is BY DESIGN. Memory/context is "
        "IRRELEVANT to your task — you analyze the question IN ISOLATION. "
        "If you find yourself thinking 'but I don't have enough info to "
        "answer', STOP — that is the answerer's worry, not yours.\n"
        "\n"
        "HARD CONSTRAINTS (your output is REJECTED if violated):\n"
        "1. NEVER output 'insufficient', 'unanswerable', 'cannot determine', "
        "or similar in final_answer. Every question has a characterizable "
        "intent. Example: even 'tell me something' has intent "
        "(granularity=description, form=sentence).\n"
        "2. Each stance MUST analyze a DIMENSION of question intent "
        "(literal form / semantic intent / answer shape / temporal "
        "precision / etc.). FORBIDDEN stance themes: 'Missing entity', "
        "'Ambiguity Critique', 'Skeptic', 'Insufficient context', "
        "'Cannot resolve'. These are answerer concerns. Reject them.\n"
        "3. final_answer must be a CHARACTERIZATION of the question "
        "(what shape of answer it expects), e.g. 'asks for an integer "
        "count of distinct items', NOT a refusal.\n"
        "\n"
        "EXAMPLES OF CORRECT ROLE EXECUTION:\n"
        "  Q: 'What is X's favorite book series about?'\n"
        "  ✓ granularity=concept, form=topic, focus_entity_type=book_series\n"
        "  ✓ final_answer='asks for the theme/subject matter of a series'\n"
        "  ✗ NOT 'cannot determine without knowing who X is'\n"
        "\n"
        "  Q: 'How many of X's writings made the big screen?'\n"
        "  ✓ granularity=specific_entity, form=integer, focus_entity_type=count\n"
        "  ✓ final_answer='asks for a cardinal count of film adaptations'\n"
        "  ✗ NOT 'insufficient — unclear which X'\n"
        "\n"
        "Your output is consumed by a DOWNSTREAM answerer agent that DOES "
        "have memory. You tell that agent what shape of answer to produce; "
        "the agent handles the rest. STAY IN YOUR LANE."
    ),
}


_PROMPT = """{agent_role_preamble}

Task: {task}

Evidence:
{evidence}

Work in three passes:
1. Identify {n_stances} opposing analytical stances a careful analyst could take
   on THIS task. Each stance: SHORT_NAME + one-line emphasis. They must
   genuinely oppose (not rewordings of one view).
2. For each stance, independently derive its conclusion from the evidence.
   Each stance MUST include a per-stance `confidence` (0..1) — its own
   probability that ITS conclusion is correct. Low individual confidence
   signals to upstream layers that the stance may benefit from deeper
   sub-debate.
3. Reconcile into one final answer per your role above. Always
   include an overall `confidence` (0..1) field — your honest probability
   that the final_answer is correct.

Return STRICT JSON only with these keys{extra_keys_summary}:
{{
  "stances": [
{stance_template_block}
  ],
  "final_answer": "...",
  "confidence": 0.0{extra_schema_block}
}}"""


_REFINE_PROMPT = """{agent_role_preamble}

You are in REFINEMENT ROUND {round_idx} of a multi-round trinity debate ({n_stances} stances).

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
- The {n_stances} stances must remain genuinely opposing (you can re-pick
  the stance set if the prior set wasn't the best fit).
- Re-derive the final_answer with full self-honesty. If you now
  realise the prior answer was wrong, say so and give the corrected
  answer. Update confidence accordingly — higher only if the new
  reasoning is genuinely more grounded.

Return STRICT JSON in the SAME schema as round {prior_idx}{extra_keys_summary}:
{{
  "stances": [
{stance_template_block}
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


def _stance_template_block(n: int) -> str:
    """Render N JSON stance placeholders for the prompt schema."""
    n = max(2, min(int(n), 7))
    line = (
        '    {"name": "...", "emphasis": "...", "conclusion": "...", '
        '"confidence": 0.0}'
    )
    items = [line] * n
    return ",\n".join(items)


def debate(
    task: str,
    evidence: str,
    llm: Any,
    extra_schema: str = "",
    max_evidence_chars: int = 6000,
    max_rounds: int = 1,
    converge_threshold: float = 0.7,
    n_stances: int = 3,
    sub_trinity_depth: int = 0,
    sub_trinity_threshold: float = 0.5,
    agent_role: str = "answerer",
) -> dict | None:
    """Run an N-stance debate and return parsed JSON.

    Three orthogonal composition dimensions — pick what the task needs:

      n_stances           "多方"  — number of opposing stances
                                    (default 3; 2-7 supported)
      max_rounds          "多轮"  — refinement passes
                                    (default 1; >1 enables iterative
                                    debate that stops on convergence)
      sub_trinity_depth   "多层"  — recursive depth
                                    (default 0; >0 lets stances with
                                    individual confidence below
                                    `sub_trinity_threshold` spawn an
                                    inner debate at depth-1 to deepen
                                    their reasoning)

    Returns the parsed JSON dict with at least `stances` + `final_answer`
    + `confidence`, plus any additional fields the caller requested via
    `extra_schema` (e.g. `extra_schema='  "revoke_ids": [int, ...]'`).

    Convergence (multi-round) stops the loop when:
      - all stances agree (unanimous), OR
      - overall confidence ≥ `converge_threshold`, OR
      - `max_rounds` is exhausted.

    Recursion (sub-trinity) fires AFTER round 1 and BEFORE refinement
    rounds, replacing low-confidence stances' conclusions with the
    final_answer of an inner debate. This is the fractal application
    of trinity to itself — each weak stance independently triangulates.
    Cost is bounded by the number of weak stances × depth.

    On any failure (LLM error, JSON parse fail, missing final_answer),
    returns None for round 1; for later rounds, returns the most
    recent successfully-parsed round.
    """
    if not llm:
        return None
    n_stances = max(2, min(int(n_stances), 7))
    extra_keys_summary, extra_schema_block = _format_extra(extra_schema)
    stance_block = _stance_template_block(n_stances)

    # Resolve agent_role to its preamble (agent 侧写). Unknown role
    # values fall back to the default "answerer" role — callers can
    # pass a literal preamble string instead of a registered role
    # name if they need a one-off custom侧写.
    if agent_role in _AGENT_ROLES:
        agent_role_preamble = _AGENT_ROLES[agent_role].format(n_stances=n_stances)
    else:
        # Treat as literal preamble (caller-supplied custom role text).
        agent_role_preamble = agent_role

    # --- Round 1 ---
    prompt_r1 = _PROMPT.format(
        agent_role_preamble=agent_role_preamble,
        n_stances=n_stances,
        task=task,
        evidence=evidence[:max_evidence_chars],
        extra_keys_summary=extra_keys_summary,
        extra_schema_block=extra_schema_block,
        stance_template_block=stance_block,
    )
    raw = _call_llm(prompt_r1, llm)
    result = _parse_json(raw)
    if result is None:
        return None

    # --- Sub-trinity recursion (多层) ---
    # Stances with low individual confidence spawn an inner debate at
    # depth-1 to refine their conclusion. Outer final_answer keeps round
    # 1's value; refinement rounds (if max_rounds > 1) will re-aggregate.
    if sub_trinity_depth > 0:
        result = _expand_low_confidence_stances(
            result, task, evidence, llm,
            depth=sub_trinity_depth,
            threshold=sub_trinity_threshold,
            max_evidence_chars=max_evidence_chars,
        )

    if max_rounds <= 1:
        return result

    # --- Refinement rounds (多轮) ---
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
            agent_role_preamble=agent_role_preamble,
            n_stances=n_stances,
            round_idx=round_idx,
            prior_idx=round_idx - 1,
            task=task,
            evidence=evidence[:max_evidence_chars],
            prior_block=prior_block,
            prior_final=prior_final,
            prior_conf=f"{prior_conf:.2f}",
            extra_keys_summary=extra_keys_summary,
            extra_schema_block=extra_schema_block,
            stance_template_block=stance_block,
        )
        raw_n = _call_llm(prompt_rN, llm)
        new_result = _parse_json(raw_n)
        if new_result is not None:
            result = new_result
            # Optional: also recurse on the new round's weak stances.
            if sub_trinity_depth > 0:
                result = _expand_low_confidence_stances(
                    result, task, evidence, llm,
                    depth=sub_trinity_depth,
                    threshold=sub_trinity_threshold,
                    max_evidence_chars=max_evidence_chars,
                )
        # If a refinement round fails to parse, KEEP the prior result
        # (better than returning None and losing what we already had).
    return result


def _expand_low_confidence_stances(
    result: dict,
    parent_task: str,
    evidence: str,
    llm: Any,
    depth: int,
    threshold: float,
    max_evidence_chars: int,
) -> dict:
    """For each stance with individual confidence < threshold, spawn an
    inner debate (at depth-1) and replace the stance's conclusion with
    the inner debate's final_answer.

    No-op when no stance has reportable individual confidence below the
    threshold. Caps recursion at `depth` levels.
    """
    if depth <= 0:
        return result
    stances = result.get("stances") or []
    if not isinstance(stances, list):
        return result
    refined_any = False
    for stance in stances:
        if not isinstance(stance, dict):
            continue
        try:
            conf = float(stance.get("confidence"))
        except (TypeError, ValueError):
            continue
        if conf >= threshold:
            continue
        # Spawn a focused sub-debate for THIS stance's claim.
        sub_task = (
            f"Inner trinity for stance '{stance.get('name','?')}' from an "
            f"outer debate. The outer task was:\n  {parent_task[:300]}\n"
            f"This stance's prior conclusion (low confidence "
            f"{conf:.2f}): {stance.get('conclusion','')[:300]}\n"
            f"Re-examine the evidence and produce a refined conclusion "
            f"specifically from this stance's perspective ("
            f"{stance.get('emphasis','')}). Three sub-stances triangulate "
            f"the refinement: literal-support / plausible-inference / "
            f"strict-skepticism."
        )
        sub = debate(
            task=sub_task,
            evidence=evidence,
            llm=llm,
            max_rounds=1,
            n_stances=3,
            sub_trinity_depth=depth - 1,
            max_evidence_chars=max_evidence_chars,
        )
        if not sub:
            continue
        new_conclusion = str(sub.get("final_answer") or "").strip()
        if not new_conclusion:
            continue
        try:
            new_conf = float(sub.get("confidence") or conf)
        except (TypeError, ValueError):
            new_conf = conf
        stance["conclusion"] = new_conclusion
        stance["confidence"] = new_conf
        stance.setdefault("provenance", []).append("sub_trinity")
        refined_any = True
    if refined_any:
        # Mark on the outer result so callers can see recursion happened.
        result.setdefault("provenance", []).append(
            f"sub_trinity_depth={depth}"
        )
    return result


# --- Convenience profiles (按需选择，无需记参数) ---

def fast(task: str, evidence: str, llm: Any, **kwargs) -> dict | None:
    """Single-round 3-stance debate. The default lightweight shape.

    Equivalent to `debate(task, evidence, llm)` with all defaults.
    Use for: routine routing decisions, single-shot abstain checks,
    skill output votes — anywhere extra rounds are not worth the cost.
    """
    kwargs.setdefault("n_stances", 3)
    kwargs.setdefault("max_rounds", 1)
    kwargs.setdefault("sub_trinity_depth", 0)
    return debate(task, evidence, llm, **kwargs)


def balanced(task: str, evidence: str, llm: Any, **kwargs) -> dict | None:
    """Two-round 3-stance debate. Adds one refinement pass.

    Use when single-round answers occasionally drift but full depth is
    overkill — preference context extraction, entity disambiguation,
    class promotion at ingest.
    """
    kwargs.setdefault("n_stances", 3)
    kwargs.setdefault("max_rounds", 2)
    kwargs.setdefault("sub_trinity_depth", 0)
    return debate(task, evidence, llm, **kwargs)


def deep(task: str, evidence: str, llm: Any, **kwargs) -> dict | None:
    """Three-round 3-stance debate with depth-1 sub-trinity recursion.

    Use for precision-critical reasoning: date arithmetic, multi-hop
    inference, age intervals — tasks where single-round accuracy is
    too noisy and sub-stance refinement materially helps.
    """
    kwargs.setdefault("n_stances", 3)
    kwargs.setdefault("max_rounds", 3)
    kwargs.setdefault("sub_trinity_depth", 1)
    kwargs.setdefault("converge_threshold", 0.75)
    return debate(task, evidence, llm, **kwargs)


def parties(
    n: int, task: str, evidence: str, llm: Any, **kwargs
) -> dict | None:
    """N-party debate (n_stances = N). For multi-interest balance tasks
    where 3 isn't enough — e.g. (ROI / risk / liquidity / opportunity)
    has 4 genuinely orthogonal interests.

    n is clamped to [2, 7]. Defaults to single-round; combine with
    max_rounds= or sub_trinity_depth= as needed.
    """
    kwargs["n_stances"] = max(2, min(int(n), 7))
    kwargs.setdefault("max_rounds", 1)
    kwargs.setdefault("sub_trinity_depth", 0)
    return debate(task, evidence, llm, **kwargs)
