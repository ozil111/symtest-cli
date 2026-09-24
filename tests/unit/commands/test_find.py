"""Tests for the ``symtest find`` command (search helpers + CLI handler).

Search helpers were moved verbatim from the retired TUI CaseController; the
test cases below are the ported originals plus new CLI-level coverage
(exit codes, tag filter, JSON output).
"""

import json
import re

import pytest

from symtest.commands.find import (
    _substring_match,
    _regex_match,
    _fuzzy_score,
    _fuzzy_match,
    search_cases,
    run_find,
)
from symtest.core.test_case import TestCase


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
    """``_regex_match`` consumes a compiled pattern (compiled once per
    search in ``search_cases``)."""

    @staticmethod
    def _pat(query):
        return re.compile(query, re.IGNORECASE)

    def test_simple_regex(self):
        assert _regex_match(self._pat(r"test\d"), _tc(name="test1"))

    def test_regex_case_insensitive(self):
        assert _regex_match(self._pat(r"HELLO"), _tc(name="hello_world"))

    def test_regex_in_command(self):
        assert _regex_match(self._pat(r"python\d"), _tc(command="python3"))

    def test_regex_in_tags(self):
        assert _regex_match(self._pat(r"smoke|reg"), _tc(tags=["smoke_test"]))

    def test_regex_no_match(self):
        assert not _regex_match(self._pat(r"test\d"), _tc(name="hello"))

    def test_full_match_pattern(self):
        """^ and $ anchors should work."""
        assert _regex_match(self._pat(r"^hello$"), _tc(name="hello"))
        assert not _regex_match(self._pat(r"^hello$"), _tc(name="hello_world"))

    def test_multiline_description(self):
        assert _regex_match(self._pat(r"line2"), _tc(description="line1\nline2\nline3"))


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


# ---------------------------------------------------------------------------
# search_cases (tag filter + mode dispatch)
# ---------------------------------------------------------------------------


class TestSearchCases:
    def test_substring_mode_default(self):
        cases = [_tc(name="login_test"), _tc(name="logout_test")]
        assert search_cases(cases, "login") == [0]

    def test_invalid_regex_matches_nothing(self):
        """Malformed regex should not raise, just match nothing."""
        cases = [_tc(name="hello")]
        assert search_cases(cases, "[unclosed", mode="regex") == []

    def test_empty_query_lists_all_in_every_mode(self):
        """Empty pattern short-circuits: same semantics for all modes."""
        cases = [_tc(name="a"), _tc(name="b")]
        for mode in ("substring", "fuzzy", "regex"):
            assert search_cases(cases, "", mode=mode) == [0, 1]

    def test_regex_mode(self):
        cases = [_tc(name="case1"), _tc(name="case2")]
        assert search_cases(cases, r"case\d", mode="regex") == [0, 1]

    def test_fuzzy_mode_ranks_by_score(self):
        cases = [_tc(name="hello"), _tc(name="hexlo")]
        indices = search_cases(cases, "hello", mode="fuzzy")
        assert indices[0] == 0

    def test_tag_filter_narrows_results(self):
        cases = [_tc(name="a", tags=["smoke"]), _tc(name="b", tags=["regression"])]
        assert search_cases(cases, "", tags=["smoke"]) == [0]

    def test_tag_filter_or_relationship(self):
        cases = [
            _tc(name="a", tags=["smoke"]),
            _tc(name="b", tags=["regression"]),
            _tc(name="c", tags=["other"]),
        ]
        assert search_cases(cases, "", tags=["smoke", "regression"]) == [0, 1]

    def test_tag_filter_applies_after_query(self):
        cases = [
            _tc(name="login_a", tags=["smoke"]),
            _tc(name="login_b", tags=["other"]),
        ]
        assert search_cases(cases, "login", tags=["smoke"]) == [0]


# ---------------------------------------------------------------------------
# CLI handler (run_find)
# ---------------------------------------------------------------------------


@pytest.fixture
def config_file(tmp_path):
    cfg = {
        "test_cases": [
            {
                "name": "login_ok",
                "execution": {"command": "echo", "args": ["login"], "timeout": 30},
                "expected": {"return_code": 0},
                "tags": ["smoke"],
            },
            {
                "name": "logout_ok",
                "execution": {"command": "echo", "args": ["logout"]},
                "expected": {"return_code": 0},
                "tags": ["regression"],
            },
        ],
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def _args(config_file, pattern, **extra):
    import argparse

    return argparse.Namespace(
        config_file=str(config_file),
        pattern=pattern,
        mode=extra.get("mode", "substring"),
        tag=extra.get("tag"),
        workspace=extra.get("workspace"),
        output_format=extra.get("output_format", "text"),
    )


class TestRunFind:
    def test_match_returns_zero(self, config_file, capsys):
        assert run_find(_args(config_file, "login")) == 0
        out = capsys.readouterr().out
        assert "login_ok" in out
        assert "logout_ok" not in out

    def test_no_match_returns_one(self, config_file, capsys):
        assert run_find(_args(config_file, "zzz_nonexistent")) == 1
        out = capsys.readouterr().out
        assert "No test cases match" in out

    def test_empty_pattern_lists_all(self, config_file, capsys):
        assert run_find(_args(config_file, "")) == 0
        out = capsys.readouterr().out
        assert "login_ok" in out
        assert "logout_ok" in out

    def test_missing_config_returns_two(self, tmp_path, capsys):
        assert run_find(_args(tmp_path / "nope.json", "login")) == 2

    def test_tag_filter(self, config_file, capsys):
        assert run_find(_args(config_file, "", tag=["smoke"])) == 0
        out = capsys.readouterr().out
        assert "login_ok" in out
        assert "logout_ok" not in out

    def test_json_output(self, config_file, capsys):
        assert run_find(_args(config_file, "login", output_format="json")) == 0
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == 1
        assert rows[0]["name"] == "login_ok"
        assert rows[0]["command"] == "echo"
        assert rows[0]["tags"] == ["smoke"]
        assert rows[0]["timeout"] == 30
        assert rows[0]["mode"] == "single"

    def test_import_expansion(self, tmp_path, capsys):
        """find auto-expands import references before searching."""
        sub = tmp_path / "sub.json"
        sub.write_text(json.dumps({"test_cases": [
            {"name": "deep_case",
             "execution": {"command": "echo", "args": ["hi"]},
             "expected": {"return_code": 0}},
        ]}), encoding="utf-8")
        main = tmp_path / "main.json"
        main.write_text(json.dumps({"test_cases": [{"import": "sub.json"}]}),
                        encoding="utf-8")

        assert run_find(_args(main, "deep_case")) == 0
        assert "deep_case" in capsys.readouterr().out
