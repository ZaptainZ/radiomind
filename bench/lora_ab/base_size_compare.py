"""Compare base model size — Qwen2.5-0.5B-4bit vs Qwen3-4B-Instruct-2507-4bit.

No LoRA on either side. Measures pure capability lift from going 0.5B → 4B
(8× parameter count). Uses the same LLM-as-judge (qwen-max) methodology
as llm_judge.py.

Why run this: user asked "can't we just use a bigger base model?" The
answer is "yes, dramatically better" — this benchmark puts a number on
"dramatically better".
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path


QUESTIONS = [
    "告诉我一件关于我的事",
    "我有什么明显的偏好",
    "我在工程上的典型做法",
    "我会怎么处理复杂依赖",
    "描述我的技术品味",
    "我在 Rust 里有什么习惯",
    "我在 iOS 开发中偏好什么",
    "我的代码风格倾向",
]


JUDGE_PROMPT = """你在比较两个 AI 助手对"{user_question}"的回答。

**用户档案**：
{user_profile}

**回答**：
回答 1：{answer_1}

回答 2：{answer_2}

评估标准（0-10 分）：
1. personalization：是否体现了对这个用户的了解？
2. groundedness：能在档案中找到证据吗？
3. coherence：是否连贯可读？

格式（严格）：
ANSWER_1: personalization=<n> groundedness=<n> coherence=<n>
ANSWER_2: personalization=<n> groundedness=<n> coherence=<n>
PREFERENCE: <1 | 2 | tie>
REASON: <一句话>"""


def call_qwen(prompt: str, config_path: Path, model: str = "qwen-max") -> str:
    import tomllib
    cfg = tomllib.loads(config_path.read_text())
    oc = cfg["llm"]["openai"]
    import urllib.request
    req = urllib.request.Request(
        f"{oc['base_url'].rstrip('/')}/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 400,
            "temperature": 0.0,
        }).encode(),
        headers={"Authorization": f"Bearer {oc['api_key']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"]


def parse_judgment(text: str) -> dict:
    out = {"ans1": {"personalization": 0, "groundedness": 0, "coherence": 0},
           "ans2": {"personalization": 0, "groundedness": 0, "coherence": 0},
           "preference": "tie", "reason": "", "raw": text}
    for line in text.strip().split("\n"):
        L = line.strip()
        if L.startswith("ANSWER_1:") or L.startswith("ANSWER_2:"):
            key = "ans1" if L.startswith("ANSWER_1:") else "ans2"
            for kv in L.split(":", 1)[1].strip().split():
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try: out[key][k.strip()] = int(float(v))
                    except ValueError: pass
        elif L.startswith("PREFERENCE:"):
            p = L.split(":", 1)[1].strip().lower()
            if p in ("1", "2", "tie"): out["preference"] = p
        elif L.startswith("REASON:"):
            out["reason"] = L.split(":", 1)[1].strip()
    return out


_CACHE: dict = {}
def load_mlx(model_id: str):
    if model_id in _CACHE: return _CACHE[model_id]
    from mlx_lm import load
    m, t = load(model_id)
    _CACHE[model_id] = (m, t)
    return m, t


def gen(model_id: str, question: str, max_tokens: int = 150) -> str:
    from mlx_lm import generate
    m, tok = load_mlx(model_id)
    prompt = tok.apply_chat_template([{"role": "user", "content": question}],
                                      add_generation_prompt=True, tokenize=False)
    return generate(m, tok, prompt=prompt, max_tokens=max_tokens, verbose=False).strip()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--small", default="mlx-community/Qwen2.5-0.5B-Instruct-4bit")
    p.add_argument("--big", default="mlx-community/Qwen3-4B-Instruct-2507-4bit")
    p.add_argument("--habits", required=True)
    p.add_argument("--config", default=str(Path.home() / ".radiomind" / "config.toml"))
    p.add_argument("--judge-model", default="qwen-max")
    p.add_argument("--out", default="bench/lora_ab/base-size-compare.json")
    args = p.parse_args()

    habits = json.loads(Path(args.habits).read_text())
    profile = "\n".join(f"- {h['description']}" for h in habits if h.get("description"))
    rng = random.Random(20260416)

    print(f"Loading {args.small}...", flush=True)
    gen(args.small, "warmup", max_tokens=3)
    print(f"Loading {args.big}...", flush=True)
    gen(args.big, "warmup", max_tokens=3)

    results = []
    big_wins = 0; small_wins = 0; ties = 0
    for q in QUESTIONS:
        a_small = gen(args.small, q)
        a_big = gen(args.big, q)
        big_in_slot_1 = rng.random() > 0.5
        if big_in_slot_1: a1, a2 = a_big, a_small
        else: a1, a2 = a_small, a_big
        try:
            raw = call_qwen(JUDGE_PROMPT.format(
                user_question=q, user_profile=profile[:1500],
                answer_1=a1[:400], answer_2=a2[:400]), Path(args.config), model=args.judge_model)
            j = parse_judgment(raw)
        except Exception as e:
            print(f"  Q judge error: {e}", flush=True); continue

        if j["preference"] == "1":
            winner = "big" if big_in_slot_1 else "small"
        elif j["preference"] == "2":
            winner = "small" if big_in_slot_1 else "big"
        else:
            winner = "tie"
        if winner == "big": big_wins += 1
        elif winner == "small": small_wins += 1
        else: ties += 1

        big_s = j["ans1"] if big_in_slot_1 else j["ans2"]
        small_s = j["ans2"] if big_in_slot_1 else j["ans1"]
        results.append({
            "q": q,
            "small_ans": a_small, "big_ans": a_big,
            "small_scores": small_s, "big_scores": big_s,
            "winner": winner, "reason": j["reason"],
        })
        print(f"  Q: winner={winner}  big={big_s}  small={small_s}", flush=True)

    def _mean(k):
        if not results: return 0, 0
        return (round(statistics.mean(r["big_scores"].get(k, 0) for r in results), 2),
                round(statistics.mean(r["small_scores"].get(k, 0) for r in results), 2))
    p_b, p_s = _mean("personalization")
    g_b, g_s = _mean("groundedness")
    c_b, c_s = _mean("coherence")

    report = {
        "big_model": args.big, "small_model": args.small,
        "judge_model": args.judge_model, "n": len(results),
        "big_wins": big_wins, "small_wins": small_wins, "ties": ties,
        "mean_scores": {
            "personalization": {"big": p_b, "small": p_s, "delta": round(p_b-p_s,2)},
            "groundedness":    {"big": g_b, "small": g_s, "delta": round(g_b-g_s,2)},
            "coherence":       {"big": c_b, "small": c_s, "delta": round(c_b-c_s,2)},
        },
        "per_query": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n=== Base-size comparison (n={len(results)}) ===", flush=True)
    print(f"  preference: big {big_wins} / small {small_wins} / tie {ties}", flush=True)
    print(f"  personalization:  big {p_b} vs small {p_s}  (Δ {p_b-p_s:+.2f})", flush=True)
    print(f"  groundedness:     big {g_b} vs small {g_s}  (Δ {g_b-g_s:+.2f})", flush=True)
    print(f"  coherence:        big {c_b} vs small {c_s}  (Δ {c_b-c_s:+.2f})", flush=True)
    print(f"  saved → {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
