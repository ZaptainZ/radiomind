"""RadioMind MCP Server — expose memory as tools for Claude Desktop, Cursor, etc.

MCP (Model Context Protocol) stdio transport.
Usage:
  radiomind mcp-server
  # Or in Claude Desktop config:
  # claude mcp add radiomind -- python -m radiomind.mcp_server

Protocol: JSON-RPC 2.0 over stdin/stdout
"""

from __future__ import annotations

import json
import sys
from typing import Any

from radiomind.core.mind import RadioMind
from radiomind.core.types import Message

SERVER_INFO = {
    "name": "radiomind",
    "version": "0.1.0",
}

TOOLS = [
    {
        "name": "radiomind_search",
        "description": "Search RadioMind's bionic memory system. Uses pyramid search (principles → patterns → facts) plus HDC habit matching.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (supports Chinese and English)"},
                "domain": {"type": "string", "description": "Optional: filter by domain (e.g. health, work, ios)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "radiomind_ingest",
        "description": "Ingest a conversation into RadioMind's memory. Extracts facts, detects domains, updates user profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": ["user", "assistant"]},
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                    },
                    "description": "Conversation messages to ingest",
                },
            },
            "required": ["messages"],
        },
    },
    {
        "name": "radiomind_learn",
        "description": "Add external knowledge to RadioMind. Enters L2 facts layer and walks the normal consolidation path (can be refined into habits via chat/dream).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Knowledge text to learn"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "radiomind_habits",
        "description": "Query RadioMind's L3 habit memories — deep, distilled patterns about the user encoded in HDC hypervectors.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Query to match against habits"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "radiomind_digest",
        "description": "Get RadioMind's context digest — a compressed summary of user profile + system state for system prompt injection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "token_budget": {"type": "integer", "description": "Max tokens for digest (default: 250)", "default": 250},
            },
        },
    },
    {
        "name": "radiomind_status",
        "description": "Get RadioMind memory statistics: counts by level, domains, habits, LLM usage.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "radiomind_chat",
        "description": "Trigger RadioMind's chat refinement — three-body debate (Guardian/Explorer/Reducer) to distill new insights from memories. Requires LLM backend.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Optional: focus on a specific domain"},
            },
        },
    },
    {
        "name": "radiomind_dream",
        "description": "Trigger RadioMind's dream refinement — SHY pruning (decay/merge/archive) + DMN wandering (random association for meta-patterns). Requires LLM backend.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


class MCPServer:
    def __init__(self):
        self._mind: RadioMind | None = None

    def _ensure_mind(self) -> RadioMind:
        if self._mind is None:
            self._mind = RadioMind()
            self._mind.initialize()
        return self._mind

    def handle_request(self, request: dict) -> dict:
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                }
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self._handle_tool_call(params)
            elif method == "notifications/initialized":
                return {}  # no response for notifications
            elif method == "ping":
                result = {}
            else:
                return self._error(req_id, -32601, f"Method not found: {method}")

            if req_id is not None:
                return {"jsonrpc": "2.0", "id": req_id, "result": result}
            return {}

        except Exception as e:
            return self._error(req_id, -32603, str(e))

    def _handle_tool_call(self, params: dict) -> dict:
        tool_name = params.get("name", "")
        args = params.get("arguments", {})
        mind = self._ensure_mind()

        if tool_name == "radiomind_search":
            results = mind.search(args["query"], domain=args.get("domain"))
            text = "\n".join(
                f"[{r.entry.level.name}/{r.entry.domain}] {r.entry.content}"
                for r in results[:10]
            )
            return {"content": [{"type": "text", "text": text or "No results found."}]}

        elif tool_name == "radiomind_ingest":
            messages = [Message(role=m["role"], content=m["content"]) for m in args["messages"]]
            entries = mind.ingest(messages)
            return {"content": [{"type": "text", "text": f"Ingested {len(entries)} memories."}]}

        elif tool_name == "radiomind_learn":
            entries = mind.learn(args["text"])
            return {"content": [{"type": "text", "text": f"Learned {len(entries)} entry."}]}

        elif tool_name == "radiomind_habits":
            habits = mind.query_habits(args["query"])
            text = "\n".join(
                f"[{h.status.value}] {h.description} (confidence={h.confidence:.1f})"
                for h in habits
            )
            return {"content": [{"type": "text", "text": text or "No habits found."}]}

        elif tool_name == "radiomind_digest":
            budget = args.get("token_budget", 250)
            digest = mind.get_context_digest(token_budget=budget)
            return {"content": [{"type": "text", "text": digest}]}

        elif tool_name == "radiomind_status":
            stats = mind.stats()
            text = json.dumps(stats, ensure_ascii=False, indent=2)
            return {"content": [{"type": "text", "text": text}]}

        elif tool_name == "radiomind_chat":
            if not mind._llm.is_available():
                return {"content": [{"type": "text", "text": "No LLM backend available."}]}
            result = mind.trigger_chat(domain=args.get("domain"))
            text = f"Chat refinement done in {result.duration_s:.1f}s.\n"
            text += f"New insights: {len(result.new_insights)}\n"
            for i in result.new_insights:
                text += f"  - {i.description}\n"
            return {"content": [{"type": "text", "text": text}]}

        elif tool_name == "radiomind_dream":
            if not mind._llm.is_available():
                return {"content": [{"type": "text", "text": "No LLM backend available."}]}
            result = mind.trigger_dream()
            text = f"Dream done in {result.duration_s:.1f}s. Merged: {result.merged}, Pruned: {result.pruned}\n"
            for i in result.new_insights:
                text += f"  Wandering insight: {i.description}\n"
            return {"content": [{"type": "text", "text": text}]}

        return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    def shutdown(self):
        if self._mind:
            self._mind.shutdown()


def main():
    """Run MCP server on stdio."""
    server = MCPServer()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = server.handle_request(request)
        if response:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

    server.shutdown()


if __name__ == "__main__":
    main()
