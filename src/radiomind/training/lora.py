"""LoRA fine-tuning via MLX — neocortical memory consolidation.

Turns accumulated habits into model weights so the agent "just knows"
without retrieval. Like how you know fire is hot without looking it up.

MLX is optional: graceful fallback with clear instructions if not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from radiomind.core.config import Config


@dataclass
class TrainResult:
    success: bool
    adapter_path: Path | None = None
    model: str = ""
    iterations: int = 0
    duration_s: float = 0.0
    train_examples: int = 0
    error: str = ""


@dataclass
class TrainConfig:
    model: str = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
    lora_rank: int = 8
    lora_layers: int = 8
    iterations: int = 500
    batch_size: int = 4
    learning_rate: float = 1e-5
    output_dir: str = ""
    # Overfitting guards
    eval_every: int = 50                # eval valid loss every N iters
    early_stop_patience: int = 3        # stop after N consecutive eval regressions
    iters_per_example_cap: int = 10     # if iters > cap * n_examples, clip
    max_seq_length: int = 512

    @classmethod
    def from_config(cls, config: Config) -> TrainConfig:
        tc = cls()
        train_cfg = config.get("training", {})
        if isinstance(train_cfg, dict):
            tc.model = train_cfg.get("model", tc.model)
            tc.lora_rank = train_cfg.get("lora_rank", tc.lora_rank)
            tc.lora_layers = train_cfg.get("lora_layers", tc.lora_layers)
            tc.iterations = train_cfg.get("iterations", tc.iterations)
            tc.batch_size = train_cfg.get("batch_size", tc.batch_size)
            tc.learning_rate = train_cfg.get("learning_rate", tc.learning_rate)
        tc.output_dir = str(config.home / "models" / "lora")
        return tc


def check_mlx_available() -> tuple[bool, str]:
    """Check if MLX and mlx-lm are installed."""
    try:
        import mlx  # noqa: F401
        import mlx_lm  # noqa: F401
        return True, ""
    except ImportError:
        return False, (
            "MLX not installed. To enable LoRA training on Apple Silicon:\n"
            "  pip install 'radiomind[train]'\n"
            "Or manually:\n"
            "  pip install mlx mlx-lm"
        )


def train_lora(
    data_path: Path,
    config: TrainConfig,
) -> TrainResult:
    """Run LoRA fine-tuning using mlx_lm Python API."""
    t0 = time.time()

    available, msg = check_mlx_available()
    if not available:
        return TrainResult(success=False, error=msg)

    if not data_path.exists():
        return TrainResult(success=False, error=f"Training data not found: {data_path}")

    with open(data_path, encoding="utf-8") as f:
        line_count = sum(1 for _ in f)
    if line_count < 30:
        return TrainResult(
            success=False,
            error=(
                f"Too few training examples ({line_count}). Need at least 30 "
                "for LoRA to not memorize. Run: radiomind train --data-only to "
                "inspect what was generated; ingest more conversations first."
            ),
        )

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # mlx_lm expects {train,valid}.jsonl in the same directory.
    # We require a real valid split produced by data_gen — sibling valid.jsonl.
    train_dir = output_dir / "data"
    train_dir.mkdir(exist_ok=True)

    import shutil
    shutil.copy2(data_path, train_dir / "train.jsonl")

    valid_src = data_path.parent / "valid.jsonl"
    if not valid_src.exists():
        return TrainResult(
            success=False,
            error=(
                f"Missing validation set at {valid_src}. Regenerate data with "
                "TrainingDataGenerator.generate() which writes train + valid."
            ),
        )
    shutil.copy2(valid_src, train_dir / "valid.jsonl")

    with open(train_dir / "valid.jsonl", encoding="utf-8") as f:
        valid_count = sum(1 for _ in f)

    # Overfitting guard: cap iterations relative to dataset size
    effective_iters = min(
        config.iterations,
        config.iters_per_example_cap * line_count,
    )
    if effective_iters < config.iterations:
        print(
            f"  Note: capping iters at {effective_iters} "
            f"({config.iters_per_example_cap}×{line_count} examples)"
        )

    adapter_dir = output_dir / "adapters"
    adapter_dir.mkdir(exist_ok=True)

    try:
        from types import SimpleNamespace
        from mlx_lm.lora import CONFIG_DEFAULTS, run as mlx_run

        run_args = dict(CONFIG_DEFAULTS)
        run_args.update({
            "model": config.model,
            "train": True,
            "data": str(train_dir),
            "num_layers": config.lora_layers,
            "batch_size": config.batch_size,
            "iters": effective_iters,
            "learning_rate": config.learning_rate,
            "adapter_path": str(adapter_dir),
            "save_every": max(config.eval_every, 50),
            "steps_per_report": 10,
            "steps_per_eval": config.eval_every,
            "max_seq_length": config.max_seq_length,
            "lora_parameters": {
                "rank": config.lora_rank,
                "dropout": 0.05,  # small dropout discourages memorization
                "scale": 20.0,
            },
        })

        print(
            f"  Training: {effective_iters} iters, model={config.model}, "
            f"rank={config.lora_rank}, train={line_count}, valid={valid_count}"
        )
        mlx_run(SimpleNamespace(**run_args))

        adapter_file = adapter_dir / "adapters.safetensors"
        return TrainResult(
            success=adapter_file.exists(),
            adapter_path=adapter_dir if adapter_file.exists() else None,
            model=config.model,
            iterations=effective_iters,
            duration_s=time.time() - t0,
            train_examples=line_count,
        )
    except Exception as e:
        return TrainResult(
            success=False,
            error=str(e)[:500],
            duration_s=time.time() - t0,
        )


def export_to_ollama(
    adapter_path: Path,
    base_model: str = "qwen2.5:0.5b",
    model_name: str = "radiomind-personal",
    mlx_base_model: str = "mlx-community/Qwen2.5-0.5B-Instruct-4bit",
    llama_cpp_convert: str = "",
) -> tuple[bool, str]:
    """Export a trained LoRA adapter to Ollama.

    Pipeline:
        1. Fuse adapter + MLX base → fused/ (safetensors) via `mlx_lm.fuse`
        2. Convert fused model → GGUF via llama.cpp convert_hf_to_gguf.py
           (path passed as `llama_cpp_convert` or found via $LLAMA_CPP_CONVERT)
        3. Write Ollama Modelfile (FROM base + the fused GGUF as the actual
           model, not as an ADAPTER — Ollama's ADAPTER expects GGUF LoRA
           which MLX doesn't emit directly)
        4. `ollama create <model_name>`

    Returns (success, message). On missing tooling returns False with a
    specific install hint rather than attempting a broken command.
    """
    import os

    adapter_file = adapter_path / "adapters.safetensors"
    if not adapter_file.exists():
        return False, f"Adapter not found at {adapter_file}. Run: radiomind train"

    # Locate llama.cpp convert script
    convert_script = (
        llama_cpp_convert
        or os.environ.get("LLAMA_CPP_CONVERT", "")
        or _find_llama_cpp_convert()
    )
    if not convert_script:
        return False, (
            "llama.cpp convert_hf_to_gguf.py not found. Set LLAMA_CPP_CONVERT "
            "to the script path, or clone https://github.com/ggerganov/llama.cpp "
            "and point to convert_hf_to_gguf.py."
        )

    fused_dir = adapter_path.parent / "fused"
    fused_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: fuse adapter into base model
    try:
        cmd = [
            "python3", "-m", "mlx_lm.fuse",
            "--model", mlx_base_model,
            "--adapter-path", str(adapter_path),
            "--save-path", str(fused_dir),
            "--de-quantize",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return False, f"mlx_lm.fuse failed: {r.stderr[-300:]}"
    except FileNotFoundError:
        return False, "mlx_lm not installed. Run: pip install 'radiomind[train]'"
    except subprocess.TimeoutExpired:
        return False, "mlx_lm.fuse timed out (>10 min). Large base model?"

    # Step 2: convert fused HF model → GGUF
    gguf_path = adapter_path.parent / "model.gguf"
    try:
        cmd = [
            "python3", convert_script,
            str(fused_dir),
            "--outfile", str(gguf_path),
            "--outtype", "q4_K_M",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            return False, f"llama.cpp convert failed: {r.stderr[-300:]}"
    except subprocess.TimeoutExpired:
        return False, "llama.cpp convert timed out (>15 min)."

    if not gguf_path.exists():
        return False, f"Expected GGUF at {gguf_path} but it wasn't written."

    # Step 3: write Modelfile. Use FROM {gguf_path} — the fused model IS the
    # new base. Ollama's ADAPTER directive expects GGUF-format LoRA which
    # MLX doesn't emit, so we bake it in instead.
    modelfile = adapter_path.parent / "Modelfile"
    modelfile.write_text(
        f"FROM {gguf_path}\n"
        f"PARAMETER temperature 0.7\n"
        f"SYSTEM You are a personal AI assistant for this user, fine-tuned on their habits.\n"
    )

    # Step 4: register with Ollama
    if not shutil.which("ollama"):
        return False, "ollama CLI not on PATH. Install from https://ollama.com"
    try:
        r = subprocess.run(
            ["ollama", "create", model_name, "-f", str(modelfile)],
            capture_output=True, text=True, timeout=180,
        )
        if r.returncode == 0:
            return True, (
                f"Created Ollama model '{model_name}'.\n"
                f"Next: ollama run {model_name}  (or radiomind A/B: "
                f"python bench/lora_ab/eval.py --base {base_model} --lora {model_name})"
            )
        return False, f"ollama create failed: {r.stderr[-300:]}"
    except Exception as e:
        return False, f"ollama error: {e}"


def _find_llama_cpp_convert() -> str:
    """Look for llama.cpp's convert_hf_to_gguf.py in common locations."""
    candidates = [
        Path.home() / "llama.cpp" / "convert_hf_to_gguf.py",
        Path.home() / "code" / "llama.cpp" / "convert_hf_to_gguf.py",
        Path("/usr/local/share/llama.cpp/convert_hf_to_gguf.py"),
        Path("/opt/homebrew/share/llama.cpp/convert_hf_to_gguf.py"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""
