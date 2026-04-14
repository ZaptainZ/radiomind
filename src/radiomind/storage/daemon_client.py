"""IPC client for Rust radiomind-daemon.

When the Rust daemon is running, Python uses this instead of direct SQLite.
Falls back to Python SQLite if daemon is unavailable.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from radiomind.core.types import MemoryEntry, MemoryLevel, MemoryStatus, PrivacyLevel, SearchResult


class DaemonClient:
    """Communicates with radiomind-daemon via Unix socket JSON Lines."""

    def __init__(self, socket_path: Path | None = None):
        self._socket_path = socket_path or (Path.home() / ".radiomind" / "radiomind.sock")
        self._sock: socket.socket | None = None
        self._req_id = 0

    @property
    def is_available(self) -> bool:
        return self._socket_path.exists()

    def connect(self) -> bool:
        if not self._socket_path.exists():
            return False
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(str(self._socket_path))
            self._sock.settimeout(10.0)
            return True
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            self._sock = None
            return False

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    def call(self, method: str, params: dict | None = None) -> Any:
        """Send a request and get the response."""
        if self._sock is None:
            if not self.connect():
                raise ConnectionError("Daemon not available")

        self._req_id += 1
        request = {"id": self._req_id, "method": method, "params": params or {}}
        data = json.dumps(request) + "\n"

        try:
            self._sock.sendall(data.encode())
            response_data = b""
            while b"\n" not in response_data:
                chunk = self._sock.recv(65536)
                if not chunk:
                    raise ConnectionError("Daemon closed connection")
                response_data += chunk

            response = json.loads(response_data.decode().strip())
            if "error" in response and response["error"]:
                raise RuntimeError(f"Daemon error: {response['error']}")
            return response.get("result")
        except (BrokenPipeError, ConnectionResetError, OSError):
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
            self._sock = None
            raise ConnectionError("Lost connection to daemon")

    # --- Convenience wrappers matching MemoryStore API ---

    def add(self, entry: MemoryEntry) -> int:
        result = self.call("add", {
            "content": entry.content,
            "domain": entry.domain,
            "level": int(entry.level),
            "parent_id": entry.parent_id,
            "status": entry.status.value,
            "privacy": entry.privacy.value,
            "embedding": None,
            "hit_count": entry.hit_count,
            "last_hit_at": entry.last_hit_at,
            "decay_count": entry.decay_count,
            "created_at": entry.created_at,
            "metadata": json.dumps(entry.metadata),
        })
        mid = result.get("id", -1)
        entry.id = mid if mid > 0 else None
        return mid

    def search(self, query: str, domain: str | None = None, limit: int = 10) -> list[SearchResult]:
        params = {"query": query, "limit": limit}
        if domain:
            params["domain"] = domain
        results = self.call("search", params)
        return [self._parse_search_result(r) for r in (results or [])]

    def stats(self) -> dict[str, Any]:
        return self.call("stats") or {}

    def ping(self) -> bool:
        try:
            result = self.call("ping")
            return result == "pong"
        except Exception:
            return False

    @staticmethod
    def _parse_search_result(data: dict) -> SearchResult:
        e = data.get("entry", {})
        return SearchResult(
            entry=MemoryEntry(
                id=e.get("id"),
                content=e.get("content", ""),
                domain=e.get("domain", ""),
                level=MemoryLevel(e.get("level", 0)),
                parent_id=e.get("parent_id"),
                status=MemoryStatus(e.get("status", "active")),
                privacy=PrivacyLevel(e.get("privacy", "open")),
                hit_count=e.get("hit_count", 0),
                last_hit_at=e.get("last_hit_at", 0.0),
                decay_count=e.get("decay_count", 0),
                created_at=e.get("created_at", 0.0),
            ),
            score=data.get("score", 0.0),
            method=data.get("method", "daemon"),
        )


def start_daemon(radiomind_home: Path | None = None) -> subprocess.Popen | None:
    """Start the Rust daemon as a background process."""
    home = radiomind_home or Path.home() / ".radiomind"
    socket_path = home / "radiomind.sock"
    binary = home / "bin" / "radiomind-daemon"

    if not binary.exists():
        # Try cargo build location
        project_root = Path(__file__).parent.parent.parent.parent / "rust-core"
        binary = project_root / "target" / "release" / "radiomind-daemon"

    if not binary.exists():
        return None

    import os
    env = os.environ.copy()
    env["RADIOMIND_HOME"] = str(home)
    proc = subprocess.Popen(
        [str(binary), str(socket_path)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    # Wait for socket to appear
    for _ in range(20):
        if socket_path.exists():
            return proc
        time.sleep(0.1)

    proc.terminate()
    return None
