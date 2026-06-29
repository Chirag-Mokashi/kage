# kage — Model Routing Reference

*Living document. Update when new models ship or benchmarks are revised.*
*Last updated: 2026-06-27 (Gemini 3.x added; Fable 5 suspended; computer-use noted)*

---

## ⚠️ Active Alerts

- **Claude Fable 5 + Mythos 5 UNAVAILABLE** — US export-control directive (2026-06-12) suspended access for all users. Expected return for US-based users ~2026-07-01. Non-US access timeline unknown. Excluded from all routing until reinstated.
- **gemini-2.0-flash** — still live (was incorrectly reported dead). Superseded by 2.5-flash; no reason to use.

---

## Benchmark + Cost Table

Source key: ¹ Official · ² Estimated from prior version lineage · ³ Third-party aggregator citing official system card · ⁴ Conflicting across sources

| Model | kage key | Provider / Access | API Key | GPQA Diamond | Coding | Math | Context | Input $/M | Output $/M |
|---|---|---|---|---|---|---|---|---|---|---|
| **claude-fable-5** ⛔ | — suspended — | Anthropic CLI | Claude sub | 92.6%¹ | SWE-V **95.0%**¹ / SWE-Pro 80.3% | FrontierMath 87%³ | 1M | $10.00 | $50.00 |
| **claude-opus-4-8** | `claude` (CLI shell arm) | Claude subscription | Claude sub ✅ | **93.6%**¹ | SWE-V 88.6% / SWE-Pro 69.2%¹ | — | 1M | $5.00 | $25.00 |
| **claude-sonnet-4-6** | `claude` (CLI shell arm) | Claude subscription | Claude sub ✅ | 65.8–74.1%⁴ | SWE-V 79.6%¹ | — | 1M | $3.00 | $15.00 |
| **claude-haiku-4-5** | — (no direct key) | Anthropic direct | `ANTHROPIC_API_KEY` ❌ | 52.4%³ | SWE-V 73.3%¹ | — | 200K | $1.00 | $5.00 |
| **gemini-3.1-pro-preview** | `gemini-3-1-pro` | Google direct | `GEMINI_API_KEY` ✅ | **94.3%**¹ | SWE-V 80.6%¹ | MATH 95.1% / AIME 91.2%¹ | 1M | $2.00 | $12.00 |
| **gemini-3.5-flash** | `gemini-3-5-flash` | Google direct | `GEMINI_API_KEY` ✅ | ~88%³ | SWE-V **78%**¹ / agentic rank #3/124 | — | 1M | $1.50 | $9.00 |
| **gemini-3-pro-preview** | `gemini-3-pro` | Google direct | `GEMINI_API_KEY` ✅ | ~90%³ | — | — | 1M | $2.00 | $12.00 |
| **gemini-2.5-pro** | `gemini-2-5-pro` | Google direct | `GEMINI_API_KEY` ✅ | 86.4%¹ | SWE-V 78%³ | AIME 88%¹ | 1M | $1.25 | $10.00 |
| **gemini-2.5-flash** | `gemini` | Google direct | `GEMINI_API_KEY` ✅ | 82.8%¹ | LiveCode 59.3%¹ | AIME 72%¹ | 1M | $0.30 | $2.50 |
| **gemini-2.5-computer-use** | `gemini-cu` | Google direct | `GEMINI_API_KEY` ✅ | — | Mind2Web 70%+¹ | — | 131K | $1.25 | — |
| **gpt-4o** | `openai` | OpenAI direct | `OPENAI_API_KEY` ✅ | 53.6%¹ | HumanEval 90.2%¹ | MATH 76.6%¹ | 128K | $2.50 | $10.00 |
| **llama-3.3-70b** | `groq` | Groq (fast inference) | `GROQ_API_KEY` ✅ | 50.5%¹ | HumanEval 88.4%¹ | MATH 77%¹ | 128K | $0.59 | $0.79 |
| **mistral-small-latest** | `mistral` | Mistral direct | `MISTRAL_API_KEY` ✅ | — | — | — | 256K | $0.15 | $0.60 |
| **deepseek-v4-pro** | `fireworks` | Fireworks | `FIREWORKS_API_KEY` ✅ | ~68.4%² | LiveCode ~49.2%² | — | 1M | $1.74 | $3.48 |
| **gpt-oss-120b** | `openrouter-general` | OpenRouter free | `OPENROUTER_API_KEY` ✅ | 80.1%¹ | SWE-Pro 16.2%¹ | — | 131K | Free | Free |
| **gpt-oss-20b** | `openrouter-fast` | OpenRouter free | `OPENROUTER_API_KEY` ✅ | 71.5%¹ | — | — | 131K | Free | Free |
| **qwen3-coder** | `openrouter-code` | OpenRouter free | `OPENROUTER_API_KEY` ✅ | — | Purpose-built coder | — | 1M | Free | Free |
| **nemotron-550b** | `openrouter-reason` | OpenRouter free | `OPENROUTER_API_KEY` ✅ | — | — | — | 1M | Free | Free |
| **kimi-k2.6** | `openrouter-long` | OpenRouter free | `OPENROUTER_API_KEY` ✅ | — | Long-horizon agentic | — | 262K | Free | Free |

---

## Provider Expectations

| Provider | Latency | Rate Limits | Reliability | Notes |
|---|---|---|---|---|
| Claude CLI (shell arm) | Medium | Subscription session/weekly limits | High | Uses existing Claude subscription; Opus + Sonnet available |
| Google direct | Medium | Free tier: 500 RPM / 1M TPM (2.5-flash); varies by model | High | Most generous free tier of any provider |
| OpenAI direct | Medium | Per-API-key tier | High | Pay-per-token |
| Groq | **Very fast** | ~30 req/min free tier | High | Hardware inference — 5–10× faster than others |
| Mistral direct | Medium | Per-API-key tier | High | Cheapest paid option |
| Fireworks | Fast | Per-API-key tier | High | Optimized open-model serving |
| OpenRouter (free) | Variable | **~200 req/day per model** | Medium | Single API key covers all free models |

---

## Task Class → Model Routing (locked 2026-06-28)

| Class | Dispatch | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|---|
| **code** | 7-step dev workflow: Plan→cloud, Write→local, Review→cloud, Run→local | Plan/Review → Claude Opus/Sonnet (CLI) | Plan → gemini-3-1-pro · Review → gemini-3-5-flash | — |
| **reasoning** | 2-step: decompose + answer (same model, no local step) | Claude Opus (CLI) | gemini-3-1-pro | gpt-oss-120b free |
| **chat** | Single dispatch | Qwen3 14B local | Groq llama-3.3-70b (--cloud flag triggers) | local (when Groq rate limits) |
| **research** | Single dispatch | gemini-2.5-flash (Google Search grounding) | warn user — no silent degradation to non-web model | — |
| **multimodal** | Single dispatch | gemini-3-5-flash (image + video + audio) | gemini-2.5-flash | — |
| **system-ctrl** | LOCAL ONLY — hard rule, never cloud | Qwen3 14B local | n/a | n/a |

---

## gemini-2.5-computer-use Notes

- Vision-based screen control (screenshot → action): click, type, scroll, form fill
- Operates in authenticated browser sessions (different from Playwright DOM manipulation)
- Optimized for web browsers; not yet reliable for desktop OS-level control
- ToS implications for login-walled UI automation need review before use in kage arms
- Candidate to replace or complement Playwright browser arm in a future cycle
- 131K context window; $1.25/M input

---

## What Stays Local Always (non-negotiable)

- `kage remember` / `kage recall` / `kage list` / `kage forget` — memory operations
- `kage reindex` / `kage migrate` — index maintenance
- `kage status` / `kage doctor` — system health
- Any note tagged `--local` or in `local_only_projects`
- Any content the 3e gate withholds

---

## Open Items

- [ ] Confirm gemini-3-pro-preview GPQA and coding benchmarks from official source
- [ ] Confirm gemini-3.5-flash GPQA exact score from official source
- [ ] Get benchmark scores for nemotron-550b, qwen3-coder, kimi-k2.6
- [ ] Add Claude via OpenRouter config entries (for when CLI shell arm hits limits)
- [ ] Review gemini-2.5-computer-use ToS before enabling as arm
- [ ] Add Perplexity when API key is available (research class primary)
- [ ] Add token consumption tracking column once Monitor is built (feeds Layer 6)
- [ ] Reinstate Fable 5 entries when export-control suspension lifts (~2026-07-01 for US)
- [ ] Chirag verdict: which Gemini 3.x model to use for reasoning class (3.1 Pro vs 3.5 Flash)
