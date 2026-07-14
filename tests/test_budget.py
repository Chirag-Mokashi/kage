"""Tests for kage.budget (Cycle 31 Slice 5) -- output-buffer reservation."""
from __future__ import annotations

from kage import budget


def test_estimate_tokens_len_over_four():
    assert budget.estimate_tokens("a" * 40) == 10


def test_estimate_tokens_empty_string():
    assert budget.estimate_tokens("") == 0


def test_trim_notes_to_budget_no_trim_when_it_fits():
    parts = ["short note one", "short note two"]
    result = budget.trim_notes_to_budget(parts, fixed_estimate=10, num_ctx=16384)
    assert result == parts


def test_trim_notes_to_budget_drops_trailing_notes_until_it_fits():
    parts = ["a" * 4000, "b" * 4000, "c" * 4000]
    result = budget.trim_notes_to_budget(parts, fixed_estimate=0, num_ctx=2000, reserved_output=0)
    assert result == ["a" * 4000, "b" * 4000]


def test_trim_notes_to_budget_can_drop_all_notes():
    parts = ["a" * 100000]
    result = budget.trim_notes_to_budget(parts, fixed_estimate=0, num_ctx=100, reserved_output=0)
    assert result == []


def test_trim_notes_to_budget_empty_input_returns_empty():
    assert budget.trim_notes_to_budget([], fixed_estimate=0, num_ctx=16384) == []


def test_num_predict_for_returns_reserved_when_smaller_than_ctx():
    assert budget.num_predict_for(16384, 1500) == 1500


def test_num_predict_for_capped_at_num_ctx_when_reserved_exceeds_it():
    assert budget.num_predict_for(100, 1500) == 100


def test_num_predict_for_uses_default_reserved_output():
    assert budget.num_predict_for(16384) == budget.DEFAULT_RESERVED_OUTPUT
