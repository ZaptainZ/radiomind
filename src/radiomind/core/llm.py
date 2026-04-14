"""Unified LLM backend — nothing hardcoded."""

from __future__ import annotations

import json
import time
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from radiomind.core.config import Config


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
    def generate(self, prompt: str, system: str = "", model: str = "") -> LLMResponse:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...


class OllamaBackend(LLMBackend):
    def __init__(self, host: str = "http://localhost:11434", default_model: str = "qwen3:0.6b"):
        self.host = host.rstrip("/")
        self.default_model = default_model

    def generate(self, prompt: str, system: str = "", model: str = "") -> LLMResponse:
        model = model or self.default_model
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            body["system"] = system

        t0 = time.time()
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
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
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False


class OpenAICompatBackend(LLMBackend):
    def __init__(self, base_url: str, api_key: str, default_model: str = "deepseek-chat"):
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self._endpoint = f"{self.base_url}/chat/completions"
        else:
            self._endpoint = f"{self.base_url}/v1/chat/completions"
        self.api_key = api_key
        self.default_model = default_model

    def generate(self, prompt: str, system: str = "", model: str = "") -> LLMResponse:
        model = model or self.default_model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {"model": model, "messages": messages, "stream": False}

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
        with urllib.request.urlopen(req, timeout=120) as resp:
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

    def generate(self, prompt: str, system: str = "", model: str = "") -> LLMResponse:
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

    def __init__(self, config: Config):
        self.config = config
        self.usage = LLMUsageTracker()
        self._backends: dict[str, LLMBackend] = {}
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
            be = self._find_available()
            if be is None:
                raise RuntimeError(
                    "No LLM backend available. Configure llm.openai in ~/.radiomind/config.toml"
                )

        resp = be.generate(prompt, system=system, model=model)
        self.usage.record(resp)
        return resp

    def is_available(self) -> bool:
        return any(b.is_available() for b in self._backends.values())

    def available_backends(self) -> list[str]:
        return [name for name, b in self._backends.items() if b.is_available()]

    def _find_available(self) -> LLMBackend | None:
        for be in self._backends.values():
            if be.is_available():
                return be
        return None
