"""budget.py -- Cycle 31 Slice 5: output-buffer reservation for local Ollama
dispatch. One shared pool -- input and output tokens share num_ctx, so
without an explicit reservation the model can be asked to write into space
that was never held open for it. See docs/cycle-31-3a-warm-context.md,
"Budget math (absorbs the 29.2 output-buffer candidate)".
"""
from __future__ import annotations

DEFAULT_RESERVED_OUTPUT = 1500


def estimate_tokens(text: str) -> int:
    """ponytail: len/4 estimate, not a real tokenizer count -- the same
    ceiling as the 29.1 num_ctx tripwire. Upgrade: a real tokenizer if
    estimates ever visibly diverge from Ollama's own prompt_eval_count.
    """
    return len(text) // 4


def trim_notes_to_budget(
    context_parts: list[str],
    fixed_estimate: int,
    num_ctx: int,
    reserved_output: int = DEFAULT_RESERVED_OUTPUT,
) -> list[str]:
    """Drop trailing retrieved notes -- least-relevant first, since callers
    already order by rank -- until `fixed_estimate` (system + warm bar +
    question) plus the remaining notes fits within num_ctx - reserved_output.
    Never raises; an already-tiny context_parts is returned unchanged.
    """
    budget_tokens = num_ctx - reserved_output
    parts = list(context_parts)
    while parts and fixed_estimate + estimate_tokens("\n\n".join(parts)) > budget_tokens:
        parts.pop()
    return parts


def num_predict_for(num_ctx: int, reserved_output: int = DEFAULT_RESERVED_OUTPUT) -> int:
    """The num_predict cap to send Ollama -- never larger than the space
    actually reserved for output, so the model is never asked to write into
    absent space.
    """
    return min(reserved_output, num_ctx)
