# Cycle 5 Pitch — Multi-Provider Cloud (v0.5)

*Written: 2026-06-08*

---

## Problem

`kage ask --cloud` is hardwired to Anthropic/Claude. kage's identity is a BROKER — it should
route to whichever cloud the user chooses. The current `if/elif` approach is a closed list:
adding a new provider requires a code change. That violates Modular and Adoptable.

---

## Design: Two-Layer Provider System

### Layer 1 — Provider types (in code, stable — never grows)

```
Type            API shape                    Covers
─────────────────────────────────────────────────────────────────────────────
claude          Anthropic /v1/messages       Claude (all models)
openai          OpenAI /v1/chat/completions  ChatGPT, GPT-4o, o1, o3
gemini          Google generateContent       Gemini 2.0, 1.5, etc.
openai-compat   OpenAI shape + base_url      Groq, Perplexity, Mistral,
                                             Together, Fireworks, LM Studio,
                                             any OpenAI-compatible endpoint
```

Four types. That's the complete set. Adding a new OpenAI-compatible service
(e.g. a future self-hosted inference endpoint) requires zero code.

### Layer 2 — Named provider profiles (in config, unlimited)

Users define named profiles in `~/.kage/config.toml`. Any number. Mix types, models, keys.

```toml
# Active default when --cloud is used without --provider
cloud_provider = "claude"

[providers.claude]
type        = "claude"
api_key_env = "ANTHROPIC_API_KEY"
model       = "claude-sonnet-4-6"

[providers.openai]
type        = "openai"
api_key_env = "OPENAI_API_KEY"
model       = "gpt-4o"

[providers.gemini]
type        = "gemini"
api_key_env = "GEMINI_API_KEY"
model       = "gemini-2.0-flash"

[providers.groq]
type        = "openai-compat"
base_url    = "https://api.groq.com/openai"
api_key_env = "GROQ_API_KEY"
model       = "llama-3.3-70b-versatile"

[providers.perplexity]
type        = "openai-compat"
base_url    = "https://api.perplexity.ai"
api_key_env = "PERPLEXITY_API_KEY"
model       = "llama-3.1-sonar-large-128k-online"
```

**Adding a new provider = add a config block. Zero code.**
Two Groq models = two profiles, same key. Two Claude accounts = two profiles,
different `api_key_env`.

### Built-in defaults

The five profiles above ship as in-code defaults so zero config is needed to use
common providers — just set the env var. User config blocks override/extend them.

---

## Manual Switching Interface

```
# Use config default (cloud_provider in config.toml)
kage ask "what is Layer 3e?" --cloud

# Override on the fly
kage ask "what is Layer 3e?" --cloud --provider openai
kage ask "what is Layer 3e?" --cloud --provider groq
kage ask "what is Layer 3e?" --cloud --provider my-custom-endpoint

# Change default persistently → edit cloud_provider in config.toml
```

---

## Future Cycles (automated routing)

Layer 4 (router) will call `_call_cloud(provider_name, system, msg, cfg)` with a
dynamically chosen name. Because the provider system is config-driven and open-ended,
the router just needs to pick a string — no code changes required to add routing targets.

---

## Implementation Plan (4 steps)

### Step 1 — `CloudError` + `DEFAULT_PROVIDERS` + `_call_cloud()`

```python
class CloudError(Exception): pass

DEFAULT_PROVIDERS = {
    "claude":     {"type": "claude",       "api_key_env": "ANTHROPIC_API_KEY",  "model": "claude-sonnet-4-6"},
    "openai":     {"type": "openai",       "api_key_env": "OPENAI_API_KEY",     "model": "gpt-4o"},
    "gemini":     {"type": "gemini",       "api_key_env": "GEMINI_API_KEY",     "model": "gemini-2.0-flash"},
    "groq":       {"type": "openai-compat","api_key_env": "GROQ_API_KEY",       "model": "llama-3.3-70b-versatile",
                   "base_url": "https://api.groq.com/openai", "chat_path": "/v1/chat/completions"},
    "perplexity": {"type": "openai-compat","api_key_env": "PERPLEXITY_API_KEY", "model": "llama-3.1-sonar-large-128k-online",
                   "base_url": "https://api.perplexity.ai",   "chat_path": "/chat/completions"},
}

def _call_cloud(provider_name: str, system: str, user_msg: str, cfg: dict) -> str:
    # Deep merge per provider: built-in default fields < user config fields
    default_pcfg = DEFAULT_PROVIDERS.get(provider_name, {})
    user_pcfg = cfg.get("providers", {}).get(provider_name, {})
    if not default_pcfg and not user_pcfg:
        raise CloudError(f"Unknown provider '{provider_name}'. "
                         f"Add [providers.{provider_name}] to ~/.kage/config.toml")
    pcfg = {**default_pcfg, **user_pcfg}
    key = os.environ.get(pcfg["api_key_env"], "")
    if not key:
        raise CloudError(f"{pcfg['api_key_env']} not set (provider: {provider_name})")
    ptype = pcfg.get("type", "openai-compat")
    model = pcfg.get("model", "")

    if ptype == "claude":
        out = _post_json(
            "https://api.anthropic.com/v1/messages",
            {"model": model, "max_tokens": 1024, "system": system,
             "messages": [{"role": "user", "content": user_msg}]},
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        return out["content"][0]["text"].strip()

    elif ptype in ("openai", "openai-compat"):
        base = pcfg.get("base_url", "https://api.openai.com")
        path = pcfg.get("chat_path", "/v1/chat/completions")
        out = _post_json(
            f"{base}{path}",
            {"model": model, "max_tokens": 1024,
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user_msg}]},
            headers={"Authorization": f"Bearer {key}"},
        )
        return out["choices"][0]["message"]["content"].strip()

    elif ptype == "gemini":
        url = (f"https://generativelanguage.googleapis.com/v1beta"
               f"/models/{model}:generateContent?key={key}")
        out = _post_json(url, {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user_msg}]}],
        })
        # Guard: Gemini returns candidates with no content on safety block
        candidates = out.get("candidates") or []
        if not candidates or "content" not in candidates[0]:
            raise CloudError(f"Gemini returned no content (provider: {provider_name})")
        return candidates[0]["content"]["parts"][0]["text"].strip()

    raise CloudError(f"Unknown provider type '{ptype}'")
```

### Step 2 — `ask`: add `--provider` flag, use `_call_cloud()`

- New option: `--provider TEXT` (default `None`)
- Effective provider = flag → `cfg["cloud_provider"]` → `"claude"`
- Replace inline Anthropic block with `_call_cloud(provider, system, user_msg, cfg)`
- Status line: `· asking {model} via {provider} ({n} note(s) as context)…`
- Catch `CloudError` → stderr + exit 1

### Step 3 — `doctor`: provider key status

```
Cloud providers:
  ✓ claude      ANTHROPIC_API_KEY    set
  · openai      OPENAI_API_KEY       not set
  · gemini      GEMINI_API_KEY       not set
  · groq        GROQ_API_KEY         not set
  · perplexity  PERPLEXITY_API_KEY   not set
  + any user-configured providers in config
```

### Step 4 — `status`: update model line

Current: `model    qwen3:14b local · claude-sonnet-4-6 via --cloud`
New:     `model    qwen3:14b local · {model} via {provider} (--cloud)`

---

## Key invariants (for tests)

- `_call_cloud("unknown", ...)` → raises `CloudError`
- Missing env var → raises `CloudError` (not `KeyError`)
- `"claude"` type → `_post_json` called with Anthropic URL + `x-api-key` header
- `"openai"` type → `_post_json` called with `https://api.openai.com/v1/chat/completions` + `Authorization: Bearer`
- `"openai-compat"` + custom `base_url`/`chat_path` → final URL = `base_url + chat_path`
- Perplexity URL = `https://api.perplexity.ai/chat/completions` (no `/v1/`)
- `"gemini"` type → URL contains `?key=` (key in URL, not header)
- Gemini safety-blocked response (no `content` in candidate) → raises `CloudError`
- User config partial override (only `model`) → keeps `type` + `api_key_env` from built-in default
- `ask --cloud` no flag, no config → defaults to `"claude"`
- `ask --cloud --provider openai` → overrides config default
- `doctor` lists all built-in + user-configured providers; ✓ only for env vars present
- `"gemini"` type → `_post_json` URL contains `?key=` (key in URL, not header)
- User config provider overrides built-in default (same name = user wins)
- `ask --cloud` with no flag, no config → defaults to `"claude"`
- `ask --cloud --provider groq` overrides config default
- `doctor` shows all built-in + user-configured providers; ✓ only for set keys

---

## Files Changed

- `src/kage/cli.py` — `CloudError`, `DEFAULT_PROVIDERS`, `_call_cloud()`, updated `ask` / `doctor` / `status`
- `tests/test_cli.py` — new tests per step
- `docs/cycle-5-pitch.md` — this file

---

## Done When

```
kage ask "what is Layer 3e?" -p kage --cloud --provider openai
kage ask "what is Layer 3e?" -p kage --cloud --provider groq
kage doctor   # shows ✓ for keys present, · for missing
```

Both return grounded answers. Adding a new provider requires only a config block.
