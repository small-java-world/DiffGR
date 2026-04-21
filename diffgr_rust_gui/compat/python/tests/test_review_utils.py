"""Tests for diffgr.review_utils."""

from __future__ import annotations

import pytest

from diffgr.review_utils import (
    REVIEW_STATUS_PRECEDENCE,
    VALID_REVIEW_STATUSES,
    line_comment_identity,
    merge_review_records,
    normalize_comment,
    normalize_review_status,
    normalized_line_comments,
)


class TestNormalizeReviewStatus:
    def test_valid_statuses(self):
        for status in ("unreviewed", "reviewed", "ignored", "needsReReview"):
            assert normalize_review_status(status) == status

    def test_invalid_non_strict_returns_none(self):
        assert normalize_review_status("bogus") is None
        assert normalize_review_status("") is None
        assert normalize_review_status(None) is None

    def test_invalid_strict_returns_unreviewed(self):
        assert normalize_review_status("bogus", strict=True) == "unreviewed"
        assert normalize_review_status("", strict=True) == "unreviewed"
        assert normalize_review_status(None, strict=True) == "unreviewed"

    def test_whitespace_trimmed(self):
        assert normalize_review_status("  reviewed  ") == "reviewed"
        assert normalize_review_status("  bad  ") is None
        assert normalize_review_status("  bad  ", strict=True) == "unreviewed"


class TestNormalizeComment:
    def test_normal(self):
        assert normalize_comment("hello") == "hello"

    def test_strips_whitespace(self):
        assert normalize_comment("  hi  ") == "hi"

    def test_empty_values(self):
        assert normalize_comment("") == ""
        assert normalize_comment(None) == ""
        assert normalize_comment(0) == ""


class TestNormalizedLineComments:
    def test_normal(self):
        record = {
            "lineComments": [
                {"oldLine": 1, "newLine": 2, "lineType": "add", "comment": "good"},
            ]
        }
        result = normalized_line_comments(record)
        assert len(result) == 1
        assert result[0]["comment"] == "good"

    def test_empty_list(self):
        assert normalized_line_comments({"lineComments": []}) == []

    def test_missing_key(self):
        assert normalized_line_comments({}) == []

    def test_non_dict_items_skipped(self):
        record = {"lineComments": ["not-a-dict", {"comment": "ok"}]}
        result = normalized_line_comments(record)
        assert len(result) == 1

    def test_empty_comment_skipped(self):
        record = {"lineComments": [{"comment": ""}, {"comment": "  "}, {"comment": "keep"}]}
        result = normalized_line_comments(record)
        assert len(result) == 1
        assert result[0]["comment"] == "keep"


class TestLineCommentIdentity:
    def test_same_items_same_identity(self):
        a = {"oldLine": 1, "newLine": 2, "lineType": "add", "comment": "hello"}
        b = {"oldLine": 1, "newLine": 2, "lineType": "add", "comment": "hello"}
        assert line_comment_identity(a) == line_comment_identity(b)

    def test_different_comment_different_identity(self):
        a = {"oldLine": 1, "newLine": 2, "lineType": "add", "comment": "hello"}
        b = {"oldLine": 1, "newLine": 2, "lineType": "add", "comment": "world"}
        assert line_comment_identity(a) != line_comment_identity(b)

    def test_extra_keys_ignored(self):
        a = {"oldLine": 1, "newLine": 2, "lineType": "add", "comment": "x", "extra": True}
        b = {"oldLine": 1, "newLine": 2, "lineType": "add", "comment": "x"}
        assert line_comment_identity(a) == line_comment_identity(b)


class TestMergeReviewRecords:
    def test_incoming_higher_precedence_wins(self):
        warnings: list[str] = []
        result = merge_review_records(
            {"status": "reviewed"},
            {"status": "needsReReview"},
            source_name="s", chunk_id="c1", warnings=warnings,
        )
        assert result["status"] == "needsReReview"
        assert warnings == []

    def test_base_higher_precedence_kept_with_warning(self):
        warnings: list[str] = []
        result = merge_review_records(
            {"status": "needsReReview"},
            {"status": "reviewed"},
            source_name="s", chunk_id="c1", warnings=warnings,
        )
        assert result["status"] == "needsReReview"
        assert len(warnings) == 1
        assert "status conflict" in warnings[0]

    def test_comment_conflict_warning(self):
        warnings: list[str] = []
        result = merge_review_records(
            {"status": "reviewed", "comment": "old"},
            {"status": "reviewed", "comment": "new"},
            source_name="s", chunk_id="c1", warnings=warnings,
        )
        assert result["comment"] == "new"
        assert any("chunk comment conflict" in w for w in warnings)

    def test_line_comments_dedup(self):
        lc = {"oldLine": 1, "newLine": 2, "lineType": "add", "comment": "dup"}
        warnings: list[str] = []
        result = merge_review_records(
            {"status": "reviewed", "lineComments": [lc]},
            {"status": "reviewed", "lineComments": [lc]},
            source_name="s", chunk_id="c1", warnings=warnings,
        )
        assert len(result["lineComments"]) == 1

    def test_extra_keys_carried(self):
        warnings: list[str] = []
        result = merge_review_records(
            {"status": "reviewed"},
            {"status": "reviewed", "customField": 42},
            source_name="s", chunk_id="c1", warnings=warnings,
        )
        assert result["customField"] == 42


class TestConstants:
    def test_valid_review_statuses_matches_precedence(self):
        assert VALID_REVIEW_STATUSES == set(REVIEW_STATUS_PRECEDENCE.keys())

    def test_precedence_values(self):
        assert REVIEW_STATUS_PRECEDENCE["ignored"] < REVIEW_STATUS_PRECEDENCE["reviewed"]
        assert REVIEW_STATUS_PRECEDENCE["reviewed"] < REVIEW_STATUS_PRECEDENCE["unreviewed"]
        assert REVIEW_STATUS_PRECEDENCE["unreviewed"] < REVIEW_STATUS_PRECEDENCE["needsReReview"]
