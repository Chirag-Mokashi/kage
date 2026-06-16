# kage — Arms Backlog & Verified Tool Decisions

*Status: PLANNING / BACKLOG. Not a cycle. These are "soon or later" implementation
notes — refinements to the arms inventory after web-verification and competitive
comparison-shopping (2026-06-15). Source brainstorm: `Context/kage-mobile-brainstorm-2026-06-15.md`.*

*Nothing here is scheduled into a cycle yet. When kage-as-MCP-client (Cycle 11) and
auto-routing (Cycle 12) land, pull the relevant rows from here into those pitches.*

---

## How to read this

Every item below was web-verified (mid-2026) and comparison-shopped against current
alternatives. "Pick" = what to actually use when the time comes. "Why" = the one-line
reason it beat the doc's original candidate.

---

## Decisions LOCKED (no change now)

### Local Executor model — keep Qwen3 14B
- **Laguna XS.2 is OUT.** It is a 33B/3B MoE; "3B active" means SPEED, not memory —
  all 33B weights must be resident (~36GB at Q4). It does NOT fit the 24GB M5 Pro.
  Expert-offloading to disk exists but is too slow for long-context agentic work.
- Devstral Small 2 (24B, ~14-15GB Q4, 68% SWE-bench, Apache 2.0) *does* fit and is a
  real coding upgrade — but it's OPTIONAL, not urgent. In kage's dev-workflow gate the
  cloud reviews all local output, so a better local coder only reduces correction load.
  A/B-test someday; do not change now.

### Cloud Executor — none. Use the Claude subscription you already pay for.
- Two different "executors": (1) dev-workflow — Claude plans/reviews, local Qwen writes;
  (2) router-executor — a FUTURE consequence-aware router that sends high-volume,
  low-stakes tasks to a cheap cloud so they don't burn Claude quota.
- (2) only earns its place at the autonomous agent-loop stage (Cycle 13). Until then:
  no paid DeepSeek/Kimi. If/when needed: **DeepSeek V4-Pro** ($0.435/$0.87, 80.6%
  SWE-bench Verified) for quality, **Qwen3-Coder 480B `:free`** on OpenRouter for $0.
  Drop Kimi K2.7 Code (most expensive output, no independent SWE-bench).

---

## Arms inventory (8) — verified picks

| # | Arm | Original candidate | Verified pick | Why |
|---|-----|--------------------|---------------|-----|
| 1 | Communication | Gmail / Calendar / Notion MCP | Same | No competitor — these are *the* providers. Real gate = kage-as-MCP-client (Cycle 11). |
| 2 | Browser | Playwright MCP | **Playwright CLI** (not MCP server) + Browser MCP later | CLI = same engine, 4-10x fewer tokens. Browser MCP later for auth'd/anti-bot sites (drives your real logged-in Chrome). Skip Skyvern (AGPL), Browserbase/Stagehand (cloud+paid). |
| 3 | Automation backbone | n8n | **Activepieces** (n8n = safe fallback) | True MIT vs n8n fair-code; deepest bidirectional MCP; lightest footprint. Watch Windmill for code-first/Python authoring if it ever adds MCP-client. |
| 4 | iOS Share Sheet -> kage | Shortcuts + webhook | Same | A mechanism, not a tool choice. |
| 5 | Web Search | Perplexity / Tavily | **Brave Search MCP** (default) + **Linkup** (citations) | Brave: 2k free/mo, independent index, privacy-first. Linkup: 91% SimpleQA, local install. Tavily now Nebius-owned (forward risk). |
| 6 | Files + Code | Filesystem MCP, GitHub MCP | Same (official servers) | Low priority — kage already owns ~/.kage; git driven via Claude Code today. Matters at autonomous-loop stage. |
| 7 | macOS Intelligence | Apple Foundation Models (`fm`) | **Thin Swift sidecar** (deferred) | See below. |
| 8 | MCP Directory | aiagentslist / glama / mcp.so | Same | A discovery resource. Rule: check the directory before building any arm. |

---

## Supporting tools (from the GitHub-repos section)

| Tool | Role | Verified pick | Why |
|------|------|---------------|-----|
| Context7 | Docs-injection MCP (current library docs into the agent) | Keep + add **GitMCP** as free fallback | Context7 cut its free tier ~92% (Jan 2026, ~1k req/mo). Still fine for personal use; GitMCP (free, zero-key, public repos) covers the no-cost path. |
| planning-with-files | Persistent markdown agent state (Manus-style) | Reference for Librarian skill-file design | STATE.md 5-section structure ~= what kage's Librarian should do. |
| Context7 / Ref / DeepWiki | (alternatives noted) | — | Ref = highest fidelity (private repos); on radar only. |

---

## Arm 7 — Apple Foundation Models via Swift sidecar (deferred, gated)

**Decision: viable, deferred. Cosmos NOT needed — device (M5 Pro) is confirmed capable;
research is sufficient.**

- Apple Foundation Models is a **Swift framework** (`LanguageModel` protocol,
  `LanguageModelSession`). There is **no first-party Python SDK** — this is the gap.
- **Do NOT rewrite kage in Swift.** Correct architecture = a thin Swift sidecar
  (~50-100 lines): a tiny compiled binary that takes a prompt on stdin, runs one
  `LanguageModelSession` call, prints the answer to stdout.
- kage shells out to it exactly like it shells out to `ollama`. Apple `fm` becomes
  "just another provider" in kage's existing provider config — zero core changes.
  Even cleaner: wrap the sidecar as a mini MCP server.
- **Costs to accept:** (1) a `swift build` step — kage gains a non-Python, macOS-only
  artifact (stops being pure-Python on this path); (2) OS gate — Foundation Models
  framework (macOS 26+; provider-swapping features macOS 27 / ~Sept 2026); (3) the
  on-device model is free + private + zero API cost — that's the whole appeal.

---

## Net change vs the original brainstorm doc

| Component | Doc's pick | Backlog pick |
|-----------|-----------|--------------|
| Browser | Playwright MCP | Playwright **CLI** + Browser MCP later |
| Local model | Laguna XS.2 (OUT) | **Keep Qwen3 14B** |
| Cloud executor | Kimi K2.7 Code | **None now**; DeepSeek V4-Pro / Qwen3-Coder free later |
| Automation | n8n | **Activepieces** (n8n fallback) |
| Docs MCP | Context7 | Context7 **+ GitMCP** fallback |
| Search MCP | Perplexity / Tavily | **Brave** + Linkup |
| Apple `fm` | "Python SDK" (does not exist) | **Swift sidecar**, deferred |

---

*Created 2026-06-15. Pull rows into Cycle 11 / 12 pitches as those cycles are shaped.*
