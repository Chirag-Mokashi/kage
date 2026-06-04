# kage test — seed corpus

> **Status:** Living capture doc (Stage 0). This is kage's test STRATEGY (genres below) + SEED cases for the
> local-vs-cloud benchmark (#98). The harness that *runs* them is Stage 1;
> for now this is a low-friction place to accumulate cases as they occur to you.
> Grow toward a ~1000-case corpus (post-v0); at that scale kage reads this file
> directly, which also exercises its file-access path (echoing markdown-memory #70).
>
> *Last updated: 2026-06-04 (Session 14).* Companion: [blueprint.md](blueprint.md) (#98)

---

## What this measures

One question per task class: **"is local (Qwen3-14B) good enough for this class, or
does it need cloud?"** — answered with data, so graduation thresholds (#68) come from
measurement, not guesses. Per case: run the SAME input through kage's internal pipeline
on LOCAL (Qwen3/Ollama) and CLOUD (e.g. Claude); score per the case's `judge`.

**Metrics (v1):** quality (the headline) · privacy (% stayed local). Latency + cost
are cheap to add later (both models already run per case).

## Test genres (machinery vs quality)

Two different questions → two kinds of test. Don't conflate them:

- **Quality benchmark** (the cases at the bottom): *"how GOOD are the outputs?"* — graded, directional (#98).
- **Machinery tests**: *"does the system WORK correctly?"* — pass/fail. Three sub-kinds:
  - **Smoke** — one real request flows end-to-end through every stage; ✓ per stage (liveness).
  - **Invariant** — privacy/partition guarantees that must ALWAYS hold (never graded, never "mostly").
  - **Integration** — components work together (routing/switching, MCP connectivity).

### Smoke test (pre-run liveness)
A single synthetic query pushed through the WHOLE pipeline — store → retrieve (3c) →
assemble (3d) → disclose (3e) → route/dispatch (4) → respond — printing ✓ as it clears
each stage and flagging where it stalls. (Smoke through pipes: if it comes out the far
end, the path is clear.) Distinct from `kage doctor` (#97): doctor checks each component
is REACHABLE/healthy (static); smoke checks a real request FLOWS through them (dynamic).
Run before benchmarks and on startup.

### Invariant tests (must ALWAYS pass — these guard the moat)
- **Identity wall (#19):** assert no memory tagged identity A is EVER returned under active
  identity B. Inviolable — one leak = hard failure, not a low score.
- **Project scoping (#19):** scoped memories return only on project match; baseline spills
  correctly; pending never returns.
- **Disclosure (3e):** nothing local-only / no redacted span ever leaves to the wrong vendor;
  per-vendor budget respected; fail-closed.
> These are the highest-priority tests in the suite — they protect privacy, the actual moat.

### Integration / capability tests
- **Model/vendor switching (Layer 4 + 3e):** a query that uses MULTIPLE models/vendors in one
  flow (local → escalate to cloud; or research→Perplexity then reason→Claude). Assert: switch
  fires per policy + context SURVIVES the switch + 3e re-checks disclosure per new vendor
  (#64 Design-B re-run). Tests switching AND context management together.
- **Identity switching:** flip active identity (`/identity`) mid-session; assert the right
  partition is active and the wall holds.
- **Project switching:** flip active project (`/project`); assert correct scoping + baseline spillover.
- **MCP connectivity:** for EACH connected MCP server (in/out) — connect, list tools, call one,
  assert response + measure speed/control/capability. **Auto-runs on registration** — when a new
  MCP server is added, kage runs this test automatically (parameterized over connected servers).
  v1 has few; the suite grows with them. (Odysseus is one such MCP client of kage.)

## Tooling — reuse existing, don't build the harness (researched Session 14)

Map each genre to an existing tool rather than hand-rolling. All Stage-1 wiring; the
Stage-0 win is knowing not to reinvent + that our seed cases are already portable.

| Genre | Tool (reuse) | Why |
|---|---|---|
| Quality benchmark | **promptfoo** (OSS) | YAML cases ≈ this doc's schema; runs every provider (Ollama local + Claude/etc.) as columns = compare-many-at-once; 3 assertion tiers map to our judges (deterministic→`accuracy`, llm-rubric/LLM-judge→`shadow-agreement`/`blend`, custom Python→invariants). **Wrap kage's own pipeline as a promptfoo custom provider** to test the whole flow, not just raw models. |
| Retrieval quality (3c) | **RAGAS** | context precision / recall / faithfulness without ground-truth labels — grades whether retrieval surfaced the right memories. |
| Invariant + integration | **DeepEval** (PyTest-style) or promptfoo custom-Python asserts | identity-wall / disclosure / switching are pass/fail assertion logic → unit-test style, CI-gated. |
| MCP connectivity + smoke | **MCP Inspector** (`--cli`: tools/list, tools/call) | official, scriptable into CI; auto-run per connected server. Claude Code can also ad-hoc smoke-test a server in NL. |
| Generic model capability | **lm-evaluation-harness** (a Claude skill exists) | 60+ standard tasks — "how good is Qwen3 broadly," separate from personal-context cases. |

Ready-made skills exist (smoke-test agent/Claude skills; glebis/claude-skills collection); this
Claude Code env already ships `verify` / `code-review` / `security-review` (Stage-1 dev-time).
Principle: adopt promptfoo + MCP Inspector + RAGAS; don't build a bespoke harness (#38 reuse).

## Case schema

```yaml
- id: <class>-NNN
  class: chat | code | reasoning | research | multimodal | system-ctrl   # the 6 router classes (#62)
  prompt: "<the user input>"
  context: ["<optional memory to inject — also tests retrieval 3b/3c>"]
  judge: accuracy | shadow-agreement | blend | reference                 # see below
  reference: "<gold answer OR a RUBRIC; null for pure shadow-agreement>"
  why: "<what this case probes>"
```

**Judge types (grading is DIRECTIONAL, never exact-match for open-ended classes):**
- `accuracy` — factual correctness against known details (clean when the right answer is checkable).
- `shadow-agreement` — cloud output is the yardstick; is local equivalent?
- `blend` — automated (rubric / shadow-agreement) on every case + human spot-check a sample.
- `reference` — gold answer, exact/rubric match (only for truly closed cases).

**Authoring guidance:** aim for a spread within each class (easy → hard) so the
*distribution* sets the threshold, not one case. Keep `reference` as a **rubric** for
open-ended cases.

---

## chat — daily-activity accuracy (time / place / tool aware; judged on facts, not tone)

```yaml
- id: chat-001          # easy — time-filter retrieval
  class: chat
  prompt: "What's on my calendar this afternoon?"
  context: ["Calendar (today): 11:00 advisor @ISEC; 15:00 gym; 18:00 call mom."]
  judge: accuracy
  reference: "Afternoon (12:00+): 15:00 gym, 18:00 call mom."
  why: "Time awareness + accurate retrieval. Local should handle → graduation candidate. Personal → 100% local."

- id: chat-002          # medium — place filter
  class: chat
  prompt: "I'm heading to campus — which of today's items are there?"
  context: ["11:00 advisor @ISEC; 15:00 gym (downtown); 18:00 call mom (home).", "ISEC = NEU campus."]
  judge: accuracy
  reference: "On campus: only the 11:00 advisor @ISEC."
  why: "Place awareness + filtering against injected context."

- id: chat-003          # hard — capability honesty + correct suggestion
  class: chat
  prompt: "Move my gym to after the advisor meeting."
  context: ["11:00 advisor; 15:00 gym.", "kage v1 READS calendar; editing events is v1.5."]
  judge: accuracy
  reference: "Should say it can't move events yet (read-only in v1) AND suggest a slot after 11:00."
  why: "Tool/capability awareness + honesty (Honesty principle). Accuracy includes knowing its own limits."
```

## reasoning — comprehension + valid reasoned options (judged by rubric + human)

```yaml
- id: reasoning-001     # medium — extract requirements, give options
  class: reasoning
  prompt: "Given the below, what are my options and which would you pick — why?"
  context: ["24GB MacBook; run a 14B model locally + keep indexes in RAM.", "Privacy first, then speed; cost N/A.", "I quit when setup is fiddly."]
  judge: blend
  reference: "RUBRIC: surfaces 24GB ceiling + privacy-first + low-friction; >=2 options w/ tradeoffs; pick tied to THOSE reqs."
  why: "Comprehension (pull real requirements from messy context) + reasoned recommendation."

- id: reasoning-002     # medium — sequencing under priorities
  class: reasoning
  prompt: "How should I sequence this week?"
  context: ["Thesis draft due Fri (hard).", "Two assignments due Thu.", "I work best mornings.", "I procrastinate on big tasks."]
  judge: blend
  reference: "RUBRIC: weighs Fri-hard + Thu-assignments + morning energy + procrastination; front-loads/decomposes thesis; justified by those facts."
  why: "Plan from competing constraints; recommendation must be tied to the stated facts."

- id: reasoning-003     # hard — competing tradeoffs, recommend
  class: reasoning
  prompt: "Given the below, what are my options and which do you pick?"
  context: ["Want a daily briefing feature.", "Privacy-first — no raw data leaving.", "Limited build time.", "Reuse over reinvent."]
  judge: blend
  reference: "RUBRIC: names privacy + time + reuse constraints; >=2 build approaches w/ tradeoffs; pick tied to constraints."
  why: "Identify constraints + weigh tradeoffs + justify a pick — the decision-support behavior."
```

---

## Backlog (post-v0)
- [ ] Grow each class toward ~1000 cases (the real benchmark scale).
- [ ] Add the remaining classes: code, research, (multimodal/system-ctrl as relevant).
- [ ] Add latency + cost metrics to each run.
- [ ] Wire the harness (Stage 1) to read this file, run local+cloud, and seed the #68 reputation table.
- [ ] Author the INVARIANT suite first (identity wall · project scoping · disclosure) — highest priority; must-pass.
- [ ] Author integration tests: model/vendor switching + context preservation; identity/project switching.
- [ ] Wire the SMOKE test (run pre-benchmark + on startup; ✓ per pipeline stage).
- [ ] MCP integration tests parameterized over connected servers; auto-run on registration.
- [ ] (Chirag adds more genres/cases as he learns the system — this doc is living.)
