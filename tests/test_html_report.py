import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.html_report import render_group_diff_html
from scripts.export_diffgr_html import main as export_html_main


def extract_report_doc_json(html: str) -> dict:
    marker = '<script id="report-doc-json" type="application/json">'
    start = html.find(marker)
    if start < 0:
        raise AssertionError("embedded report-doc-json script not found")
    end = html.find("</script>", start)
    if end < 0:
        raise AssertionError("embedded report-doc-json script is not closed")
    payload = html[start + len(marker) : end]
    return json.loads(payload)


def extract_report_config_json(html: str) -> dict:
    marker = '<script id="report-config-json" type="application/json">'
    start = html.find(marker)
    if start < 0:
        raise AssertionError("embedded report-config-json script not found")
    end = html.find("</script>", start)
    if end < 0:
        raise AssertionError("embedded report-config-json script is not closed")
    payload = html[start + len(marker) : end]
    return json.loads(payload)


def make_doc() -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {
            "title": "UT Report",
            "createdAt": "2026-02-22T00:00:00Z",
            "source": {"type": "example", "base": "base", "head": "head"},
        },
        "groups": [
            {"id": "g-pr01", "name": "計算倍率変更", "order": 1},
            {"id": "g-pr02", "name": "入力正規化", "order": 2},
        ],
        "chunks": [
            {
                "id": "c1",
                "filePath": "src/a.ts",
                "old": {"start": 1, "count": 2},
                "new": {"start": 1, "count": 2},
                "header": "export function compute()",
                "lines": [
                    {"kind": "context", "text": "export function compute() {", "oldLine": 1, "newLine": 1},
                    {"kind": "delete", "text": "  return a + 1;", "oldLine": 2, "newLine": None},
                    {"kind": "add", "text": "  return a * 2;", "oldLine": None, "newLine": 2},
                    {"kind": "context", "text": "}", "oldLine": 3, "newLine": 3},
                ],
            },
            {
                "id": "c2",
                "filePath": "src/b.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 1},
                "header": "export function normalize()",
                "lines": [
                    {"kind": "delete", "text": "  return v.trim();", "oldLine": 1, "newLine": None},
                    {"kind": "add", "text": "  return v.trim().toLowerCase();", "oldLine": None, "newLine": 1},
                ],
            },
            {
                "id": "c3",
                "filePath": "src/c.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 2},
                "header": "export const FLAG = true",
                "lines": [
                    {"kind": "context", "text": "export const FLAG = true;", "oldLine": 1, "newLine": 1},
                    {"kind": "add", "text": "export const EXTRA = true;", "oldLine": None, "newLine": 2},
                ],
            },
        ],
        "assignments": {"g-pr01": ["c1"], "g-pr02": ["c2"]},
        "reviews": {},
    }


class TestHtmlReport(unittest.TestCase):
    def test_render_group_diff_html_by_japanese_name(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        self.assertIn("Group: <b>計算倍率変更</b>", html)
        self.assertIn("data-file='src/a.ts'", html)
        self.assertNotIn("data-file='src/b.ts'", html)
        self.assertIn("return a * 2", html)
        self.assertIn("return a + 1", html)

    def test_render_group_diff_html_raises_for_ambiguous_name(self):
        doc = make_doc()
        doc["groups"] = [
            {"id": "g1", "name": "同名", "order": 1},
            {"id": "g2", "name": "同名", "order": 2},
        ]
        with self.assertRaises(RuntimeError):
            render_group_diff_html(doc, group_selector="同名")

    def test_render_group_diff_html_unassigned_selector(self):
        html = render_group_diff_html(make_doc(), group_selector="unassigned")
        self.assertIn("Group: <b>Unassigned</b>", html)
        self.assertIn("data-file='src/c.ts'", html)
        self.assertNotIn("data-file='src/a.ts'", html)
        self.assertNotIn("data-file='src/b.ts'", html)

    def test_render_embeds_original_doc_json_for_html_side_editing(self):
        doc = make_doc()
        html = render_group_diff_html(doc, group_selector="計算倍率変更")
        embedded = extract_report_doc_json(html)
        self.assertEqual(embedded.get("format"), "diffgr")
        self.assertEqual([chunk.get("id") for chunk in embedded.get("chunks", [])], ["c1", "c2", "c3"])

    def test_render_includes_html_comment_posting_controls_and_script_hooks(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        self.assertIn('id="stat-reviewed-rate"', html)
        self.assertIn('id="save-state"', html)
        self.assertIn('id="download-json"', html)
        self.assertIn('id="download-state"', html)
        self.assertIn('id="import-state"', html)
        self.assertIn('id="diff-state"', html)
        self.assertIn('id="apply-state-selection"', html)
        self.assertIn('id="import-state-file"', html)
        self.assertIn('id="copy-state"', html)
        self.assertIn('id="state-source-label"', html)
        self.assertIn('id="state-selection-modal"', html)
        self.assertIn('id="comment-editor-modal"', html)
        self.assertIn("data-action='toggle-reviewed'", html)
        self.assertIn("data-action='chunk-comment'", html)
        self.assertIn("data-action='line-comment'", html)
        self.assertIn("data-action='edit-comment-item'", html)
        self.assertIn("function openCommentEditor(options)", html)
        self.assertIn("function setChunkStatus(", html)
        self.assertIn("function refreshReviewProgress()", html)
        self.assertIn("setSaveStatus(", html)
        self.assertIn("function setChunkComment(", html)
        self.assertIn("function setLineCommentForAnchor(", html)
        self.assertIn("function editCommentItemFromPane(commentItemEl)", html)
        self.assertIn("function rebuildCommentPaneFromDraft()", html)
        self.assertIn("function rebuildInboxFromDom()", html)
        self.assertIn("function currentStatePayload()", html)
        self.assertIn("function normalizeImportedStatePayload(", html)
        self.assertIn("function cloneStateValue(", html)
        self.assertIn("function canonicalStateValue(", html)
        self.assertIn("function canonicalStateString(", html)
        self.assertIn("function applyImportedState(", html)
        self.assertIn("updateImpactPlanActions();", html)
        self.assertIn("function parseSelectionTokens(", html)
        self.assertIn("function collectSelectableTokens(", html)
        self.assertIn("function diffStatePayload(", html)
        self.assertIn("function applySelectedStateTokens(", html)
        self.assertIn('const stateDiffSections = ["reviews", "groupBriefs", "analysisState", "threadState"];', html)
        self.assertIn(
            'const stateSelectionSections = ["reviews", "groupBriefs", "analysisState", "threadState", "threadState.__files"];',
            html,
        )
        self.assertIn("function createEmptyDiffSection()", html)
        self.assertIn("threadState.__files:${fileKey}", html)
        self.assertIn("Object.keys(value).sort()", html)
        self.assertIn("for (const sectionName of stateDiffSections)", html)
        self.assertIn("Object.fromEntries(stateSelectionSections.map((section) => [section, []]))", html)
        self.assertIn("Object.fromEntries(stateSelectionSections.map((section) => [section, new Set()]))", html)
        self.assertIn("addedCount", html)
        self.assertIn('" [select: " + token + "]"', html)
        self.assertIn("function refreshChunkVisualsFromDraft()", html)

    def test_render_includes_line_anchor_data_attributes_for_line_commenting(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        self.assertIn("data-anchor-key='delete:2:'", html)
        self.assertIn("data-old-line='2' data-new-line=''", html)
        self.assertIn("data-anchor-key='add::2'", html)
        self.assertIn("data-old-line='' data-new-line='2'", html)
        self.assertIn("data-chunk-id='c1'", html)

    def test_render_prefills_comment_pane_and_stats_from_reviews(self):
        doc = make_doc()
        doc["reviews"] = {
            "c1": {
                "status": "needsReReview",
                "comment": "chunk note",
                "lineComments": [
                    {"oldLine": 2, "newLine": None, "lineType": "delete", "comment": "line note"},
                ],
            }
        }
        html = render_group_diff_html(doc, group_selector="計算倍率変更")
        self.assertIn("chunk note", html)
        self.assertIn("line note", html)
        self.assertIn('id="stat-comments-total" class="v">2</span>', html)
        self.assertIn('id="comment-total">2</span>', html)
        self.assertIn('id="comment-unresolved">2</span>', html)
        self.assertIn("data-kind='line-comment' data-anchor-key='delete:2:'", html)
        self.assertIn("data-chunk-id='c1' data-anchor-key='delete:2:'", html)

    def test_render_comment_items_include_edit_anchor_metadata(self):
        doc = make_doc()
        doc["reviews"] = {
            "c1": {
                "status": "needsReReview",
                "comment": "chunk note",
                "lineComments": [
                    {"oldLine": 2, "newLine": None, "lineType": "delete", "comment": "line note"},
                ],
            }
        }
        html = render_group_diff_html(doc, group_selector="計算倍率変更")
        self.assertIn("data-type='chunk' data-chunk-id='c1' data-anchor-key='' data-chunk-anchor='chunk-c1'", html)
        self.assertIn(
            "data-type='line' data-chunk-id='c1' data-anchor-key='delete:2:' data-chunk-anchor='chunk-c1'",
            html,
        )
        self.assertIn("class='comment-edit-btn' type='button' data-action='edit-comment-item'", html)

    def test_render_reflects_reviewed_checkbox_and_percentage(self):
        doc = make_doc()
        doc["reviews"] = {"c1": {"status": "reviewed", "reviewedAt": "2026-02-22T00:00:00Z"}}
        html = render_group_diff_html(doc, group_selector="計算倍率変更")
        self.assertIn("data-status='reviewed'", html)
        self.assertIn("data-action='toggle-reviewed' checked", html)
        self.assertIn('id="stat-reviewed-count">1</span>', html)
        self.assertIn('id="stat-reviewed-total">1</span>', html)
        self.assertIn('id="stat-reviewed-rate">100</span>', html)

    def test_render_embeds_save_config_defaults(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        config = extract_report_config_json(html)
        self.assertEqual(config.get("saveStateUrl"), "")
        self.assertEqual(config.get("saveStateLabel"), "Save State")
        self.assertEqual(config.get("stateSourceLabel"), "embedded")
        self.assertIn('id="save-state" type="button" hidden', html)

    def test_render_embeds_save_config_when_url_is_provided(self):
        html = render_group_diff_html(
            make_doc(),
            group_selector="計算倍率変更",
            save_state_url="/api/state",
            save_state_label="Sync",
        )
        config = extract_report_config_json(html)
        self.assertEqual(config.get("saveStateUrl"), "/api/state")
        self.assertEqual(config.get("saveStateLabel"), "Sync")
        self.assertEqual(config.get("currentGroupId"), "g-pr01")

    def test_render_embeds_overlay_state_source(self):
        html = render_group_diff_html(
            make_doc(),
            group_selector="計算倍率変更",
            state_source_label="review.state.json",
        )
        config = extract_report_config_json(html)
        self.assertEqual(config.get("stateSourceLabel"), "overlay:review.state.json")

    def test_render_impact_preview_panel_only_when_payload_is_present(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        self.assertNotIn("Impact Preview", html)

        payload = {
            "impactSummary": {
                "impactedGroupCount": 1,
                "unchangedGroupCount": 1,
                "newOnlyChunkIds": ["c9"],
                "oldOnlyChunkIds": [],
                "impactedGroups": [
                    {"groupId": "g-pr01", "name": "計算倍率変更", "changed": 1, "new": 0, "removed": 0}
                ],
            },
            "mergeSummary": {
                "warnings": {
                    "kinds": {
                        "statusConflict": 1,
                        "chunkCommentConflict": 0,
                        "groupBriefConflict": 1,
                        "invalidReviewRecord": 0,
                        "invalidGroupBriefRecord": 0,
                    }
                }
            },
            "affectedBriefs": [
                {
                    "groupId": "g-pr01",
                    "status": "ready",
                    "summary": "handoff",
                    "focusPointsCount": 1,
                    "testEvidenceCount": 1,
                    "questionsCount": 0,
                }
            ],
        }
        html = render_group_diff_html(
            make_doc(),
            group_selector="計算倍率変更",
            impact_preview_payload=payload,
            impact_preview_label="old.diffgr.json -> new.diffgr.json using review.state.json",
            impact_state_label="review.state.json",
        )
        self.assertIn('id="toggle-impact-preview"', html)
        self.assertIn('id="impact-preview-panel"', html)
        self.assertIn("Impact</h3>", html)
        self.assertIn("Group Brief Changes", html)
        self.assertIn("Affected Briefs", html)
        self.assertIn("Selection Plans", html)
        self.assertIn('id="impact-plan-status"', html)
        self.assertIn("State Diff", html)
        self.assertIn("data-action='copy-impact-plan'", html)
        self.assertIn("data-action='apply-impact-plan'", html)
        self.assertIn("const impactStateLabel = String(reportConfig.impactStateLabel || \"\").trim();", html)
        self.assertIn("const impactStateFingerprint = String(reportConfig.impactStateFingerprint || \"\").trim();", html)
        self.assertIn("function reviewStateFingerprint(payload)", html)
        self.assertIn("function currentImpactApplyAvailability()", html)
        self.assertIn("function updateImpactPlanActions()", html)
        self.assertIn("function openStateSelectionPreviewWithTokens(tokens, sourceLabel, baseStateOverride, baseLabelOverride)", html)
        config = extract_report_config_json(html)
        self.assertIn("impactPreviewReport", config)
        self.assertEqual(
            config["impactPreviewReport"]["sourceLabel"],
            "old.diffgr.json -> new.diffgr.json using review.state.json",
        )
        self.assertIn("old.diffgr.json -&gt; new.diffgr.json using review.state.json", html)
        self.assertNotIn(
            "old.diffgr.json -&gt; new.diffgr.json using review.state.json -&gt; 計算倍率変更 using",
            html,
        )

    def test_render_impact_preview_panel_from_report_without_raw_payload(self):
        html = render_group_diff_html(
            make_doc(),
            group_selector="計算倍率変更",
            impact_preview_report={
                "title": "Impact Preview: old.diffgr.json -> new.diffgr.json using review.state.json",
                "sourceLabel": "old.diffgr.json -> new.diffgr.json using review.state.json",
                "changeSummary": {
                    "carriedReviews": 1,
                    "changedToNeedsReReview": 0,
                    "unmappedNewChunks": 0,
                },
                "impactSummary": {
                    "impactedGroupCount": 1,
                    "unchangedGroupCount": 0,
                    "newOnlyChunkIds": [],
                    "oldOnlyChunkIds": [],
                    "impactedGroups": [
                        {"groupId": "g-pr01", "name": "計算倍率変更", "changed": 1, "new": 0, "removed": 0}
                    ],
                },
                "warningSummary": {"total": 0, "kinds": {}},
                "groupBriefChanges": [],
                "affectedBriefs": [],
                "selectionPlans": {"handoffs": {"tokens": ["groupBriefs:g-pr01"], "count": 1}},
                "stateDiff": {},
            },
            impact_preview_label="old.diffgr.json -> new.diffgr.json using review.state.json",
            impact_state_label="review.state.json",
        )
        self.assertIn('id="toggle-impact-preview"', html)
        self.assertIn("old.diffgr.json -&gt; new.diffgr.json using review.state.json", html)
        self.assertIn(">groupBriefs:g-pr01<", html)

    def test_render_apply_selected_state_preview_uses_real_changed_section_count(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        self.assertIn("function countChangedSections(diff)", html)
        self.assertIn("changedSectionCount: countChangedSections(resultDiff)", html)

    def test_render_diff_state_uses_modal_and_token_reuse_flow(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        self.assertIn('id="state-diff-modal"', html)
        self.assertIn('id="state-diff-preview"', html)
        self.assertIn('id="state-diff-copy"', html)
        self.assertIn('id="state-diff-apply"', html)
        self.assertIn("function buildStateDiffReport(baseState, otherState, sourceLabel)", html)
        self.assertIn("state.lastStateDiffTokens = report.selectionTokens;", html)
        self.assertIn("openStateSelectionWithTokens(state.lastStateDiffTokens);", html)
        self.assertNotIn('window.alert("State Diff vs ', html)

    def test_render_apply_selected_state_uses_preview_modal_flow(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        self.assertIn('id="state-selection-preview"', html)
        self.assertIn('id="state-selection-preview-btn"', html)
        self.assertIn("Run Preview first for the current tokens.", html)
        self.assertIn("renderSelectionPreviewReport(report)", html)
        self.assertIn("stateSelectionApply.disabled = false", html)
        self.assertNotIn("window.confirm(", html)

    def test_render_impact_plan_apply_opens_preview_modal_directly(self):
        html = render_group_diff_html(
            make_doc(),
            group_selector="計算倍率変更",
            impact_preview_payload={
                "impactSummary": {"impactedGroupCount": 1, "unchangedGroupCount": 0, "impactedGroups": []},
                "affectedBriefs": [],
                "warningSummary": {"total": 0, "kinds": {}},
                "stateDiff": {},
                "selectionPlans": {"handoffs": {"tokens": ["groupBriefs:g1"], "count": 1}},
            },
            impact_preview_label="old -> new using state",
            impact_state_label="review.state.json",
        )
        self.assertIn("openStateSelectionPreviewWithTokens(", html)
        self.assertIn('planName ? "impact:" + planName : "impact"', html)
        self.assertIn("state.importedStatePayload,", html)
        self.assertIn('base=" + baseLabel', html)
        self.assertIn('(baseLabel ? "\\nbase=" + baseLabel : "")', html)
        self.assertIn("selection plan is empty", html)

    def test_render_impact_preview_state_diff_keeps_detail_rows_for_all_sections(self):
        html = render_group_diff_html(
            make_doc(),
            group_selector="計算倍率変更",
            impact_preview_payload={
                "impactSummary": {"impactedGroupCount": 1, "unchangedGroupCount": 0, "impactedGroups": []},
                "affectedBriefs": [],
                "warningSummary": {"total": 0, "kinds": {}},
                "mergeSummary": {"diff": {
                    "reviews": {
                        "addedDetails": [{"key": "c1", "preview": "reviewed", "selectionToken": "reviews:c1"}],
                        "removedDetails": [],
                        "changedDetails": [],
                        "addedCount": 1,
                        "removedCount": 0,
                        "changedCount": 0,
                        "unchangedCount": 0,
                    },
                    "groupBriefs": {
                        "addedDetails": [],
                        "removedDetails": [],
                        "changedDetails": [{"key": "g-pr01", "beforePreview": "draft", "afterPreview": "ready", "selectionToken": "groupBriefs:g-pr01"}],
                        "addedCount": 0,
                        "removedCount": 0,
                        "changedCount": 1,
                        "unchangedCount": 0,
                    },
                    "analysisState": {
                        "addedDetails": [{"key": "selectedGroupId", "preview": "g-pr01", "selectionToken": "analysisState:selectedGroupId"}],
                        "removedDetails": [],
                        "changedDetails": [],
                        "addedCount": 1,
                        "removedCount": 0,
                        "changedCount": 0,
                        "unchangedCount": 0,
                    },
                    "threadState": {
                        "addedDetails": [],
                        "removedDetails": [],
                        "changedDetails": [{"key": "__files:src/a.ts", "beforePreview": "{}", "afterPreview": "{\"open\":true}", "selectionToken": "threadState.__files:src/a.ts"}],
                        "addedCount": 0,
                        "removedCount": 0,
                        "changedCount": 1,
                        "unchangedCount": 0,
                    },
                }},
                "selectionPlans": {"handoffs": {"tokens": ["groupBriefs:g-pr01"], "count": 1}},
            },
            impact_preview_label="old -> new using state",
            impact_state_label="review.state.json",
        )
        self.assertIn(">c1<", html)
        self.assertIn(">g-pr01<", html)
        self.assertIn(">selectedGroupId<", html)
        self.assertIn("__files:src/a.ts", html)

    def test_render_group_brief_card_and_embeds_group_briefs(self):
        doc = make_doc()
        doc["groupBriefs"] = {
            "g-pr01": {
                "status": "ready",
                "summary": "倍率変更の意図を reviewer に共有する",
                "focusPoints": ["演算子変更", "副作用なし"],
                "testEvidence": ["unit test compute"],
                "questionsForReviewer": ["*2 が妥当か"],
            }
        }
        html = render_group_diff_html(doc, group_selector="計算倍率変更", save_state_url="/api/state")
        embedded = extract_report_doc_json(html)
        self.assertIn("Review Handoff", html)
        self.assertIn("id='group-brief-card'", html)
        self.assertIn("id='edit-group-brief'", html)
        self.assertIn("倍率変更の意図を reviewer に共有する", html)
        self.assertIn('"groupBriefs"', html)
        self.assertEqual(embedded["groupBriefs"]["g-pr01"]["status"], "ready")

    def test_render_embeds_full_state_sections(self):
        doc = make_doc()
        doc["groupBriefs"] = {"g-pr01": {"status": "ready", "summary": "handoff"}}
        doc["analysisState"] = {"selectedGroupId": "g-pr01"}
        doc["threadState"] = {"c1": {"open": True}}
        html = render_group_diff_html(doc, group_selector="計算倍率変更", save_state_url="/api/state")
        embedded = extract_report_doc_json(html)
        self.assertEqual(embedded["groupBriefs"]["g-pr01"]["summary"], "handoff")
        self.assertEqual(embedded["analysisState"]["selectedGroupId"], "g-pr01")
        self.assertEqual(embedded["threadState"]["c1"]["open"], True)

    def test_render_includes_state_restore_helpers(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更", save_state_url="/api/state")
        self.assertIn("function persistAnalysisState()", html)
        self.assertIn("function restoreAnalysisState()", html)
        self.assertIn('analysisState.selectedChunkId', html)
        self.assertIn("function persistThreadState()", html)
        self.assertIn("function restoreThreadState()", html)
        self.assertIn("nextState.__files = fileState", html)

    def test_render_all_groups_uses_review_map_sidebar(self):
        doc = make_doc()
        doc["groupBriefs"] = {
            "g-pr01": {"status": "ready", "summary": "計算確認"},
            "g-pr02": {"status": "draft", "summary": "正規化確認"},
        }
        html = render_group_diff_html(doc, group_selector="all")
        self.assertIn("Review Map", html)
        self.assertIn("data-nav-type='group'", html)
        self.assertIn("g-pr01", html)
        self.assertIn("計算確認", html)
        self.assertIn("g-pr02", html)

    def test_export_script_writes_html(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            input_path = repo / "doc.diffgr.json"
            output_path = repo / "out" / "report.html"
            input_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            code = export_html_main(
                [
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--group",
                    "計算倍率変更",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(output_path.exists())
            html = output_path.read_text(encoding="utf-8")
            self.assertIn("計算倍率変更", html)
            self.assertIn("src/a.ts", html)

    def test_export_script_embeds_save_state_url(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            input_path = repo / "doc.diffgr.json"
            output_path = repo / "out" / "report.html"
            input_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            code = export_html_main(
                [
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--group",
                    "計算倍率変更",
                    "--save-state-url",
                    "/api/state",
                    "--save-state-label",
                    "Save Live",
                ]
            )
            self.assertEqual(code, 0)
            html = output_path.read_text(encoding="utf-8")
            config = extract_report_config_json(html)
            self.assertEqual(config.get("saveStateUrl"), "/api/state")
            self.assertEqual(config.get("saveStateLabel"), "Save Live")

    def test_export_script_overlays_external_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            input_path = repo / "doc.diffgr.json"
            state_path = repo / "state.json"
            output_path = repo / "out" / "report.html"
            input_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed"}},
                        "groupBriefs": {"g-pr01": {"summary": "handoff"}},
                        "analysisState": {"selectedChunkId": "c1"},
                        "threadState": {"c1": {"open": True}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            code = export_html_main(
                [
                    "--input",
                    str(input_path),
                    "--state",
                    str(state_path),
                    "--output",
                    str(output_path),
                    "--group",
                    "計算倍率変更",
                ]
            )
            self.assertEqual(code, 0)
            html = output_path.read_text(encoding="utf-8")
            embedded = extract_report_doc_json(html)
            config = extract_report_config_json(html)
            self.assertEqual(embedded["reviews"]["c1"]["status"], "reviewed")
            self.assertEqual(embedded["groupBriefs"]["g-pr01"]["summary"], "handoff")
            self.assertEqual(embedded["analysisState"]["selectedChunkId"], "c1")
            self.assertEqual(config.get("stateSourceLabel"), "overlay:state.json")

    def test_export_script_embeds_impact_preview_when_args_are_provided(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            old_path = repo / "old.diffgr.json"
            input_path = repo / "new.diffgr.json"
            state_path = repo / "review.state.json"
            output_path = repo / "out" / "report.html"
            old_doc = make_doc()
            new_doc = make_doc()
            new_doc["chunks"][0]["lines"][2]["text"] = "  return a * 3;"
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False), encoding="utf-8")
            input_path.write_text(json.dumps(new_doc, ensure_ascii=False), encoding="utf-8")
            state_path.write_text(
                json.dumps({"groupBriefs": {"g-pr01": {"status": "ready", "summary": "handoff"}}}, ensure_ascii=False),
                encoding="utf-8",
            )
            code = export_html_main(
                [
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--group",
                    "計算倍率変更",
                    "--impact-old",
                    str(old_path),
                    "--impact-state",
                    str(state_path),
                ]
            )
            self.assertEqual(code, 0)
            html = output_path.read_text(encoding="utf-8")
            self.assertIn('id="toggle-impact-preview"', html)
            self.assertIn("Impact</h3>", html)
            self.assertIn("Group Brief Changes", html)
            config = extract_report_config_json(html)
            self.assertEqual(
                config["impactPreviewReport"]["sourceLabel"],
                "old.diffgr.json -> new.diffgr.json using review.state.json",
            )

    def test_export_script_rejects_partial_impact_args(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            input_path = repo / "doc.diffgr.json"
            output_path = repo / "out" / "report.html"
            input_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            code = export_html_main(
                [
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                    "--group",
                    "計算倍率変更",
                    "--impact-old",
                    str(input_path),
                ]
            )
            self.assertEqual(code, 1)

    def test_render_embeds_state_diff_report_in_config(self):
        state_diff_report = {
            "sourceLabel": "state.json",
            "stateDiff": {
                "reviews": {"addedDetails": [{"key": "c1", "preview": "reviewed", "selectionToken": "reviews:c1"}], "removedDetails": [], "changedDetails": [], "addedCount": 1, "removedCount": 0, "changedCount": 0, "unchangedCount": 0},
                "groupBriefs": {"addedDetails": [], "removedDetails": [], "changedDetails": [], "addedCount": 0, "removedCount": 0, "changedCount": 0, "unchangedCount": 0},
                "analysisState": {"addedDetails": [], "removedDetails": [], "changedDetails": [], "addedCount": 0, "removedCount": 0, "changedCount": 0, "unchangedCount": 0},
                "threadState": {"addedDetails": [], "removedDetails": [], "changedDetails": [], "addedCount": 0, "removedCount": 0, "changedCount": 0, "unchangedCount": 0},
            },
            "rows": [{"section": "reviews", "changeKind": "added", "key": "c1", "preview": "reviewed", "selectionToken": "reviews:c1"}],
            "selectionTokens": ["reviews:c1"],
        }
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更", state_diff_report=state_diff_report)
        config = extract_report_config_json(html)
        self.assertIsNotNone(config.get("stateDiffReport"))
        self.assertEqual(config["stateDiffReport"]["sourceLabel"], "state.json")
        self.assertEqual(config["stateDiffReport"]["selectionTokens"], ["reviews:c1"])

    def test_render_includes_build_stat_diff_report_and_render_stat_diff_report_js(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        self.assertIn("function buildStateDiffReport(baseState, otherState, sourceLabel)", html)
        self.assertIn("function renderStateDiffReport(report)", html)
        self.assertIn("function buildSelectionPreviewReport(rawTokens, sourceLabel, baseLabel)", html)
        self.assertIn("function renderSelectionPreviewReport(report)", html)
        self.assertIn("function buildDiffRows(diff)", html)

    def test_render_diff_state_uses_build_stat_diff_report(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        self.assertIn("buildStateDiffReport(currentStatePayload(), state.importedStatePayload, label)", html)
        self.assertIn("renderStateDiffReport(report)", html)
        self.assertNotIn("renderStateDiffSummary(diff)", html)

    def test_render_apply_selected_state_uses_build_selection_preview_report(self):
        html = render_group_diff_html(make_doc(), group_selector="計算倍率変更")
        self.assertIn("buildSelectionPreviewReport(rawTokens", html)
        self.assertIn("renderSelectionPreviewReport(report)", html)

    def test_export_script_embeds_state_diff_report_when_state_is_provided(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            input_path = repo / "doc.diffgr.json"
            state_path = repo / "state.json"
            output_path = repo / "out" / "report.html"
            doc = make_doc()
            input_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {"reviews": {"c1": {"status": "reviewed"}}, "groupBriefs": {}},
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            code = export_html_main(
                [
                    "--input", str(input_path),
                    "--state", str(state_path),
                    "--output", str(output_path),
                    "--group", "計算倍率変更",
                ]
            )
            self.assertEqual(code, 0)
            html = output_path.read_text(encoding="utf-8")
            config = extract_report_config_json(html)
            self.assertIsNotNone(config.get("stateDiffReport"))
            self.assertEqual(config["stateDiffReport"]["sourceLabel"], "state.json")
            self.assertIn("reviews:c1", config["stateDiffReport"]["selectionTokens"])

    def test_export_script_rejects_mismatched_state_and_impact_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            old_path = repo / "old.diffgr.json"
            input_path = repo / "new.diffgr.json"
            state_path = repo / "view.state.json"
            impact_state_path = repo / "impact.state.json"
            output_path = repo / "out" / "report.html"
            old_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            input_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            state_path.write_text(json.dumps({"reviews": {}}, ensure_ascii=False), encoding="utf-8")
            impact_state_path.write_text(json.dumps({"reviews": {}}, ensure_ascii=False), encoding="utf-8")
            code = export_html_main(
                [
                    "--input",
                    str(input_path),
                    "--state",
                    str(state_path),
                    "--output",
                    str(output_path),
                    "--group",
                    "計算倍率変更",
                    "--impact-old",
                    str(old_path),
                    "--impact-state",
                    str(impact_state_path),
                ]
            )
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
