import json
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr import viewer_app as view_diffgr_app


def make_doc() -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {
            "title": "UT Doc",
            "createdAt": "2026-02-22T00:00:00Z",
            "source": {"type": "example", "base": "a", "head": "b"},
        },
        "groups": [{"id": "g-all", "name": "All", "order": 1}],
        "chunks": [
            {
                "id": "c1",
                "filePath": "src/a.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 2},
                "lines": [
                    {"kind": "context", "text": "a", "oldLine": 1, "newLine": 1},
                    {"kind": "add", "text": "b", "oldLine": None, "newLine": 2},
                ],
            }
        ],
        "assignments": {"g-all": ["c1"]},
        "reviews": {},
    }


class TestViewDiffgrApp(unittest.TestCase):
    def test_parse_args_defaults(self):
        args = view_diffgr_app.parse_app_args(["sample.diffgr.json"])
        self.assertEqual(args.path, "sample.diffgr.json")
        self.assertEqual(args.page_size, 15)
        self.assertFalse(args.once)

    def test_run_once_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = view_diffgr_app.run_app([str(file_path), "--once", "--page-size", "5", "--ui", "prompt"])
            self.assertEqual(code, 0)

    def test_run_with_missing_file_returns_error(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = view_diffgr_app.run_app(["not-found.diffgr.json", "--once", "--ui", "prompt"])
        self.assertEqual(code, 1)

    def test_run_with_invalid_page_size_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = view_diffgr_app.run_app([str(file_path), "--once", "--page-size", "0", "--ui", "prompt"])
            self.assertEqual(code, 2)

    def test_run_once_resolves_path_with_repo_root_fallback(self):
        old_cwd = Path.cwd()
        try:
            os.chdir(ROOT / "scripts")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = view_diffgr_app.run_app(
                    ["samples/diffgr/ts20-5pr.named.diffgr.json", "--once", "--page-size", "5", "--ui", "prompt"]
                )
        finally:
            os.chdir(old_cwd)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
