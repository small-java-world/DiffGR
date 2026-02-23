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

from scripts.check_virtual_pr_coverage import main as check_main  # noqa: E402


def make_doc() -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "UT Coverage", "createdAt": "2026-02-22T00:00:00Z"},
        "groups": [
            {"id": "g1", "name": "A", "order": 1},
            {"id": "g2", "name": "B", "order": 2},
        ],
        "chunks": [
            {"id": "c1", "filePath": "a.ts", "old": {"start": 1, "count": 1}, "new": {"start": 1, "count": 1}, "lines": []},
            {"id": "c2", "filePath": "b.ts", "old": {"start": 2, "count": 1}, "new": {"start": 2, "count": 1}, "lines": []},
        ],
        "assignments": {"g1": ["c1"], "g2": ["c2"]},
        "reviews": {},
    }


class TestCheckVirtualPrCoverage(unittest.TestCase):
    def test_ok_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "doc.diffgr.json"
            path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = check_main(["--input", str(path)])
        self.assertEqual(code, 0)

    def test_unassigned_returns_two_and_writes_prompt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "doc.diffgr.json"
            doc = make_doc()
            doc["assignments"] = {"g1": ["c1"]}  # c2 missing
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            prompt_path = root / "prompt.md"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = check_main(["--input", str(path), "--write-prompt", str(prompt_path)])
            self.assertEqual(code, 2)
            self.assertTrue(prompt_path.exists())
            prompt = prompt_path.read_text(encoding="utf-8")
            self.assertIn("Unassigned chunks", prompt)
            self.assertIn("c2", prompt)

    def test_duplicate_returns_two(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "doc.diffgr.json"
            doc = make_doc()
            doc["assignments"]["g2"].append("c1")  # duplicate assignment
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = check_main(["--input", str(path), "--json"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
