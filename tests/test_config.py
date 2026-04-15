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


def test_home_path(monkeypatch):
    # Default (no env override) should point at ~/.radiomind
    monkeypatch.delenv("RADIOMIND_HOME", raising=False)
    # Config() doesn't re-read env; test via load() which picks up _default_home
    cfg = Config.load()
    assert isinstance(cfg.home, Path)
    assert cfg.home.name == ".radiomind"


def test_home_path_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RADIOMIND_HOME", str(tmp_path))
    cfg = Config.load()
    assert cfg.home == tmp_path


def test_env_home_beats_config_toml(monkeypatch, tmp_path):
    """RADIOMIND_HOME env var must override [general] home in config.toml.

    Regression guard: 2026-04-15 audit found that a config.toml with an
    explicit `[general] home = ...` silently overrode the env var,
    making the sandbox-isolation escape hatch ineffective for real
    users who had ever run `radiomind init`. Content was merged from
    file config AFTER we seeded env-home, so file won.
    """
    # Simulate a home with a pre-existing config.toml pointing elsewhere
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    config_path = sandbox / "config.toml"
    config_path.write_text('[general]\nhome = "/this/should/be/overridden"\n')

    monkeypatch.setenv("RADIOMIND_HOME", str(sandbox))
    cfg = Config.load()
    # Env must win — not the '/this/should/be/overridden' from the file
    assert cfg.home == sandbox, f"env var should override config.toml, got {cfg.home}"


def test_db_path():
    cfg = Config()
    assert cfg.db_path.name == "radiomind.db"
    assert "data" in str(cfg.db_path)
