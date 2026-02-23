import unittest

from diffgr.summary import summarize_document


class TestSummary(unittest.TestCase):
    def test_summarize_document_counts(self):
        doc = {
            "format": "diffgr",
            "version": 1,
            "meta": {
                "title": "UT",
                "createdAt": "2026-02-23T00:00:00Z",
                "source": {
                    "type": "git_compare",
                    "base": "main",
                    "head": "feature",
                    "baseSha": "a" * 40,
                    "headSha": "b" * 40,
                    "mergeBaseSha": "c" * 40,
                },
            },
            "groups": [
                {"id": "g1", "name": "G1", "order": 1},
                {"id": "g2", "name": "G2", "order": 2},
            ],
            "chunks": [
                {"id": "c1", "filePath": "a.txt", "old": {"start": 1, "count": 1}, "new": {"start": 1, "count": 1}, "lines": []},
                {"id": "c2", "filePath": "b.txt", "old": {"start": 1, "count": 1}, "new": {"start": 1, "count": 1}, "lines": []},
                {"id": "c3", "filePath": "c.txt", "old": {"start": 1, "count": 1}, "new": {"start": 1, "count": 1}, "lines": []},
            ],
            "assignments": {"g1": ["c1", "c2"], "g2": ["c2"]},
            "reviews": {
                "c1": {"status": "reviewed"},
                "c2": {"status": "ignored"},
                "c3": {"status": "unreviewed"},
            },
        }
        summary = summarize_document(doc)
        self.assertEqual(summary["chunkCount"], 3)
        self.assertEqual(summary["groupCount"], 2)

        # Coverage: c3 is unassigned; c2 is duplicated.
        cov = summary["coverage"]
        self.assertFalse(cov["ok"])
        self.assertEqual(cov["unassigned"], ["c3"])
        self.assertIn("c2", cov["duplicated"])

        # Overall review metrics: tracked excludes ignored.
        review = summary["review"]
        self.assertEqual(review["Tracked"], 2)
        self.assertEqual(review["Reviewed"], 1)
        self.assertEqual(review["Pending"], 1)

        groups = {g["id"]: g for g in summary["groups"]}
        self.assertEqual(groups["g1"]["total"], 2)
        self.assertEqual(groups["g1"]["tracked"], 1)
        self.assertEqual(groups["g1"]["reviewed"], 1)
        self.assertEqual(groups["g2"]["total"], 1)
        self.assertEqual(groups["g2"]["tracked"], 0)  # only c2 which is ignored


if __name__ == "__main__":
    unittest.main()

