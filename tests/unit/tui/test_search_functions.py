"""Tests for TUI search helper functions."""

import pytest

from symtest.core.test_case import TestCase
from symtest.tui.controllers.case_controller import (
    _substring_match,
    _regex_match,
    _fuzzy_score,
    _fuzzy_match,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tc(**kwargs) -> TestCase:
    """Shorthand to create a TestCase with defaults."""
    defaults = {
        "name": "test",
        "command": "",
        "args": [],
        "expected": {},
        "tags": [],
        "description": "",
    }
    defaults.update(kwargs)
    return TestCase(**defaults)


# ---------------------------------------------------------------------------
# _substring_match
# ---------------------------------------------------------------------------


class TestSubstringMatch:
    def test_match_in_name(self):
        assert _substring_match("hello", _tc(name="hello_world"))

    def test_match_case_insensitive(self):
        assert _substring_match("HELLO", _tc(name="hello_world"))

    def test_match_in_command(self):
        assert _substring_match("python", _tc(command="python3"))

    def test_match_in_args(self):
        assert _substring_match("script", _tc(args=["run", "script.py"]))

    def test_match_in_tags(self):
        assert _substring_match("smoke", _tc(tags=["smoke", "regression"]))

    def test_match_in_description(self):
        assert _substring_match("important", _tc(description="An important test"))

    def test_no_match(self):
        assert not _substring_match("xyz123", _tc(name="hello"))

    def test_empty_query_matches_all(self):
        """Empty string is contained in every string."""
        assert _substring_match("", _tc(name="hello"))

    def test_query_with_dot_literal(self):
        """Dot is a literal char, not a regex wildcard in substring mode."""
        assert _substring_match("test_case", _tc(name="my_test_case_extra"))


# ---------------------------------------------------------------------------
# _regex_match
# ---------------------------------------------------------------------------


class TestRegexMatch:
    def test_simple_regex(self):
        assert _regex_match(r"test\d", _tc(name="test1"))

    def test_regex_case_insensitive(self):
        assert _regex_match(r"HELLO", _tc(name="hello_world"))

    def test_regex_in_command(self):
        assert _regex_match(r"python\d", _tc(command="python3"))

    def test_regex_in_tags(self):
        assert _regex_match(r"smoke|reg", _tc(tags=["smoke_test"]))

    def test_regex_no_match(self):
        assert not _regex_match(r"test\d", _tc(name="hello"))

    def test_invalid_regex_returns_false(self):
        """Malformed regex should not raise, just return False."""
        assert not _regex_match(r"[unclosed", _tc(name="hello"))

    def test_full_match_pattern(self):
        """^ and $ anchors should work."""
        assert _regex_match(r"^hello$", _tc(name="hello"))
        assert not _regex_match(r"^hello$", _tc(name="hello_world"))

    def test_multiline_description(self):
        assert _regex_match(r"line2", _tc(description="line1\nline2\nline3"))


# ---------------------------------------------------------------------------
# _fuzzy_score
# ---------------------------------------------------------------------------


class TestFuzzyScore:
    def test_exact_match_scores_high(self):
        score = _fuzzy_score("hello", _tc(name="hello"))
        assert score > 0.5

    def test_no_match_scores_zero(self):
        score = _fuzzy_score("xyz", _tc(name="abcdef"))
        assert score == 0.0

    def test_partial_overlap(self):
        score = _fuzzy_score("hel", _tc(name="hello"))
        assert score > 0.0

    def test_name_weights_more_than_args(self):
        score_name = _fuzzy_score("script", _tc(name="script_runner"))
        score_args = _fuzzy_score("script", _tc(name="other", args=["script.py"]))
        assert score_name > score_args

    def test_two_char_partial_overlap(self):
        """Two-char prefix matches first bigram."""
        score = _fuzzy_score("he", _tc(name="hello"))
        assert score > 0.0

    def test_empty_query_scores_zero(self):
        score = _fuzzy_score("", _tc(name="hello"))
        assert score == 0.0

    def test_score_is_non_negative(self):
        score = _fuzzy_score("zxy", _tc(name="abc"))
        assert score >= 0.0


# ---------------------------------------------------------------------------
# _fuzzy_match
# ---------------------------------------------------------------------------


class TestFuzzyMatch:
    def test_returns_matching_indices(self):
        cases = [
            _tc(name="hello_world"),
            _tc(name="goodbye"),
            _tc(name="hello_again"),
        ]
        indices = _fuzzy_match("hello", cases)
        assert 0 in indices
        assert 2 in indices
        assert 1 not in indices

    def test_returns_sorted_by_score(self):
        cases = [
            _tc(name="abc"),
            _tc(name="document", description="test_and_more"),
            _tc(name="test_and_more"),
        ]
        indices = _fuzzy_match("test", cases)
        # Case[2] matches in name (weight 2.0) > Case[1] matches only in desc (weight 1.0)
        assert indices[0] == 2

    def test_threshold_filters_low_scores(self):
        cases = [
            _tc(name="hello"),
            _tc(name="h_xx_e_xx_l_xx_l_xx_o"),  # Low bigram overlap
        ]
        indices = _fuzzy_match("hello", cases, threshold=0.5)
        assert 0 in indices
        assert 1 not in indices

    def test_low_threshold_includes_more(self):
        cases = [_tc(name="hello"), _tc(name="zzz")]
        indices = _fuzzy_match("hello", cases, threshold=0.0)
        assert len(indices) >= 1

    def test_empty_cases(self):
        assert _fuzzy_match("hello", []) == []

    def test_all_below_threshold(self):
        cases = [_tc(name="a"), _tc(name="b")]
        indices = _fuzzy_match("xyz", cases, threshold=0.5)
        assert indices == []
