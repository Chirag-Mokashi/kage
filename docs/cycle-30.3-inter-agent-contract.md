# Cycle 30.3 — Make the Scout/Monitor → Librarian hand-off fail loud

*Status: SHIPPED. Executed via the 7-step gate on 2026-07-08; 834/834 tests passing (830 pre-existing + 4 new). Option A built exactly as locked — scout.py only, no deposit_to_queue changes.*

> **SHIPPED changelog:** `scout.py`'s report-parsing loop now counts deposits; the blanket `except Exception: pass` audits `scout_deposit_parse_error` (with `deposited_before_error`, so a partial hand-off before a crash is distinguishable from a clean empty one) instead of swallowing silently; a non-empty report that yields zero deposited cards prints a visible `⚠` warning to Scout's own run output *and* audits `scout_deposit_empty`. 4 new tests: recognized headers (no warning), drifted headers (warning + audit fires), exception mid-loop after 2 successful deposits (partial count preserved, no false "empty" double-signal), and a genuinely empty report (no false-positive warning). 834/834 total.
>
> Two more kage-ask-driven-codegen findings surfaced and logged to `kage-corrections` during Step 2/5: (1) `--identity scratch` alone is not sufficient to avoid the local "I don't know — nothing in your notes covers this" fallback when retrieval returns zero notes — it must be paired with one seeded placeholder note in that identity (now done once per kage home). (2) A meta-lesson from my own tooling: never embed a literal backtick-quoted shell command inside a double-quoted bash string passed to another command — the outer shell interpolates it as a subshell before the inner command sees the text (caught a garbled memory entry from exactly this, deleted and re-saved clean).
*Discipline: 7-step dev-workflow gate. Local (Qwen3) will write all code/tests; cloud reviews.*
*Date: 2026-07-08*
*Series: third and last of the 30.x mini-cycles (30.1 routing ✅ → 30.2 inbound guardrail ✅ → **30.3 hand-off failure visibility**).*

> **v2 changelog (2 cold reviews, both REVISE, core F1 sound; both said DEFER is a legitimate alternative):**
> - **BLOCKER (both reviewers, independently — INVARIANT ENUMERATION RULE): the caller enumeration undercounted.** v1 grepped the call-syntax `deposit_to_queue(` and missed **`librarian.py:886`**, where the function is registered as a bare symbol in the Librarian's ADK `tools=[...]` list — making the Librarian LLM a live caller whose **return value IS consumed** (serialized back into the model context). This falsified v1's "all callers ignore the return, so returning `""` is safe" claim. **v2 fix: enumeration = 5 sites; the `""`-return change is DROPPED entirely** — validation is audit-only and never changes `deposit_to_queue`'s return semantics, so the ADK-tool caller is unaffected. (Second cycle running the enumeration grep undercounted; logged the bare-symbol grep pattern to `kage-corrections`.)
> - **SHOULD-FIX (both): A3 doctor check CUT.** Every `doctor` check is a current-state pass/fail invariant ([cli.py:1445-1518](../src/kage/cli.py#L1445)); scanning the append-only audit log for historical anomalies violates the doctor=health / status=snapshot convention (`feedback_status_vs_doctor.md`) and would go sticky-red forever off one stale record. Cut.
> - **SHOULD-FIX (reviewer B): A2's signal must reach a surface the user actually reads**, not audit-only — an audit line no one opens is a *quieter* failure, not awareness. v2: Scout prints a one-line warning to its run output *and* audits.
> - **SHOULD-FIX (both): 50k oversize cap DROPPED** — neither real producer can approach it (monitor snapshot < 1 KB; scout cards low-thousands), so it guarded a non-event. Gold-plating, cut.
> - **NIT (reviewer A): empty-content guard is redundant** vs the real producers (all 3 scout sites are already `if current_card:`-guarded and seed a `### ` header; monitor uses a fixed non-empty template). Downgraded to an audit-only observation, not a reject.
> - **NIT (reviewer B): reuse the existing idioms** — `_KNOWN_SOURCES` as a `frozenset` mirroring `privacy._ALWAYS_LOCAL_PROJECTS`; audit records use librarian.py's own `{"event": ..., "ts": ...}` shape (NOT the `{"type": ...}` v1 wrote); validate at **function entry** (before the dedup SELECT), so classification is independent of queue state.
> - Both verified v1's two "already safe" claims are CORRECT (read-path name-keyed; identity canonicalized on both `write_note` and CTM paths).

---

## Honest scoping (ponytail — the reviews shrank this cycle; read before deciding to build)

Grounding in the real code removed most of v1's proposed surface. What's **already safe** (verified by both reviewers, no fix needed):
1. **Read-path drift (observe.py class):** `get_staging_queue` ([librarian.py:132-139](../src/kage/librarian.py#L132)) is `sqlite3.Row` + `dict(row)` — name-keyed, immune to positional drift.
2. **Identity mistagging (Cycle 28.1 class):** every deposit→`memory_identities` path canonicalizes through `resolve_write_identity()` first — `write_note` ([librarian.py:666](../src/kage/librarian.py#L666)) and the CTM path ([librarian.py:587](../src/kage/librarian.py#L587)). No raw-identity write path exists at this seam.

So a typed-schema framework is gold-plating. **After the reviews, this cycle collapses to essentially one real fix (F1) plus one line of cheap seam insurance.** DEFER is a legitimate call — both reviewers said so — and I'm surfacing that as an explicit option below rather than building for completeness.

## The one real bug (F1) — Scout can hand the Librarian NOTHING, silently

All three producer→Librarian hand-offs funnel through `deposit_to_queue(content, source, reason="", project=None, identity=None)` ([librarian.py:175](../src/kage/librarian.py#L175)). **Corrected repo-wide enumeration (5 sites, bare-symbol grep):**

```
$ grep -rn "deposit_to_queue" src/kage/*.py
librarian.py:175  def deposit_to_queue(...)              # the seam
librarian.py:886  deposit_to_queue,                      # ← ADK tools=[...] registration (MISSED in v1)
scout.py:13       from kage.librarian import deposit_to_queue
scout.py:557      deposit_to_queue("\n".join(current_card).strip(), "scout", project=project)
scout.py:564      deposit_to_queue(...)
scout.py:569      deposit_to_queue(...)
monitor.py:733    deposit_to_queue(content, source="monitor", project=..., identity=...)
```

Scout parses the cloud model's markdown report by string-matching headers (`## Tier 1`, `## Tier 2`, `### `) at [scout.py:548-569](../src/kage/scout.py#L548), and the **entire loop is wrapped in `except Exception: pass`** ([scout.py:570-571](../src/kage/scout.py#L570)). Both reviewers confirmed **nothing surfaces a zero-deposit today**: `_token_log` records `items`/`report_chars`, and the `scout_runs` INSERT records `notes_fetched` — all *fetched* counts, never *deposited*. So if the cloud model changes its header style (`## Tier 1:` / `**Tier 1**` / localized — which happens on a provider/model swap, and kage swaps Scout providers), the parser matches nothing, deposits nothing, and Scout runs green with **no signal anywhere.** The hand-off transfers empty and no one knows. This is the true inter-agent analog of the schema-drift bug — and the reason to build.

## What we're adding (trimmed to what survived review)

**F1 fix (the load-bearing change) — make the silent hand-off loud.** In Scout's deposit loop ([scout.py:548-571](../src/kage/scout.py#L548)):
  - count successful deposits;
  - narrow the blanket `except Exception: pass` to an `except` that **audits** `scout_deposit_parse_error` (Scout stays resilient — still no crash — but no longer silent), preserving any partial deposits already made;
  - after the loop, if the report was non-empty but **zero** cards were deposited, (a) **print a one-line warning to Scout's run output** — the surface the user actually reads — e.g. `⚠ Scout parsed 0 cards from a non-empty report (header drift?) — nothing handed to the Librarian`, and (b) audit `scout_deposit_empty` (report length) for the record.

**Seam insurance (minimal, audit-only, no return change) — optional, see decision below.** At `deposit_to_queue` **entry** (before the dedup SELECT):
  - `_KNOWN_SOURCES: frozenset[str] = frozenset({"monitor", "scout"})` (the real non-LLM producers). An unrecognized `source` still deposits normally and **still returns its real id** — it only additionally emits `{"event": "deposit_unknown_source", "source": source, "ts": ...}` so a typo surfaces in the log. No behavior change, no return-type change → the ADK-tool caller and all existing tests are unaffected.
  - (empty content likewise: still returns an id; optionally emit `deposit_empty_content` as an observation. Marginal — the real producers can't emit empty. Include only if the seam-insurance option is chosen.)

**REAL-SCHEMA test:** the existing `lib_env` fixture already builds a real `Store` + `init_schema()` and does not monkeypatch the connection ([test_librarian.py:24-36]), so every `deposit_to_queue` test already exercises the real schema — the rule is satisfied for free.

## The build-vs-defer decision — DECIDED: Option A

Both reviewers: F1 is a real latent bug worth fixing at a shared seam; the rest is trimmed to near-zero; DEFER is legitimate. **User chose Option A (2026-07-08): build F1 only.**

- **Option A (CHOSEN) — build F1 only.** Fix Scout's silent zero-deposit (loud on stdout + audit, narrowed except). ~20 lines, one real bug, no seam changes, no return-semantics risk. The most ponytail version — "inter-agent contract" turns out to mean "the hand-off must not fail silent." Rationale: a background/autonomous agent silently disabling a whole pipeline is the worst failure mode for kage's "Aware" characteristic; ~20 lines to convert silent pipeline-death into a visible warning is worth it. Option B's source-audit dropped — reviews showed the real producers can't emit a bad source, so it would only add test-suite audit noise for zero real coverage.
- ~~Option B — F1 + source-audit seam insurance.~~ Not chosen (marginal/redundant).
- ~~Option C — defer.~~ Not chosen (won't knowingly leave a silent failure in the unattended path when the fix is this small).

**Scope for build:** `scout.py` only. No `librarian.py` / `deposit_to_queue` changes.

## Files / seams

- `src/kage/scout.py` — deposit counter; narrowed `except` with `scout_deposit_parse_error` audit; post-loop stdout warning + `scout_deposit_empty` audit. (Both options.)
- `src/kage/librarian.py` — (Option B only) `_KNOWN_SOURCES` frozenset + entry-point `deposit_unknown_source` audit; `{"event", "ts"}` shape; no return change.
- `tests/test_scout.py` + `tests/test_librarian.py` — see test plan; real-schema for the librarian test.

## Direction / safety

- Pure additive; changes no read path, no promotion, no identity handling (all already correct). Writes only to the local staging DB / audit log — no egress, no privacy surface.
- **Return semantics unchanged** (v1's `""`-return dropped), so the ADK-tool caller at librarian.py:886 and the ~30 id-binding tests are unaffected. Cold review must re-confirm no return-type change slipped in.

## Known ceilings (ponytail)

- F1's signal detects "zero cards deposited," not "wrong cards deposited" — a parser that mis-slices but still yields *some* card won't trip it. Bounded; not a parser rewrite.
- `_KNOWN_SOURCES` (Option B) is hardcoded; a new agent's first deposit audits once until added. Intended fail-loud, but a manual step; named.
- Content-shape inside `content` stays unvalidated — the Librarian distill (LLM) is the tolerant consumer by design.

## Test plan (local writes in step 5)

- Scout: report with recognized headers → N cards, no empty-warning/audit; report with drifted headers (`**Tier 1**`) → 0 cards + stdout warning + `scout_deposit_empty` audit; an exception mid-loop → `scout_deposit_parse_error` audit, partial deposits preserved, run completes; **N-then-exception** case (reviewer B) — partial count recorded, not reported as clean-empty.
- (Option B) `deposit_to_queue`: known source → deposits, no audit; unknown source → **still returns a real id** + `deposit_unknown_source` audit; a dedup-hit (duplicate content_hash returns existing id) does **not** emit a spurious rejection/unknown audit. At least one against the real `init_schema()` DB.

## Out of scope (leave the seam)

- Typed/pydantic deposit schema (gold-plating; read path already name-keyed).
- Any `""`-return / return-type change (dropped — the ADK-tool caller consumes the return).
- A `kage doctor` audit-log scan (cut — violates doctor=health convention).
- Content-oversize cap (dropped — producers can't approach it).
- Any change to promotion / identity canonicalization (already correct).
