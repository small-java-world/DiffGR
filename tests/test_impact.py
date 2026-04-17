import unittest

from diffgr.impact import build_impact_report
from diffgr.impact_merge import (
    build_impact_selection_plans,
    build_impact_preview_report,
    preview_impact_apply,
    preview_impact_merge,
    summarize_impact_report,
    summarize_rebase_warnings,
)


def make_doc(*, title: str, groups: list[dict], chunks: list[dict], assignments: dict) -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {"title": title, "createdAt": "2026-02-23T00:00:00Z"},
        "groups": groups,
        "chunks": chunks,
        "assignments": assignments,
        "reviews": {},
    }


def make_chunk(*, chunk_id: str, file_path: str, header: str, lines: list[dict]) -> dict:
    return {
        "id": chunk_id,
        "filePath": file_path,
        "old": {"start": 1, "count": 1},
        "new": {"start": 1, "count": 1},
        "header": header,
        "lines": lines,
    }


class TestImpactReport(unittest.TestCase):
    def test_group_impact_classification_old_grouping(self):
        old_doc = make_doc(
            title="old",
            groups=[{"id": "g1", "name": "G1", "order": 1}, {"id": "g2", "name": "G2", "order": 2}],
            chunks=[
                make_chunk(
                    chunk_id="old1",
                    file_path="src/a.ts",
                    header="h1",
                    lines=[
                        {"kind": "context", "text": "const x = 1;", "oldLine": 1, "newLine": 1},
                        {"kind": "add", "text": "return x + 1;", "oldLine": None, "newLine": 2},
                    ],
                ),
                make_chunk(
                    chunk_id="old2",
                    file_path="src/b.ts",
                    header="h2",
                    lines=[
                        {"kind": "add", "text": "return 1;", "oldLine": None, "newLine": 1},
                    ],
                ),
            ],
            assignments={"g1": ["old1"], "g2": ["old2"]},
        )

        new_doc = make_doc(
            title="new",
            groups=[{"id": "g-all", "name": "All", "order": 1}],
            chunks=[
                # old1: context changed but add/delete identical -> delta (no impact)
                make_chunk(
                    chunk_id="new1",
                    file_path="src/a.ts",
                    header="h1",
                    lines=[
                        {"kind": "context", "text": "const x = 2;", "oldLine": 1, "newLine": 1},
                        {"kind": "add", "text": "return x + 1;", "oldLine": None, "newLine": 2},
                    ],
                ),
                # old2: add line changed -> similar (impact)
                make_chunk(
                    chunk_id="new2",
                    file_path="src/b.ts",
                    header="h2",
                    lines=[
                        {"kind": "add", "text": "return 2;", "oldLine": None, "newLine": 1},
                    ],
                ),
                # new-only chunk
                make_chunk(
                    chunk_id="new3",
                    file_path="src/c.ts",
                    header="h3",
                    lines=[
                        {"kind": "add", "text": "new stuff", "oldLine": None, "newLine": 1},
                    ],
                ),
            ],
            assignments={"g-all": ["new1", "new2", "new3"]},
        )

        report = build_impact_report(old_doc=old_doc, new_doc=new_doc, grouping="old", similarity_threshold=0.70)

        counts = report["match"]["counts"]
        self.assertEqual(counts["delta"], 1)
        self.assertEqual(counts["similar"], 1)
        self.assertEqual(report["match"]["newOnly"], 1)

        groups = {g["id"]: g for g in report["groups"]}
        self.assertEqual(groups["g1"]["action"], "skip")
        self.assertEqual(groups["g1"]["changed"], 0)
        self.assertEqual(groups["g1"]["unchanged"], 1)
        self.assertEqual(groups["g2"]["action"], "review")
        self.assertEqual(groups["g2"]["changed"], 1)

        new_only = report["newOnlyChunks"]
        self.assertEqual(len(new_only), 1)
        self.assertEqual(new_only[0]["id"], "new3")

    def test_summarize_impact_report_splits_impacted_and_unchanged_groups(self):
        report = {
            "grouping": "old",
            "groups": [
                {"id": "g1", "name": "G1", "action": "skip", "changed": 0, "unchanged": 1},
                {"id": "g2", "name": "G2", "action": "review", "changed": 2, "new": 1},
            ],
            "newOnlyChunkIds": ["c9"],
            "oldOnlyChunkIds": [],
        }
        summary = summarize_impact_report(report)
        self.assertEqual(summary["impactedGroupIds"], ["g2"])
        self.assertEqual(summary["unchangedGroupIds"], ["g1"])
        self.assertEqual(summary["newOnlyChunkIds"], ["c9"])

    def test_preview_impact_merge_returns_impact_and_affected_briefs(self):
        old_doc = make_doc(
            title="old",
            groups=[{"id": "g1", "name": "G1", "order": 1}],
            chunks=[make_chunk(chunk_id="old1", file_path="src/a.ts", header="h1", lines=[{"kind": "add", "text": "return 1;", "oldLine": None, "newLine": 1}])],
            assignments={"g1": ["old1"]},
        )
        new_doc = make_doc(
            title="new",
            groups=[{"id": "g1", "name": "G1", "order": 1}],
            chunks=[make_chunk(chunk_id="new1", file_path="src/a.ts", header="h1", lines=[{"kind": "add", "text": "return 2;", "oldLine": None, "newLine": 1}])],
            assignments={"g1": ["new1"]},
        )
        preview = preview_impact_merge(
            old_doc=old_doc,
            new_doc=new_doc,
            state={"groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}}, "reviews": {"old1": {"status": "reviewed"}}},
            similarity_threshold=0.7,
        )
        self.assertEqual(preview["impactSummary"]["impactedGroupIds"], ["g1"])
        self.assertEqual(preview["affectedBriefs"][0]["groupId"], "g1")
        self.assertEqual(preview["affectedBriefs"][0]["summary"], "handoff")
        self.assertIn("warningSummary", preview)
        self.assertIn("selectionPlans", preview)
        self.assertIn("reviews", preview["selectionPlans"])

    def test_build_impact_selection_plans_splits_handoffs_reviews_and_ui(self):
        preview = {
            "impactSummary": {"impactedGroupIds": ["g1"]},
            "impactReport": {
                "groups": [
                    {
                        "id": "g1",
                        "action": "review",
                        "changedChunkIds": ["new1"],
                        "removedChunkIds": ["old1"],
                    }
                ]
            },
            "mergeSummary": {
                "diff": {
                    "reviews": {
                        "addedDetails": [{"key": "new1", "preview": "x", "selectionToken": "reviews:new1"}],
                        "removedDetails": [{"key": "old1", "preview": "y", "selectionToken": "reviews:old1"}],
                        "changedDetails": [],
                    },
                    "groupBriefs": {
                        "addedDetails": [],
                        "removedDetails": [],
                        "changedDetails": [{"key": "g1", "beforePreview": "a", "afterPreview": "b", "selectionToken": "groupBriefs:g1"}],
                    },
                    "analysisState": {
                        "addedDetails": [{"key": "selectedChunkId", "preview": "new1", "selectionToken": "analysisState:selectedChunkId"}],
                        "removedDetails": [],
                        "changedDetails": [],
                    },
                    "threadState": {
                        "addedDetails": [],
                        "removedDetails": [],
                        "changedDetails": [{"key": "__files:src/a.ts", "beforePreview": "0", "afterPreview": "1", "selectionToken": "threadState.__files:src/a.ts"}],
                    },
                }
            },
        }
        plans = build_impact_selection_plans(preview)
        self.assertEqual(plans["handoffs"]["tokens"], ["groupBriefs:g1"])
        self.assertEqual(plans["reviews"]["tokens"], ["reviews:new1", "reviews:old1"])
        self.assertEqual(plans["ui"]["tokens"], ["analysisState:selectedChunkId", "threadState.__files:src/a.ts"])
        self.assertEqual(plans["all"]["count"], 5)

    def test_summarize_rebase_warnings_classifies_rebase_specific_kinds(self):
        summary = summarize_rebase_warnings(
            [
                "Ambiguous stable match skipped (stable=abc..., old=2, new=2)",
                "status conflict on chunk c1; kept reviewed, ignored ignored",
            ],
            unmapped_new_chunks=3,
        )
        self.assertEqual(summary["kinds"]["rebaseWeakMatch"], 1)
        self.assertEqual(summary["kinds"]["statusConflict"], 1)
        self.assertEqual(summary["kinds"]["rebaseUnmappedChunk"], 3)

    def test_build_impact_preview_report_exposes_common_sections(self):
        preview = {
            "impactSummary": {"impactedGroupCount": 1, "unchangedGroupCount": 0, "impactedGroups": []},
            "affectedBriefs": [],
            "warningSummary": {"total": 2, "kinds": {"rebaseWeakMatch": 1}},
            "mergeSummary": {"diff": {"reviews": {"addedCount": 0, "removedCount": 0, "changedCount": 1, "unchangedCount": 0}}},
            "rebaseSummary": {},
        }
        report = build_impact_preview_report(
            preview,
            old_label="old.diffgr.json",
            new_label="new.diffgr.json",
            state_label="review.state.json",
        )
        self.assertEqual(report["sourceLabel"], "old.diffgr.json -> new.diffgr.json using review.state.json")
        self.assertIn("changeSummary", report)
        self.assertIn("groupBriefChanges", report)
        self.assertIn("warningSummary", report)
        self.assertIn("stateDiff", report)
        self.assertIn("selectionPlans", report)

    def test_preview_impact_apply_returns_selection_preview_for_plan(self):
        old_doc = make_doc(
            title="old",
            groups=[{"id": "g1", "name": "G1", "order": 1}],
            chunks=[make_chunk(chunk_id="old1", file_path="src/a.ts", header="h1", lines=[{"kind": "add", "text": "return 1;", "oldLine": None, "newLine": 1}])],
            assignments={"g1": ["old1"]},
        )
        new_doc = make_doc(
            title="new",
            groups=[{"id": "g1", "name": "G1", "order": 1}],
            chunks=[make_chunk(chunk_id="new1", file_path="src/a.ts", header="h1", lines=[{"kind": "add", "text": "return 2;", "oldLine": None, "newLine": 1}])],
            assignments={"g1": ["new1"]},
        )
        state = {"groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}}, "reviews": {"old1": {"status": "reviewed"}}}
        result = preview_impact_apply(
            old_doc=old_doc,
            new_doc=new_doc,
            state=state,
            plan="handoffs",
            old_label="old.diffgr.json",
            new_label="new.diffgr.json",
            state_label="review.state.json",
        )
        self.assertEqual(result["planName"], "handoffs")
        self.assertEqual(result["selectionTokens"], ["groupBriefs:g1"])
        self.assertEqual(result["selectionPreview"]["summary"]["appliedCount"], 1)
        self.assertEqual(result["sourceLabel"], "old.diffgr.json -> new.diffgr.json using review.state.json")


if __name__ == "__main__":
    unittest.main()
