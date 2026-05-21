"""Direct LLM A/B test: V7 evidence-candidate injection vs V6.6.p2 baseline.

Skips ingest + retrieve. Pulls retrieved memories straight from V6.6.p2
answer text (its "Step 1: SCAN ALL MEMORIES" section), then sends two
prompts to deepseek-v3.2 via dashscope:
  A) Mem0 format prompt with raw memories          (= V6.3 baseline)
  B) Mem0 format prompt + EVIDENCE CANDIDATES head (= V7 Step 1)

Each is one LLM call (~30s). Compares answers head-to-head on selected
flip qids. Avoids the DashScope embedder hang seen in full-pipeline runs.

Usage:
    PYTHONPATH=$(pwd)/src python bench/end_to_end/direct_llm_ab.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from radiomind.core.evidence_candidates import (
    extract_evidence_candidates,
    render_evidence_candidates,
)
from mem0_protocol.locomo_prompts import (
    get_answer_generation_prompt,
)

# Bypass any system proxy (DashScope sometimes hangs on proxied connections)
_BYPASS_PROXY_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
)


def llm_call(prompt: str, profile_cfg: dict, model: str,
             max_tokens: int = 1500, timeout: int = 90,
             system: str | None = None) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    req = urllib.request.Request(
        f"{profile_cfg['base_url'].rstrip('/')}/chat/completions",
        data=json.dumps({
            "model": model, "messages": messages,
            "max_tokens": max_tokens, "temperature": 0.0,
        }).encode(),
        headers={
            "Authorization": f"Bearer {profile_cfg['api_key']}",
            "Content-Type": "application/json",
        },
    )
    with _BYPASS_PROXY_OPENER.open(req, timeout=timeout) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"].strip()


_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _human_to_iso(s: str) -> str:
    """Convert 'Wednesday, February 08, 2023' → '2023-02-08'. Best effort."""
    s = s.strip().rstrip(":").strip()
    # Try ISO already
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # 'Weekday, Month DD, YYYY' or 'Month DD, YYYY'
    m = re.search(
        r"(?:\w+,\s+)?(\w+)\s+(\d{1,2}),?\s+(\d{4})", s,
    )
    if m:
        mon = _MONTH_MAP.get(m.group(1).lower())
        if mon:
            return f"{m.group(3)}-{mon}-{int(m.group(2)):02d}"
    return s  # fallback (mem0 will truncate to first 10 chars)


def parse_memories_from_answer(answer: str) -> list[dict]:
    """Extract memory list from a V6.6 LLM answer text."""
    memories = []
    pat = re.compile(
        r"^\s*(?:-|\d+\.)\s+\(([^)]{6,40})\)\s*:?\s*([^\n]+)$",
        re.MULTILINE,
    )
    for m in pat.finditer(answer):
        date = m.group(1).strip()
        iso = _human_to_iso(date)
        content = m.group(2).strip()
        if len(content) < 5:
            continue
        memories.append({
            "memory": content,
            "date": iso,
            "created_at": iso,
        })
    return memories


def load_dashscope_cfg() -> tuple[dict, str]:
    """Read ~/.radiomind/config.toml dashscope profile."""
    import tomllib
    cfg_path = Path.home() / ".radiomind" / "config.toml"
    cfg = tomllib.loads(cfg_path.read_text())
    profile = cfg["llm"]["dashscope"]
    return profile, profile.get("model", "deepseek-v3.2")


def run_ab(qid: str, q: str, gold: str, baseline_answer: str,
           profile: dict, model: str) -> dict:
    memories = parse_memories_from_answer(baseline_answer)
    if len(memories) < 1:
        return {"qid": qid, "skip": "no parseable memories"}

    # Build base prompt (V6.3-style, no evidence block)
    base_prompt = get_answer_generation_prompt(q, memories, reference_date="2023")

    # Build V7 prompt (with evidence block prepended)
    candidates = extract_evidence_candidates(q, memories, top_k=5)
    evidence_block = render_evidence_candidates(candidates)
    v7_prompt = evidence_block + base_prompt

    print(f"\n{'=' * 90}")
    print(f"qid={qid}  gold={gold!r}  candidates={len(candidates)}")
    print(f"{'=' * 90}")
    print(f"  Top candidates:")
    for c in candidates[:3]:
        tr = f" [{c.temporal_role}]" if c.temporal_role else ""
        print(f"    - {c.candidate!r} conf={c.confidence:.2f}{tr}")

    # Call A: baseline
    t0 = time.time()
    try:
        ans_a = llm_call(base_prompt, profile, model)
    except Exception as e:
        ans_a = f"[error: {e}]"
    dt_a = time.time() - t0

    # Call B: V7
    t0 = time.time()
    try:
        ans_b = llm_call(v7_prompt, profile, model)
    except Exception as e:
        ans_b = f"[error: {e}]"
    dt_b = time.time() - t0

    print(f"\n  [A] baseline ({dt_a:.1f}s):")
    print(f"    head: {ans_a[:200]}")
    print(f"    tail: ...{ans_a[-200:]}")
    print(f"\n  [B] V7 Step 1 ({dt_b:.1f}s):")
    print(f"    head: {ans_b[:200]}")
    print(f"    tail: ...{ans_b[-200:]}")

    # Quick gold-token check
    gold_low = gold.lower()
    gold_tokens = set(re.findall(r"\b[a-zA-Z]{4,}\b", gold_low)) - {
        "with", "from", "that", "this", "have",
    }
    gold_tokens.update(re.findall(r"\d{4}", gold_low))
    if re.search(r"few years (ago|before|earlier)", gold_low):
        gold_tokens.add("few years")
    a_hit = any(t in ans_a.lower() for t in gold_tokens)
    b_hit = any(t in ans_b.lower() for t in gold_tokens)
    print(f"\n  gold tokens: {sorted(gold_tokens)}")
    print(f"  [A] contains gold token: {'✓' if a_hit else '✗'}")
    print(f"  [B] contains gold token: {'✓' if b_hit else '✗'}")
    return {"qid": qid, "a_hit": a_hit, "b_hit": b_hit,
            "a_ans": ans_a, "b_ans": ans_b, "dt_a": dt_a, "dt_b": dt_b}


def main():
    # All 10 flip qids — includes ones where retrieve already missed gold
    # (c2 fin, c4 Seattle, c5 Voyageurs, c9 Calvin) — those serve as
    # regression check: V7 evidence block should NOT make them worse.
    target_qids = [
        "c1_69a7c9bffe",  # Gina tattoo (relative phrase candidate)
        "c2_29183ecb5e",  # John financial (retrieve missed wealthy/middle-class)
        "c2_b4b43181aa",  # Maria community work (Aug 4 2023)
        "c3_2656e2c771",  # count "two" vs evidence "third" (reasoning needed)
        "c3_94f06e1a00",  # Joanna Tilly (proper noun)
        "c3_a9fddfe69b",  # Nate dragons (topic keyword)
        "c4_5cfba98ae8",  # Seattle (retrieve missed Seattle)
        "c5_dac00a436e",  # Voyageurs (retrieve missed park name)
        "c6_9da9f73c2a",  # Sept 2022 (date + next month inference)
        "c9_5ab522b5c7",  # Calvin/Dave abstraction (reasoning needed)
    ]
    profile, model = load_dashscope_cfg()
    base_path = Path(__file__).parent / "validation" / "v6.6-path2-flip10-smoke.json"
    data = json.loads(base_path.read_text())
    recs = {r["question_id"]: r for r in data["per_query"]}

    print(f"Running A/B test on {len(target_qids)} qids, model={model}")
    results = []
    for qid in target_qids:
        r = recs.get(qid)
        if not r:
            print(f"  skip {qid}: not in baseline")
            continue
        out = run_ab(qid, r["q"], r["gold"], r["answer"], profile, model)
        results.append(out)

    # Aggregate
    n = sum(1 for r in results if "skip" not in r)
    a_n = sum(1 for r in results if r.get("a_hit"))
    b_n = sum(1 for r in results if r.get("b_hit"))
    print(f"\n{'=' * 90}")
    print(f"AGGREGATE ({n} qids):")
    print(f"  [A] baseline:    gold-token hit in answer = {a_n}/{n}")
    print(f"  [B] V7 Step 1:   gold-token hit in answer = {b_n}/{n}")

    out_path = Path(__file__).parent / "validation" / "v7-step1-direct-ab.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n  detail: {out_path}")


if __name__ == "__main__":
    main()
