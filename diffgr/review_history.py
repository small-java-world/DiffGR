from __future__ import annotations

import datetime as dt
from typing import Any


def iso_utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_meta(doc: dict[str, Any]) -> dict[str, Any]:
    meta = doc.get("meta", {})
    if not isinstance(meta, dict):
        return {}
    source = meta.get("source", {})
    if not isinstance(source, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ["type", "url", "base", "head", "baseSha", "headSha", "mergeBaseSha", "description"]:
        value = source.get(key)
        if value is not None:
            out[key] = value
    return out


def _title(doc: dict[str, Any]) -> str:
    meta = doc.get("meta", {})
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("title", ""))


def _cap_list(values: list[Any], *, max_ids_per_group: int) -> tuple[list[Any], int]:
    if max_ids_per_group <= 0:
        return [], len(values)
    if len(values) <= max_ids_per_group:
        return values, 0
    return values[:max_ids_per_group], len(values) - max_ids_per_group


def _group_digest(
    groups: list[dict[str, Any]],
    *,
    max_ids_per_group: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    impacted: list[dict[str, Any]] = []
    unaffected: list[dict[str, Any]] = []
    for item in groups:
        if not isinstance(item, dict):
            continue
        changed_ids_raw = item.get("changedChunkIds", [])
        removed_ids_raw = item.get("removedChunkIds", [])
        new_ids_raw = item.get("newChunkIds", [])
        changed_ids = list(changed_ids_raw) if isinstance(changed_ids_raw, list) else []
        removed_ids = list(removed_ids_raw) if isinstance(removed_ids_raw, list) else []
        new_ids = list(new_ids_raw) if isinstance(new_ids_raw, list) else []
        changed_ids_capped, changed_truncated = _cap_list(changed_ids, max_ids_per_group=max_ids_per_group)
        removed_ids_capped, removed_truncated = _cap_list(removed_ids, max_ids_per_group=max_ids_per_group)
        new_ids_capped, new_truncated = _cap_list(new_ids, max_ids_per_group=max_ids_per_group)
        digest = {
            "id": item.get("id"),
            "name": item.get("name"),
            "order": item.get("order"),
            "action": item.get("action"),
            "changed": item.get("changed", 0),
            "removed": item.get("removed", 0),
            "new": item.get("new", 0),
            "unchanged": item.get("unchanged", 0),
            "changedChunkIds": changed_ids_capped,
            "removedChunkIds": removed_ids_capped,
            "newChunkIds": new_ids_capped,
            "changedChunkIdsTruncated": changed_truncated,
            "removedChunkIdsTruncated": removed_truncated,
            "newChunkIdsTruncated": new_truncated,
        }
        if str(item.get("action", "")) == "review":
            impacted.append(digest)
        else:
            unaffected.append(digest)
    return impacted, unaffected


def build_rebase_history_entry(
    *,
    old_doc: dict[str, Any],
    new_doc: dict[str, Any],
    summary: dict[str, Any],
    impact: dict[str, Any],
    old_path: str,
    new_path: str,
    output_path: str,
    keep_new_groups: bool,
    carry_line_comments: bool,
    similarity_threshold: float,
    warnings: list[str],
    label: str | None = None,
    actor: str | None = None,
    max_ids_per_group: int = 200,
) -> dict[str, Any]:
    impact_groups = impact.get("groups", [])
    if not isinstance(impact_groups, list):
        impact_groups = []
    impacted_groups, unaffected_groups = _group_digest(impact_groups, max_ids_per_group=max_ids_per_group)

    coverage_new = impact.get("coverageNew", {})
    if not isinstance(coverage_new, dict):
        coverage_new = {}
    match = impact.get("match", {})
    if not isinstance(match, dict):
        match = {}
    counts = match.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}

    entry: dict[str, Any] = {
        "type": "rebase",
        "at": iso_utc_now(),
        "from": {
            "path": old_path,
            "title": _title(old_doc),
            "source": _source_meta(old_doc),
        },
        "to": {
            "path": new_path,
            "title": _title(new_doc),
            "source": _source_meta(new_doc),
        },
        "output": output_path,
        "options": {
            "keepNewGroups": bool(keep_new_groups),
            "carryLineComments": bool(carry_line_comments),
            "similarityThreshold": similarity_threshold,
        },
        "result": {
            "matchedStrong": summary.get("matchedStrong", 0),
            "matchedStable": summary.get("matchedStable", 0),
            "matchedDelta": summary.get("matchedDelta", 0),
            "matchedSimilar": summary.get("matchedSimilar", 0),
            "carriedReviews": summary.get("carriedReviews", 0),
            "carriedReviewed": summary.get("carriedReviewed", 0),
            "changedToNeedsReReview": summary.get("changedToNeedsReReview", 0),
            "unmappedNewChunks": summary.get("unmappedNewChunks", 0),
            "warnings": list(warnings),
        },
        "impactScope": {
            "grouping": impact.get("grouping", "old"),
            "impactedGroupCount": len(impacted_groups),
            "unaffectedGroupCount": len(unaffected_groups),
            "impactedGroups": impacted_groups,
            "unaffectedGroups": unaffected_groups,
            "newOnlyChunkIds": impact.get("newOnlyChunkIds", []),
            "oldOnlyChunkIds": impact.get("oldOnlyChunkIds", []),
            "matchCounts": {
                "strong": counts.get("strong", 0),
                "stable": counts.get("stable", 0),
                "delta": counts.get("delta", 0),
                "similar": counts.get("similar", 0),
            },
            "coverageNew": {
                "ok": bool(coverage_new.get("ok", False)),
                "unassigned": coverage_new.get("unassigned", []),
                "duplicated": coverage_new.get("duplicated", {}),
                "unknownGroups": coverage_new.get("unknown_groups", []),
                "unknownChunks": coverage_new.get("unknown_chunks", {}),
            },
        },
    }
    if label:
        entry["label"] = str(label)
    if actor:
        entry["actor"] = str(actor)
    return entry


def append_review_history(doc: dict[str, Any], entry: dict[str, Any], *, max_entries: int = 100) -> None:
    meta = doc.setdefault("meta", {})
    if not isinstance(meta, dict):
        return
    history = meta.get("x-reviewHistory")
    if not isinstance(history, list):
        history = []
    history.append(entry)
    if max_entries > 0 and len(history) > max_entries:
        history = history[-max_entries:]
    meta["x-reviewHistory"] = history
    meta["x-impactScope"] = entry.get("impactScope", {})
