import json
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr import viewer_app as view_diffgr_app
from diffgr import viewer_render


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
        self.assertEqual(args.state, None)
        self.assertEqual(args.page_size, 15)
        self.assertFalse(args.once)

    def test_parse_args_accepts_state(self):
        args = view_diffgr_app.parse_app_args(["sample.diffgr.json", "--state", "review.state.json"])
        self.assertEqual(args.path, "sample.diffgr.json")
        self.assertEqual(args.state, "review.state.json")

    def test_run_once_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = view_diffgr_app.run_app([str(file_path), "--once", "--page-size", "5", "--ui", "prompt"])
            self.assertEqual(code, 0)

    def test_run_once_overlays_external_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "review.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed"}},
                        "analysisState": {"selectedChunkId": "c1"},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                code = view_diffgr_app.run_app(
                    [str(file_path), "--state", str(state_path), "--once", "--page-size", "5", "--ui", "prompt"]
                )
            self.assertEqual(code, 0)
            self.assertIn("reviewed", stdout.getvalue())

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

    def test_prompt_ui_save_writes_external_state_when_state_path_is_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "review.state.json"
            original_text = json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n"
            file_path.write_text(original_text, encoding="utf-8")
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[
                    "group g-all",
                    "set-status c1 reviewed",
                    "comment c1 looks good",
                    "line-comment c1 - 2 add line note",
                    "brief g-all handoff summary",
                    "brief-status g-all ready",
                    "brief-meta g-all updatedAt 2026-03-14T12:00:00Z",
                    "brief-meta g-all sourceHead abc1234",
                    "brief-list g-all focus auth path | validation gap",
                    "brief-list g-all evidence unit test added | manual check",
                    "brief-list g-all tradeoff extra query remains",
                    "brief-list g-all question confirm rename intent",
                    "brief-mentions g-all @alice | @bob",
                    "brief-ack g-all alice;2026-03-14T10:00:00Z;reviewed | bob;2026-03-14T11:00:00Z;ack",
                    "detail c1",
                    "save",
                    "quit",
                ],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            self.assertEqual(file_path.read_text(encoding="utf-8"), original_text)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reviews"]["c1"]["status"], "reviewed")
            self.assertEqual(payload["reviews"]["c1"]["comment"], "looks good")
            self.assertEqual(payload["reviews"]["c1"]["lineComments"][0]["comment"], "line note")
            self.assertEqual(payload["reviews"]["c1"]["lineComments"][0]["newLine"], 2)
            self.assertEqual(payload["groupBriefs"]["g-all"]["summary"], "handoff summary")
            self.assertEqual(payload["groupBriefs"]["g-all"]["status"], "ready")
            self.assertEqual(payload["groupBriefs"]["g-all"]["updatedAt"], "2026-03-14T12:00:00Z")
            self.assertEqual(payload["groupBriefs"]["g-all"]["sourceHead"], "abc1234")
            self.assertEqual(payload["groupBriefs"]["g-all"]["focusPoints"], ["auth path", "validation gap"])
            self.assertEqual(payload["groupBriefs"]["g-all"]["testEvidence"], ["unit test added", "manual check"])
            self.assertEqual(payload["groupBriefs"]["g-all"]["knownTradeoffs"], ["extra query remains"])
            self.assertEqual(payload["groupBriefs"]["g-all"]["questionsForReviewer"], ["confirm rename intent"])
            self.assertEqual(payload["groupBriefs"]["g-all"]["mentions"], ["@alice", "@bob"])
            self.assertEqual(payload["groupBriefs"]["g-all"]["acknowledgedBy"][0]["actor"], "alice")
            self.assertEqual(payload["groupBriefs"]["g-all"]["acknowledgedBy"][1]["note"], "ack")
            self.assertEqual(payload["analysisState"]["currentGroupId"], "g-all")
            self.assertEqual(payload["analysisState"]["selectedChunkId"], "c1")
            self.assertEqual(payload["threadState"]["selectedLineAnchor"]["anchorKey"], "add::2")
            self.assertIn("Saved state", stdout.getvalue())

    def test_prompt_ui_save_persists_analysis_state_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "review.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=["group g-all", "status reviewed", "file src/a", "detail c1", "save", "quit"],
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["analysisState"]["currentGroupId"], "g-all")
            self.assertEqual(payload["analysisState"]["promptStatusFilter"], "reviewed")
            self.assertEqual(payload["analysisState"]["filterText"], "src/a")
            self.assertEqual(payload["analysisState"]["selectedChunkId"], "c1")

    def test_prompt_ui_save_writes_source_document_without_state_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=["set-status c1 needsReReview", "save", "quit"],
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            written = json.loads(file_path.read_text(encoding="utf-8"))
            self.assertEqual(written["reviews"]["c1"]["status"], "needsReReview")
            self.assertTrue(file_path.with_suffix(file_path.suffix + ".bak").exists())

    def test_prompt_ui_detail_shows_chunk_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            doc = make_doc()
            doc["reviews"] = {
                "c1": {
                    "status": "reviewed",
                    "comment": "looks good",
                    "lineComments": [{"oldLine": None, "newLine": 2, "lineType": "add", "comment": "line note"}],
                }
            }
            file_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["detail c1", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Chunk Detail", output)
            self.assertIn("looks good", output)
            self.assertIn("Line Comments", output)
            self.assertIn("line note", output)

    def test_prompt_ui_brief_show_displays_group_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            doc = make_doc()
            doc["groupBriefs"] = {
                "g-all": {
                    "status": "ready",
                    "summary": "handoff summary",
                    "updatedAt": "2026-03-14T12:00:00Z",
                    "sourceHead": "abc1234",
                    "focusPoints": ["auth path"],
                    "testEvidence": ["unit test"],
                    "knownTradeoffs": ["extra query"],
                    "questionsForReviewer": ["confirm rename intent"],
                    "mentions": ["@alice", "@bob"],
                    "acknowledgedBy": [
                        {"actor": "alice", "at": "2026-03-14T10:00:00Z", "note": "reviewed"},
                        {"actor": "bob", "at": "2026-03-14T11:00:00Z", "note": "ack"},
                    ],
                }
            }
            file_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["brief-show g-all", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Group Brief", output)
            self.assertIn("handoff summary", output)
            self.assertIn("ready", output)
            self.assertIn("2026-03-14T12:00:00Z", output)
            self.assertIn("abc1234", output)
            self.assertIn("Focus Points", output)
            self.assertIn("Test Evidence", output)
            self.assertIn("Known Tradeoffs", output)
            self.assertIn("Questions", output)
            self.assertIn("Mentions", output)
            self.assertIn("Acknowledged By", output)
            self.assertIn("auth path", output)
            self.assertIn("unit test", output)
            self.assertIn("extra query", output)
            self.assertIn("confirm rename intent", output)
            self.assertIn("@alice", output)
            self.assertIn("2026-03-14T10:00:00Z", output)
            self.assertIn("reviewed", output)

    def test_prompt_ui_restores_analysis_state_filters_from_external_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "review.state.json"
            doc = make_doc()
            doc["chunks"].append(
                {
                    "id": "c2",
                    "filePath": "lib/b.ts",
                    "old": {"start": 3, "count": 1},
                    "new": {"start": 3, "count": 2},
                    "lines": [{"kind": "add", "text": "x", "oldLine": None, "newLine": 3}],
                }
            )
            doc["assignments"]["g-all"].append("c2")
            file_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed"}, "c2": {"status": "unreviewed"}},
                        "analysisState": {
                            "currentGroupId": "g-all",
                            "promptStatusFilter": "reviewed",
                            "filterText": "src/a",
                            "selectedChunkId": "c1",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("src/a.ts", output)
            self.assertNotIn("lib/b.ts", output)

    def test_prompt_ui_line_comment_clear_removes_anchor_and_line_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "review.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[
                    "line-comment c1 - 2 add line note",
                    "line-comment c1 - 2 add clear",
                    "save",
                    "quit",
                ],
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            review = payload["reviews"].get("c1", {})
            self.assertNotIn("lineComments", review)
            self.assertFalse(payload.get("threadState", {}).get("selectedLineAnchor"))

    def test_prompt_ui_state_show_renders_current_state_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[
                    "group g-all",
                    "set-status c1 reviewed",
                    "comment c1 looks good",
                    "line-comment c1 - 2 add line note",
                    "brief g-all handoff summary",
                    "brief-status g-all ready",
                    "detail c1",
                    "state-show",
                    "quit",
                ],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("State Summary", output)
            self.assertIn("reviewed=1", output)
            self.assertIn("lineComments=1", output)
            self.assertIn("ready=1", output)
            self.assertIn("group=g-all", output)
            self.assertIn("chunk=c1", output)

    def test_prompt_ui_state_show_includes_bound_state_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "bound.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(json.dumps({"reviews": {}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["state-show", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("BoundState", output)

    def test_prompt_ui_state_bind_updates_default_target_for_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "dynamic.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"state-bind {state_path}", "set-status c1 reviewed", "state-save-as", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reviews"]["c1"]["status"], "reviewed")
            self.assertIn("Bound state", stdout.getvalue())

    def test_prompt_ui_state_unbind_clears_default_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "bound.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(json.dumps({"reviews": {}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=["state-unbind", "state-diff", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Unbound state", output)
            self.assertIn("Usage: state-diff <path-to.state.json>", output)

    def test_prompt_ui_state_save_as_writes_state_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            export_path = Path(tmp) / "out" / "prompt.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[
                    "group g-all",
                    "set-status c1 reviewed",
                    f"state-save-as {export_path}",
                    "quit",
                ],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            payload = json.loads(export_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reviews"]["c1"]["status"], "reviewed")
            self.assertEqual(payload["analysisState"]["currentGroupId"], "g-all")
            self.assertIn("Wrote state", stdout.getvalue())

    def test_prompt_ui_state_save_as_uses_bound_state_path_when_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "bound.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=["group g-all", "set-status c1 reviewed", "state-save-as", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reviews"]["c1"]["status"], "reviewed")
            self.assertEqual(payload["analysisState"]["currentGroupId"], "g-all")
            self.assertIn("Wrote state", stdout.getvalue())

    def test_prompt_ui_state_load_applies_external_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "import.state.json"
            doc = make_doc()
            doc["chunks"].append(
                {
                    "id": "c2",
                    "filePath": "lib/b.ts",
                    "old": {"start": 3, "count": 1},
                    "new": {"start": 3, "count": 2},
                    "lines": [{"kind": "add", "text": "x", "oldLine": None, "newLine": 3}],
                }
            )
            doc["assignments"]["g-all"].append("c2")
            file_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed"}},
                        "groupBriefs": {"g-all": {"status": "ready", "summary": "loaded handoff"}},
                        "analysisState": {
                            "currentGroupId": "g-all",
                            "promptStatusFilter": "reviewed",
                            "filterText": "src/a",
                            "selectedChunkId": "c1",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=[f"state-load {state_path}", "brief-show g-all", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Loaded state", output)
            loaded_section = output.split("Loaded state:", maxsplit=1)[1]
            self.assertIn("src/a.ts", loaded_section)
            self.assertNotIn("lib/b.ts", loaded_section)
            self.assertIn("loaded handoff", loaded_section)

    def test_prompt_ui_state_load_uses_bound_state_path_when_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "bound.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "reviewed"}}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["state-load", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Loaded state", output)
            self.assertIn("reviewed", output)

    def test_prompt_ui_state_diff_shows_change_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "diff.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed"}},
                        "groupBriefs": {"g-all": {"summary": "handoff"}},
                        "analysisState": {"currentGroupId": "g-all"},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=["set-status c1 needsReReview", f"state-diff {state_path}", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("State Diff vs", output)
            self.assertIn("reviews", output)
            self.assertIn("changed=1", output)
            self.assertIn("groupBriefs", output)
            self.assertIn("added=1", output)
            self.assertIn("reviews keys", output)
            self.assertIn("c1", output)
            self.assertIn("needsReReview", output)
            self.assertIn("{\"status\":\"reviewed\"}", output)
            self.assertIn("reviews:c1", output)
            self.assertIn("groupBriefs keys", output)
            self.assertIn("g-all", output)

    def test_prompt_ui_state_diff_uses_bound_state_path_when_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "bound.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "reviewed"}}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=["set-status c1 needsReReview", "state-diff", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("State Diff vs", output)
            self.assertIn("changed=1", output)

    def test_prompt_ui_state_merge_merges_external_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "merge.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {
                            "c1": {
                                "status": "needsReReview",
                                "comment": "incoming",
                                "lineComments": [{"oldLine": None, "newLine": 2, "lineType": "add", "comment": "note"}],
                            }
                        },
                        "groupBriefs": {"g-all": {"status": "ready", "summary": "merged handoff"}},
                        "analysisState": {"currentGroupId": "g-all", "selectedChunkId": "c1"},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=["set-status c1 reviewed", f"state-merge {state_path}", "brief-show g-all", "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Merged state", output)
            self.assertIn("applied=1", output)
            self.assertIn("State Merge", output)
            self.assertIn("Warnings", output)
            merged_section = output.split("Merged state:", maxsplit=1)[1]
            self.assertIn("needsReReview", merged_section)
            self.assertIn("merged handoff", merged_section)
            self.assertIn("ready=1", merged_section)

    def test_prompt_ui_state_bind_reports_replaced_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            first_state = Path(tmp) / "one.state.json"
            second_state = Path(tmp) / "two.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"state-bind {first_state}", f"state-bind {second_state}", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Bound state", output)
            self.assertIn("replaced", output)

    def test_prompt_ui_state_merge_uses_bound_state_path_when_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "bound.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "needsReReview"}}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=["set-status c1 reviewed", "state-merge", "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Merged state", output)
            self.assertIn("needsReReview=1", output)

    def test_prompt_ui_state_merge_preview_does_not_mutate_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "preview.state.json"
            doc = make_doc()
            doc["reviews"] = {"c1": {"status": "reviewed"}}
            file_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "needsReReview"}},
                        "groupBriefs": {"g-all": {"status": "ready", "summary": "preview handoff"}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"state-merge-preview {state_path}", "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Merge preview", output)
            self.assertIn("Group Brief Changes", output)
            state_show = output.split("State Summary", maxsplit=1)[1]
            self.assertNotIn("needsReReview=1", state_show)

    def test_prompt_ui_state_merge_preview_reports_brief_changes_and_warning_kinds(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "preview.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "needsReReview", "comment": "incoming"}},
                        "groupBriefs": {"g-all": {"status": "ready", "summary": "preview handoff"}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"state-merge-preview {state_path}", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Source", output)
            self.assertIn("Change Summary", output)
            self.assertIn("Warnings", output)
            self.assertIn("preview handoff", output)

    def test_prompt_ui_impact_merge_preview_reports_impacted_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            old_path = Path(tmp) / "old.diffgr.json"
            new_path = Path(tmp) / "new.diffgr.json"
            state_path = Path(tmp) / "impact.state.json"
            old_doc = make_doc()
            old_doc["chunks"][0]["id"] = "old1"
            old_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 1;", "oldLine": None, "newLine": 1}]
            old_doc["assignments"] = {"g-all": ["old1"]}
            old_doc["reviews"] = {}
            new_doc = make_doc()
            new_doc["chunks"][0]["id"] = "new1"
            new_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 2;", "oldLine": None, "newLine": 1}]
            new_doc["assignments"] = {"g-all": ["new1"]}
            new_doc["reviews"] = {}
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"old1": {"status": "reviewed"}}, "groupBriefs": {"g-all": {"status": "ready", "summary": "handoff"}}}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"impact-merge-preview {old_path} {new_path} {state_path}", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Impact merge preview", output)
            self.assertIn("Impact", output)
            self.assertIn("Affected Briefs", output)
            self.assertIn("Selection Plans", output)
            self.assertIn("g-all", output)
            self.assertIn("handoff", output)

    def test_prompt_ui_impact_apply_preview_reports_selection_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            old_path = Path(tmp) / "old.diffgr.json"
            new_path = Path(tmp) / "new.diffgr.json"
            state_path = Path(tmp) / "impact.state.json"
            old_doc = make_doc()
            old_doc["chunks"][0]["id"] = "old1"
            old_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 1;", "oldLine": None, "newLine": 1}]
            old_doc["assignments"] = {"g-all": ["old1"]}
            old_doc["reviews"] = {}
            new_doc = make_doc()
            new_doc["chunks"][0]["id"] = "new1"
            new_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 2;", "oldLine": None, "newLine": 1}]
            new_doc["assignments"] = {"g-all": ["new1"]}
            new_doc["reviews"] = {}
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"old1": {"status": "reviewed"}}, "groupBriefs": {"g-all": {"status": "ready", "summary": "handoff"}}}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"impact-apply-preview {old_path} {new_path} {state_path} handoffs", "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Impact apply preview", output)
            self.assertIn("selection plan: handoffs", output)
            self.assertIn("groupBriefs:g-all", output)
            state_show = output.split("State Summary", maxsplit=1)[1]
            self.assertNotIn("ready=1", state_show)

    def test_prompt_ui_impact_apply_updates_session_state_for_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            old_path = Path(tmp) / "old.diffgr.json"
            new_path = Path(tmp) / "new.diffgr.json"
            state_path = Path(tmp) / "impact.state.json"
            old_doc = make_doc()
            old_doc["chunks"][0]["id"] = "old1"
            old_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 1;", "oldLine": None, "newLine": 1}]
            old_doc["assignments"] = {"g-all": ["old1"]}
            old_doc["reviews"] = {}
            new_doc = make_doc()
            new_doc["chunks"][0]["id"] = "new1"
            new_doc["chunks"][0]["lines"] = [{"kind": "add", "text": "return 2;", "oldLine": None, "newLine": 1}]
            new_doc["assignments"] = {"g-all": ["new1"]}
            new_doc["reviews"] = {}
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"old1": {"status": "reviewed"}}, "groupBriefs": {"g-all": {"status": "ready", "summary": "handoff"}}}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"impact-apply {old_path} {new_path} {state_path} handoffs", "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Impact apply", output)
            self.assertIn("selection plan: handoffs", output)
            self.assertIn("groupBriefs:g-all", output)
            state_show = output.split("State Summary", maxsplit=1)[1]
            self.assertIn("ready=1", state_show)

    def test_prompt_ui_impact_apply_reports_empty_plan_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            old_path = Path(tmp) / "old.diffgr.json"
            new_path = Path(tmp) / "new.diffgr.json"
            state_path = Path(tmp) / "impact.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            old_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(json.dumps({"reviews": {"c1": {"status": "reviewed"}}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"impact-apply {old_path} {new_path} {state_path} ui", "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Impact apply", output)
            self.assertIn("selection plan is empty", output)
            state_show = output.split("State Summary", maxsplit=1)[1]
            self.assertNotIn("needsReReview=1", state_show)

    def test_prompt_ui_state_apply_updates_only_selected_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "apply.state.json"
            doc = make_doc()
            doc["reviews"] = {"c1": {"status": "reviewed"}}
            doc["analysisState"] = {"currentGroupId": "g-all", "selectedChunkId": "c1"}
            file_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "needsReReview"}},
                        "analysisState": {"currentGroupId": "g-all", "selectedChunkId": "c9"},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"state-apply {state_path} reviews:c1", "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Applied state selection", output)
            self.assertIn("reviews:c1", output)
            self.assertIn("needsReReview=1", output)
            self.assertIn("chunk=c1", output)

    def test_prompt_ui_state_apply_preview_does_not_mutate_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "apply.state.json"
            doc = make_doc()
            doc["reviews"] = {"c1": {"status": "reviewed"}}
            file_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "needsReReview"}}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"state-apply-preview {state_path} reviews:c1", "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("State apply preview", output)
            state_show = output.split("State Summary", maxsplit=1)[1]
            self.assertNotIn("needsReReview=1", state_show)

    def test_prompt_ui_state_apply_uses_bound_state_when_path_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "apply.state.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"reviews": {"c1": {"status": "needsReReview"}}}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=["state-apply reviews:c1", "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--state", str(state_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Applied state selection", output)
            self.assertIn("needsReReview=1", output)

    def test_prompt_ui_state_apply_accepts_quoted_thread_state_file_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "apply.state.json"
            doc = make_doc()
            doc["threadState"] = {"__files": {"src/my file.ts": {"open": True}}}
            file_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps({"threadState": {"__files": {"src/my file.ts": {"open": False}}}}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f'state-apply {state_path} "threadState.__files:src/my file.ts"', "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Applied state selection", output)
            self.assertIn("files=1", output)

    def test_prompt_ui_state_reset_clears_loaded_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            state_path = Path(tmp) / "import.state.json"
            doc = make_doc()
            doc["chunks"].append(
                {
                    "id": "c2",
                    "filePath": "lib/b.ts",
                    "old": {"start": 3, "count": 1},
                    "new": {"start": 3, "count": 2},
                    "lines": [{"kind": "add", "text": "x", "oldLine": None, "newLine": 3}],
                }
            )
            doc["assignments"]["g-all"].append("c2")
            file_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed"}},
                        "groupBriefs": {"g-all": {"status": "ready", "summary": "loaded handoff"}},
                        "analysisState": {
                            "currentGroupId": "g-all",
                            "promptStatusFilter": "reviewed",
                            "filterText": "src/a",
                            "selectedChunkId": "c1",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[f"state-load {state_path}", "state-reset", "state-show", "quit"],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])
            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Reset state", output)
            reset_section = output.split("Reset state:", maxsplit=1)[1]
            self.assertIn("src/a.ts", reset_section)
            self.assertIn("lib/b.ts", reset_section)
            self.assertIn("State Summary", reset_section)
            self.assertIn("reviewed=0", reset_section)
            self.assertIn("ready=0", reset_section)
            self.assertIn("group=-", reset_section)

    def test_set_group_brief_list_clear_prunes_empty_record(self):
        doc = {"groupBriefs": {"g-all": {"focusPoints": ["auth path"]}}}

        view_diffgr_app._set_group_brief_list(doc, "g-all", "focus", "")

        self.assertEqual(doc["groupBriefs"], {})

    def test_set_group_brief_mentions_and_acks_normalize_entries(self):
        doc = {"groupBriefs": {}}

        view_diffgr_app._set_group_brief_mentions(doc, "g-all", " @alice |  | @bob ")
        view_diffgr_app._set_group_brief_acks(
            doc,
            "g-all",
            "alice;2026-03-14T10:00:00Z;reviewed | ;ignored | bob;;ack",
        )

        self.assertEqual(doc["groupBriefs"]["g-all"]["mentions"], ["@alice", "@bob"])
        self.assertEqual(
            doc["groupBriefs"]["g-all"]["acknowledgedBy"],
            [
                {"actor": "alice", "at": "2026-03-14T10:00:00Z", "note": "reviewed"},
                {"actor": "bob", "note": "ack"},
            ],
        )

    def test_set_group_brief_meta_clear_prunes_empty_record(self):
        doc = {"groupBriefs": {"g-all": {"updatedAt": "2026-03-14T12:00:00Z"}}}

        view_diffgr_app._set_group_brief_meta(doc, "g-all", "updatedAt", "")

        self.assertEqual(doc["groupBriefs"], {})

    def test_set_group_brief_acks_clear_prunes_empty_record(self):
        doc = {"groupBriefs": {"g-all": {"acknowledgedBy": [{"actor": "alice"}]}}}

        view_diffgr_app._set_group_brief_acks(doc, "g-all", "")

        self.assertEqual(doc["groupBriefs"], {})

    def test_set_line_comment_replaces_existing_anchor_without_duplication(self):
        doc = {
            "reviews": {
                "c1": {
                    "lineComments": [
                        {"oldLine": None, "newLine": 2, "lineType": "add", "comment": "old"},
                    ]
                }
            },
            "threadState": {
                "selectedLineAnchor": {
                    "anchorKey": "add::2",
                    "oldLine": None,
                    "newLine": 2,
                    "lineType": "add",
                }
            },
        }

        view_diffgr_app._set_line_comment(
            doc,
            "c1",
            old_line=None,
            new_line=2,
            line_type="add",
            comment="new",
        )

        self.assertEqual(
            doc["reviews"]["c1"]["lineComments"],
            [{"oldLine": None, "newLine": 2, "lineType": "add", "comment": "new"}],
        )
        self.assertEqual(doc["threadState"]["selectedLineAnchor"]["anchorKey"], "add::2")

    def test_replace_prompt_state_rebuilds_indexes_and_restores_filters(self):
        doc = make_doc()
        doc["chunks"].append(
            {
                "id": "c2",
                "filePath": "lib/b.ts",
                "old": {"start": 3, "count": 1},
                "new": {"start": 3, "count": 2},
                "lines": [{"kind": "add", "text": "x", "oldLine": None, "newLine": 3}],
            }
        )
        doc["assignments"]["g-all"].append("c2")

        (
            updated_doc,
            chunk_map,
            status_map,
            active_group,
            active_status,
            active_file,
            selected_chunk_id,
        ) = view_diffgr_app._replace_prompt_state(
            doc,
            {
                "reviews": {"c1": {"status": "reviewed"}},
                "groupBriefs": {"g-all": {"summary": "handoff"}},
                "analysisState": {
                    "currentGroupId": "g-all",
                    "promptStatusFilter": "reviewed",
                    "filterText": "src/a",
                    "selectedChunkId": "c1",
                },
                "threadState": {},
            },
        )

        self.assertEqual(updated_doc["groupBriefs"]["g-all"]["summary"], "handoff")
        self.assertIn("c2", chunk_map)
        self.assertEqual(status_map["c1"], "reviewed")
        self.assertEqual(status_map["c2"], "unreviewed")
        self.assertEqual(active_group, "g-all")
        self.assertEqual(active_status, "reviewed")
        self.assertEqual(active_file, "src/a")
        self.assertEqual(selected_chunk_id, "c1")

    def test_restore_prompt_analysis_state_ignores_invalid_values(self):
        doc = {
            "assignments": {"g-all": ["c1"]},
            "analysisState": {
                "currentGroupId": "missing",
                "promptStatusFilter": "invalid",
                "filterText": "",
                "selectedChunkId": "missing",
            },
        }
        chunk_map = {"c1": {"id": "c1"}}

        active_group, active_status, active_file, selected_chunk_id = view_diffgr_app._restore_prompt_analysis_state(
            doc,
            chunk_map,
        )

        self.assertIsNone(active_group)
        self.assertIsNone(active_status)
        self.assertIsNone(active_file)
        self.assertIsNone(selected_chunk_id)

    def test_persist_prompt_analysis_state_clears_empty_values(self):
        doc = {"analysisState": {"currentGroupId": "g-all", "promptStatusFilter": "reviewed", "filterText": "src/a", "selectedChunkId": "c1"}}

        view_diffgr_app._persist_prompt_analysis_state(
            doc,
            active_group=None,
            active_status=None,
            active_file=None,
            selected_chunk_id=None,
        )

        self.assertNotIn("analysisState", doc)

    def test_render_state_summary_outputs_expected_sections(self):
        console = Console(record=True, width=120, file=io.StringIO())

        viewer_render.render_state_summary(
            console,
            {
                "reviews": {
                    "total": 2,
                    "statusCounts": {"reviewed": 1, "needsReReview": 1},
                    "chunkCommentCount": 1,
                    "lineCommentCount": 3,
                },
                "groupBriefs": {
                    "total": 1,
                    "statusCounts": {"draft": 0, "ready": 1, "acknowledged": 0, "stale": 0},
                },
                "analysisState": {"currentGroupId": "g-all", "selectedChunkId": "c1", "filterText": "src/a", "chunkDetailViewMode": "compact"},
                "threadState": {"chunkEntryCount": 1, "fileEntryCount": 2, "hasSelectedLineAnchor": True},
            },
        )

        output = console.export_text()
        self.assertIn("State Summary", output)
        self.assertIn("reviewed=1", output)
        self.assertIn("lineComments=3", output)
        self.assertIn("ready=1", output)
        self.assertIn("group=g-all", output)
        self.assertIn("selectedLineAnchor=yes", output)

    def test_render_group_brief_detail_outputs_mentions_and_acks(self):
        console = Console(record=True, width=120, file=io.StringIO())

        viewer_render.render_group_brief_detail(
            console,
            {"id": "g-all", "name": "All", "order": 1},
            {
                "status": "ready",
                "summary": "handoff summary",
                "mentions": ["@alice"],
                "acknowledgedBy": [{"actor": "alice", "at": "2026-03-14T10:00:00Z", "note": "reviewed"}],
            },
            3,
        )

        output = console.export_text()
        self.assertIn("Group Brief", output)
        self.assertIn("Mentions", output)
        self.assertIn("@alice", output)
        self.assertIn("Acknowledged By", output)
        self.assertIn("2026-03-14T10:00:00Z", output)

    def test_parse_line_number_token_handles_dash_and_rejects_zero(self):
        self.assertIsNone(view_diffgr_app._parse_line_number_token("-"))
        self.assertIsNone(view_diffgr_app._parse_line_number_token("none"))
        with self.assertRaises(ValueError):
            view_diffgr_app._parse_line_number_token("0")

    def test_line_anchor_key_formats_missing_lines(self):
        self.assertEqual(view_diffgr_app._line_anchor_key("add", None, 12), "add::12")
        self.assertEqual(view_diffgr_app._line_anchor_key("delete", 8, None), "delete:8:")

    def test_set_group_brief_status_clear_prunes_empty_record(self):
        doc = {"groupBriefs": {"g-all": {"status": "ready"}}}

        view_diffgr_app._set_group_brief_status(doc, "g-all", "")

        self.assertEqual(doc["groupBriefs"], {})

    def test_set_group_brief_summary_clear_keeps_record_when_other_fields_exist(self):
        doc = {"groupBriefs": {"g-all": {"summary": "handoff", "focusPoints": ["auth path"]}}}

        view_diffgr_app._set_group_brief_summary(doc, "g-all", "")

        self.assertEqual(doc["groupBriefs"]["g-all"]["focusPoints"], ["auth path"])
        self.assertNotIn("summary", doc["groupBriefs"]["g-all"])

    def test_render_chunk_detail_outputs_fingerprints_and_line_comment_count(self):
        console = Console(record=True, width=120, file=io.StringIO())

        viewer_render.render_chunk_detail(
            console,
            {
                "id": "c1",
                "filePath": "src/a.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 2},
                "header": "hdr",
                "fingerprints": {"stable": "fp1"},
                "lines": [{"kind": "add", "text": "x", "oldLine": None, "newLine": 2}],
            },
            "reviewed",
            max_lines=10,
            review_record={
                "comment": "looks good",
                "lineComments": [{"oldLine": None, "newLine": 2, "lineType": "add", "comment": "line note"}],
            },
        )

        output = console.export_text()
        self.assertIn("Chunk Detail", output)
        self.assertIn("fingerprints", output)
        self.assertIn("lineComments", output)
        self.assertIn("line note", output)

    def test_render_command_help_includes_prompt_state_commands(self):
        console = Console(record=True, width=140, file=io.StringIO())

        viewer_render.render_command_help(console)

        output = console.export_text()
        self.assertIn("state-show", output)
        self.assertIn("state-bind <path>", output)
        self.assertIn("state-unbind", output)
        self.assertIn("state-load <path>", output)
        self.assertIn("state-apply <path?> <selection...>", output)
        self.assertIn("state-reset", output)
        self.assertIn("state-save-as <path>", output)

    def test_prompt_ui_state_load_missing_file_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["state-load missing.state.json", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            self.assertIn("State load failed", stdout.getvalue())

    def test_resolve_prompt_output_path_returns_absolute_path(self):
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                resolved = view_diffgr_app._resolve_prompt_output_path("out/review.state.json")
            finally:
                os.chdir(old_cwd)
        self.assertTrue(resolved.is_absolute())
        self.assertTrue(str(resolved).endswith("out/review.state.json"))

    def test_resolve_prompt_state_target_uses_bound_path_when_value_empty(self):
        bound = Path("/tmp/review.state.json")
        self.assertEqual(view_diffgr_app._resolve_prompt_state_target("", bound), bound)
        self.assertIsNone(view_diffgr_app._resolve_prompt_state_target("", None))

    def test_prompt_ui_unknown_command_shows_error_and_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["wat", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Unknown command: wat", output)
            self.assertIn("Commands", output)

    def test_prompt_ui_line_comment_invalid_line_type_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["line-comment c1 - 2 meta note", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            self.assertIn("Invalid lineType: meta", stdout.getvalue())

    def test_prompt_ui_line_comment_invalid_line_number_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["line-comment c1 0 2 add note", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            self.assertIn("Invalid line number", stdout.getvalue())

    def test_prompt_ui_brief_meta_invalid_field_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["brief-meta g-all nope value", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            self.assertIn("Invalid brief meta field: nope", stdout.getvalue())

    def test_prompt_ui_brief_list_invalid_field_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["brief-list g-all nope value", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            self.assertIn("Invalid brief list field: nope", stdout.getvalue())

    def test_prompt_ui_save_failure_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(view_diffgr_app, "_save_prompt_document", side_effect=RuntimeError("boom")):
                with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["save", "quit"]):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                        code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            self.assertIn("Save failed:", stdout.getvalue())
            self.assertIn("boom", stdout.getvalue())

    def test_prompt_ui_usage_errors_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[
                    "state-load",
                    "state-apply",
                    "state-apply-preview",
                    "state-merge",
                    "state-merge-preview",
                    "impact-merge-preview",
                    "impact-apply-preview",
                    "impact-apply",
                    "state-save-as",
                    "detail",
                    "brief-show",
                    "set-status",
                    "comment",
                    "line-comment",
                    "brief-status",
                    "brief-meta",
                    "brief",
                    "brief-list",
                    "brief-mentions",
                    "brief-ack",
                    "list nope",
                    "quit",
                ],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Usage: state-load <path-to.state.json>", output)
            self.assertIn("Usage: state-apply <path-to.state.json> <selection...>", output)
            self.assertIn("Usage: state-apply-preview <path-to.state.json> <selection...>", output)
            self.assertIn("Usage: state-merge <path-to.state.json>", output)
            self.assertIn("Usage: state-merge-preview <path-to.state.json>", output)
            self.assertIn("state-merge-preview (with", output)
            self.assertIn("Usage: impact-merge-preview <old.diffgr.json> <new.diffgr.json> <state.json?>", output)
            self.assertIn("Usage: impact-apply-preview <old.diffgr.json> <new.diffgr.json> <state.json?>", output)
            self.assertIn("Usage: impact-apply <old.diffgr.json> <new.diffgr.json> <state.json?>", output)
            self.assertIn("<handoffs|reviews|ui|all>", output)
            self.assertIn("Usage: state-save-as <path-to.state.json>", output)
            self.assertIn("Usage: detail <chunk_id>", output)
            self.assertIn("Usage: brief-show <group_id>", output)
            self.assertIn("Usage: set-status <chunk_id> <status>", output)
            self.assertIn("Usage: comment <chunk_id> <text|clear>", output)
            self.assertIn("Usage: line-comment <chunk_id> <oldLine|-> <newLine|-> <lineType> <text|clear>", output)
            self.assertIn("Usage: brief-status <group_id> <status|clear>", output)
            self.assertIn("Usage: brief-meta <group_id> <updatedAt|sourceHead> <value|clear>", output)
            self.assertIn("Usage: brief <group_id> <summary|clear>", output)
            self.assertIn("Usage: brief-list <group_id> <focus|evidence|tradeoff|question>", output)
            self.assertIn("Usage: brief-mentions <group_id> <mention1 | mention2 | clear>", output)
            self.assertIn("Usage: brief-ack <group_id> <actor;at;note | clear>", output)
            self.assertIn("Invalid page: nope", output)

    def test_prompt_ui_state_merge_missing_file_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["state-merge missing.state.json", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            self.assertIn("State merge failed", stdout.getvalue())

    def test_prompt_ui_state_apply_missing_file_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["state-apply missing.state.json reviews:c1", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            self.assertIn("State apply failed", stdout.getvalue())

    def test_prompt_ui_state_diff_missing_file_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(view_diffgr_app.Prompt, "ask", side_effect=["state-diff missing.state.json", "quit"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            self.assertIn("State diff failed", stdout.getvalue())

    def test_prompt_ui_unknown_targets_and_invalid_values_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "doc.diffgr.json"
            file_path.write_text(json.dumps(make_doc(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            with mock.patch.object(
                view_diffgr_app.Prompt,
                "ask",
                side_effect=[
                    "group missing-group",
                    "detail missing-chunk",
                    "set-status missing-chunk reviewed",
                    "comment missing-chunk note",
                    "status bogus",
                    "set-status c1 bogus",
                    "brief-show missing-group",
                    "brief-status missing-group ready",
                    "brief-status g-all bogus",
                    "brief-meta missing-group updatedAt x",
                    "brief-list missing-group focus x",
                    "brief-mentions missing-group @alice",
                    "brief-ack missing-group alice;now;ok",
                    "quit",
                ],
            ):
                stdout = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = view_diffgr_app.run_app([str(file_path), "--ui", "prompt"])

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("Unknown group in assignments: missing-group", output)
            self.assertIn("Chunk not found: missing-chunk", output)
            self.assertIn("Invalid status: bogus", output)
            self.assertIn("Unknown group: missing-group", output)
            self.assertIn("Invalid brief status: bogus", output)


if __name__ == "__main__":
    unittest.main()
