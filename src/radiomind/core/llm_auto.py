"""Auto-detect LLM from environment — zero config for 95% of setups.

Priority (handled by RadioMind._resolve_llm):
1. Host framework LLM (llm= parameter)    ← highest priority
2. Environment variables (API keys)        ← user already has these
3. Local Ollama (localhost:11434)           ← free, just needs to be installed
4. config.toml (if exists)                 ← advanced users / standalone
5. No LLM → pure memory mode              ← add/search/digest still work

Most users never touch config.toml — it's only for advanced overrides.
RadioMind automatically uses whatever LLM is available in the environment.
"""

from __future__ import annotations

import os
from typing import Any

from radiomind.core.llm import (
    CallableBackend,
    LLMBackend,
    LLMResponse,
    OllamaBackend,
    OpenAICompatBackend,
)

# Environment variable → (base_url, model) mapping
ENV_PROVIDERS: list[tuple[str, str, str]] = [
    # (env_var, base_url, default_model)
    ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "claude-sonnet-4-20250514"),
    ("DASHSCOPE_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    ("TOGETHER_API_KEY", "https://api.together.xyz/v1", "meta-llama/Llama-3-70b-chat-hf"),
    ("MOONSHOT_API_KEY", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ("ZHIPUAI_API_KEY", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    ("SILICONFLOW_API_KEY", "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct"),
    ("MISTRAL_API_KEY", "https://api.mistral.ai/v1", "mistral-small-latest"),
    ("FIREWORKS_API_KEY", "https://api.fireworks.ai/inference/v1", "accounts/fireworks/models/llama-v3p1-70b-instruct"),
]


def auto_detect(llm: Any = None) -> LLMBackend | None:
    """Auto-detect the best available LLM backend.

    Args:
        llm: Optional hint — can be:
             - None: auto-detect from environment
             - callable: (prompt, system) → str
             - OpenAI client object
             - Anthropic client object
             - str: model name for Ollama (e.g. "qwen3:0.6b")

    Returns:
        LLMBackend or None if nothing found.
    """
    if llm is not None:
        return _from_object(llm)

    # Try environment variables
    backend = _from_env()
    if backend:
        return backend

    # Try local Ollama
    backend = _from_ollama()
    if backend:
        return backend

    return None


def _from_object(obj: Any) -> LLMBackend | None:
    """Identify and wrap a passed object."""
    # Already a callable with (prompt, system) → str
    if callable(obj) and not hasattr(obj, "chat") and not hasattr(obj, "messages"):
        return CallableBackend(obj, name="callable")

    # String → treat as Ollama model name
    if isinstance(obj, str):
        return OllamaBackend(default_model=obj)

    # OpenAI client (has .chat.completions.create)
    if _is_openai_client(obj):
        return _wrap_openai(obj)

    # Anthropic client (has .messages.create)
    if _is_anthropic_client(obj):
        return _wrap_anthropic(obj)

    # LiteLLM completion function
    if callable(obj) and hasattr(obj, "__module__") and "litellm" in str(getattr(obj, "__module__", "")):
        return _wrap_litellm(obj)

    # Last resort: try as callable with flexible signature
    if callable(obj):
        return CallableBackend(obj, name="callable")

    return None


def _from_env() -> LLMBackend | None:
    """Detect LLM from environment variables."""
    for env_var, base_url, default_model in ENV_PROVIDERS:
        api_key = os.environ.get(env_var)
        if api_key:
            # Special case: Anthropic uses a different API format
            if "anthropic" in env_var.lower():
                return _make_anthropic_backend(api_key)
            return OpenAICompatBackend(
                base_url=base_url,
                api_key=api_key,
                default_model=default_model,
            )
    return None


def _from_ollama() -> LLMBackend | None:
    """Check if local Ollama is running."""
    backend = OllamaBackend()
    if backend.is_available():
        return backend
    return None


# --- Client type detection ---

def _is_openai_client(obj: Any) -> bool:
    try:
        return hasattr(obj, "chat") and hasattr(obj.chat, "completions")
    except Exception:
        return False


def _is_anthropic_client(obj: Any) -> bool:
    try:
        return hasattr(obj, "messages") and hasattr(obj.messages, "create")
    except Exception:
        return False


# --- Wrappers ---

def _wrap_openai(client: Any) -> CallableBackend:
    """Wrap OpenAI client as LLMBackend."""
    def generate(prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=getattr(client, "_default_model", "gpt-4o-mini"),
            messages=messages,
        )
        return resp.choices[0].message.content or ""
    return CallableBackend(generate, name="openai")


def _wrap_anthropic(client: Any) -> CallableBackend:
    """Wrap Anthropic client as LLMBackend."""
    def generate(prompt: str, system: str = "") -> str:
        kwargs = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        return resp.content[0].text if resp.content else ""
    return CallableBackend(generate, name="anthropic")


def _make_anthropic_backend(api_key: str) -> CallableBackend:
    """Create Anthropic backend from API key (lazy import)."""
    def generate(prompt: str, system: str = "") -> str:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            kwargs = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system
            resp = client.messages.create(**kwargs)
            return resp.content[0].text if resp.content else ""
        except ImportError:
            return ""
    return CallableBackend(generate, name="anthropic")


def _wrap_litellm(completion_fn: Any) -> CallableBackend:
    """Wrap LiteLLM completion function."""
    def generate(prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = completion_fn(messages=messages)
        return resp.choices[0].message.content or ""
    return CallableBackend(generate, name="litellm")
