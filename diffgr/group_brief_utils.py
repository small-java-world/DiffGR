from __future__ import annotations

import copy
from typing import Any

from diffgr.generator import canonical_json

GROUP_BRIEF_STATUS_PRECEDENCE: dict[str, int] = {
    "draft": 1,
    "acknowledged": 2,
    "ready": 3,
    "stale": 4,
}

VALID_GROUP_BRIEF_STATUSES: set[str] = set(GROUP_BRIEF_STATUS_PRECEDENCE.keys())

# Primary handoff list fields shown in the editor UI.
CORE_LIST_KEYS: tuple[str, ...] = ("focusPoints", "testEvidence", "knownTradeoffs", "questionsForReviewer")

# Additional metadata fields carried with the record but not treated as content.
GROUP_BRIEF_METADATA_FIELDS: tuple[str, ...] = ("updatedAt", "sourceHead")

GROUP_BRIEF_LIST_FIELDS: set[str] = {
    "focusPoints",
    "testEvidence",
    "knownTradeoffs",
    "questionsForReviewer",
    "mentions",
}

GROUP_BRIEF_SINGLE_FIELDS: set[str] = {
    "summary",
    *GROUP_BRIEF_METADATA_FIELDS,
}


def normalize_group_brief_status(value: Any, *, strict: bool = False) -> str | None:
    status = str(value or "").strip()
    if status in GROUP_BRIEF_STATUS_PRECEDENCE:
        return status
    return "draft" if strict else None


def merge_group_brief_records(
    base_record: dict[str, Any],
    incoming_record: dict[str, Any],
    *,
    source_name: str,
    group_id: str,
    warnings: list[str],
) -> dict[str, Any]:
    merged = copy.deepcopy(base_record)

    base_status = normalize_group_brief_status(base_record.get("status"))
    incoming_status = normalize_group_brief_status(incoming_record.get("status"))
    if incoming_status is not None:
        if base_status is None or GROUP_BRIEF_STATUS_PRECEDENCE[incoming_status] >= GROUP_BRIEF_STATUS_PRECEDENCE[base_status]:
            merged["status"] = incoming_status

    for key in GROUP_BRIEF_SINGLE_FIELDS:
        incoming_value = str(incoming_record.get(key, "")).strip()
        base_value = str(base_record.get(key, "")).strip()
        if incoming_value:
            if base_value and base_value != incoming_value and key == "summary":
                warnings.append(f"{source_name}: group brief conflict on {group_id}; used incoming {key}.")
            merged[key] = incoming_value
        elif base_value:
            merged[key] = base_value
        else:
            merged.pop(key, None)

    for key in GROUP_BRIEF_LIST_FIELDS:
        combined: list[str] = []
        seen: set[str] = set()
        for source in (base_record, incoming_record):
            raw = source.get(key)
            if not isinstance(raw, list):
                continue
            for item in raw:
                text = str(item or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                combined.append(text)
        if combined:
            merged[key] = combined
        else:
            merged.pop(key, None)

    combined_acks: list[dict[str, Any]] = []
    seen_acks: set[str] = set()
    for source in (base_record, incoming_record):
        raw = source.get("acknowledgedBy")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            identity = canonical_json(item)
            if identity in seen_acks:
                continue
            seen_acks.add(identity)
            combined_acks.append(copy.deepcopy(item))
    if combined_acks:
        merged["acknowledgedBy"] = combined_acks
    else:
        merged.pop("acknowledgedBy", None)

    # approval merge: prefer newer/revoked state
    from diffgr.approval import merge_approval_record  # noqa: PLC0415 — deferred to avoid circular import

    should_set, approval_value = merge_approval_record(
        base_record.get("approval"), incoming_record.get("approval")
    )
    if should_set:
        merged["approval"] = approval_value
    elif "approval" not in incoming_record:
        pass  # keep base approval as-is

    handled_keys = (
        {"status", "acknowledgedBy", "approval"}
        | GROUP_BRIEF_SINGLE_FIELDS
        | GROUP_BRIEF_LIST_FIELDS
    )
    for key, value in incoming_record.items():
        if key in handled_keys:
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def normalize_brief_items(value: Any) -> list[str]:
    """Normalize a list field to a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text)
    return items


def normalize_group_brief_record(raw: Any) -> dict[str, Any]:
    """Normalize a raw group brief record while preserving unknown fields."""
    if not isinstance(raw, dict):
        raw = {}
    normalized = copy.deepcopy(raw)
    status = str(raw.get("status", "draft")).strip() or "draft"
    if status not in VALID_GROUP_BRIEF_STATUSES:
        status = "draft"
    normalized["status"] = status
    normalized["summary"] = str(raw.get("summary", "")).strip()
    for key in CORE_LIST_KEYS:
        normalized[key] = normalize_brief_items(raw.get(key))
    for key in GROUP_BRIEF_METADATA_FIELDS:
        value = str(raw.get(key, "")).strip()
        if value:
            normalized[key] = value
        else:
            normalized.pop(key, None)
    mentions = normalize_brief_items(raw.get("mentions"))
    if mentions:
        normalized["mentions"] = mentions
    else:
        normalized.pop("mentions", None)
    raw_acks = raw.get("acknowledgedBy")
    if isinstance(raw_acks, list):
        acks = [copy.deepcopy(item) for item in raw_acks if isinstance(item, dict)]
        if acks:
            normalized["acknowledgedBy"] = acks
        else:
            normalized.pop("acknowledgedBy", None)
    else:
        normalized.pop("acknowledgedBy", None)
    approval = raw.get("approval")
    if isinstance(approval, dict):
        normalized["approval"] = copy.deepcopy(approval)
    else:
        normalized.pop("approval", None)
    return normalized


SPECIAL_KEYS: frozenset[str] = frozenset(
    {"status", "summary", *GROUP_BRIEF_METADATA_FIELDS, *CORE_LIST_KEYS, "mentions", "acknowledgedBy", "approval"}
)


def merge_group_brief_payload(
    existing: Any,
    payload: dict[str, Any],
    *,
    fallback_status: str = "draft",
) -> dict[str, Any] | None:
    """Merge a UI/editor payload into an existing group brief record.

    Known handoff fields behave like PATCH semantics: omitted keys keep their existing
    normalized value, while present keys replace the corresponding value. Unknown keys
    are preserved so UI round-trips do not silently drop future extensions.

    Returns the merged record, or ``None`` when the result is semantically empty.
    """
    brief = normalize_group_brief_record(existing)

    for key, value in payload.items():
        if key not in SPECIAL_KEYS:
            brief[key] = copy.deepcopy(value)

    if "status" in payload:
        status = str(payload.get("status", "")).strip()
        if status not in VALID_GROUP_BRIEF_STATUSES:
            status = fallback_status if fallback_status in VALID_GROUP_BRIEF_STATUSES else "draft"
    else:
        status = normalize_group_brief_status(brief.get("status")) or (
            fallback_status if fallback_status in VALID_GROUP_BRIEF_STATUSES else "draft"
        )
    brief["status"] = status

    if "summary" in payload:
        brief["summary"] = str(payload.get("summary", "")).strip()
    else:
        brief["summary"] = str(brief.get("summary", "")).strip()

    for key in CORE_LIST_KEYS:
        if key in payload:
            brief[key] = normalize_brief_items(payload.get(key))
        else:
            brief[key] = normalize_brief_items(brief.get(key))

    for key in GROUP_BRIEF_METADATA_FIELDS:
        if key in payload:
            value = str(payload.get(key, "")).strip()
        else:
            value = str(brief.get(key, "")).strip()
        if value:
            brief[key] = value
        else:
            brief.pop(key, None)

    if "mentions" in payload or "mentions" in brief:
        mentions_source = payload.get("mentions") if "mentions" in payload else brief.get("mentions")
        mentions = normalize_brief_items(mentions_source)
        if mentions:
            brief["mentions"] = mentions
        else:
            brief.pop("mentions", None)

    ack_source = payload.get("acknowledgedBy") if "acknowledgedBy" in payload else brief.get("acknowledgedBy")
    if isinstance(ack_source, list):
        acks = [copy.deepcopy(item) for item in ack_source if isinstance(item, dict)]
        if acks:
            brief["acknowledgedBy"] = acks
        else:
            brief.pop("acknowledgedBy", None)

    approval_source = payload.get("approval") if "approval" in payload else brief.get("approval")
    if isinstance(approval_source, dict):
        brief["approval"] = copy.deepcopy(approval_source)
    elif "approval" in payload:
        brief.pop("approval", None)

    has_content = any(
        [
            brief.get("summary", ""),
            brief.get("focusPoints", []),
            brief.get("testEvidence", []),
            brief.get("knownTradeoffs", []),
            brief.get("questionsForReviewer", []),
        ]
    )
    preserve_record = bool(brief.get("approval")) or bool(brief.get("mentions")) or bool(brief.get("acknowledgedBy"))
    has_extra = any(k not in SPECIAL_KEYS for k in brief)
    if has_content or brief.get("status") != "draft" or preserve_record or has_extra:
        return brief
    return None


def summarize_group_brief_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {
            "status": "",
            "summary": "",
            "focusPointsCount": 0,
            "testEvidenceCount": 0,
            "questionsCount": 0,
            "mentionsCount": 0,
            "acknowledgedByCount": 0,
        }
    return {
        "status": str(record.get("status", "")).strip(),
        "summary": str(record.get("summary", "")).strip(),
        "focusPointsCount": len(record.get("focusPoints", [])) if isinstance(record.get("focusPoints"), list) else 0,
        "testEvidenceCount": len(record.get("testEvidence", [])) if isinstance(record.get("testEvidence"), list) else 0,
        "questionsCount": len(record.get("questionsForReviewer", []))
        if isinstance(record.get("questionsForReviewer"), list)
        else 0,
        "mentionsCount": len(record.get("mentions", [])) if isinstance(record.get("mentions"), list) else 0,
        "acknowledgedByCount": len(record.get("acknowledgedBy", []))
        if isinstance(record.get("acknowledgedBy"), list)
        else 0,
    }
