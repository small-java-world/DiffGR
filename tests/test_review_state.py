import unittest

from diffgr.review_state import (
    STATE_DIFF_SECTIONS,
    apply_review_state_selection,
    apply_review_state,
    build_review_state_diff_report,
    build_review_state_selection_preview_report,
    collect_review_state_selectable_keys,
    diff_review_states,
    extract_review_state,
    iter_review_state_diff_rows,
    iter_review_state_selection_tokens,
    merge_review_states,
    normalize_review_state_payload,
    parse_review_state_selection,
    preview_review_state_selection,
    preview_merge_review_states,
    summarize_group_brief_changes,
    summarize_group_brief_record,
    summarize_merge_result,
    summarize_merge_warnings,
    summarize_review_state,
)


class TestReviewState(unittest.TestCase):
    def test_normalize_review_state_payload_accepts_wrapper(self):
        state = normalize_review_state_payload(
            {
                "state": {
                    "reviews": {"c1": {"status": "reviewed"}},
                    "groupBriefs": {"g1": {"summary": "handoff"}},
                }
            }
        )
        self.assertEqual(state["reviews"]["c1"]["status"], "reviewed")
        self.assertEqual(state["groupBriefs"]["g1"]["summary"], "handoff")
        self.assertEqual(state["analysisState"], {})
        self.assertEqual(state["threadState"], {})

    def test_extract_review_state_returns_all_keys(self):
        doc = {
            "reviews": {"c1": {"status": "reviewed"}},
            "groupBriefs": {"g1": {"summary": "handoff"}},
            "analysisState": {"currentGroupId": "g1"},
            "threadState": {"c1": {"open": True}},
        }
        state = extract_review_state(doc)
        self.assertEqual(state["reviews"]["c1"]["status"], "reviewed")
        self.assertEqual(state["groupBriefs"]["g1"]["summary"], "handoff")
        self.assertEqual(state["analysisState"]["currentGroupId"], "g1")
        self.assertTrue(state["threadState"]["c1"]["open"])

    def test_apply_review_state_replaces_full_state(self):
        doc = {
            "format": "diffgr",
            "version": 1,
            "meta": {},
            "groups": [],
            "chunks": [],
            "assignments": {},
            "reviews": {"c0": {"status": "ignored"}},
            "groupBriefs": {"g0": {"summary": "old"}},
            "analysisState": {"currentGroupId": "g0"},
            "threadState": {"c0": {"open": False}},
        }
        out = apply_review_state(
            doc,
            {
                "reviews": {"c1": {"status": "reviewed"}},
                "groupBriefs": {"g1": {"summary": "handoff"}},
                "analysisState": {"currentGroupId": "g1"},
                "threadState": {"c1": {"open": True}},
            },
        )
        self.assertEqual(out["reviews"], {"c1": {"status": "reviewed"}})
        self.assertEqual(out["groupBriefs"], {"g1": {"summary": "handoff"}})
        self.assertEqual(out["analysisState"], {"currentGroupId": "g1"})
        self.assertEqual(out["threadState"], {"c1": {"open": True}})

    def test_merge_review_states_merges_records_deterministically(self):
        merged, warnings, applied = merge_review_states(
            {
                "reviews": {
                    "c1": {
                        "status": "reviewed",
                        "comment": "base",
                        "lineComments": [{"oldLine": None, "newLine": 1, "lineType": "add", "comment": "base line"}],
                    }
                },
                "groupBriefs": {"g1": {"status": "draft", "summary": "base summary", "focusPoints": ["auth"]}},
                "analysisState": {"currentGroupId": "g1", "filterText": "base"},
                "threadState": {"c1": {"open": True}, "__files": {"src/a.ts": {"open": True}}},
            },
            [
                (
                    "incoming",
                    {
                        "reviews": {
                            "c1": {
                                "status": "needsReReview",
                                "comment": "incoming",
                                "lineComments": [{"oldLine": None, "newLine": 2, "lineType": "add", "comment": "incoming line"}],
                            }
                        },
                        "groupBriefs": {"g1": {"status": "ready", "summary": "incoming summary", "focusPoints": ["risk"]}},
                        "analysisState": {"filterText": "incoming", "selectedChunkId": "c1"},
                        "threadState": {
                            "c1": {"open": False},
                            "__files": {"src/b.ts": {"open": False}},
                            "selectedLineAnchor": {"anchorKey": "add::2", "oldLine": None, "newLine": 2, "lineType": "add"},
                        },
                    },
                )
            ],
        )
        self.assertEqual(applied, 1)
        self.assertTrue(any("chunk comment conflict" in item for item in warnings))
        self.assertEqual(merged["reviews"]["c1"]["status"], "needsReReview")
        self.assertEqual(merged["reviews"]["c1"]["comment"], "incoming")
        self.assertEqual(len(merged["reviews"]["c1"]["lineComments"]), 2)
        self.assertEqual(merged["groupBriefs"]["g1"]["status"], "ready")
        self.assertEqual(merged["groupBriefs"]["g1"]["focusPoints"], ["auth", "risk"])
        self.assertEqual(merged["analysisState"]["filterText"], "incoming")
        self.assertEqual(merged["analysisState"]["selectedChunkId"], "c1")
        self.assertFalse(merged["threadState"]["c1"]["open"])
        self.assertIn("src/a.ts", merged["threadState"]["__files"])
        self.assertIn("src/b.ts", merged["threadState"]["__files"])

    def test_summarize_review_state_counts_reviews_briefs_and_state(self):
        summary = summarize_review_state(
            {
                "reviews": {
                    "c1": {"status": "reviewed", "comment": "ok"},
                    "c2": {
                        "status": "needsReReview",
                        "lineComments": [{"oldLine": None, "newLine": 2, "lineType": "add", "comment": "line"}],
                    },
                },
                "groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}},
                "analysisState": {"currentGroupId": "g1", "selectedChunkId": "c2", "filterText": "auth"},
                "threadState": {
                    "c1": {"open": True},
                    "__files": {"src/a.ts": {"open": True}},
                    "selectedLineAnchor": {"anchorKey": "add::2", "oldLine": None, "newLine": 2, "lineType": "add"},
                },
            }
        )
        self.assertEqual(summary["reviews"]["total"], 2)
        self.assertEqual(summary["reviews"]["statusCounts"]["reviewed"], 1)
        self.assertEqual(summary["reviews"]["statusCounts"]["needsReReview"], 1)
        self.assertEqual(summary["reviews"]["chunkCommentCount"], 1)
        self.assertEqual(summary["reviews"]["lineCommentCount"], 1)
        self.assertEqual(summary["groupBriefs"]["statusCounts"]["ready"], 1)
        self.assertEqual(summary["analysisState"]["currentGroupId"], "g1")
        self.assertEqual(summary["analysisState"]["selectedChunkId"], "c2")
        self.assertEqual(summary["threadState"]["chunkEntryCount"], 1)
        self.assertEqual(summary["threadState"]["fileEntryCount"], 1)
        self.assertTrue(summary["threadState"]["hasSelectedLineAnchor"])

    def test_diff_review_states_counts_added_removed_and_changed(self):
        diff = diff_review_states(
            {
                "reviews": {"c1": {"status": "reviewed"}, "c2": {"status": "ignored"}},
                "groupBriefs": {"g1": {"summary": "old"}},
                "analysisState": {"currentGroupId": "g1"},
                "threadState": {"selectedLineAnchor": {"anchorKey": "add::2"}},
            },
            {
                "reviews": {"c1": {"status": "needsReReview"}, "c3": {"status": "reviewed"}},
                "groupBriefs": {"g1": {"summary": "new"}, "g2": {"summary": "added"}},
                "analysisState": {"currentGroupId": "g2", "selectedChunkId": "c3"},
                "threadState": {"selectedLineAnchor": {"anchorKey": "add::2"}, "__files": {"src/a.ts": {"open": True}}},
            },
        )
        self.assertEqual(diff["reviews"]["added"], ["c3"])
        self.assertEqual(diff["reviews"]["removed"], ["c2"])
        self.assertEqual(diff["reviews"]["changed"], ["c1"])
        self.assertEqual(diff["groupBriefs"]["added"], ["g2"])
        self.assertEqual(diff["groupBriefs"]["changed"], ["g1"])
        self.assertEqual(diff["analysisState"]["added"], ["selectedChunkId"])
        self.assertEqual(diff["analysisState"]["changed"], ["currentGroupId"])
        self.assertEqual(diff["threadState"]["added"], ["__files:src/a.ts"])
        self.assertEqual(diff["threadState"]["unchanged"], ["selectedLineAnchor"])
        self.assertEqual(diff["reviews"]["changedDetails"][0]["key"], "c1")
        self.assertIn("reviewed", diff["reviews"]["changedDetails"][0]["beforePreview"])
        self.assertIn("needsReReview", diff["reviews"]["changedDetails"][0]["afterPreview"])
        self.assertEqual(diff["groupBriefs"]["addedDetails"][0]["key"], "g2")
        self.assertIn("added", diff["groupBriefs"]["addedDetails"][0]["preview"])

    def test_summarize_merge_warnings_groups_by_section(self):
        summary = summarize_merge_warnings(
            [
                "incoming: chunk comment conflict on chunk c1; used incoming comment.",
                "incoming: group brief conflict on g1; used incoming summary.",
                "misc warning",
            ]
        )
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["sections"]["reviews"], 1)
        self.assertEqual(summary["sections"]["groupBriefs"], 1)
        self.assertEqual(summary["sections"]["other"], 1)

    def test_summarize_merge_result_includes_diff_and_warning_summary(self):
        base_state = {
            "reviews": {"c1": {"status": "reviewed"}},
            "groupBriefs": {},
            "analysisState": {},
            "threadState": {},
        }
        merged_state = {
            "reviews": {"c1": {"status": "needsReReview"}},
            "groupBriefs": {"g1": {"summary": "handoff"}},
            "analysisState": {},
            "threadState": {},
        }
        summary = summarize_merge_result(
            base_state,
            merged_state,
            ["incoming: chunk comment conflict on chunk c1; used incoming comment."],
        )
        self.assertEqual(summary["diff"]["reviews"]["changed"], ["c1"])
        self.assertEqual(summary["diff"]["groupBriefs"]["added"], ["g1"])
        self.assertEqual(summary["warnings"]["total"], 1)
        self.assertEqual(summary["warnings"]["sections"]["reviews"], 1)

    def test_parse_review_state_selection_accepts_repeatable_tokens(self):
        selection = parse_review_state_selection(
            ["reviews:c1,c2", "analysisState:selectedChunkId", "threadState.__files:src/a.ts"]
        )
        self.assertEqual(selection["reviews"], ["c1", "c2"])
        self.assertEqual(selection["analysisState"], ["selectedChunkId"])
        self.assertEqual(selection["threadState.__files"], ["src/a.ts"])

    def test_apply_review_state_selection_updates_only_selected_keys(self):
        applied_state, applied = apply_review_state_selection(
            {
                "reviews": {"c1": {"status": "reviewed"}, "c2": {"status": "ignored"}},
                "groupBriefs": {"g1": {"summary": "old"}},
                "analysisState": {"currentGroupId": "g1", "selectedChunkId": "c1"},
                "threadState": {"selectedLineAnchor": {"anchorKey": "add::2"}, "__files": {"src/a.ts": {"open": True}}},
            },
            {
                "reviews": {"c1": {"status": "needsReReview"}},
                "groupBriefs": {"g1": {"summary": "new"}},
                "analysisState": {"currentGroupId": "g2", "selectedChunkId": "c9"},
                "threadState": {"selectedLineAnchor": {"anchorKey": "add::3"}, "__files": {"src/a.ts": {"open": False}}},
            },
            ["reviews:c1", "analysisState:selectedChunkId", "threadState.__files:src/a.ts"],
        )
        self.assertEqual(applied, 3)
        self.assertEqual(applied_state["reviews"]["c1"]["status"], "needsReReview")
        self.assertEqual(applied_state["reviews"]["c2"]["status"], "ignored")
        self.assertEqual(applied_state["groupBriefs"]["g1"]["summary"], "old")
        self.assertEqual(applied_state["analysisState"]["currentGroupId"], "g1")
        self.assertEqual(applied_state["analysisState"]["selectedChunkId"], "c9")
        self.assertEqual(applied_state["threadState"]["__files"]["src/a.ts"]["open"], False)
        self.assertEqual(applied_state["threadState"]["selectedLineAnchor"]["anchorKey"], "add::2")

    def test_apply_review_state_selection_rejects_unknown_key(self):
        with self.assertRaisesRegex(RuntimeError, "Unknown selection key"):
            apply_review_state_selection(
                {"reviews": {"c1": {"status": "reviewed"}}},
                {"reviews": {"c1": {"status": "needsReReview"}}},
                ["reviews:c9"],
            )

    def test_preview_review_state_selection_reports_noop_and_result_diff(self):
        preview = preview_review_state_selection(
            {
                "reviews": {"c1": {"status": "reviewed"}},
                "analysisState": {"selectedChunkId": "c1"},
            },
            {
                "reviews": {"c1": {"status": "reviewed"}},
                "analysisState": {"selectedChunkId": "c9"},
            },
            ["reviews:c1", "analysisState:selectedChunkId"],
        )
        self.assertEqual(preview["summary"]["selectedKeyCount"], 2)
        self.assertEqual(preview["summary"]["noOpCount"], 1)
        self.assertEqual(preview["summary"]["changedSectionCount"], 1)
        self.assertEqual(preview["resultDiff"]["analysisState"]["changed"], ["selectedChunkId"])

    def test_collect_review_state_selectable_keys_unions_thread_state_file_keys(self):
        selectable = collect_review_state_selectable_keys(
            {
                "reviews": {"c1": {"status": "reviewed"}},
                "threadState": {"selectedLineAnchor": {"anchorKey": "a"}, "__files": {"src/a.ts": {"open": True}}},
            },
            {
                "reviews": {"c2": {"status": "needsReReview"}},
                "analysisState": {"selectedChunkId": "c2"},
                "threadState": {"filterMode": "comments", "__files": {"src/my file.ts": {"open": False}}},
            },
        )
        self.assertEqual(selectable["reviews"], {"c1", "c2"})
        self.assertEqual(selectable["analysisState"], {"selectedChunkId"})
        self.assertEqual(selectable["threadState"], {"selectedLineAnchor", "filterMode"})
        self.assertEqual(selectable["threadState.__files"], {"src/a.ts", "src/my file.ts"})

    def test_diff_review_states_thread_state_files_emit_only_valid_selection_tokens(self):
        diff = diff_review_states(
            {"threadState": {"__files": {"src/old path.ts": {"open": True}}}},
            {"threadState": {"__files": {"src/my file.ts": {"open": False}}}},
        )
        self.assertEqual(diff["threadState"]["added"], ["__files:src/my file.ts"])
        self.assertEqual(diff["threadState"]["removed"], ["__files:src/old path.ts"])
        self.assertNotIn("__files", diff["threadState"]["added"])
        self.assertEqual(
            diff["threadState"]["addedDetails"][0]["selectionToken"],
            "threadState.__files:src/my file.ts",
        )

    def test_iter_review_state_diff_rows_returns_renderable_rows(self):
        diff = diff_review_states(
            {"reviews": {"c1": {"status": "reviewed"}}, "analysisState": {"currentGroupId": "g1"}},
            {"reviews": {"c1": {"status": "needsReReview"}, "c2": {"status": "reviewed"}}, "analysisState": {"currentGroupId": "g1"}},
        )
        rows = iter_review_state_diff_rows(diff)
        self.assertEqual(rows[0]["section"], "reviews")
        self.assertEqual(rows[0]["changeKind"], "added")
        self.assertEqual(rows[0]["key"], "c2")
        self.assertEqual(rows[0]["selectionToken"], "reviews:c2")
        self.assertTrue(any(row["changeKind"] == "changed" and row["selectionToken"] == "reviews:c1" for row in rows))

    def test_iter_review_state_selection_tokens_returns_stable_unique_tokens(self):
        diff = diff_review_states(
            {"reviews": {"c1": {"status": "reviewed"}}, "threadState": {"__files": {"src/a.ts": {"open": True}}}},
            {"reviews": {"c1": {"status": "needsReReview"}}, "threadState": {"__files": {"src/b.ts": {"open": False}}}},
        )
        tokens = iter_review_state_selection_tokens(diff)
        self.assertEqual(tokens, ["reviews:c1", "threadState.__files:src/a.ts", "threadState.__files:src/b.ts"])

    def test_state_diff_sections_constant_matches_public_sections(self):
        self.assertEqual(STATE_DIFF_SECTIONS, ("reviews", "groupBriefs", "analysisState", "threadState"))

    def test_summarize_group_brief_record_counts_lists(self):
        summary = summarize_group_brief_record(
            {
                "status": "ready",
                "summary": "handoff",
                "focusPoints": ["a", "b"],
                "testEvidence": ["t1"],
                "questionsForReviewer": ["q1", "q2"],
                "mentions": ["@a"],
                "acknowledgedBy": [{"actor": "alice"}],
            }
        )
        self.assertEqual(summary["status"], "ready")
        self.assertEqual(summary["summary"], "handoff")
        self.assertEqual(summary["focusPointsCount"], 2)
        self.assertEqual(summary["questionsCount"], 2)
        self.assertEqual(summary["acknowledgedByCount"], 1)

    def test_summarize_group_brief_changes_detects_status_and_summary_change(self):
        changes = summarize_group_brief_changes(
            {"groupBriefs": {"g1": {"status": "draft", "summary": "old"}}},
            {"groupBriefs": {"g1": {"status": "ready", "summary": "new"}}},
        )
        self.assertEqual(changes[0]["groupId"], "g1")
        self.assertEqual(changes[0]["changeKind"], "changed")
        self.assertEqual(changes[0]["before"]["status"], "draft")
        self.assertEqual(changes[0]["after"]["status"], "ready")

    def test_preview_merge_review_states_returns_summary_and_inputs(self):
        preview = preview_merge_review_states(
            {"reviews": {"c1": {"status": "reviewed"}}, "groupBriefs": {"g1": {"status": "draft", "summary": "old"}}},
            [
                (
                    "incoming.state.json",
                    {"reviews": {"c1": {"status": "needsReReview"}}, "groupBriefs": {"g1": {"status": "ready", "summary": "new"}}},
                )
            ],
        )
        self.assertEqual(preview["applied"], 1)
        self.assertEqual(preview["summary"]["inputs"][0]["source"], "incoming.state.json")
        self.assertEqual(preview["summary"]["briefChanges"][0]["groupId"], "g1")
        self.assertEqual(preview["summary"]["diff"]["reviews"]["changed"], ["c1"])

    def test_summarize_merge_warnings_counts_warning_kinds(self):
        summary = summarize_merge_warnings(
            [
                "a: status conflict on chunk c1; kept reviewed, ignored ignored",
                "a: chunk comment conflict on chunk c1; used incoming comment.",
                "a: group brief conflict on g1; used incoming summary.",
                "a: review record must be object for chunk: c9",
                "a: group brief record must be object for group: g9",
            ]
        )
        self.assertEqual(summary["kinds"]["statusConflict"], 1)
        self.assertEqual(summary["kinds"]["chunkCommentConflict"], 1)
        self.assertEqual(summary["kinds"]["groupBriefConflict"], 1)
        self.assertEqual(summary["kinds"]["invalidReviewRecord"], 1)
        self.assertEqual(summary["kinds"]["invalidGroupBriefRecord"], 1)

    def test_build_review_state_diff_report_returns_rows_and_tokens(self):
        base = {"reviews": {"c1": {"status": "reviewed"}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}}
        other = {
            "reviews": {"c1": {"status": "needsReReview"}, "c2": {"status": "reviewed"}},
            "groupBriefs": {"g1": {"summary": "handoff"}},
            "analysisState": {},
            "threadState": {},
        }
        report = build_review_state_diff_report(base, other, source_label="state.json")
        self.assertEqual(report["sourceLabel"], "state.json")
        self.assertIn("stateDiff", report)
        self.assertIn("rows", report)
        self.assertIn("selectionTokens", report)
        rows = report["rows"]
        self.assertTrue(any(r["key"] == "c1" and r["changeKind"] == "changed" for r in rows))
        self.assertTrue(any(r["key"] == "c2" and r["changeKind"] == "added" for r in rows))
        self.assertTrue(any(r["key"] == "g1" and r["section"] == "groupBriefs" for r in rows))
        tokens = report["selectionTokens"]
        self.assertIn("reviews:c1", tokens)
        self.assertIn("reviews:c2", tokens)
        self.assertIn("groupBriefs:g1", tokens)

    def test_build_review_state_diff_report_includes_thread_state_files(self):
        base = {
            "reviews": {},
            "groupBriefs": {},
            "analysisState": {},
            "threadState": {"__files": {"src/a.ts": {"open": False}}},
        }
        other = {
            "reviews": {},
            "groupBriefs": {},
            "analysisState": {},
            "threadState": {"__files": {"src/a.ts": {"open": True}, "src/b.ts": {"open": True}}},
        }
        report = build_review_state_diff_report(base, other)
        tokens = report["selectionTokens"]
        self.assertIn("threadState.__files:src/a.ts", tokens)
        self.assertIn("threadState.__files:src/b.ts", tokens)

    def test_build_review_state_selection_preview_report_returns_summary_and_result_diff(self):
        base = {"reviews": {"c1": {"status": "reviewed"}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}}
        other = {
            "reviews": {"c1": {"status": "needsReReview"}, "c2": {"status": "reviewed"}},
            "groupBriefs": {},
            "analysisState": {},
            "threadState": {},
        }
        report = build_review_state_selection_preview_report(
            base, other, ["reviews:c2"], source_label="state.json", base_label="embedded"
        )
        self.assertEqual(report["sourceLabel"], "state.json")
        self.assertEqual(report["baseLabel"], "embedded")
        self.assertIn("selection", report)
        self.assertIn("rows", report)
        self.assertIn("summary", report)
        self.assertIn("resultDiff", report)
        summary = report["summary"]
        self.assertEqual(summary["appliedCount"], 1)
        self.assertEqual(summary["noOpCount"], 0)
        self.assertEqual(summary["changedSectionCount"], 1)

    def test_build_review_state_selection_preview_report_stable_for_same_inputs(self):
        base = {"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}}
        other = {"reviews": {"c1": {"status": "reviewed"}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}}
        r1 = build_review_state_selection_preview_report(base, other, ["reviews:c1"])
        r2 = build_review_state_selection_preview_report(base, other, ["reviews:c1"])
        import json as _json
        self.assertEqual(_json.dumps(r1, sort_keys=True), _json.dumps(r2, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
