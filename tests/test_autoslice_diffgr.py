import json
import tempfile
import unittest
from pathlib import Path

from diffgr.autoslice import autoslice_document_by_commits
from diffgr.generator import build_diffgr_document, run_git


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestAutoSliceDiffgr(unittest.TestCase):
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

