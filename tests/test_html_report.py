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
        self.assertIn('id="save-reviews"', html)
        self.assertIn('id="download-json"', html)
        self.assertIn('id="copy-reviews"', html)
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
        self.assertEqual(config.get("saveReviewsUrl"), "")
        self.assertEqual(config.get("saveReviewsLabel"), "Save to App")
        self.assertIn('id="save-reviews" type="button" hidden', html)

    def test_render_embeds_save_config_when_url_is_provided(self):
        html = render_group_diff_html(
            make_doc(),
            group_selector="計算倍率変更",
            save_reviews_url="/api/reviews",
            save_reviews_label="Sync",
        )
        config = extract_report_config_json(html)
        self.assertEqual(config.get("saveReviewsUrl"), "/api/reviews")
        self.assertEqual(config.get("saveReviewsLabel"), "Sync")

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

    def test_export_script_embeds_save_reviews_url(self):
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
                    "--save-reviews-url",
                    "/api/reviews",
                    "--save-reviews-label",
                    "Save Live",
                ]
            )
            self.assertEqual(code, 0)
            html = output_path.read_text(encoding="utf-8")
            config = extract_report_config_json(html)
            self.assertEqual(config.get("saveReviewsUrl"), "/api/reviews")
            self.assertEqual(config.get("saveReviewsLabel"), "Save Live")


if __name__ == "__main__":
    unittest.main()
