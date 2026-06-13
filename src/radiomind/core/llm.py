"""Unified LLM backend — nothing hardcoded."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from radiomind.core.config import Config

# Bypass system proxy (macOS scutil-level / Surge / Clash).
# Default urllib auto-picks system proxy config, which blocks the whole
# RadioMind pipeline when the user's proxy client is misbehaving or down
# (indefinite SSL handshake hang to localhost:6152). Every LLM + API
# call should go direct unless the user explicitly sets HTTPS_PROXY.
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ollama_ready(host: str, timeout: int = 5) -> bool:
    """Shared Ollama liveness probe: the daemon answers /api/tags AND has
    at least one model pulled. Both the auto-detect path (llm_auto P3) and
    the config-router path use THIS function — the two probes drifted once
    (LLMRouter-1a defect B: an installed-but-empty ollama outranked the
    configured cloud backend and 404'd every call) and must not drift again.
    """
    try:
        req = urllib.request.Request(f"{host.rstrip('/')}/api/tags")
        with _NO_PROXY_OPENER.open(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return bool(data.get("models"))
    except Exception:
        return False


@dataclass
class LLMResponse:
    text: str
    model: str
    tokens_prompt: int = 0
    tokens_completion: int = 0
    duration_s: float = 0.0


@dataclass
class LLMUsageTracker:
    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    by_model: dict[str, int] = field(default_factory=dict)

    def record(self, resp: LLMResponse) -> None:
        self.total_calls += 1
        self.total_prompt_tokens += resp.tokens_prompt
        self.total_completion_tokens += resp.tokens_completion
        self.by_model[resp.model] = self.by_model.get(resp.model, 0) + 1


class LLMBackend(ABC):
    @abstractmethod
    def generate(self, prompt: str, system: str = "", model: str = "",
                 max_tokens: int | None = None) -> LLMResponse:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...


class OllamaBackend(LLMBackend):
    def __init__(self, host: str = "http://localhost:11434", default_model: str = "qwen3:0.6b"):
        self.host = host.rstrip("/")
        self.default_model = default_model

    def generate(self, prompt: str, system: str = "", model: str = "",
                 max_tokens: int | None = None) -> LLMResponse:
        model = model or self.default_model
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            body["system"] = system
        # OpenAICompatOptions-1b: Ollama caps completion via options.num_predict.
        if max_tokens is not None:
            body["options"] = {"num_predict": max_tokens}

        t0 = time.time()
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with _NO_PROXY_OPENER.open(req, timeout=120) as resp:
            result = json.loads(resp.read())

        duration = time.time() - t0
        return LLMResponse(
            text=result.get("response", ""),
            model=model,
            tokens_prompt=result.get("prompt_eval_count", 0),
            tokens_completion=result.get("eval_count", 0),
            duration_s=duration,
        )

    def is_available(self) -> bool:
        # LLMRouter-1b Fix B: a daemon with zero models cannot serve —
        # shared probe, see ollama_ready.
        return ollama_ready(self.host)


class OpenAICompatBackend(LLMBackend):
    def __init__(self, base_url: str, api_key: str, default_model: str = "deepseek-chat",
                 timeout: int = 45, max_tokens: int | None = None):
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self._endpoint = f"{self.base_url}/chat/completions"
        else:
            self._endpoint = f"{self.base_url}/v1/chat/completions"
        self.api_key = api_key
        self.default_model = default_model
        # LLMRouter-1b: per-profile override via [llm.<name>] timeout = N.
        # The 45s default was sized for short benchmark-era calls; long
        # refinement generations (multi-stance debate JSON) legitimately
        # exceed it — a too-tight cap here silently kills every chat
        # refinement via trinity's exception-swallowing _call_llm.
        self.timeout = timeout
        # OpenAICompatOptions-1b: per-profile default completion cap via
        # [llm.<name>] max_tokens = N. None ⇒ omit the field ⇒ provider's
        # own default (current behavior). The truncation analogue of the
        # timeout fix: a small provider default silently clips long
        # refinement JSON instead of timing it out.
        self.max_tokens = max_tokens

    def generate(self, prompt: str, system: str = "", model: str = "",
                 max_tokens: int | None = None) -> LLMResponse:
        model = model or self.default_model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {"model": model, "messages": messages, "stream": False}
        # Call-site override wins; else per-profile default; else omit.
        effective_max = max_tokens if max_tokens is not None else self.max_tokens
        if effective_max is not None:
            body["max_tokens"] = effective_max

        t0 = time.time()
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self._endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        # Default 45s (short-call sizing, see __init__); profiles serving
        # refinement-class long generations set [llm.<name>] timeout higher.
        with _NO_PROXY_OPENER.open(req, timeout=self.timeout) as resp:
            result = json.loads(resp.read())

        duration = time.time() - t0
        usage = result.get("usage", {})
        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError(f"LLM returned empty choices: {result}")
        text = choices[0].get("message", {}).get("content", "")
        return LLMResponse(
            text=text,
            model=model,
            tokens_prompt=usage.get("prompt_tokens", 0),
            tokens_completion=usage.get("completion_tokens", 0),
            duration_s=duration,
        )

    def is_available(self) -> bool:
        return bool(self.base_url and self.api_key)


LLMCallable = Any  # Callable[[str, str], str]  (prompt, system) → response text


class CallableBackend(LLMBackend):
    """Wraps an external callable as an LLMBackend.

    Accepts any function with signature: (prompt: str, system: str) → str
    This lets host frameworks inject their own LLM without RadioMind config.

    Examples:
        # Simple function
        def my_llm(prompt, system=""): return openai.chat(...)
        mind = RadioMind(llm=my_llm)

        # Lambda
        mind = RadioMind(llm=lambda p, s: client.generate(p, system_prompt=s))

        # LangChain
        mind = RadioMind(llm=lambda p, s: chain.invoke({"input": p}))
    """

    def __init__(self, fn: LLMCallable, name: str = "external"):
        self._fn = fn
        self._name = name

    def generate(self, prompt: str, system: str = "", model: str = "",
                 max_tokens: int | None = None) -> LLMResponse:
        # OpenAICompatOptions-1b: the wrapped callable is (prompt, system)
        # only — max_tokens cannot be threaded through it, so it is
        # accepted-and-ignored here (host frameworks size their own calls).
        t0 = time.time()
        text = self._fn(prompt, system)
        return LLMResponse(
            text=str(text),
            model=self._name,
            duration_s=time.time() - t0,
        )

    def is_available(self) -> bool:
        return True


class LLMRouter:
    """Routes LLM calls based on config. Falls back gracefully."""

    # llm.* keys that are NOT OpenAI-compatible profile sections
    _RESERVED_LLM_KEYS = ("ollama", "openai", "models", "default_backend")

    def __init__(self, config: Config):
        self.config = config
        self.usage = LLMUsageTracker()
        self._backends: dict[str, LLMBackend] = {}
        self._warned_fallback: set[str] = set()
        self._init_backends()

    def _init_backends(self) -> None:
        ollama_cfg = self.config.get("llm.ollama", {})
        if ollama_cfg.get("host"):
            self._backends["ollama"] = OllamaBackend(
                host=ollama_cfg["host"],
                default_model=ollama_cfg.get("model", "qwen3:0.6b"),
            )

        openai_cfg = self.config.get("llm.openai", {})
        if openai_cfg.get("base_url") and openai_cfg.get("api_key"):
            self._backends["openai"] = OpenAICompatBackend(
                base_url=openai_cfg["base_url"],
                api_key=openai_cfg["api_key"],
                default_model=openai_cfg.get("model", "deepseek-chat"),
                timeout=int(openai_cfg.get("timeout", 45)),
                max_tokens=openai_cfg.get("max_tokens"),
            )

        # LLMRouter-1b Fix A: every other [llm.<name>] section that carries
        # base_url + api_key is an OpenAI-compatible profile (dashscope,
        # openrouter, openai_direct, ...). Before this, only the two
        # hardcoded sections above were ever built — 1a defect A:
        # default_backend = "dashscope" silently fell back to whatever
        # _find_available picked (on this machine, a dead endpoint).
        llm_cfg = self.config.get("llm", {}) or {}
        for name, sec in llm_cfg.items():
            if name in self._RESERVED_LLM_KEYS or name in self._backends:
                continue
            if isinstance(sec, dict) and sec.get("base_url") and sec.get("api_key"):
                self._backends[name] = OpenAICompatBackend(
                    base_url=sec["base_url"],
                    api_key=sec["api_key"],
                    default_model=sec.get("model", ""),
                    timeout=int(sec.get("timeout", 45)),
                    max_tokens=sec.get("max_tokens"),
                )

    def set_external(self, fn: LLMCallable, name: str = "external") -> None:
        """Inject an external LLM callable as the primary backend."""
        self._backends["external"] = CallableBackend(fn, name=name)
        self.config.set("llm.default_backend", "external")

    def generate(
        self,
        prompt: str,
        system: str = "",
        model: str = "",
        backend: str = "",
        cost_tier: str = "",
        max_tokens: int | None = None,
    ) -> LLMResponse:
        # Resolve model from cost tier if no explicit model given
        if not model and cost_tier:
            model = self.config.get(f"llm.models.{cost_tier}", "")
        if not model:
            mode = self.config.get("refinement.cost_mode", "economy")
            tier_model = self.config.get(f"llm.models.{mode}", "")
            if tier_model:
                model = tier_model

        backend_name = backend or self.config.get("llm.default_backend", "ollama")
        be = self._backends.get(backend_name)

        if be is None or not be.is_available():
            found = self._find_available()
            if found is None:
                raise RuntimeError(
                    "No LLM backend available. Configure llm.openai in ~/.radiomind/config.toml"
                )
            fb_name, be = found
            # LLMRouter-1b Fix C: never reroute silently — 1a defect C: the
            # dead TokenPlan endpoint absorbed every refinement call without
            # a trace. Warn once per requested backend per router instance.
            if backend_name not in self._warned_fallback:
                self._warned_fallback.add(backend_name)
                logger.warning(
                    "llm backend '%s' unavailable or not configured; "
                    "falling back to '%s'", backend_name, fb_name,
                )

        # max_tokens None ⇒ backend uses its per-profile default (or omits).
        resp = be.generate(prompt, system=system, model=model,
                           max_tokens=max_tokens)
        self.usage.record(resp)
        return resp

    def is_available(self) -> bool:
        return any(b.is_available() for b in self._backends.values())

    def available_backends(self) -> list[str]:
        return [name for name, b in self._backends.items() if b.is_available()]

    def _find_available(self) -> tuple[str, LLMBackend] | None:
        for name, be in self._backends.items():
            if be.is_available():
                return name, be
        return None
