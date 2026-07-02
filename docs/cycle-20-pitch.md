# Cycle 20 — Monitor Cadence Split + Scout Deep Fetch (v0.21.0)

*Status: SHIPPED v0.20.0 (`c1d7644`) — pitch v3 (2026-06-29). Cold reviews: 2.*
*Built per the 7-step dev workflow: plan cloud → write local (Qwen3) → review cloud → plan tests cloud → write tests local → review tests cloud → run tests local.*

> **v2 changelog (cold review #1):**
> - B1: `_run_once_async` state-key assumption documented; `run()` reads state directly from runner.
> - B2: Reddit body addition breaks `test_fetch_reddit_prefilters_body` — Step 1 now says to update it.
> - B3: Step 4 now explicitly keeps `_generate_plist` unchanged (CLI + test backward compat).
> - B4: CLI `kage monitor observe`/`digest` and updated `install`/`uninstall` added to Step 5.
> - W2 (ScoutBroad URL hallucination): changed to index-based shortlisting — corpus is numbered, ScoutBroad outputs indices.
> - W3: D7 now explicitly keeps `build_pipeline` unchanged (existing tests pass unchanged).
> - W5: Empty observations case specified — sends `"No observations recorded today."`.
> - M4: `build_monitor_digest` correctly described as Workflow, not bare LlmAgent.
> - M2: `_ENRICHED_CORPUS_CAP = 80_000` named constant added.

> **v3 changelog (cold review #2):**
> - B1–B4: All new runner-using functions used wrong ADK session API. Corrected all code blocks to match `_run_once_impl` (monitor.py:483–511): `runner.session_service` (no underscore), `asyncio.run()` on all async calls, `create_session` before `run()`, `new_message=genai_types.Content(...)` not `message=str`.
> - B5: `_get_paths()` does not exist in monitor.py. Step 5 now shows the correct inline pattern from the existing `monitor_install` (`shutil.which("uv")` + `_resolve_repo_root()`).
> - B6: `kage scout bootstrap` fell through to cloud Stage 3. Fixed: early-exit on `mode in ("dry-run", "bootstrap")`.
> - B7: Renaming `_BROAD_INSTRUCTION` to index-shortlisting breaks `build_pipeline(cloud=True)` which still uses the old classify semantics. Fix: new variable `_BROAD_SHORTLIST_INSTRUCTION` for the shortlist task; original `_BROAD_INSTRUCTION` kept for `build_pipeline` backward compat.
> - W1: Test name was inconsistent between Step 1 text and test table. Unified as `test_fetch_reddit_prefilters_body` (keep existing name, no rename).
> - W3: `test_run_two_stage_pipeline` now specifies the FakeRunner/FakeSession mocking pattern.
> - Minor D2: Corrected "all of today's records" → "most recent ~60 runs (last ~5 hours)" to match the 50k cap reality.
> - Added `test_monitor_install_creates_both_plists` to test plan (install logic is non-trivial).

---

## Two items, one cycle

This cycle fixes two independent problems in the agent pipeline:

**Item 1 — Monitor cadence split:** MonitorObserve (local Qwen3) and MonitorDigest (cloud) run as one coupled Workflow every 5 minutes. Cloud synthesis fires 288×/day on data that barely changes between runs. Split into two independent schedules: observe runs 24/7 (local, no cost), digest runs once per day (cloud, pattern recognition across the accumulated data).

**Item 2 — Scout deep fetch:** ScoutBroad classifies 30 items into Tier 1/Tier 2 on headline text alone (200-char snippets). Headlines are unreliable — HN is cryptic, YouTube is clickbait, GitHub repos have marketing copy. Add a two-stage pipeline: ScoutBroad shortlists candidates by index number, Python fetches full content (Jina Reader for articles, GitHub API for READMEs, body field for Reddit), ScoutIntegrate classifies on actual content.

Both items are additive — no schema changes, no breaking API changes. Existing `kage monitor run` and `kage scout run` behavior is preserved.

---

## North stars

> **Item 1:** MonitorObserve sees everything, always. MonitorDigest synthesises once.

> **Item 2:** Scout judges on content, not headlines.

---

## What this cycle IS / IS NOT

**IS:**
- Monitor: two separate launchd plists, two separate CLI commands, two separate build functions
- Monitor: `_observe_impl` writes structured observation records; `_digest_impl` reads accumulated records and synthesises
- Scout: two-stage pipeline — index-based shortlist stage on headlines, then full-content fetch, then integrate stage
- Scout: Jina Reader for articles/blogs (HN, RSS links), GitHub API README for repos, body field for Reddit
- Scout: YouTube seam left open (returns `""` — yt-dlp wires in post-Kaggle without rework)

**IS NOT:**
- Not a new agent or new ADK Workflow type
- Not a schema change (no new tables, no ALTER TABLE)
- Not a change to Scout's `scout_recall` disclosure gate (unchanged)
- Not a change to Monitor's tool set (same 10 tools)
- Not YouTube transcript fetching (seam only, yt-dlp deferred)
- Not feedparser migration (RSS stays stdlib xml — separate minor fix if needed)

---

## Item 1 — Monitor Cadence Split

### Key facts from reading the code

1. **`build_monitor(cfg)` at [monitor.py:444](src/kage/monitor.py#L444)** returns a single `Workflow` with edges `[(START, observe_agent), (observe_agent, digest_agent)]`. There is no way to run only MonitorObserve without MonitorDigest in the current structure.

2. **`_run_once_impl(cfg)` at [monitor.py:483](src/kage/monitor.py#L483)** — the canonical ADK runner pattern in this codebase (lines 483–511). All new runner-using functions must follow this exactly:
   ```python
   runner = InMemoryRunner(node=agent, app_name="...")
   content = genai_types.Content(role="user", parts=[genai_types.Part(text="...")])
   session = asyncio.run(runner.session_service.create_session(app_name="...", user_id="kage"))
   list(runner.run(user_id="kage", session_id=session.id, new_message=content))
   session = asyncio.run(runner.session_service.get_session(
       app_name="...", user_id="kage", session_id=session.id))
   result = (session.state.get("key") or "") if session else ""
   ```
   Key details: `runner.session_service` (no underscore); `create_session` before `run()`; `new_message=genai_types.Content(...)` not `message=str`; `asyncio.run()` on all async calls.

3. **`_generate_plist()` at [monitor.py:364](src/kage/monitor.py#L364)** — **kept unchanged**. `cli.py:1868` and `tests/test_monitor.py:14` both import/call it directly.

4. **`observe_agent` in `build_monitor` currently has NO `output_key`** (lines 457–462). The new `build_monitor_observe` must add `output_key="monitor_findings"` to its `observe_agent`. Original `build_monitor` stays untouched.

5. **MonitorDigest's instruction** ([monitor.py:406](src/kage/monitor.py#L406)) already says "You receive MonitorObserve's structured findings." It is designed to work from pre-computed text input — no Workflow edge needed.

6. **Existing `monitor_install` in cli.py (line 1853)** resolves paths inline:
   ```python
   import shutil as _shutil
   from kage.arms import _resolve_repo_root
   uv_path = _shutil.which("uv")
   project_root = _resolve_repo_root()
   home = str(Path.home())
   ```
   No helper function exists; the new `monitor_install` must use this same inline pattern.

### Architecture after split

```
  kage monitor observe  ─── launchd plist A, StartInterval=300 ───►
                             build_monitor_observe(cfg)
                             MonitorObserve only (local Qwen3)
                             output_key="monitor_findings"
                             all 10 tools available
                             output: structured JSON record
                             appended to ~/.kage/monitor/observations-YYYY-MM-DD.jsonl
                             state.json updated (latest snapshot)

  kage monitor digest   ─── launchd plist B, StartCalendarInterval 07:00 ───►
                             reads observations-YYYY-MM-DD.jsonl
                             concatenates most recent ~60 runs into digest_input
                             build_monitor_digest(cfg)
                             Workflow with MonitorDigest only (cloud, _pii_seam)
                             output: YYYY-MM-DD.md
```

### Design decisions

**D1 — Observations file format**

Each observe run appends one JSON line to `~/.kage/monitor/observations-YYYY-MM-DD.jsonl`:
```json
{"ts": "2026-06-29T07:05:12+05:30", "findings": "<MonitorObserve output text>"}
```

MonitorDigest reads all lines, extracts `findings`, concatenates with `\n---\n` separator, feeds as its user message. Simple, human-readable, no schema change.

**D2 — digest_input construction**

`_digest_impl` assembles:
```
Observation run 1 (07:00): <findings text>
---
Observation run 2 (07:05): <findings text>
---
...
```
Capped at 50,000 chars — this covers the most recent ~60 runs (~last 5 hours at 5-min intervals). If cap is exceeded, keep most-recent records that fit. If JSONL file is missing or empty, send literal `"No observations recorded today."` as the user message — MonitorDigest writes a brief digest noting no data.

**D3 — Backward compatibility**

Keep `kage monitor run` as a convenience alias: runs `_observe_impl` then `_digest_impl` in sequence. The launchd split is the new default scheduling.

**D4 — plist B uses StartCalendarInterval, not StartInterval**

`StartCalendarInterval` fires at a fixed wall-clock time. `StartInterval` drifts over time. For a daily digest ready before you sit down, `StartCalendarInterval` is correct.

```xml
<key>StartCalendarInterval</key>
<dict>
  <key>Hour</key><integer>7</integer>
  <key>Minute</key><integer>0</integer>
</dict>
```

**D5 — `kage monitor install` installs both plists**

Two plist files:
- `~/.config/kage/dev.kage.monitor.observe.plist`
- `~/.config/kage/dev.kage.monitor.digest.plist`

On install: write both plists, bootout any previously installed single-plist version (`dev.kage.monitor.plist`) if it exists, bootstrap both new ones. On uninstall: bootout and remove both.

### Implementation steps

```
Step 1  monitor.py: build_monitor_observe(cfg)
        Copy observe_agent definition from build_monitor(), add output_key="monitor_findings".
        Wrap in Workflow(edges=[(START, observe_agent)]).
        Do NOT copy digest_agent.

        build_monitor_digest(cfg)
        Copy digest_agent definition from build_monitor() (with _pii_seam, output_key="monitor_digest").
        Wrap in Workflow(edges=[(START, digest_agent)]).
        No tools.

        build_monitor(cfg) — UNCHANGED
        _generate_plist() — UNCHANGED

Step 2  monitor.py: _observe_impl(cfg)
        Follow _run_once_impl pattern exactly (lines 483-511):

        from google.adk.runners import InMemoryRunner
        import google.genai.types as genai_types

        runner = InMemoryRunner(node=build_monitor_observe(cfg), app_name="kage-monitor-obs")
        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text="Run a monitoring observation pass.")],
        )
        session = asyncio.run(
            runner.session_service.create_session(app_name="kage-monitor-obs", user_id="kage")
        )
        list(runner.run(user_id="kage", session_id=session.id, new_message=content))
        session = asyncio.run(runner.session_service.get_session(
            app_name="kage-monitor-obs", user_id="kage", session_id=session.id
        ))
        findings = (session.state.get("monitor_findings") or "") if session else ""

        record = {"ts": datetime.now().astimezone().isoformat(), "findings": findings}
        monitor_dir = Path(runtime.config.home) / "monitor"
        monitor_dir.mkdir(parents=True, exist_ok=True)
        obs_path = monitor_dir / f"observations-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with obs_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        _write_state_json({"last_observe": record["ts"], "latest_findings": findings[:500]})

Step 3  monitor.py: _digest_impl(cfg)
        from google.adk.runners import InMemoryRunner
        import google.genai.types as genai_types

        monitor_dir = Path(runtime.config.home) / "monitor"
        obs_path = monitor_dir / f"observations-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        if not obs_path.exists():
            digest_input = "No observations recorded today."
        else:
            lines = obs_path.read_text().splitlines()
            records = []
            for line in lines:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            if not records:
                digest_input = "No observations recorded today."
            else:
                # most-recent-first, cap at 50k chars
                parts = []
                total = 0
                for i, r in enumerate(reversed(records)):
                    chunk = f"Observation run {len(records)-i} ({r['ts']}): {r['findings']}\n---\n"
                    if total + len(chunk) > 50_000:
                        break
                    parts.append(chunk)
                    total += len(chunk)
                digest_input = "".join(reversed(parts)) or "No observations recorded today."

        runner = InMemoryRunner(node=build_monitor_digest(cfg), app_name="kage-monitor-dig")
        content = genai_types.Content(
            role="user", parts=[genai_types.Part(text=digest_input)]
        )
        session = asyncio.run(
            runner.session_service.create_session(app_name="kage-monitor-dig", user_id="kage")
        )
        list(runner.run(user_id="kage", session_id=session.id, new_message=content))
        session = asyncio.run(runner.session_service.get_session(
            app_name="kage-monitor-dig", user_id="kage", session_id=session.id
        ))
        digest = (session.state.get("monitor_digest") or "") if session else ""

        today = datetime.now().strftime("%Y-%m-%d")
        (monitor_dir / f"{today}.md").write_text(digest)
        _write_state_json({
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "digest_preview": digest[:200] if digest else "",
        })

Step 4  monitor.py: _generate_observe_plist(uv_path, project_root, home) → str
        Copy _generate_plist(), change:
          - Label: dev.kage.monitor.observe
          - ProgramArguments last two args: "monitor", "observe"
          - Keep StartInterval=300

        _generate_digest_plist(uv_path, project_root, home) → str
        Copy _generate_plist(), change:
          - Label: dev.kage.monitor.digest
          - ProgramArguments last two args: "monitor", "digest"
          - Replace StartInterval block with StartCalendarInterval (Hour=7, Minute=0)

Step 5  cli.py: new subcommands and updated install/uninstall

        @_monitor_app.command("observe")
        def monitor_observe():
            from kage import monitor as _mon
            _mon._observe_impl(runtime.config.data)

        @_monitor_app.command("digest")
        def monitor_digest():
            from kage import monitor as _mon
            _mon._digest_impl(runtime.config.data)

        Update monitor_run() body:
            _mon._observe_impl(runtime.config.data)
            _mon._digest_impl(runtime.config.data)
        (remove _run_once_impl call, keep function decorator unchanged)

        Replace monitor_install() body (keep decorator):
            import shutil as _shutil
            from kage.arms import _resolve_repo_root
            from kage import monitor as _mon
            uv_path = _shutil.which("uv")
            if not uv_path:
                typer.echo("Error: uv not found on PATH.", err=True); raise typer.Exit(1)
            project_root = _resolve_repo_root()
            home = str(Path.home())
            log_dir = Path.home() / ".kage" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            import subprocess as _sp, os as _os
            uid = f"gui/{_os.getuid()}"
            for gen_fn, label in [
                (_mon._generate_observe_plist, "dev.kage.monitor.observe"),
                (_mon._generate_digest_plist,  "dev.kage.monitor.digest"),
            ]:
                plist_path = Path.home() / ".config" / "kage" / f"{label}.plist"
                plist_path.parent.mkdir(parents=True, exist_ok=True)
                plist_path.write_text(gen_fn(uv_path, project_root, home))
                _sp.run(["launchctl", "bootout", uid, str(plist_path)], check=False)
                _sp.run(["launchctl", "bootstrap", uid, str(plist_path)], check=True)
            # bootout old single-plist if present
            old = Path.home() / ".config" / "kage" / "dev.kage.monitor.plist"
            if old.exists():
                _sp.run(["launchctl", "bootout", uid, str(old)], check=False)
            typer.echo(f"Monitor installed (observe + digest). Logs: {log_dir}")

        Replace monitor_uninstall() body (keep decorator):
            import subprocess as _sp, os as _os
            uid = f"gui/{_os.getuid()}"
            for label in ["dev.kage.monitor.observe", "dev.kage.monitor.digest"]:
                plist_path = Path.home() / ".config" / "kage" / f"{label}.plist"
                _sp.run(["launchctl", "bootout", uid, str(plist_path)], check=False)
                plist_path.unlink(missing_ok=True)
            typer.echo("Monitor uninstalled.")
```

---

## Item 2 — Scout Deep Fetch

### Key facts from reading the code

1. **`_BROAD_INSTRUCTION` at [scout.py:31](src/kage/scout.py#L31)** currently asks ScoutBroad to classify into Tier 1/Tier 2. **This variable is kept unchanged** — `build_pipeline(cfg, cloud=True)` uses it and must continue to produce Tier 1/2 output for backward compat. The new shortlist behavior uses a new variable `_BROAD_SHORTLIST_INSTRUCTION` (see D1).

2. **`_INTEGRATE_INSTRUCTION` at [scout.py:59](src/kage/scout.py#L59)** — updated to handle FULL CONTENT + HEADLINES sections.

3. **`_fetch_reddit` at [scout.py:143](src/kage/scout.py#L143)** currently stores `"snippet": ""` (the 40k ctx fix). Store `"body": d.get("selftext", "")[:3000]` alongside existing fields. `_corpus()` never reads `"body"` so shallow corpus is unaffected.

   **UPDATE TEST `test_fetch_reddit_prefilters_body` (test_scout.py) — keep the existing test name, split into two assertions:**
   ```python
   # body IS stored in the item dict
   assert results[0].get("body") is not None
   # body does NOT appear in the shallow corpus
   assert "SECRETBODY" not in _corpus(results)
   ```

4. **`_fetch_github` at [scout.py:117](src/kage/scout.py#L117)** stores `"title": item["full_name"]` (format: `"owner/repo"`). GitHub API README: `https://api.github.com/repos/{title}/readme` → `{"content": "<base64>", "encoding": "base64"}`.

5. **`build_pipeline(cfg, *, cloud: bool)` at [scout.py:294](src/kage/scout.py#L294)** — **kept exactly as-is**. Tests at `test_scout.py:215–240` call it directly and must pass unchanged.

6. **`_corpus()` never includes URLs** — items are formatted as `[source] title — snippet`. ScoutBroad cannot reliably emit URLs it was never shown. Stage 1 corpus is numbered 1–N inline in `run()`. ScoutBroad returns item numbers (not URLs) in `_BROAD_SHORTLIST_INSTRUCTION`.

7. **ADK runner pattern for scout** — same as monitor (Key Fact 2 above). The existing `_run_once_async` in scout.py uses the same `runner.session_service` / `asyncio.run()` / `create_session` pattern. All new runner calls in `run()` must follow it.

### Architecture

```
  STAGE 1 — Wide shallow
  ──────────────────────────────────────────────────────
  fetch(cfg) → items[] (30 items, headlines + snippets)
  Numbered corpus (inline in run()):
    "1. [hn] Title — snippet\n2. [arxiv] Title — snippet\n..."
  build_broad_pipeline(cfg) → ScoutBroad (local Qwen3)
    instruction: _BROAD_SHORTLIST_INSTRUCTION
    output_key="shortlist_indices"
  → shortlist_text: "3. ambiguous headline, worth reading\n7. GitHub ..."

  STAGE 2 — Narrow deep fetch (new)
  ──────────────────────────────────────────────────────
  _parse_shortlist_indices(shortlist_text, items) → list[dict]
    Regex: r"^(\d+)\." per line; look up items[N-1]; bounds-check; deduplicate; max 8
    Empty list = graceful degrade (Stage 3 runs on shallow corpus)
  _fetch_full(item) → str
    github  → GitHub API /repos/{title}/readme → base64.b64decode → [:3000]
    reddit  → item.get("body", "")  (no HTTP call)
    youtube → ""  (seam open, yt-dlp post-Kaggle)
    arxiv   → _http._get(f"https://r.jina.ai/{url}", ...)[:2000]
    others  → _http._get(f"https://r.jina.ai/{url}", ...)[:5000]
    Any exception → ""
  _corpus_enriched(items, shortlisted, full_map) → str
    _ENRICHED_CORPUS_CAP = 80_000
    "=== FULL CONTENT ===\n" + shortlisted items with full text
    "=== HEADLINES ===\n" + _corpus(remaining items)
    Total capped at _ENRICHED_CORPUS_CAP

  STAGE 3 — Cloud integrate on real content
  ──────────────────────────────────────────────────────
  build_integrate_pipeline(cfg) → ScoutIntegrate (cloud)
    instruction: _INTEGRATE_INSTRUCTION (updated)
    tools=[scout_recall], before_model_callback=_pii_seam
    output_key="report"
  → morning report (Tier 1/2 classification on actual content)
```

### Design decisions

**D1 — Two broad instructions: classify vs shortlist**

`_BROAD_INSTRUCTION` (existing, kept for `build_pipeline` backward compat):
- Current Tier 1/Tier 2 classification. Do not change.

`_BROAD_SHORTLIST_INSTRUCTION` (new variable, used only by `build_broad_pipeline`):
```
You are Scout's shortlisting stage. You receive a numbered list of recent items (titles and snippets).

Your ONLY job: identify the 5-8 items most worth reading in full — items where the headline
is ambiguous, potentially high-signal, or where the snippet suggests depth worth exploring.

Do NOT classify into Tier 1/Tier 2. Do NOT analyze. Just pick item numbers.

Output format — exactly one line per chosen item:
N. one sentence: why this item is worth reading in full

Where N is the item's number from the list above (integer only, e.g. "3." or "15.").
If fewer than 5 items are worth investigating, output only those.
Maximum 8 items.
```

**D2 — Why indices, not URLs**

`_corpus()` shows items as `[source] title — snippet` — no URLs. Qwen3 cannot reliably emit a URL it was never shown. Indices (1–30) are visible, bounded, and unambiguous. `_parse_shortlist_indices` uses a trivial regex on leading integers.

**D3 — Full content cap per item**

Jina Reader: 5,000 chars (2,000 for arXiv). GitHub README: 3,000 chars. Reddit body: 3,000 chars (capped at `_fetch_reddit`). Total enriched corpus cap: `_ENRICHED_CORPUS_CAP = 80_000`.

**D4 — Jina Reader fallback**

`_fetch_full` catches ALL exceptions → `""`. Item falls through to HEADLINES section. If ALL shortlisted items fail, `_corpus_enriched` returns a FULL CONTENT section with no entries and a full HEADLINES section — ScoutIntegrate still classifies from headlines. Never crash.

**D5 — arXiv handled by separate cap, not a separate code branch**

`_fetch_full` checks `source == "arxiv"` inline for cap selection. One `if`, no new branch.

**D6 — `_parse_shortlist_indices` implementation**

```python
def _parse_shortlist_indices(text: str, items: list[dict]) -> list[dict]:
    chosen, seen = [], set()
    for line in text.splitlines():
        m = re.match(r"^(\d+)\.", line.strip())
        if not m:
            continue
        idx = int(m.group(1)) - 1   # 1-indexed → 0-indexed
        if 0 <= idx < len(items) and idx not in seen:
            chosen.append(items[idx])
            seen.add(idx)
        if len(chosen) >= 8:
            break
    return chosen
```

**D7 — `build_pipeline` unchanged; `_BROAD_INSTRUCTION` unchanged**

`build_pipeline(cfg, *, cloud: bool)` at scout.py:294 stays exactly as-is. It uses `_BROAD_INSTRUCTION` (Tier 1/2 classify). The new `build_broad_pipeline` uses `_BROAD_SHORTLIST_INSTRUCTION`. These are two separate variables, not a rename.

### Implementation steps

```
Step 1  scout.py: update _fetch_reddit to store body field
        In the per-post loop, add: "body": d.get("selftext", "")[:3000]
        _corpus() is unchanged — does not read "body".
        UPDATE TEST test_fetch_reddit_prefilters_body: split into two assertions (see Key Fact 3).

Step 2  scout.py: add _BROAD_SHORTLIST_INSTRUCTION (new module-level constant, after _BROAD_INSTRUCTION)
        Content: D1 above.
        _BROAD_INSTRUCTION — DO NOT MODIFY.
        _parse_shortlist_indices(text, items) → list[dict]: D6 above.
        build_broad_pipeline(cfg) → Workflow:
          broad = LlmAgent(name="ScoutBroad",
                           model=_litellm_target(cfg, cloud=False),
                           instruction=_BROAD_SHORTLIST_INSTRUCTION,
                           output_key="shortlist_indices")
          return Workflow(name="kage-scout-broad", edges=[(START, broad)])

Step 3  scout.py: _fetch_full(item) → str
        source = item.get("source", "")
        url    = item.get("url", "")
        try:
            if source == "github":
                raw = _http._get(
                    f"https://api.github.com/repos/{item['title']}/readme",
                    headers={**_UA, "Accept": "application/vnd.github+json"},
                    timeout=10,
                )
                return base64.b64decode(json.loads(raw)["content"]).decode()[:3000]
            if source == "reddit":
                return item.get("body", "")
            if source == "youtube":
                return ""   # ponytail: seam open — yt-dlp wires here post-July 6
            cap = 2000 if source == "arxiv" else 5000
            return _http._get(f"https://r.jina.ai/{url}", headers=_UA, timeout=15)[:cap]
        except Exception:
            return ""

Step 4  scout.py: _corpus_enriched(items, shortlisted, full_map) → str
        _ENRICHED_CORPUS_CAP = 80_000   # add near _CORPUS_CHAR_CAP at top of file

        full_section = "=== FULL CONTENT ===\n"
        for it in shortlisted:
            content = full_map.get(id(it), "")
            full_section += f"[{it['source']}] {it['title']}\n{content}\n\n"

        remaining = [it for it in items if it not in shortlisted]
        headlines_section = "=== HEADLINES ===\n" + _corpus(remaining)

        combined = full_section + headlines_section
        return combined[:_ENRICHED_CORPUS_CAP]

Step 5  scout.py: _INTEGRATE_INSTRUCTION update
        Prepend to the existing instruction text:
        "You receive a corpus in two sections:
         === FULL CONTENT === items where the full article or README was fetched.
         Judge these on actual content, not just the headline.
         === HEADLINES === items with title and snippet only. Judge from the snippet.
         Classify ALL items (both sections) into Tier 1 or Tier 2."
        Rest of instruction (project context recall, report format, scout_recall usage) unchanged.

        build_integrate_pipeline(cfg) → Workflow:
          integrate = LlmAgent(name="ScoutIntegrate",
                               model=_litellm_target(cfg, cloud=True),
                               instruction=_INTEGRATE_INSTRUCTION,
                               tools=[scout_recall],
                               before_model_callback=_pii_seam,
                               output_key="report")
          return Workflow(name="kage-scout-int", edges=[(START, integrate)])

Step 6  scout.py: run(mode) updated — call new pipeline functions, follow _run_once_impl ADK pattern

        import asyncio
        from google.adk.runners import InMemoryRunner
        import google.genai.types as genai_types

        items = [it for it in fetch(cfg) if _key(it) not in cache]

        # Stage 1: numbered shallow corpus → shortlist indices (local Qwen3)
        numbered = "\n".join(
            f"{i+1}. [{it['source']}] {it['title']} — {it.get('snippet','')}"
            for i, it in enumerate(items)
        )
        runner1 = InMemoryRunner(node=build_broad_pipeline(cfg), app_name="kage-scout-broad")
        content1 = genai_types.Content(role="user", parts=[genai_types.Part(text=numbered)])
        sess1 = asyncio.run(runner1.session_service.create_session(
            app_name="kage-scout-broad", user_id="kage"))
        list(runner1.run(user_id="kage", session_id=sess1.id, new_message=content1))
        sess1 = asyncio.run(runner1.session_service.get_session(
            app_name="kage-scout-broad", user_id="kage", session_id=sess1.id))
        shortlist_text = (sess1.state.get("shortlist_indices") or "") if sess1 else ""

        # dry-run and bootstrap stop here — no cloud cost
        if mode in ("dry-run", "bootstrap"):
            if mode == "bootstrap":
                update_cache(items)     # seed seen cache (same as current bootstrap behavior)
            return shortlist_text

        # Stage 2: deep fetch for shortlisted items
        shortlisted = _parse_shortlist_indices(shortlist_text, items)
        full_map = {id(it): _fetch_full(it) for it in shortlisted}

        # Stage 3: integrate on enriched corpus (cloud)
        enriched = _corpus_enriched(items, shortlisted, full_map)
        runner2 = InMemoryRunner(node=build_integrate_pipeline(cfg), app_name="kage-scout-int")
        content2 = genai_types.Content(role="user", parts=[genai_types.Part(text=enriched)])
        sess2 = asyncio.run(runner2.session_service.create_session(
            app_name="kage-scout-int", user_id="kage"))
        list(runner2.run(user_id="kage", session_id=sess2.id, new_message=content2))
        sess2 = asyncio.run(runner2.session_service.get_session(
            app_name="kage-scout-int", user_id="kage", session_id=sess2.id))
        report = (sess2.state.get("report") or "") if sess2 else ""

        # rest unchanged: write_report, update_cache, token_log, scout_runs insert
```

---

## Test plan

### Item 1 — Monitor cadence split

New/updated tests in `tests/test_monitor.py`:

| Test | What it checks |
|---|---|
| `test_observe_impl_writes_observations_jsonl` | `_observe_impl` appends valid JSON line to YYYY-MM-DD.jsonl |
| `test_observe_impl_updates_state_json` | state.json gets `last_observe` and `latest_findings` |
| `test_digest_impl_reads_observations` | `_digest_impl` reads JSONL, assembles digest_input, passes to runner (mock runner) |
| `test_digest_impl_caps_at_50k` | >50k chars of JSONL → most-recent records that fit, no crash |
| `test_digest_impl_empty_observations` | missing JSONL → digest runner receives `"No observations recorded today."` |
| `test_digest_impl_writes_md_file` | `_digest_impl` writes YYYY-MM-DD.md to monitor dir |
| `test_build_monitor_observe_single_node` | graph has MonitorObserve, NOT MonitorDigest |
| `test_build_monitor_digest_single_node` | graph has MonitorDigest, NOT MonitorObserve |
| `test_generate_observe_plist_start_interval` | observe plist has StartInterval=300 and `"observe"` in ProgramArguments |
| `test_generate_digest_plist_calendar_interval` | digest plist has StartCalendarInterval Hour=7 Minute=0 and `"digest"` in ProgramArguments |
| `test_generate_plist_unchanged` | existing `_generate_plist()` still returns StartInterval=300 with `"run"` in ProgramArguments |
| `test_monitor_run_calls_both` | `monitor_run()` calls both `_observe_impl` and `_digest_impl` (mock both) |
| `test_monitor_install_creates_both_plists` | mock `subprocess.run`; assert both plist files written; assert bootout+bootstrap called for each label; assert old single-plist booted out if present |

### Item 2 — Scout deep fetch

New/updated tests in `tests/test_scout.py`:

| Test | What it checks |
|---|---|
| `test_fetch_reddit_prefilters_body` (updated) | body IS in item dict; `_corpus(results)` does NOT contain body text |
| `test_parse_shortlist_indices_valid` | `"3. reason\n7. reason"` with 10-item list → `[items[2], items[6]]` |
| `test_parse_shortlist_indices_out_of_bounds` | index 99 with 10 items → skipped, no crash, returns `[]` |
| `test_parse_shortlist_indices_empty_on_malformed` | no leading integers → `[]`, no crash |
| `test_parse_shortlist_indices_deduplicates` | same index twice → appears once |
| `test_parse_shortlist_indices_max_8` | 10 valid indices → only first 8 returned |
| `test_fetch_full_github_decodes_readme` | mock GitHub API returns base64 → decoded text ≤3000 chars |
| `test_fetch_full_reddit_uses_body_field` | item with `body="text"` → `"text"` returned, zero `_http._get` calls |
| `test_fetch_full_youtube_returns_empty` | `source="youtube"` → `""` |
| `test_fetch_full_arxiv_capped_at_2000` | mock Jina returns 5000 chars for arxiv item → capped at 2000 |
| `test_fetch_full_jina_reader_other` | mock `_http._get` for r.jina.ai → returns capped text |
| `test_fetch_full_fails_gracefully` | `_http._get` raises `Exception` → `""`, no crash |
| `test_corpus_enriched_two_sections` | output contains `"=== FULL CONTENT ==="` and `"=== HEADLINES ==="` |
| `test_corpus_enriched_cap` | total ≤ `_ENRICHED_CORPUS_CAP` regardless of input size |
| `test_corpus_enriched_shortlisted_not_in_headlines` | shortlisted item title does not appear in HEADLINES section |
| `test_corpus_enriched_empty_shortlist` | `shortlisted=[]` → FULL CONTENT header only, HEADLINES has all items |
| `test_run_two_stage_pipeline` | monkeypatch `build_broad_pipeline` → returns a mock Workflow backed by a `FakeRunner` (same `FakeRunner`/`FakeService` pattern as `test_run_once_async_returns_state` in the existing test file); `FakeSession.state = {"shortlist_indices": "1. reason\n2. reason"}`; monkeypatch `_fetch_full` → returns `"full text"`; monkeypatch `build_integrate_pipeline` → `FakeRunner` with `state = {"report": "## Tier 1\n..."}`; assert `run("run")` returns the report string |
| `test_dry_run_stops_after_stage1` | monkeypatch `build_broad_pipeline` with FakeRunner; `run("dry-run")` returns shortlist_text, `build_integrate_pipeline` never called |
| `test_bootstrap_stops_after_stage1` | `run("bootstrap")` returns shortlist_text, `build_integrate_pipeline` never called |
| `test_build_broad_pipeline_has_scoutbroad` | graph has ScoutBroad node |
| `test_build_integrate_pipeline_has_scoutintegrate` | graph has ScoutIntegrate node |
| `test_build_pipeline_unchanged` | `build_pipeline(cfg, cloud=False)` and `cloud=True` signatures and node names unchanged |

---

## Seams left open

| Seam | Where it lands |
|---|---|
| `_fetch_full` YouTube branch returns `""` | Post-July 6: `yt-dlp --write-auto-subs --skip-download`; add `scout.youtube.channels` to config |
| feedparser for Atom RSS feeds | Separate minor fix — swap `_fetch_rss` when Atom feeds needed |
| Monitor digest time as config | Currently hardcoded 07:00; future: `monitor.digest_hour` in config |
| ScoutBroad max shortlist as config | Currently hardcoded 8; future: `scout.shortlist_max` in config |
| Jina Reader rate limits | Free tier, no documented limits; add backoff if 429s appear |

---

## What this cycle does NOT do

```
  ✗  YouTube transcript fetching (yt-dlp) — seam only
  ✗  feedparser RSS migration
  ✗  Monitor new tools
  ✗  Scout new sources
  ✗  Any schema changes
  ✗  Changes to Librarian, arms, or the disclosure gate
```

---

## Open items (for manual smoke test before build)

1. **`_run_once_async` exists in scout.py** — before Qwen3 writes Step 6, confirm whether `run()` currently calls `_run_once_async` or calls the runner directly. Step 6 bypasses `_run_once_async` entirely; if anything else in the codebase calls `run()` and depends on `_run_once_async`'s behavior, confirm it's unaffected.

2. **arXiv via Jina**: Smoke test `curl https://r.jina.ai/https://arxiv.org/abs/2406.12345` to confirm Jina renders abstract text (not PDF redirect). If Jina follows the PDF link and returns binary-ish content, switch arXiv source to `arxiv.org/pdf/...` with `[:2000]` cap.

3. **Monitor 5-hour window**: The 50k cap covers ~60 runs = last 5 hours of observations. MonitorDigest will not see observations from midnight–02:00 if the digest fires at 07:00 with 288 runs/day × 800 chars/run. For now this is acceptable — if pattern visibility across the full 24h is needed, raise cap to 200k or add hourly JSONL rotation.

---

*v3 — 2 cold reviews complete. Ready to proceed to build if open items are acceptable.*
