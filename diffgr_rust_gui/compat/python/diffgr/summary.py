from __future__ import annotations

from dataclasses import asdict
from typing import Any

from diffgr.group_utils import ordered_groups
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
    chunk_map, status_map = build_indexes(doc)
    metrics = compute_metrics(doc, status_map)
    coverage = analyze_virtual_pr_coverage(doc)
    group_briefs = doc.get("groupBriefs", {}) if isinstance(doc.get("groupBriefs"), dict) else {}
    analysis_state = doc.get("analysisState", {}) if isinstance(doc.get("analysisState"), dict) else {}
    thread_state = doc.get("threadState", {}) if isinstance(doc.get("threadState"), dict) else {}
    brief_status_counts = {"draft": 0, "ready": 0, "acknowledged": 0, "stale": 0}
    brief_total = 0
    file_thread_state = thread_state.get("__files", {}) if isinstance(thread_state.get("__files"), dict) else {}
    thread_chunk_entry_count = sum(
        1 for key in thread_state.keys() if key not in {"__files", "selectedLineAnchor"}
    )

    groups = ordered_groups(doc)
    group_items: list[dict[str, Any]] = []
    assignments = doc.get("assignments", {}) if isinstance(doc.get("assignments"), dict) else {}
    for group in groups:
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
        brief = group_briefs.get(gid, {})
        has_brief = isinstance(brief, dict) and bool(
            str(brief.get("summary", "")).strip()
            or brief.get("focusPoints")
            or brief.get("testEvidence")
            or brief.get("knownTradeoffs")
            or brief.get("questionsForReviewer")
        )
        brief_status = "none"
        if isinstance(brief, dict):
            brief_status = str(brief.get("status", "draft")).strip() or "draft"
            if brief_status not in brief_status_counts:
                brief_status = "draft"
            brief_status_counts[brief_status] += 1
            brief_total += 1

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
                "hasBrief": has_brief,
                "briefStatus": brief_status,
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
        "briefs": {
            "total": brief_total,
            "statusCounts": brief_status_counts,
        },
        "state": {
            "hasAnalysisState": bool(analysis_state),
            "hasThreadState": bool(thread_state),
            "currentGroupId": str(analysis_state.get("currentGroupId", "")).strip(),
            "selectedChunkId": str(analysis_state.get("selectedChunkId", "")).strip(),
            "filterText": str(analysis_state.get("filterText", "")).strip(),
            "groupReportMode": bool(analysis_state.get("groupReportMode", False)),
            "chunkDetailViewMode": str(analysis_state.get("chunkDetailViewMode", "")).strip(),
            "showContextLines": bool(analysis_state.get("showContextLines", True)),
            "threadChunkEntryCount": thread_chunk_entry_count,
            "threadFileEntryCount": len(file_thread_state),
            "hasSelectedLineAnchor": isinstance(thread_state.get("selectedLineAnchor"), dict),
        },
        "groups": group_items,
    }
