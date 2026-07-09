from kage.router import _classify, _candidates, _local_eligible


def test_classify_code_keyword():
    assert _classify("can you debug this traceback?") == "code"


def test_classify_code_keyword_refactor():
    assert _classify("please refactor this function") == "code"


def test_classify_research_keyword():
    assert _classify("search for the latest AI news") == "research"


def test_classify_multimodal_keyword():
    assert _classify("describe this image") == "multimodal"


def test_classify_multimodal_extension():
    assert _classify("here is a file.png to analyze") == "multimodal"


def test_classify_reasoning_keyword():
    assert _classify("analyze the pros and cons of this approach") == "reasoning"


def test_classify_default_chat():
    assert _classify("hello how are you") == "chat"


def test_classify_empty_string():
    assert _classify("") == "chat"


def test_classify_what_is_not_research():
    # "what is" must NOT trigger research class (too generic)
    assert _classify("what is the capital of france") != "research"


def test_classify_priority_code_over_research():
    # "compile" (code) appears before "latest news" (research) in priority order
    # so code wins when both keywords are present
    assert _classify("compile the latest news scraper") == "code"


def test_classify_case_insensitive():
    assert _classify("DEBUG this issue") == "code"


def test_candidates_code_class():
    result = _candidates("code", {})
    assert result[0] == "claude-opus"
    assert "gemini-3-1-pro" in result


def test_candidates_research_class():
    result = _candidates("research", {})
    assert result == ["gemini-research"]


def test_candidates_chat_class():
    assert _candidates("chat", {}) == []


def test_candidates_unknown_class():
    assert _candidates("nonexistent", {}) == []


def test_candidates_config_override_replaces():
    cfg = {"routing_table": {"reasoning": ["groq", "mistral"]}}
    result = _candidates("reasoning", cfg)
    assert result == ["groq", "mistral"]
    # override replaces, not extends
    assert "claude-opus" not in result


def test_candidates_config_override_only_affects_named_class():
    cfg = {"routing_table": {"reasoning": ["groq"]}}
    # code class should be unchanged
    result = _candidates("code", cfg)
    assert result[0] == "claude-opus"


def test_candidates_returns_copy():
    # modifying the returned list should not affect the internal table
    result = _candidates("code", {})
    result.clear()
    assert len(_candidates("code", {})) > 0


def test_local_eligible_code():
    assert _local_eligible("code") is True


def test_local_eligible_reasoning():
    assert _local_eligible("reasoning") is True


def test_local_eligible_research_false():
    assert _local_eligible("research") is False


def test_local_eligible_multimodal_false():
    assert _local_eligible("multimodal") is False


def test_local_eligible_chat_false():
    assert _local_eligible("chat") is False
