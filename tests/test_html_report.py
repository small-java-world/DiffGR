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
        self.assertIn("src/a.ts", html)
        self.assertNotIn("src/b.ts", html)
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
        self.assertIn("src/c.ts", html)
        self.assertNotIn("src/a.ts", html)
        self.assertNotIn("src/b.ts", html)

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


if __name__ == "__main__":
    unittest.main()
