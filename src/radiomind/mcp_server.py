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
    {
        "name": "radiomind_refine_step",
        "description": "Step-by-step refinement — YOU (the host AI) do the thinking, RadioMind organizes. "
                       "Call with step='prepare' to start a debate. RadioMind returns a prompt for you to reason about. "
                       "Then call again with your response and the next step name. "
                       "Steps: prepare → guardian → explorer → reducer → synthesize. "
                       "For dreaming: dream_prune → dream_apply, dream_wander → dream_apply. "
                       "This mode requires NO external LLM — you ARE the LLM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "step": {
                    "type": "string",
                    "description": "Step name: prepare/guardian/explorer/reducer/synthesize/dream_prune/dream_wander/dream_apply",
                    "enum": ["prepare", "guardian", "explorer", "reducer", "synthesize", "dream_prune", "dream_wander", "dream_apply"],
                },
                "domain": {"type": "string", "description": "Domain to focus on (required for prepare/dream_prune)"},
                "response": {"type": "string", "description": "Your reasoning response to the previous step's prompt"},
            },
            "required": ["step"],
        },
    },
    {
        "name": "radiomind_push_habits",
        "description": "Push confirmed habits to host platform's native memory "
                       "(Claude Code memory files, Codex AGENTS.md, Cursor .cursorrules). "
                       "Idempotent — safe to call multiple times. Uses markers to track and update individual habits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "Force platform: claude-code, codex, cursor"},
                "project_dir": {"type": "string", "description": "Project directory (default: cwd)"},
                "dry_run": {"type": "boolean", "description": "Preview without writing", "default": False},
            },
        },
    },
    {
        "name": "radiomind_reject_habit",
        "description": "Mark a habit as incorrect or not applicable to this user. "
                       "Use this when you (the AI) notice the user's actual behavior contradicts a stored habit, "
                       "or when the user explicitly says a habit is wrong. "
                       "Two rejections archive the habit automatically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "habit_index": {"type": "integer", "description": "Zero-based index of the habit (from radiomind_habits)"},
                "reason": {"type": "string", "description": "Brief reason for rejection"},
            },
            "required": ["habit_index"],
        },
    },
    {
        "name": "radiomind_get_memory",
        "description": "Fetch a single memory by its id. Returns content, domain, level, user/session scope, and timestamps.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "integer"}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "radiomind_update_memory",
        "description": "Update a memory's content and/or metadata. Writes an entry to the history audit trail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "integer"},
                "content": {"type": "string", "description": "New content (optional)"},
                "metadata": {"type": "object", "description": "Replacement metadata (optional)"},
            },
            "required": ["memory_id"],
        },
    },
    {
        "name": "radiomind_delete_memory",
        "description": "Delete a single memory by id. The deletion is recorded in memory_history for audit.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "integer"}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "radiomind_list_memories",
        "description": "List memories filtered by scope (user_id / agent_id / session_id). "
                       "Returns up to `limit` entries, newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "session_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "radiomind_memory_history",
        "description": "Get the audit history of a memory (created / updated / deleted events with before/after content).",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "integer"}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "radiomind_delete_scope",
        "description": "Delete ALL memories matching a scope (user_id / agent_id / session_id). "
                       "Refuses if no scope is provided — use this only when the user explicitly asks "
                       "to wipe their own data. Returns count deleted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "session_id": {"type": "string"},
            },
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
            resp = mind.search_with_habits(args["query"], domain=args.get("domain"))
            lines = [
                f"[{r.entry.level.name}/{r.entry.domain}] {r.entry.content}"
                for r in resp.results[:10]
            ]
            if resp.matched_habits:
                lines.append("\n--- Matched Habits ---")
                for h, score in resp.matched_habits:
                    line = f"[{h.status.value}|c={h.confidence:.1f}|sim={score:.2f}] {h.description}"
                    if h.evidence:
                        line += f"\n    evidence: {h.evidence}"
                    lines.append(line)
            text = "\n".join(lines)
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
            lines = []
            for h in habits:
                line = f"[{h.status.value}] {h.description} (confidence={h.confidence:.1f}"
                line += f", hits={h.hit_count}" if h.hit_count else ""
                line += ")"
                if h.evidence:
                    line += f"\n    evidence: {h.evidence}"
                if h.falsifier:
                    line += f"\n    falsifier: {h.falsifier}"
                lines.append(line)
            text = "\n".join(lines)
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
            if not mind.is_llm_available():
                return {"content": [{"type": "text", "text": "No LLM backend available."}]}
            result = mind.trigger_chat(domain=args.get("domain"))
            text = f"Chat refinement done in {result.duration_s:.1f}s.\n"
            text += f"New insights: {len(result.new_insights)}\n"
            for i in result.new_insights:
                text += f"  - {i.description}\n"
            return {"content": [{"type": "text", "text": text}]}

        elif tool_name == "radiomind_dream":
            if not mind.is_llm_available():
                return {"content": [{"type": "text", "text": "No LLM backend available."}]}
            result = mind.trigger_dream()
            text = f"Dream done in {result.duration_s:.1f}s. Merged: {result.merged}, Pruned: {result.pruned}\n"
            for i in result.new_insights:
                text += f"  Wandering insight: {i.description}\n"
            return {"content": [{"type": "text", "text": text}]}

        elif tool_name == "radiomind_push_habits":
            result = mind.push_habits(
                platform=args.get("platform"),
                project_dir=args.get("project_dir"),
                dry_run=args.get("dry_run", False),
            )
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}

        elif tool_name == "radiomind_reject_habit":
            idx = args.get("habit_index")
            reason = args.get("reason", "")
            if idx is None:
                return {"content": [{"type": "text", "text": "habit_index required."}], "isError": True}
            mind.reject_habit(int(idx), reason=reason)
            habits = mind._habits.all_habits()
            if 0 <= int(idx) < len(habits):
                h = habits[int(idx)]
                return {"content": [{"type": "text", "text": f"Rejected habit #{idx}: '{h.description}' (reject_count={h.reject_count}, status={h.status.value})"}]}
            return {"content": [{"type": "text", "text": f"Rejected habit #{idx}."}]}

        elif tool_name == "radiomind_get_memory":
            mid = args.get("memory_id")
            if mid is None:
                return {"content": [{"type": "text", "text": "memory_id required."}], "isError": True}
            entry = mind.get_memory(int(mid))
            if entry is None:
                return {"content": [{"type": "text", "text": f"Memory {mid} not found."}]}
            payload = {
                "id": entry.id,
                "content": entry.content,
                "domain": entry.domain,
                "level": entry.level.name.lower(),
                "user_id": entry.user_id,
                "agent_id": entry.agent_id,
                "session_id": entry.session_id,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "hit_count": entry.hit_count,
                "metadata": entry.metadata,
            }
            return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]}

        elif tool_name == "radiomind_update_memory":
            mid = args.get("memory_id")
            if mid is None:
                return {"content": [{"type": "text", "text": "memory_id required."}], "isError": True}
            entry = mind.update_memory(
                int(mid),
                content=args.get("content"),
                metadata=args.get("metadata"),
            )
            if entry is None:
                return {"content": [{"type": "text", "text": f"Memory {mid} not found."}]}
            return {"content": [{"type": "text", "text": f"Updated memory {mid}."}]}

        elif tool_name == "radiomind_delete_memory":
            mid = args.get("memory_id")
            if mid is None:
                return {"content": [{"type": "text", "text": "memory_id required."}], "isError": True}
            ok = mind.delete_memory(int(mid))
            msg = f"Deleted memory {mid}." if ok else f"Memory {mid} not found."
            return {"content": [{"type": "text", "text": msg}]}

        elif tool_name == "radiomind_list_memories":
            entries = mind.list_memories(
                user_id=args.get("user_id", ""),
                agent_id=args.get("agent_id", ""),
                session_id=args.get("session_id", ""),
                limit=int(args.get("limit", 50)),
            )
            text = "\n".join(
                f"[{e.id}] ({e.domain}/{e.level.name.lower()}) user={e.user_id or '-'} "
                f"session={e.session_id or '-'} — {e.content}"
                for e in entries
            ) or "No memories match this scope."
            return {"content": [{"type": "text", "text": text}]}

        elif tool_name == "radiomind_memory_history":
            mid = args.get("memory_id")
            if mid is None:
                return {"content": [{"type": "text", "text": "memory_id required."}], "isError": True}
            history = mind.memory_history(int(mid))
            return {"content": [{"type": "text", "text": json.dumps(history, ensure_ascii=False, indent=2)}]}

        elif tool_name == "radiomind_delete_scope":
            user_id = args.get("user_id", "")
            agent_id = args.get("agent_id", "")
            session_id = args.get("session_id", "")
            if not (user_id or agent_id or session_id):
                return {"content": [{"type": "text", "text": "Refused: at least one of user_id / agent_id / session_id is required to scope the deletion."}], "isError": True}
            n = mind.delete_all_memories(user_id=user_id, agent_id=agent_id, session_id=session_id)
            return {"content": [{"type": "text", "text": f"Deleted {n} memory/memories in scope."}]}

        elif tool_name == "radiomind_refine_step":
            step = args.get("step", "")
            domain = args.get("domain", "")
            response = args.get("response", "")
            result = mind.refine_step(step, domain=domain, response=response)
            text = json.dumps(result, ensure_ascii=False, indent=2)
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
        except json.JSONDecodeError as e:
            err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
            continue

        response = server.handle_request(request)
        if response:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

    server.shutdown()


if __name__ == "__main__":
    main()
