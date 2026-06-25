# Scout v1.1 — project-aware analysis + Tier 1/2 depth

*Status: PITCH v3 (cloud-authored, Sonnet 4.6; v1 2026-06-25, v2–v3 cold reviews same day). 7-step dev workflow applies.*
*Branch: cycle-14-scout-v1.1 (not yet created). Base: main (v0.14.0).*

> **v2 changelog (cold review #1, independent subagent, 2026-06-25):**
> (Blocker) §6 "Existing tests to update" named four phantom test functions that don't exist in
> `test_scout.py` — replaced with actual names from the file. (Major) Two-line GitHub corpus
> format will IndexError on `test_corpus_round_robin_order` / `test_corpus_round_robin_interleaves`
> because those tests split every non-empty line on `[` — §6 now calls out the filter fix. (Major)
> Multi-line corpus block cap atomicity was unspecified — §2 now states the two-line block is
> treated as atomic. (Major) Tier 1/2 format coupling between broad and integrate has no fallback
> — §3 now adds a `ponytail:` ceiling comment. (Minor) Zero-value integer ambiguity — §2 clarifies
> `score=0`/`forks=0` are always shown (integers, never omitted). (Minor) `test_run_once_injects_project`
> needs both `create_session` AND `get_session` async mocks — §6 points to the reference pattern.

> **v3 changelog (cold review #2, independent subagent, 2026-06-25):**
> (Blocker) `test_run_once_async_returns_state` will read real disk state after v1.1 adds
> `_resolve_context` call — added to §6 update table. (Blocker) "from the shortlist above" in
> CRITICAL grounding rule of `_INTEGRATE_INSTRUCTION` — verified correct: ADK Workflow passes
> the previous node's final response as the user message to the next node (confirmed by v0.14.0
> shipping and producing reports); added an explicit note in §4. (Major) `_CORPUS_CHAR_CAP=120k`
> leaves ~200 token headroom for broad instruction + output — §3 adds a `ponytail:` note to reduce
> cap to 100k in this change. (Major) Step 1 empty-result fallback missing from integrate instruction
> — §4 adds explicit instruction. (Major) `_corpus` omit-empty-field algorithm was prose-only — §2
> now gives the concrete one-liner. (Major) Empty Tier 1 `(none)` not handled in integrate
> instruction — §4 adds explicit instruction. (Minor) Bootstrap format change now documented in §3.
> (Minor) "omit this line" → "omit this block" fixed in §4 prose. (Minor) Version updated here.

---

## What changed and why

v0.14.0 Scout produces shallow, kage-specific, source-grouped headlines.
Three problems locked in this session:

1. **Hallucination under thin corpus** — fixed in v0.14.0 commit 30b772b. Already shipped. ✓

2. **Analysis is too shallow.** "One sentence why notable" is not enough to decide
   whether to spend time on something. A business-minded person would ask a dozen
   more questions. Scout should answer them so you don't have to.

3. **Instructions are kage-specific.** Every analysis field says "kage." Scout will be
   reused across projects. The lens must switch automatically with `kage use <project>`.

4. **GitHub items lack statistics.** Stars and description are fetched; forks, language,
   license, and last-push date are in the API response but not captured. These are the
   first things anyone checks before spending time on a repo.

5. **Tier 1 / Tier 2 split is missing.** All items get the same shallow card. Actionable
   items (repos, papers with impl potential) deserve a full business-ruthlessness card.
   General news (HN stories, world events) deserves a light card. Nothing is dropped —
   Librarian owns curation.

---

## Scope (v1.1 only — nothing else)

Five targeted changes to `src/kage/scout.py`. No new files, no new dependencies,
no new CLI commands.

| Change | What |
|---|---|
| `_fetch_github` | +4 fields (forks, language, license, pushed_at) |
| `_corpus` | include GitHub stats as second line per GitHub item |
| `_BROAD_INSTRUCTION` | Tier 1/2 classifier; nothing dropped; reduce cap |
| `_INTEGRATE_INSTRUCTION` | project-aware dual-card; Step 1/2/3 tool-use |
| `_run_once_async` | inject `{project}` from `_resolve_context()` |

**NOT in v1.1:**
- Reddit 403 fix (deferred)
- New fetch sources
- Librarian promotion logic
- launchd scheduling
- RSS feed configuration

---

## §1 — `_fetch_github` enrichment

The GitHub Search API already returns `forks_count`, `language`, `license`, and
`pushed_at` in every item. We are currently discarding them. Add four fields to
the returned dict (lines ~100–107 in v0.14.0):

```python
{
    "source":    "github",
    "title":     item["full_name"],
    "url":       item["html_url"],
    "score":     item.get("stargazers_count", 0),
    "snippet":   item.get("description") or "",
    "forks":     item.get("forks_count", 0),
    "language":  item.get("language") or "",
    "license":   (item.get("license") or {}).get("spdx_id") or "",
    "pushed_at": (item.get("pushed_at") or "")[:10],   # YYYY-MM-DD only
}
```

No new API call. No new rate-limit exposure. Pure dict enrichment.

---

## §2 — `_corpus` — include GitHub stats as second line

`_corpus()` builds the text fed to both LLM stages. GitHub items must include
the new fields. Non-GitHub items are unchanged.

### Format

For each GitHub item, render as two lines:
```
[github] owner/repo — description
  ⭐ {score} stars · 🍴 {forks} forks · {language} · {license} · last push {pushed_at}
```

`score` and `forks` are always shown (integers; `0` is a valid and meaningful value,
not a missing value). `language`, `license`, and `pushed_at` are strings; omit any
that are empty string.

### Concrete omission algorithm

```python
parts = [f"⭐ {it['score']} stars", f"🍴 {it['forks']} forks"]
for field in (it.get("language", ""), it.get("license", ""), f"last push {it.get('pushed_at', '')}"):
    if field and field != "last push ":
        parts.append(field)
stats = " · ".join(parts)
rendered = f"[github] {it['title']} — {it['snippet']}\n  {stats}\n" if stats else f"[github] {it['title']} — {it['snippet']}\n"
```

In practice `score` and `forks` are always present (defaulted to `0`), so `parts`
always has at least two elements and `stats` is never empty. The conditional is a
defensive fallback only.

### Cap atomicity

The two-line GitHub block is treated as an **atomic unit** for the `_CORPUS_CHAR_CAP`
check: if `len(corpus) + len(rendered) > _CORPUS_CHAR_CAP`, the whole item is skipped
(both lines), not just the second line. This matches the existing cap behavior for
single-line items and avoids orphaned first lines.

Also: change `_CORPUS_CHAR_CAP` from `120_000` to `100_000` in this same step.
At ~4 chars/token, 120k chars ≈ 30k tokens, which leaves ~200 tokens headroom for
the broad instruction (~200 tokens) and its output (~1,500 tokens) against Qwen3's
32k context window. 100k chars ≈ 25k tokens leaves ~6,800 tokens of headroom — safe.

```python
# ponytail: 100k cap leaves ~6k token headroom in Qwen3's 32k window;
# ceiling = Qwen3 ctx limit; upgrade path = raise cap if model is swapped for larger ctx
_CORPUS_CHAR_CAP = 100_000
```

---

## §3 — `_BROAD_INSTRUCTION` rewrite

Qwen3 (Pass 1+2, local, $0). Receives the full corpus. Output: two sections only.
**Nothing dropped.** Every item lands in Tier 1 or Tier 2.

### Tier 1 — Actionable
Items that could become a task, cycle, or implementation decision for a generic software
engineering project:
- GitHub repos with novel or useful functionality
- Research papers with concrete implementation implications
- New tools or techniques that could replace something in a typical stack

**Note:** The broad stage has no project context (`{project}` is only in the integrate
stage). Classify generically using the heuristic above, not against any specific project.

### Tier 2 — Good to Know
Everything else:
- Company news, acquisitions, funding rounds
- General releases (of things not affecting a typical stack)
- Industry trends, opinion pieces, world events
- Interesting but not actionable in a software project

### Bootstrap note
`bootstrap` uses `cloud=False` (broad stage only). `bootstrap.md` will now contain
a Tier 1 / Tier 2 classified list instead of the old source-grouped format. This is
intentional — the classification is useful even without the integrate stage.

### Tier 1/2 format coupling (known ceiling)
```python
# ponytail: ScoutIntegrate receives ScoutBroad's output as its user message (ADK Workflow
# passes previous node's final response to next node). Format compliance depends on Qwen3 14B.
# If Tier 1/Tier 2 headers are malformed or [source] tags are inconsistent, ScoutIntegrate
# sees noise and may hallucinate structure. Upgrade path = validate shortlist format before
# passing to cloud stage (e.g. regex check for "## Tier" headers before run_async).
```

### Exact instruction string

```python
_BROAD_INSTRUCTION = (
    "You are Scout's triage stage. You receive a corpus of recent items from Hacker News, "
    "arXiv, GitHub, Reddit, and RSS feeds.\n\n"
    "CRITICAL: Only classify items explicitly present in the corpus. "
    "Do not add, invent, or infer items from your training knowledge.\n\n"
    "Classify every item into exactly one tier. Nothing is dropped.\n\n"
    "You have no information about the active project. Classify generically:\n"
    "Tier 1 — Actionable: items that could become a task, implementation decision, or cycle "
    "for a software engineering project. Includes: GitHub repos with novel/useful functionality, "
    "research papers with concrete implementation implications, tools or techniques that could "
    "replace something in a typical stack.\n\n"
    "Tier 2 — Good to Know: everything else. Includes: company news, acquisitions, funding, "
    "general releases, industry trends, opinion pieces, world events. Interesting but not "
    "directly actionable in a software project.\n\n"
    "Output format — use exactly:\n\n"
    "## Tier 1 — Actionable\n"
    "- [source] Title — one sentence why actionable\n\n"
    "## Tier 2 — Good to Know\n"
    "- [source] Title — one sentence summary\n\n"
    "Where [source] is one of: hn, arxiv, github, reddit, rss.\n"
    "If a tier has no items write: (none)"
)
```

---

## §4 — `_INTEGRATE_INSTRUCTION` rewrite

Cloud (Pass 3+4). Receives the Tier 1/2 shortlist **as its user message input**.

### How ADK passes the shortlist

In ADK Workflow, `ScoutBroad` writes its final response to `output_key="shortlist"`
in session state. ADK then passes the previous node's final response as the **user
message** to the next node (`ScoutIntegrate`). This means the shortlist IS present
as the content "above" in the integrate stage's conversation. The CRITICAL grounding
rule referencing "the shortlist above" is therefore correct.

This was confirmed empirically: v0.14.0 ships and produces reports, which means
the integrate stage receives the broad stage's output correctly.

### Opening action (mandatory, before any item analysis)

The cloud node must first call:
```
scout_recall("{project} current stack implementation goals and recent changes")
```
This gives it project context before analyzing any item. If `scout_recall` returns
empty results (sparse project memory), all `Currently used` and `Previously used`
fields must be written as `unknown` — do not infer from training knowledge.

### Empty Tier 1 handling

If the Tier 1 section of the shortlist contains only `(none)`, write:
```
## Tier 1 — Actionable
(none)
```
Do not write any cards. Do not invent items.

### Tier 1 card — full business-ruthlessness

One card per Tier 1 item. Call `scout_recall` per item to check project memory.

```
### [source] Title or repo/name

> ⭐ X stars · 🍴 Y forks · Language · License · Last push: YYYY-MM-DD
  (GitHub items only — omit this entire block for non-GitHub items)

**Tech relevance:** one sentence on why the tech world cares
**{project} relevance:** why this matters to {project} — or "N/A — [reason]"
**Where in {project}:** which module, layer, or component — or "N/A"
**Currently used:** what {project} uses today for this (from recall) — or "unknown"
**Previously used:** prior approach (from recall) — or "unknown"
**Competitors:** 2–4 main alternatives in the same space
**Outperforms by:** how and how much — or "unclear"
**Complexity:** low / medium / high — ~N specs, ~N days
**Worth your time?** yes / no + the decisive reason in one line
**Cycle candidate:** [ ] yes — one-line pitch  OR  [-] no — one-line reason
```

### Tier 2 card — light

```
### [source] Title

**What happened:** one sentence
**Tech relevance:** one sentence
**{project} relevance:** "N/A — [why it does not apply]"  OR  one sentence if it applies
```

### Report wrapper

```
# Scout Report — {today}
**Active project:** {project}

## Tier 1 — Actionable
[Tier 1 cards, or (none)]

## Tier 2 — Good to Know
[Tier 2 cards]

---
**What to dig into today:** 2–3 sentence paragraph on the highest-signal Tier 1 items
and why they are worth time today specifically. Omit if Tier 1 is (none).
```

### Exact instruction string

```python
_INTEGRATE_INSTRUCTION = (
    "You are Scout's integration stage. You receive a classified shortlist of items "
    "as your input message above.\n\n"
    "CRITICAL: Only include items from the shortlist above. "
    "Do not add, invent, or infer items from your training knowledge.\n\n"
    "Step 1 — Project context (do this FIRST, before analyzing any item):\n"
    "Call scout_recall with the query: "
    "'{project} current stack implementation goals and recent changes'\n"
    "If scout_recall returns empty results, write 'unknown' for all "
    "'Currently used' and 'Previously used' fields. Do not infer from training knowledge.\n\n"
    "Step 2 — For each Tier 1 item, call scout_recall with a short targeted query "
    "(e.g. the tool or technique name) to check project memory. "
    "Use the result for 'Currently used' and 'Previously used' fields.\n\n"
    "Step 3 — Write the morning digest:\n\n"
    "# Scout Report — {today}\n"
    "**Active project:** {project}\n\n"
    "## Tier 1 — Actionable\n\n"
    "If Tier 1 contains only '(none)', write '(none)' and no cards.\n"
    "Otherwise for each Tier 1 item:\n"
    "### [source] Title\n"
    "> ⭐ X stars · 🍴 Y forks · Language · License · Last push: YYYY-MM-DD\n"
    "  (GitHub items only — omit this entire block for non-GitHub items)\n\n"
    "**Tech relevance:** one sentence why the tech world cares\n"
    "**{project} relevance:** why this matters to {project} — or 'N/A — [reason]'\n"
    "**Where in {project}:** which module/layer/component — or 'N/A'\n"
    "**Currently used:** from recall — or 'unknown'\n"
    "**Previously used:** from recall — or 'unknown'\n"
    "**Competitors:** 2–4 main alternatives\n"
    "**Outperforms by:** how and how much — or 'unclear'\n"
    "**Complexity:** low/medium/high — ~N specs, ~N days\n"
    "**Worth your time?** yes/no + decisive reason\n"
    "**Cycle candidate:** [ ] yes — one-line pitch  OR  [-] no — one-line reason\n\n"
    "## Tier 2 — Good to Know\n\n"
    "For each Tier 2 item:\n"
    "### [source] Title\n"
    "**What happened:** one sentence\n"
    "**Tech relevance:** one sentence\n"
    "**{project} relevance:** 'N/A — [reason]' or one sentence if it applies\n\n"
    "---\n"
    "**What to dig into today:** 2–3 sentences on highest-signal Tier 1 items "
    "and why they are worth time today. Omit this paragraph if Tier 1 is (none)."
)
```

---

## §5 — `_run_once_async` — inject `{project}`

`_resolve_context(None, None)` is already imported at the top of `scout.py`
(`from kage.context import _resolve_context`). Reuse it here. Add two lines
before `session_service.create_session`:

```python
async def _run_once_async(runner: InMemoryRunner, corpus: str) -> str:
    _, project, _ = _resolve_context(None, None)   # sync file read, safe in CLI batch
    session = await runner.session_service.create_session(
        app_name="kage-scout", user_id="scout",
        state={
            "today": str(_dt.date.today()),
            "project": project or "kage",
        },
    )
    # rest of function unchanged
```

`_resolve_context` reads `~/.kage/state.json` — a synchronous file read, negligible
in a CLI batch context. If no active project is set, it returns `None`; the `or "kage"`
fallback ensures `{project}` is never an empty string in the instruction.

---

## §6 — Test plan

### Existing tests to update

Actual test names from `tests/test_scout.py` (verified against file):

| Test | What to change |
|---|---|
| `test_fetch_github_auth_header` (line ~28) | Also assert `forks`, `language`, `license`, `pushed_at` present in the returned dict with correct types |
| `test_corpus_round_robin_order` (line ~108) | Fix the source-extraction line: filter to only lines that start with `[` before splitting on `[`/`]`; otherwise the stats line (`  ⭐ ...`) causes `IndexError` |
| `test_corpus_round_robin_interleaves` (line ~130) | Same filter fix as above |
| `test_run_once_async_returns_state` (line ~381) | Add `monkeypatch.setattr(scout, "_resolve_context", lambda *a: ("personal", "kage", None))` — without this the test reads real `~/.kage/state.json` and becomes environment-dependent |

**Note:** There are no existing instruction-string tests in `test_scout.py`.
The two instruction rows from v1 spec are removed — all instruction tests below are new.

### New tests to add

| Test | What it checks |
|---|---|
| `test_fetch_github_stats_fields` | mock API response with `forks_count=5`, `language="Python"`, `license={"spdx_id":"MIT"}`, `pushed_at="2026-06-01T00:00:00Z"`; assert returned dict has `forks=5`, `language="Python"`, `license="MIT"`, `pushed_at="2026-06-01"` |
| `test_fetch_github_stats_null_license` | mock response with `license=None`; assert `license=""` (not `AttributeError`) |
| `test_corpus_github_stats_line` | build one github item with known stats; assert corpus string contains `⭐` and `🍴` on the second line |
| `test_corpus_github_omits_empty_language` | item with `language=""`; assert `· ·` does not appear in corpus (no double separator) |
| `test_corpus_github_cap_atomicity` | set `_CORPUS_CHAR_CAP` to a value that fits the first line but not both lines; assert the entire item is skipped (neither line appears) |
| `test_run_once_injects_project` | monkeypatch `scout._resolve_context` to return `("personal", "hsi", None)`; use a `FakeRunner` with both `create_session` and `get_session` as async methods (reference pattern: `test_run_once_async_returns_state`); assert `state["project"] == "hsi"` in the `create_session` call |
| `test_run_once_project_fallback` | monkeypatch `scout._resolve_context` to return `("personal", None, None)`; assert `state["project"] == "kage"` |
| `test_broad_instruction_has_grounding_rule` | assert "Only classify items explicitly present in the corpus" in `_BROAD_INSTRUCTION` |
| `test_broad_instruction_has_tier_format` | assert "## Tier 1 — Actionable" and "## Tier 2 — Good to Know" in `_BROAD_INSTRUCTION` |
| `test_integrate_instruction_has_project_variable` | assert "{project}" in `_INTEGRATE_INSTRUCTION` |
| `test_integrate_instruction_has_step1` | assert "Step 1" and "scout_recall" in `_INTEGRATE_INSTRUCTION` |
| `test_integrate_instruction_handles_none_tier` | assert "only '(none)'" in `_INTEGRATE_INSTRUCTION` |

---

## Implementation steps (for Qwen3)

Each step is a unified diff only — no full-file rewrites (Ollama context limit).
Confirm each diff before proceeding to the next step.

```
Step 1  _fetch_github dict — add forks/language/license/pushed_at (§1)
Step 2  _corpus — GitHub two-line format + omission algorithm + cap=100k (§2)
Step 3  _BROAD_INSTRUCTION — replace constant (§3)
Step 4  _INTEGRATE_INSTRUCTION — replace constant (§4)
Step 5  _run_once_async — add _resolve_context + project in state (§5)
Step 6  Tests — update 4 existing + add 12 new (§6)
```

---

## Security / egress checklist

- `{project}` is the project name string only (e.g. "kage", "hsi") — no memory content
  is injected into the instruction. Memory content only enters via `scout_recall`, which
  is already gated by `_disclosure_gate`. No new egress surface.
- `_resolve_context` reads `~/.kage/state.json` — local file, no network call.
- GitHub stats fields are public API data — no auth required, no personal data.
- Project name going to cloud provider: a plain string like "kage" or "hsi" — not PII,
  not sensitive. Acceptable under the existing egress model.

---

*v3 — two cold reviews done (independent subagents, 2026-06-25). Cleared for implementation.*
