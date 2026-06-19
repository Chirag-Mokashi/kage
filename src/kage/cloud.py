"""CloudClient — multi-vendor cloud LLM transport (Cycle 12 Slice 1).

THE single cloud egress sink: every cloud-bound request funnels through
`CloudClient.complete()`. Both kage's cloud paths reach it — single-shot
(`_call_cloud` → `_call_cloud_chat`) and multi-turn (`chat`/session → `_call_cloud_chat`).
The provider dispatch (claude / openai-compat / gemini) is moved verbatim from
`cli._call_cloud_chat`. cli re-exports `CloudError` + `DEFAULT_PROVIDERS` and forwards
`_call_cloud_chat`/`_call_cloud` to `runtime.cloud.complete()`.
"""

from __future__ import annotations

import os
import urllib.error
from collections.abc import Callable

from kage.http import _post_json


class CloudError(Exception):
    """Raised on any cloud-provider dispatch failure."""


DEFAULT_PROVIDERS: dict[str, dict] = {
    "claude":     {"type": "claude",        "api_key_env": "ANTHROPIC_API_KEY",  "model": "claude-sonnet-4-6"},
    "openai":     {"type": "openai",        "api_key_env": "OPENAI_API_KEY",     "model": "gpt-4o"},
    "gemini":     {"type": "gemini",        "api_key_env": "GEMINI_API_KEY",     "model": "gemini-2.0-flash"},
    "groq":       {"type": "openai-compat", "api_key_env": "GROQ_API_KEY",       "model": "llama-3.3-70b-versatile",
                   "base_url": "https://api.groq.com/openai", "chat_path": "/v1/chat/completions"},
    "perplexity": {"type": "openai-compat", "api_key_env": "PERPLEXITY_API_KEY", "model": "llama-3.1-sonar-large-128k-online",
                   "base_url": "https://api.perplexity.ai",   "chat_path": "/chat/completions"},
}


def _dispatch_claude(pcfg: dict, key: str, system: str, messages: list[dict]) -> str:
    out = _post_json(
        "https://api.anthropic.com/v1/messages",
        {"model": pcfg.get("model", ""), "max_tokens": 1024, "system": system, "messages": messages},
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    return out["content"][0]["text"].strip()


def _dispatch_openai_compat(pcfg: dict, key: str, system: str, messages: list[dict]) -> str:
    base = pcfg.get("base_url", "https://api.openai.com")
    path = pcfg.get("chat_path", "/v1/chat/completions")
    out = _post_json(
        f"{base}{path}",
        {"model": pcfg.get("model", ""), "max_tokens": 1024,
         "messages": [{"role": "system", "content": system}] + messages},
        headers={"Authorization": f"Bearer {key}"},
    )
    return out["choices"][0]["message"]["content"].strip()


def _dispatch_gemini(pcfg: dict, key: str, system: str, messages: list[dict]) -> str:
    model = pcfg.get("model", "")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{model}:generateContent?key={key}"
    )
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user",
         "parts": [{"text": m["content"]}]}
        for m in messages
    ]
    out = _post_json(url, {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
    })
    candidates = out.get("candidates") or []
    if not candidates or "content" not in candidates[0]:
        raise CloudError("Gemini returned no content")
    return candidates[0]["content"]["parts"][0]["text"].strip()


_PROVIDER_REGISTRY: dict[str, Callable[[dict, str, str, list[dict]], str]] = {}


def register_provider_type(
    name: str,
    dispatch_fn: Callable[[dict, str, str, list[dict]], str],
) -> None:
    _PROVIDER_REGISTRY[name] = dispatch_fn


register_provider_type("claude", _dispatch_claude)
register_provider_type("openai", _dispatch_openai_compat)
register_provider_type("openai-compat", _dispatch_openai_compat)
register_provider_type("gemini", _dispatch_gemini)


class CloudClient:
    """The cloud egress seam. `complete()` is the single sink all cloud paths funnel through."""

    def complete(self, provider_name: str, system: str, messages: list[dict], cfg: dict) -> str:
        """Multi-turn chat dispatch. messages = history + current user turn (no system message)."""
        default_pcfg = DEFAULT_PROVIDERS.get(provider_name, {})
        user_pcfg = cfg.get("providers", {}).get(provider_name, {})
        if not default_pcfg and not user_pcfg:
            raise CloudError(
                f"Unknown provider '{provider_name}'. "
                f"Add providers.{provider_name} to ~/.kage/config.json"
            )
        pcfg = {**default_pcfg, **user_pcfg}
        key = os.environ.get(pcfg["api_key_env"], "")
        if not key:
            raise CloudError(f"{pcfg['api_key_env']} not set (provider: {provider_name})")
        ptype = pcfg.get("type", "openai-compat")
        dispatch_fn = _PROVIDER_REGISTRY.get(ptype)
        if dispatch_fn is None:
            raise CloudError(f"Unknown provider type '{ptype}'")
        try:
            return dispatch_fn(pcfg, key, system, messages)
        except (urllib.error.URLError, KeyError, IndexError, TimeoutError) as exc:
            raise CloudError(f"Provider '{provider_name}' request failed: {exc}") from exc
