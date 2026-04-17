import unittest

from diffgr.group_brief_utils import (
    GROUP_BRIEF_LIST_FIELDS,
    GROUP_BRIEF_SINGLE_FIELDS,
    GROUP_BRIEF_STATUS_PRECEDENCE,
    VALID_GROUP_BRIEF_STATUSES,
    merge_group_brief_records,
    normalize_group_brief_status,
    summarize_group_brief_record,
)


class TestNormalizeGroupBriefStatus(unittest.TestCase):
    def test_valid_statuses(self):
        for status in ("draft", "acknowledged", "ready", "stale"):
            self.assertEqual(normalize_group_brief_status(status), status)
            self.assertEqual(normalize_group_brief_status(status, strict=True), status)

    def test_invalid_non_strict_returns_none(self):
        self.assertIsNone(normalize_group_brief_status("invalid"))
        self.assertIsNone(normalize_group_brief_status(""))
        self.assertIsNone(normalize_group_brief_status(None))

    def test_invalid_strict_returns_draft(self):
        self.assertEqual(normalize_group_brief_status("invalid", strict=True), "draft")
        self.assertEqual(normalize_group_brief_status("", strict=True), "draft")
        self.assertEqual(normalize_group_brief_status(None, strict=True), "draft")

    def test_whitespace_stripped(self):
        self.assertEqual(normalize_group_brief_status("  ready  "), "ready")


class TestMergeGroupBriefRecords(unittest.TestCase):
    def test_status_precedence_higher_wins(self):
        warnings: list[str] = []
        result = merge_group_brief_records(
            {"status": "draft"},
            {"status": "stale"},
            source_name="s", group_id="g1", warnings=warnings,
        )
        self.assertEqual(result["status"], "stale")
        self.assertEqual(warnings, [])

    def test_status_precedence_lower_keeps_base(self):
        warnings: list[str] = []
        result = merge_group_brief_records(
            {"status": "stale"},
            {"status": "draft"},
            source_name="s", group_id="g1", warnings=warnings,
        )
        self.assertEqual(result["status"], "stale")

    def test_list_dedup(self):
        warnings: list[str] = []
        result = merge_group_brief_records(
            {"focusPoints": ["a", "b"]},
            {"focusPoints": ["b", "c"]},
            source_name="s", group_id="g1", warnings=warnings,
        )
        self.assertEqual(result["focusPoints"], ["a", "b", "c"])

    def test_summary_conflict_warning(self):
        warnings: list[str] = []
        result = merge_group_brief_records(
            {"summary": "old"},
            {"summary": "new"},
            source_name="src", group_id="g1", warnings=warnings,
        )
        self.assertEqual(result["summary"], "new")
        self.assertEqual(len(warnings), 1)
        self.assertIn("group brief conflict", warnings[0])

    def test_acknowledged_by_merge(self):
        warnings: list[str] = []
        result = merge_group_brief_records(
            {"acknowledgedBy": [{"user": "alice"}]},
            {"acknowledgedBy": [{"user": "alice"}, {"user": "bob"}]},
            source_name="s", group_id="g1", warnings=warnings,
        )
        self.assertEqual(len(result["acknowledgedBy"]), 2)

    def test_approval_merge(self):
        warnings: list[str] = []
        result = merge_group_brief_records(
            {"approval": {"state": "approved", "approved": True, "decisionAt": "2025-01-01T00:00:00Z"}},
            {"approval": {"state": "approved", "approved": True, "decisionAt": "2025-01-02T00:00:00Z"}},
            source_name="s", group_id="g1", warnings=warnings,
        )
        self.assertIn("approval", result)

    def test_extra_keys_carried(self):
        warnings: list[str] = []
        result = merge_group_brief_records(
            {},
            {"customField": "hello"},
            source_name="s", group_id="g1", warnings=warnings,
        )
        self.assertEqual(result["customField"], "hello")


class TestSummarizeGroupBriefRecord(unittest.TestCase):
    def test_non_dict_returns_zeros(self):
        result = summarize_group_brief_record(None)
        self.assertEqual(result["status"], "")
        self.assertEqual(result["focusPointsCount"], 0)

    def test_counts_correct(self):
        record = {
            "status": "ready",
            "summary": "test summary",
            "focusPoints": ["a", "b"],
            "testEvidence": ["e1"],
            "questionsForReviewer": ["q1", "q2", "q3"],
            "mentions": [],
            "acknowledgedBy": [{"user": "alice"}],
        }
        result = summarize_group_brief_record(record)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["summary"], "test summary")
        self.assertEqual(result["focusPointsCount"], 2)
        self.assertEqual(result["testEvidenceCount"], 1)
        self.assertEqual(result["questionsCount"], 3)
        self.assertEqual(result["mentionsCount"], 0)
        self.assertEqual(result["acknowledgedByCount"], 1)


class TestConstants(unittest.TestCase):
    def test_valid_statuses_matches_precedence_keys(self):
        self.assertEqual(VALID_GROUP_BRIEF_STATUSES, set(GROUP_BRIEF_STATUS_PRECEDENCE.keys()))

    def test_field_sets_non_empty(self):
        self.assertTrue(len(GROUP_BRIEF_LIST_FIELDS) > 0)
        self.assertTrue(len(GROUP_BRIEF_SINGLE_FIELDS) > 0)


if __name__ == "__main__":
    unittest.main()
