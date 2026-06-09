# kage — Smoke Test Checklist

Use this after a cycle lands or before starting a new one. Keep the test data boring and synthetic.

## Local CLI

```bash
export KAGE_HOME="$(mktemp -d)/.kage"

uv run kage init
uv run kage remember "Cycle smoke fact: the test token is maple-42." -p smoke -y
uv run kage recall "maple" -p smoke
uv run kage list -p smoke
uv run kage status
uv run kage doctor
```

Expected:
- `recall` returns the `maple-42` note
- `status` shows one smoke note
- `doctor` is healthy, with warnings allowed for missing Ollama or missing cloud keys

## Local Ask

Requires Ollama running with the configured local model.

```bash
uv run kage ask "what is the test token?" -p smoke --no-sources
```

Expected:
- answer contains `maple-42`
- if Ollama is down, the command exits with the "ollama serve" hint

## Live Cloud Provider Smoke

Run live provider checks only with the isolated `KAGE_HOME` above. These commands send the dummy smoke note to the selected provider.

```bash
uv run kage ask "what is the test token?" -p smoke --cloud --provider openai --no-sources
uv run kage ask "what is the test token?" -p smoke --cloud --provider groq --no-sources
```

Optional, depending on which keys are available:

```bash
uv run kage ask "what is the test token?" -p smoke --cloud --provider claude --no-sources
uv run kage ask "what is the test token?" -p smoke --cloud --provider gemini --no-sources
uv run kage ask "what is the test token?" -p smoke --cloud --provider perplexity --no-sources
```

Expected:
- answer contains `maple-42`
- missing keys fail clearly with `<ENV_VAR> not set`
- `uv run kage doctor` shows `✓` for providers whose env vars are set and `·` for missing keys

## Cleanup

The commands above use a temporary `KAGE_HOME`. Closing the shell is enough. To remove it immediately:

```bash
rm -rf "$(dirname "$KAGE_HOME")"
unset KAGE_HOME
```
