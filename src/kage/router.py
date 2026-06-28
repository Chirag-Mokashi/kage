_CLASSIFY_RULES: list[tuple[str, list[str]]] = [
    ("code", [
        "compile", "debug", "refactor", "implement",
        "write a function", "write a script", "write a class",
        "fix the bug", "fix this error", "traceback", "syntax error",
        "unit test", "pytest", "def ", "class ",
    ]),
    ("research", [
        "search for", "look up", "latest news", "current news", "recent news",
        "find online", "up to date", "as of today", "breaking news",
    ]),
    ("multimodal", [
        "image", "photo", "picture", "video", "audio", "screenshot",
        "diagram", "chart", ".jpg", ".png", ".gif", ".mp4", ".pdf",
        "describe this", "what do you see",
    ]),
    ("reasoning", [
        "analyze", "compare", "explain why", "think through", "pros and cons",
        "trade-off", "should i", "what would happen if", "step by step",
        "design", "architect", "review", "evaluate", "is this correct",
    ]),
]

# ponytail: v1 hardcoded; Layer 6 makes this a learned lookup table
_ROUTING_TABLE: dict[str, list[str]] = {
    "code":       ["claude-opus", "gemini-3-1-pro", "gemini-3-5-flash"],
    "reasoning":  ["claude-opus", "gemini-3-1-pro", "openrouter-general"],
    "research":   ["gemini-research"],
    "multimodal": ["gemini-3-5-flash", "gemini"],
    "chat":       [],
}


def _classify(question: str) -> str:
    """Return the task class for question. Priority order: code > research > multimodal > reasoning > chat."""
    q = question.lower()
    for cls, keywords in _CLASSIFY_RULES:
        if any(kw in q for kw in keywords):
            return cls
    return "chat"


def _candidates(task_class: str, cfg: dict) -> list[str]:
    """Return ordered provider names for task_class. User cfg.routing_table rows replace defaults."""
    # ponytail: custom routing_table keys accepted silently; upgrade = validation + warning
    user_table: dict[str, list[str]] = cfg.get("routing_table", {})
    table = {**_ROUTING_TABLE, **user_table}
    return list(table.get(task_class, []))
