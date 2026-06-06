"""
Tests for the helper functions in llm_client.py:

- _parse_json_response(content)  — three-tier JSON extraction:
    tier 1: pure JSON literal
    tier 2: JSON inside ```json ... ``` markdown fence
    tier 3: JSON inside a { ... } brace region in prose
    else:   raise ValueError

- _extract_state_mutations_dict(content) — same idea but only returns
  if the parsed dict has a `state_mutations` key.

- generate_scene_response(system_prompt, user_input, ...) — backwards-
  compat module-level helper used by older code paths.

- build_few_shots(examples) — passthrough identity with a docstring
  contract check.

These tests use no network, no LLM API — they exercise the parsing
heuristics which are the bulk of the previously-uncovered code.
"""
from __future__ import annotations

import pytest

from llm_client import (
    _extract_state_mutations_dict,
    _parse_json_response,
    build_few_shots,
)


class TestParseJsonResponse:
    """_parse_json_response: tier 1 = direct JSON.parse."""

    def test_tier1_pure_json(self) -> None:
        assert _parse_json_response('{"a": 1}') == {"a": 1}

    def test_tier1_nested(self) -> None:
        assert _parse_json_response('{"a": {"b": [1, 2, 3]}}') == {"a": {"b": [1, 2, 3]}}

    def test_tier2_markdown_fenced_json(self) -> None:
        # Markdown code fence containing JSON
        content = 'Here is the response:\n```json\n{"a": 1}\n```\nThanks!'
        assert _parse_json_response(content) == {"a": 1}

    def test_tier2_fenced_no_language_tag(self) -> None:
        # Plain ``` without 'json' tag
        content = '```\n{"a": 1}\n```'
        assert _parse_json_response(content) == {"a": 1}

    def test_tier3_brace_in_prose(self) -> None:
        # JSON object buried in prose
        content = 'The answer is {"x": 42} as you can see.'
        assert _parse_json_response(content) == {"x": 42}

    def test_tier3_multiline_brace(self) -> None:
        content = 'Look at this:\n{\n  "a": 1,\n  "b": 2\n}\nEnd.'
        assert _parse_json_response(content) == {"a": 1, "b": 2}

    def test_unparseable_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse JSON"):
            _parse_json_response("this is not JSON at all")

    def test_tier2_invalid_json_in_fence_falls_through(self) -> None:
        # Bad JSON in fence, no brace region -> raises
        content = "```json\n{not valid}\n```"
        with pytest.raises(ValueError, match="Could not parse JSON"):
            _parse_json_response(content)


class TestExtractStateMutationsDict:
    """_extract_state_mutations_dict returns the dict only if it has
    a `state_mutations` key. Used to gate F3 contract validation."""

    def test_dict_with_state_mutations_key(self) -> None:
        content = '{"state_mutations": [{"type": "tag_add"}], "narrative": "ok"}'
        result = _extract_state_mutations_dict(content)
        assert result is not None
        assert "state_mutations" in result
        assert result["narrative"] == "ok"

    def test_dict_without_state_mutations_key_returns_none(self) -> None:
        # Has narrative but no state_mutations — not a state contract response
        content = '{"narrative": "just a story"}'
        assert _extract_state_mutations_dict(content) is None

    def test_fenced_with_state_mutations(self) -> None:
        content = '```json\n{"state_mutations": [], "x": 1}\n```'
        result = _extract_state_mutations_dict(content)
        assert result == {"state_mutations": [], "x": 1}

    def test_unparseable_returns_none(self) -> None:
        # Doesn't raise — just returns None
        assert _extract_state_mutations_dict("not JSON at all") is None

    def test_empty_state_mutations_array(self) -> None:
        # state_mutations: [] is valid (means "no changes this turn")
        content = '{"state_mutations": []}'
        result = _extract_state_mutations_dict(content)
        assert result == {"state_mutations": []}


class TestBuildFewShots:
    """build_few_shots is a passthrough but with type validation."""

    def test_empty_list(self) -> None:
        assert build_few_shots([]) == []

    def test_passthrough_single(self) -> None:
        examples = [{"role": "user", "content": "hi"}]
        assert build_few_shots(examples) == examples

    def test_passthrough_multiple(self) -> None:
        examples = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ]
        assert build_few_shots(examples) == examples
