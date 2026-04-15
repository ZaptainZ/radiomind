"""LoRA A/B evaluation — does personal LoRA actually help vs the base model?

Runs the LoCoMo-lite query set through two Ollama models (base vs LoRA-adapted)
with the same retrieved context and scores answer quality. Uses token-overlap
scoring against gold statements (no LLM judge needed) so it runs locally.

Usage:
    # Requires ollama running and both models available
    python bench/lora_ab/eval.py \\
        --base qwen2.5:0.5b \\
        --lora radiomind-personal \\
        --out bench/lora_ab/result.json

    # Skip LoRA side — just measure base-model + RAG as a sanity check
    python bench/lora_ab/eval.py --base qwen2.5:0.5b

Output:
    - Per-query: retrieved context, base answer, lora answer, overlap scores
    - Aggregate: mean score base vs lora, win/loss/tie counts, delta
    - Nonzero exit if LoRA hurts mean score by > 0.05 (regression gate)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DATASET = (
    Path(__file__).parent.parent / "locomo_lite" / "dataset.json"
)

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def ollama_generate(model: str, prompt: str, system: str = "", timeout: int = 30) -> str:
    """Call ollama /api/generate. Returns text or raises on error."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body.get("response", "")


def ollama_available(model: str) -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL.rstrip('/')}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as r:
            tags = json.loads(r.read().decode())
        names = [m["name"] for m in tags.get("models", [])]
        return any(n == model or n.startswith(model + ":") for n in names)
    except Exception:
        return False


def overlap_score(answer: str, gold_texts: list[str]) -> float:
    """Token-overlap score: fraction of distinct gold tokens present in answer.

    For CJK: per-character Jaccard style. For ASCII: whitespace tokens.
    Score in [0, 1]; combines recall-style measure across gold statements.
    """
    if not answer or not gold_texts:
        return 0.0
    ans = answer.lower()

    def tokens(text: str) -> set[str]:
        text = text.lower()
        toks: set[str] = set()
        # CJK: characters
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff":
                toks.add(ch)
        # ASCII: word chunks
        for word in text.split():
            w = "".join(c for c in word if c.isalnum())
            if len(w) >= 2:
                toks.add(w)
        return toks

    ans_toks = tokens(ans)
    per_gold: list[float] = []
    for g in gold_texts:
        g_toks = tokens(g)
        if not g_toks:
            continue
        hit = len(g_toks & ans_toks)
        per_gold.append(hit / len(g_toks))
    return statistics.mean(per_gold) if per_gold else 0.0


def build_prompt(query: str, context_statements: list[str]) -> str:
    ctx = "\n".join(f"- {s}" for s in context_statements)
    return (
        f"以下是关于用户的一些已知事实：\n{ctx}\n\n"
        f"用户问：{query}\n\n"
        "请基于上述事实用一句话回答。如果事实里没有相关信息，就说「没有记录」。"
    )


def seed_memory(sandbox: Path, statements: list[dict]):
    """Seed a sandbox RadioMind with the benchmark statements for retrieval."""
    os.environ["RADIOMIND_HOME"] = str(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)

    from radiomind.core.mind import RadioMind
    from radiomind.core.types import MemoryEntry, MemoryLevel

    mind = RadioMind()
    mind.initialize()
    for s in statements:
        entry = MemoryEntry(
            content=s["text"],
            domain="bench",
            level=MemoryLevel.FACT,
            metadata={"sid": s["id"]},
        )
        if mind._embedder:
            entry.embedding = mind._embedder.encode(s["text"])
        mind._store.add(entry, dedup=False)
    return mind


def run(base_model: str, lora_model: str | None, max_queries: int | None = None) -> dict:
    sandbox = Path("/tmp/rm-bench-lora-ab")
    if sandbox.exists():
        shutil.rmtree(sandbox)

    data = json.loads(DATASET.read_text())
    statements = data["statements"]
    queries = data["queries"]
    if max_queries:
        queries = queries[:max_queries]
    sid_to_text = {s["id"]: s["text"] for s in statements}

    mind = seed_memory(sandbox, statements)

    if not ollama_available(base_model):
        mind.shutdown()
        return {
            "error": (
                f"Base model '{base_model}' not available on Ollama ({OLLAMA_URL}). "
                "Start ollama and run: ollama pull " + base_model
            ),
        }

    do_lora = bool(lora_model)
    if do_lora and not ollama_available(lora_model):
        do_lora = False
        lora_unavailable = (
            f"LoRA model '{lora_model}' not available. Skipping LoRA side. "
            "Run: radiomind deploy --model " + lora_model
        )
    else:
        lora_unavailable = ""

    per_query = []
    base_scores: list[float] = []
    lora_scores: list[float] = []
    t0 = time.time()

    for q in queries:
        results = mind.search(q["q"])
        context_texts = [r.entry.content for r in results[:5]]
        prompt = build_prompt(q["q"], context_texts)

        gold_texts = [sid_to_text[sid] for sid in q["gold"]]

        try:
            base_ans = ollama_generate(base_model, prompt)
        except Exception as e:
            base_ans = f"[error: {e}]"
        base_s = overlap_score(base_ans, gold_texts)
        base_scores.append(base_s)

        lora_ans = ""
        lora_s = 0.0
        if do_lora:
            try:
                lora_ans = ollama_generate(lora_model, prompt)
            except Exception as e:
                lora_ans = f"[error: {e}]"
            lora_s = overlap_score(lora_ans, gold_texts)
            lora_scores.append(lora_s)

        per_query.append({
            "q": q["q"],
            "gold": q["gold"],
            "context_sids": [r.entry.metadata.get("sid", "") for r in results[:5]],
            "base_answer": base_ans,
            "base_score": round(base_s, 3),
            "lora_answer": lora_ans if do_lora else None,
            "lora_score": round(lora_s, 3) if do_lora else None,
        })

    report = {
        "base_model": base_model,
        "lora_model": lora_model if do_lora else None,
        "n_queries": len(queries),
        "base_mean": round(statistics.mean(base_scores), 4) if base_scores else 0.0,
        "elapsed_s": round(time.time() - t0, 1),
    }
    if do_lora:
        wins = sum(1 for i, s in enumerate(lora_scores) if s > base_scores[i] + 0.05)
        losses = sum(1 for i, s in enumerate(lora_scores) if s < base_scores[i] - 0.05)
        ties = len(lora_scores) - wins - losses
        report.update({
            "lora_mean": round(statistics.mean(lora_scores), 4),
            "delta": round(statistics.mean(lora_scores) - statistics.mean(base_scores), 4),
            "wins": wins, "losses": losses, "ties": ties,
        })
    if lora_unavailable:
        report["lora_unavailable"] = lora_unavailable

    report["per_query"] = per_query
    mind.shutdown()
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="qwen2.5:0.5b", help="Ollama base model name.")
    p.add_argument("--lora", default="", help="Ollama LoRA-adapted model name (optional).")
    p.add_argument("--max-queries", type=int, default=None, help="Cap for a fast smoke run.")
    p.add_argument("--out", default="bench/lora_ab/result.json", help="Write full JSON report here.")
    p.add_argument("--regression-threshold", type=float, default=0.05,
                   help="If LoRA mean < base mean - threshold, exit 1.")
    args = p.parse_args()

    report = run(args.base, args.lora or None, max_queries=args.max_queries)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    if "error" in report:
        print(f"ERROR: {report['error']}", file=sys.stderr)
        return 2

    print(f"LoRA A/B — {args.base}" + (f" vs {args.lora}" if args.lora else " (base only)"))
    print(f"  queries: {report['n_queries']}  elapsed: {report['elapsed_s']}s")
    print(f"  base mean score: {report['base_mean']:.3f}")
    if report.get("lora_model"):
        print(f"  LoRA mean score: {report['lora_mean']:.3f}  "
              f"delta: {report['delta']:+.3f}  "
              f"wins/losses/ties: {report['wins']}/{report['losses']}/{report['ties']}")
        if report["delta"] < -args.regression_threshold:
            print(
                f"\nREGRESSION: LoRA worse than base by {-report['delta']:.3f}.",
                file=sys.stderr,
            )
            return 1
    if report.get("lora_unavailable"):
        print(f"  [note] {report['lora_unavailable']}")
    print(f"  full report → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
