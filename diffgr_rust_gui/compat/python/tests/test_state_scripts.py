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

from scripts.apply_diffgr_state import main as apply_state_main  # noqa: E402
from scripts.apply_diffgr_state_diff import main as apply_state_diff_main  # noqa: E402
from scripts.diff_diffgr_state import main as diff_state_main  # noqa: E402
from scripts.extract_diffgr_state import main as extract_state_main  # noqa: E402
from scripts.merge_diffgr_state import main as merge_state_main  # noqa: E402
from scripts.preview_rebased_merge import main as preview_rebased_merge_main  # noqa: E402
from scripts.rebase_diffgr_state import main as rebase_state_main  # noqa: E402
from scripts.summarize_diffgr_state import main as summarize_state_main  # noqa: E402


def make_doc() -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "UT"},
        "groups": [{"id": "g1", "name": "G1", "order": 1}],
        "chunks": [
            {
                "id": "c1",
                "filePath": "src/a.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 1},
                "header": "h1",
                "lines": [],
            }
        ],
        "assignments": {"g1": ["c1"]},
        "reviews": {"c1": {"status": "reviewed"}},
        "groupBriefs": {"g1": {"summary": "handoff"}},
        "analysisState": {"currentGroupId": "g1", "selectedChunkId": "c1"},
        "threadState": {"c1": {"open": True}},
    }


class TestStateScripts(unittest.TestCase):
    def test_extract_diffgr_state_writes_state_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.diffgr.json"
            output_path = root / "state.json"
            input_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            code = extract_state_main(["--input", str(input_path), "--output", str(output_path)])

            self.assertEqual(code, 0)
            state = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(state["reviews"]["c1"]["status"], "reviewed")
            self.assertEqual(state["groupBriefs"]["g1"]["summary"], "handoff")
            self.assertEqual(state["analysisState"]["currentGroupId"], "g1")
            self.assertTrue(state["threadState"]["c1"]["open"])

    def test_apply_diffgr_state_writes_updated_doc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.diffgr.json"
            state_path = root / "state.json"
            output_path = root / "output.diffgr.json"
            doc = make_doc()
            doc["reviews"] = {}
            doc.pop("groupBriefs", None)
            doc.pop("analysisState", None)
            doc.pop("threadState", None)
            input_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "needsReReview"}},
                        "groupBriefs": {"g1": {"summary": "incoming"}},
                        "analysisState": {"currentGroupId": "g1"},
                        "threadState": {"c1": {"open": False}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            code = apply_state_main(
                ["--input", str(input_path), "--state", str(state_path), "--output", str(output_path)]
            )

            self.assertEqual(code, 0)
            out = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(out["reviews"]["c1"]["status"], "needsReReview")
            self.assertEqual(out["groupBriefs"]["g1"]["summary"], "incoming")
            self.assertEqual(out["analysisState"]["currentGroupId"], "g1")
            self.assertFalse(out["threadState"]["c1"]["open"])

    def test_merge_diffgr_state_writes_merged_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            input_a = root / "a.state.json"
            input_b = root / "b.state.json"
            output_path = root / "merged.state.json"
            base_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed", "comment": "base"}},
                        "groupBriefs": {"g1": {"status": "draft", "summary": "base"}},
                        "analysisState": {"currentGroupId": "g1"},
                        "threadState": {"c1": {"open": True}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            input_a.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "needsReReview", "comment": "incoming"}},
                        "groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            input_b.write_text(
                json.dumps(
                    {
                        "analysisState": {"selectedChunkId": "c1"},
                        "threadState": {"c1": {"open": False}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            code = merge_state_main(
                [
                    "--base",
                    str(base_path),
                    "--input",
                    str(input_a),
                    "--input",
                    str(input_b),
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(code, 0)
            merged = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["reviews"]["c1"]["status"], "needsReReview")
            self.assertEqual(merged["reviews"]["c1"]["comment"], "incoming")
            self.assertEqual(merged["groupBriefs"]["g1"]["status"], "ready")
            self.assertEqual(merged["analysisState"]["selectedChunkId"], "c1")
            self.assertFalse(merged["threadState"]["c1"]["open"])

    def test_merge_diffgr_state_preview_prints_summary_without_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            input_a = root / "a.state.json"
            base_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed", "comment": "base"}},
                        "groupBriefs": {"g1": {"status": "draft", "summary": "base"}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            input_a.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "needsReReview", "comment": "incoming"}},
                        "groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = merge_state_main(["--base", str(base_path), "--input", str(input_a), "--preview"])

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Preview:", output)
            self.assertIn("Source:", output)
            self.assertIn("Change Summary:", output)
            self.assertIn("Warnings:", output)
            self.assertIn("Group Brief Changes:", output)
            self.assertIn("g1: changed", output)
            self.assertIn("State Diff:", output)

    def test_merge_diffgr_state_preview_json_summary_does_not_require_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            input_a = root / "a.state.json"
            base_path.write_text(json.dumps({"reviews": {"c1": {"status": "reviewed"}}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            input_a.write_text(json.dumps({"reviews": {"c1": {"status": "needsReReview"}}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = merge_state_main(["--base", str(base_path), "--input", str(input_a), "--preview", "--json-summary"])

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["preview"])
            self.assertIn("report", payload)
            self.assertEqual(payload["summary"]["diff"]["reviews"]["changed"], ["c1"])

    def test_preview_rebased_merge_prints_impact_and_briefs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old_path = root / "old.diffgr.json"
            new_path = root / "new.diffgr.json"
            state_path = root / "state.json"
            old_doc = make_doc()
            old_doc["chunks"][0]["id"] = "old1"
            old_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 1;", "oldLine": None, "newLine": 1}]
            old_doc["assignments"] = {"g1": ["old1"]}
            old_doc["groups"] = [{"id": "g1", "name": "G1", "order": 1}]
            old_doc["reviews"] = {}
            new_doc = make_doc()
            new_doc["chunks"][0]["id"] = "new1"
            new_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 2;", "oldLine": None, "newLine": 1}]
            new_doc["assignments"] = {"g1": ["new1"]}
            new_doc["groups"] = [{"id": "g1", "name": "G1", "order": 1}]
            new_doc["reviews"] = {}
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"old1": {"status": "reviewed"}}, "groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}}}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = preview_rebased_merge_main(["--old", str(old_path), "--new", str(new_path), "--state", str(state_path)])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Source:", output)
            self.assertIn("Change Summary:", output)
            self.assertIn("Impact:", output)
            self.assertIn("Warnings:", output)
            self.assertIn("State Diff:", output)
            self.assertIn("Affected Briefs:", output)
            self.assertIn("Selection Plans:", output)
            self.assertIn("g1", output)

    def test_preview_rebased_merge_json_keeps_raw_payload_and_adds_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old_path = root / "old.diffgr.json"
            new_path = root / "new.diffgr.json"
            state_path = root / "state.json"
            old_doc = make_doc()
            old_doc["chunks"][0]["id"] = "old1"
            old_doc["assignments"] = {"g1": ["old1"]}
            old_doc["groups"] = [{"id": "g1", "name": "G1", "order": 1}]
            old_doc["reviews"] = {}
            new_doc = make_doc()
            new_doc["chunks"][0]["id"] = "new1"
            new_doc["assignments"] = {"g1": ["new1"]}
            new_doc["groups"] = [{"id": "g1", "name": "G1", "order": 1}]
            new_doc["reviews"] = {}
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"old1": {"status": "reviewed"}}, "groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}}}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = preview_rebased_merge_main(["--old", str(old_path), "--new", str(new_path), "--state", str(state_path), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertIn("impactReport", payload)
            self.assertIn("rebasedState", payload)
            self.assertIn("report", payload)
            self.assertIn("warningSummary", payload["report"])
            self.assertIn("selectionPlans", payload["report"])

    def test_preview_rebased_merge_tokens_only_prints_plan_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old_path = root / "old.diffgr.json"
            new_path = root / "new.diffgr.json"
            state_path = root / "state.json"
            old_doc = make_doc()
            old_doc["chunks"][0]["id"] = "old1"
            old_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 1;", "oldLine": None, "newLine": 1}]
            old_doc["assignments"] = {"g1": ["old1"]}
            old_doc["groups"] = [{"id": "g1", "name": "G1", "order": 1}]
            old_doc["reviews"] = {}
            new_doc = make_doc()
            new_doc["chunks"][0]["id"] = "new1"
            new_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 2;", "oldLine": None, "newLine": 1}]
            new_doc["assignments"] = {"g1": ["new1"]}
            new_doc["groups"] = [{"id": "g1", "name": "G1", "order": 1}]
            new_doc["reviews"] = {}
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"old1": {"status": "reviewed"}}, "groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}}}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = preview_rebased_merge_main(
                    ["--old", str(old_path), "--new", str(new_path), "--state", str(state_path), "--tokens-only", "handoffs"]
                )
            self.assertEqual(code, 0)
            self.assertIn("groupBriefs:g1", stdout.getvalue().splitlines())

    def test_diff_diffgr_state_prints_human_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            other_path = root / "other.state.json"
            base_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed"}},
                        "groupBriefs": {"g1": {"summary": "old"}},
                        "analysisState": {"currentGroupId": "g1"},
                        "threadState": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            other_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "needsReReview"}, "c2": {"status": "reviewed"}},
                        "groupBriefs": {"g1": {"summary": "new"}},
                        "analysisState": {"currentGroupId": "g2"},
                        "threadState": {"selectedLineAnchor": {"anchorKey": "add::2"}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = diff_state_main(["--base", str(base_path), "--other", str(other_path)])

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("reviews: added=1 removed=0 changed=1 unchanged=0", output)
            self.assertIn("[select: reviews:c2]", output)
            self.assertIn("[select: reviews:c1]", output)
            self.assertIn("analysisState: added=0 removed=0 changed=1 unchanged=0", output)

    def test_apply_diffgr_state_diff_writes_selected_keys_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            other_path = root / "other.state.json"
            output_path = root / "applied.state.json"
            base_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed"}},
                        "analysisState": {"currentGroupId": "g1", "selectedChunkId": "c1"},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            other_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "needsReReview"}},
                        "analysisState": {"currentGroupId": "g9", "selectedChunkId": "c9"},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            code = apply_state_diff_main(
                [
                    "--base",
                    str(base_path),
                    "--other",
                    str(other_path),
                    "--select",
                    "reviews:c1",
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reviews"]["c1"]["status"], "needsReReview")
            self.assertEqual(payload["analysisState"]["currentGroupId"], "g1")
            self.assertEqual(payload["analysisState"]["selectedChunkId"], "c1")

    def test_apply_diffgr_state_diff_accepts_thread_state_file_selection_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            other_path = root / "other.state.json"
            output_path = root / "applied.state.json"
            base_path.write_text(
                json.dumps({"threadState": {"__files": {"src/my file.ts": {"open": True}}}}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            other_path.write_text(
                json.dumps({"threadState": {"__files": {"src/my file.ts": {"open": False}}}}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )

            code = apply_state_diff_main(
                [
                    "--base",
                    str(base_path),
                    "--other",
                    str(other_path),
                    "--select",
                    "threadState.__files:src/my file.ts",
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(payload["threadState"]["__files"]["src/my file.ts"]["open"])

    def test_apply_diffgr_state_diff_preview_does_not_write_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            other_path = root / "other.state.json"
            output_path = root / "applied.state.json"
            base_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "reviewed"}}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            other_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "needsReReview"}}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = apply_state_diff_main(
                    [
                        "--base",
                        str(base_path),
                        "--other",
                        str(other_path),
                        "--select",
                        "reviews:c1",
                        "--preview",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertFalse(output_path.exists())
            self.assertIn("Preview:", stdout.getvalue())
            self.assertIn("Selection: reviews:c1", stdout.getvalue())
            self.assertIn("No-op:", stdout.getvalue())
            self.assertIn("Result Diff:", stdout.getvalue())
            self.assertIn("reviews: added=0 removed=0 changed=1 unchanged=0", stdout.getvalue())

    def test_apply_diffgr_state_diff_impact_plan_preview_uses_rebased_selection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            old_path = root / "old.diffgr.json"
            new_path = root / "new.diffgr.json"
            base_path.write_text(
                json.dumps({"reviews": {"old1": {"status": "reviewed"}}, "groupBriefs": {"g1": {"status": "draft", "summary": "base"}}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            old_doc = make_doc()
            old_doc["chunks"][0]["id"] = "old1"
            old_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 1;", "oldLine": None, "newLine": 1}]
            old_doc["assignments"] = {"g1": ["old1"]}
            old_doc["groups"] = [{"id": "g1", "name": "G1", "order": 1}]
            old_doc["reviews"] = {}
            new_doc = make_doc()
            new_doc["chunks"][0]["id"] = "new1"
            new_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 2;", "oldLine": None, "newLine": 1}]
            new_doc["assignments"] = {"g1": ["new1"]}
            new_doc["groups"] = [{"id": "g1", "name": "G1", "order": 1}]
            new_doc["reviews"] = {}
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = apply_state_diff_main(
                    [
                        "--base",
                        str(base_path),
                        "--impact-old",
                        str(old_path),
                        "--impact-new",
                        str(new_path),
                        "--impact-plan",
                        "handoffs",
                        "--preview",
                    ]
                )
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("plan=handoffs", output)
            self.assertIn("Selection: groupBriefs:g1", output)
            self.assertIn("No-op: 1", output)
            self.assertIn("Changed sections: 0", output)
            self.assertIn("old.diffgr.json -> new.diffgr.json using base.state.json plan=handoffs", output)

    def test_apply_diffgr_state_diff_impact_plan_empty_tokens_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            old_path = root / "old.diffgr.json"
            new_path = root / "new.diffgr.json"
            output_path = root / "applied.state.json"
            base_path.write_text(json.dumps({"reviews": {"c1": {"status": "reviewed"}}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            old_doc = make_doc()
            new_doc = make_doc()
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = apply_state_diff_main(
                    [
                        "--base",
                        str(base_path),
                        "--impact-old",
                        str(old_path),
                        "--impact-new",
                        str(new_path),
                        "--impact-plan",
                        "handoffs",
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertIn("Selection:", stdout.getvalue())
            self.assertIn("Applied: 0", stdout.getvalue())
            self.assertIn("Changed sections: 0", stdout.getvalue())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reviews"]["c1"]["status"], "reviewed")
            self.assertEqual(payload.get("groupBriefs", {}), {})

    def test_apply_diffgr_state_diff_rejects_select_with_impact_plan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            old_path = root / "old.diffgr.json"
            new_path = root / "new.diffgr.json"
            base_path.write_text(json.dumps({}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            old_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = apply_state_diff_main(
                    [
                        "--base",
                        str(base_path),
                        "--select",
                        "reviews:c1",
                        "--impact-old",
                        str(old_path),
                        "--impact-new",
                        str(new_path),
                        "--impact-plan",
                        "all",
                        "--preview",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("--select cannot be combined", stderr.getvalue())

    def test_diff_diffgr_state_prints_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            other_path = root / "other.state.json"
            base_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "reviewed"}}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            other_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "reviewed"}}, "analysisState": {"currentGroupId": "g1"}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = diff_state_main(["--base", str(base_path), "--other", str(other_path), "--json"])

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["reviews"]["unchanged"], ["c1"])
            self.assertEqual(payload["analysisState"]["added"], ["currentGroupId"])

    def test_rebase_diffgr_state_writes_rebased_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old_path = root / "old.diffgr.json"
            new_path = root / "new.diffgr.json"
            state_path = root / "old.state.json"
            output_path = root / "rebased.state.json"

            old_doc = make_doc()
            old_doc["chunks"][0]["id"] = "old1"
            old_doc["chunks"][0]["fingerprints"] = {"stable": "s1", "strong": "t-old"}
            old_doc["assignments"] = {"g1": ["old1"]}
            old_doc["reviews"] = {}
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            new_doc = make_doc()
            new_doc["chunks"][0]["id"] = "new1"
            new_doc["chunks"][0]["fingerprints"] = {"stable": "s1", "strong": "t-new"}
            new_doc["assignments"] = {"g1": ["new1"]}
            new_doc["reviews"] = {}
            new_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"old1": {"status": "reviewed"}},
                        "groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}},
                        "analysisState": {"currentGroupId": "g1", "selectedChunkId": "old1"},
                        "threadState": {"old1": {"open": True}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            code = rebase_state_main(
                [
                    "--old",
                    str(old_path),
                    "--new",
                    str(new_path),
                    "--state",
                    str(state_path),
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(code, 0)
            rebased = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(rebased["reviews"]["new1"]["status"], "reviewed")
            self.assertEqual(rebased["groupBriefs"]["g1"]["summary"], "handoff")
            self.assertEqual(rebased["analysisState"]["selectedChunkId"], "new1")
            self.assertTrue(rebased["threadState"]["new1"]["open"])

    def test_summarize_diffgr_state_json_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "state.json"
            input_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed", "comment": "ok"}},
                        "groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}},
                        "analysisState": {"currentGroupId": "g1", "selectedChunkId": "c1"},
                        "threadState": {"c1": {"open": True}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            saved_stdout = sys.stdout
            try:
                from io import StringIO

                buffer = StringIO()
                sys.stdout = buffer
                code = summarize_state_main(["--input", str(input_path), "--json"])
            finally:
                sys.stdout = saved_stdout

            self.assertEqual(code, 0)
            summary = json.loads(buffer.getvalue())
            self.assertEqual(summary["reviews"]["total"], 1)
            self.assertEqual(summary["groupBriefs"]["statusCounts"]["ready"], 1)
            self.assertEqual(summary["analysisState"]["currentGroupId"], "g1")

    def test_diff_diffgr_state_tokens_only_prints_selection_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.state.json"
            other_path = root / "other.state.json"
            base_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "reviewed"}}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            other_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "needsReReview"}}, "analysisState": {"selectedChunkId": "c1"}}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = diff_state_main(["--base", str(base_path), "--other", str(other_path), "--tokens-only"])

            self.assertEqual(code, 0)
            output = stdout.getvalue().splitlines()
            self.assertIn("reviews:c1", output)
            self.assertIn("analysisState:selectedChunkId", output)


if __name__ == "__main__":
    unittest.main()
