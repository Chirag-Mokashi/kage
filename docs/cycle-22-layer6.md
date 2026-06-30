# Cycle 22 — Layer 6: kage learn (v0.22.0)

*Status: PITCH v3 (2 cold reviews)*
*Date: 2026-06-30*

> **v3 changelog (cold review #2 — subagent):**
> BLOCKER 4 — `_search_fts` call in Monitor is invalid: `project=` is positional and
>              `limit` is required. Fixed: Monitor uses `_count_total_corrections()` in
>              learn.py — a direct SQLite COUNT query, no _search_fts import.
> BLOCKER 5 — Wrong function name: `_write_state` does not exist. Fixed: corrected to
>              `_write_state_json`. Also: no `_read_state()` exists in monitor.py.
>              Fixed: learn state stored in separate `~/.kage/learn_state.json` managed
>              by learn.py helpers — never touches monitor's state file.
> BLOCKER 6 — `_write_state_json` overwrites entire file; learn counter would be lost on
>              next Monitor run. Fixed by the learn_state.json separation above.
> MINOR 4   — `kage learn --all` empty-class behavior unspecified. Fixed: skip classes
>              where run_learning_pass returns empty prompt.
> MINOR 5   — `provider_name` for call_cloud_fn unspecified. Fixed: use default provider
>              from cfg (same resolution as `kage ask --cloud`).
> NOTE 3    — `kage learn --accept` with no pending file. Fixed: print helpful error.
>
> **v2 changelog (cold review #1 — subagent):**
> BLOCKER 1 — `task_class` defaults to `"chat"` on non-auto local path. Fixed: Step 2 now
>              specifies `_classify(question)` runs unconditionally in ask command, not only
>              when `--auto`. candidates list still only populated when `--auto` is True.
> BLOCKER 2 — `_count_corrections_by_class()` unimplementable — corrections have no class
>              tag. Fixed: Monitor trigger uses TOTAL correction count; per-class split happens
>              inside `run_learning_pass` (cloud keyword-hint filtering). Step 4 rewritten.
> BLOCKER 3 — Blueprint Decision #44 violated — no CoT/trace stored. Fixed: schema now
>              includes `trace` (full cloud analysis output) and `source_note_ids`.
> MINOR 1   — `run_learning_pass` `_search_fts` identity unspecified. Fixed: uses `"personal"`.
> MINOR 2   — `pending_learned.json` overwritten by `--all`. Fixed: keyed by class.
> MINOR 3   — Correction log egress to cloud not acknowledged. Fixed: explicit note added.
> NOTE 1    — `_call_cloud` defined in cli.py → circular import from learn.py. Fixed:
>              `run_learning_pass` accepts `call_cloud_fn` as parameter.
> NOTE 2    — Cold review described as programmatic. Clarified: human-in-the-loop step.

---

## What and why

kage runs a 7-step dev workflow where every cloud correction of Qwen3's output is logged to
the `kage-corrections` project. 81 notes have accumulated. They are read by humans, admired,
and never fed back into the model.

Layer 6 closes that loop. The correction logs are the highest-quality signal available about
Qwen3's failure modes — human-expert-verified, real-task-derived, already structured. A cloud
model can read them, identify the recurring patterns, and write a set of explicit rules to
prepend to Qwen3's system prompt. The next time Qwen3 runs a code task, it has those rules.
If it keeps making mistakes, corrections accumulate, the next learning pass rewrites the rules
with more signal, and the prompt gets more specific.

This is Layer 6 v1: **prompt-only learning, no weight updates, no fine-tuning.**

Blueprint Decision #39 (LoRA rejected) is explicitly upheld. The approach maps to the
"context exemplars + editable rules" pattern validated by Cursor/Cognee/EMG-RAG in production.

---

## Design decisions (brainstorm 2026-06-30, all locked)

### Input

- **Single source of truth:** `kage-corrections` project only. No implicit signal streams.
- **Format unchanged:** existing correction log format (`"Correction log — <feature> Step N
  (date): Local made X errors: … Pattern: …"`). No transformation needed for analysis.
- **Seam open (A1.5):** auto-capture of implicit signals (re-asks, edits) into correction log
  format is deferred. The format IS the stable interface for future input variations
  (visual, audio, etc.).

### What gets improved

- **v1 scope: prompt only.** Routing and retrieval are downstream improvements; they amplify a
  better base prompt but are not substitutes for it. Fixing prompt quality first gives a clean
  experimental baseline before extending to other dimensions.

### Analysis pattern

- **ProTeGi pattern.** Cloud reads the full corrections batch for a task class, identifies
  recurring error patterns, and rewrites the system prompt for that class as a set of concrete
  rules. Each learning pass produces a fresh prompt for the class — not an append, a rewrite.
  Frequent mistakes generate more specific rules; rare mistakes get consolidated or absorbed.

- **Meta-prompt for the cloud analysis step:**

  ```
  Here are all corrections logged for [task_class] tasks in kage's dev workflow.
  Each entry describes a mistake the local model (Qwen3 14B) made and the pattern
  behind it. Read all entries carefully.

  Write a concise set of rules (max 8 bullet points) that, if prepended to the
  local model's system prompt, would prevent these mistakes from recurring.
  Be specific — name the exact API, method, column, or pattern involved.
  No vague advice. No general "be careful" rules.
  Output ONLY the rules as a bulleted list. No preamble, no explanation.
  ```

  After cloud returns the generated prompt, a **cold review pass** checks:
  - do the rules address the top recurring patterns in the corrections?
  - are any rules too broad (would break correct behavior)?
  - is anything missing that the corrections clearly show?

  Cold review output feeds back into the meta-prompt if significant gaps are found.

### Trigger (C1)

- **Dual trigger:** manual `kage learn [--class X|--all]` AND automatic N-threshold.
- **N = 7** new corrections TOTAL triggers a learning pass. Monitor watches the total
  kage-corrections count (not per-class — corrections carry no class tag). When the total
  count delta since the last learn run reaches 7, Monitor fires `kage learn --all`.
  Per-class splitting happens inside `run_learning_pass` via keyword-hint filtering on the
  correction text — not at the trigger layer.
- **Monitor owns the automation.** Same pattern as launchd calling `kage monitor observe`.
- **No per-query injection (C2).** Query time stays lean. The learning pass pre-computes the
  improved prompt; query time just uses the stored result.

### Stored artifact (D1, D2, D3)

Single dedicated file: `~/.kage/learned_prompts.json`

```json
{
  "code": {
    "active": "v2",
    "versions": {
      "v1": {
        "date": "2026-06-30",
        "correction_count": 10,
        "source_note_ids": ["20260612T141220-80e6b5", "..."],
        "prompt": "- Never invent function signatures...",
        "trace": "<full cloud analysis output including reasoning>"
      },
      "v2": {
        "date": "2026-07-15",
        "correction_count": 25,
        "source_note_ids": ["...", "..."],
        "prompt": "- Never invent function signatures...",
        "trace": "<full cloud analysis output including reasoning>"
      }
    }
  },
  "reasoning": {
    "active": "v1",
    "versions": {
      "v1": {
        "date": "2026-07-01",
        "correction_count": 8,
        "source_note_ids": ["..."],
        "prompt": "...",
        "trace": "..."
      }
    }
  }
}
```

`prompt` = the extracted bulleted rules — injected at query time (compact).
`trace` = full cloud output including reasoning — stored for audit and future RAG use.
`source_note_ids` = the correction note IDs that fed this version — required by Blueprint
Decision #44 ("if kage stores teacher responses as retrievable exemplars, MUST preserve
full reasoning trace, not just final answer"). The `trace` field satisfies #44.

- **All 5 task classes in scope:** code / research / multimodal / reasoning / chat.
  Most signal is currently in `code`; other classes start with no active prompt and
  accumulate naturally as more non-code corrections are logged.
- **Per-class granularity.** Each class learns at its own pace. A threshold crossing in
  `code` does not rerun `reasoning`.
- **Rollback:** change `"active": "v2"` → `"v1"` — one line edit. All versions kept.
- **Same pattern as `~/.kage/sensitive.json`** — dedicated system file outside
  `~/.kage/memory/`, machine-readable, human-editable.

### Injection (E1, E2)

- **Local Ollama path only.** Cloud models (Claude, Gemini) do not share Qwen3's failure modes;
  injecting learned rules into cloud calls would be noise.
- **Extend, not replace.** Base system prompt provides role framing and context awareness
  (dynamic, per-query). Learned rules provide class-level error guardrails (static,
  pre-computed). They are complementary.
- **`task_class` must be resolved unconditionally.** Currently `_classify(question)` only
  runs when `--auto` is set (cli.py line 967). Without `--auto`, `task_class` stays at its
  default `"chat"` — every local call would inject the chat learned prompt regardless of
  query type. Fix: move `task_class = _classify(question)` to run unconditionally in the
  ask command, before the `if auto:` block. `candidates` list still only populated when
  `--auto` is True. This is a required cli.py change in Step 2.

- **Injection point:** after `if not cloud:` at line 1160 of `cli.py`, before `prompt`
  is assembled. Two lines:

  ```python
  _learned = load_learned_prompt(task_class)
  if _learned:
      system = system + f"\n\n[kage learned rules — {task_class}]\n{_learned}"
  ```

  `load_learned_prompt` = one file read + one dict lookup. Zero latency impact.
- **Graceful degradation:** if no learned prompt exists for the class yet, base system
  prompt is used unchanged.

### Validation (F1)

- **Existing 7-step dev workflow** validates the implementation (code correctness).
- **Cold review of the generated prompt** validates the artifact (prompt effectiveness) —
  before Librarian approval, cloud reads the generated rules against the correction logs
  that produced them.
- **HITL approval:** `kage learn` prints the generated prompt and writes it to
  `~/.kage/pending_learned.json` (keyed by class — see MINOR 2 fix). Chirag reads the
  output, optionally runs a manual cold review (asking cloud to check the rules against
  the correction logs), then runs `kage learn --accept [--class X]` to commit. This is a
  human-in-the-loop step — no programmatic gate. The cold review is Chirag's reading +
  optional cloud check, not code.
- **Ongoing signal:** if the new prompt still produces mistakes, corrections accumulate,
  Monitor triggers the next pass. The loop self-corrects.
- **Benchmark (Option A) deferred to v2.** 15 synthetic test questions across 6 error
  classes, auto-graded by string match, before/after each learning pass. Deferred until
  there are enough real learned prompt versions to compare against each other.

### CLI surface (G1, G2)

```
kage learn                   # learn for all classes with ≥1 correction
kage learn --class code      # learn for code class only
kage learn --all             # force relearn all classes regardless of count
kage learn --accept          # write the pending generated prompt to file
kage learn --status          # show current active prompt per class + version
kage learn --rollback code   # set code class back to previous version
```

- **`kage learn`** is a standalone verb — not a subcommand of Monitor or Librarian.
  Monitor calls it as a subprocess; Chirag calls it manually. Both paths work
  independently.
- **Approval gate:** Chirag (HITL via `--accept`). Cold review of the generated prompt
  happens before `--accept` is run.

---

## Recurring error classes (from 81 correction logs — informs v1 learned rules)

```
Class 1  Hallucinated signatures   ~30%   invents APIs it never saw in context
Class 2  Schema / column drift     ~20%   wrong column names under long-prompt pressure
Class 3  Context not in window     ~20%   cannot track renames across non-contiguous sections
Class 4  State / control flow      ~10%   loses mutable state across nested loops
Class 5  Regex anchoring           ~10%   defaults ^/$ anchors; re.match instead of re.search
Class 6  Test patch targets        ~10%   wrong patch target after module extraction
```

Positive signal: **"pure copy/transform tasks with exact target provided are zero-error."**
This is the constraint boundary — the learned rules should push more tasks toward this shape.

---

## Implementation steps

Follows the locked 7-step workflow. Cloud plans and reviews; local (Qwen3) writes all code
and tests.

### Step 1 — `src/kage/learn.py` (new module)

```
load_learned_prompt(task_class, home=KAGE_HOME) → str
  reads ~/.kage/learned_prompts.json
  returns active prompt text for class, or "" if none / file missing

_build_meta_prompt(corrections: list[str], task_class: str) → str
  constructs the cloud meta-prompt (see Design Decisions above)

_count_total_corrections(home=KAGE_HOME) → int
  # direct SQLite COUNT — avoids importing _search_fts from cli.py
  conn = sqlite3.connect(str(home / "indexes" / "kage.db"))
  n = conn.execute("SELECT COUNT(*) FROM memories WHERE project = ?",
                   ("kage-corrections",)).fetchone()[0]
  conn.close()
  return n
  # returns 0 on any exception (DB not yet created, etc.)

_read_learn_state(home=KAGE_HOME) → dict
  reads ~/.kage/learn_state.json; returns {} if missing

_write_learn_state(state: dict, home=KAGE_HOME) → None
  writes ~/.kage/learn_state.json atomically (tmp + os.replace)

run_learning_pass(task_class: str, call_cloud_fn: callable, cfg: dict,
                  home=KAGE_HOME) → tuple[str, str, list[str]]
  # call_cloud_fn is passed in from cli.py to avoid circular import
  # (_call_cloud is defined in cli.py; learn.py must not import from cli.py)
  # signature: call_cloud_fn(provider_name, system, user_msg, cfg) → str
  # provider_name: cfg.get("provider", next(iter(cfg.get("providers", {"claude-sonnet": {}}))))
  #   — same provider resolution as kage ask --cloud; no new config key needed
  1. recalls all notes from kage-corrections project via _search_fts(
       "correction log", "kage-corrections", limit=200, identity="personal"
     ) — note: positional args required, limit=200 is a safe ceiling
  2. filters by task_class keyword hints:
       code        → "function", "class", "import", "test", "def", "sql", "insert"
       research    → "search", "fetch", "scrape", "source", "url"
       reasoning   → "analyze", "compare", "explain", "design"
       multimodal  → "image", "screenshot", "vision"
       chat        → uses ALL unmatched corrections as fallback
     if no corrections match for the class: returns ("", "", []) — caller skips
  writing to pending_learned.json for that class (do NOT write empty entry)
  3. records note IDs of matched corrections as source_note_ids
  4. calls _build_meta_prompt → calls call_cloud_fn → gets full cloud output
  5. extracts bulleted rules from output as prompt (everything after first bullet)
  6. returns (prompt, full_trace, source_note_ids)

save_learned_prompt(task_class: str, prompt: str, trace: str,
                    source_note_ids: list[str], correction_count: int,
                    home=KAGE_HOME) → None
  reads existing learned_prompts.json (or starts fresh {})
  increments version number for class (v1, v2, v3...)
  sets new version as active
  stores both prompt (compact, for injection) and trace (full, for audit / #44)
  stores source_note_ids for future RAG / audit
  writes back atomically (write to tmp path, os.replace)
```

### Step 2 — `cli.py` injection

Two changes to the `ask` command in `cli.py`:

**Change A — unconditional classify (BLOCKER 1 fix):**
Move `task_class = _classify(question)` to run before the `if auto:` block (currently
line 967 is inside `if auto:`). `candidates = _candidates(task_class, cfg)` stays inside
`if auto:`. Result: `task_class` is always correct regardless of `--auto`.

**Change B — injection in local path:**
In the `if not cloud:` block (line 1160), before `prompt` is assembled:

```python
from kage.learn import load_learned_prompt as _load_lp
_learned = _load_lp(task_class)
if _learned:
    system = system + f"\n\n[kage learned rules — {task_class}]\n{_learned}"
```

`task_class` is now correctly set for all local calls via Change A above.

### Step 3 — `kage learn` CLI command

New command in `cli.py`:

```
@app.command()
def learn(
    task_class: str = typer.Option(None, "--class", help="Task class to learn for"),
    all_classes: bool = typer.Option(False, "--all"),
    accept: bool = typer.Option(False, "--accept"),
    status: bool = typer.Option(False, "--status"),
    rollback: str = typer.Option(None, "--rollback"),
)
```

Behaviour:
- `--status`: print current active prompt per class + version + correction_count
- `--rollback X`: set class X active version to previous
- `--accept [--class X]`: write pending prompt(s) from `~/.kage/pending_learned.json` to
  `learned_prompts.json`. Without `--class`, accepts all pending classes. With `--class X`,
  accepts only that class. `pending_learned.json` is keyed by class so `--all` followed by
  `--accept --class code` works correctly without overwriting other pending classes.
  If `pending_learned.json` does not exist: print `"[kage] No pending learned prompts.
  Run 'kage learn' first."` and exit 0.
- default (no --accept): run learning pass, print generated prompt, write to
  `~/.kage/pending_learned.json` (keyed by class). Do NOT write to learned_prompts.json yet.
- `--all`: run for all 5 classes in sequence; each class's result written to its own key in
  `pending_learned.json`

### Step 4 — Monitor integration

Corrections carry no class tag, so Monitor tracks TOTAL correction count (not per-class).
Per-class splitting is handled by `run_learning_pass` internally via keyword hints.

In Monitor's digest (daily run), add a correction-count check:

```python
from kage.learn import _count_total_corrections, _read_learn_state, _write_learn_state

_total = _count_total_corrections()          # direct SQLite COUNT in learn.py
_state = _read_learn_state()                 # reads ~/.kage/learn_state.json
_last  = _state.get("last_learn_correction_count", 0)
if _total - _last >= 7:
    subprocess.run(["kage", "learn", "--all"], check=False)
    _write_learn_state({**_state, "last_learn_correction_count": _total})
```

Key points:
- `_count_total_corrections`, `_read_learn_state`, `_write_learn_state` all live in
  `learn.py` — Monitor imports from learn.py, NOT from cli.py (no circular import).
- `learn_state.json` is separate from Monitor's own state file (`_write_state_json`
  overwrites everything; the learn counter must not be stored there or it will be lost
  on the next Monitor digest run).
- Monitor fires `kage learn --all` but NOT `kage learn --accept` — Chirag reviews first.

---

## Files changed

```
src/kage/learn.py          NEW — load_learned_prompt, run_learning_pass, save_learned_prompt,
                                 _count_total_corrections, _read_learn_state, _write_learn_state
src/kage/cli.py            MODIFY — _classify unconditional (Change A), inject in ask (Change B),
                                    add learn command (~70 lines)
src/kage/monitor.py        MODIFY — import from learn.py, correction-count check in digest
~/.kage/learned_prompts.json   NEW at runtime (created on first kage learn --accept)
~/.kage/pending_learned.json   NEW at runtime (keyed by class; staging area)
~/.kage/learn_state.json       NEW at runtime (last_learn_correction_count)
tests/test_learn.py        NEW
tests/test_cli.py          MODIFY — learn command tests, injection tests, _classify unconditional
tests/test_monitor.py      MODIFY — correction-count trigger tests
```

---

## Security / egress note

Correction logs are sent to cloud (the analysis step) without passing through the 3e
substitution gate. This is a conscious decision: correction logs are dev workflow artifacts
(Qwen3 error descriptions, module names, function signatures) — not personal data. The 3e
gate targets PII (email, Aadhaar, phone); it would not redact `_search_fts` or
`INSERT INTO observations`. For v1, correction egress is accepted as-is. If correction logs
ever contain personal information (e.g., content from a personal note Qwen3 was asked to
process), that is a future concern to address at write time.

---

## Out of scope / deferred

| Item | Why deferred |
|---|---|
| Auto-capture of implicit signals (A1.5) | Requires new instrumentation. v2+ |
| Prompt + routing + retrieval learning (B1 v2) | Clean baseline first. |
| LoRA / weight updates | Blueprint Decision #39. v3+ research only. |
| Per-correction task-class tagging at write time | Corrections currently untagged. Keyword-hint filtering in run_learning_pass covers v1. |
| Librarian staging queue integration | learned_prompts.json is system config, not memory. HITL via --accept is sufficient for v1. |
| 3e gating of correction log egress | Corrections are dev artifacts, not PII. Acceptable for v1; revisit if personal content enters corrections. |
| Benchmark (Option A) | 15 synthetic questions, auto-graded. v2 once real prompt versions exist to compare. |

---

## Version

v0.22.0 — stacks on Cycle 21 (cycle-19-sensitive-vault branch, unmerged).
