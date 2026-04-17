from __future__ import annotations

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

from diffgr.approval import approve_group  # noqa: E402
from diffgr.review_bundle import (  # noqa: E402
    build_review_bundle_manifest,
    compose_document_from_bundle,
    split_document_into_bundle,
    verify_review_bundle_artifacts,
)
from scripts.export_review_bundle import main as export_bundle_main  # noqa: E402
from scripts.verify_review_bundle import main as verify_bundle_main  # noqa: E402


class TestReviewBundle(unittest.TestCase):
    def _make_doc(self) -> dict:
        doc = {
            "format": "diffgr",
            "version": 1,
            "meta": {
                "title": "UT Bundle",
                "createdAt": "2026-03-15T00:00:00Z",
                "source": {"type": "example", "headSha": "abc123"},
            },
            "groups": [{"id": "g1", "name": "Auth", "order": 1}],
            "chunks": [
                {
                    "id": "c1",
                    "filePath": "src/a.ts",
                    "old": {"start": 1, "count": 1},
                    "new": {"start": 1, "count": 1},
                    "lines": [{"kind": "add", "text": "return 1;"}],
                }
            ],
            "assignments": {"g1": ["c1"]},
            "reviews": {"c1": {"status": "reviewed", "comment": "ok"}},
            "groupBriefs": {"g1": {"status": "ready", "summary": "handoff"}},
            "analysisState": {"currentGroupId": "g1", "selectedChunkId": "c1"},
            "threadState": {"selectedLineAnchor": {"anchorKey": "add::1"}},
        }
        return approve_group(doc, "g1", approved_by="alice")

    def test_split_and_compose_roundtrip(self):
        doc = self._make_doc()
        bundle_doc, state = split_document_into_bundle(doc)
        self.assertEqual(bundle_doc["reviews"], {})
        self.assertNotIn("groupBriefs", bundle_doc)
        recomposed = compose_document_from_bundle(bundle_doc, state)
        self.assertEqual(recomposed, doc)

    def test_manifest_and_verify_success(self):
        doc = self._make_doc()
        bundle_doc, state = split_document_into_bundle(doc)
        manifest = build_review_bundle_manifest(bundle_doc, state)
        result = verify_review_bundle_artifacts(bundle_doc, state, manifest, expected_head="abc123", require_approvals=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["computedManifest"]["bundleDigest"], manifest["bundleDigest"])
        self.assertIsInstance(result["approvalReport"], dict)
        self.assertTrue(result["approvalReport"]["allApproved"])

    def test_verify_fails_on_expected_head_mismatch(self):
        doc = self._make_doc()
        bundle_doc, state = split_document_into_bundle(doc)
        manifest = build_review_bundle_manifest(bundle_doc, state)
        result = verify_review_bundle_artifacts(bundle_doc, state, manifest, expected_head="different-head")
        self.assertFalse(result["ok"])
        self.assertIn("Expected head different-head", result["errors"][0])

    def test_verify_fails_when_bundle_contains_mutable_state(self):
        doc = self._make_doc()
        bundle_doc, state = split_document_into_bundle(doc)
        bundle_doc["groupBriefs"] = {"g1": {"status": "ready"}}
        manifest = build_review_bundle_manifest(bundle_doc, state)
        result = verify_review_bundle_artifacts(bundle_doc, state, manifest)
        self.assertFalse(result["ok"])
        self.assertTrue(any("mutable state key" in item for item in result["errors"]))

    def test_verify_warns_when_state_references_unknown_group(self):
        doc = self._make_doc()
        bundle_doc, state = split_document_into_bundle(doc)
        state["groupBriefs"]["missing-group"] = {"status": "ready", "summary": "stale"}
        manifest = build_review_bundle_manifest(bundle_doc, split_document_into_bundle(doc)[1])
        result = verify_review_bundle_artifacts(bundle_doc, state, manifest)
        # Topology mismatch is a warning; manifest stateDigest mismatch is what makes ok=False
        self.assertFalse(result["ok"])
        self.assertTrue(any("groupBrief key not found" in item for item in result["warnings"]))

    def test_verify_warns_when_analysis_state_points_to_missing_chunk(self):
        doc = self._make_doc()
        bundle_doc, state = split_document_into_bundle(doc)
        state["analysisState"]["selectedChunkId"] = "missing-chunk"
        manifest = build_review_bundle_manifest(bundle_doc, split_document_into_bundle(doc)[1])
        result = verify_review_bundle_artifacts(bundle_doc, state, manifest)
        self.assertFalse(result["ok"])  # state digest mismatch against original manifest
        self.assertTrue(any("analysisState.selectedChunkId" in item for item in result["warnings"]))

    def test_export_and_verify_scripts(self):
        doc = self._make_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_path = tmp / "review.diffgr.json"
            bundle_path = tmp / "bundle.diffgr.json"
            state_path = tmp / "review.state.json"
            manifest_path = tmp / "review.manifest.json"
            input_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                export_code = export_bundle_main([
                    "--input", str(input_path),
                    "--bundle-out", str(bundle_path),
                    "--state-out", str(state_path),
                    "--manifest-out", str(manifest_path),
                ])
            self.assertEqual(export_code, 0)
            self.assertTrue(bundle_path.exists())
            self.assertTrue(state_path.exists())
            self.assertTrue(manifest_path.exists())

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                verify_code = verify_bundle_main([
                    "--bundle", str(bundle_path),
                    "--state", str(state_path),
                    "--manifest", str(manifest_path),
                    "--expected-head", "abc123",
                    "--require-approvals",
                ])
            self.assertEqual(verify_code, 0)

    def test_verify_script_returns_two_when_state_tampered(self):
        doc = self._make_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_path = tmp / "review.diffgr.json"
            bundle_path = tmp / "bundle.diffgr.json"
            state_path = tmp / "review.state.json"
            manifest_path = tmp / "review.manifest.json"
            input_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                export_code = export_bundle_main([
                    "--input", str(input_path),
                    "--bundle-out", str(bundle_path),
                    "--state-out", str(state_path),
                    "--manifest-out", str(manifest_path),
                ])
            self.assertEqual(export_code, 0)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["reviews"]["c1"]["status"] = "needsReReview"
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                verify_code = verify_bundle_main([
                    "--bundle", str(bundle_path),
                    "--state", str(state_path),
                    "--manifest", str(manifest_path),
                ])
            self.assertEqual(verify_code, 2)


if __name__ == "__main__":
    unittest.main()
