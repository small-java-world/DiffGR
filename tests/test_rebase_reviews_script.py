import json
import tempfile
import unittest
from pathlib import Path

from scripts.rebase_reviews import main


def _make_doc(*, title: str, groups: list[dict], chunks: list[dict], assignments: dict, reviews: dict) -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {"title": title, "createdAt": "2026-02-23T00:00:00Z"},
        "groups": groups,
        "chunks": chunks,
        "assignments": assignments,
        "reviews": reviews,
    }


class TestRebaseReviewsScript(unittest.TestCase):
    def test_history_impact_scope_uses_rebased_output_coverage(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            old_path = root / "old.diffgr.json"
            new_path = root / "new.diffgr.json"
            out_path = root / "out.diffgr.json"

            old_doc = _make_doc(
                title="old",
                groups=[{"id": "g1", "name": "G1", "order": 1}],
                chunks=[
                    {
                        "id": "old1",
                        "filePath": "src/a.ts",
                        "old": {"start": 1, "count": 1},
                        "new": {"start": 1, "count": 1},
                        "lines": [{"kind": "add", "text": "x", "oldLine": None, "newLine": 1}],
                        "fingerprints": {"stable": "s1", "strong": "t1"},
                    }
                ],
                assignments={"g1": ["old1"]},
                reviews={"old1": {"status": "reviewed"}},
            )
            new_doc = _make_doc(
                title="new",
                groups=[{"id": "g-all", "name": "All", "order": 1}],
                chunks=[
                    {
                        "id": "new1",
                        "filePath": "src/a.ts",
                        "old": {"start": 10, "count": 1},
                        "new": {"start": 10, "count": 1},
                        "lines": [{"kind": "add", "text": "x", "oldLine": None, "newLine": 10}],
                        "fingerprints": {"stable": "s1", "strong": "u1"},
                    },
                    {
                        "id": "new2",
                        "filePath": "src/b.ts",
                        "old": {"start": 1, "count": 1},
                        "new": {"start": 1, "count": 1},
                        "lines": [{"kind": "add", "text": "y", "oldLine": None, "newLine": 1}],
                        "fingerprints": {"stable": "s2", "strong": "u2"},
                    },
                ],
                assignments={"g-all": ["new1", "new2"]},
                reviews={},
            )
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            code = main(
                [
                    "--old",
                    str(old_path),
                    "--new",
                    str(new_path),
                    "--output",
                    str(out_path),
                    "--history-label",
                    "ut",
                ]
            )
            self.assertEqual(code, 0)

            out_doc = json.loads(out_path.read_text(encoding="utf-8"))
            scope = out_doc.get("meta", {}).get("x-impactScope", {})
            self.assertIsInstance(scope, dict)
            coverage = scope.get("coverageNew", {})
            self.assertEqual(coverage.get("ok"), False)
            self.assertIn("new2", coverage.get("unassigned", []))


if __name__ == "__main__":
    unittest.main()

