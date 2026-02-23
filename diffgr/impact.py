from __future__ import annotations

from dataclasses import asdict
from typing import Any

from diffgr.review_rebase import ChunkMatch, match_chunks
from diffgr.virtual_pr_coverage import CoverageIssue, analyze_virtual_pr_coverage


def _group_sort_key(group: dict[str, Any]) -> tuple:
    return (
        group.get("order") is None,
        group.get("order", 0),
        str(group.get("name", "")),
        str(group.get("id", "")),
    )


def _chunk_change_preview(chunk: dict[str, Any], *, max_lines: int = 6) -> str:
    lines: list[str] = []
    for ln in chunk.get("lines") or []:
        kind = ln.get("kind")
        if kind not in {"add", "delete"}:
            continue
        text = str(ln.get("text", ""))
        if text.strip() == "":
            continue
        lines.append(f"{kind}: {text}")
        if len(lines) >= max_lines:
            break
    return " / ".join(lines) if lines else "(no add/delete lines)"


def _coverage_to_dict(issue: CoverageIssue) -> dict[str, Any]:
    payload = asdict(issue)
    payload["ok"] = issue.ok
    return payload


def _chunk_item(chunk: dict[str, Any], chunk_id: str, *, preview_lines: int) -> dict[str, Any]:
    return {
        "id": chunk_id,
        "filePath": chunk.get("filePath"),
        "header": chunk.get("header"),
        "old": chunk.get("old"),
        "new": chunk.get("new"),
        "preview": _chunk_change_preview(chunk, max_lines=preview_lines),
    }


def build_impact_report(
    *,
    old_doc: dict[str, Any],
    new_doc: dict[str, Any],
    grouping: str = "old",
    similarity_threshold: float = 0.86,
    max_items_per_group: int = 20,
    preview_lines: int = 6,
) -> dict[str, Any]:
    if grouping not in {"old", "new"}:
        raise ValueError("grouping must be 'old' or 'new'")

    matches, warnings = match_chunks(old_doc, new_doc, similarity_threshold=similarity_threshold)
    old_chunk_by_id = {
        str(chunk.get("id")): chunk
        for chunk in old_doc.get("chunks", []) or []
        if isinstance(chunk, dict) and str(chunk.get("id", ""))
    }
    new_chunk_by_id = {
        str(chunk.get("id")): chunk
        for chunk in new_doc.get("chunks", []) or []
        if isinstance(chunk, dict) and str(chunk.get("id", ""))
    }

    old_to_new: dict[str, ChunkMatch] = {m.old_id: m for m in matches}
    new_to_old: dict[str, ChunkMatch] = {m.new_id: m for m in matches}

    old_ids = set(old_chunk_by_id.keys())
    new_ids = set(new_chunk_by_id.keys())
    matched_old = set(old_to_new.keys())
    matched_new = set(new_to_old.keys())
    old_only = sorted(old_ids - matched_old)
    new_only = sorted(new_ids - matched_new)

    matched_counts = {
        "strong": sum(1 for m in matches if m.kind == "strong"),
        "stable": sum(1 for m in matches if m.kind == "stable"),
        "delta": sum(1 for m in matches if m.kind == "delta"),
        "similar": sum(1 for m in matches if m.kind == "similar"),
    }

    old_meta = old_doc.get("meta", {}) if isinstance(old_doc.get("meta"), dict) else {}
    new_meta = new_doc.get("meta", {}) if isinstance(new_doc.get("meta"), dict) else {}
    old_source = old_meta.get("source", {}) if isinstance(old_meta.get("source"), dict) else {}
    new_source = new_meta.get("source", {}) if isinstance(new_meta.get("source"), dict) else {}

    coverage_new = _coverage_to_dict(analyze_virtual_pr_coverage(new_doc))

    def _group_items_from(doc: dict[str, Any]) -> list[dict[str, Any]]:
        groups = [g for g in doc.get("groups", []) or [] if isinstance(g, dict)]
        groups.sort(key=_group_sort_key)
        return groups

    def _assigned_ids(doc: dict[str, Any], group_id: str) -> list[str]:
        assignments = doc.get("assignments", {})
        if not isinstance(assignments, dict):
            return []
        raw = assignments.get(group_id, [])
        if not isinstance(raw, list):
            return []
        return [str(cid) for cid in raw]

    report_groups: list[dict[str, Any]] = []
    if grouping == "old":
        groups = _group_items_from(old_doc)
        for group in groups:
            gid = str(group.get("id", "")).strip()
            if not gid:
                continue
            assigned_old = [cid for cid in _assigned_ids(old_doc, gid) if cid in old_chunk_by_id]

            unchanged: list[str] = []
            changed: list[dict[str, Any]] = []
            removed: list[str] = []
            for old_id in assigned_old:
                match = old_to_new.get(old_id)
                if match is None:
                    removed.append(old_id)
                    continue
                if match.kind in {"strong", "stable", "delta"}:
                    unchanged.append(match.new_id)
                    continue
                item = _chunk_item(new_chunk_by_id.get(match.new_id) or {}, match.new_id, preview_lines=preview_lines)
                item["fromOldId"] = match.old_id
                item["matchKind"] = match.kind
                item["matchScore"] = match.score
                changed.append(item)

            changed_ids = [str(item.get("id", "")) for item in changed if str(item.get("id", ""))]
            action = "skip" if (not changed_ids and not removed) else "review"
            report_groups.append(
                {
                    "id": gid,
                    "name": str(group.get("name", gid)),
                    "order": group.get("order"),
                    "totalOld": len(assigned_old),
                    "unchanged": len(unchanged),
                    "changed": len(changed_ids),
                    "removed": len(removed),
                    "action": action,
                    "changedChunkIds": changed_ids,
                    "removedChunkIds": list(removed),
                    "changedChunks": changed[:max_items_per_group],
                    "removedChunks": [
                        _chunk_item(old_chunk_by_id.get(cid) or {}, cid, preview_lines=preview_lines)
                        for cid in removed[:max_items_per_group]
                    ],
                }
            )
    else:
        groups = _group_items_from(new_doc)
        for group in groups:
            gid = str(group.get("id", "")).strip()
            if not gid:
                continue
            assigned_new = [cid for cid in _assigned_ids(new_doc, gid) if cid in new_chunk_by_id]

            unchanged: list[str] = []
            changed: list[dict[str, Any]] = []
            added: list[dict[str, Any]] = []
            for new_id in assigned_new:
                match = new_to_old.get(new_id)
                if match is None:
                    added.append(_chunk_item(new_chunk_by_id.get(new_id) or {}, new_id, preview_lines=preview_lines))
                    continue
                if match.kind in {"strong", "stable", "delta"}:
                    unchanged.append(new_id)
                    continue
                item = _chunk_item(new_chunk_by_id.get(new_id) or {}, new_id, preview_lines=preview_lines)
                item["fromOldId"] = match.old_id
                item["matchKind"] = match.kind
                item["matchScore"] = match.score
                changed.append(item)

            changed_ids = [str(item.get("id", "")) for item in changed if str(item.get("id", ""))]
            added_ids = [str(item.get("id", "")) for item in added if str(item.get("id", ""))]
            action = "skip" if (not changed_ids and not added_ids) else "review"
            report_groups.append(
                {
                    "id": gid,
                    "name": str(group.get("name", gid)),
                    "order": group.get("order"),
                    "totalNew": len(assigned_new),
                    "unchanged": len(unchanged),
                    "changed": len(changed_ids),
                    "new": len(added_ids),
                    "action": action,
                    "changedChunkIds": changed_ids,
                    "newChunkIds": added_ids,
                    "changedChunks": changed[:max_items_per_group],
                    "newChunks": added[:max_items_per_group],
                }
            )

    new_only_items = [_chunk_item(new_chunk_by_id.get(cid) or {}, cid, preview_lines=preview_lines) for cid in new_only[:max_items_per_group]]
    old_only_items = [_chunk_item(old_chunk_by_id.get(cid) or {}, cid, preview_lines=preview_lines) for cid in old_only[:max_items_per_group]]

    return {
        "grouping": grouping,
        "old": {
            "title": str(old_meta.get("title", "")),
            "createdAt": old_meta.get("createdAt"),
            "source": old_source,
            "chunkCount": len(old_chunk_by_id),
        },
        "new": {
            "title": str(new_meta.get("title", "")),
            "createdAt": new_meta.get("createdAt"),
            "source": new_source,
            "chunkCount": len(new_chunk_by_id),
        },
        "match": {
            "counts": matched_counts,
            "oldOnly": len(old_only),
            "newOnly": len(new_only),
            "warnings": warnings,
            "similarityThreshold": similarity_threshold,
        },
        "coverageNew": coverage_new,
        "groups": report_groups,
        "newOnlyChunkIds": new_only,
        "oldOnlyChunkIds": old_only,
        "newOnlyChunks": new_only_items,
        "oldOnlyChunks": old_only_items,
    }
