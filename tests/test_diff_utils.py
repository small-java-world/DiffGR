from __future__ import annotations

import pytest

from diffgr.diff_utils import line_anchor_key, normalize_line_number


class TestNormalizeLineNumber:
    def test_none(self):
        assert normalize_line_number(None) is None

    def test_int(self):
        assert normalize_line_number(42) == 42

    def test_string_int(self):
        assert normalize_line_number("7") == 7

    def test_invalid_string(self):
        assert normalize_line_number("abc") is None

    def test_float(self):
        assert normalize_line_number(3.9) == 3

    def test_empty_string(self):
        assert normalize_line_number("") is None


class TestLineAnchorKey:
    def test_basic(self):
        assert line_anchor_key("add", None, 10) == "add::10"

    def test_delete(self):
        assert line_anchor_key("delete", 5, None) == "delete:5:"

    def test_context(self):
        assert line_anchor_key("context", 3, 7) == "context:3:7"

    def test_none_both(self):
        assert line_anchor_key("meta", None, None) == "meta::"

    def test_string_line_numbers(self):
        assert line_anchor_key("add", "10", "20") == "add:10:20"

    def test_normalizes_values(self):
        assert line_anchor_key("add", "abc", 5) == "add::5"
