"""Unit tests for diffgr.approval and approval-related scripts."""
from __future__ import annotations

import copy
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

from diffgr.approval import (  # noqa: E402
    REASON_APPROVED,
    REASON_CHANGES_REQUESTED,
    REASON_INVALIDATED_CODE_CHANGE,
    REASON_INVALIDATED_FINGERPRINT,
    REASON_INVALIDATED_HEAD,
    REASON_INVALIDATED_REVIEW_STATE,
    REASON_NOT_APPROVED,
    REASON_REVOKED,
    approve_group,
    check_all_approvals,
    check_approvals_against_regenerated,
    check_group_approval,
    compute_group_approval_fingerprint,
    merge_approval_record,
    request_changes_on_group,
    revoke_group_approval,
)
from scripts.approve_virtual_pr import main as approve_main  # noqa: E402
from scripts.check_virtual_pr_approval import main as check_main  # noqa: E402
from scripts.request_changes import main as request_changes_main  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_chunk(chunk_id: str, file_path: str, lines: list[dict], *, stable_override: str | None = None) -> dict:
    chunk = {
        "id": chunk_id,
        "filePath": file_path,
        "old": {"start": 1, "count": len(lines)},
        "new": {"start": 1, "count": len(lines)},
        "lines": copy.deepcopy(lines),
    }
    if stable_override is not None:
        chunk["fingerprints"] = {"stable": stable_override, "strong": f"strong-{chunk_id}"}
    return chunk


def make_lines(*texts: str) -> list[dict]:
    return [{"kind": "add", "text": t} for t in texts]


def make_doc(
    *,
    chunks: list[dict] | None = None,
    groups: list[dict] | None = None,
    assignments: dict | None = None,
    reviews: dict | None = None,
    group_briefs: dict | None = None,
    head_sha: str = "abc123",
) -> dict:
    c1 = make_chunk("c1", "a.ts", make_lines("line-alpha"))
    c2 = make_chunk("c2", "b.ts", make_lines("line-beta"))
    doc: dict = {
        "format": "diffgr",
        "version": 1,
        "meta": {
            "title": "UT Approval",
            "createdAt": "2026-03-14T00:00:00Z",
            "source": {"type": "example", "headSha": head_sha},
        },
        "groups": groups or [
            {"id": "g1", "name": "Auth Module", "order": 1},
            {"id": "g2", "name": "API Layer", "order": 2},
        ],
        "chunks": chunks or [c1, c2],
        "assignments": assignments or {"g1": ["c1"], "g2": ["c2"]},
        "reviews": reviews or {},
    }
    if group_briefs is not None:
        doc["groupBriefs"] = group_briefs
    return doc


def fully_reviewed_doc() -> dict:
    return make_doc(reviews={"c1": {"status": "reviewed"}, "c2": {"status": "reviewed"}})


# ---------------------------------------------------------------------------
# fingerprint tests
# ---------------------------------------------------------------------------

class TestComputeGroupApprovalFingerprint(unittest.TestCase):
    def test_deterministic(self):
        doc = make_doc()
        fp1 = compute_group_approval_fingerprint(doc, "g1")
        fp2 = compute_group_approval_fingerprint(doc, "g1")
        self.assertEqual(fp1, fp2)

    def test_chunk_order_irrelevant(self):
        c1 = make_chunk("c1", "a.ts", make_lines("alpha"))
        c2 = make_chunk("c2", "b.ts", make_lines("beta"))
        doc_a = make_doc(
            chunks=[c1, c2],
            groups=[{"id": "g1", "name": "G", "order": 1}],
            assignments={"g1": ["c1", "c2"]},
        )
        doc_b = copy.deepcopy(doc_a)
        doc_b["assignments"]["g1"] = ["c2", "c1"]
        self.assertEqual(
            compute_group_approval_fingerprint(doc_a, "g1"),
            compute_group_approval_fingerprint(doc_b, "g1"),
        )

    def test_recomputed_fingerprint_ignores_stale_cached_stable(self):
        chunk = make_chunk("c1", "a.ts", make_lines("alpha"), stable_override="stale-cached-stable")
        doc = make_doc(chunks=[chunk], groups=[{"id": "g1", "name": "G", "order": 1}], assignments={"g1": ["c1"]})
        cached = compute_group_approval_fingerprint(doc, "g1", trust_cached=True)
        recomputed = compute_group_approval_fingerprint(doc, "g1", trust_cached=False)
        self.assertNotEqual(cached, recomputed)


# ---------------------------------------------------------------------------
# approve / revoke / merge tests
# ---------------------------------------------------------------------------

class TestApproveGroup(unittest.TestCase):
    def test_approve_fully_reviewed_group(self):
        doc = fully_reviewed_doc()
        out = approve_group(doc, "g1", approved_by="alice")
        approval = out["groupBriefs"]["g1"]["approval"]
        self.assertTrue(approval["approved"])
        self.assertEqual(approval["state"], "approved")
        self.assertEqual(approval["approvedBy"], "alice")
        self.assertEqual(approval["sourceHead"], "abc123")
        self.assertEqual(approval["reviewedCount"], 1)
        self.assertEqual(approval["totalCount"], 1)

    def test_approve_raises_if_unreviewed_chunks(self):
        doc = make_doc(reviews={"c1": {"status": "reviewed"}})
        with self.assertRaises(ValueError):
            approve_group(doc, "g2", approved_by="alice")

    def test_approve_does_not_mutate_input(self):
        doc = fully_reviewed_doc()
        original = copy.deepcopy(doc)
        approve_group(doc, "g1", approved_by="alice")
        self.assertEqual(doc, original)


# ---------------------------------------------------------------------------
# revoke_group_approval tests
# ---------------------------------------------------------------------------

class TestRevokeGroupApproval(unittest.TestCase):
    def test_revoke_writes_tombstone(self):
        doc = fully_reviewed_doc()
        approved = approve_group(doc, "g1", approved_by="alice")
        revoked = revoke_group_approval(approved, "g1", revoked_by="bob")
        approval = revoked["groupBriefs"]["g1"]["approval"]
        self.assertFalse(approval["approved"])
        self.assertEqual(approval["state"], "revoked")
        self.assertEqual(approval["revokedBy"], "bob")
        self.assertIn("revokedAt", approval)

    def test_revoke_does_not_mutate_input(self):
        doc = fully_reviewed_doc()
        approved = approve_group(doc, "g1", approved_by="alice")
        original = copy.deepcopy(approved)
        revoke_group_approval(approved, "g1")
        self.assertEqual(approved, original)


class TestMergeApprovalRecord(unittest.TestCase):
    def test_newer_revoked_beats_older_approved(self):
        base = {"state": "revoked", "approved": False, "decisionAt": "2026-03-15T10:00:00Z"}
        incoming = {"state": "approved", "approved": True, "decisionAt": "2026-03-15T09:00:00Z"}
        should_set, _ = merge_approval_record(base, incoming)
        self.assertFalse(should_set)

    def test_same_timestamp_revoked_beats_approved(self):
        base = {"state": "approved", "approved": True, "decisionAt": "2026-03-15T10:00:00Z"}
        incoming = {"state": "revoked", "approved": False, "decisionAt": "2026-03-15T10:00:00Z"}
        should_set, value = merge_approval_record(base, incoming)
        self.assertTrue(should_set)
        self.assertEqual(value["state"], "revoked")


# ---------------------------------------------------------------------------
# check_group_approval tests
# ---------------------------------------------------------------------------

class TestCheckGroupApproval(unittest.TestCase):
    def test_not_approved(self):
        doc = make_doc()
        status = check_group_approval(doc, "g1")
        self.assertFalse(status.approved)
        self.assertFalse(status.valid)
        self.assertEqual(status.reason, REASON_NOT_APPROVED)

    def test_approved_and_valid(self):
        doc = fully_reviewed_doc()
        approved = approve_group(doc, "g1", approved_by="alice")
        status = check_group_approval(approved, "g1")
        self.assertTrue(status.approved)
        self.assertTrue(status.valid)
        self.assertEqual(status.reason, REASON_APPROVED)

    def test_head_mismatch_invalidates(self):
        doc = fully_reviewed_doc()
        approved = approve_group(doc, "g1", approved_by="alice")
        approved["meta"]["source"]["headSha"] = "def456"
        status = check_group_approval(approved, "g1")
        self.assertTrue(status.approved)
        self.assertFalse(status.valid)
        self.assertEqual(status.reason, REASON_INVALIDATED_HEAD)

    def test_review_status_regression_invalidates(self):
        doc = fully_reviewed_doc()
        approved = approve_group(doc, "g1", approved_by="alice")
        approved["reviews"]["c1"]["status"] = "needsReReview"
        status = check_group_approval(approved, "g1")
        self.assertTrue(status.approved)
        self.assertFalse(status.valid)
        self.assertEqual(status.reason, REASON_INVALIDATED_REVIEW_STATE)

    def test_fingerprint_mismatch_invalidates_even_if_cached_stable_stays_same(self):
        doc = fully_reviewed_doc()
        approved = approve_group(doc, "g1", approved_by="alice")
        approved["chunks"][0]["lines"] = make_lines("changed-content")
        approved["chunks"][0]["fingerprints"] = {"stable": approved["chunks"][0].get("fingerprints", {}).get("stable", "cached")}
        status = check_group_approval(approved, "g1")
        self.assertTrue(status.approved)
        self.assertFalse(status.valid)
        self.assertEqual(status.reason, REASON_INVALIDATED_FINGERPRINT)

    def test_revoked_status_is_reported(self):
        doc = fully_reviewed_doc()
        approved = approve_group(doc, "g1", approved_by="alice")
        revoked = revoke_group_approval(approved, "g1", revoked_by="bob")
        status = check_group_approval(revoked, "g1")
        self.assertFalse(status.approved)
        self.assertFalse(status.valid)
        self.assertEqual(status.reason, REASON_REVOKED)


# ---------------------------------------------------------------------------
# check_all_approvals tests
# ---------------------------------------------------------------------------

class TestCheckAllApprovals(unittest.TestCase):
    def test_all_approved(self):
        doc = fully_reviewed_doc()
        doc = approve_group(doc, "g1", approved_by="alice")
        doc = approve_group(doc, "g2", approved_by="alice")
        report = check_all_approvals(doc)
        self.assertTrue(report.all_approved)
        self.assertEqual(len(report.groups), 2)

    def test_extra_regenerated_chunk_only_invalidates_affected_group(self):
        old = fully_reviewed_doc()
        old = approve_group(old, "g1", approved_by="alice")
        old = approve_group(old, "g2", approved_by="alice")
        new = copy.deepcopy(old)
        new["chunks"].append(make_chunk("c3", "c.ts", make_lines("line-gamma")))
        new["assignments"]["g1"].append("c3")
        report = check_approvals_against_regenerated(old, new)
        reasons = {item.group_id: item.reason for item in report.groups}
        validity = {item.group_id: item.valid for item in report.groups}
        self.assertFalse(report.all_approved)
        self.assertEqual(reasons["g1"], REASON_INVALIDATED_CODE_CHANGE)
        self.assertFalse(validity["g1"])
        self.assertEqual(reasons["g2"], REASON_APPROVED)
        self.assertTrue(validity["g2"])
        self.assertTrue(report.warnings)

    def test_group_reassignment_invalidates_affected_group(self):
        old = fully_reviewed_doc()
        old = approve_group(old, "g1", approved_by="alice")
        old = approve_group(old, "g2", approved_by="alice")
        new = copy.deepcopy(old)
        new["assignments"] = {"g1": [], "g2": ["c1", "c2"]}
        report = check_approvals_against_regenerated(old, new)
        reasons = {item.group_id: item.reason for item in report.groups}
        validity = {item.group_id: item.valid for item in report.groups}
        self.assertEqual(reasons["g1"], REASON_INVALIDATED_CODE_CHANGE)
        self.assertFalse(validity["g1"])
        self.assertEqual(reasons["g2"], REASON_INVALIDATED_CODE_CHANGE)
        self.assertFalse(validity["g2"])


# ---------------------------------------------------------------------------
# CI script tests
# ---------------------------------------------------------------------------

class TestCheckVirtualPrApprovalScript(unittest.TestCase):
    def _write_doc(self, tmpdir: str, doc: dict) -> Path:
        path = Path(tmpdir) / "doc.diffgr.json"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return path

    def test_all_approved_returns_zero(self):
        doc = fully_reviewed_doc()
        doc = approve_group(doc, "g1", approved_by="alice")
        doc = approve_group(doc, "g2", approved_by="alice")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = check_main(["--input", str(path)])
        self.assertEqual(code, 0)

    def test_not_all_approved_returns_two(self):
        doc = fully_reviewed_doc()
        doc = approve_group(doc, "g1", approved_by="alice")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = check_main(["--input", str(path)])
        self.assertEqual(code, 2)

    def test_partial_full_check_args_return_one(self):
        doc = fully_reviewed_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = check_main(["--input", str(path), "--repo", "/tmp/repo-only"])
        self.assertEqual(code, 1)

    def test_bad_input_returns_one(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = check_main(["--input", "/nonexistent/path.json"])
        self.assertEqual(code, 1)


class TestApproveVirtualPrScript(unittest.TestCase):
    def _write_doc(self, tmpdir: str, doc: dict) -> Path:
        path = Path(tmpdir) / "doc.diffgr.json"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return path

    def test_approve_specific_group(self):
        doc = fully_reviewed_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            out_path = Path(tmpdir) / "out.diffgr.json"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = approve_main([
                    "--input", str(path),
                    "--output", str(out_path),
                    "--group", "g1",
                    "--approved-by", "alice",
                ])
            self.assertEqual(code, 0)
            out = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(out["groupBriefs"]["g1"]["approval"]["approved"])
            self.assertNotIn("g2", out.get("groupBriefs", {}))

    def test_approve_all_groups(self):
        doc = fully_reviewed_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            out_path = Path(tmpdir) / "out.diffgr.json"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = approve_main([
                    "--input", str(path),
                    "--output", str(out_path),
                    "--all",
                    "--approved-by", "alice",
                ])
            self.assertEqual(code, 0)
            out = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(out["groupBriefs"]["g1"]["approval"]["approved"])
            self.assertTrue(out["groupBriefs"]["g2"]["approval"]["approved"])

    def test_unreviewed_chunk_returns_one(self):
        doc = make_doc(reviews={})
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = approve_main([
                    "--input", str(path),
                    "--group", "g1",
                    "--approved-by", "alice",
                ])
        self.assertEqual(code, 1)

    def test_no_group_flag_returns_one(self):
        doc = fully_reviewed_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = approve_main(["--input", str(path), "--approved-by", "alice"])
        self.assertEqual(code, 1)


# ---------------------------------------------------------------------------
# request_changes_on_group tests
# ---------------------------------------------------------------------------

class TestRequestChangesOnGroup(unittest.TestCase):
    def test_request_changes_writes_record(self):
        doc = make_doc()
        out = request_changes_on_group(doc, "g1", requested_by="alice")
        approval = out["groupBriefs"]["g1"]["approval"]
        self.assertFalse(approval["approved"])
        self.assertEqual(approval["state"], "changesRequested")
        self.assertEqual(approval["changesRequestedBy"], "alice")
        self.assertIn("changesRequestedAt", approval)
        self.assertIn("decisionAt", approval)

    def test_request_changes_with_comment(self):
        doc = make_doc()
        out = request_changes_on_group(doc, "g1", requested_by="alice", comment="Please fix auth logic.")
        approval = out["groupBriefs"]["g1"]["approval"]
        self.assertEqual(approval["comment"], "Please fix auth logic.")

    def test_request_changes_no_comment_omits_field(self):
        doc = make_doc()
        out = request_changes_on_group(doc, "g1", requested_by="alice")
        self.assertNotIn("comment", out["groupBriefs"]["g1"]["approval"])

    def test_request_changes_does_not_mutate_input(self):
        doc = make_doc()
        original = copy.deepcopy(doc)
        request_changes_on_group(doc, "g1", requested_by="alice")
        self.assertEqual(doc, original)

    def test_request_changes_check_returns_reason(self):
        doc = make_doc()
        out = request_changes_on_group(doc, "g1", requested_by="alice")
        status = check_group_approval(out, "g1")
        self.assertFalse(status.approved)
        self.assertFalse(status.valid)
        self.assertEqual(status.reason, REASON_CHANGES_REQUESTED)

    def test_merge_changes_requested_beats_approved(self):
        ts = "2026-03-15T12:00:00Z"
        base = {"state": "approved", "approved": True, "decisionAt": ts}
        incoming = {"state": "changesRequested", "approved": False, "decisionAt": ts}
        should_set, value = merge_approval_record(base, incoming)
        self.assertTrue(should_set)
        self.assertEqual(value["state"], "changesRequested")

    def test_merge_revoked_beats_changes_requested(self):
        ts = "2026-03-15T12:00:00Z"
        base = {"state": "revoked", "approved": False, "decisionAt": ts}
        incoming = {"state": "changesRequested", "approved": False, "decisionAt": ts}
        should_set, _ = merge_approval_record(base, incoming)
        self.assertFalse(should_set)

    def test_all_approvals_false_when_changes_requested(self):
        doc = fully_reviewed_doc()
        doc = approve_group(doc, "g2", approved_by="alice")
        doc = request_changes_on_group(doc, "g1", requested_by="bob", comment="Needs review.")
        report = check_all_approvals(doc)
        self.assertFalse(report.all_approved)
        reasons = {s.group_id: s.reason for s in report.groups}
        self.assertEqual(reasons["g1"], REASON_CHANGES_REQUESTED)

    def test_re_approve_after_changes_requested(self):
        """approve_group() after request_changes_on_group() produces a clean approved record."""
        doc = fully_reviewed_doc()
        doc = request_changes_on_group(doc, "g1", requested_by="bob", comment="Fix this.")
        doc = approve_group(doc, "g1", approved_by="alice")
        approval = doc["groupBriefs"]["g1"]["approval"]
        self.assertTrue(approval["approved"])
        self.assertEqual(approval["state"], "approved")
        # approve_group writes a fresh record — stale changesRequested fields must be gone
        self.assertNotIn("changesRequestedAt", approval)
        self.assertNotIn("changesRequestedBy", approval)
        self.assertNotIn("comment", approval)

    def test_merge_changes_requested_vs_invalidated_deterministic(self):
        """Same-timestamp changesRequested vs invalidated resolves via canonical JSON (deterministic)."""
        ts = "2026-03-15T12:00:00Z"
        a = {"state": "changesRequested", "approved": False, "decisionAt": ts}
        b = {"state": "invalidated", "approved": False, "decisionAt": ts}
        should_set_ab, val_ab = merge_approval_record(a, b)
        should_set_ba, val_ba = merge_approval_record(b, a)
        # Exactly one of them should win, and the result must be consistent
        winner = val_ab["state"] if should_set_ab else a["state"]
        loser_result = val_ba["state"] if should_set_ba else b["state"]
        self.assertEqual(winner, loser_result)

    def test_comment_none_clears_previous_comment(self):
        """comment=None (default) omits comment even if the previous record had one."""
        doc = make_doc()
        doc = request_changes_on_group(doc, "g1", requested_by="alice", comment="First concern.")
        doc = request_changes_on_group(doc, "g1", requested_by="alice")  # no comment
        self.assertNotIn("comment", doc["groupBriefs"]["g1"]["approval"])


# ---------------------------------------------------------------------------
# request_changes script tests
# ---------------------------------------------------------------------------

class TestRequestChangesScript(unittest.TestCase):
    def _write_doc(self, tmpdir: str, doc: dict) -> Path:
        path = Path(tmpdir) / "doc.diffgr.json"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return path

    def test_request_changes_specific_group(self):
        doc = make_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            out_path = Path(tmpdir) / "out.diffgr.json"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = request_changes_main([
                    "--input", str(path),
                    "--output", str(out_path),
                    "--group", "g1",
                    "--requested-by", "alice",
                    "--comment", "Fix auth.",
                ])
            self.assertEqual(code, 0)
            out = json.loads(out_path.read_text(encoding="utf-8"))
            approval = out["groupBriefs"]["g1"]["approval"]
            self.assertEqual(approval["state"], "changesRequested")
            self.assertEqual(approval["comment"], "Fix auth.")

    def test_request_changes_all_groups(self):
        doc = make_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            out_path = Path(tmpdir) / "out.diffgr.json"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = request_changes_main([
                    "--input", str(path),
                    "--output", str(out_path),
                    "--all",
                    "--requested-by", "alice",
                ])
            self.assertEqual(code, 0)
            out = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(out["groupBriefs"]["g1"]["approval"]["state"], "changesRequested")
            self.assertEqual(out["groupBriefs"]["g2"]["approval"]["state"], "changesRequested")

    def test_comment_omitted_does_not_set_field(self):
        """--comment not specified should not write a comment field to the record."""
        doc = make_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            out_path = Path(tmpdir) / "out.diffgr.json"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = request_changes_main([
                    "--input", str(path),
                    "--output", str(out_path),
                    "--group", "g1",
                    "--requested-by", "alice",
                ])
            self.assertEqual(code, 0)
            out = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertNotIn("comment", out["groupBriefs"]["g1"]["approval"])

    def test_no_group_flag_returns_one(self):
        doc = make_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_doc(tmpdir, doc)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = request_changes_main(["--input", str(path), "--requested-by", "alice"])
        self.assertEqual(code, 1)

    def test_bad_input_returns_one(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = request_changes_main([
                "--input", "/nonexistent/path.json",
                "--group", "g1",
                "--requested-by", "alice",
            ])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
