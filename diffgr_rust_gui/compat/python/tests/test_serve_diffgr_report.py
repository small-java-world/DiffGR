import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.serve_diffgr_report import (  # noqa: E402
    ServerState,
    _normalize_state_payload,
    save_review_state_to_file,
    save_review_state_to_document,
)


def extract_report_config_json(html: str) -> dict:
    marker = '<script id="report-config-json" type="application/json">'
    start = html.find(marker)
    if start < 0:
        raise AssertionError("embedded report-config-json script not found")
    end = html.find("</script>", start)
    if end < 0:
        raise AssertionError("embedded report-config-json script is not closed")
    return json.loads(html[start + len(marker) : end])


def make_doc() -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {
            "title": "UT Report",
            "createdAt": "2026-02-22T00:00:00Z",
            "source": {"type": "example", "base": "base", "head": "head"},
        },
        "groups": [{"id": "g-pr01", "name": "計算倍率変更", "order": 1}],
        "chunks": [
            {
                "id": "c1",
                "filePath": "src/a.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 1},
                "header": "export function compute()",
                "lines": [
                    {"kind": "context", "text": "return a;", "oldLine": 1, "newLine": 1},
                ],
            }
        ],
        "assignments": {"g-pr01": ["c1"]},
        "reviews": {},
    }


class TestServeDiffgrReport(unittest.TestCase):
    def test_normalize_state_payload_accepts_state_wrapper_and_partial_keys(self):
        wrapped = _normalize_state_payload(
            {
                "state": {
                    "reviews": {"c1": {"comment": "ok"}},
                    "groupBriefs": {"g1": {"summary": "handoff"}},
                }
            }
        )
        self.assertEqual(wrapped["reviews"]["c1"]["comment"], "ok")
        self.assertEqual(wrapped["groupBriefs"]["g1"]["summary"], "handoff")
        self.assertEqual(wrapped["analysisState"], {})
        self.assertEqual(wrapped["threadState"], {})

    def test_normalize_state_payload_rejects_invalid_shape(self):
        with self.assertRaises(RuntimeError):
            _normalize_state_payload({"state": []})
        with self.assertRaises(RuntimeError):
            _normalize_state_payload({"groupBriefs": []})
        with self.assertRaises(RuntimeError):
            _normalize_state_payload({"c1": {"comment": "ok"}})

    def test_save_review_state_to_document_persists_full_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "doc.diffgr.json"
            path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            result = save_review_state_to_document(
                path,
                {
                    "reviews": {"c1": {"comment": "line by line"}},
                    "groupBriefs": {"g-pr01": {"summary": "handoff"}},
                    "analysisState": {"selectedGroupId": "g-pr01"},
                    "threadState": {"c1": {"open": True}},
                },
            )
            self.assertEqual(result["reviewChunkCount"], 1)
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["reviews"]["c1"]["comment"], "line by line")
            self.assertEqual(updated["groupBriefs"]["g-pr01"]["summary"], "handoff")
            self.assertEqual(updated["analysisState"]["selectedGroupId"], "g-pr01")
            self.assertEqual(updated["threadState"]["c1"]["open"], True)

    def test_server_state_render_html_embeds_save_endpoint(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "doc.diffgr.json"
            path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            state = ServerState(
                source_path=path,
                state_path=None,
                group_selector="g-pr01",
                report_title=None,
                lock=threading.Lock(),
            )
            html = state.render_html()
            self.assertIn('"saveStateUrl": "/api/state"', html)
            self.assertIn('id="save-state"', html)

    def test_server_state_save_state_persists_full_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "doc.diffgr.json"
            path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            state = ServerState(
                source_path=path,
                state_path=None,
                group_selector="g-pr01",
                report_title=None,
                lock=threading.Lock(),
            )
            result = state.save_state(
                {
                    "reviews": {"c1": {"comment": "ok"}},
                    "groupBriefs": {"g-pr01": {"status": "ready", "summary": "handoff"}},
                    "analysisState": {"selectedChunkId": "c1"},
                    "threadState": {"c1": {"resolved": False}},
                }
            )
            self.assertEqual(result["reviewChunkCount"], 1)
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["groupBriefs"]["g-pr01"]["summary"], "handoff")
            self.assertEqual(updated["analysisState"]["selectedChunkId"], "c1")
            self.assertEqual(updated["threadState"]["c1"]["resolved"], False)

    def test_save_review_state_to_file_writes_state_json(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "state.json"
            result = save_review_state_to_file(
                path,
                {
                    "reviews": {"c1": {"comment": "ok"}},
                    "groupBriefs": {"g-pr01": {"summary": "handoff"}},
                    "analysisState": {"selectedChunkId": "c1"},
                    "threadState": {"c1": {"open": True}},
                },
            )
            self.assertEqual(result["reviewChunkCount"], 1)
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["reviews"]["c1"]["comment"], "ok")
            self.assertEqual(updated["groupBriefs"]["g-pr01"]["summary"], "handoff")
            self.assertEqual(updated["analysisState"]["selectedChunkId"], "c1")
            self.assertTrue(updated["threadState"]["c1"]["open"])

    def test_server_state_render_html_overlays_external_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "doc.diffgr.json"
            state_path = Path(tempdir) / "state.json"
            path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {
                        "reviews": {"c1": {"status": "reviewed"}},
                        "groupBriefs": {"g-pr01": {"summary": "handoff"}},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            state = ServerState(
                source_path=path,
                state_path=state_path,
                group_selector="g-pr01",
                report_title=None,
                lock=threading.Lock(),
            )
            html = state.render_html()
            self.assertIn("data-status='reviewed'", html)
            self.assertIn("handoff", html)

    def test_server_state_render_html_embeds_state_diff_report_when_state_is_provided(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "doc.diffgr.json"
            state_path = Path(tempdir) / "state.json"
            path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            state_path.write_text(
                json.dumps(
                    {"reviews": {"c1": {"status": "reviewed"}}, "groupBriefs": {}},
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            server_state = ServerState(
                source_path=path,
                state_path=state_path,
                group_selector="g-pr01",
                lock=threading.Lock(),
            )
            html = server_state.render_html()
            config = extract_report_config_json(html)
            self.assertIsNotNone(config.get("stateDiffReport"))
            self.assertEqual(config["stateDiffReport"]["sourceLabel"], "state.json")
            self.assertIn("reviews:c1", config["stateDiffReport"]["selectionTokens"])

    def test_server_state_render_html_embeds_impact_preview_when_configured(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "new.diffgr.json"
            old_path = Path(tempdir) / "old.diffgr.json"
            impact_state_path = Path(tempdir) / "impact.state.json"
            new_doc = make_doc()
            old_doc = make_doc()
            new_doc["chunks"][0]["lines"][0]["text"] = "return a * 2;"
            path.write_text(json.dumps(new_doc, ensure_ascii=False), encoding="utf-8")
            old_path.write_text(json.dumps(old_doc, ensure_ascii=False), encoding="utf-8")
            impact_state_path.write_text(
                json.dumps({"groupBriefs": {"g-pr01": {"summary": "handoff"}}}, ensure_ascii=False),
                encoding="utf-8",
            )
            state = ServerState(
                source_path=path,
                impact_old_path=old_path,
                impact_state_path=impact_state_path,
                group_selector="g-pr01",
                lock=threading.Lock(),
            )
            html = state.render_html()
            self.assertIn('id="toggle-impact-preview"', html)
            self.assertIn("Impact</h3>", html)
            self.assertIn("Group Brief Changes", html)
            self.assertIn('"impactPreviewReport":', html)
            self.assertIn("old.diffgr.json -&gt; new.diffgr.json using impact.state.json", html)

    def test_server_state_render_html_rejects_mismatched_state_and_impact_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "new.diffgr.json"
            old_path = Path(tempdir) / "old.diffgr.json"
            state_path = Path(tempdir) / "view.state.json"
            impact_state_path = Path(tempdir) / "impact.state.json"
            path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            old_path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            state_path.write_text(json.dumps({"reviews": {}}, ensure_ascii=False), encoding="utf-8")
            impact_state_path.write_text(json.dumps({"reviews": {}}, ensure_ascii=False), encoding="utf-8")
            state = ServerState(
                source_path=path,
                state_path=state_path,
                impact_old_path=old_path,
                impact_state_path=impact_state_path,
                group_selector="g-pr01",
                lock=threading.Lock(),
            )
            with self.assertRaises(RuntimeError):
                state.render_html()

    def test_server_state_save_state_writes_external_state_when_configured(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "doc.diffgr.json"
            state_path = Path(tempdir) / "state.json"
            path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            state = ServerState(
                source_path=path,
                state_path=state_path,
                group_selector="g-pr01",
                report_title=None,
                lock=threading.Lock(),
            )
            result = state.save_state(
                {
                    "reviews": {"c1": {"status": "reviewed"}},
                    "groupBriefs": {"g-pr01": {"summary": "handoff"}},
                }
            )
            self.assertEqual(result["reviewChunkCount"], 1)
            self.assertFalse("groupBriefs" in json.loads(path.read_text(encoding="utf-8")))
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_state["reviews"]["c1"]["status"], "reviewed")
            self.assertEqual(saved_state["groupBriefs"]["g-pr01"]["summary"], "handoff")


if __name__ == "__main__":
    unittest.main()
