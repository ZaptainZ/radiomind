"""Generic three-way debate primitive.

The trinity is the primitive: **three opposing analytical stances
triangulate a conclusion**. It is NOT a fixed cast of named roles. The
stances are task-dependent and picked by the LLM based on what tensions
the task surfaces.

Examples of stance triples that emerge from different tasks:
- counting evidence:  conservative / inclusive / consolidative
- timeline question:  anchor-based / chain-based / window-based
- open-domain pick:   literal-from-evidence / inferred / abstention-safe
- habit mining:       stability-first / novelty-first / parsimony-first

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
   synthesize; when evidence is thin, abstain ("insufficient").

Return STRICT JSON only with these keys{extra_keys_summary}:
{{
  "stances": [
    {{"name": "...", "emphasis": "...", "conclusion": "..."}},
    {{"name": "...", "emphasis": "...", "conclusion": "..."}},
    {{"name": "...", "emphasis": "...", "conclusion": "..."}}
  ],
  "final_answer": "..."{extra_schema_block}
}}"""


def debate(
    task: str,
    evidence: str,
    llm: Any,
    extra_schema: str = "",
    max_evidence_chars: int = 6000,
) -> dict | None:
    """Run a three-stance debate and return parsed JSON.

    Returns the parsed JSON dict with at least `stances` + `final_answer`,
    plus any additional fields the caller requested via `extra_schema`.
    `extra_schema` is a short schema fragment injected into the prompt
    template, e.g.:
        extra_schema='  "revoke_ids": [int, int, ...]'
    The LLM is shown the full contract so it outputs the extra key.
    On any failure (LLM error, JSON parse fail, missing final_answer),
    returns None.
    """
    if not llm:
        return None
    extra_keys_summary = ""
    extra_schema_block = ""
    if extra_schema.strip():
        extra_keys_summary = " plus the caller-requested keys"
        extra_schema_block = f",\n{extra_schema.rstrip(',')}"
    prompt = _PROMPT.format(
        task=task,
        evidence=evidence[:max_evidence_chars],
        extra_keys_summary=extra_keys_summary,
        extra_schema_block=extra_schema_block,
    )
    try:
        if hasattr(llm, "generate"):
            raw = getattr(llm.generate(prompt, system="Output only strict JSON."), "text", "") or ""
        else:
            raw = llm(prompt, "Output only strict JSON.")
    except Exception:
        return None
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
