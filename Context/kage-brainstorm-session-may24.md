# kage — Brainstorm Session Notes
*Compiled from mobile brainstorm session — May 2026*
*To be merged into docs/blueprint.md on desktop*

---

## 1 · Session Purpose

This document captures all decisions, discoveries, and notes from a brainstorm session conducted on mobile before desktop implementation begins. Everything here feeds into the existing kage blueprint. Nothing here supersedes the canonical `docs/blueprint.md` — it extends it.

**Rule:** Before implementing anything from this document, run a Cosmos search to validate current technology landscape. We do not want to build on stale foundations.

---

## 2 · The Vision — Restated and Sharpened

### What kage actually is

kage is not a home automation hub. It is not a dashboard. It is not another personal AI chatbot.

**kage is a mediator — a second layer of yourself.**

You express intent naturally — voice, text, or gesture. kage understands that intent through context and memory. kage identifies which device or combination of devices on your local network fulfills that intent. kage executes silently and confirms minimally.

The devices are just arms. kage is the brain. You are the person.

### The full device vision

Any device on your WiFi network is a potential node:
- MacBook Pro M5 Pro — primary brain
- ASUS VivoBook — secondary display (Phase 2)
- Alexa
- Smart TV
- Printer
- Any IoT device connected to WiFi

kage discovers these devices automatically, understands their capabilities, and routes your intent to the right one. You never think about the device. You express intent. kage handles the rest.

**This is not Home Assistant.** Home Assistant manages devices. kage mediates between you and devices. The distinction is intent understanding and deep personal context — not device management.

### The self-aware substrate vision

When anyone downloads kage from GitHub, it:
1. Boots and scans its environment
2. Discovers what devices are on the local network automatically
3. Understands the capability of each device — compute, screen, input type
4. Distributes itself organically across available nodes
5. Routes intelligence to the right device based on capability

kage grows with the network. Add a device — kage finds it. Remove a device — kage adapts. Zero manual configuration.

---

## 3 · Architecture Decisions — New and Updated

### 3a · The `actions/` Layer — Locked

**Decision:** Adopt the clean `actions/` separation pattern from Mark XXXIX.

An action is the smallest executable unit of work that touches the outside world. It is what an agent *does* after it *decides*. Actions contain no reasoning — only execution.

**What lives in `actions/`:**
- `send_email(to, subject, body)`
- `create_calendar_event(title, time, duration)`
- `read_emails(account, limit)`
- `search_web(query)`
- `write_file(path, content)`
- `push_to_device(device_id, payload)`
- `speak(text)`
- `query_memory(query)`
- `discover_devices()`
- `send_to_screen(device_id, content)`

**What does NOT live in `actions/`:**
- Deciding which emails are important — agent reasoning
- Planning a morning briefing — orchestration
- Routing local vs cloud — intelligence router
- Remembering context — memory layer

**Why this matters:** Every action becomes a permission boundary. The per-agent permission model wraps the `actions/` layer cleanly.

```
Monitor agent    → read_* actions only
Executor agent   → write_* actions (confirmation required)
Librarian agent  → memory_* actions only
Bridge agent     → api_* actions only
```

**Folder structure to adopt (from Mark XXXIX):**
```
kage/
├── actions/       # Executable units — touch the outside world
├── agent/         # Agent logic — reasoning and decisions
├── core/          # Core engine — routing, orchestration
├── memory/        # Memory layer — FAISS + BM25
├── config/        # Config — single config.toml
└── main.py        # Entry point — okiro
```

---

### 3b · Multi-Device Communication Layer — Locked Direction

**Phase 1 (single Mac):** asyncio internal queues — Python talking to Python, no network.

**Phase 2 (Mac + VivoBook):** Plain WebSockets via Socket.IO — one server on Mac, VivoBook browser connects. No Redis needed at two devices. Socket.IO preferred over raw WebSockets — handles reconnection, fallback, and rooms automatically (pattern confirmed by ADA V2).

**Phase 3+ (full local network — Alexa, TV, printer, Pi nodes):** MQTT + Zyre/Pyre for device-aware, self-discovering architecture.

### 3c · Device Discovery Architecture — Locked Direction

**Two-layer approach:**

**Layer A — Discovery: Zyre / Pyre (Python port)**
- UDP beacons broadcast on local network at boot
- Any kage node on same WiFi appears automatically within 1–2 seconds
- No config file, no IP addresses, no setup wizard
- Zero-config for anyone who downloads kage from GitHub
- Protocol-neutral, works across OS and language

**Layer B — Messaging: MQTT with local Mosquitto broker**
- Once devices discovered, lightweight Mosquitto broker spins up on primary device (Mac)
- All inter-device state flows through MQTT topics
- Clean, structured, low overhead
- Adding a new device is one line of config

**Phase 3 upgrade path: EMQX 6.2**
- Native A2A (agent-to-agent) protocol — agents register, discover, collaborate through broker
- MCP Bridge Plugin — devices expose tools directly to AI agents via MQTT
- Scoped authorization maps to kage's identity partition model
- Drop-in upgrade from Mosquitto — same MQTT protocol

**Why not Redis + WebSockets (like AZARIS):**
Redis solves multi-server synchronization. kage is local-first on one primary device. Redis is overkill and adds unnecessary infrastructure. Redis also changed its license in 2024. Skip entirely unless kage eventually runs across multiple servers — far outside current roadmap.

**Cosmos search required before implementing device discovery layer.**

---

### 3d · Voice Layer — Locked Direction

**Decision: LiveKit as the voice pipeline framework.**

This resolves the parked "voice output — decide when Mac arrives" decision. Locked now.

**What LiveKit is:**
Open source real-time communication platform built on WebRTC. Apache 2.0 license — commercial use cleared. Used by OpenAI (ChatGPT Voice), Meta, Character.ai. LiveKit Agents 1.0 shipped April 2025, currently at 1.5.x with native MCP tool support.

**The pipeline for kage:**
```
okiro wake word → VAD → STT (Whisper local) → LLM (Qwen3 14B / Claude fallback) → TTS (Piper local) → speakers
```

**Key properties:**
- Self-hosted on Mac — no cloud audio routing
- Vendor agnostic — swap any component with one line change
- Native MCP support — connects directly to Gmail, Calendar, Notion tools mid-conversation
- Built-in interruption handling — cut agent off mid-sentence, it stops and listens
- Sub-100ms audio latency via WebRTC — voice feels natural, not robotic
- Phase 2: VivoBook joins same LiveKit room as a participant — audio routing handled natively

**Component choices (subject to Cosmos search validation):**
- **Wake word:** Open Wake Word — open source, local, customizable for `okiro`
- **STT:** Whisper — confirmed working on Apple Silicon (validated by NetworkChuck)
- **LLM:** Qwen3 14B local (≥0.60 confidence) → Claude Sonnet 4.6 fallback (<0.60)
- **TTS:** Piper — local, fast, offline, customizable voice, runs on Apple Silicon
- **Protocol:** Wyoming — lightweight local voice component communication protocol (alternative to LiveKit for simpler setups, worth knowing)

**Why not WebSockets for voice:**
WebSockets add 500ms–1.5s latency. Voice conversation breaks down above 600ms. WebRTC delivers sub-100ms. There is no comparison for real-time voice.

**Cosmos search required before implementing voice layer.**

---

## 4 · The `soul.md` File — Pending Task

**Concept locked. Content to be defined on desktop.**

A single human-readable markdown file that defines kage's personality, communication style, tone, and behavioral rules. Not code — just a document kage reads as its core identity. Editable anytime without touching code.

**To define when on desktop:**
- kage's name and how it refers to itself
- Tone during `okiro` morning briefing vs casual queries vs urgent alerts
- Communication style — brief for alerts, detailed for briefings, structured for options
- Behavioral rules — when to confirm, when to act, when to surface vs stay silent
- How kage addresses you
- Personality traits — professional, warm, efficient

**Pattern source:** Clawdbot / Claudette by Mark Kashef — validated in production.

---

## 5 · Competitor Reference Library — Clone Locally

Repos to clone on desktop for local reference. Read code, study patterns, never run blindly.

| Repo | License | Clone URL | What to study | Safe to borrow? |
|---|---|---|---|---|
| Stanford OpenJarvis | Apache 2.0 | github.com/open-jarvis/OpenJarvis | Agent harness, FAISS memory, DSPy loop, Ollama integration | Yes — kage's fork substrate (Hazy Research + Scaling Intelligence Lab, Stanford SAIL) |
| nazirlouis/ada_v2 | MIT | github.com/nazirlouis/ada_v2 | `debug_mdns.py` discovery, `project_manager.py` memory, Socket.IO pattern, `authenticator.py` face auth | Yes — MIT |
| FatihMakes/Mark-XXXIX | CC BY-NC 4.0 | github.com/FatihMakes/Mark-XXXIX | `actions/` folder structure, memory module, cross-platform patterns | Reference only — non-commercial license |
| LiveKit Agents | Apache 2.0 | github.com/livekit/agents | Voice pipeline framework — STT/LLM/TTS orchestration | Yes — adopt as framework |
| LiveKit Server | Apache 2.0 | github.com/livekit/livekit | WebRTC server — self-host on Mac | Yes — adopt as framework |

**Files specifically worth reading from ada_v2:**
- `debug_mdns.py` — local network device discovery via mDNS
- `printer_agent.py` — auto-discovery pattern (discovery logic only, not printing)
- `project_manager.py` — file-based JSON project memory (Librarian early phase reference)
- `server.py` — Socket.IO frontend-backend event loop pattern
- `authenticator.py` — MediaPipe face auth (future identity verification reference)

---

## 6 · Future Considerations — Breadcrumb Bag

Items noted for the future. Not planned, not parked with timeline. Just remembered so they don't get lost.

### Telegram as Mobile Gateway
When away from Mac, a Telegram bot becomes the mobile interface to kage. You message the bot → kage receives, processes, responds. Zero custom app development. Works on any device. Future consideration — no timeline.

### Raspberry Pi as Always-On Listener Node
A Pi as a room-level kage listener — always on, always listening for `okiro`, even when MacBook is closed. Low power, cheap, dedicated hardware. Connects to local network device vision. Future consideration — no timeline.

### Always-On Dedicated Hardware
Mac Mini or similar as kage's permanent brain — never sleeps, always available. Relevant when kage needs 24/7 operation independent of MacBook being open. Future consideration — no timeline.

### GibberLink / Inter-Agent Communication Efficiency
kage's six internal agents currently communicate via message bus in structured JSON. GibberLink research suggests machine-to-machine internal communication doesn't need human-readable language overhead. Future direction — kage's internal message bus could eventually use a compressed, efficient inter-agent protocol. Cosmos search when relevant.

### Multi-Device Audio via LiveKit
When VivoBook joins the network, LiveKit handles audio routing between both devices natively — same room, two participants. This extends the Phase 2 WebSocket plan with something more capable at no extra cost since LiveKit is already adopted.

---

## 7 · Cosmos Research Queue

**Rule: Run Cosmos before implementing any of these. Do not build on assumptions.**

### Priority 1 — Before voice layer implementation
- Is LiveKit still the best local voice pipeline framework or has something better emerged?
- Best local STT for Apple Silicon M5 Pro — Whisper vs current alternatives
- Best local TTS for natural voice output on Mac — Piper vs current alternatives
- Any new frameworks combining wake word + VAD + STT + LLM + TTS in a single local pipeline
- Open Wake Word vs alternatives for custom wake word detection in 2026
- Wyoming protocol — current status and adoption

### Priority 2 — Before device discovery implementation
- Zyre/Pyre current status — is it still actively maintained?
- MQTT broker comparison for local personal AI — Mosquitto vs alternatives in 2026
- EMQX 6.2 A2A registry — production readiness for personal scale
- mDNS vs UDP beacon discovery — current best practice for local device discovery

### Priority 3 — Before inter-agent communication implementation
- GibberLink / emergent communication protocols — current research state
- Lightweight inter-agent messaging for local multi-agent systems 2026
- asyncio vs ZeroMQ for local Python agent-to-agent communication

---

## 8 · Videos and Sources Analyzed This Session

### Useful — Added to Reference Library

| Source | Creator | What was useful |
|---|---|---|
| AZARIS Instagram reel | Unknown | Multi-monitor HUD concept, Three.js particle orb, state-aware animation pattern |
| ADA V2 YouTube + GitHub | Naz Louis (nazirlouis) | mDNS discovery, Socket.IO pattern, MediaPipe auth, project memory — MIT license |
| Mark XXXIX YouTube + GitHub | FatihMakes | `actions/` folder architecture, memory module separation — CC BY-NC reference only |
| Clawdbot / Claudette | Mark Kashef | `soul.md` personality file concept, Whisper on Apple Silicon, Docker blast radius framing, account separation |
| LiveKit Jarvis | Eddie Chen | LiveKit framework discovery — most significant voice layer finding |
| NetworkChuck local Alexa replacement | NetworkChuck | Open Wake Word, Piper TTS, Wyoming protocol, Raspberry Pi listener node concept, Whisper confirmed on Apple Silicon |

### Skipped — No Value for kage

| Source | Reason |
|---|---|
| NetHyTech no-code Jarvis | Paywalled source code, no architecture depth |
| NetHyTech Jarvis 2.0 playlist (43 videos) | Same creator, paywalled, tutorial-level only |
| Nate Herk (Lovable + ElevenLabs + n8n) | No-code, all cloud, no open source, wrong direction |
| Rahul Jindal (Claude Code + Telegram + VPS) | Cloud VPS, no repo — Telegram gateway noted as future breadcrumb only |

### Interesting — Conceptual Only

| Source | What it contributed |
|---|---|
| GibberLink video | Inter-agent communication efficiency concept — future Cosmos search |

---

## 9 · Desktop To-Do List

Tasks to complete when on desktop, in rough priority order:

1. **Clone all repos** from the reference library table above
2. **Read `debug_mdns.py`** from ada_v2 — understand the mDNS discovery pattern before designing kage's discovery module
3. **Read `actions/` folder** from Mark XXXIX — understand action separation before writing kage's action layer
4. **Read `project_manager.py`** from ada_v2 — Librarian agent early implementation reference
5. **Read LiveKit Agents docs** — understand the pipeline before designing kage's voice layer
6. **Write `soul.md`** — define kage's personality, tone, communication style, behavioral rules
7. **Run Cosmos searches** from Section 7 before implementing anything
8. **Merge this document** into `docs/blueprint.md` — add new decisions to the locked decisions table, add new pending items to open questions, add new parked items to the deferred list
9. **Add Competitor Reference Library** as a new section in blueprint.md
10. **Add device discovery architecture** (Section 3c) as a new layer design — likely Layer 3.5 between the existing layers

---

## 10 · Key Decisions Summary — Quick Reference

| Decision | Status | Notes |
|---|---|---|
| `actions/` layer separation | Locked | Smallest executable unit, permission boundary per agent |
| Folder structure | Locked | actions/ agent/ core/ memory/ config/ main.py |
| Phase 1 comms | Locked | asyncio internal queues |
| Phase 2 comms | Locked | Socket.IO over WebSockets, Mac → VivoBook |
| Phase 3 comms | Locked direction | MQTT (Mosquitto) + Zyre discovery, EMQX upgrade path |
| Redis | Rejected | Overkill for local-first single-primary setup |
| Voice framework | Locked | LiveKit — self-hosted, Apache 2.0 |
| Wake word | Locked direction | Open Wake Word — Cosmos search before implementing |
| STT | Locked direction | Whisper local on Apple Silicon — Cosmos search before implementing |
| TTS | Locked direction | Piper local — Cosmos search before implementing |
| soul.md | Concept locked | Content to be written on desktop |
| Telegram gateway | Future breadcrumb | No timeline, just remembered |
| Pi listener node | Future breadcrumb | No timeline, just remembered |
| GibberLink inter-agent | Future Cosmos search | When inter-agent protocol becomes relevant |
| Cosmos search before build | Mandatory | Every major layer requires research validation |

---

*Session date: May 2026*
*Next action: Open desktop, clone repos, run Cosmos searches, merge into blueprint.md*
