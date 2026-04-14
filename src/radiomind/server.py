"""RadioMind REST API — cross-language access via HTTP.

4 endpoints matching the Protocol:
  POST /v1/add      — add conversation messages
  POST /v1/search   — search memories
  GET  /v1/digest   — get context digest
  POST /v1/refine   — run refinement cycle

Plus utility endpoints:
  GET  /v1/status    — memory statistics
  GET  /health       — health check

Auth: Bearer token from config (optional, disabled if no token set).

Usage:
  radiomind serve --port 8730
  curl -X POST http://localhost:8730/v1/search -d '{"query":"running"}'
"""

from __future__ import annotations

from typing import Any

from radiomind.core.config import Config
from radiomind.simple import SimpleRadioMind

_mind: SimpleRadioMind | None = None


def create_app(config: Config | None = None) -> Any:
    """Create FastAPI app. Lazy import to keep fastapi optional."""
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field

    cfg = config or Config.load()
    auth_token = cfg.get("server.auth_token", "")

    app = FastAPI(
        title="RadioMind",
        description="Bionic memory core for AI agents",
        version="0.1.0",
    )

    cors_origins = cfg.get("server.cors_origins", "http://localhost:*")
    if cors_origins == "*":
        import warnings
        warnings.warn("CORS allow_origins='*' is insecure for non-local deployments")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cors_origins] if cors_origins != "*" else ["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # --- Auth ---

    async def check_auth(request: Request):
        if not auth_token:
            return
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(401, "Missing Authorization header")
        if header[7:] != auth_token:
            raise HTTPException(403, "Invalid token")

    # --- Models ---

    class MessageIn(BaseModel):
        role: str = "user"
        content: str

    class AddRequest(BaseModel):
        messages: list[MessageIn]
        user_id: str = ""

    class AddResponse(BaseModel):
        added: int
        skipped: int

    class SearchRequest(BaseModel):
        query: str
        limit: int = 10
        domain: str | None = None

    class MemoryOut(BaseModel):
        content: str
        domain: str = ""
        level: str = "fact"
        score: float = 0.0
        metadata: dict[str, Any] = Field(default_factory=dict)

    class SearchResponse(BaseModel):
        query: str
        count: int
        results: list[MemoryOut]

    class RefineRequest(BaseModel):
        domain: str | None = None

    class RefineResponse(BaseModel):
        insights: int
        merged: int
        pruned: int
        duration_s: float

    class DigestResponse(BaseModel):
        digest: str
        token_budget: int

    class StatusResponse(BaseModel):
        version: str
        total_active: int
        habits: int
        domains: int
        llm_available: bool

    # --- Startup ---

    @app.on_event("startup")
    async def startup():
        global _mind
        _mind = SimpleRadioMind()

    @app.on_event("shutdown")
    async def shutdown():
        global _mind
        if _mind:
            _mind.close()
            _mind = None

    def get_mind() -> SimpleRadioMind:
        if _mind is None:
            raise HTTPException(503, "RadioMind not initialized")
        return _mind

    # --- Endpoints ---

    @app.post("/v1/add", response_model=AddResponse, dependencies=[Depends(check_auth)])
    async def add_memories(req: AddRequest):
        mind = get_mind()
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
        result = mind.add(messages, user_id=req.user_id)
        return AddResponse(added=result.added, skipped=result.skipped)

    @app.post("/v1/search", response_model=SearchResponse, dependencies=[Depends(check_auth)])
    async def search_memories(req: SearchRequest):
        mind = get_mind()
        results = mind.search(req.query, limit=req.limit, domain=req.domain)
        return SearchResponse(
            query=req.query,
            count=len(results),
            results=[
                MemoryOut(
                    content=r.content,
                    domain=r.domain,
                    level=r.level,
                    score=r.score,
                    metadata=r.metadata,
                )
                for r in results
            ],
        )

    @app.get("/v1/digest", response_model=DigestResponse, dependencies=[Depends(check_auth)])
    async def get_digest(token_budget: int = 250):
        mind = get_mind()
        digest = mind.digest(token_budget=token_budget)
        return DigestResponse(digest=digest, token_budget=token_budget)

    @app.post("/v1/refine", response_model=RefineResponse, dependencies=[Depends(check_auth)])
    async def refine(req: RefineRequest):
        mind = get_mind()
        result = mind.refine(domain=req.domain)
        return RefineResponse(
            insights=result.insights,
            merged=result.merged,
            pruned=result.pruned,
            duration_s=result.duration_s,
        )

    @app.get("/v1/status", response_model=StatusResponse, dependencies=[Depends(check_auth)])
    async def status():
        mind = get_mind()
        s = mind.advanced.stats()
        return StatusResponse(
            version="0.1.0",
            total_active=s["total_active"],
            habits=s["habits"],
            domains=s["domain_count"],
            llm_available=s["llm_available"],
        )

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    return app


def run_server(host: str = "0.0.0.0", port: int = 8730):
    """Run the REST API server."""
    import uvicorn
    app = create_app()
    uvicorn.run(app, host=host, port=port)
