"""LoRA fine-tuning via MLX — neocortical memory consolidation.

Turns accumulated habits into model weights so the agent "just knows"
without retrieval. Like how you know fire is hot without looking it up.

MLX is optional: graceful fallback with clear instructions if not installed.
"""

from __future__ import annotations

import json
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

    line_count = sum(1 for _ in open(data_path))
    if line_count < 3:
        return TrainResult(
            success=False,
            error=f"Too few training examples ({line_count}). Need at least 3.",
        )

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Prepare data directory: mlx_lm expects train.jsonl + valid.jsonl
    train_dir = output_dir / "data"
    train_dir.mkdir(exist_ok=True)

    import shutil
    shutil.copy2(data_path, train_dir / "train.jsonl")

    with open(data_path) as f:
        lines = f.readlines()
    # Valid set needs at least batch_size examples; use same data if too few
    valid_count = max(config.batch_size, len(lines) // 5)
    valid_lines = (lines * ((valid_count // len(lines)) + 1))[:valid_count] if lines else []
    with open(train_dir / "valid.jsonl", "w") as f:
        f.writelines(valid_lines)

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
            "iters": config.iterations,
            "learning_rate": config.learning_rate,
            "adapter_path": str(adapter_dir),
            "save_every": config.iterations,
            "steps_per_report": 10,
            "steps_per_eval": config.iterations,
            "max_seq_length": 512,
            "lora_parameters": {
                "rank": config.lora_rank,
                "dropout": 0.0,
                "scale": 20.0,
            },
        })

        print(f"  Training: {config.iterations} iters, model={config.model}, rank={config.lora_rank}")
        mlx_run(SimpleNamespace(**run_args))

        adapter_file = adapter_dir / "adapters.safetensors"
        return TrainResult(
            success=adapter_file.exists(),
            adapter_path=adapter_dir if adapter_file.exists() else None,
            model=config.model,
            iterations=config.iterations,
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
) -> tuple[bool, str]:
    """Export LoRA adapter to Ollama as a custom model.

    Creates an Ollama Modelfile and registers the model.
    """
    # Convert adapter to GGUF if needed
    gguf_path = adapter_path / "adapter.gguf"

    if not gguf_path.exists():
        # Try mlx_lm.convert
        try:
            cmd = [
                "python3", "-m", "mlx_lm.convert",
                "--model", str(adapter_path),
                "--quantize",
                "--output", str(gguf_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                return False, f"GGUF conversion failed: {result.stderr[:200]}"
        except Exception as e:
            return False, f"GGUF conversion error: {e}"

    # Create Ollama Modelfile
    modelfile_path = adapter_path / "Modelfile"
    modelfile_content = f"FROM {base_model}\nADAPTER {gguf_path}\n"
    modelfile_path.write_text(modelfile_content)

    # Register with Ollama
    try:
        result = subprocess.run(
            ["ollama", "create", model_name, "-f", str(modelfile_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True, f"Model '{model_name}' created successfully"
        else:
            return False, f"Ollama create failed: {result.stderr[:200]}"
    except FileNotFoundError:
        return False, "Ollama not found. Install from https://ollama.com"
    except Exception as e:
        return False, f"Ollama error: {e}"
