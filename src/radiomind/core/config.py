"""Configuration management — nothing hardcoded."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


DEFAULT_HOME = Path.home() / ".radiomind"

DEFAULT_CONFIG = {
    "general": {
        "home": str(DEFAULT_HOME),
        "log_level": "info",
    },
    "llm": {
        "default_backend": "ollama",
        "ollama": {
            "host": "http://localhost:11434",
            "model": "qwen3:0.6b",
        },
        "openai": {
            "base_url": "",
            "api_key": "",
            "model": "deepseek-chat",
        },
    },
    "refinement": {
        "cost_mode": "economy",  # economy | standard | deep
        "chat": {
            "guardian_model": "",  # empty = use llm.ollama.model
            "explorer_model": "",
            "reducer_model": "",
            "trigger_hit_count": 3,
        },
        "dream": {
            "decay_days": 30,
            "decay_threshold": 3,
            "wander_sample_size": 5,
        },
    },
    "storage": {
        "db_name": "radiomind.db",
    },
    "hdc": {
        "dim": 10000,
    },
    "meta": {
        "digest_token_budget": 250,
    },
}


@dataclass
class Config:
    data: dict[str, Any] = field(default_factory=lambda: _deep_copy(DEFAULT_CONFIG))
    _path: Path | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        if path is None:
            path = DEFAULT_HOME / "config.toml"
        cfg = cls(_path=path)
        if path.exists():
            with open(path, "rb") as f:
                user = tomllib.load(f)
            _deep_merge(cfg.data, user)
        return cfg

    def save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines = _to_toml(self.data)
        self._path.write_text(lines)

    def get(self, dotpath: str, default: Any = None) -> Any:
        keys = dotpath.split(".")
        node = self.data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    def set(self, dotpath: str, value: Any) -> None:
        keys = dotpath.split(".")
        node = self.data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value

    @property
    def home(self) -> Path:
        return Path(self.get("general.home", str(DEFAULT_HOME)))

    @property
    def db_path(self) -> Path:
        return self.home / "data" / self.get("storage.db_name", "radiomind.db")


def _deep_copy(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        out[k] = _deep_copy(v) if isinstance(v, dict) else v
    return out


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _to_toml(d: dict, prefix: str = "") -> str:
    lines: list[str] = []
    scalars = {k: v for k, v in d.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in d.items() if isinstance(v, dict)}

    if prefix and scalars:
        lines.append(f"[{prefix}]")
    for k, v in scalars.items():
        if isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
    if scalars:
        lines.append("")

    for k, v in tables.items():
        sub = f"{prefix}.{k}" if prefix else k
        lines.append(_to_toml(v, sub))

    return "\n".join(lines)
