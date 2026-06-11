# Cycle 8 — Retrieval Eval Corpus (draft)

*Draft fixture corpus for the retrieval-quality eval. Created 2026-06-10.*
*These are SYNTHETIC, fictional test notes — NOT Chirag's real memory. Safe to commit.*
*At build time each note below becomes a file in `tests/fixtures/eval_corpus/<filename>.md`.*

---

## How this is used

1. Import all fixture notes into a fresh, throwaway kage store.
2. Run each `query → expected-note(s)` case (Chirag authors these — section at the bottom).
3. Compute **recall@k** (was the expected note in the top k?) and **MRR** (how high did it rank?).
4. Run **before** the chunking + reranker changes (baseline) and **after** (improvement).

The corpus is deliberately built so that a *naive* retriever (today's structural chunking, no reranker) **fails or ranks poorly** on several cases, and the Cycle 8 changes should visibly improve them.

## Coverage matrix — what each note is for

```
  CHALLENGE                          NOTES
  ───────────────────────────────────────────────────────────
  Headerless long prose              04, 11, 17   ← exercises the chunking bug
  (buried fact in one paragraph)                    (today: whole note = 1 chunk)
  Multi-section (## headers)         01, 02, 15, 18
  Keyword collision (rerank)         07/08 "Apollo", 09/10 "budget"
  Semantic match, different words    14 ("save money" ↔ "route around paywalls"),
  (vector + rerank, not FTS)         04
  Short single-fact recall           03, 05, 06, 12, 13, 16
  Project-partition wall             collisions span projects: Apollo (kage vs
                                     personal), budget (finance vs personal)
```

---

## Fixture notes

> Each note shows: **filename** · `project` · *structure type* — then the body.

---

### 01 · `kage-privacy-gate.md` · `kage` · *multi-section*
```
## What it does
The privacy gate decides what may leave the machine before any cloud call.

## How it works
Three checks run in order: the local_only flag, the project rule, then a PII
scan across 29 patterns. If anything is withheld, the user is asked before dispatch.
```

### 02 · `kage-roadmap.md` · `kage` · *multi-section*
```
## Cycle 8
Retrieval quality: recursive chunking, a cross-encoder reranker, and an eval harness.

## Cycle 9
kage chat with streaming, so conversations become stateful instead of one-shot.

## Cycle 10
kage becomes an MCP client and calls external tools itself.
```

### 03 · `neu-advisor.md` · `school` · *short fact*
```
My thesis advisor is Dr. Lena Park. Her office is 312 ISEC and she holds open
hours on Thursdays at 2pm.
```

### 04 · `neu-thesis-topic.md` · `school` · *headerless prose (buried fact)*
```
Spent the afternoon narrowing the thesis. A lot of the early ideas were too broad —
something about multi-agent systems, then something about retrieval benchmarks, none
of it focused enough to defend. After talking it through, the direction that actually
holds together is personal-scale access control: taking the enterprise idea of
participant-aware permissions and instantiating it for a single user with multiple
identities. That is the contribution. The rest of the afternoon went to unrelated
errands and a long tangent about whether to use LaTeX or Typst for the writeup.
```

### 05 · `neu-course-deadlines.md` · `school` · *short fact*
```
ML systems project is due April 15. The final exam is May 2 at 9am.
```

### 06 · `coffee-preference.md` · `personal` · *short fact*
```
I drink my coffee black, no sugar. Switched away from lattes back in 2024.
```

### 07 · `apollo-project.md` · `kage` · *short — keyword collision with 08*
```
Apollo is the internal codename for kage's offline export feature — bundling a
project's notes into a single portable archive.
```

### 08 · `apollo-cafe.md` · `personal` · *short — keyword collision with 07*
```
Apollo Cafe on Huntington Ave has the best cold brew near campus. Cash only before 11am.
```

### 09 · `budget-ai-cloud.md` · `finance` · *short — keyword collision with 10*
```
Monthly AI budget: a hard cap of $20 for cloud API spend. Everything else routes local.
```

### 10 · `budget-goa-trip.md` · `personal` · *short — keyword collision with 09*
```
Goa trip budget is 30k INR, mostly flights and the stay. Food and travel kept separate.
```

### 11 · `gym-routine.md` · `health` · *headerless prose (buried fact)*
```
The current split is push on Monday, pull on Wednesday, legs on Friday, with the
weekend kept loose. Tuesdays and Thursdays are easy cardio or a walk if motivation is
low. The one rule that actually matters: Sunday is a full rest day, no exceptions,
because skipping it last quarter is what led to the shoulder strain.
```

### 12 · `sleep-notes.md` · `health` · *short fact*
```
Target 7.5 hours of sleep. Take melatonin 0.5mg only when traveling across time zones.
```

### 13 · `mom-birthday.md` · `personal` · *short fact*
```
Mom's birthday is March 22. She likes orchids, not cut flowers.
```

### 14 · `kage-jugaad.md` · `kage` · *semantic match (no "money"/"cost" words)*
```
kage's operating value is jugaad: get the most out of what you already have and
route around artificial walls like paywalls and missing APIs, instead of paying to
remove them. Use the subscription UI you already own rather than buying API access twice.
```

### 15 · `recipe-dal.md` · `recipes` · *multi-section (distractor + structure)*
```
## Ingredients
Toor dal, turmeric, cumin seeds, garlic, tomato, ghee, salt.

## Steps
Pressure cook the dal with turmeric. Temper cumin and garlic in ghee, add tomato,
then fold into the dal. Finish with salt.
```

### 16 · `laptop-specs.md` · `personal` · *short fact*
```
Main machine: MacBook Pro M5 Pro, 24GB unified memory. Bought late 2025.
```

### 17 · `meeting-notes-2026-05.md` · `school` · *headerless prose (buried decision)*
```
Lab meeting ran long. Most of it was logistics — room booking for the showcase, who
is presenting first, the projector that still does not work. Someone brought donuts.
Buried in the middle of all that, the one decision worth keeping: the showcase demo
will use the local model only, no cloud calls, so the privacy story is the headline.
Then back to scheduling arguments for another twenty minutes.
```

### 18 · `perplexity-vs-cosmos.md` · `kage` · *multi-section*
```
## Perplexity
Strong for fast web-grounded answers. Has an API, but it bills separately from the Pro
subscription.

## Cosmos (Edison Scientific)
Deep multi-source research that takes minutes. Has an official Platform API; cost vs the
subscription is still unconfirmed.
```

---

## Eval cases (drafted by Claude — for Chirag's approval)

Format: a natural-language query, the note(s) that *should* come back, an optional
`project:` scope, and what each tests. 20 cases, covering every row of the matrix.

```yaml
# ── short-fact recall (should already work; baseline sanity) ──
- query: "what time are my advisor's office hours?"
  expect: [neu-advisor]
  tests: short-fact recall

- query: "when is the ML systems project due?"
  expect: [neu-course-deadlines]
  tests: short-fact recall

- query: "how do I take my coffee?"
  expect: [coffee-preference]
  tests: short-fact recall

- query: "how much sleep should I be getting?"
  expect: [sleep-notes]
  tests: short-fact recall

- query: "when is mom's birthday and what flowers does she like?"
  expect: [mom-birthday]
  tests: short-fact recall

- query: "what laptop do I use?"
  expect: [laptop-specs]
  tests: short-fact recall

# ── buried fact in headerless prose (chunking fix should improve) ──
- query: "what is my thesis actually about?"
  expect: [neu-thesis-topic]
  tests: buried fact, headerless note — relevant para surrounded by noise

- query: "which day is my full rest day?"
  expect: [gym-routine]
  tests: buried fact, headerless note

- query: "what did we decide about the showcase demo?"
  expect: [meeting-notes-2026-05]
  tests: buried decision inside a rambling headerless note

# ── keyword collisions (reranker should rank the right one #1) ──
- query: "which Apollo is the export feature?"
  expect: [apollo-project]
  tests: collision — must beat apollo-cafe

- query: "where's a good cold brew near campus?"
  expect: [apollo-cafe]
  tests: collision + semantic (cold brew) — must beat apollo-project

- query: "what's my monthly cap for cloud AI spend?"
  expect: [budget-ai-cloud]
  tests: collision — must beat budget-goa-trip

- query: "how much is the Goa trip going to cost?"
  expect: [budget-goa-trip]
  tests: collision — must beat budget-ai-cloud

# ── semantic match, different words (vector + rerank, not FTS) ──
- query: "how does kage avoid spending money?"
  expect: [kage-jugaad]
  tests: note never says money/spend — only "route around paywalls"

- query: "does Perplexity's API cost extra beyond the subscription?"
  expect: [perplexity-vs-cosmos]
  tests: semantic + multi-section retrieval

# ── multi-section notes (right section should surface) ──
- query: "what does the privacy gate check before sending?"
  expect: [kage-privacy-gate]
  tests: multi-section — the "How it works" section

- query: "what's planned for cycle 9?"
  expect: [kage-roadmap]
  tests: multi-section — the specific Cycle 9 section

- query: "what are the steps to make dal?"
  expect: [recipe-dal]
  tests: multi-section — the Steps section

# ── project-partition wall (scoped query must not leak across projects) ──
- query: "budget"
  project: finance
  expect: [budget-ai-cloud]
  tests: partition — must NOT return budget-goa-trip (personal)

- query: "Apollo"
  project: kage
  expect: [apollo-project]
  tests: partition — must NOT return apollo-cafe (personal)
```

**Expected baseline behavior (today, no fixes):** the short-fact and multi-section
cases should mostly pass; the **buried-fact (07/08/17-style), collision, and
semantic** cases are where today's retriever should rank poorly — and where Cycle 8
should show the biggest recall@k / MRR jump.

---

*Next: Chirag approves/edits these cases; build session imports the corpus, records
baseline, applies chunking + reranker, re-measures.*
