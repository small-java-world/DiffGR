from __future__ import annotations

from dataclasses import asdict
from typing import Any

from diffgr.viewer_core import VALID_STATUSES, build_indexes, compute_metrics
from diffgr.virtual_pr_coverage import analyze_virtual_pr_coverage


def _status_counts(chunk_ids: list[str], status_map: dict[str, str]) -> dict[str, int]:
    counts = {status: 0 for status in VALID_STATUSES}
    for chunk_id in chunk_ids:
        status = status_map.get(chunk_id, "unreviewed")
        if status not in VALID_STATUSES:
            status = "unreviewed"
        counts[status] += 1
    return counts


def summarize_document(doc: dict[str, Any]) -> dict[str, Any]:
    meta = doc.get("meta", {}) if isinstance(doc.get("meta"), dict) else {}
    source = meta.get("source", {}) if isinstance(meta.get("source"), dict) else {}
    groups = [g for g in doc.get("groups", []) if isinstance(g, dict)]

    chunk_map, status_map = build_indexes(doc)
    metrics = compute_metrics(doc, status_map)
    coverage = analyze_virtual_pr_coverage(doc)

    group_items: list[dict[str, Any]] = []
    assignments = doc.get("assignments", {}) if isinstance(doc.get("assignments"), dict) else {}
    for group in sorted(
        groups,
        key=lambda item: (
            item.get("order") is None,
            item.get("order", 0),
            str(item.get("name", "")),
            str(item.get("id", "")),
        ),
    ):
        gid = str(group.get("id", "")).strip()
        if not gid:
            continue
        assigned = assignments.get(gid, [])
        if not isinstance(assigned, list):
            assigned = []
        chunk_ids = [str(cid) for cid in assigned if str(cid) in chunk_map]
        counts = _status_counts(chunk_ids, status_map)

        total = len(chunk_ids)
        ignored = counts.get("ignored", 0)
        tracked = total - ignored
        reviewed = counts.get("reviewed", 0)
        pending = tracked - reviewed
        rate = 1.0 if tracked == 0 else (reviewed / tracked)

        group_items.append(
            {
                "id": gid,
                "name": str(group.get("name", gid)),
                "order": group.get("order"),
                "total": total,
                "tracked": tracked,
                "reviewed": reviewed,
                "pending": pending,
                "rate": rate,
                "statusCounts": counts,
            }
        )

    return {
        "title": str(meta.get("title", "")),
        "createdAt": meta.get("createdAt"),
        "source": source,
        "chunkCount": len(chunk_map),
        "groupCount": len(groups),
        "coverage": asdict(coverage) | {"ok": coverage.ok},
        "review": metrics,
        "groups": group_items,
    }

