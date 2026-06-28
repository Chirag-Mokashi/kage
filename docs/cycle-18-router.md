# Cycle 18 — Multi-Vendor Router (v0.19.0)

*Status: PITCH v3 (2026-06-28, cloud-authored). 2 cold reviews complete (5+3 BLOCKERs + 4+4 WARNs resolved across both passes). BUILD READY.*
*Built per the 7-step dev workflow: plan cloud → write local (Qwen3) → review cloud → plan tests cloud → write tests local → review tests cloud → run tests local.*

---

## North star

> kage classifies queries by task type and routes them to the best-available
> model automatically. `kage ask --auto` is the trigger. v1 uses keyword matching;
> Layer 6 replaces it with learned routing later. No new CLI surface beyond `--auto`.

---

## What this cycle is NOT

- Not a UI / conversation change (ask stays ask)
- Not Layer 6 (learned routing, reputation tables, feedback loops) — deferred
- Not automatic 7-step dev workflow execution — routing picks the right model for a single dispatch; the 7-step is a human-level process
- Not multimodal file ingestion — `kage ask` has no `--file` arg today; see §Multimodal below
- Not Perplexity research (no API key) — Gemini with Search Grounding is the research backend for v1
- Not `kage chat` REPL routing — `--auto` on `ask` only; chat gets it in a later cycle

---

## Scope — four additive steps (must be applied in order)

```
  A  src/kage/router.py     NEW   _classify(), _candidates(), _ROUTING_TABLE
  B  src/kage/cloud.py      EDIT  shell-llm dispatch + registry + api_key_env fix + gemini search_grounding
  D  ~/.kage/config.json    EDIT  claude-opus, claude-sonnet, gemini-research provider entries
  C  src/kage/cli.py        EDIT  --auto flag + wiring into ask + fallback chain
```

**Order is load-bearing.** Step C references providers by name (e.g., `"claude-opus"`).
If D is not applied first, `CloudClient.complete()` raises `CloudError("Unknown provider")` on
the very first `--auto` dispatch and the fallback chain crashes before it starts.

---

## Step A — `src/kage/router.py`

### Classification (v1 — keyword-first)

`_classify(question: str) -> str` checks keywords in priority order and returns one
of the five class names below. Order matters — a question matching multiple classes
takes the first match.

```
  Priority  Class        Trigger keywords (case-insensitive, substring match)
  ────────  ───────────  ──────────────────────────────────────────────────────
  1         code         compile · debug · refactor · implement · write a function ·
                         write a script · write a class · fix the bug · fix this error ·
                         traceback · syntax error · unit test · pytest · def · class
  2         research     search for · look up · latest news · current news · recent · find online ·
                         up to date · as of today · breaking news
                         [NOT "what is" / "who is" — too generic, routes trivial questions
                          to live web search; those stay in reasoning or chat]
  3         multimodal   image · photo · picture · video · audio · screenshot · diagram ·
                         chart · .jpg · .png · .gif · .mp4 · .pdf · describe this ·
                         what do you see
  4         reasoning    analyze · compare · explain why · think through · pros and cons ·
                         trade-off · should I · what would happen if · step by step ·
                         design · architect · review · evaluate · is this correct
  5         chat         (default — no keyword matched; stays local; --auto has no effect)
```

**system-ctrl is NOT classified here.** It is already handled by `_detect_arms()` in
`cli.py` (Cycle 11). Arms fire first; the router never sees system-ctrl queries.

**chat class with --auto:** classification returns `"chat"` → `_candidates()` returns
`[]` → `ask` stays local. `--auto` has no effect on short casual queries.

**Multimodal v1 limitation:** the multimodal class is classified correctly, but `kage ask`
has no `--file` argument. A multimodal-classified query routes to `gemini-3-5-flash` and
gets answered from text notes only (no image). The CLI prints a one-line notice:
`"[kage] Multimodal route: no attachment provided — answering from notes only."`
This is transparent rather than silent.

```
ponytail: multimodal detection is keyword-only (no attachment); upgrade = --file arg
```

### Routing table

`_candidates(task_class: str, cfg: dict) -> list[str]` returns provider names in
fallback order. The caller tries each in sequence.

```python
# ponytail: v1 hardcoded; Layer 6 makes this a learned lookup table
_ROUTING_TABLE: dict[str, list[str]] = {
    "code":       ["claude-opus", "gemini-3-1-pro", "gemini-3-5-flash"],
    "reasoning":  ["claude-opus", "gemini-3-1-pro", "openrouter-general"],
    "research":   ["gemini-research"],  # no fallback — warn user on failure (see §Step C)
    "multimodal": ["gemini-3-5-flash", "gemini"],
    "chat":       [],  # local only
}
```

`_candidates()` reads `cfg.get("routing_table", {})` first, merging over the defaults.
User-supplied rows in `~/.kage/config.json` **replace** (not extend) the default row.
Unknown class names in user-supplied `routing_table` are silently valid — they extend
the routing table with custom classes. This is intentional extensibility.
```
ponytail: custom routing_table keys accepted silently; upgrade = validation + warning
```

```json
"routing_table": {
  "reasoning": ["gemini-3-1-pro", "openrouter-general"]
}
```

The function returns the merged list as-is. Unknown `task_class` → returns `[]` → local.

---

## Step B — `src/kage/cloud.py` changes

### B0 — Fix `api_key_env` KeyError (line 106)

Current code (line 106):
```python
key = os.environ.get(pcfg["api_key_env"], "")
```

`shell-llm` providers have no `api_key_env` key → `KeyError` BEFORE dispatch, OUTSIDE the
`except` block at line 115 → uncaught crash.

Fix (line 106 — exact replacement):
```python
api_key_env = pcfg.get("api_key_env", "")
key = os.environ.get(api_key_env, "") if api_key_env else ""
```

Then update the guard (currently line 107–108):
```python
if not key and api_key_env:
    raise CloudError(f"{api_key_env} not set (provider: {provider_name})")
```

`shell-llm` providers: `api_key_env` absent → `key = ""` → no error → dispatch called with `key=""` (unused).

### B1 — `shell-llm` provider type

Claude is accessed via the Claude CLI subscription (no `ANTHROPIC_API_KEY`).
The dispatch runs `claude --print --model {model} "{prompt}"` as a subprocess.

Config shape (no `api_key_env`):
```json
"claude-opus": {
  "type": "shell-llm",
  "command": "claude",
  "model": "claude-opus-4-8"
}
```

`_dispatch_shell_llm(pcfg, key, system, messages)` — exact spec:

```python
def _dispatch_shell_llm(pcfg, key, system, messages):
    cmd = pcfg["command"]          # "claude"
    model = pcfg.get("model", "")
    # single-shot: use only the last user message (v1 — multi-turn history is not serialised)
    # ponytail: history dropped; upgrade = serialise earlier turns as text prefix
    prompt = system + "\n\n" + messages[-1]["content"]
    try:
        result = subprocess.run(
            [cmd, "--print", "--model", model, prompt],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as exc:
        # OSError covers FileNotFoundError (binary not on PATH) and PermissionError
        raise CloudError(f"shell-llm '{cmd}' failed: {exc}") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise CloudError(
            f"shell-llm '{cmd}' exited {result.returncode}: {result.stderr[:200]}"
        )
    return result.stdout.strip()
```

**`subprocess` import:** add `import subprocess` to `cloud.py`.

**Exact subprocess arg list:** `[cmd, "--print", "--model", model, prompt]`
- `--print` is the boolean flag (enables non-interactive output mode)
- `--model model` is the model flag + value
- `prompt` is the positional argument (the question text)
- This is the long form of `-p`; use `--print` for clarity to avoid parser ambiguity

**Pre-build verification (open item):** Confirm `claude --print --model claude-opus-4-8 "hello"` works
in terminal BEFORE writing Step B code. If the model flag or arg order is wrong, Step B tests will
catch it; but save time by verifying manually first.

**Registry call** (must be added at module level, after the function definition):
```python
register_provider_type("shell-llm", _dispatch_shell_llm)
```

Without this, `_PROVIDER_REGISTRY.get("shell-llm")` returns `None` →
`CloudError("Unknown provider type 'shell-llm'")` on first run.

### B2 — Gemini Search Grounding

`_dispatch_gemini` adds `"tools": [{"google_search": {}}]` when `pcfg.get("search_grounding")` is True.

```python
body = {
    "systemInstruction": {"parts": [{"text": system}]},
    "contents": contents,
}
if pcfg.get("search_grounding"):
    body["tools"] = [{"google_search": {}}]
```

Config entry (added in Step D):
```json
"gemini-research": {
  "type": "gemini",
  "api_key_env": "GEMINI_API_KEY",
  "model": "gemini-2.5-flash",
  "search_grounding": true
}
```

**Pre-build verification (open item):** Confirm `gemini-2.5-flash` with `google_search` tool via
`kage ask --cloud --provider gemini-research "latest AI news today"` before wiring Step C.

---

## Step D — `~/.kage/config.json` additions

`gemini-3-1-pro` and `gemini-3-5-flash` are ALREADY in the live config (added Cycle 13).
Step D only adds the three NEW providers (applied BEFORE Step C):

```json
"claude-opus": {
  "type": "shell-llm",
  "command": "claude",
  "model": "claude-opus-4-8"
},
"claude-sonnet": {
  "type": "shell-llm",
  "command": "claude",
  "model": "claude-sonnet-4-6"
},
"gemini-research": {
  "type": "gemini",
  "api_key_env": "GEMINI_API_KEY",
  "model": "gemini-2.5-flash",
  "search_grounding": true
}
```

**Model ID pre-build checks (must do before implementing Step C):**
- `gemini-3-1-pro` → verify `gemini-3.1-pro-preview` is the correct model name via live API
- `gemini-3-5-flash` → verify `gemini-3.5-flash` is the correct model name via live API
- `claude-opus-4-8` → verify via `claude --print --model claude-opus-4-8 "hello"`
- If any ID is wrong, update the `_ROUTING_TABLE` in router.py and/or the config accordingly

---

## Step C — `cli.py` changes (ask command)

### New flag

```python
auto: bool = typer.Option(False, "--auto", help="Classify query and auto-route to best model.")
```

`--auto` and `--provider` / `--cloud` are **mutually exclusive**. Add early-exit guard:
```python
if auto and (cloud or provider):
    typer.echo("[kage] --auto is mutually exclusive with --cloud / --provider.", err=True)
    raise typer.Exit(code=1)
```

### Dispatch flow with `--auto`

The 3e disclosure gate in `ask()` is ~70 lines of inline control flow (lines 959–1031) —
it is NOT a standalone callable. The correct structure for `--auto` is:

```
BEFORE the for-loop (once):
  1. classify question → task_class
  2. candidates = _candidates(task_class, cfg)
  3. if not candidates:
       fall through to local Ollama path unchanged
  4. provider_name = candidates[0]          # first candidate only, for gate
  5. RUN THE GATE INLINE (lines 959–1031, as today but with provider_name = candidates[0])
     - if gate blocks ALL notes → set cloud=False, fall to local (existing logic applies)
     - if user denies → set cloud=False, fall to local (existing logic applies)
     - if gate passes (allowed_rows computed) → continue to for-loop
     - gate approval is cached in _session_approvals[provider_name]

AFTER the gate (for-loop):
  6. for provider_name in candidates:
       a. if task_class == "multimodal":
            typer.echo("[kage] Multimodal route: no attachment provided — answering from notes only.")
       b. try:
            answer = _call_cloud(provider_name, system, user_msg, cfg)
            # write audit log for this dispatch (including fallback providers)
            _write_audit({..., "provider": provider_name, "outcome": "dispatched"})
            break   # success
       c. except CloudError as e:
            if provider_name is last candidate:
                if task_class == "research":
                    typer.echo("[kage] Web search unavailable. Answering from notes only.")
                set cloud=False, fall to local
            else:
                # on first CloudError (candidates[0] failed), pre-approve remaining providers
                # so the gate doesn't re-prompt for the same disclosure decision this query
                # ponytail: pre-approval applies only to this query's for-loop run, but
                # _session_approvals persists to subsequent queries in the same session;
                # this means a user who approved claude-opus is silently pre-approved for
                # gemini-3-1-pro next query too. Upgrade = cache approval per-query, not per-session.
                for p in candidates:
                    _session_approvals[p] = True
                typer.echo(f"[kage] {provider_name} failed, trying fallback…")
                continue

  NOTE: The for-loop REPLACES the existing `if cloud: ... except CloudError` block at
  lines 1082–1098 of cli.py entirely. Do NOT add the for-loop alongside the existing
  block — that causes duplicate cloud dispatch. Qwen3 must delete lines 1082–1098 and
  insert the for-loop in their place.
```

**Research warning gate:** the "Web search unavailable" warning only prints when
all candidates are exhausted due to `CloudError`. If the gate blocks all notes,
the gate's own message prints ("All retrieved context is local-only") — the research
warning must NOT also print.

### Existing paths unchanged

- `kage ask question` (no flags) → local, unchanged
- `kage ask --cloud question` → `cfg.get("cloud_provider")`, unchanged
- `kage ask --cloud --provider X question` → explicit provider, unchanged
- `kage ask --auto question` → NEW path above

---

## Layer 3e × Layer 4 contract (v1 — simplified Decision #64)

Full Design B (ranked-list filter, per-candidate policy) is the target.
v1 simplification:

```
  3e gate runs ONCE, keyed to candidates[0].
  All other candidates in the fallback chain are pre-approved after gate passes.
  Reason: same notes, same identity/project, same PII; all current providers
  are external cloud (same trust boundary).
  Per-candidate policy (account-specific privacy rules) deferred to v2.
  ponytail: gate runs once; per-candidate policy = Decision #64 Design B v2
```

---

## Implementation steps (7-step gate, one gate per step)

```
  Step 1: router.py — _classify() + _candidates() + _ROUTING_TABLE + config merge
  Step 2: cloud.py  — B0 (api_key_env fix) + B1 (shell-llm) + B2 (search_grounding)
  Step 3: config    — add claude-opus, claude-sonnet, gemini-research (verify IDs first)
  Step 4: cli.py   — --auto flag + mutual exclusion + gate-once + for-loop + warnings
```

Each step: cloud plans spec → Qwen3 writes code → cloud reviews → cloud plans tests →
Qwen3 writes tests → cloud reviews tests → Chirag runs tests.

---

## Test plan

```
  router.py (unit — pure Python, no cloud calls):
    - _classify: one positive test per class keyword
    - _classify: default-to-chat when no keywords match
    - _classify: priority order (code+research keyword in same question → code wins)
    - _classify: empty string → "chat"
    - _classify: "what is" does NOT trigger research class
    - _candidates: returns correct list per class
    - _candidates: config override replaces (not extends) default row
    - _candidates: unknown class → []
    - _candidates: "chat" → []

  cloud.py (unit — subprocess mocked):
    - shell-llm success path: returncode=0, stdout="answer" → returns "answer"
    - shell-llm non-zero returncode → CloudError
    - shell-llm empty stdout → CloudError
    - shell-llm subprocess.TimeoutExpired → CloudError (not propagated raw)
    - shell-llm subprocess.SubprocessError → CloudError
    - api_key_env absent (shell-llm) → no CloudError raised in complete()
    - api_key_env present but env var missing → CloudError (existing behavior)
    - gemini search_grounding=True → "tools" key in POST body
    - gemini search_grounding=False → no "tools" key in POST body
    - shell-llm registered in _PROVIDER_REGISTRY (call complete() with type=shell-llm)

  cli.py ask --auto (integration — cloud mocked via runtime.cloud):
    - --auto + code keyword → routes to claude-opus
    - --auto + research keyword → routes to gemini-research
    - --auto + multimodal keyword → routes to gemini-3-5-flash + notice printed
    - --auto + no keyword (chat) → local Ollama (no cloud call)
    - --auto + code, primary raises CloudError → tries gemini-3-1-pro
    - --auto + code, all candidates raise CloudError → local fallback, no crash
    - --auto + research, gemini-research raises CloudError → local fallback + warning shown
    - --auto + all blocked by gate → local (gate message shown, NOT research warning)
    - --auto + --provider → exit code 1, error message shown
    - --auto + --cloud → exit code 1, error message shown
    - _session_approvals set for all candidates after gate passes for candidates[0]
    - existing --cloud path: unchanged (no --auto)
    - existing --cloud --provider path: unchanged (no --auto)
    - gemini-research absent from config entirely → CloudError caught by for-loop → local fallback + research warning shown
```

---

## Open items / known ceilings

```
  PRE-BUILD (do these before writing any code):
  [ ] Verify: claude --print --model claude-opus-4-8 "hello" works in terminal
  [ ] Verify: gemini-3.1-pro-preview is the correct Gemini API model ID
  [ ] Verify: gemini-3.5-flash is the correct Gemini API model ID
  [ ] Verify: gemini-2.5-flash + google_search tool via live API call

  PONYTAIL CEILINGS (upgrade paths documented, not built):
  ponytail: multimodal detection is keyword-only (no attachment); upgrade = --file arg
  ponytail: classification is keyword-first, no ML; upgrade = embedding classifier (Layer 6)
  ponytail: routing table is hardcoded; upgrade = config-driven + Layer 6 reputation table
  ponytail: 3e gate runs once per query (candidates[0]); upgrade = per-candidate policy (Decision #64 v2)
  ponytail: shell-llm is single-shot (last message only); upgrade = serialize history for multi-turn

  DEFERRED:
  [ ] kage chat REPL --auto routing (next cycle after Cycle 18)
  [ ] kage status --verbose routing table display
  [ ] Reinstate Fable 5 in routing table when export-control suspension lifts (~2026-07-01 US)
  [ ] Add Perplexity as research primary when API key available
```

---

*v2 — awaiting second cold review*
