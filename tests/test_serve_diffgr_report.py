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
    _normalize_reviews_payload,
    save_reviews_to_document,
)


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
    def test_normalize_reviews_payload_accepts_wrapped_and_direct(self):
        direct = _normalize_reviews_payload({"c1": {"comment": "ok"}})
        wrapped = _normalize_reviews_payload({"reviews": {"c1": {"comment": "ok"}}})
        self.assertEqual(direct["c1"]["comment"], "ok")
        self.assertEqual(wrapped["c1"]["comment"], "ok")

    def test_normalize_reviews_payload_rejects_invalid_shape(self):
        with self.assertRaises(RuntimeError):
            _normalize_reviews_payload("bad")
        with self.assertRaises(RuntimeError):
            _normalize_reviews_payload({"reviews": []})

    def test_save_reviews_to_document_updates_reviews(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "doc.diffgr.json"
            path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            result = save_reviews_to_document(path, {"c1": {"comment": "line by line"}})
            self.assertEqual(result["reviewChunkCount"], 1)
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["reviews"]["c1"]["comment"], "line by line")
            self.assertEqual(updated["chunks"][0]["id"], "c1")

    def test_server_state_render_html_embeds_save_endpoint(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "doc.diffgr.json"
            path.write_text(json.dumps(make_doc(), ensure_ascii=False), encoding="utf-8")
            state = ServerState(
                source_path=path,
                group_selector="g-pr01",
                report_title=None,
                lock=threading.Lock(),
            )
            html = state.render_html()
            self.assertIn('"saveReviewsUrl": "/api/reviews"', html)
            self.assertIn('id="save-reviews"', html)


if __name__ == "__main__":
    unittest.main()
