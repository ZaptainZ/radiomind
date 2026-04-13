"""Tests for configuration system."""

from pathlib import Path

from radiomind.core.config import Config, DEFAULT_CONFIG


def test_default_config():
    cfg = Config()
    assert cfg.get("llm.default_backend") == "ollama"
    assert cfg.get("hdc.dim") == 10000
    assert cfg.get("refinement.cost_mode") == "economy"


def test_dotpath_get_set():
    cfg = Config()
    cfg.set("llm.ollama.model", "phi3:3b")
    assert cfg.get("llm.ollama.model") == "phi3:3b"


def test_dotpath_missing():
    cfg = Config()
    assert cfg.get("nonexistent.path", "fallback") == "fallback"


def test_save_load(tmp_path: Path):
    path = tmp_path / "config.toml"
    cfg = Config(_path=path)
    cfg.set("llm.ollama.model", "test-model")
    cfg.save()

    loaded = Config.load(path)
    assert loaded.get("llm.ollama.model") == "test-model"
    assert loaded.get("hdc.dim") == 10000


def test_home_path():
    cfg = Config()
    assert isinstance(cfg.home, Path)
    assert cfg.home.name == ".radiomind"


def test_db_path():
    cfg = Config()
    assert cfg.db_path.name == "radiomind.db"
    assert "data" in str(cfg.db_path)
