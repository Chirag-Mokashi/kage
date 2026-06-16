# Cycle 11 — kage as MCP Client

*Status: PITCH v2 (cold-reviewed, all findings folded in). To be built per the locked
7-step dev workflow: plan cloud → write local (Qwen3) → review cloud → plan tests cloud
→ write tests local → review tests cloud → run tests local. Created 2026-06-16.*

---

## One line

kage reaches out — for the first time it calls external MCP servers, turning passive
forwarder into active mediator. First arms: Google Calendar and Gmail (read-only,
verify-then-unlock model).

## Appetite

One full cycle. Two arms, one OAuth setup, one routing layer, one explicit human
verify gate before write permissions are ever considered.

**This is the keystone** — every arm in the backlog is inert until this exists.

## Version / branch

`v0.11.0` — first minor version bump since v0.10. kage's first outbound call.
Branch: `cycle-11`.

---

## Problem

kage today only receives. A user asks "what's on my calendar?" and kage searches its
own memory — which has nothing about today's real schedule. It cannot reach out to
live data. Every one of the 8 arms in the backlog requires kage to call external MCP
servers, which it currently cannot do. The mediator is passive.

## Solution

Wire the `mcp` library's client side (already a dependency) to call out to external
MCP servers. Add a keyword-based routing layer inside `kage ask` that detects when
a question needs an arm, calls all matching arms, and injects the results as context
before the LLM answers.

```
kage ask "any email about my meeting tomorrow?"
  → _resolve_context()              [already works]
  → _detect_arms(question)          [new — keyword match → ["gmail", "calendar"]]
  → _call_arm("gmail", ...)         [new — MCP client, read-only]
  → _call_arm("calendar", ...)      [new — MCP client, read-only]
  → results injected as ARM DATA
  → LLM synthesizes answer
  → arm calls written to audit log
```

---

## The 10 Characteristics — design check

```
Seamless    → kage ask same command; arm calls invisible to user
Transparent → kage status shows which arms live; audit log records every outbound call
Aware       → kage reads live calendar/inbox data, not just stored memory
Local       → OAuth tokens in ~/.kage/ only; arm data never persisted to kage memory
Silent      → arm calls happen without user steering; kage decides when to invoke
Broker      → THIS cycle makes kage an actual broker: mediates between you and live data
Adoptable   → each arm is a config entry; add/remove without touching code
Controlled  → read-only scope first; EXPLICIT HUMAN VERIFY GATE before write unlocked
Invisible   → user asks naturally; routing, arm calls, context injection all hidden
Modular     → arms independent; Calendar failure never affects Gmail or memory recall
```

**Controlled** is the most load-bearing characteristic. The read-only-then-verify model
is a characteristic requirement, not just caution.

---

## Critical fixes from cold review (all folded in)

### Fix 1 — Transport architecture: Google's official MCPs are remote SSE

`@google/mcp-server-calendar` and `@google/mcp-server-gmail` do NOT exist on npm.
Google's official Calendar and Gmail MCPs are **remote MCP servers** (Streamable HTTP at
`calendarmcp.googleapis.com/mcp/v1` and `gmailmcp.googleapis.com/mcp/v1`) — not local
stdio processes.

**Developer Preview gate (discovered 2026-06-16):** These endpoints are gated behind the
Google Workspace Developer Preview Program. Before calls work, the GCP project must be:
1. Enrolled at `developers.google.com/workspace/preview` (manual review, ~2 days)
2. MCP service APIs enabled: `calendarmcp.googleapis.com` + `gmailmcp.googleapis.com`
   (via GCP Console → APIs & Services → Enable APIs, or `gcloud services enable`)

Until enrolled, all calls return 404 regardless of token validity.

`_call_arm` must support two transports:

```
stdio  →  local process via StdioServerParameters (Playwright, Filesystem, etc.)
sse    →  remote HTTP/SSE via sse_client (Google Calendar, Gmail, etc.)
```

Config schema gains a `transport` field:

```json
{
  "arms": {
    "calendar": {
      "enabled": true,
      "transport": "sse",
      "mcp_url": "https://calendarmcp.googleapis.com/mcp/v1",
      "identity": "personal",
      "permission": "read"
    },
    "gmail": {
      "enabled": true,
      "transport": "sse",
      "mcp_url": "https://gmailmcp.googleapis.com/mcp/v1",
      "identity": "personal",
      "permission": "read"
    }
  },
  "google_oauth": {
    "client_id": "...",
    "client_secret": "...",
    "refresh_token": "..."
  }
}
```

Future stdio arms (Playwright, Filesystem):

```json
"browser": {
  "enabled": false,
  "transport": "stdio",
  "mcp_command": "npx",
  "mcp_args": ["@playwright/mcp"],
  "identity": "personal",
  "permission": "read"
}
```

### Fix 2 — Async/sync bridge: specified explicitly

`_call_arm` is `async`. Callers are currently sync. Two solutions, one per surface:

- **CLI (`kage ask`)**: wrap with `asyncio.run(_arm_flow(...))` — safe because Typer
  commands run outside any event loop.
- **MCP tool (`kage_ask`)**: make it `async def kage_ask(...)` — FastMCP natively
  supports async tool functions. This is the correct fix; `asyncio.run` inside a
  running anyio loop raises `RuntimeError`.

### Fix 3 — `session.initialize()` required before `call_tool`

`ClientSession.__aenter__` starts the receive loop but does NOT call `initialize()`.
Protocol error results without it. Canonical `_call_arm` skeleton:

```python
async with _connect_arm(arm_name) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()          # ← required
        tools = await session.list_tools()  # discover tool names
        tool_name, params = _select_tool(arm_name, question, tools.tools)
        result = await session.call_tool(tool_name, params)
        return _serialize_arm_result(result)
```

---

## Full architecture (post cold-review)

### `_connect_arm` — dual-transport context manager

```python
from contextlib import asynccontextmanager
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp import StdioServerParameters

@asynccontextmanager
async def _connect_arm(arm_name: str):
    arm = _config()["arms"][arm_name]
    if arm["transport"] == "sse":
        token = await _get_google_token()   # refresh → access token
        async with sse_client(
            url=arm["mcp_url"],
            headers={"Authorization": f"Bearer {token}"},
        ) as streams:
            yield streams
    else:
        server_params = StdioServerParameters(
            command=arm["mcp_command"],
            args=arm["mcp_args"],
        )
        async with stdio_client(server_params) as streams:
            yield streams
```

### `_call_arm` — with tool discovery and result serialization

```python
_arm_tool_cache: dict[str, list] = {}   # module-level, warm across calls in a session

async def _call_arm(arm_name: str, question: str, timeout: float = 30.0) -> str | None:
    """Call an arm. Returns serialized text or None on any failure."""
    try:
        async with asyncio.timeout(timeout):
            async with _connect_arm(arm_name) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    if arm_name not in _arm_tool_cache:
                        tools = await session.list_tools()
                        _arm_tool_cache[arm_name] = tools.tools
                    tool_name, params = _select_tool(
                        arm_name, question, _arm_tool_cache[arm_name]
                    )
                    result = await session.call_tool(tool_name, params)
                    return _serialize_arm_result(result)
    except Exception:
        return None   # graceful fallback — never propagates
```

**Timeout is 30s** (not 5s) to cover npx cold starts for future stdio arms and
network latency for SSE arms.

### `_serialize_arm_result` — ContentBlock → string

```python
from mcp.types import CallToolResult

def _serialize_arm_result(result: CallToolResult) -> str | None:
    if result.isError:
        return None
    texts = [block.text for block in result.content if hasattr(block, "text")]
    return "\n".join(texts) if texts else None
```

### `_detect_arms` — all matching arms, in config order

```python
ARM_KEYWORDS = {
    "calendar": ["calendar", "schedule", "meeting", "event",
                 "appointment", "today", "tomorrow", "this week"],
    "gmail":    ["email", "mail", "inbox", "thread", "draft",
                 "unread", "reply", "newsletter", "attachment"],
    # "from" and "subject" removed — too broad, false-positive on common English
}

def _detect_arms(question: str, identity: str) -> list[str]:
    """Return list of enabled, identity-matching arm names whose keywords hit."""
    arms = _config().get("arms", {})
    q = question.lower()
    return [
        name for name, arm in arms.items()
        if arm.get("enabled")
        and isinstance(arm.get("identity"), str)   # guard against None
        and arm["identity"] == identity
        and arm.get("permission") == "read"        # write gate: never call write arms
        and any(kw in q for kw in ARM_KEYWORDS.get(name, []))
    ]
```

**All matching arms fire in sequence** (not first-match-only). A question matching
both calendar and gmail calls both; results concatenated into ARM DATA context.

### Updated system prompt in `kage ask`

Current prompt says "Answer ONLY from the user's saved notes." This is wrong when arm
data is present. Updated structure:

```
You are kage, a personal context broker.

MEMORY (user's saved notes):
{memory_context}

ARM DATA (live data from connected services):
{arm_context}

Answer using MEMORY and ARM DATA. Clearly distinguish:
- facts from saved notes (cite "from your notes")
- live data from a connected service (cite "from your calendar" / "from your email")
If neither contains the answer, say so explicitly.
```

When no arms fire, `arm_context` is empty and the section is omitted. Existing
behavior for memory-only answers is unchanged.

### OAuth credential shape — Google OAuth 2.0

Google OAuth produces short-lived access tokens (1h) and long-lived refresh tokens.
Config stores the refresh token; `_get_google_token()` exchanges it for a fresh
access token before each arm call:

```python
async def _get_google_token() -> str:
    cfg = _config()["google_oauth"]
    # POST to token endpoint with refresh_token grant
    # returns access_token (valid 1h)
    ...
```

The one-time human setup flow:
```
1. Google Cloud Console → create OAuth client ID + secret (type: Desktop app)
2. Run: kage arm auth    (new command — triggers browser consent flow)
3. Paste authorization code → kage exchanges for tokens → stores in config.json
4. Done. Refresh is automatic from here.
```

### Audit log — arm calls recorded

Every arm call appended to the existing audit trail:

```python
_write_audit({
    "type": "arm_call",
    "arm": arm_name,
    "tool": tool_name,
    "identity": identity,
    "ts": datetime.utcnow().isoformat(),
    "success": result is not None,
})
```

Outbound calls to Google's servers are now visible in the audit log. (Transparent)

### `kage doctor` arm check — specified

```python
async def _check_arm_health(arm_name: str) -> bool:
    try:
        async with asyncio.timeout(10.0):
            async with _connect_arm(arm_name) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.list_tools()   # proves connectivity + auth
        return True
    except Exception:
        return False
```

Missing credentials → connect fails → `kage doctor` prints:
`  ✗ calendar — missing google_oauth credentials (run: kage arm auth)`

---

## Permission model — verify gate (Controlled)

Cycle 11 ships **read-only OAuth scopes only**:

```
Calendar:  https://www.googleapis.com/auth/calendar.readonly
Gmail:     https://www.googleapis.com/auth/gmail.readonly
```

Write scopes **not requested, not stored, not in scope**:

```
Calendar write:  https://www.googleapis.com/auth/calendar.events    ← NOT cycle 11
Gmail compose:   https://www.googleapis.com/auth/gmail.compose      ← NOT cycle 11
```

**The verify gate is explicit:**
After Cycle 11 ships, Chirag uses the arms in real daily use and confirms:
- Calendar and Gmail return correct, timely, correctly-scoped data
- Identity wall holds (personal arm not called in neu context)
- No unexpected behavior, no data leakage

Only after explicit sign-off does write scope get added. That is a separate cycle
(Cycle 11.5 or folded into 12), not a config flag flip done quietly.

---

## Hard contracts (correctness — never skip)

1. **Identity wall.** `arm["identity"] == resolved_identity` (both validated as
   non-empty strings at config load) checked in `_detect_arms` before any arm call.
2. **Permission wall.** `arm["permission"] == "read"` checked in `_detect_arms`.
   Even if OAuth token had write scope, no write tool is ever called in Cycle 11.
3. **Arm failure never breaks `kage ask`.** `_call_arm` returns `None` on any
   exception or timeout. Caller falls back to memory-only answer silently.
4. **`enabled: false` = arm is dead.** Checked first in `_detect_arms`.
5. **OAuth credentials never in source.** Stored in `~/.kage/config.json`
   (gitignored). `kage doctor` hints if missing.
6. **`session.initialize()` before every `call_tool`.** No exceptions.
7. **`kage_ask` MCP tool is `async def`.** Never wraps async in `asyncio.run`
   inside FastMCP's event loop.

---

## Surface

```
kage ask "what's on my calendar today?"      → Calendar arm (read)
kage ask "any unread email from my advisor?" → Gmail arm (read)
kage ask "email about my meeting tomorrow?"  → Gmail + Calendar arms (both fire)
kage ask "what is activation energy?"        → no arm, memory only

kage arm auth                                → one-time OAuth consent flow
kage status                                  → arms: calendar [read ✓]  gmail [read ✓]
kage doctor                                  → reachability + auth check per arm
```

---

## Implementation order (7-step gate applies to each step)

1. **Dual-transport `_connect_arm`** — `sse` and `stdio` branches; `_get_google_token`
   refresh flow; credentials read from config.
2. **`_call_arm`** — `session.initialize()`, `list_tools()`, `_select_tool()`,
   `_serialize_arm_result()`, 30s timeout, graceful `None` on any failure.
3. **`_detect_arms`** — keyword table (without "from"/"subject"), all matching arms,
   identity + permission wall, `enabled` gate.
4. **Wire into `kage ask` (CLI)** — `asyncio.run(_arm_flow(...))` wraps async path;
   ARM DATA section in context; updated system prompt.
5. **Wire into `kage_ask` (MCP tool)** — make `async def`; same arm flow; Odysseus
   and Antigravity benefit automatically.
6. **`kage arm auth`** — browser consent flow, token exchange, writes to config.
7. **`kage status` arms section** — enabled arms, transport type, permission level.
8. **`kage doctor` arm health check** — `_check_arm_health` per arm; missing-creds
   hint; MCP server unreachable message.
9. **Audit log** — `_write_audit` on every arm call (arm, tool, identity, success, ts).
10. **Tests** — mocked SSE arm response; `_detect_arms` wall test (personal arm not
    called in neu context); failure fallback (arm returns None → memory-only answer);
    `_serialize_arm_result` with TextContent, empty content, `isError: True`.

---

## Out of scope (deliberately deferred)

- **Write permissions** — gated behind verify (Controlled). Separate cycle.
- **NEU Outlook** — IMAP + XOAUTH2 path noted in arms backlog. Slots into
  `neu` identity arm config when ready — no core code change needed.
- **Consequence-aware router** — Cycle 12 replaces the keyword heuristic.
- **n8n / Activepieces wiring** — after MCP client pattern is stable.
- **All other 6 backlog arms** — become config entries once pattern proven.
- **iOS Share Sheet pipeline** — separate track.

---

## NEU Outlook — research summary (backlog, not Cycle 11)

Three viable paths when ready, ranked:

1. **IMAP + XOAUTH2** using Microsoft's trusted client ID
   (`d3590ed6-52b3-4102-aeff-aad2292ab01c`) — may bypass NEU admin consent wall.
   Test: clone UvA-FNWI/M365-IMAP and run `get_token.py` with NEU account. If
   "Admin approval required" → path blocked, move to path 2.
2. **Playwright** driving Outlook Web — jugaad path, zero OAuth infrastructure,
   drives the web UI already logged in. MFA handled via saved session state.
3. **Graph API** via personal Azure app registration — likely blocked by NEU's
   tenant consent policy; test empirically before investing.

EWS dead (Oct 2026). Canvas has no email API. When this lands: add `neu` identity
arm entry in config → identity wall routes it automatically → no core changes.

---

## Decisions locked for this cycle

- First arms: Google Calendar + Gmail (official remote Streamable HTTP MCPs, shared OAuth)
- Endpoints: `calendarmcp.googleapis.com/mcp/v1`, `gmailmcp.googleapis.com/mcp/v1`
- **Live test blocked** until GCP project enrolled in Google Workspace Developer Preview
- Transport: `sse` for Google arms; `stdio` for future community arms
- Permission model: read-only; `"write"` permission rejected in `_detect_arms`
- Verify gate: explicit human sign-off required before write scope is ever added
- Multi-arm routing: all matching enabled arms fire in sequence (not first-match)
- Keywords: `"from"` and `"subject"` removed from gmail list (false-positive risk)
- Timeout: 30s (covers npx cold start and SSE network latency)
- Tool discovery: `session.list_tools()` on first call, cached for session lifetime
- Async bridge: `asyncio.run()` in CLI; `async def` in MCP tool
- OAuth credential shape: refresh token in config; `_get_google_token()` exchanges it
- Audit: every arm call (arm, tool, identity, success) written to audit log

---

*Cold review complete (v2). Next step: Chirag approves → Qwen3 writes code per Step 1.*
