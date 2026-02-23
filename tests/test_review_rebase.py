import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_rebase import rebase_review_state, stable_fingerprint_for_chunk  # noqa: E402
from diffgr.viewer_core import validate_document  # noqa: E402


def make_chunk(
    *,
    chunk_id: str,
    file_path: str,
    old_start: int,
    new_start: int,
    header: str,
    lines: list[dict],
    stable_override: str | None = None,
) -> dict:
    chunk = {
        "id": chunk_id,
        "filePath": file_path,
        "old": {"start": old_start, "count": 1},
        "new": {"start": new_start, "count": 1},
        "header": header,
        "lines": lines,
    }
    stable = stable_override or stable_fingerprint_for_chunk(chunk)
    chunk["fingerprints"] = {"stable": stable, "strong": f"strong-{chunk_id}"}
    return chunk


def make_doc(*, chunks: list[dict], groups: list[dict], assignments: dict, reviews: dict) -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "UT Rebase", "createdAt": "2026-02-22T00:00:00Z"},
        "groups": groups,
        "chunks": chunks,
        "assignments": assignments,
        "reviews": reviews,
    }


class TestReviewRebase(unittest.TestCase):
    def test_stable_match_carries_review_and_remaps_line_comments(self):
        old_lines = [
            {"kind": "context", "text": "a", "oldLine": 1, "newLine": 1},
            {"kind": "add", "text": "b", "oldLine": None, "newLine": 2},
        ]
        old_chunk = make_chunk(
            chunk_id="old1",
            file_path="src/a.ts",
            old_start=1,
            new_start=1,
            header="h1",
            lines=old_lines,
        )
        stable = old_chunk["fingerprints"]["stable"]

        new_lines = [
            {"kind": "context", "text": "a", "oldLine": 10, "newLine": 10},
            {"kind": "add", "text": "b", "oldLine": None, "newLine": 11},
        ]
        new_chunk = make_chunk(
            chunk_id="new1",
            file_path="src/a.ts",
            old_start=10,
            new_start=10,
            header="h1",
            lines=new_lines,
            stable_override=stable,
        )

        old_doc = make_doc(
            chunks=[old_chunk],
            groups=[{"id": "g1", "name": "A", "order": 1}],
            assignments={"g1": ["old1"]},
            reviews={
                "old1": {
                    "status": "reviewed",
                    "comment": "ok",
                    "lineComments": [
                        {
                            "oldLine": None,
                            "newLine": 2,
                            "lineType": "add",
                            "comment": "nit",
                        }
                    ],
                }
            },
        )
        new_doc = make_doc(
            chunks=[new_chunk],
            groups=[{"id": "g-all", "name": "All", "order": 1}],
            assignments={"g-all": ["new1"]},
            reviews={},
        )

        out_doc, summary, warnings = rebase_review_state(old_doc=old_doc, new_doc=new_doc, preserve_groups=True)
        self.assertEqual(warnings, [])
        validate_document(out_doc)
        self.assertEqual(out_doc["groups"][0]["id"], "g1")
        self.assertEqual(out_doc["assignments"]["g1"], ["new1"])
        self.assertEqual(out_doc["reviews"]["new1"]["status"], "reviewed")
        self.assertEqual(out_doc["reviews"]["new1"]["comment"], "ok")
        line_comments = out_doc["reviews"]["new1"].get("lineComments") or []
        self.assertEqual(len(line_comments), 1)
        self.assertEqual(line_comments[0]["newLine"], 11)

        self.assertEqual(summary.matched_stable, 1)
        self.assertEqual(summary.carried_reviews, 1)

    def test_similar_match_marks_reviewed_as_needs_rereview(self):
        old_chunk = make_chunk(
            chunk_id="old1",
            file_path="src/a.ts",
            old_start=1,
            new_start=1,
            header="h1",
            lines=[{"kind": "add", "text": "return base * 2;", "oldLine": None, "newLine": 1}],
        )
        new_chunk = make_chunk(
            chunk_id="new1",
            file_path="src/a.ts",
            old_start=1,
            new_start=1,
            header="h1",
            lines=[{"kind": "add", "text": "return base * 3;", "oldLine": None, "newLine": 1}],
        )

        old_doc = make_doc(
            chunks=[old_chunk],
            groups=[{"id": "g1", "name": "A", "order": 1}],
            assignments={"g1": ["old1"]},
            reviews={"old1": {"status": "reviewed", "comment": "ok"}},
        )
        new_doc = make_doc(
            chunks=[new_chunk],
            groups=[{"id": "g-all", "name": "All", "order": 1}],
            assignments={"g-all": ["new1"]},
            reviews={},
        )

        out_doc, summary, warnings = rebase_review_state(
            old_doc=old_doc,
            new_doc=new_doc,
            preserve_groups=True,
            similarity_threshold=0.70,
        )
        self.assertEqual(warnings, [])
        self.assertEqual(summary.matched_similar, 1)
        self.assertEqual(out_doc["reviews"]["new1"]["status"], "needsReReview")

    def test_delta_match_preserves_reviewed_when_only_context_changes(self):
        old_lines = [
            {"kind": "context", "text": "const x = 1;", "oldLine": 1, "newLine": 1},
            {"kind": "add", "text": "return x + 1;", "oldLine": None, "newLine": 2},
        ]
        new_lines = [
            {"kind": "context", "text": "const x = 2;", "oldLine": 1, "newLine": 1},
            {"kind": "add", "text": "return x + 1;", "oldLine": None, "newLine": 2},
        ]
        old_chunk = make_chunk(
            chunk_id="old1",
            file_path="src/a.ts",
            old_start=1,
            new_start=1,
            header="h1",
            lines=old_lines,
        )
        new_chunk = make_chunk(
            chunk_id="new1",
            file_path="src/a.ts",
            old_start=1,
            new_start=1,
            header="h1",
            lines=new_lines,
        )

        old_doc = make_doc(
            chunks=[old_chunk],
            groups=[{"id": "g1", "name": "A", "order": 1}],
            assignments={"g1": ["old1"]},
            reviews={"old1": {"status": "reviewed", "comment": "ok", "lineComments": [{"oldLine": None, "newLine": 2, "lineType": "add", "comment": "nit"}]}},
        )
        new_doc = make_doc(
            chunks=[new_chunk],
            groups=[{"id": "g-all", "name": "All", "order": 1}],
            assignments={"g-all": ["new1"]},
            reviews={},
        )

        out_doc, summary, warnings = rebase_review_state(
            old_doc=old_doc,
            new_doc=new_doc,
            preserve_groups=True,
            similarity_threshold=0.70,
        )
        self.assertEqual(warnings, [])
        self.assertEqual(summary.matched_delta, 1)
        self.assertEqual(out_doc["reviews"]["new1"]["status"], "reviewed")
        # We intentionally do not carry lineComments for delta match (context changed).
        self.assertIsNone(out_doc["reviews"]["new1"].get("lineComments"))
