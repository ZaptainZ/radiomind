"""Tests for MCP server."""

import json
import pytest

from radiomind.mcp_server import MCPServer


@pytest.fixture
def server(tmp_path):
    import os
    os.environ["RADIOMIND_HOME"] = str(tmp_path / ".radiomind")
    s = MCPServer()
    yield s
    s.shutdown()


class TestMCPProtocol:
    def test_initialize(self, server):
        resp = server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })
        assert resp["id"] == 1
        assert resp["result"]["serverInfo"]["name"] == "radiomind"
        assert "tools" in resp["result"]["capabilities"]

    def test_tools_list(self, server):
        resp = server.handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        tools = resp["result"]["tools"]
        assert len(tools) == 9
        names = {t["name"] for t in tools}
        assert "radiomind_search" in names
        assert "radiomind_dream" in names
        assert "radiomind_digest" in names

    def test_ping(self, server):
        resp = server.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "ping",
            "params": {},
        })
        assert resp["id"] == 3

    def test_unknown_method(self, server):
        resp = server.handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "nonexistent",
            "params": {},
        })
        assert "error" in resp

    def test_notification_no_response(self, server):
        resp = server.handle_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })
        assert resp == {}


class TestMCPToolCalls:
    def test_search(self, server):
        # First learn something
        server.handle_request({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "radiomind_learn", "arguments": {"text": "test memory"}},
        })

        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 2,
            "method": "tools/call",
            "params": {"name": "radiomind_search", "arguments": {"query": "test"}},
        })
        content = resp["result"]["content"][0]["text"]
        assert "test" in content.lower()

    def test_ingest(self, server):
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {
                "name": "radiomind_ingest",
                "arguments": {
                    "messages": [
                        {"role": "user", "content": "我叫小明"},
                        {"role": "assistant", "content": "你好小明"},
                    ],
                },
            },
        })
        assert "Ingested" in resp["result"]["content"][0]["text"]

    def test_status(self, server):
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "radiomind_status", "arguments": {}},
        })
        text = resp["result"]["content"][0]["text"]
        assert "total_active" in text

    def test_digest(self, server):
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "radiomind_digest", "arguments": {}},
        })
        assert "content" in resp["result"]
