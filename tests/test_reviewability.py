from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.reviewability import compute_all_group_reviewability, compute_group_reviewability  # noqa: E402
from scripts.summarize_reviewability import main as summarize_reviewability_main  # noqa: E402


class TestReviewability(unittest.TestCase):
    def _doc(self, *, group_briefs: dict | None = None, reviews: dict | None = None, chunks: list | None = None, assignments: dict | None = None) -> dict:
        chunks = chunks or [
            {
                "id": "c1",
                "filePath": "src/auth.ts",
                "old": {"start": 1, "count": 2},
                "new": {"start": 1, "count": 2},
                "lines": [
                    {"kind": "delete", "text": "old token"},
                    {"kind": "add", "text": "new token"},
                ],
            },
            {
                "id": "c2",
                "filePath": "src/api.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 1},
                "lines": [{"kind": "add", "text": "return ok"}],
            },
        ]
        return {
            "format": "diffgr",
            "version": 1,
            "meta": {"title": "UT Reviewability", "source": {"headSha": "abc123"}},
            "groups": [{"id": "g1", "name": "Auth", "order": 1}],
            "chunks": chunks,
            "assignments": assignments or {"g1": ["c1", "c2"]},
            "reviews": reviews or {"c1": {"status": "needsReReview"}, "c2": {"status": "reviewed"}},
            "groupBriefs": group_briefs or {},
        }

    def test_needs_handoff_without_summary_and_evidence(self):
        row = compute_group_reviewability(self._doc(), "g1")
        self.assertEqual(row["verdict"], "needs_handoff")
        self.assertIn("missing summary", row["reasons"])
        self.assertIn("missing testEvidence", row["reasons"])

    def test_dense_group_with_handoff_present(self):
        chunks = []
        assignments = {"g1": []}
        reviews = {}
        for idx in range(7):
            cid = f"c{idx+1}"
            chunks.append(
                {
                    "id": cid,
                    "filePath": f"src/{idx}.ts",
                    "old": {"start": 1, "count": 1},
                    "new": {"start": 1, "count": 1},
                    "lines": [{"kind": "add", "text": f"line {idx}"}],
                }
            )
            assignments["g1"].append(cid)
            reviews[cid] = {"status": "reviewed"}
        row = compute_group_reviewability(
            self._doc(
                chunks=chunks,
                assignments=assignments,
                reviews=reviews,
                group_briefs={"g1": {"summary": "handoff", "focusPoints": ["fp"], "testEvidence": ["te"]}},
            ),
            "g1",
        )
        self.assertEqual(row["verdict"], "dense")

    def test_needs_reslice_when_changed_lines_large(self):
        chunks = [
            {
                "id": "c1",
                "filePath": "src/big.ts",
                "old": {"start": 1, "count": 500},
                "new": {"start": 1, "count": 500},
                "lines": [{"kind": "add", "text": f"line {idx}"} for idx in range(450)],
            }
        ]
        row = compute_group_reviewability(
            self._doc(
                chunks=chunks,
                assignments={"g1": ["c1"]},
                reviews={"c1": {"status": "reviewed"}},
                group_briefs={"g1": {"summary": "handoff", "focusPoints": ["fp"], "testEvidence": ["te"]}},
            ),
            "g1",
        )
        self.assertEqual(row["verdict"], "needs_reslice")

    def test_must_read_prioritizes_needs_rereview_chunk(self):
        row = compute_group_reviewability(
            self._doc(group_briefs={"g1": {"summary": "handoff", "focusPoints": ["fp"], "testEvidence": ["te"]}}),
            "g1",
        )
        self.assertEqual(row["mustReadChunks"][0], "c1")
        # mustReadChunks and hotspotChunks are mutually exclusive: c1 is in mustRead, not hotspot
        self.assertNotIn("c1", row["hotspotChunks"])

    def test_script_json_output(self):
        doc = self._doc(group_briefs={"g1": {"summary": "handoff", "focusPoints": ["fp"], "testEvidence": ["te"]}})
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "doc.diffgr.json"
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = summarize_reviewability_main(["--input", str(path), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["groups"][0]["groupId"], "g1")

    def test_compute_all_group_reviewability_returns_all_groups(self):
        doc = self._doc(group_briefs={"g1": {"summary": "handoff", "focusPoints": ["fp"], "testEvidence": ["te"]}})
        rows = compute_all_group_reviewability(doc)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["groupId"], "g1")


if __name__ == "__main__":
    unittest.main()
