from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.group_brief_utils import merge_group_brief_payload, normalize_group_brief_record  # noqa: E402
from diffgr.html_report import _normalize_group_brief, _render_group_approval_summary  # noqa: E402


class TestGroupBriefUtilities(unittest.TestCase):
    def test_normalize_group_brief_record_preserves_extra_fields(self):
        brief = normalize_group_brief_record(
            {
                "status": "ready",
                "summary": "handoff",
                "focusPoints": ["fp1"],
                "approval": {"approved": True, "state": "approved"},
                "mentions": ["@alice"],
                "acknowledgedBy": [{"user": "bob"}],
                "customFlag": {"keep": True},
            }
        )
        self.assertEqual(brief["approval"]["state"], "approved")
        self.assertEqual(brief["mentions"], ["@alice"])
        self.assertEqual(brief["acknowledgedBy"][0]["user"], "bob")
        self.assertEqual(brief["customFlag"], {"keep": True})

    def test_merge_group_brief_payload_preserves_control_fields(self):
        existing = {
            "status": "ready",
            "summary": "existing summary",
            "focusPoints": ["fp1"],
            "approval": {"approved": True, "state": "approved", "approvedBy": "alice"},
            "mentions": ["@alice"],
            "acknowledgedBy": [{"user": "bob", "at": "2026-03-15T10:00:00Z"}],
            "customFlag": {"keep": True},
        }
        merged = merge_group_brief_payload(
            existing,
            {
                "status": "acknowledged",
                "summary": "updated summary",
                "focusPoints": ["fp2"],
                "testEvidence": [],
                "knownTradeoffs": [],
                "questionsForReviewer": [],
            },
            fallback_status="ready",
        )
        assert merged is not None
        self.assertEqual(merged["summary"], "updated summary")
        self.assertEqual(merged["status"], "acknowledged")
        self.assertEqual(merged["approval"]["state"], "approved")
        self.assertEqual(merged["mentions"], ["@alice"])
        self.assertEqual(merged["customFlag"], {"keep": True})

    def test_clearing_handoff_keeps_record_if_approval_exists(self):
        existing = {
            "status": "ready",
            "summary": "existing summary",
            "approval": {"approved": True, "state": "approved"},
            "mentions": ["@alice"],
        }
        merged = merge_group_brief_payload(
            existing,
            {
                "status": "draft",
                "summary": "",
                "focusPoints": [],
                "testEvidence": [],
                "knownTradeoffs": [],
                "questionsForReviewer": [],
            },
            fallback_status="ready",
        )
        assert merged is not None
        self.assertEqual(merged["approval"]["state"], "approved")
        self.assertEqual(merged["mentions"], ["@alice"])


    def test_clearing_handoff_drops_metadata_only_record(self):
        existing = {
            "status": "ready",
            "summary": "existing summary",
            "updatedAt": "2026-03-15T10:00:00Z",
            "sourceHead": "abc123",
        }
        merged = merge_group_brief_payload(
            existing,
            {
                "status": "draft",
                "summary": "",
                "focusPoints": [],
                "testEvidence": [],
                "knownTradeoffs": [],
                "questionsForReviewer": [],
            },
            fallback_status="ready",
        )
        self.assertIsNone(merged)

    def test_partial_payload_keeps_existing_handoff_fields(self):
        existing = {
            "status": "ready",
            "summary": "existing summary",
            "focusPoints": ["fp1"],
            "testEvidence": ["te1"],
            "knownTradeoffs": ["kt1"],
            "questionsForReviewer": ["q1"],
        }
        merged = merge_group_brief_payload(existing, {"summary": "updated summary"}, fallback_status="draft")
        assert merged is not None
        self.assertEqual(merged["status"], "ready")
        self.assertEqual(merged["summary"], "updated summary")
        self.assertEqual(merged["focusPoints"], ["fp1"])
        self.assertEqual(merged["testEvidence"], ["te1"])
        self.assertEqual(merged["knownTradeoffs"], ["kt1"])
        self.assertEqual(merged["questionsForReviewer"], ["q1"])

class TestHtmlGroupBriefHelpers(unittest.TestCase):
    def test_normalize_group_brief_uses_preserving_normalizer(self):
        brief = _normalize_group_brief(
            {
                "g1": {
                    "status": "ready",
                    "summary": "handoff",
                    "approval": {"approved": True, "state": "approved"},
                    "customFlag": {"keep": True},
                }
            },
            "g1",
        )
        assert brief is not None
        self.assertEqual(brief["approval"]["state"], "approved")
        self.assertEqual(brief["customFlag"], {"keep": True})

    def test_render_group_approval_summary_contains_state(self):
        html = _render_group_approval_summary(
            {
                "approval": {
                    "approved": False,
                    "state": "invalidated",
                    "approvedBy": "alice",
                    "invalidatedAt": "2026-03-15T10:00:00Z",
                    "invalidationReason": "head_changed",
                }
            }
        )
        self.assertIn("INVALIDATED", html)
        self.assertIn("head_changed", html)


if __name__ == "__main__":
    unittest.main()
