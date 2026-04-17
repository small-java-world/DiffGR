import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_split import (  # noqa: E402
    build_group_output_filename,
    build_group_review_document,
    merge_reviews_into_base,
    split_document_by_group,
)
from scripts.merge_group_reviews import main as merge_group_reviews_main  # noqa: E402
from scripts.split_group_reviews import main as split_group_reviews_main  # noqa: E402


def make_doc() -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {
            "title": "UT Split Merge",
            "createdAt": "2026-02-22T00:00:00Z",
            "source": {"type": "example", "base": "base", "head": "head"},
        },
        "groups": [
            {"id": "g-pr01", "name": "認証", "order": 1},
            {"id": "g-pr02", "name": "UI", "order": 2},
        ],
        "chunks": [
            {
                "id": "c1",
                "filePath": "src/a.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 1},
                "header": "h1",
                "lines": [],
            },
            {
                "id": "c2",
                "filePath": "src/b.ts",
                "old": {"start": 2, "count": 1},
                "new": {"start": 2, "count": 1},
                "header": "h2",
                "lines": [],
            },
            {
                "id": "c3",
                "filePath": "src/c.ts",
                "old": {"start": 3, "count": 1},
                "new": {"start": 3, "count": 1},
                "header": "h3",
                "lines": [],
            },
        ],
        "assignments": {"g-pr01": ["c1", "c2"], "g-pr02": ["c3"]},
        "reviews": {
            "c1": {"status": "reviewed", "comment": "ok"},
            "c3": {"status": "needsReReview", "comment": "recheck"},
        },
        "groupBriefs": {
            "g-pr01": {"status": "ready", "summary": "auth handoff"},
            "g-pr02": {"status": "draft", "summary": "ui handoff"},
        },
        "analysisState": {
            "currentGroupId": "g-pr01",
            "selectedChunkId": "c1",
            "filterText": "auth",
        },
        "threadState": {
            "c1": {"open": True},
            "c3": {"open": False},
            "__files": {
                "src/a.ts": {"open": True},
                "src/c.ts": {"open": False},
            },
            "selectedLineAnchor": {"anchorKey": "add::10", "oldLine": None, "newLine": 10, "lineType": "add"},
        },
    }


class TestReviewSplit(unittest.TestCase):
    def test_build_group_output_filename(self):
        name = build_group_output_filename(2, "g-pr02", "UI 調整")
        self.assertEqual(name, "02-g-pr02-UI.diffgr.json")

    def test_build_group_review_document_keeps_only_target_chunks_and_reviews(self):
        doc = make_doc()
        group_doc = build_group_review_document(doc, "g-pr01")

        self.assertEqual(group_doc["groups"][0]["id"], "g-pr01")
        self.assertEqual([chunk["id"] for chunk in group_doc["chunks"]], ["c1", "c2"])
        self.assertEqual(set(group_doc["reviews"].keys()), {"c1"})
        self.assertEqual(group_doc["groupBriefs"]["g-pr01"]["summary"], "auth handoff")
        self.assertEqual(group_doc["analysisState"]["currentGroupId"], "g-pr01")
        self.assertEqual(group_doc["analysisState"]["selectedChunkId"], "c1")
        self.assertEqual(group_doc["threadState"]["c1"]["open"], True)
        self.assertNotIn("c3", group_doc["threadState"])
        self.assertIn("src/a.ts", group_doc["threadState"]["__files"])
        self.assertNotIn("src/c.ts", group_doc["threadState"]["__files"])
        self.assertIn("[認証]", group_doc["meta"]["title"])

    def test_split_document_by_group(self):
        doc = make_doc()
        outputs = split_document_by_group(doc)

        self.assertEqual(len(outputs), 2)
        first_group, first_doc = outputs[0]
        self.assertEqual(first_group["id"], "g-pr01")
        self.assertEqual(len(first_doc["chunks"]), 2)

    def test_merge_reviews_into_base_warns_unknown_chunk(self):
        base = make_doc()
        reviewer_doc = make_doc()
        reviewer_doc["reviews"] = {"c2": {"status": "reviewed"}, "cx": {"status": "ignored"}}

        merged, warnings, applied = merge_reviews_into_base(base, [("reviewer-a", reviewer_doc)], strict=False)

        self.assertEqual(applied, 1)
        self.assertEqual(merged["reviews"]["c2"]["status"], "reviewed")
        self.assertTrue(any("unknown chunk id" in item for item in warnings))

    def test_merge_reviews_into_base_merges_line_comments_and_uses_status_precedence(self):
        base = make_doc()
        base["reviews"] = {
            "c1": {
                "status": "reviewed",
                "comment": "base comment",
                "lineComments": [
                    {"oldLine": None, "newLine": 10, "lineType": "add", "comment": "base line"},
                ],
            }
        }
        reviewer_doc = make_doc()
        reviewer_doc["reviews"] = {
            "c1": {
                "status": "needsReReview",
                "lineComments": [
                    {"oldLine": None, "newLine": 11, "lineType": "add", "comment": "incoming line"},
                ],
            }
        }

        merged, warnings, applied = merge_reviews_into_base(base, [("reviewer-a", reviewer_doc)], strict=False)

        self.assertEqual(applied, 1)
        self.assertEqual(warnings, [])
        self.assertEqual(merged["reviews"]["c1"]["status"], "needsReReview")
        line_comments = merged["reviews"]["c1"]["lineComments"]
        self.assertEqual(len(line_comments), 2)
        self.assertEqual(line_comments[0]["comment"], "base line")
        self.assertEqual(line_comments[1]["comment"], "incoming line")

    def test_merge_reviews_into_base_warns_on_comment_conflict_and_uses_incoming(self):
        base = make_doc()
        base["reviews"] = {"c1": {"status": "reviewed", "comment": "base comment"}}
        reviewer_doc = make_doc()
        reviewer_doc["reviews"] = {"c1": {"status": "ignored", "comment": "incoming comment"}}

        merged, warnings, applied = merge_reviews_into_base(base, [("reviewer-a", reviewer_doc)], strict=False)

        self.assertEqual(applied, 1)
        self.assertEqual(merged["reviews"]["c1"]["comment"], "incoming comment")
        self.assertEqual(merged["reviews"]["c1"]["status"], "reviewed")
        self.assertTrue(any("chunk comment conflict" in item for item in warnings))

    def test_merge_reviews_into_base_merges_group_briefs(self):
        base = make_doc()
        base["groupBriefs"] = {
            "g-pr01": {"status": "draft", "summary": "base summary", "focusPoints": ["auth"]},
        }
        reviewer_doc = make_doc()
        reviewer_doc["groupBriefs"] = {
            "g-pr01": {
                "status": "ready",
                "summary": "incoming summary",
                "focusPoints": ["risk"],
                "questionsForReviewer": ["is retry ok?"],
            }
        }

        merged, warnings, _ = merge_reviews_into_base(base, [("reviewer-a", reviewer_doc)], strict=False)

        self.assertEqual(merged["groupBriefs"]["g-pr01"]["status"], "ready")
        self.assertEqual(merged["groupBriefs"]["g-pr01"]["summary"], "incoming summary")
        self.assertEqual(merged["groupBriefs"]["g-pr01"]["focusPoints"], ["auth", "risk"])
        self.assertEqual(merged["groupBriefs"]["g-pr01"]["questionsForReviewer"], ["is retry ok?"])
        self.assertTrue(any("group brief conflict" in item for item in warnings))

    def test_merge_reviews_into_base_merges_state_objects(self):
        base = make_doc()
        base["analysisState"] = {"currentGroupId": "g-pr01", "selectedChunkId": "c1", "filterText": "base"}
        base["threadState"] = {"c1": {"open": True}, "__files": {"src/a.ts": {"open": True}}}
        reviewer_doc = make_doc()
        reviewer_doc["analysisState"] = {"currentGroupId": "g-pr02", "selectedChunkId": "c3", "filterText": "incoming"}
        reviewer_doc["threadState"] = {
            "c3": {"open": False},
            "__files": {"src/c.ts": {"open": False}},
            "selectedLineAnchor": {"anchorKey": "add::3", "oldLine": None, "newLine": 3, "lineType": "add"},
        }

        merged, warnings, _ = merge_reviews_into_base(base, [("reviewer-a", reviewer_doc)], strict=False)

        self.assertEqual(warnings, [])
        self.assertEqual(merged["analysisState"]["currentGroupId"], "g-pr02")
        self.assertEqual(merged["analysisState"]["selectedChunkId"], "c3")
        self.assertEqual(merged["analysisState"]["filterText"], "incoming")
        self.assertTrue(merged["threadState"]["c1"]["open"])
        self.assertFalse(merged["threadState"]["c3"]["open"])
        self.assertIn("src/a.ts", merged["threadState"]["__files"])
        self.assertIn("src/c.ts", merged["threadState"]["__files"])
        self.assertEqual(merged["threadState"]["selectedLineAnchor"]["anchorKey"], "add::3")

    def test_split_group_reviews_script_and_merge_group_reviews_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.diffgr.json"
            base_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            split_dir = root / "split"

            code = split_group_reviews_main(
                [
                    "--input",
                    str(base_path),
                    "--output-dir",
                    str(split_dir),
                ]
            )
            self.assertEqual(code, 0)

            split_files = sorted(path for path in split_dir.glob("*.diffgr.json"))
            self.assertEqual(len(split_files), 2)

            # Simulate two reviewers by editing each split file.
            reviewer_a = json.loads(split_files[0].read_text(encoding="utf-8"))
            reviewer_b = json.loads(split_files[1].read_text(encoding="utf-8"))
            reviewer_a.setdefault("reviews", {})["c1"] = {"status": "reviewed", "comment": "A done"}
            reviewer_b.setdefault("reviews", {})["c3"] = {"status": "ignored", "comment": "B ignored"}
            split_files[0].write_text(json.dumps(reviewer_a, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            split_files[1].write_text(json.dumps(reviewer_b, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            merged_path = root / "merged.diffgr.json"
            code = merge_group_reviews_main(
                [
                    "--base",
                    str(base_path),
                    "--input",
                    str(split_files[0]),
                    "--input",
                    str(split_files[1]),
                    "--output",
                    str(merged_path),
                ]
            )
            self.assertEqual(code, 0)

            merged = json.loads(merged_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["reviews"]["c1"]["comment"], "A done")
            self.assertEqual(merged["reviews"]["c3"]["status"], "needsReReview")


if __name__ == "__main__":
    unittest.main()
