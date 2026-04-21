from __future__ import annotations

from diffgr.viewer_core import build_chunk_map


class TestBuildChunkMap:
    def test_from_doc(self):
        doc = {
            "chunks": [
                {"id": "c1", "filePath": "a.py"},
                {"id": "c2", "filePath": "b.py"},
            ]
        }
        result = build_chunk_map(doc)
        assert set(result.keys()) == {"c1", "c2"}
        assert result["c1"]["filePath"] == "a.py"

    def test_from_list(self):
        chunks = [
            {"id": "c1", "filePath": "a.py"},
            {"id": "c2", "filePath": "b.py"},
        ]
        result = build_chunk_map(chunks)
        assert set(result.keys()) == {"c1", "c2"}

    def test_filters_non_dict_entries(self):
        doc = {
            "chunks": [
                {"id": "c1"},
                "not a dict",
                None,
                42,
                {"id": "c2"},
            ]
        }
        result = build_chunk_map(doc)
        assert set(result.keys()) == {"c1", "c2"}

    def test_filters_empty_id(self):
        doc = {
            "chunks": [
                {"id": "c1"},
                {"id": ""},
                {"other": "no id key"},
                {"id": "c2"},
            ]
        }
        result = build_chunk_map(doc)
        assert set(result.keys()) == {"c1", "c2"}

    def test_empty_doc(self):
        assert build_chunk_map({}) == {}
        assert build_chunk_map({"chunks": []}) == {}
        assert build_chunk_map([]) == {}

    def test_id_coerced_to_str(self):
        doc = {"chunks": [{"id": 123, "filePath": "num.py"}]}
        result = build_chunk_map(doc)
        assert "123" in result
        assert result["123"]["filePath"] == "num.py"

    def test_none_chunks_key(self):
        doc = {"chunks": None}
        assert build_chunk_map(doc) == {}
