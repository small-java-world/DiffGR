"""Virtual PR Approval — core logic for approving groups and detecting invalidation."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from diffgr.generator import canonical_json, iso_utc_now, sha256_hex
from diffgr.group_utils import safe_groups


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------

def _stable_fingerprint_input_for_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "filePath": str(chunk.get("filePath", "")),
        "lines": [
            {"kind": line.get("kind"), "text": line.get("text")}
            for line in (chunk.get("lines") or [])
        ],
    }


def _stable_fingerprint_for_chunk(chunk: dict[str, Any], *, trust_cached: bool) -> str:
    fingerprints = chunk.get("fingerprints")
    if trust_cached and isinstance(fingerprints, dict) and isinstance(fingerprints.get("stable"), str) and fingerprints["stable"]:
        return str(fingerprints["stable"])
    return sha256_hex(_stable_fingerprint_input_for_chunk(chunk))


def compute_group_approval_fingerprint(
    doc: dict[str, Any],
    group_id: str,
    *,
    trust_cached: bool = True,
) -> str:
    """SHA-256 over the sorted stable fingerprints of all chunks in the group.

    Chunk order and line-number shifts do NOT affect the result because:
    - we sort the fingerprints before hashing
    - the stable fingerprint excludes line numbers

    For approval checks we typically use ``trust_cached=False`` so stale embedded
    fingerprints cannot keep an approval alive after content changes.
    """
    chunk_map: dict[str, dict[str, Any]] = {
        c["id"]: c for c in doc.get("chunks", []) if isinstance(c, dict) and "id" in c
    }
    chunk_ids: list[str] = doc.get("assignments", {}).get(group_id, [])
    stable_fps = sorted(
        _stable_fingerprint_for_chunk(chunk_map[cid], trust_cached=trust_cached)
        for cid in chunk_ids
        if cid in chunk_map
    )
    return sha256_hex(stable_fps)


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------

@dataclass
class GroupApprovalStatus:
    group_id: str
    group_name: str
    approved: bool   # approval object exists and approved=True
    valid: bool      # fingerprint matches current chunks
    reason: str      # see constants below
    reviewed_count: int
    total_count: int


# reason constants
REASON_APPROVED = "approved"
REASON_NOT_APPROVED = "not_approved"
REASON_REVOKED = "revoked"
REASON_CHANGES_REQUESTED = "changes_requested"
REASON_INVALIDATED_FINGERPRINT = "invalidated_fingerprint"
REASON_INVALIDATED_CODE_CHANGE = "invalidated_code_change"
REASON_INVALIDATED_HEAD = "invalidated_head"
REASON_INVALIDATED_REVIEW_STATE = "invalidated_review_state"
REASON_INVALIDATED_RECORD = "invalidated_record"


@dataclass
class ApprovalReport:
    all_approved: bool
    groups: list[GroupApprovalStatus] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _approval_state(record: dict[str, Any]) -> str:
    state = str(record.get("state", "")).strip()
    if state in {"approved", "revoked", "invalidated", "changesRequested"}:
        return state
    if record.get("approved"):
        return "approved"
    reason = str(record.get("invalidationReason", "")).strip()
    if reason in {"revoked", REASON_REVOKED} or record.get("revokedAt"):
        return "revoked"
    return "invalidated"


def _approval_decision_time(record: dict[str, Any]) -> str:
    for key in ("decisionAt", "revokedAt", "invalidatedAt", "approvedAt"):
        value = str(record.get(key, "")).strip()
        if value:
            return value
    return ""


def _normalize_approval_record(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    normalized = copy.deepcopy(record)
    state = _approval_state(normalized)
    normalized["state"] = state
    normalized["approved"] = state == "approved"
    decision_at = _approval_decision_time(normalized)
    if decision_at:
        normalized["decisionAt"] = decision_at
    return normalized


def _invalidation_reason_from_record(approval: dict[str, Any]) -> str:
    state = _approval_state(approval)
    if state == "revoked":
        return REASON_REVOKED
    if state == "changesRequested":
        return REASON_CHANGES_REQUESTED
    raw = str(approval.get("invalidationReason", "")).strip()
    if raw in {"head_changed", REASON_INVALIDATED_HEAD}:
        return REASON_INVALIDATED_HEAD
    if raw in {"review_state_changed", REASON_INVALIDATED_REVIEW_STATE}:
        return REASON_INVALIDATED_REVIEW_STATE
    if raw in {"code_changed", REASON_INVALIDATED_CODE_CHANGE}:
        return REASON_INVALIDATED_CODE_CHANGE
    if raw in {"fingerprint_changed", REASON_INVALIDATED_FINGERPRINT}:
        return REASON_INVALIDATED_FINGERPRINT
    return REASON_INVALIDATED_RECORD if raw else REASON_NOT_APPROVED


# ---------------------------------------------------------------------------
# approval merge helper (used by review_state.py and review_split.py)
# ---------------------------------------------------------------------------

def merge_approval_record(
    base_approval: Any,
    incoming_approval: Any,
) -> tuple[bool, Any]:
    """Merge two approval records using decisionAt + state precedence.

    Returns (should_set, value): if should_set is True, caller should write value
    into merged["approval"]; if False, keep base as-is.

    Rules:
    - approval records are tombstones, never implicit deletes
    - newer ``decisionAt`` wins regardless of state
    - for ties: revoked(3) > changesRequested(2) = invalidated(2) > approved(1)
    - final tie-break is canonical JSON so the merge is deterministic
    """
    incoming = _normalize_approval_record(incoming_approval)
    if incoming is None:
        return False, None
    base = _normalize_approval_record(base_approval)
    if base is None:
        return True, incoming

    incoming_at = _approval_decision_time(incoming)
    base_at = _approval_decision_time(base)
    if incoming_at > base_at:
        return True, incoming
    if incoming_at < base_at:
        return False, None

    precedence = {"approved": 1, "invalidated": 2, "changesRequested": 2, "revoked": 3}
    incoming_state = _approval_state(incoming)
    base_state = _approval_state(base)
    if precedence[incoming_state] > precedence[base_state]:
        return True, incoming
    if precedence[incoming_state] < precedence[base_state]:
        return False, None

    if canonical_json(incoming) >= canonical_json(base):
        return True, incoming
    return False, None


# ---------------------------------------------------------------------------
# approve / revoke
# ---------------------------------------------------------------------------

def _current_head_sha(doc: dict[str, Any]) -> str:
    """Extract the HEAD SHA from doc.meta.source."""
    source = doc.get("meta", {}).get("source", {}) if isinstance(doc.get("meta"), dict) else {}
    return str(source.get("headSha") or source.get("head") or "").strip()


def _get_chunk_review_status(doc: dict[str, Any], chunk_id: str) -> str:
    reviews = doc.get("reviews", {})
    record = reviews.get(chunk_id)
    if isinstance(record, dict):
        return str(record.get("status", "unreviewed"))
    return "unreviewed"


def _group_name(doc: dict[str, Any], group_id: str) -> str:
    for g in doc.get("groups", []):
        if isinstance(g, dict) and g.get("id") == group_id:
            return str(g.get("name", group_id))
    return group_id


def _chunk_ids_for_group(doc: dict[str, Any], group_id: str) -> list[str]:
    return list(doc.get("assignments", {}).get(group_id, []))


def _reviewed_count(doc: dict[str, Any], group_id: str) -> tuple[int, int]:
    chunk_ids = _chunk_ids_for_group(doc, group_id)
    reviewed = sum(
        1 for cid in chunk_ids
        if _get_chunk_review_status(doc, cid) in {"reviewed", "ignored"}
    )
    return reviewed, len(chunk_ids)


def approve_group(
    doc: dict[str, Any],
    group_id: str,
    *,
    approved_by: str,
    force: bool = False,
) -> dict[str, Any]:
    """Record approval for a group.

    Raises ValueError if not all chunks are reviewed/ignored (unless ``force=True``).
    Returns the updated doc (deep-copied).
    """
    chunk_ids = _chunk_ids_for_group(doc, group_id)
    if not force:
        if not chunk_ids:
            raise ValueError(f"Group {group_id!r} has no assigned chunks.")

        unreviewed = [
            cid for cid in chunk_ids
            if _get_chunk_review_status(doc, cid) not in {"reviewed", "ignored"}
        ]
        if unreviewed:
            raise ValueError(
                f"Group {group_id!r} has {len(unreviewed)} unreviewed chunk(s): {unreviewed[:5]}"
            )

    reviewed, total = _reviewed_count(doc, group_id)

    doc = copy.deepcopy(doc)
    group_briefs: dict[str, Any] = doc.setdefault("groupBriefs", {})
    if not isinstance(group_briefs, dict):
        group_briefs = {}
        doc["groupBriefs"] = group_briefs

    brief = group_briefs.setdefault(group_id, {})
    head_sha = _current_head_sha(doc)
    now = iso_utc_now()

    brief["approval"] = {
        "state": "approved",
        "approved": True,
        "approvedAt": now,
        "approvedBy": str(approved_by).strip(),
        "approvalFingerprint": compute_group_approval_fingerprint(doc, group_id, trust_cached=False),
        "sourceHead": head_sha,
        "decisionAt": now,
        "reviewedCount": reviewed,
        "totalCount": total,
    }
    return doc


def revoke_group_approval(
    doc: dict[str, Any],
    group_id: str,
    *,
    revoked_by: str = "system",
    reason: str = REASON_REVOKED,
) -> dict[str, Any]:
    """Revoke (tombstone) the approval for a group. Returns updated doc (deep-copied)."""
    doc = copy.deepcopy(doc)
    group_briefs = doc.get("groupBriefs", {})
    if isinstance(group_briefs, dict):
        brief = group_briefs.get(group_id)
        if isinstance(brief, dict):
            now = iso_utc_now()
            prev_approval = brief.get("approval")
            tombstone = copy.deepcopy(prev_approval) if isinstance(prev_approval, dict) else {}
            tombstone.update({
                "state": "revoked",
                "approved": False,
                "revokedAt": now,
                "revokedBy": str(revoked_by).strip(),
                "decisionAt": now,
                "invalidationReason": reason,
            })
            brief["approval"] = tombstone
    return doc


def request_changes_on_group(
    doc: dict[str, Any],
    group_id: str,
    *,
    requested_by: str,
    comment: str | None = None,
) -> dict[str, Any]:
    """Record a 'changes requested' decision for a group (tombstone pattern).

    Does not require chunks to be reviewed — a reviewer can flag concerns at any time.
    Returns the updated doc (deep-copied).

    ``comment`` — explanation of what needs to change.  Pass a non-empty string to
    record a comment; pass ``None`` (default) or ``""`` to omit the field.

    Note: ``group_id`` need not be present in ``doc["groups"]``; the record is written
    regardless so that reviewers can flag concerns on any group ID.
    """
    doc = copy.deepcopy(doc)
    group_briefs: dict[str, Any] = doc.setdefault("groupBriefs", {})
    if not isinstance(group_briefs, dict):
        group_briefs = {}
        doc["groupBriefs"] = group_briefs

    brief = group_briefs.setdefault(group_id, {})
    now = iso_utc_now()

    prev_approval = brief.get("approval")
    record = copy.deepcopy(prev_approval) if isinstance(prev_approval, dict) else {}
    record.update({
        "state": "changesRequested",
        "approved": False,
        "changesRequestedAt": now,
        "changesRequestedBy": str(requested_by).strip(),
        "decisionAt": now,
    })
    # comment=None or "" means "omit" — do not carry over a previous comment
    if comment:
        record["comment"] = comment
    elif "comment" in record:
        del record["comment"]
    brief["approval"] = record
    return doc


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def check_group_approval(doc: dict[str, Any], group_id: str) -> GroupApprovalStatus:
    """Check the approval status of a single group."""
    group_briefs = doc.get("groupBriefs", {})
    brief = group_briefs.get(group_id, {}) if isinstance(group_briefs, dict) else {}
    approval = brief.get("approval") if isinstance(brief, dict) else None

    reviewed, total = _reviewed_count(doc, group_id)
    name = _group_name(doc, group_id)

    # 1. approval レコード不在
    if not isinstance(approval, dict):
        return GroupApprovalStatus(
            group_id=group_id, group_name=name,
            approved=False, valid=False, reason=REASON_NOT_APPROVED,
            reviewed_count=reviewed, total_count=total,
        )

    # 2. approved != True (tombstone / revoked / invalidated)
    if not approval.get("approved"):
        return GroupApprovalStatus(
            group_id=group_id, group_name=name,
            approved=False, valid=False, reason=_invalidation_reason_from_record(approval),
            reviewed_count=reviewed, total_count=total,
        )

    # 3. sourceHead 不一致
    saved_head = str(approval.get("sourceHead", "")).strip()
    current_head = _current_head_sha(doc)
    if saved_head and current_head and saved_head != current_head:
        return GroupApprovalStatus(
            group_id=group_id, group_name=name,
            approved=True, valid=False, reason=REASON_INVALIDATED_HEAD,
            reviewed_count=reviewed, total_count=total,
        )

    # 4. review status regression (全チャンクが reviewed/ignored でない)
    chunk_ids = _chunk_ids_for_group(doc, group_id)
    if chunk_ids and any(
        _get_chunk_review_status(doc, cid) not in {"reviewed", "ignored"}
        for cid in chunk_ids
    ):
        return GroupApprovalStatus(
            group_id=group_id, group_name=name,
            approved=True, valid=False, reason=REASON_INVALIDATED_REVIEW_STATE,
            reviewed_count=reviewed, total_count=total,
        )

    # 5. fingerprint 不一致
    saved_fp = str(approval.get("approvalFingerprint", ""))
    current_fp = compute_group_approval_fingerprint(doc, group_id, trust_cached=False)
    if saved_fp != current_fp:
        return GroupApprovalStatus(
            group_id=group_id, group_name=name,
            approved=True, valid=False, reason=REASON_INVALIDATED_FINGERPRINT,
            reviewed_count=reviewed, total_count=total,
        )

    # 6. 全チェック通過
    return GroupApprovalStatus(
        group_id=group_id, group_name=name,
        approved=True, valid=True, reason=REASON_APPROVED,
        reviewed_count=reviewed, total_count=total,
    )


def check_all_approvals(doc: dict[str, Any]) -> ApprovalReport:
    """Check approval status for all groups in the document."""
    groups = safe_groups(doc)
    statuses: list[GroupApprovalStatus] = []

    for group in groups:
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            continue
        statuses.append(check_group_approval(doc, group_id))

    all_approved = bool(statuses) and all(s.approved and s.valid for s in statuses)
    return ApprovalReport(all_approved=all_approved, groups=statuses)


def check_approvals_against_regenerated(doc: dict[str, Any], new_doc: dict[str, Any]) -> ApprovalReport:
    """Full CI check: validate that approved groups survive regeneration as intact groups.

    We do not just ask whether each old chunk found *some* match. Approval is group-scoped,
    so a regenerated group is considered equivalent only when:

    - every old chunk in the approved group matches a regenerated chunk via strong/stable/delta
    - the matched regenerated chunks all land in exactly one regenerated group
    - that regenerated group contains no extra chunks beyond the matched set

    Any split / merge / reassignment / unmatched extra chunk invalidates the affected group.
    """
    from diffgr.review_rebase import match_chunks  # local import to avoid circular

    matches, match_warnings = match_chunks(doc, new_doc)
    accepted_matches = [m for m in matches if m.kind in {"strong", "stable", "delta"}]
    old_to_new: dict[str, str] = {m.old_id: m.new_id for m in accepted_matches}
    matched_new_ids: set[str] = set(old_to_new.values())
    all_new_ids: set[str] = {
        str(chunk.get("id", "")).strip()
        for chunk in new_doc.get("chunks", [])
        if isinstance(chunk, dict) and str(chunk.get("id", "")).strip()
    }
    unmatched_new_ids = all_new_ids - matched_new_ids

    new_assignments_raw = new_doc.get("assignments", {})
    new_group_to_chunks: dict[str, set[str]] = {}
    new_chunk_to_groups: dict[str, set[str]] = {}
    if isinstance(new_assignments_raw, dict):
        for raw_group_id, raw_chunk_ids in new_assignments_raw.items():
            group_id = str(raw_group_id).strip()
            if not group_id or not isinstance(raw_chunk_ids, list):
                continue
            chunk_ids = {str(chunk_id).strip() for chunk_id in raw_chunk_ids if str(chunk_id).strip()}
            new_group_to_chunks[group_id] = chunk_ids
            for chunk_id in chunk_ids:
                new_chunk_to_groups.setdefault(chunk_id, set()).add(group_id)

    groups = safe_groups(doc)
    statuses: list[GroupApprovalStatus] = []

    for group in groups:
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            continue

        status = check_group_approval(doc, group_id)

        if status.approved and status.valid:
            chunk_ids = _chunk_ids_for_group(doc, group_id)
            unique_chunk_ids = set(chunk_ids)  # deduplicate: malformed assignments list is safe
            matched_group_chunk_ids = {old_to_new[cid] for cid in unique_chunk_ids if cid in old_to_new}
            if len(matched_group_chunk_ids) != len(unique_chunk_ids):
                status = GroupApprovalStatus(
                    group_id=group_id,
                    group_name=status.group_name,
                    approved=True,
                    valid=False,
                    reason=REASON_INVALIDATED_CODE_CHANGE,
                    reviewed_count=status.reviewed_count,
                    total_count=status.total_count,
                )
            else:
                candidate_new_group_ids: set[str] = set()
                for chunk_id in matched_group_chunk_ids:
                    candidate_new_group_ids.update(new_chunk_to_groups.get(chunk_id, set()))
                if len(candidate_new_group_ids) != 1:
                    status = GroupApprovalStatus(
                        group_id=group_id,
                        group_name=status.group_name,
                        approved=True,
                        valid=False,
                        reason=REASON_INVALIDATED_CODE_CHANGE,
                        reviewed_count=status.reviewed_count,
                        total_count=status.total_count,
                    )
                else:
                    new_group_id = next(iter(candidate_new_group_ids))
                    new_group_chunk_ids = new_group_to_chunks.get(new_group_id, set())
                    if new_group_chunk_ids != matched_group_chunk_ids:
                        status = GroupApprovalStatus(
                            group_id=group_id,
                            group_name=status.group_name,
                            approved=True,
                            valid=False,
                            reason=REASON_INVALIDATED_CODE_CHANGE,
                            reviewed_count=status.reviewed_count,
                            total_count=status.total_count,
                        )

        statuses.append(status)

    warnings = list(match_warnings)
    if unmatched_new_ids:
        warnings.append(
            f"{len(unmatched_new_ids)} regenerated chunk(s) have no strong/stable/delta match in the approved source document."
        )

    all_approved = bool(statuses) and all(s.approved and s.valid for s in statuses)
    return ApprovalReport(all_approved=all_approved, groups=statuses, warnings=warnings)


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------

def approval_report_to_json(report: ApprovalReport) -> str:
    data = {
        "allApproved": report.all_approved,
        "groups": [
            {
                "groupId": s.group_id,
                "groupName": s.group_name,
                "approved": s.approved,
                "valid": s.valid,
                "reason": s.reason,
                "reviewedCount": s.reviewed_count,
                "totalCount": s.total_count,
            }
            for s in report.groups
        ],
        "warnings": report.warnings,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)
