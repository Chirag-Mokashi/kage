# Layer 8 — Browser Arm: Cosmos connector (basic)

*Design spec. Status: PLAN (cloud-authored), to be built next session per dev workflow (plan → write local → review cloud).*
*Created 2026-06-10. Target: Cosmos. Mode: design now, build next session.*

> **⚠️ UPDATE 2026-06-10 — this browser arm may be UNNECESSARY for Cosmos.**
> Cosmos = **Edison Scientific**, which ships an **official Platform API** (API keys, docs, cookbook: edisonscientific.gitbook.io/edison-cookbook). A sanctioned API connector beats browser automation on every axis — zero ToS/ban risk, no Playwright fragility, clean to build.
> **Decision GATED on one fact:** is Edison's API included in the subscription, or billed separately (double-pay, like Perplexity/Claude APIs)?
> - Included / affordable → build an **Edison API connector**; abandon this browser-arm path for Cosmos.
> - Separately billed → this browser-arm design becomes the jugaad fallback; resume ToS/detection research.
> Chirag to check pricing (platform.edisonscientific.com/profile + /pricing). **Build NOTHING until known.**

---

## Why this exists (the economic driver)

Cosmos has **no public API**, and the API path for the tools that *do* have one (Perplexity, Claude) bills **separately from the subscriptions Chirag already pays for** — using the API double-pays. The browser arm drives the **web UI Chirag's subscription already covers**, at **zero marginal cost**. It also establishes an **adaptable baseline**: once the BrowserConnector exists, adding a new tool = one small adapter (selectors + URL). See [[project-layer8-browser-arm]].

**Cosmos-specific bonus:** Cosmos results are exactly what we've been hand-pasting (the reason `cosmos-research-log.md` is "digested, not verbatim"). Automating this closes that gap.

---

## Goal (basic scope)

`kage browse cosmos "<query>"` → kage drives Cosmos's web UI using a logged-in browser session, waits for the deep-research run to finish, extracts the report, and saves it into kage memory as a note.

## Non-goals (explicitly out for v1)

- No multi-step / agent chaining (kage has no agent loop yet — Chirag invokes the command).
- No login automation — Chirag logs in manually once into a persistent profile; kage never handles credentials/2FA.
- No headless evasion tricks.
- Only Cosmos. Perplexity / others are future adapters behind the same interface.

---

## ⚠️ Risk accepted before build

**Automating the Cosmos web UI may violate its Terms of Service and risk account suspension.** Mitigations baked into the design: persistent *real* browser profile, **headed** by default, human-paced, manual login. This lowers but does not eliminate the risk. Chirag accepts this consciously. (Recorded here so it isn't rediscovered later.)

---

## Architecture

```
  kage browse cosmos "<query>"   (new CLI command)
      │
      ▼
  ToolConnector (interface)        ← the adaptable frame; future API tools plug in here too
      └─ BrowserConnector          (Playwright, persistent Chromium profile)
           └─ CosmosAdapter        (URL + selectors + completion signal — site-specifics)
                navigate → submit → POLL until research complete → extract report
      │
      ▼
  Layer 3e disclosure gate on the OUTBOUND query   (see "Privacy" below)
      │
      ▼
  save result → kage memory note (source=cosmos, project tag, timestamp, query)
```

## Interface (stable — define now, won't change as tools are added)

```python
class ToolConnector(Protocol):
    name: str
    def query(self, prompt: str, *, timeout_s: int) -> "ToolResult": ...

@dataclass
class ToolResult:
    text: str            # extracted report
    source: str          # "cosmos"
    url: str | None      # shareable permalink if Cosmos provides one
    elapsed_s: float
    truncated: bool      # True if timeout cut it short
```

`BrowserConnector` implements `ToolConnector` via Playwright; `CosmosAdapter` holds only the site-specific bits (URL, selectors, completion detection).

## Browser / session model

- Playwright `launch_persistent_context(user_data_dir=~/.kage/browser/cosmos)` → reuses a real logged-in session.
- **First run:** headed browser opens, Chirag logs in manually (SSO etc.); session persists in the profile dir.
- **Later runs:** reuse profile. If session expired → detect logged-out state → prompt headed re-login. Never fail silently.
- **Headed by default** (visible, lower ban risk, debuggable). `--headless` is opt-in later.

## Cosmos flow — the hard part is that it's LONG-RUNNING

Deep research takes **minutes**, not seconds. The connector must:

1. Navigate to Cosmos new-research entry point.
2. Type query into the input, submit.
3. **Poll for completion** — this is the key challenge. Need a reliable "research finished" signal (spinner gone / status text / stable DOM for N seconds).
4. Generous timeout — default **900s (15 min)**, configurable. On timeout: extract whatever exists, mark `truncated=True`.
5. Extract the final report (rendered text/markdown) + permalink if available.
6. Save into kage (`_save` / remember path): text, `source=cosmos`, project tag, original query, timestamp.

## 🔍 Must be discovered empirically on first build-session run (cannot be specced blind)

The implementation **cannot proceed without** capturing these by opening Cosmos with Playwright inspector / devtools (a ~20-min task at the start of the build session):

- [ ] Cosmos base URL + new-research entry point
- [ ] Confirm SSO login works with a persistent profile
- [ ] Query input selector
- [ ] Submit mechanism (button selector vs Enter)
- [ ] **Completion signal** — how do we know research finished? (spinner state / status text / button state)
- [ ] Result container selector
- [ ] Whether a shareable permalink exists
- [ ] Typical completion time (calibrates default timeout)

## Command shape

```
kage browse cosmos "<query>" [--project X] [--save/--no-save] [--timeout 900] [--headed/--headless]
```
Defaults: headed, save=True, timeout=900.

## Failure modes to handle (don't crash cryptically)

- Not logged in → headed re-login prompt.
- Timeout exceeded → save partial, `truncated=True`, tell the user.
- Selector not found (UI changed) → clear error naming which selector failed.
- Bot-detection / captcha → detect, pause, let Chirag solve it in the headed window, then continue.

## Privacy (Layer 3e)

`kage browse` sends the **query** to a cloud service (Cosmos), so the outbound query must pass through the **same Layer 3e disclosure gate as `ask --cloud`** — PII scan, approval, audit. The returned report coming *in* is then saved like any import. **Do not bypass the gate for the browser path.**

## Dependencies & layout

- `playwright` (Python) + `playwright install chromium`.
- New: `src/kage/connectors/browser.py` (BrowserConnector + ToolResult) and `cosmos.py` (CosmosAdapter). Single file acceptable for the basic slice.
- New CLI command `browse` in `cli.py`.

## Testing (honest departure from the 100%-real-coverage norm)

A browser arm **cannot** have the same live coverage as pure logic (auth + cost + flakiness + ToS). Approach:
- **Unit:** mock the Playwright page; test connector logic, save path, failure handling, result parsing against **captured fixture HTML**.
- **Integration smoke:** one manual, CI-skipped test against live Cosmos.
- Flag this explicitly in the cycle so the coverage drop is a known, accepted trade-off — not a regression.

## Roadmap impact (needs confirmation)

This inserts ahead of the previously-planned next cycle (`kage chat`). The Cycle 8–11 order in [[project-mediator-vision]] (chat → MCP client → routing → agent loop) shifts. **Open question for Chirag:** does the browser arm become the next cycle (pushing chat/etc. back one), or slot in elsewhere?

---

*Next session: run the discovery checklist first, then implement against this spec via plan → write → review.*
