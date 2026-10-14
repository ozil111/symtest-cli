"""Tests for the JSONC parser (symtest.config.jsonc)."""

import io
import json

import pytest

from symtest.config import jsonc


class TestStripComments:
    def test_line_comment(self):
        assert json.loads(jsonc.strip_jsonc('{ // note\n"a": 1\n}')) == {"a": 1}

    def test_block_comment(self):
        assert json.loads(
            jsonc.strip_jsonc('{ /* multi\nline */ "a": 1 }')
        ) == {"a": 1}

    def test_comment_only_object(self):
        assert jsonc.loads("{\n// no keys\n}") == {}

    def test_comment_at_eof_without_newline(self):
        assert jsonc.loads('{"a": 1} // tail') == {"a": 1}

    def test_unterminated_block_comment(self):
        assert jsonc.loads('{"a": 1} /* unterminated') == {"a": 1}

    def test_strip_preserves_length_and_newlines(self):
        src = '{\n// comment line\n"a": 1\n}\n'
        stripped = jsonc.strip_jsonc(src)
        assert len(stripped) == len(src)
        assert stripped.count("\n") == src.count("\n")

    def test_line_comment_stops_at_crlf(self):
        stripped = jsonc.strip_jsonc('{ // c1\r\n"a": 1\r\n}')
        assert json.loads(stripped) == {"a": 1}
        assert "\r\n" in stripped


class TestTrailingCommas:
    def test_array_trailing_comma(self):
        assert jsonc.loads('[1, 2, 3,]') == [1, 2, 3]

    def test_object_trailing_comma(self):
        assert jsonc.loads('{"a": 1,}') == {"a": 1}

    def test_nested_trailing_commas(self):
        src = '{"list": [1, 2,], "map": {"x": 1,},}'
        assert jsonc.loads(src) == {"list": [1, 2], "map": {"x": 1}}

    def test_comma_before_commented_close(self):
        src = '{"a": [1, 2,]\n// disabled case\n}'
        assert jsonc.loads(src) == {"a": [1, 2]}


class TestStringAwareness:
    def test_comment_marker_inside_string(self):
        assert jsonc.loads('{"a": "ham // egg"}') == {"a": "ham // egg"}

    def test_block_marker_inside_string(self):
        assert jsonc.loads('{"a": "not /* a comment */"}') == {
            "a": "not /* a comment */"
        }

    def test_url_inside_string(self):
        url = "https://example.com/a/*b"
        assert jsonc.loads('{"url": "%s"}' % url) == {"url": url}

    def test_escaped_quote_then_comment(self):
        src = '{"a": "say \\"hi\\"" // trailing\n}'
        assert jsonc.loads(src) == {"a": 'say "hi"'}

    def test_trailing_comma_like_sequence_inside_string(self):
        assert jsonc.loads('{"a": "x, }"}') == {"a": "x, }"}


class TestAPI:
    def test_loads_bytes(self):
        assert jsonc.loads(b'{"a": 1}') == {"a": 1}

    def test_load_file_object(self):
        f = io.StringIO('{"a": 1} // c')
        assert jsonc.load(f) == {"a": 1}

    def test_plain_json_unchanged(self):
        assert jsonc.loads('{"a": [1, 2], "b": null}') == {
            "a": [1, 2], "b": None
        }

    def test_error_positions_match_source(self):
        """Stripped characters keep their positions, so JSON error
        line numbers refer to the original file."""
        src = (
            "{\n"
            '  "a": 1, // ok\n'
            "  /* block\n"
            "     comment */\n"
            '  "b": <error>,\n'
            "}\n"
        )
        with pytest.raises(json.JSONDecodeError) as exc_info:
            jsonc.loads(src)
        assert exc_info.value.lineno == 5
