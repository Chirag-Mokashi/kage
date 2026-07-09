# Cycle 29.1 — Num-Ctx Truncation Hotfix (v0.29.1)

*Status: EXECUTED, not yet committed. Authored + built 2026-07-07 via the 7-step gate:
cloud planned + reviewed, local (Qwen3 via `kage ask`) wrote code + tests, local ran them.
All 6 real generation sites fixed (re-enumerated in review, not trusted from this doc's
original table); librarian.py investigated and confirmed structurally unreachable, no
change needed. 791/791 tests passing (775 baseline + 16 new). Live-probe verified against
the real local Ollama server: `prompt_eval_count` was hard-capped at 4095 before the fix,
now exceeds the full sent prompt size. One correction-log entry recorded — local hit a
quality wall on free-form test-authoring (weak assertions → wrong CliRunner kwarg → full
hallucination on a bundled correction request → a timeout), fully recovered once dispatches
were split into single, minimal, isolated asks.*
*Scope: hotfix-sized. One branch, one PR. Independent of (and prerequisite to) the 3a cycle.*

---

## Problem — empirically confirmed on this machine, 2026-07-07

kage never passes `num_ctx` to Ollama, so every local call runs at the **server default
4096** — not Qwen3 14B's native **40,960** (verified via `ollama show qwen3:14b`; no
Modelfile param, no `OLLAMA_CONTEXT_LENGTH` env).

**Live probe:** a ~6,400-token prompt to `/api/chat` returned `prompt_eval_count: 4095`.
Ollama **silently truncated** — no error, no warning to the caller.

**Why this is biting today:** `session.py` budgets **4,000 tokens for chat history
alone** (`token_budget=4000`), before adding the system prompt, up to 5 retrieved
notes, and the question. `kage chat` in longer sessions is near-certainly dropping
prompt content silently. Scout Pass 1 (fetched corpora) and Monitor observe (a day of
JSONL) are also high-risk overflow payloads.

## Site enumeration (INVARIANT ENUMERATION RULE — grep output, not memory; reviewer MUST re-run)

`grep -rnE "11434|ollama_url|/api/chat|/api/generate|LiteLlm\(" src/kage/*.py`

**Generation sites (need num_ctx):**
| # | Site | Path | Payload risk |
|---|------|------|-------------|
| 1 | `cli.py:422` | `/api/chat` — `kage chat` local | CONFIRMED truncating (history budget 4000 + system + context) |
| 2 | `cli.py:1175` | `/api/generate` — `kage ask` local | 5 retrieved notes + learned rules + question |
| 3 | `mcp_server.py:249` | `/api/generate` — MCP `kage_ask` local | same shape as #2 |
| 4 | `scout.py` (`_litellm_target` + ScoutBroad `LiteLlm(model="ollama_chat/...")`) | ADK/LiteLLM | fetched corpora — HIGH overflow risk |
| 5 | `monitor.py:556` + `monitor.py:595` | ADK/LiteLLM `ollama_chat/` | full day of AX JSONL — HIGH |
| 6 | `librarian.py:870-880` | ADK/LiteLLM (provider-dependent; local distill possible) | staged content batches |

**Out of scope (different mechanism, note only):** `/api/embed` (`embed.py:18`,
`cli.py:477`) — embedding models have separate truncation semantics; `/api/tags`
health checks (no prompt).

## Design

### D1 — Config key, one source of truth
- New config key `ollama_num_ctx`, **default 16384**, read via `cfg.get("ollama_num_ctx", 16384)`.
- Why 16384: KV cache for Qwen3-14B ≈ 0.16 MB/token f16 → ~2.6 GB at 16k on top of
  ~10 GB Q4 weights — comfortable on 24 GB. 32k (~5.2 GB) works but slows prompt eval;
  user-overridable in `~/.kage/config.json`. (128k recipe — FLASH_ATTENTION + Q8_0 KV —
  exists in project memory; explicitly NOT this hotfix.)
- Executor: verify the exact KV numbers empirically after the change (`ollama ps` shows
  memory while a 16k-context request is loaded) — the 0.16 MB/tok figure is an estimate,
  not gospel.

### D2 — Direct HTTP sites (#1, #2, #3): add options to payload
Each payload gains: `"options": {"num_ctx": cfg.get("ollama_num_ctx", 16384)}`.
Three-line change per site. No other payload fields touched.

### D3 — LiteLLM/ADK sites (#4, #5, #6): verify passthrough, then apply or defer
LiteLLM's ollama provider forwards provider-specific options, but the exact mechanism
through ADK's `LiteLlm` wrapper (extra kwargs vs `extra_body`) must be **verified
empirically first** (check litellm docs/source for `ollama_chat` optional params; then
confirm via one live call that `prompt_eval_count` can exceed 4096). If trivial → apply
in this hotfix. If not trivial → **defer agent sites to a follow-up slice with a loud
TODO + doctor warning**, don't balloon the hotfix. Decision recorded in the PR either way.

### D4 — Runtime truncation tripwire (the detection that was missing)
Ollama's response already returns `prompt_eval_count`. On the main local paths (#1, #2):
estimate sent tokens with the existing len/4 heuristic (`session.py`); if
`prompt_eval_count >= num_ctx - 8` (window filled) AND estimate exceeds num_ctx →
`typer.echo("[kage] ⚠ prompt filled the context window — output may be missing context", err=True)`
+ an audit-log entry. ponytail: heuristic tripwire, not exact accounting; ceiling is
the len/4 estimator; upgrade path is a real tokenizer count.

### D5 — `kage doctor` check
New check "local context window":
- read `ollama_num_ctx` (default 16384);
- fetch model native context via `/api/show` (`context_length`); fail if config > native;
- warn if `session token_budget (4000) + 2000 (system+context headroom) > 0.75 × num_ctx`.
Static + one cheap API call; no live generation probe in doctor (too slow).

### D6 — What does NOT change
`token_budget=4000` stays (now fits comfortably in 16k). No num_predict changes.
No cloud-path changes. No embed changes.

## Execution — 7-step mapping (HARD GATE)

1. PLAN (cloud) — this document.
2. WRITE code (local Qwen3 via `kage ask`, diffs not rewrites, per Ollama prompt-size memory) — D1+D2 first, then D4, then D5; D3 verification is executor-driven (small live probe), its code local-written.
3. REVIEW code (cloud) — **re-run the enumeration grep** and check every generation site is covered or explicitly deferred.
4. PLAN tests (cloud): payload carries num_ctx (all 3 direct sites, mock `_post_json`, assert `options.num_ctx`); default 16384 + config override honored; tripwire fires when `prompt_eval_count` hits cap and stays silent otherwise; doctor check passes/warns/fails on the three conditions. REAL-SCHEMA RULE n/a (no SQL).
5. WRITE tests (local).
6. REVIEW tests (cloud).
7. RUN (local): `uv run pytest -q` full suite + one manual live probe re-run showing `prompt_eval_count > 4096` on the same ~6,400-token prompt.

**Mistake log** after each step (`kage remember --project kage-corrections`).
Cold review: mechanical change → cloud-inline review suffices, BUT the reviewer must
independently re-run the site grep (enumeration rule) and diff against this doc's table.

## Verification (definition of done)
- Live probe: same 6,400-token prompt → `prompt_eval_count` ≈ 6,400 (not 4,095).
- Full suite green; CI green on PR.
- `kage doctor` shows the new check ✓ on this machine.
- `kage chat` long-session smoke: no tripwire warning under normal use.

## Risks & rollback
- **RAM/latency regression** at 16k KV: mitigated by config override (`ollama_num_ctx: 8192`
  one-line rollback); verify with `ollama ps` during smoke.
- **LiteLLM passthrough unknown**: bounded by D3's verify-or-defer rule.
- **Ollama behavior drift** (0.30.8 today): tripwire is heuristic; doctor pins
  config-vs-native, not server default (which stays invisible — that's WHY we set it
  explicitly per request).

## Relation to 3a
Independent hotfix, but its outputs are 3a inputs: the config key + doctor check +
tripwire become the budget floor the 3a warm tier is designed against (warm tier
≤ ~5% of the quality window; see 3a brainstorm).
