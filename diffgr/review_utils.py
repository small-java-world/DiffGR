"""Shared review-record utilities.

Centralises constants, normalisation helpers, and the merge algorithm that
were previously duplicated across review_state.py, review_split.py,
review_rebase.py and html_report.py.
"""

from __future__ import annotations

import copy
from typing import Any

from diffgr.generator import canonical_json

REVIEW_STATUS_PRECEDENCE: dict[str, int] = {
    "ignored": 1,
    "reviewed": 2,
    "unreviewed": 3,
    "needsReReview": 4,
}

VALID_REVIEW_STATUSES: set[str] = set(REVIEW_STATUS_PRECEDENCE.keys())


def normalize_review_status(value: Any, *, strict: bool = False) -> str | None:
    """Normalise a review status string.

    * ``strict=False`` (default): returns ``None`` when *value* is not a
      recognised status (compatible with review_state / review_split).
    * ``strict=True``: returns ``"unreviewed"`` for unrecognised values
      (compatible with review_rebase).
    """
    status = str(value or "").strip()
    if status in REVIEW_STATUS_PRECEDENCE:
        return status
    return "unreviewed" if strict else None


def normalize_comment(value: Any) -> str:
    return str(value or "").strip()


def normalized_line_comments(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw = record.get("lineComments")
    if not isinstance(raw, list):
        return []
    kept: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        comment = normalize_comment(item.get("comment"))
        if not comment:
            continue
        line_comment = copy.deepcopy(item)
        line_comment["comment"] = comment
        kept.append(line_comment)
    return kept


def line_comment_identity(item: dict[str, Any]) -> str:
    normalized = {
        "oldLine": item.get("oldLine"),
        "newLine": item.get("newLine"),
        "lineType": str(item.get("lineType", "")),
        "comment": normalize_comment(item.get("comment")),
    }
    return canonical_json(normalized)


def merge_review_records(
    base_record: dict[str, Any],
    incoming_record: dict[str, Any],
    *,
    source_name: str,
    chunk_id: str,
    warnings: list[str],
) -> dict[str, Any]:
    merged = copy.deepcopy(base_record)

    base_status = normalize_review_status(base_record.get("status"))
    incoming_status = normalize_review_status(incoming_record.get("status"))
    if incoming_status is not None:
        if base_status is None or REVIEW_STATUS_PRECEDENCE[incoming_status] >= REVIEW_STATUS_PRECEDENCE[base_status]:
            merged["status"] = incoming_status
        elif base_status != incoming_status:
            warnings.append(
                f"{source_name}: status conflict on chunk {chunk_id}; kept {base_status}, ignored {incoming_status}"
            )

    base_comment = normalize_comment(base_record.get("comment"))
    incoming_comment = normalize_comment(incoming_record.get("comment"))
    if incoming_comment:
        if base_comment and base_comment != incoming_comment:
            warnings.append(f"{source_name}: chunk comment conflict on chunk {chunk_id}; used incoming comment.")
        merged["comment"] = incoming_comment
    elif base_comment:
        merged["comment"] = base_comment
    else:
        merged.pop("comment", None)

    combined_line_comments: list[dict[str, Any]] = []
    seen_line_comments: set[str] = set()
    for item in normalized_line_comments(base_record) + normalized_line_comments(incoming_record):
        identity = line_comment_identity(item)
        if identity in seen_line_comments:
            continue
        seen_line_comments.add(identity)
        combined_line_comments.append(item)
    if combined_line_comments:
        merged["lineComments"] = combined_line_comments
    else:
        merged.pop("lineComments", None)

    for key, value in incoming_record.items():
        if key in {"status", "comment", "lineComments"}:
            continue
        merged[key] = copy.deepcopy(value)
    return merged
