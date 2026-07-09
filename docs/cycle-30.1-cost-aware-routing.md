# Cycle 30.1 — Cost/complexity-aware routing (Layer 4)

*Status: SHIPPED. Executed via the 7-step gate on 2026-07-08; 808/808 tests passing (777 pre-existing + 31 new/updated).*
*Discipline: 7-step dev-workflow gate. Local (Qwen3) wrote all code/tests; cloud reviewed.*
*Date: 2026-07-08*
*Series: first of the 30.x mini-cycles (30.1 routing → 30.2 inbound injection guardrail → 30.3 inter-agent schema).*

> **SHIPPED changelog:** implemented exactly as locked in v3 (Option B, local-triage call). `_local_eligible` added to `router.py`; `_triage_simple` + the pinned short-circuit + reworded transparency line + down-route audit added to `cli.py`. 3 existing tests fixed (would otherwise have made real, unmocked network calls to Ollama via the new triage call — caught during test planning, before any test ran). 17 new tests added (5 `_local_eligible`, 8 `_triage_simple`, 4 ask()-level integration including the two never-called proofs for research/multimodal). One cold-review-style catch during test review: Qwen3 padded its output with one unrequested duplicate test, dropped per ponytail. Logged to `kage-corrections`.
>
> **v2 changelog (2 cold reviews, both REVISE, core sound):** two consumer sites enumerated (A); control flow pinned to short-circuit (A); egress-direction safety independently confirmed by both; transparency copy softened (B); fail-closed config + down-route audit (B); YAGNI scope line + extra ceiling.

---

## Problem (the real gap, with code refs)

`kage ask --auto` routes purely on **task class**. In [`router.py`](../src/kage/router.py): `_classify()` → class; `_candidates()` → provider list. In [`cli.py` ask()](../src/kage/cli.py#L996-L1003) the only local-vs-cloud lever under `--auto` is whether the class has candidates:

```python
if auto:
    candidates = _candidates(task_class, cfg)
    if candidates:
        cloud = True
        provider = candidates[0]
```

So `chat` → local; **everything else → premium cloud, regardless of triviality.** "What does `def` mean?" and "refactor this module" both hit `claude-opus`. That burns paid tokens on questions local Qwen3 answers fine — the waste **jugaad** + the **okiro** toggle exist to prevent.

**Scope honesty (YAGNI):** affects only the opt-in `--auto` path. Plain `kage ask` is *already* local and free. 0.1/30.1 sharpens `--auto` = "route smartly **and** don't spend cloud on trivia." Changes no default.

## What we're adding

A **local-triage call** that lets a low-complexity query stay **local** even when its class would route to cloud. Divergence from NexusGate is deliberate: they down-route to *cheaper cloud*; **kage down-routes to free *local*** (Local-first + free beats cheap — both reviewers confirmed this is right for kage).

### Mechanism (§Decision RESOLVED — Option B)

A tiny fast local Qwen3 call rates the query's difficulty and decides:

- **Prompt:** minimal, e.g. `"Rate this question's difficulty 1-5 (1=trivial/factual, 5=deep multi-step reasoning). Reply with only the digit.\n\nQ: <question>"`, `think:false`, small `num_predict`.
- **Parse:** first digit in the reply; `<= cfg.auto_triage_max_simple` (default **2**) → simple → down-route local.
- Reuses `_post_json` + `ollama_url`/`model` already in [cli.py](../src/kage/cli.py#L1188). No new dependency.

### Two refinements that shrink the Seamless cost (v3)

1. **Scoped to eligible classes only.** The triage call fires **only for `code`/`reasoning`** — the capability whitelist short-circuits first, so `research`/`multimodal`/`chat` never trigger it. The latency tax the reviewer flagged is therefore **not on every `--auto` query**, only code/reasoning ones.
2. **Short timeout + fail-closed (informed by this session's Ollama-hang learning, 2026-07-07).** We logged that Ollama can hang indefinitely with no client timeout firing. So the triage call gets a **short timeout (~15s)** and on timeout/error/unparseable-reply → treat as **NOT simple → route cloud** (today's behavior). A hung Ollama must never hang `ask()`. This is a direct reuse of a mistake-log entry as a design input.

### Capability edge (whitelist — verified sound by both reviews)

`research` needs live web, `multimodal` needs vision — local can't. Eligibility is a **whitelist**, pure and testable:

```
code       → eligible (triage decides local vs cloud)
reasoning  → eligible (triage decides)
chat       → already local (empty candidates, never reaches triage)
research   → NEVER local
multimodal → NEVER local
```

### Integration point — pinned control flow (cold review A must-fix)

The check must **short-circuit** the assignment. The `and` also ensures the triage call only fires when eligible:

```python
candidates = _candidates(task_class, cfg)
if candidates and not (_local_eligible(task_class) and _triage_simple(question, cfg)):
    cloud = True
    provider = candidates[0]
```

- `_local_eligible(task_class)` — **pure** (router.py): True for `code`/`reasoning` only.
- `_triage_simple(question, cfg)` — the local call (cli.py, has `_post_json`+cfg); fail-closed, short timeout. Only invoked when eligible (short-circuit).

### Transparency — reworded (cold review B: Awareness over control)

Non-assertive, with a real override hint (never claim the query *is* simple):

`[kage] Answering locally to conserve cloud — re-run with --cloud if the answer falls short.`

Override is real: `--auto` is mutually exclusive with `--cloud`/`--provider` ([L997](../src/kage/cli.py#L997)); `kage ask --cloud "…"` bypasses the whole gate. No new flag.

### Down-route audit (cold review B)

On a down-route, write a one-line audit record (`outcome: "auto_downrouted_local"`, the difficulty digit) so the awareness story is inspectable.

## Egress-direction safety (both reviewers traced & CONFIRMED)

The gate only moves a query **cloud→local** (suppresses the `cloud=True` assignment), never the reverse. Down-routed queries fall to `if not cloud:` ([L1186](../src/kage/cli.py#L1186)) — local Ollama, **zero egress** — so skipping the 3e gate and `two_pass_gate` is correct. **No path sends more to cloud than today, or bypasses a gate on a cloud dispatch.** All risk is answer-quality, not privacy. (Note: the triage call itself sends the *question* only to **local** Ollama, never cloud — no new egress.)

## Files / seams — corrected enumeration (cold review A)

- `src/kage/router.py` — add `_local_eligible(task_class)` (pure whitelist).
- `src/kage/cli.py` — add `_triage_simple(question, cfg)` (local call, fail-closed, short timeout); the pinned short-circuit inside `if auto:` (~[L1000](../src/kage/cli.py#L1000)); transparency echo; down-route audit.
- config — `auto_triage_max_simple` (default 2) + triage timeout, documented, fail-closed.
- `tests/test_cli.py` + router tests.

**Consumer-site enumeration (TWO sites):**
1. `cli.py:1000-1003` — the assignment the gate short-circuits.
2. `cli.py:1154` — `if auto and candidates:` fallback fan-out. Reads the `candidates` **variable**, so `grep _candidates` misses it. **Cold review must re-run `grep -n "candidates" src/kage/cli.py`.** L1154 is safe on the down-route because it lives under `if cloud:` ([L1152](../src/kage/cli.py#L1152)); documented so it isn't silently broken later.

Agents (monitor/librarian/scout) call cloud with a fixed provider, not via `_candidates` — **out of scope**.

## Known ceilings (ponytail)

- The triage rating is a judgment; edge cases will mis-rate. Fail-closed means a mis-rate toward "hard" just costs a cloud call (= today); a mis-rate toward "simple" is bounded to code/reasoning where local is at least capable.
- `_classify` matches `"def "` for `code` first ([router.py:6](../src/kage/router.py#L6)); "look up the latest def of X" misclassifies as `code`. Pre-existing; the triage call would then run on a research query and could down-route it to local (which can't web-search). Acknowledged, not fixed here.

## Test plan (local writes in step 5 — must inject a fake triage response, no real Ollama)

- `_local_eligible`: True for `code`/`reasoning`; False for `research`/`multimodal`/`chat`.
- `_triage_simple` with **injected** Ollama reply "1" → True; "5" → False; timeout/error/garbage → False (fail-closed).
- ask()-level: eligible + injected "1" → no cloud dispatch, prints reworded line, writes down-route audit; `research` with injected "1" → **still cloud** (never reaches triage); triage timeout → cloud, no crash/hang.

## Out of scope (leave the seam)

- Agent-internal routing (monitor/scout/librarian).
- Arm-synthesis routing.
- Layer-6-learned difficulty thresholds.
