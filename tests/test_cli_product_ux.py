"""CLIProductSmoke-1b: UX-patch unit coverage (F1/F4/F6 renderers, F5 entry,
backend_status ordering). Deterministic — no LLM, no network, no real store.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from radiomind.cli.main import _render_backends, _render_train_gap
from radiomind.core.config import Config
from radiomind.core.llm import LLMRouter
from radiomind.training.data_gen import DataGenReport


# ---------------- F6: backend_status ordering + render ----------------

def _router(cfg: dict) -> LLMRouter:
    c = Config()
    c.set("llm", cfg)
    return c and LLMRouter(c)


def test_backend_status_default_first_deprecated_last():
    r = _router({
        "default_backend": "dashscope",
        "openai": {"base_url": "https://oa/v1", "api_key": "k",
                   "deprecated": True},
        "dashscope": {"base_url": "https://ds/v1", "api_key": "k"},
        "openrouter": {"base_url": "https://or/v1", "api_key": "k"},
    })
    rows = r.backend_status()
    assert rows[0]["name"] == "dashscope" and rows[0]["is_default"]
    assert rows[-1]["name"] == "openai" and rows[-1]["deprecated"]


def test_render_backends_tags():
    rows = [
        {"name": "dashscope", "is_default": True, "available": True, "deprecated": False},
        {"name": "openrouter", "is_default": False, "available": True, "deprecated": False},
        {"name": "openai", "is_default": False, "available": True, "deprecated": True},
    ]
    out = _render_backends(rows)
    assert out == "dashscope [default], openrouter, openai [deprecated]"


def test_render_backends_unavailable_tag():
    rows = [{"name": "ollama", "is_default": True, "available": False, "deprecated": False}]
    assert _render_backends(rows) == "ollama [default, unavailable]"


def test_render_backends_empty():
    assert _render_backends([]) == "none"


# ---------------- F1: actionable train gap ----------------

def _refused(habits, domains, examples) -> DataGenReport:
    return DataGenReport(
        train_count=0, valid_count=0, dropped_pii=0, dropped_dup=0,
        dropped_short=0, habits_used=habits, domains_used=domains,
        refused=True, refused_reason="x", distinct_examples=examples,
    )


def test_train_gap_shows_each_threshold():
    lines = _render_train_gap(_refused(3, 1, 18), prepared=False)
    body = "\n".join(lines)
    assert "habits     3/5  [short]" in body
    assert "domains    1/2  [short]" in body
    assert "examples   18/30  [short]" in body
    assert "train --prepare-habits" in body  # next step when not prepared


def test_train_gap_marks_ok_thresholds():
    lines = _render_train_gap(_refused(7, 3, 18), prepared=True)
    body = "\n".join(lines)
    assert "habits     7/5  [ok]" in body
    assert "domains    3/2  [ok]" in body
    assert "examples   18/30  [short]" in body


def test_train_gap_prepared_says_data_not_failure():
    body = "\n".join(_render_train_gap(_refused(1, 1, 5), prepared=True))
    assert "DATA-VOLUME shortfall" in body
    assert "not an LLM/router failure" in body
    assert "--prepare-habits" not in body  # don't re-suggest what already ran


def test_datagen_report_distinct_examples_default_zero():
    r = DataGenReport(train_count=0, valid_count=0, dropped_pii=0,
                      dropped_dup=0, dropped_short=0, habits_used=0,
                      domains_used=0)
    assert r.distinct_examples == 0


# ---------------- F5: python -m radiomind ----------------

def test_python_dash_m_radiomind_help():
    repo = Path(__file__).resolve().parents[1]
    env = {"PYTHONPATH": str(repo / "src"), "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(
        [sys.executable, "-m", "radiomind", "--help"],
        capture_output=True, text=True, env=env, cwd=str(repo),
    )
    assert proc.returncode == 0
    assert "RadioMind" in proc.stdout


# ---------------- F3/F4: source-guard wiring ----------------

def test_search_hints_when_no_embedder():
    src = (Path(__file__).resolve().parents[1]
           / "src" / "radiomind" / "cli" / "main.py").read_text()
    assert "mind._embedder is None" in src
    assert "keyword (FTS)" in src


def test_doctor_path_check_not_a_warning():
    src = (Path(__file__).resolve().parents[1]
           / "src" / "radiomind" / "cli" / "main.py").read_text()
    # F4: the running entry always works → PASS, never WARN
    assert "current entry works" in src
    assert 'add("PASS", "radiomind CLI"' in src
