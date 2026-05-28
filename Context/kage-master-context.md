# kage — Master Context File
*Single source of truth. Upload this at the start of any Claude session to resume instantly.*
*Last updated: May 2026*

---

## Who I Am

- **Name:** Chirag Mokashi
- **Program:** Northeastern University — Masters in Applied AI
- **Hardware:** MacBook Pro M5 Pro, 24GB unified memory, 1TB storage
- **Git identity:** Chirag-Mokashi / personal-a@example.com
- **Primary AI stack:** kage (local) + Claude Pro (planning) + Perplexity Pro (research) + Claude Code (coding) + Antigravity (IDE) + Gemini (Google Workspace)

---

## Active Projects

| Project | Status | Priority |
|---|---|---|
| kage (personal AI system) | In build — Week 1 | Primary |
| Quantum AI (NEU coursework) | Complete — revival mode only | Dormant |
| LLM Research — Artificial Lung Capacity | Conceptual stage, notes captured | Parked |

---

## Project 1: kage

### What It Is
A personal AI system triggered by one keyword: `okiro` (Japanese — "wake up"). Local model handles execution and monitoring. Claude cloud handles thinking and planning. User is the review layer between the two.

Previously called OpenJarvis. Renamed to kage (Japanese — "shadow"). Folder: `~/.kage/`. GitHub repo: `kage` — **private**.

### Build Approach
**Fork Stanford's OpenJarvis (Apache 2.0) — not building from scratch.**
- 4 of 6 agents already exist in OpenJarvis and are battle-tested
- What we lift: agent harness, memory (FAISS), DSPy learning loop, Docker setup, morning briefing TTS, Ollama integration
- What we build: Bridge agent, okiro trigger, confidence threshold routing, Mac menu bar UI, per-agent parameter control
- Apache 2.0: cleared for personal use, modification, private repo, future commercialization. Only obligation if commercialized: keep license notice + one-line Stanford attribution.

### Current Status (as of last session)
- Docker: ✅ running
- Ollama: ✅ installed
- Qwen3 14B Q4_K_M: ✅ pulled and smoke tested — passed all 5 intent-routing tests
- Claude Code: not yet installed
- GitHub repo `kage`: not yet created
- Antigravity: installed but Claude Code extension not yet set up

**Resume point:** Open Antigravity → install Claude Code extension → log in with university credentials → fork OpenJarvis into private repo as `kage` → begin repo structure build.

### Model Correction (Important)
- Qwen3.5 14B does not exist as a local model — cloud API only
- **Correct model: Qwen3 14B Q4_K_M** — this is what is installed and running
- Beats Qwen2.5-14B on every benchmark, beats Qwen2.5-32B on coding and reasoning

### Intelligence Layer
| Config | Value |
|---|---|
| Primary model | Qwen3 14B Q4_K_M |
| Confidence threshold | 0.60 |
| Cloud fallback | Claude Sonnet 4.6 |
| Monthly cloud cap | $20 (placeholder — revisit after local testing) |
| Alert at | 85% usage — auto switch to local only |
| Last 15% | Manual override only via `--cloud` flag |

Status bar format:
```
⚡ Qwen3 14B  [████████░░] 2,340 tok
● LOCAL                    $0.00 / $20
```

### Agents (All 6)
| Agent | Type | Permissions | Status |
|---|---|---|---|
| Monitor | monitor_operative | email read, calendar read, files read, web search | Lift from OpenJarvis |
| Executor | orchestrator | calendar read/write/create — confirmation always required | Lift from OpenJarvis |
| Librarian | operative | files read, email read, calendar read, memory write — hourly schedule | Lift from OpenJarvis |
| Bridge | claude_code | executor write, Anthropic API | **Build from scratch** |
| NativeOpenHands | native_openhands | files read only — observation phase | Lift as-is |
| OpenHands | openhands | files read only — observation phase | Lift as-is |

- No Judge/comparator model needed at current stage
- Agent conflict resolution: revisit Phase 3 only
- All write actions require explicit user confirmation

### Agent Parameters Framework
- **Routine agents** (Monitor, Executor): thinking off, low temperature — fast and deterministic
- **Memory agent** (Librarian): thinking off, medium temperature — flexible summarization
- **Periodic behavior analysis**: thinking on, scheduled — builds user profile weekly
- **Complex one-off queries**: thinking on, triggered by confidence threshold

### Build Sequence (Locked)
1. Repo + folder structure
2. Config system — single `config.toml`
3. Intelligence router — local vs cloud at 0.60 threshold
4. Message bus — internal agent communication
5. Bridge agent — Claude API connection
6. Executor agent — action taking with confirmation
7. Monitor agent — email, calendar, morning briefing
8. Librarian agent — memory read/write, hourly schedule
9. `okiro` startup script — sequential agent launch, prints "Jarvis is ready."
10. OpenHands agents — observation phase only

### 3-Week Plan
**Week 1 — Foundation:** Docker, Ollama + Qwen3 14B, okiro trigger script, GitHub repo + folder structure, basic message passing, Claude API fallback working.

**Week 2 — Agents:** Monitor, Librarian, Bridge, Executor agents. Confirmation system. MCP connections — Gmail, Calendar, Notion.

**Week 3 — Polish:** Morning briefing end to end, okiro fires full sequence, menu bar status display, FAISS + BM25 memory, error handling and logging, testing.

### Smoke Test Results (Already Done)
| Test | Intent | Tool | Result |
|---|---|---|---|
| "What do I have going on tomorrow?" | Calendar check | Calendar | ✅ |
| "Any important emails I should know about?" | Email scan | Email | ✅ |
| "Remind me about my meeting at 3" | Set reminder | Calendar | ✅ |
| "What was that thing I had to do today?" | Task review | Calendar | ✅ |
| "Check if I have anything after 5pm, and also see if my professor emailed me" | Multi-intent | Calendar + Email | ✅ |

Additional findings: thinking mode off via `--think=false` flag, JSON output clean and parseable directly.

### MCP Connections
| MCP | Permissions | Phase |
|---|---|---|
| Gmail | Read + alert — all 3 accounts | Week 2 |
| Google Calendar | Read, create, modify with confirmation | Week 2 |
| Notion | Read only | Week 2 |
| Anthropic API | Fallback + Bridge | Week 1 |
| GitHub | TBD | Coding agents promoted |

### Memory Layer
- Backend: Hybrid — FAISS + BM25
- Retention: Indefinite with smart compression
- Summarization after 30 days
- Deduplication and versioning enabled
- Project memory spaces: LLM Research (top_k 8), Personal (top_k 5), User Profile (top_k 3)

### Security
- Per-agent permissions — each agent sees only what it needs
- Confirmation required: all write actions
- Sandboxing: Docker — priority one, done before anything else
- Logging: minimal, destructive actions logged, 30 days rolling, 10MB max

### Backup
- Primary: Time Machine (needs external drive — parked)
- Secondary: iCloud end-to-end encrypted
- Sync folder: `~/.kage/data`

### UI Layer
- Menu bar app: primary UI, always accessible
- Übersicht HUD: Phase 2 — always-visible desktop widget showing active model, token bar, monthly spend, agent states

### Startup Sequence
```bash
alias okiro="~/.kage/scripts/start.sh"
```
Fires: ollama serve → librarian → monitor → bridge → executor → desktop app opens. ~20–25 seconds to ready.

### Parked Decisions
| Item | When |
|---|---|
| Voice output engine | After Antigravity setup |
| Übersicht HUD build | After exploring widgets manually |
| News topics for morning briefing | Before first okiro run |
| Morning briefing opening line style | Before first okiro run |
| Desktop app auto-open on okiro | Decide during build |
| NativeOpenHands promotion to write | When ready |
| 30B models | If 14B shows limits in Phase 3 |
| Time Machine | When external drive acquired |
| Monetization architecture | Foundation first |

---

## Project 2: Quantum AI (NEU Coursework)

### Status
Complete. Revival mode only — no active assignments. Potential future research paper contribution — professor leads, Chirag is supporting technical contributor only.

### Tools Used
PennyLane, Qiskit Aer, GitHub, Google Colab, Python, Cosmos research tool.

### Knowledge Base Location
12 Perplexity threads — exported and structured. Stored in Claude Project (Quantum AI space). Cover page file: `quantum-ai-coverpage.md`.

### Revival Protocol
If this project reactivates: lead with technical summary (circuits, code, results), then decisions and conclusions. Keep email and timeline context in background unless directly asked.

---

## Project 3: LLM Research — Artificial Lung Capacity

### Status
Conceptual and literature-survey stage only. No implementation, no dataset curation, no formal architecture yet.

### The Idea
An artificial lung capacity module for AI voice synthesis — a time-varying lung-state that constrains where emphasis can occur, how strong it can be, and when sentences must end. Modulates voice synthesis the way real respiratory physiology modulates human speech.

### What the Research Confirmed
- Human speech physiology: lung volume → subglottal pressure → loudness and pitch. Emphasis literally spends more air.
- Speakers plan breath groups around utterance length and emphasis ahead of time.
- USC/Aston virtual human system has an explicit `capacitylung` parameter (syllables per breath, loudness tied to breath frequency).
- KTH TTS system learns breath-group context so it "knows" it is about to run out of air — rushes slightly like a human.
- **Critical missing piece:** no current neural TTS tracks a running air budget and asks "can I afford to emphasize this word given what's left?" — this is the open research gap.
- Deepfake detectors exploit this gap — AI voices are detectable partly because they lack physiologically coherent breath patterns.

### Conceptual Architecture (Locked)
1. Lung-volume state tracker
2. Emphasis-air cost model
3. Breath-position planner
4. Voice-quality modulation tied to lung level

### Open Questions
- How to make the respiratory model differentiable and computationally efficient for integration with neural TTS
- How to parameterize an emphasis air-cost model from real speech data
- How to train neural prosody models to respect a lung-capacity constraint
- Universal vs per-voice respiratory model (different "lung size" per persona)

### Key Sources
- KTH: Breathing and Speech Planning in Spontaneous Speech Synthesis
- USC/Aston: Speech Breathing in Virtual Humans — explicit `capacitylung` implementation
- Interspeech: Implementation of Respiration in Articulatory Synthesis
- Respiratory constraints on speech production (phonetics/physiology foundational papers)

### Suggested Next Actions When Revisiting
1. Architecture design draft — integrate lightweight respiratory state module into neural TTS pipeline
2. Data and feature strategy — infer lung-volume signals from existing speech corpora
3. Toy experiments — simplified breath-budget model influencing sentence splitting and emphasis attenuation
4. Evaluation framework — AB tests, deepfake detector robustness, physiological alignment

---

## Mac Setup — Current State

### Done
macOS updated, Apple ID + iCloud, Chrome, Git configured, Homebrew 5.1.12 (ARM64), GitHub CLI 2.92.0 (authenticated as Chirag-Mokashi), Python 3.14.5, pip 26.1.1, Claude desktop app, Raycast (default Cmd+Space), uBlock Origin, Wispr Flow, FileVault enabled, Stage Manager disabled, desktop cleaned, screenshots redirected.

### Still Needed
- Time Machine — needs external drive
- Password manager — parked
- Übersicht widgets — explore manually

### Key Mac Shortcuts to Remember
- Cmd replaces Ctrl for all shortcuts
- Red X does not quit — use Cmd+Q
- Two finger tap = right click
- Fn+Delete = forward delete
- Cmd+Delete = move to trash in Finder

---

## Context Management Protocol
*How to use this file across sessions:*

- Upload this file at the start of any Claude session with: "Resume from this context file. [What I need today]."
- After any session with meaningful decisions: update the relevant section before closing.
- Store locally at: `~/.kage/context/kage-master-context.md`
- When kage is built, the Librarian agent will eventually maintain this file automatically.

---

*Generated: May 2026 | Synthesized from all Claude Project knowledge base files*
