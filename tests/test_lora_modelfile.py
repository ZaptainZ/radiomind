"""LoRA-1c: the exported Ollama Modelfile must carry TEMPLATE / stop /
num_predict. A bare FROM Modelfile turns /api/generate into unterminated
raw completion (1b probe: 17k+ tokens runaway, misread in April as
quantization loss). Deterministic — no ollama, no mlx.
"""
from __future__ import annotations

from pathlib import Path

from radiomind.training.lora import modelfile_content


def _content() -> str:
    return modelfile_content(Path("/x/model.gguf"))


def test_from_line_points_at_gguf():
    assert _content().startswith("FROM /x/model.gguf\n")


def test_template_present_with_prompt_and_system_slots():
    c = _content()
    assert "TEMPLATE" in c
    assert "{{ .Prompt }}" in c
    assert "{{ .System }}" in c
    # ChatML role markers — the supported (qwen) family
    assert "<|im_start|>user" in c
    assert "<|im_start|>assistant" in c


def test_stop_tokens_cover_chatml_and_endoftext():
    c = _content()
    assert "PARAMETER stop <|im_end|>" in c
    assert "PARAMETER stop <|im_start|>" in c
    assert "PARAMETER stop <|endoftext|>" in c


def test_num_predict_capped_and_overridable():
    assert "PARAMETER num_predict 512" in _content()
    assert "PARAMETER num_predict 64" in modelfile_content("/x/m.gguf", num_predict=64)


def test_legacy_lines_preserved():
    c = _content()
    assert "PARAMETER temperature 0.7" in c
    assert c.rstrip().endswith("fine-tuned on their habits.")


def test_no_bare_modelfile_regression():
    # the April defect: FROM + temperature + SYSTEM only. Any future
    # refactor that drops the template must fail here.
    c = _content()
    lines = [l for l in c.splitlines() if l.strip()]
    assert len(lines) > 3, "Modelfile regressed to the bare April form"
