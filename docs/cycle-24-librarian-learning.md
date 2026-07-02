# Cycle 24 — Librarian Learning: learn from rejections (EPM, v0.24.0)

*Status: SHIPPED v0.24.0 (`f16e861`). Pitch v3 (2026-07-01). TWO cold reviews done (independent
subagents vs. real repo). CR#1 forced the scope split (EPM-only; CTM → Cycle 25) and
fixed 3 BLOCKERs. CR#2 returned ready-with-fixes (zero BLOCKERs) and confirmed the
critical invariant: the always-local gate does NOT starve the learn pass (it reads via
raw sqlite3 + disk, not the gate). CR#2's 5 must-fixes are folded in below (marked ✎CR2).*

*Depends on: Cycle 23 (gate hardening, merged 7fd9156). Branches off post-Cycle-23.*

*Built per the 7-step dev workflow: plan cloud → write local (Qwen3) → review
cloud → plan tests cloud → write tests local → review tests cloud → run tests local.*

*Not part of the Kaggle submission. Build after July 6.*

---

## North star

> Close the feedback loop every 2025–26 observability platform leaves open. The
> Librarian already asks the human to approve/reject each distilled memory candidate,
> and throws the answer away. This cycle captures **rejections** and feeds them back:
> the Librarian learns which distillations it should not have made, and stops repeating
> them. This is the low-risk half of MemAPO's dual-memory design — Error-Pattern Memory.
> The Correct-Template Memory half (learning from approvals, injected at runtime) is
> Cycle 25.

Scope: **one agent (Librarian), one signal (reject), one mechanism (batch, reusing the
existing Layer 6 engine).**

---

## Why this scope (what cold review #1 changed)

v1 proposed EPM (rejections) **and** CTM (approvals, runtime-injected) together. The
review confirmed the risk concentrates entirely in the CTM-runtime half:

- PROMOTE-bias (injecting only approved examples),
- the local-Qwen3 LLM-check machinery,
- an unknown context ceiling on loading all approved trajectories.

None of those touch EPM. EPM reuses a proven batch engine and carries only mechanical
fixes. So we ship EPM now and give CTM its own careful cycle. The v1 `ctm_enabled`
seam becomes simply: **CTM does not exist yet** (Cycle 25).

---

## What already exists (reused, not rebuilt)

`learn.py` is an Error-Pattern-Memory engine already: `run_learning_pass(task_class, …)`
reads the `kage-corrections` project, distills error patterns into a rules block via
cloud, and the `pending → kage learn --accept` HITL flow versions them into
`learned_prompts.json`; `load_learned_prompt(key)` prepends the active block to a system
prompt. Batch-triggered by `monitor._maybe_trigger_learn` (rides the 07:00 digest).

`load_learned_prompt` / `save_learned_prompt` are keyed by **arbitrary string** (verified
learn.py:21–31, 146–175), so a `"librarian"` key drops in with no change to those two.

Signal point: `reject_approval(approval_id, reason)` (librarian.py:816). Consumption
point: `distill_and_judge` builds `_DISTILL_SYSTEM` (librarian.py:301) and passes it to
`runtime.cloud.complete(provider, _DISTILL_SYSTEM, …)` at librarian.py:391.

---

## Architecture (single path)

```
  kage librarian reject <id> --reason "..."
        │
        ▼
  reject_approval(): SELECT note title + source + reason  →  write a note to
        project kage-corrections-librarian, worded "Correction log — Librarian ..."
        │
        │   (batch, rides monitor 07:00 digest via _maybe_trigger_learn)
        ▼
  run_librarian_learning_pass(): FTS-read kage-corrections-librarian
        →  librarian meta-prompt  →  cloud distills rules
        →  pending_learned.json["librarian"]
        │
        │   kage learn --accept        (HITL — human accepts the rules)
        ▼
  learned_prompts.json["librarian"]  active version
        │
        ▼
  distill_and_judge(): load_learned_prompt("librarian") prepended to _DISTILL_SYSTEM
```

---

## Fixes carried from cold review #1

### FIX B1 (was BLOCKER) — correction notes must never egress
The partition wall does **not** protect a project from a no-active-project cloud query:
`store.allowed_note_ids(identity, None)` returns all-project notes (store.py:157). So a
note in `kage-corrections-librarian` would be retrievable by a plain `kage ask --cloud`.
`_disclosure_gate` (privacy.py) only hard-blocks on identity wall, the `local_only` flag,
and `local_only_projects` membership (privacy.py:62).

**Fix:** privacy.py gains a module-level always-local set, hard-blocked in **both**
egress functions regardless of user config:

```python
_ALWAYS_LOCAL_PROJECTS = {
    "kage-corrections-librarian",  # this cycle
    # NB: kage-corrections is added by a SEPARATE isolated commit (see §Commit plan)
    # NB: kage-ctm-librarian is NOT reserved here — Cycle 25 adds it when CTM lands (YAGNI ✎CR2)
}
```

A note whose project is in this set is withheld exactly like a `local_only:project` hit.

**✎CR2 — enforce in TWO functions, not one.** CR#2 found `_gate_conversation`
(privacy.py:89 — the session/chat egress path, called from session.py + cli REPL + MCP)
has **no project-membership check at all**, not even the existing `local_only_projects`.
Retrieval (`_disclosure_gate`) is not the only path to cloud. The invariant must hold on
both: add the `_ALWAYS_LOCAL_PROJECTS` block to `_disclosure_gate` **and** to
`_gate_conversation` (the latter needs the note's project, fetched alongside its existing
`local_only` flag lookup). For EPM-only the chat-leak risk is narrow (correction notes are
Librarian-authored, unlikely to enter a chat turn's `note_ids`), but a safety invariant
that only holds on one of two egress paths is not an invariant.

This is a **more restrictive** gate change (safe direction) but touches the
security-critical gate Cycle 23 just hardened → the gate diff gets its own subagent
cold-review. **Confirmed by CR#2:** this block lives in the egress gate only; the Layer 6
learn pass reads corrections via raw `sqlite3` + direct disk read (learn.py:90–111) and
never calls the gate, so blocking these projects does NOT starve the learner.

### FIX B2 (was BLOCKER) — the learn reuse + trigger are real surgery, done safely
Three concrete problems in v1, each fixed:

1. **FTS query.** `run_learning_pass` matches `'"correction" "log"'` (FTS5 space = AND).
   v1's proposed wording matched neither token. **Fix (jugaad):** word Librarian
   corrections with the same prefix the dev-workflow mistake log already uses —
   *"Correction log — Librarian …"* — so they match the existing query verbatim.
2. **Hardcoded project.** `run_learning_pass` and `_count_total_corrections` hardcode
   `kage-corrections`. **Fix:** add a **new parallel** `run_librarian_learning_pass(project, …)`
   and `_count_corrections(project)` rather than mutate the shipped functions (protect the
   code/research loop from regression — ~15 lines duplicated is cheaper than the risk).
3. **Dead trigger.** `_maybe_trigger_learn` fires `kage learn --all`, which loops
   `ALL_CLASSES` — no `"librarian"` target exists. **Fix:** add a `kage learn --librarian`
   path and give `_maybe_trigger_learn` a **second counter** (`last_librarian_learn_count`)
   for the librarian project that fires `kage learn --librarian` at the same 7+ threshold.

### FIX B3 (was BLOCKER) — Librarian needs its own meta-prompt
`_build_meta_prompt` is code-specific ("name the exact API, method, column"; interpolates
`{task_class}`). Reusing it on curation rejections yields nonsense. **Fix:** a new
`_build_librarian_meta_prompt(corrections)` framed for curation quality — e.g. *"Each
entry is a memory-curation decision the Librarian made that the user rejected. Write rules
that would stop the wrong PROMOTE/HOLD/DISCARD or the wrong dedup/quality judgment. Name
the concrete signal (source type, staleness, redundancy) — no vague advice."* Budgeted in
files-changed.

### FIX m1 — `reject_approval` must gather title/source
It currently has only `approval_id` + `reason` (librarian.py:816). To write the correction
it SELECTs `note_json` (for the distilled title, present on the approval row even though a
rejected note never calls `write_note`) and joins `staging_queue` for `source`. One extra
query, all columns confirmed present (CR#2). **✎CR2:** for *manual* approvals `staging_id`
is NULL (librarian.py:830) → `source` will be absent; word the correction defensively
(empty source tolerated, no crash).

### FIX open-Q4 — don't depend silently on the daemon
CR#2's weakest-point finding: `_maybe_trigger_learn` rides the monitor 07:00 digest, so if
the user never runs the launchd daemon, librarian learning never fires. **Fix (cheap, keeps
"aware not steered"):** `kage librarian reject` opportunistically checks the librarian
correction count and prints a hint when the threshold is crossed — *"7 rejections pending
— run `kage learn --librarian`"*. No second trigger mechanism; just surfaces the state.

---

## Config (optional; safe defaults)

```jsonc
"librarian": {
  "learning": { "epm_enabled": true }   // prepend learned librarian rules to _DISTILL_SYSTEM
}
```

`epm_enabled: false` disables prepending with no code removal. The B1 always-local
protection is NOT config-gated — it is unconditional in the gate.

---

## Files changed (estimated)

```
src/kage/privacy.py     CHANGE — _ALWAYS_LOCAL_PROJECTS hard-block in BOTH _disclosure_gate
                                 AND _gate_conversation (✎CR2) (security-critical — own review)
src/kage/librarian.py   CHANGE — reject_approval(): SELECT title/source (defensive on NULL
                                   staging_id ✎CR2), emit "Correction log — Librarian ..."
                                   note to kage-corrections-librarian (guarded: only on the
                                   found-row branch, once per rejection); print threshold
                                   hint (✎CR2 open-Q4)
                                 distill_and_judge(): prepend load_learned_prompt(
                                   "librarian", home=runtime.config.home) — NOT the bare
                                   default (✎CR2 home-propagation) — to _DISTILL_SYSTEM when
                                   epm_enabled
src/kage/learn.py       NEW    — run_librarian_learning_pass(project, call_cloud_fn, cfg, home)
                                 _count_corrections(project, home)
                                 _build_librarian_meta_prompt(corrections)  [no {task_class}]
src/kage/cli.py         CHANGE — `kage learn --librarian` path: mirror the else-branch
                                 (cli.py:2123+) but call the librarian pass → pending["librarian"];
                                 --accept already handles arbitrary keys (cli.py:2057);
                                 add "librarian" to the --status display loop (✎CR2 —
                                 status loops ALL_CLASSES at cli.py:2089 and would hide it)
src/kage/monitor.py     CHANGE — _maybe_trigger_learn: second counter last_librarian_learn_count
                                 (merge-spread write, coexists with code counter) + fire
                                 `kage learn --librarian`
tests/test_privacy* / test_cli.py   CHANGE — always-local block in BOTH gate functions
tests/test_librarian.py CHANGE — reject emits correctly-worded, correctly-projected note;
                                 distill prepends librarian rules when present
tests/test_learn.py     CHANGE — librarian pass reads scoped project; does not touch
                                 code/research prompts
```

## Commit plan (✎CR2 — isolate the retro-fix)

The `kage-corrections` retro-protection is a behavior change to a **shipped** project, so it
lands as its own isolated commit + test, not folded into the librarian diff:

1. `fix(privacy): hard-block kage-corrections from cloud egress` — adds `kage-corrections`
   to `_ALWAYS_LOCAL_PROJECTS` in both gate functions, with its own regression test. (Pre-
   existing leak; one line; no other flow intends to egress dev-workflow corrections.)
2. `feat: Cycle 24 — Librarian EPM learning` — everything else.

No new module. (ponytail: fewest files; new logic lands in learn.py alongside its kin.)

---

## Test plan (one runnable check per non-trivial unit)

- **B1 gate (security-critical):** a note in `kage-corrections-librarian` (and in
  `kage-corrections`) is withheld by **both** `_disclosure_gate` and `_gate_conversation`
  (✎CR2) even with `project=None` and no `local_only` flag. A note in an ordinary project
  is still allowed. ← the guard that fails loudly if either egress path reopens.
- `reject_approval` on a real approval row writes exactly one note to
  `kage-corrections-librarian`, prefixed "Correction log — Librarian", containing the
  distilled title, source, and reason.
- `reject_approval` on a missing id writes no note and returns False (no orphan emit).
- `run_librarian_learning_pass` reads only `kage-corrections-librarian`; a `kage-corrections`
  code note does not leak into the librarian rules, and vice-versa.
- FTS: a "Correction log — Librarian …" note is actually matched by the pass (guards the
  jugaad wording fix — if someone rewords the prefix, this fails).
- `distill_and_judge` with a saved `"librarian"` learned prompt prepends it to the system
  message; with none, the system message is byte-identical to today.
- `_maybe_trigger_learn` fires `kage learn --librarian` after 7+ librarian corrections,
  independently of the code/research counter (mock subprocess).
- `_build_librarian_meta_prompt` contains no code-specific language / no `{task_class}`.
- **✎CR2:** `kage learn --status` displays the `librarian` key (regression guard for the
  ALL_CLASSES loop omission). `--accept` and `--rollback librarian` round-trip cleanly.
- Cloud + local models mocked throughout (no live dependency). Pass `home` explicitly to
  every learn.py call (per the home-propagation rule — module constants differ under
  monkeypatch); `distill_and_judge` uses `home=runtime.config.home`.

---

## Out of scope (explicit)

- **CTM / learning from approvals / runtime injection** → **Cycle 25** (its own pitch:
  full-trajectory store, local-Qwen3 LLM-check, gate-before-inject, PROMOTE-bias framing,
  context ceiling). Cycle 25 adds `kage-ctm-librarian` to `_ALWAYS_LOCAL_PROJECTS` itself
  when the project first exists (✎CR2 — not reserved speculatively here).
- **Scout and Monitor** decision learning — later cycles.
- **Cross-agent semantic backpropagation** (arxiv 2412.03624) — later; kage's topology is
  sequential, per-agent EPM suffices for v1.
- **Per-event (online) triggering** — batch only; seam not built.

---

## Risks & rollback

- **Egress (highest):** the B1 gate change is the load-bearing safety fix. If wrong,
  correction notes (which may contain snippets of rejected content) leak to cloud. The
  security-critical test above + a dedicated subagent cold-review of the privacy.py diff
  are mandatory.
- **Regressing the shipped learn loop:** avoided by *adding* parallel librarian functions,
  not mutating `run_learning_pass` / `_count_total_corrections`. Test asserts the two
  loops stay independent.
- **Meta-prompt quality:** a bad librarian meta-prompt yields useless rules — but the HITL
  `kage learn --accept` step means no rules take effect without the user reading them.
- **Rollback:** `epm_enabled: false` stops prepending; `kage learn --rollback librarian`
  reverts to a prior version (existing mechanism). The B1 gate block stays regardless
  (it is pure protection).

---

## Resolved by the two cold reviews (were open questions)

1. **`_ALWAYS_LOCAL_PROJECTS` mechanism** → hard-coded, not config-seeded. It is a safety
   invariant a user must not be able to remove. (CR2 agreed.)
2. **Retro-protect `kage-corrections`?** → Yes, close it here — real leak, one line — but as
   its own isolated commit + test (see §Commit plan). (CR2 agreed.)
3. **Cycle-23 gate ordering vs. prepended rules?** → No interaction. Gate runs on `content`
   (librarian.py:369); rules go into the separate `_DISTILL_SYSTEM` string (librarian.py:391).
   Verified clean by CR2.
4. **Daemon-only trigger?** → Fixed: `kage librarian reject` prints a threshold hint (§FIX
   open-Q4). Manual `kage learn --librarian` always works as the explicit path.
5. **Does always-local starve the learn read?** → No. Learn reads via raw sqlite3 + disk
   (learn.py:90–111), never the gate. Verified by CR2 — this was the make-or-break question.
