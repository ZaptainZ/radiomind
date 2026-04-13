"""Tests for Rust daemon IPC client.

Requires the Rust daemon binary to be built: cargo build --release
Tests are skipped if binary not found.
"""

import subprocess
import time
import pytest
from pathlib import Path

from radiomind.core.types import MemoryEntry
from radiomind.storage.daemon_client import DaemonClient

RUST_BINARY = Path(__file__).parent.parent / "rust-core" / "target" / "release" / "radiomind-daemon"


@pytest.fixture
def daemon():
    if not RUST_BINARY.exists():
        pytest.skip("Rust daemon not built. Run: cd rust-core && cargo build --release")

    import tempfile
    short_dir = tempfile.mkdtemp(prefix="rm_", dir="/tmp")
    socket_path = Path(short_dir) / "d.sock"
    env = {
        "RADIOMIND_HOME": short_dir,
        "PATH": "/usr/bin:/bin",
    }
    proc = subprocess.Popen(
        [str(RUST_BINARY), str(socket_path)],
        env=env,
        stderr=subprocess.PIPE,
    )

    for _ in range(30):
        if socket_path.exists():
            break
        time.sleep(0.1)

    client = DaemonClient(socket_path)
    assert client.connect(), f"Failed to connect. Socket exists: {socket_path.exists()}"

    yield client

    client.close()
    proc.terminate()
    proc.wait(timeout=5)
    import shutil
    shutil.rmtree(short_dir, ignore_errors=True)


class TestDaemonIPC:
    def test_ping(self, daemon):
        assert daemon.ping()

    def test_add_and_search(self, daemon):
        entry = MemoryEntry(content="testing rust daemon", domain="test")
        mid = daemon.add(entry)
        assert mid > 0

        results = daemon.search("rust daemon")
        assert len(results) > 0
        assert "rust daemon" in results[0].entry.content

    def test_dedup(self, daemon):
        entry = MemoryEntry(content="unique content", domain="test")
        id1 = daemon.add(entry)
        id2 = daemon.add(MemoryEntry(content="unique content", domain="test"))
        assert id1 > 0
        assert id2 == -1

    def test_stats(self, daemon):
        daemon.add(MemoryEntry(content="stat test", domain="d"))
        stats = daemon.stats()
        assert stats["total_active"] >= 1

    def test_search_empty(self, daemon):
        results = daemon.search("nonexistent12345")
        assert len(results) == 0

    def test_multiple_adds(self, daemon):
        for i in range(10):
            daemon.add(MemoryEntry(content=f"memory {i}", domain="batch"))
        stats = daemon.stats()
        assert stats["total_active"] >= 10
