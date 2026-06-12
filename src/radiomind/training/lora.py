"""LoRA fine-tuning via MLX — neocortical memory consolidation.

Turns accumulated habits into model weights so the agent "just knows"
without retrieval. Like how you know fire is hot without looking it up.

MLX is optional: graceful fallback with clear instructions if not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
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
    # LoRAFuel-1b: which habits the training data consumed (observational,
    # threaded from DataGenReport by mind.train; also persisted to
    # train_meta.json next to the adapter).
    habit_ids: list = field(default_factory=list)


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
        from pathlib import Path as _P
        from types import SimpleNamespace
        # NOTE: we deliberately do NOT call mlx_lm.lora.run() because it
        # unconditionally overwrites its `training_callback` kwarg with
        # get_reporting_callbacks() on entry — a foot-gun that silently
        # discards our BestCheckpointTracker. Instead we reproduce the
        # three steps run() does (load → lora-layers → train) and pass
        # our callback directly to train().
        from mlx_lm.lora import CONFIG_DEFAULTS
        from mlx_lm.lora import linear_to_lora_layers, load_dataset, print_trainable_parameters, save_config
        from mlx_lm.tuner.trainer import TrainingArgs, train as mlx_train, CacheDataset
        from mlx_lm.tuner.callbacks import TrainingCallback
        from mlx_lm.utils import load as mlx_load
        import mlx.optimizers as _optim
        import mlx.core as _mx
        import numpy as _np

        # Align save cadence with eval cadence so every eval has a matching
        # checkpoint we can pick as "best". Without this the early-stopping
        # callback can observe a val-loss minimum it has no snapshot for.
        eval_every = config.eval_every
        save_every = eval_every

        class BestCheckpointTracker(TrainingCallback):
            """Track (iter, val_loss) pairs during training.

            At the end we promote the checkpoint with the lowest val_loss
            as the final adapter — so we never ship the over-trained tail.
            """
            def __init__(self):
                self.val_history: list[tuple[int, float]] = []

            def on_val_loss_report(self, val_info: dict):
                # mlx_lm reports iteration 0-indexed (0, eval_every-1, ...)
                # but the checkpoint files it saves use 1-indexed names
                # (0000025_adapters.safetensors for the 25th iter). Align
                # here so best_iter keys directly into a real file.
                it = int(val_info.get("iteration", 0)) + 1
                vl = float(val_info.get("val_loss", float("inf")))
                self.val_history.append((it, vl))

        tracker = BestCheckpointTracker()

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
            "save_every": save_every,
            "steps_per_report": 10,
            "steps_per_eval": eval_every,
            "max_seq_length": config.max_seq_length,
            "lora_parameters": {
                "rank": config.lora_rank,
                "dropout": 0.05,
                "scale": 20.0,
            },
        })
        args_ns = SimpleNamespace(**run_args)

        print(
            f"  Training: {effective_iters} iters, model={config.model}, "
            f"rank={config.lora_rank}, train={line_count}, valid={valid_count}, "
            f"eval_every={eval_every}"
        )

        _np.random.seed(args_ns.seed)
        _mx.random.seed(args_ns.seed)

        model, tokenizer = mlx_load(args_ns.model, tokenizer_config={"trust_remote_code": True})
        train_set, valid_set, _test = load_dataset(args_ns, tokenizer)

        model.freeze()
        linear_to_lora_layers(model, args_ns.num_layers, args_ns.lora_parameters)
        print_trainable_parameters(model)

        _P(args_ns.adapter_path).mkdir(parents=True, exist_ok=True)
        save_config(vars(args_ns), _P(args_ns.adapter_path) / "adapter_config.json")

        training_args = TrainingArgs(
            batch_size=args_ns.batch_size,
            iters=args_ns.iters,
            val_batches=args_ns.val_batches,
            steps_per_report=args_ns.steps_per_report,
            steps_per_eval=args_ns.steps_per_eval,
            steps_per_save=args_ns.save_every,
            adapter_file=_P(args_ns.adapter_path) / "adapters.safetensors",
            max_seq_length=args_ns.max_seq_length,
            grad_checkpoint=args_ns.grad_checkpoint,
            grad_accumulation_steps=args_ns.grad_accumulation_steps,
        )
        opt = _optim.Adam(learning_rate=args_ns.learning_rate)

        mlx_train(
            model=model,
            args=training_args,
            optimizer=opt,
            train_dataset=CacheDataset(train_set),
            val_dataset=CacheDataset(valid_set),
            training_callback=tracker,
        )

        # Early-stopping finalizer: promote the checkpoint with lowest val_loss.
        # mlx_lm saves per-iter checkpoints named `<iter>_adapters.safetensors`
        # alongside the final `adapters.safetensors`. We pick the lowest-val
        # snapshot and copy it over.
        best_iter = None
        best_loss = float("inf")
        if tracker.val_history:
            best_iter, best_loss = min(tracker.val_history, key=lambda p: p[1])
            _, final_loss = tracker.val_history[-1]

            # Only promote if the best isn't already the final one AND we
            # actually saw degradation past it (patience semantics).
            past_best = [vl for it, vl in tracker.val_history if it > best_iter]
            degraded = sum(1 for vl in past_best if vl > best_loss + 1e-6)

            if best_iter != tracker.val_history[-1][0] and degraded >= config.early_stop_patience:
                candidate = adapter_dir / f"{best_iter:07d}_adapters.safetensors"
                final = adapter_dir / "adapters.safetensors"
                if candidate.exists():
                    shutil.copy2(candidate, final)
                    print(
                        f"  Early-stop promotion: rolled back to iter {best_iter} "
                        f"(val={best_loss:.3f}, final val was {final_loss:.3f}, "
                        f"{degraded} regressions seen past iter {best_iter})"
                    )

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


# LoRA-1c: chat templates + stop tokens per base-model family. A bare
# `FROM model.gguf` Modelfile turns /api/generate into UNTERMINATED raw
# completion — the 1b probe caught a single request decoding 17k+ tokens
# at full speed, which the April A/B had misread as "q8_0 quantization
# loss + timeouts". The template/stop discipline is what makes the
# deployed model answer-and-stop.
_CHATML_TEMPLATE = (
    'TEMPLATE """{{ if .System }}<|im_start|>system\n'
    "{{ .System }}<|im_end|>\n"
    "{{ end }}<|im_start|>user\n"
    "{{ .Prompt }}<|im_end|>\n"
    '<|im_start|>assistant\n"""\n'
    "PARAMETER stop <|im_end|>\n"
    "PARAMETER stop <|im_start|>\n"
    "PARAMETER stop <|endoftext|>\n"
)


def modelfile_content(
    gguf_path: Path | str,
    mlx_base_model: str = "mlx-community/Qwen2.5-0.5B-Instruct-4bit",
    num_predict: int = 512,
) -> str:
    """Build the Ollama Modelfile for a fused-GGUF personal model.

    Pure — unit-testable without ollama. Template/stop are chosen by base
    family; the supported training recipe uses Qwen (ChatML). Unknown
    bases also get ChatML (every base this pipeline has ever fused is
    ChatML-family) — if a non-ChatML base is ever added, extend the
    family map here FIRST or the deployed model will regress to raw
    completion.
    """
    template = _CHATML_TEMPLATE  # qwen/chatml family; sole supported recipe
    return (
        f"FROM {gguf_path}\n"
        f"{template}"
        f"PARAMETER num_predict {num_predict}\n"
        f"PARAMETER temperature 0.7\n"
        f"SYSTEM You are a personal AI assistant for this user, "
        f"fine-tuned on their habits.\n"
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
    # Use sys.executable so we invoke Python from the venv where MLX is
    # installed, not whatever `python3` happens to resolve to on PATH.
    try:
        cmd = [
            sys.executable, "-m", "mlx_lm.fuse",
            "--model", mlx_base_model,
            "--adapter-path", str(adapter_path),
            "--save-path", str(fused_dir),
            "--dequantize",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return False, f"mlx_lm.fuse failed: {r.stderr[-300:]}"
    except FileNotFoundError:
        return False, "mlx_lm not installed. Run: pip install 'radiomind[train]'"
    except subprocess.TimeoutExpired:
        return False, "mlx_lm.fuse timed out (>10 min). Large base model?"

    # Step 2: convert fused HF model → GGUF
    # NOTE: llama.cpp's convert_hf_to_gguf.py only supports outtype of
    # f32/f16/bf16/q8_0/tq1_0/tq2_0/auto. For k-quants like q4_K_M the
    # user must then run llama.cpp's quantize binary — we pick q8_0 as
    # the best single-step balance of size (~500MB for a 0.5B model)
    # and quality (~lossless).
    gguf_path = adapter_path.parent / "model.gguf"
    try:
        cmd = [
            sys.executable, convert_script,
            str(fused_dir),
            "--outfile", str(gguf_path),
            "--outtype", "q8_0",
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
    modelfile.write_text(modelfile_content(gguf_path, mlx_base_model))

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
