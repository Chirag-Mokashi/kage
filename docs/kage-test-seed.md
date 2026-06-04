# kage test — seed corpus

> **Status:** Living capture doc (Stage 0). These are SEED cases for the
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
