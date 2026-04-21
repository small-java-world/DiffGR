from __future__ import annotations

from diffgr.group_utils import chunk_change_preview, group_sort_key, ordered_groups


class TestGroupSortKey:
    def test_order_first(self):
        a = {"id": "a", "name": "A", "order": 1}
        b = {"id": "b", "name": "B", "order": 2}
        assert group_sort_key(a) < group_sort_key(b)

    def test_none_order_last(self):
        a = {"id": "a", "name": "A", "order": 99}
        b = {"id": "b", "name": "B"}
        assert group_sort_key(a) < group_sort_key(b)

    def test_same_order_sort_by_name(self):
        a = {"id": "x", "name": "Alpha", "order": 1}
        b = {"id": "y", "name": "Beta", "order": 1}
        assert group_sort_key(a) < group_sort_key(b)


class TestOrderedGroups:
    def test_sorts_groups(self):
        doc = {
            "groups": [
                {"id": "b", "name": "B", "order": 2},
                {"id": "a", "name": "A", "order": 1},
            ]
        }
        result = ordered_groups(doc)
        assert [g["id"] for g in result] == ["a", "b"]

    def test_skips_non_dict(self):
        doc = {"groups": [{"id": "a", "order": 1}, "bad", None]}
        result = ordered_groups(doc)
        assert len(result) == 1


class TestChunkChangePreview:
    def test_add_delete_only(self):
        chunk = {
            "lines": [
                {"kind": "context", "text": "ctx"},
                {"kind": "add", "text": "new line"},
                {"kind": "delete", "text": "old line"},
            ]
        }
        result = chunk_change_preview(chunk)
        assert "add: new line" in result
        assert "delete: old line" in result
        assert "ctx" not in result

    def test_include_meta(self):
        chunk = {
            "lines": [
                {"kind": "context", "text": "ctx"},
                {"kind": "meta", "text": "@@ hunk"},
                {"kind": "add", "text": "new"},
            ]
        }
        result = chunk_change_preview(chunk, include_meta=True)
        assert "meta: @@ hunk" in result
        assert "ctx" not in result

    def test_max_lines(self):
        chunk = {
            "lines": [
                {"kind": "add", "text": f"line {i}"} for i in range(10)
            ]
        }
        result = chunk_change_preview(chunk, max_lines=3)
        assert result.count(" / ") == 2  # 3 items separated by " / "

    def test_empty_add_delete(self):
        chunk = {"lines": [{"kind": "context", "text": "only ctx"}]}
        assert chunk_change_preview(chunk) == "(no add/delete lines)"

    def test_empty_include_meta(self):
        chunk = {"lines": [{"kind": "context", "text": "only ctx"}]}
        assert chunk_change_preview(chunk, include_meta=True) == "(meta-only)"

    def test_blank_add_lines_skipped(self):
        chunk = {"lines": [{"kind": "add", "text": "  "}]}
        assert chunk_change_preview(chunk) == "(no add/delete lines)"
