"""LLM-as-judge A/B for LoRA vs base — more rigorous than token overlap.

Overlap metric rewards verbose output whether or not it's actually
accurate. An LLM judge can evaluate:
  - Does the answer reflect knowledge about THIS user?
  - Is it grounded in user habits (not generic)?
  - Does it avoid hallucination?

Uses the Qwen API already configured in ~/.radiomind/config.toml
(qwen-max for judging — best of the tier).

Usage (with isolated sandbox containing adapter):
    python bench/lora_ab/llm_judge.py \\
        --adapter /tmp/rm-lora-test/models/lora/adapters \\
        --base mlx-community/Qwen2.5-0.5B-Instruct-4bit \\
        --habits /tmp/rm-lora-test/data/hdc/habits.json \\
        --out bench/lora_ab/llm-judge-ab.json
"""
from __future__ import annotations

import argparse
import json
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
    "我如何看待 AI 工具的使用",
    "我的代码风格倾向",
    "我对算法的兴趣方向",
    "我工作时会避免做什么",
    "我如何决定是否引入新依赖",
]


JUDGE_PROMPT = """你在评估一个 AI 助手对"{user_question}"这个问题的回答。

**用户档案**（来自用户的真实 habit 记忆，共 {n_habits} 条）：
{user_profile}

**两个 AI 回答（你不知道哪个是 A 哪个是 B 来自 LoRA）**：
回答 1：{answer_1}

回答 2：{answer_2}

**评估标准**（每项 0-10 分）：
1. personalization：回答多大程度反映了对"这个具体用户"的了解，而不是通用建议？
2. groundedness：回答的内容能多大程度从用户档案中找到对应证据？
3. coherence：回答是否连贯、可读、没有胡编乱造？

**输出格式**（严格遵守，不要多写）：
ANSWER_1: personalization=<n> groundedness=<n> coherence=<n>
ANSWER_2: personalization=<n> groundedness=<n> coherence=<n>
PREFERENCE: <1 | 2 | tie>
REASON: <一句话说明为什么>"""


def call_qwen(prompt: str, config_path: Path, model: str = "qwen-max") -> str:
    """Call Qwen via Dashscope (OpenAI-compatible)."""
    import tomllib
    cfg = tomllib.loads(config_path.read_text())
    openai_cfg = cfg["llm"]["openai"]
    base_url = openai_cfg["base_url"].rstrip("/")
    api_key = openai_cfg["api_key"]

    import urllib.request
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 400,
            "temperature": 0.0,
        }).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read())
    return body["choices"][0]["message"]["content"]


def parse_judgment(text: str) -> dict:
    out = {
        "ans1": {"personalization": 0, "groundedness": 0, "coherence": 0},
        "ans2": {"personalization": 0, "groundedness": 0, "coherence": 0},
        "preference": "tie",
        "reason": "",
        "raw": text,
    }
    for line in text.strip().split("\n"):
        L = line.strip()
        if L.startswith("ANSWER_1:") or L.startswith("ANSWER_2:"):
            key = "ans1" if L.startswith("ANSWER_1:") else "ans2"
            rest = L.split(":", 1)[1]
            for kv in rest.strip().split():
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try:
                        out[key][k.strip()] = int(float(v))
                    except ValueError:
                        pass
        elif L.startswith("PREFERENCE:"):
            pref = L.split(":", 1)[1].strip().lower()
            if pref in ("1", "2", "tie"):
                out["preference"] = pref
        elif L.startswith("REASON:"):
            out["reason"] = L.split(":", 1)[1].strip()
    return out


def generate_with_mlx(model_id: str, adapter_path: str | None, question: str, max_tokens: int = 150) -> str:
    from mlx_lm import load, generate
    cache_key = (model_id, adapter_path)
    if not hasattr(generate_with_mlx, "_cache"):
        generate_with_mlx._cache = {}
    if cache_key not in generate_with_mlx._cache:
        generate_with_mlx._cache[cache_key] = load(model_id, adapter_path=adapter_path) if adapter_path else load(model_id)
    model, tok = generate_with_mlx._cache[cache_key]
    prompt = tok.apply_chat_template(
        [{"role": "user", "content": question}],
        add_generation_prompt=True,
        tokenize=False,
    )
    return generate(model, tok, prompt=prompt, max_tokens=max_tokens, verbose=False).strip()


def main() -> int:
    import random

    p = argparse.ArgumentParser()
    p.add_argument("--adapter", required=True)
    p.add_argument("--base", default="mlx-community/Qwen2.5-0.5B-Instruct-4bit")
    p.add_argument("--habits", required=True, help="Path to habits.json")
    p.add_argument("--config", default=str(Path.home() / ".radiomind" / "config.toml"))
    p.add_argument("--judge-model", default="qwen-max")
    p.add_argument("--out", default="bench/lora_ab/llm-judge-ab.json")
    p.add_argument("--n-questions", type=int, default=len(QUESTIONS))
    args = p.parse_args()

    habits = json.loads(Path(args.habits).read_text())
    habit_text = "\n".join(f"- {h['description']}" for h in habits if h.get("description"))
    print(f"Loaded {len(habits)} habits from {args.habits}", flush=True)

    questions = QUESTIONS[: args.n_questions]
    rng = random.Random(20260415)

    print(f"Loading base + LoRA models via MLX...", flush=True)
    _ = generate_with_mlx(args.base, None, "warmup", max_tokens=3)
    _ = generate_with_mlx(args.base, args.adapter, "warmup", max_tokens=3)

    results = []
    a1_better = 0
    a2_better = 0
    ties = 0

    print(f"\nRunning {len(questions)} judgments (qwen-max)...", flush=True)
    for i, q in enumerate(questions):
        base_ans = generate_with_mlx(args.base, None, q)
        lora_ans = generate_with_mlx(args.base, args.adapter, q)

        # Randomize which slot is LoRA so the judge can't pattern-match ordering
        lora_is_1 = rng.random() > 0.5
        if lora_is_1:
            a1, a2 = lora_ans, base_ans
        else:
            a1, a2 = base_ans, lora_ans

        jp = JUDGE_PROMPT.format(
            user_question=q, n_habits=len(habits),
            user_profile=habit_text[:1500],
            answer_1=a1[:400], answer_2=a2[:400],
        )
        try:
            raw = call_qwen(jp, Path(args.config), model=args.judge_model)
            judgment = parse_judgment(raw)
        except Exception as e:
            print(f"  Q{i+1} judge error: {e}", flush=True)
            continue

        # Map judge preference to LoRA vs base
        if judgment["preference"] == "1":
            winner = "lora" if lora_is_1 else "base"
        elif judgment["preference"] == "2":
            winner = "base" if lora_is_1 else "lora"
        else:
            winner = "tie"

        if winner == "lora":
            a1_better += 1  # (reusing counter as lora_wins)
        elif winner == "base":
            a2_better += 1
        else:
            ties += 1

        lora_scores = judgment["ans1"] if lora_is_1 else judgment["ans2"]
        base_scores = judgment["ans2"] if lora_is_1 else judgment["ans1"]

        results.append({
            "q": q,
            "base_answer": base_ans,
            "lora_answer": lora_ans,
            "lora_was_slot": "1" if lora_is_1 else "2",
            "lora_scores": lora_scores,
            "base_scores": base_scores,
            "winner": winner,
            "reason": judgment["reason"],
        })
        print(f"  Q{i+1:02d}: winner={winner}  lora={lora_scores}  base={base_scores}", flush=True)

    # Aggregate
    lora_wins = a1_better  # relabeled
    base_wins = a2_better
    n = len(results)
    def _mean(key):
        lora = statistics.mean(r["lora_scores"].get(key, 0) for r in results) if results else 0
        base = statistics.mean(r["base_scores"].get(key, 0) for r in results) if results else 0
        return round(lora, 2), round(base, 2)

    p_l, p_b = _mean("personalization")
    g_l, g_b = _mean("groundedness")
    c_l, c_b = _mean("coherence")

    report = {
        "judge_model": args.judge_model,
        "base_model": args.base,
        "adapter": args.adapter,
        "n_questions": n,
        "lora_wins": lora_wins,
        "base_wins": base_wins,
        "ties": ties,
        "mean_scores": {
            "personalization": {"lora": p_l, "base": p_b, "delta": round(p_l - p_b, 2)},
            "groundedness":    {"lora": g_l, "base": g_b, "delta": round(g_l - g_b, 2)},
            "coherence":       {"lora": c_l, "base": c_b, "delta": round(c_l - c_b, 2)},
        },
        "per_query": results,
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print(f"\n=== LLM-as-judge A/B (n={n}, judge={args.judge_model}) ===")
    print(f"  preference: lora {lora_wins} / base {base_wins} / tie {ties}")
    print(f"  personalization:  lora {p_l} vs base {p_b}   (Δ {p_l-p_b:+.2f})")
    print(f"  groundedness:     lora {g_l} vs base {g_b}   (Δ {g_l-g_b:+.2f})")
    print(f"  coherence:        lora {c_l} vs base {c_b}   (Δ {c_l-c_b:+.2f})")
    print(f"  saved → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
