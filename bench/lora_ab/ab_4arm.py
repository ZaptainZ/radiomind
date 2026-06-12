"""LoRA-1b — 4-arm A/B driver (2026-06-12).

Arms on the IDENTICAL personal held-out query set (data_gen valid.jsonl,
never seen in training):
  A  MLX-direct base
  B  MLX-direct + adapter
  C  fused -> GGUF f16  -> Ollama
  D  fused -> GGUF q8_0 -> Ollama

Dual metrics per user ruling:
  - token-overlap vs gold (reuse eval.overlap_score)
  - LLM judge (qwen-max via DashScope): pairwise arm-vs-base with gold shown
Ollama timeouts are recorded as runtime_failure and EXCLUDED from quality
means — a timeout is not a quality loss.

Run under the mlx venv (~/rm-lora-exp/venv) — arms A/B need mlx_lm:
    ~/rm-lora-exp/venv/bin/python bench/lora_ab/ab_4arm.py \
        --adapter ~/rm-lora-exp/adapters \
        --valid ~/rm-lora-exp/data/valid.jsonl \
        --ollama-f16 radiomind-ab-f16 --ollama-q8 radiomind-ab-q8 \
        --out bench/lora_ab/lora1b-4arm.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eval import overlap_score  # noqa: E402  (pure function, stdlib only)

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

JUDGE_PROMPT = """You compare two assistant answers to a question about a specific user.
A reference answer (gold) written from the user's true profile is provided.

Question: {question}
Gold reference: {gold}

Answer 1: {a1}
Answer 2: {a2}

Which answer better matches the gold reference's substance (specific facts,
habits, preferences)? Generic advice that ignores the user's profile is worse.
Reply with EXACTLY one of: 1 / 2 / tie, then one short reason."""


def load_valid(path: Path, max_q: int | None) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        msgs = json.loads(line)["messages"]
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        gold = next((m["content"] for m in msgs if m["role"] == "assistant"), "")
        if user and gold:
            rows.append({"system": system, "q": user, "gold": gold})
    return rows[:max_q] if max_q else rows


def mlx_generate(model_id: str, adapter: str | None, system: str, q: str,
                 max_tokens: int = 200) -> str:
    from mlx_lm import load, generate
    key = (model_id, adapter or "")
    cache = mlx_generate.__dict__.setdefault("_cache", {})
    if key not in cache:
        cache[key] = load(model_id, adapter_path=adapter) if adapter else load(model_id)
    model, tok = cache[key]
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": q}]
    prompt = tok.apply_chat_template(msgs, add_generation_prompt=True)
    return generate(model, tok, prompt=prompt, max_tokens=max_tokens)


def ollama_generate(model: str, system: str, q: str, timeout: int) -> tuple[str | None, str | None]:
    """Returns (answer, runtime_failure). Timeout/conn errors are runtime
    failures, not quality losses."""
    payload = {"model": model, "prompt": q, "system": system, "stream": False}
    req = urllib.request.Request(
        f"{OLLAMA_URL.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()).get("response", ""), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:120]


def judge_pair(cfg: dict, question: str, gold: str, base_ans: str, other_ans: str) -> str:
    """Returns 'win' (other beats base) / 'loss' / 'tie' / 'judge_error'."""
    prompt = JUDGE_PROMPT.format(question=question, gold=gold[:600],
                                 a1=base_ans[:600], a2=other_ans[:600])
    req = urllib.request.Request(
        f"{cfg['base_url'].rstrip('/')}/chat/completions",
        data=json.dumps({"model": "qwen-max",
                         "messages": [{"role": "user", "content": prompt}],
                         "max_tokens": 120, "temperature": 0.0}).encode(),
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = json.loads(r.read())["choices"][0]["message"]["content"].strip().lower()
    except Exception:
        return "judge_error"
    head = text.split()[0].strip(".:,") if text.split() else ""
    if head == "2":
        return "win"
    if head == "1":
        return "loss"
    if head.startswith("tie"):
        return "tie"
    return "judge_error"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--adapter", required=True)
    p.add_argument("--valid", required=True)
    p.add_argument("--mlx-base", default="mlx-community/Qwen2.5-0.5B-Instruct-4bit")
    p.add_argument("--ollama-f16", default="")
    p.add_argument("--ollama-q8", default="")
    p.add_argument("--ollama-timeout", type=int, default=60)
    p.add_argument("--max-q", type=int, default=0)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    queries = load_valid(Path(args.valid), args.max_q or None)
    dash = tomllib.loads((Path.home() / ".radiomind" / "config.toml").read_text())["llm"]["dashscope"]

    arms = {"A_mlx_base": lambda s, q: (mlx_generate(args.mlx_base, None, s, q), None),
            "B_mlx_adapter": lambda s, q: (mlx_generate(args.mlx_base, args.adapter, s, q), None)}
    if args.ollama_f16:
        arms["C_ollama_f16"] = lambda s, q: ollama_generate(args.ollama_f16, s, q, args.ollama_timeout)
    if args.ollama_q8:
        arms["D_ollama_q8"] = lambda s, q: ollama_generate(args.ollama_q8, s, q, args.ollama_timeout)

    per_q, agg = [], {a: {"overlap": [], "runtime_failures": 0,
                          "win": 0, "loss": 0, "tie": 0, "judge_error": 0}
                      for a in arms}
    for i, qr in enumerate(queries):
        rec = {"q": qr["q"], "gold": qr["gold"], "arms": {}}
        answers = {}
        for name, fn in arms.items():
            t0 = time.time()
            ans, fail = fn(qr["system"], qr["q"])
            entry = {"latency_s": round(time.time() - t0, 1)}
            if fail:
                agg[name]["runtime_failures"] += 1
                entry["runtime_failure"] = fail
            else:
                sc = overlap_score(ans, [qr["gold"]])
                agg[name]["overlap"].append(sc)
                entry.update({"answer": ans[:400], "overlap": round(sc, 4)})
                answers[name] = ans
            rec["arms"][name] = entry
        base_ans = answers.get("A_mlx_base", "")
        for name in arms:
            if name == "A_mlx_base" or name not in answers or not base_ans:
                continue
            verdict = judge_pair(dash, qr["q"], qr["gold"], base_ans, answers[name])
            agg[name][verdict if verdict in ("win", "loss", "tie") else "judge_error"] += 1
            rec["arms"][name]["judge_vs_base"] = verdict
        per_q.append(rec)
        print(f"[{i+1}/{len(queries)}] " + " ".join(
            f"{n}={rec['arms'][n].get('overlap', 'RTFAIL')}" for n in arms), flush=True)

    summary = {}
    for name, s in agg.items():
        summary[name] = {
            "n_scored": len(s["overlap"]),
            "mean_overlap": round(statistics.mean(s["overlap"]), 4) if s["overlap"] else None,
            "runtime_failures": s["runtime_failures"],
            **({"judge_vs_base": f"{s['win']}W/{s['loss']}L/{s['tie']}T"
                + (f" ({s['judge_error']} judge_err)" if s["judge_error"] else "")}
               if name != "A_mlx_base" else {}),
        }
    out = {"experiment": "LoRA-1b 4-arm A/B", "date": "2026-06-12",
           "mlx_base": args.mlx_base, "adapter": args.adapter,
           "valid_set": args.valid, "n_queries": len(queries),
           "summary": summary, "per_query": per_q}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
