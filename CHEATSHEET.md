# kage — cheat sheet

Quick reference. (`cat ~/Projects/kage/CHEATSHEET.md` anytime.)

---

## Running `kage` (fixing "command not found")

The `kage` command lives in the project's venv. Pick ONE:

**A — install it globally once (recommended — then `kage` works from any folder):**
```bash
cd ~/Projects/kage
uv tool install --editable .
# if still "not found":  uv tool update-shell   then restart the terminal
kage status        # works from ANY folder, no activation needed
```

**B — activate the venv (per terminal session):**
```bash
cd ~/Projects/kage
source .venv/bin/activate
kage status
deactivate         # when done
```

**C — no activation, prefix each call:**
```bash
uv run --project ~/Projects/kage kage status
```

---

## Everyday commands
```bash
kage init                            # set up ~/.kage  (once)
kage remember "<note>" -p <project>  # save a note (asks to confirm; -y to skip)
kage import <folder> -p <project>    # bulk-add .md/.txt files  (--dry-run to preview)
kage list [-p <project>]             # browse saved notes
kage recall "<words>" [-p <project>] # keyword search
kage recall "<words>" --pipe         # copy matches to clipboard → paste into any AI
kage ask "<question>" [-p <project>] # answer using your notes  (full natural language)
kage ask "<question>" --cloud        # same, via Claude  (needs ANTHROPIC_API_KEY)
kage ask "<question>" --think        # let the local model reason first  (slower)
kage forget <id|prefix>              # delete one note (copy the id from `kage list`)
kage status                          # what's stored, where, which model
kage doctor                          # health check (store, index, Ollama)
kage --help                          # full command list
```

---

## Natural language in `kage ask`

`ask` accepts full conversational questions — no keyword format needed:
```bash
kage ask "when is my thesis draft due?" -p grad-school
kage ask "what were the key points from the architecture meeting?" -p work
kage ask "summarise everything I know about Layer 3e" -p kage
kage ask "what did I write about my sleep schedule?" -p life
```
It recalls the most relevant notes, sends them as context to the model, and answers.
`recall` and `remember` are keyword-driven; `ask` is the natural-language entry point.

---

## Which AI to use for what

| Task | Tool | Cost |
|------|------|------|
| Code questions, debugging | `kage ask` (local Qwen3) | free |
| Context-aware answers from your notes | `kage ask` | free |
| Hard reasoning, architecture decisions | `kage ask --cloud` or claude.ai (personal) | quota/free |
| Planning sessions, long-form reasoning | claude.ai personal account | free |
| Research drafts | Gemini (personal account) | free |
| API-powered Claude in kage | `kage ask --cloud` | uni quota |

**Token tip:** Claude Code sessions eat quota proportional to context length, not just output.
Keep sessions short and scoped to ONE task. Use `kage ask` (local) to answer code questions
instead of opening a new Claude Code session for them.

---

## Ollama (the local model — powers `kage ask`)
```bash
ollama ps                # is the model loaded? how much RAM?
ollama stop qwen3:14b    # unload → frees ~10 GB  (server stays running)
ollama serve             # start the server if it's down
# auto-unloads after ~5 min idle
```

---

## Dev / repo
```bash
cd ~/Projects/kage       # IMPORTANT: always cd here first before dev commands
uv sync                  # install/refresh dependencies
uv run pytest -q         # run the test suite  (must be in ~/Projects/kage)
git status               # what's changed
git switch main          # back to main
git switch -c cycle-N    # start a new cycle branch
```

---

## Where things live
- **Your notes** — `~/.kage/memory/*.md`  (plain markdown — yours, 100% local)
- **Index** — `~/.kage/indexes/kage.db`  (derived; rebuildable from the markdown)
- **The code** — `~/Projects/kage/src/kage/cli.py`
- **Config** — `~/.kage/config.json`  (set `model`, `cloud_model`, `ollama_url` here)
