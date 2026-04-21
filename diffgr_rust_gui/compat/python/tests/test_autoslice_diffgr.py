import json
import tempfile
import unittest
from pathlib import Path

from diffgr.autoslice import autoslice_document_by_commits, change_fingerprint_for_chunk, change_fingerprints_for_diff_text
from diffgr.generator import build_diffgr_document, run_git


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestAutoSliceDiffgr(unittest.TestCase):
    def test_change_fingerprint_for_chunk_distinguishes_header_and_blank_line_only_change(self):
        chunk_a = {
            "id": "c1",
            "filePath": "src/a.ts",
            "header": "@@ function alpha @@",
            "lines": [{"kind": "add", "text": "", "oldLine": None, "newLine": 10}],
        }
        chunk_b = {
            "id": "c2",
            "filePath": "src/a.ts",
            "header": "@@ function beta @@",
            "lines": [{"kind": "add", "text": "", "oldLine": None, "newLine": 10}],
        }

        self.assertNotEqual(change_fingerprint_for_chunk(chunk_a), change_fingerprint_for_chunk(chunk_b))

    def test_change_fingerprints_for_diff_text_includes_header_and_blank_line_only_change(self):
        diff_alpha = """diff --git a/src/a.ts b/src/a.ts
index 1111111..2222222 100644
--- a/src/a.ts
+++ b/src/a.ts
@@ -1,1 +1,2 @@ function alpha
 line
+
"""
        diff_beta = """diff --git a/src/a.ts b/src/a.ts
index 1111111..2222222 100644
--- a/src/a.ts
+++ b/src/a.ts
@@ -1,1 +1,2 @@ function beta
 line
+
"""

        self.assertNotEqual(
            change_fingerprints_for_diff_text(diff_alpha),
            change_fingerprints_for_diff_text(diff_beta),
        )

    def test_autoslice_by_commits_assigns_all_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, ["init"])
            run_git(repo, ["config", "user.email", "ut@example.com"])
            run_git(repo, ["config", "user.name", "UT"])

            file_path = repo / "a.txt"
            lines = [f"line {i:03d}" for i in range(1, 101)]
            write_lines(file_path, lines)
            run_git(repo, ["add", "."])
            run_git(repo, ["commit", "-m", "base"])
            base = run_git(repo, ["rev-parse", "HEAD"]).strip()

            # commit 1: edit line 10
            lines[9] = "line 010 - change1"
            write_lines(file_path, lines)
            run_git(repo, ["add", "."])
            run_git(repo, ["commit", "-m", "PR1: change line 10"])

            # commit 2: edit line 50 (far enough to avoid hunk merge)
            lines[49] = "line 050 - change2"
            write_lines(file_path, lines)
            run_git(repo, ["add", "."])
            run_git(repo, ["commit", "-m", "PR2: change line 50"])

            # commit 3: edit line 90
            lines[89] = "line 090 - change3"
            write_lines(file_path, lines)
            run_git(repo, ["add", "."])
            run_git(repo, ["commit", "-m", "PR3: change line 90"])
            feature = run_git(repo, ["rev-parse", "HEAD"]).strip()

            doc = build_diffgr_document(
                repo=repo,
                base_ref=base,
                feature_ref=feature,
                title="UT",
                include_patch=False,
            )
            self.assertGreaterEqual(len(doc["chunks"]), 3)
            source = doc.get("meta", {}).get("source", {})
            self.assertEqual(source.get("baseSha"), base)
            self.assertEqual(source.get("headSha"), feature)
            # base is an ancestor of feature in this test repo, so merge-base == base.
            self.assertEqual(source.get("mergeBaseSha"), base)

            new_doc, warnings = autoslice_document_by_commits(
                repo=repo,
                doc=json.loads(json.dumps(doc)),
                base_ref=base,
                feature_ref=feature,
                max_commits=10,
                name_style="pr",
            )
            self.assertEqual(warnings, [])
            self.assertEqual(len(new_doc["groups"]), 3)

            assigned = set()
            for ids in new_doc["assignments"].values():
                assigned.update(ids)
            self.assertEqual(assigned, {c["id"] for c in doc["chunks"]})

    def test_autoslice_warns_when_commit_history_is_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, ["init"])
            run_git(repo, ["config", "user.email", "ut@example.com"])
            run_git(repo, ["config", "user.name", "UT"])

            file_path = repo / "a.txt"
            lines = [f"line {i:03d}" for i in range(1, 21)]
            write_lines(file_path, lines)
            run_git(repo, ["add", "."])
            run_git(repo, ["commit", "-m", "base"])
            base = run_git(repo, ["rev-parse", "HEAD"]).strip()

            for index in range(3):
                lines[index] = f"line {index:03d} changed"
                write_lines(file_path, lines)
                run_git(repo, ["add", "."])
                run_git(repo, ["commit", "-m", f"PR{index + 1}: change"])
            feature = run_git(repo, ["rev-parse", "HEAD"]).strip()

            doc = build_diffgr_document(repo=repo, base_ref=base, feature_ref=feature, title="UT", include_patch=False)
            _, warnings = autoslice_document_by_commits(
                repo=repo,
                doc=doc,
                base_ref=base,
                feature_ref=feature,
                max_commits=1,
            )
            self.assertTrue(any("truncated" in warning for warning in warnings))

    def test_autoslice_can_fail_on_truncate(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, ["init"])
            run_git(repo, ["config", "user.email", "ut@example.com"])
            run_git(repo, ["config", "user.name", "UT"])

            file_path = repo / "a.txt"
            lines = [f"line {i:03d}" for i in range(1, 21)]
            write_lines(file_path, lines)
            run_git(repo, ["add", "."])
            run_git(repo, ["commit", "-m", "base"])
            base = run_git(repo, ["rev-parse", "HEAD"]).strip()

            for index in range(3):
                lines[index] = f"line {index:03d} changed"
                write_lines(file_path, lines)
                run_git(repo, ["add", "."])
                run_git(repo, ["commit", "-m", f"PR{index + 1}: change"])
            feature = run_git(repo, ["rev-parse", "HEAD"]).strip()

            doc = build_diffgr_document(repo=repo, base_ref=base, feature_ref=feature, title="UT", include_patch=False)
            with self.assertRaises(RuntimeError):
                autoslice_document_by_commits(
                    repo=repo,
                    doc=doc,
                    base_ref=base,
                    feature_ref=feature,
                    max_commits=1,
                    fail_on_truncate=True,
                )
