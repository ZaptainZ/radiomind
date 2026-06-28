"""Schema-version single-source + doctor reports the migrated version (KnowledgeLibrary-2a follow-up)."""

from radiomind.storage import database
from radiomind.storage.database import MemoryStore
from radiomind.storage.migrations import CURRENT_SCHEMA_VERSION


def test_schema_version_is_single_source():
    # database.SCHEMA_VERSION must not drift from the migration ledger (used to be a stale 3).
    assert database.SCHEMA_VERSION == CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION >= 5


def test_open_migrates_to_current(tmp_path):
    store = MemoryStore(tmp_path / "radiomind.db")
    store.open()
    ver = store.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    store.close()
    assert ver == CURRENT_SCHEMA_VERSION


def test_doctor_reports_migrated_schema(tmp_path, monkeypatch):
    # Simulate a stale on-disk version (pre-migration), then doctor must apply + report the current one
    # rather than the stale value it used to read off a raw read-only connection.
    monkeypatch.setenv("RADIOMIND_HOME", str(tmp_path / "rmhome"))
    from radiomind.core.config import Config

    cfg = Config.load()
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    store = MemoryStore(cfg.db_path)
    store.open()
    store.conn.execute("UPDATE schema_version SET version = 4")
    store.conn.commit()
    store.close()

    from click.testing import CliRunner
    from radiomind.cli.main import cli

    result = CliRunner().invoke(cli, ["doctor"])
    assert f"schema v{CURRENT_SCHEMA_VERSION}" in result.output, result.output
    assert "schema v4" not in result.output
