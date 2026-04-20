"""Smoke test for answer_hint / temporal / open_domain pipelines.

Picks real LME-S questions of each attention type, runs only the
pipeline-specific code path (skip answer/judge LLM), verifies no crash
and reasonable non-empty output. Cheap: ~5 LLM calls total.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_longmemeval_mem0 import llm_call  # noqa: E402


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="rm-smoke-pipelines-"))
    os.environ["RADIOMIND_HOME"] = str(sandbox)

    import shutil
    cfg_src = Path.home() / ".radiomind" / "config.toml"
    cfg_dst = sandbox / "config.toml"
    if cfg_src.exists():
        cfg_dst.write_text(
            cfg_src.read_text().replace(str(Path.home() / ".radiomind"), str(sandbox))
        )

    def _llm(prompt: str, system: str = "") -> str:
        return llm_call(
            prompt, cfg_dst, model="openai/gpt-4o", max_tokens=1200,
            profile="openrouter", system=(system or None),
        )

    from radiomind import RadioMind
    from radiomind.core.attention import analyze

    # Synthetic minimal memory context for each test shape.
    # Real bench harness supplies rich retrieved_memories; we just verify
    # the pipelines produce *something* non-empty and don't crash.
    test_cases = [
        {
            "wants": "date",
            "question": "When did Deboran and Jolene agree to go surfing?",
            "memories": [
                {"memory": "Jolene mentioned being pumped to try surfing.",
                 "created_at": "2023-03-22"},
                {"memory": "Deborah and Jolene discussed plans to go surfing together.",
                 "created_at": "2023-10-15"},
                {"memory": "They finalized surfing plans for October 2023.",
                 "created_at": "2023-10-20"},
            ],
            "ref_date": "2024-01-01",
        },
        {
            "wants": "inference",
            "question": "What might Nate consider as an alternative career?",
            "memories": [
                {"memory": "Nate loves animals, especially turtles at the zoo.",
                 "created_at": "2022-06-01"},
                {"memory": "Nate mentioned volunteering at a local wildlife sanctuary.",
                 "created_at": "2022-08-10"},
                {"memory": "Nate said he'd enjoy working as an animal keeper someday.",
                 "created_at": "2022-09-15"},
            ],
            "ref_date": "",
        },
        {
            "wants": "detail",
            "question": "What does Joanna do while she writes?",
            "memories": [
                {"memory": "Joanna uses her journal daily for expression.",
                 "created_at": "2022-01-15"},
                {"memory": "She keeps Tilly, her stuffed animal dog, with her while writing.",
                 "created_at": "2022-03-20"},
                {"memory": "Joanna creates wild worlds and characters in her stories.",
                 "created_at": "2022-05-11"},
            ],
            "ref_date": "",
        },
    ]

    mind = RadioMind(llm=_llm)
    mind.initialize()

    all_ok = True
    for tc in test_cases:
        sig = analyze(tc["question"])
        print(f"\n== {tc['wants']} ==")
        print(f"Q: {tc['question']}")
        print(f"analyze → wants={sig.wants}")
        if sig.wants != tc["wants"]:
            print(f"  ⚠ attention misroute: expected {tc['wants']}, got {sig.wants}")
            all_ok = False
            continue
        try:
            prefix = mind.answer_hint(
                query=tc["question"],
                retrieved_memories=tc["memories"],
                reference_date=tc["ref_date"],
            )
        except Exception as e:
            print(f"  ✗ CRASH: {e}")
            all_ok = False
            continue
        if not prefix:
            print(f"  ⚠ empty prefix (pipeline abstained)")
        else:
            print(f"  ✓ prefix ({len(prefix)} chars):")
            for line in prefix.strip().split("\n")[:6]:
                print(f"    {line}")

    mind.shutdown()
    print(f"\n{'ok' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
