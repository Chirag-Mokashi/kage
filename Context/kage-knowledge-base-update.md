# kage — Knowledge Base Update
*Session: May 2026 — Mobile planning + Mac setup execution*

---

## Status Change Since Last Entry

Previous status: Docker install running, next step Ollama + Qwen3.5 14B.
Current status: Docker running, Ollama installed, Qwen3 14B pulled and smoke tested. Ready to fork OpenJarvis and begin build.

---

## Decisions Made This Session

### Name
- **Project name: kage** (Japanese — "shadow")
- Replaces working name "OpenJarvis" / "kage"
- Folder: `~/.kage/`
- GitHub repo: `kage` — **private**

### Model Correction
- Qwen3.5 14B does not exist as a local model — cloud API only
- **Correct model: Qwen3 14B Q4_K_M** — confirmed installed and running
- Benchmark confirmed: beats Qwen2.5-14B on every benchmark, beats Qwen2.5-32B on coding and reasoning

### Build Approach — Major Decision
- **Fork OpenJarvis (Stanford) — do not build from scratch**
- Reasoning: 4 of 6 agents already exist in OpenJarvis and are battle-tested
- What we lift: agent harness, memory (FAISS), DSPy learning loop, Docker setup, morning briefing TTS, Ollama integration
- What we build ourselves: Bridge agent, okiro trigger, confidence threshold routing, Mac menu bar UI, per-agent parameter control

### Licensing
- OpenJarvis is Apache 2.0
- Fully cleared for: personal use, modification, private repo, future commercialization
- Obligation if commercialized: keep license notice + one-line Stanford attribution
- No obligation to open source additions

### GitHub Repo
- **Private by default**
- Can switch to public anytime via one toggle in GitHub settings
- Private protects: Bridge agent, routing logic, okiro trigger, all unique architecture

---

## Agent Mapping — OpenJarvis vs kage

| kage agent | OpenJarvis equivalent | Approach |
|---|---|---|
| Monitor | `morning_digest` + `monitor_operative` | Lift and customize |
| Executor | `orchestrator` | Lift and customize |
| Librarian | `operative` | Lift and customize |
| Bridge | None | Build from scratch |
| NativeOpenHands | `native_openhands` | Lift as-is |
| OpenHands | `native_openhands` advanced | Lift as-is |

---

## Smoke Test Results — Qwen3 14B

Ran 5 intent-routing tests. Model passed all 5.

| Test | Intent | Tool picked | Result |
|---|---|---|---|
| "What do I have going on tomorrow?" | Calendar check | Calendar | ✅ |
| "Any important emails I should know about?" | Email scan | Email | ✅ |
| "Remind me about my meeting at 3" | Set reminder | Calendar | ✅ |
| "What was that thing I had to do today?" | Task review | Calendar | ✅ |
| "Check if I have anything after 5pm, and also see if my professor emailed me" | Multi-intent | Calendar + Email | ✅ |

Additional findings:
- Thinking mode off via `--think=false` flag at runtime
- JSON output: clean, no markdown wrapping, parseable directly
- Multi-intent handling: correctly splits two intents in one sentence

---

## Agent Parameters — Decision Framework

Parameters are NOT set globally. Decided per agent at time of build.

General framework locked:
- **Routine agents** (Monitor, Executor): thinking off, low temperature — fast and deterministic
- **Memory agent** (Librarian): thinking off, medium temperature — flexible summarization
- **Periodic behavior analysis**: thinking on, scheduled — builds user profile over time
- **Complex one-off queries**: thinking on, triggered by confidence threshold

This maps to three operational modes:
1. Daily operations — lean and fast
2. Hard queries — full reasoning on demand
3. Weekly behavior analysis — scheduled deep review, builds personalization over time

---

## Immediate Next Steps (Resume Here)

1. Open Antigravity on Mac
2. Install Claude Code extension
3. Log in with university credentials — higher compute credits
4. Refine kage build plan inside Antigravity
5. Fork OpenJarvis into private GitHub repo as `kage`
6. Begin build — Step 1: repo structure

---

## Build Sequence (Locked)

1. Repo + folder structure
2. Config system — single `config.toml`
3. Intelligence router — local vs cloud routing at 0.60 threshold
4. Message bus — internal agent communication
5. Bridge agent — Claude API connection (unique to kage)
6. Executor agent — action taking with confirmation
7. Monitor agent — email, calendar, morning briefing
8. Librarian agent — memory read/write, hourly schedule
9. okiro startup script — sequential agent launch, `Jarvis is ready.`
10. OpenHands agents — observation phase only

---

## Parked Decisions (Unchanged)

| Item | When |
|---|---|
| Voice output engine | Decide after Antigravity setup |
| Übersicht HUD | After exploring widgets manually |
| News topics for morning briefing | Before first okiro run |
| Morning briefing opening line style | Before first okiro run |
| Desktop app auto-open on okiro | Decide during build |
| NativeOpenHands promotion to write | When coding agents ready |
| 30B models | If 14B shows limits in Phase 3 |
| Monetization architecture | Future — foundation first |

---

## Full AI Stack (Confirmed)

| Tool | Role |
|---|---|
| kage local | Execution, monitoring, calendar, email, files |
| Claude Pro | Deep reasoning, planning, brainstorming |
| Perplexity Pro | Web research, cited answers |
| Claude Code | Heavy autonomous coding |
| Antigravity | IDE — UI only, AI features off for now |
| Gemini | Google Workspace, long context |

---

*Updated: May 2026*
*Next session: Resume at Antigravity setup + OpenJarvis fork*
