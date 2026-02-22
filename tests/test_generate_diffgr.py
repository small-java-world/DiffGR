import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr import generator as generate_diffgr


class TestGenerateDiffgr(unittest.TestCase):
    def test_normalize_diff_path(self):
        self.assertEqual(generate_diffgr.normalize_diff_path("a/src/app.ts"), "src/app.ts")
        self.assertEqual(generate_diffgr.normalize_diff_path("b/src/app.ts"), "src/app.ts")
        self.assertIsNone(generate_diffgr.normalize_diff_path("/dev/null"))
        self.assertEqual(generate_diffgr.normalize_diff_path("src/app.ts"), "src/app.ts")

    def test_parse_unified_diff_with_hunk_and_meta_line(self):
        diff_text = "\n".join(
            [
                "diff --git a/src/a.ts b/src/a.ts",
                "--- a/src/a.ts",
                "+++ b/src/a.ts",
                "@@ -1,2 +1,3 @@ function demo()",
                " line1",
                "-line2",
                "+line2_changed",
                "+line3",
                "\\ No newline at end of file",
            ]
        )
        files = generate_diffgr.parse_unified_diff(diff_text)
        self.assertEqual(len(files), 1)
        file_entry = files[0]
        self.assertEqual(file_entry["a_path"], "src/a.ts")
        self.assertEqual(file_entry["b_path"], "src/a.ts")
        self.assertEqual(len(file_entry["hunks"]), 1)

        hunk = file_entry["hunks"][0]
        self.assertEqual(hunk["old"], {"start": 1, "count": 2})
        self.assertEqual(hunk["new"], {"start": 1, "count": 3})
        self.assertEqual(hunk["header"], "function demo()")
        self.assertEqual([line["kind"] for line in hunk["lines"]], ["context", "delete", "add", "add", "meta"])
        self.assertEqual(hunk["lines"][1]["oldLine"], 2)
        self.assertEqual(hunk["lines"][2]["newLine"], 2)

    def test_build_chunk_adds_fingerprints_and_id(self):
        lines = [
            {"kind": "context", "text": "x", "oldLine": 1, "newLine": 1},
            {"kind": "add", "text": "y", "oldLine": None, "newLine": 2},
        ]
        chunk = generate_diffgr.build_chunk(
            file_path="src/file.ts",
            old_range={"start": 1, "count": 1},
            new_range={"start": 1, "count": 2},
            header="fn",
            lines=lines,
        )
        self.assertIn("id", chunk)
        self.assertEqual(len(chunk["id"]), 64)
        self.assertEqual(chunk["fingerprints"].keys(), {"stable", "strong"})
        self.assertEqual(len(chunk["fingerprints"]["stable"]), 64)
        self.assertEqual(len(chunk["fingerprints"]["strong"]), 64)
        self.assertEqual(chunk["header"], "fn")

    def test_build_chunk_metadata_only_supports_extra_meta(self):
        chunk = generate_diffgr.build_chunk(
            file_path="src/file.ts",
            old_range={"start": 0, "count": 0},
            new_range={"start": 0, "count": 0},
            header=None,
            lines=[],
            extra_meta={"diffHeaderLines": ["new file mode 100644"]},
        )
        self.assertEqual(chunk["lines"], [])
        self.assertIn("x-meta", chunk)
        self.assertEqual(chunk["x-meta"]["diffHeaderLines"][0], "new file mode 100644")


if __name__ == "__main__":
    unittest.main()
