import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr import viewer_core as view_diffgr


def make_doc():
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "Example", "createdAt": "2026-02-22T00:00:00Z"},
        "groups": [
            {"id": "g1", "name": "Core", "order": 1},
            {"id": "g2", "name": "Edge", "order": 2},
        ],
        "chunks": [
            {
                "id": "c1",
                "filePath": "src/a.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 2},
                "lines": [],
            },
            {
                "id": "c2",
                "filePath": "src/b.ts",
                "old": {"start": 3, "count": 2},
                "new": {"start": 3, "count": 2},
                "lines": [],
            },
            {
                "id": "c3",
                "filePath": "src/c.ts",
                "old": {"start": 8, "count": 1},
                "new": {"start": 8, "count": 1},
                "lines": [],
            },
        ],
        "assignments": {"g1": ["c1", "c2"], "g2": ["c3"]},
        "reviews": {
            "c1": {"status": "reviewed"},
            "c2": {"status": "needsReReview"},
            "c3": {"status": "ignored"},
        },
    }


class TestViewDiffgr(unittest.TestCase):
    def test_validate_document_accepts_valid_doc(self):
        warnings = view_diffgr.validate_document(make_doc())
        self.assertEqual(warnings, [])

    def test_validate_document_reports_warnings_for_unknown_refs(self):
        doc = make_doc()
        doc["assignments"]["ghost"] = ["c1"]
        doc["assignments"]["g1"].append("missing")
        doc["reviews"]["missing-review"] = {"status": "reviewed"}
        warnings = view_diffgr.validate_document(doc)
        self.assertTrue(any("Assignment key not in groups: ghost" in item for item in warnings))
        self.assertTrue(any("Assigned chunk id not found: missing" in item for item in warnings))
        self.assertTrue(any("Review key chunk id not found: missing-review" in item for item in warnings))

    def test_validate_document_warns_when_group_assignments_key_missing(self):
        doc = make_doc()
        doc["assignments"].pop("g2", None)
        warnings = view_diffgr.validate_document(doc)
        self.assertTrue(any("Group missing assignments entry: g2" in item for item in warnings))

    def test_build_indexes_defaults_invalid_status_to_unreviewed(self):
        doc = make_doc()
        doc["reviews"]["c2"] = {"status": "invalid-status"}
        chunk_map, status_map = view_diffgr.build_indexes(doc)
        self.assertEqual(set(chunk_map.keys()), {"c1", "c2", "c3"})
        self.assertEqual(status_map["c2"], "unreviewed")

    def test_compute_metrics_excludes_ignored_from_tracked(self):
        doc = make_doc()
        _, status_map = view_diffgr.build_indexes(doc)
        metrics = view_diffgr.compute_metrics(doc, status_map)
        self.assertEqual(metrics["Unassigned"], 0)
        self.assertEqual(metrics["Tracked"], 2)
        self.assertEqual(metrics["Reviewed"], 1)
        self.assertEqual(metrics["Pending"], 1)
        self.assertAlmostEqual(metrics["CoverageRate"], 0.5)

    def test_filter_chunks_by_group_status_and_file(self):
        doc = make_doc()
        chunk_map, status_map = view_diffgr.build_indexes(doc)
        filtered = view_diffgr.filter_chunks(
            doc=doc,
            chunk_map=chunk_map,
            status_map=status_map,
            group_id="g1",
            chunk_id=None,
            status_filter="needsReReview",
            file_contains="b.ts",
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "c2")

    def test_filter_chunks_raises_for_unknown_group(self):
        doc = make_doc()
        chunk_map, status_map = view_diffgr.build_indexes(doc)
        with self.assertRaises(LookupError):
            view_diffgr.filter_chunks(
                doc=doc,
                chunk_map=chunk_map,
                status_map=status_map,
                group_id="unknown",
                chunk_id=None,
                status_filter=None,
                file_contains=None,
            )

    def test_filter_chunks_allows_known_group_without_assignments_key(self):
        doc = make_doc()
        doc["assignments"].pop("g2", None)
        chunk_map, status_map = view_diffgr.build_indexes(doc)
        filtered = view_diffgr.filter_chunks(
            doc=doc,
            chunk_map=chunk_map,
            status_map=status_map,
            group_id="g2",
            chunk_id=None,
            status_filter=None,
            file_contains=None,
        )
        self.assertEqual(filtered, [])

    def test_resolve_input_path_falls_back_to_search_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            nested = repo_root / "nested"
            nested.mkdir(parents=True, exist_ok=True)
            target = repo_root / "doc.diffgr.json"
            target.write_text("{}", encoding="utf-8")

            old_cwd = Path.cwd()
            try:
                os.chdir(nested)
                resolved = view_diffgr.resolve_input_path(Path("doc.diffgr.json"), search_roots=[repo_root])
            finally:
                os.chdir(old_cwd)

            self.assertEqual(resolved, target.resolve())


if __name__ == "__main__":
    unittest.main()
