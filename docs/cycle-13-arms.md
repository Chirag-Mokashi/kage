# Cycle 13 — Arms Expansion: Native OS + Open Web (v0.13.0)

*Status: PITCH (cloud-authored plan, Sonnet 4.6, 2026-06-21). Built per the 7-step dev workflow: plan cloud → write local → review cloud → plan tests cloud → write tests local → review tests cloud → run tests local.*

---

## Framing

Two new arms. Both follow the same **ToS-routing principle locked in this cycle:** if a service has a native macOS integration (TCC-gated, zero ToS risk) → use a `shell` arm via osascript. If the target is open web with no login wall → use the `browser` arm via Playwright MCP. This principle replaces ad-hoc per-service decisions with a durable rule.

```
Query ──► ARM_KEYWORDS match
               │
     ┌─────────┴──────────┐
     │                    │
  Native OS arm       Browser arm
  (shell transport)   (browser transport)
  TCC-gated           DuckDuckGo HTML
  Zero ToS risk       Open web only
     │                    │
  osascript / icalbuddy   Playwright MCP
  Calendar ✅ (Cy 11)    @playwright/mcp
  Gmail ← this cycle     ← this cycle
```

**Gmail arm:** Mail.app already has Gmail synced via IMAP + OAuth (Apple's client, Google explicitly supports). osascript reads Mail.app — no browser automation, no ToS concern, same pattern as the calendar arm.

**Browser arm:** Playwright MCP is a `stdio` MCP server maintained by Microsoft. For web research it does two steps: `browser_navigate(url)` → `browser_snapshot()` (accessibility tree, text-efficient). A dedicated `_call_arm_browser` handler wraps these two steps. URL source: if the question contains a URL → navigate directly; otherwise build a DuckDuckGo HTML search URL (`html.duckduckgo.com/html/?q=...`, no login wall, headless-friendly).

---

## What's already in place (no rebuild)

| Thing | State |
|---|---|
| `gmail` registered in `arms.py` line 138 as `shell` | ✅ dormant — only config missing |
| `_call_arm_shell` handles all shell arms | ✅ no change |
| `_connect_arm` else-branch uses `mcp_command`+`mcp_args` via stdio_client | ✅ browser arm reuses this |
| `_TRANSPORT_HANDLERS` is extensible | ✅ add `'browser'` key |
| `urllib.parse` imported in `arms.py` | ✅ used by DDG URL builder |
| Playwright MCP tool names confirmed live: `browser_navigate`, `browser_snapshot` | ✅ verified 2026-06-21 |
| osascript Mail.app access confirmed working from Terminal | ✅ verified 2026-06-21 |

---

## Deliverables

### A. `src/kage/arms.py` — 3 additions

**A1. Add `import re` to the import block** (new import, needed for URL detection in question).

**A2. New `_call_arm_browser` function** — insert after `_call_arm_mcp`, before `_TRANSPORT_HANDLERS`:

```python
async def _call_arm_browser(
    arm_name: str, _arm_cfg: dict, question: str, identity: str, timeout: float,
) -> str | None:
    ts = _dt.datetime.now().astimezone().isoformat(timespec='seconds')
    m = re.search(r'https?://\S+', question)
    url = m.group() if m else (
        'https://html.duckduckgo.com/html/?q=' + urllib.parse.quote_plus(question)
    )
    try:
        async with asyncio.timeout(timeout):
            async with _connect_arm(arm_name) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await session.call_tool('browser_navigate', {'url': url})
                    result = await session.call_tool('browser_snapshot', {})
                    data = _serialize_arm_result(result)
                    _privacy._write_audit({
                        'type': 'arm_call', 'arm': arm_name,
                        'tool': 'browser_navigate+snapshot',
                        'identity': identity, 'ts': ts, 'success': data is not None,
                    })
                    return data
    except Exception:
        _privacy._write_audit({
            'type': 'arm_call', 'arm': arm_name, 'tool': 'browser',
            'identity': identity, 'ts': ts, 'success': False,
        })
        return None
```

**A3. Register browser arm** — add after existing `register_arm` calls (line 138–139):

```python
register_arm(
    'browser',
    ['search', 'browse', 'website', 'article', 'web', 'news',
     'look up', 'find online', 'read about'],
    'browser',
    _call_arm_browser,
)
```

No change to `_select_tool` — browser arm has its own handler that calls tools directly.

---

### B. `~/.kage/mail_arm.scpt` — new file (Chirag installs manually, not in repo)

```applescript
tell application "Mail"
    set unread_msgs to (messages of inbox whose read status is false)
    set result_text to ""
    set msg_count to 0
    repeat with m in unread_msgs
        if msg_count >= 10 then exit repeat
        set result_text to result_text & subject of m & " | " & sender of m & "\n"
        set msg_count to msg_count + 1
    end repeat
    if result_text is "" then
        return "No unread messages."
    end if
    return result_text
end tell
```

Returns: `Subject line | sender@email.com\n` per message, up to 10 unreads. Matches the static-read pattern of the calendar arm (returns current state; parameterized search is a future cycle).

---

### C. `~/.kage/config.json` — user adds 2 blocks inside `"arms": {}`

```json
"gmail": {
  "enabled": true,
  "transport": "shell",
  "command": "osascript /Users/mokashi/.kage/mail_arm.scpt",
  "identity": "personal",
  "permission": "read"
},
"browser": {
  "enabled": true,
  "transport": "browser",
  "mcp_command": "npx",
  "mcp_args": ["@playwright/mcp@latest", "--headless"],
  "identity": "personal",
  "permission": "read"
}
```

`--headless` keeps the browser invisible during arm calls. `npx` downloads `@playwright/mcp` on first run (no global install needed).

---

## Keyword separation (no overlap)

| Arm | Keywords |
|---|---|
| `calendar` | calendar, schedule, meeting, event, appointment, today, tomorrow, this week |
| `gmail` | email, mail, inbox, thread, draft, unread, reply, newsletter, attachment |
| `browser` | search, browse, website, article, web, news, look up, find online, read about |

Zero cross-arm keyword overlap. "Today" stays exclusively on `calendar`; "email" stays exclusively on `gmail`; "search" stays exclusively on `browser`.

---

## Implementation order for Qwen3

Run in this exact order. Each step is a diff, not a full rewrite.

```
Step 1 — arms.py: add `import re` to import block
Step 2 — arms.py: add _call_arm_browser function (after _call_arm_mcp)
Step 3 — arms.py: add register_arm('browser', ...) call (after line 139)
Step 4 — create ~/.kage/mail_arm.scpt (verbatim from §B above)
Step 5 — write tests (see §Test Plan)
```

Steps 1–4 are mechanical; Qwen3 should output diffs only (not full files).

---

## Test Plan (cloud-authored, Qwen3 writes)

All new tests go in `tests/test_cli.py`. Mock pattern: monkeypatch `arms._call_arm_browser` / `arms._call_arm_shell` for unit tests; the arm dispatch path is already covered by existing tests.

| Test | What it checks |
|---|---|
| `test_browser_arm_keywords_detected` | `_detect_arms('search the web for X', 'personal')` returns `['browser']` when browser arm enabled in config |
| `test_browser_arm_ddg_url_built` | When question has no URL, `_call_arm_browser` calls `browser_navigate` with DDG URL containing the question |
| `test_browser_arm_direct_url` | When question contains `https://example.com`, `browser_navigate` is called with that URL directly |
| `test_browser_arm_mcp_failure_returns_none` | When MCP session raises, `_call_arm_browser` returns `None` without propagating exception |
| `test_gmail_arm_keywords_detected` | `_detect_arms('check my inbox', 'personal')` returns `['gmail']` when gmail arm enabled |
| `test_gmail_arm_shell_empty_command_returns_none` | `_call_arm_shell` with empty `command` key returns `None` |

Target: 6 new tests. Running total ~382+ after merge.

---

## What this cycle is NOT

- Not a Gmail search arm (static unread read only; search = future cycle)
- Not a ToS gate bypass for services that require login (browser arm = open web only, DDG by default)
- Not a multi-step interactive browser session (2-step navigate+snapshot only)
- Not a signed Swift helper for TCC (deferred — Terminal context already has Automation permission)

---

## ToS routing rule (locked in this cycle)

> **If a service has a native macOS app that syncs the data you need → `shell` arm (osascript). If the target is open web with no auth wall → `browser` arm (Playwright MCP). Never automate a login-walled web UI.**

Future arms (Contacts, Reminders, Notes) follow the same native-first rule without a new decision each time.
