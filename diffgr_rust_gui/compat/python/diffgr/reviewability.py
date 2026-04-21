from __future__ import annotations

import copy
import json
from typing import Any

from diffgr.group_utils import safe_groups

DEFAULT_REVIEWABILITY_THRESHOLDS: dict[str, int] = {
    "denseChunkCount": 6,
    "denseChangedLines": 200,
    "denseFileCount": 4,
    "resliceChunkCount": 12,
    "resliceChangedLines": 400,
    "resliceFileCount": 8,
    "mustReadCount": 3,
    "hotspotBonusMixedChange": 20,
    "hotspotBonusNeedsReview": 15,
    "hotspotBonusHasComments": 8,
}


def normalize_reviewability_thresholds(overrides: dict[str, Any] | None = None) -> dict[str, int]:
    thresholds = copy.deepcopy(DEFAULT_REVIEWABILITY_THRESHOLDS)
    if not isinstance(overrides, dict):
        return thresholds
    for key, value in overrides.items():
        try:
            thresholds[str(key)] = int(value)
        except Exception:
            continue
    return thresholds


def _group_name(doc: dict[str, Any], group_id: str) -> str:
    for group in doc.get("groups", []):
        if isinstance(group, dict) and str(group.get("id", "")).strip() == group_id:
            return str(group.get("name", group_id))
    return group_id


def _chunk_ids_for_group(doc: dict[str, Any], group_id: str) -> list[str]:
    assignments = doc.get("assignments", {})
    if not isinstance(assignments, dict):
        return []
    raw = assignments.get(group_id, [])
    if not isinstance(raw, list):
        return []
    return [str(chunk_id).strip() for chunk_id in raw if str(chunk_id).strip()]


def _review_status(doc: dict[str, Any], chunk_id: str) -> str:
    reviews = doc.get("reviews", {})
    if not isinstance(reviews, dict):
        return "unreviewed"
    record = reviews.get(chunk_id)
    if not isinstance(record, dict):
        return "unreviewed"
    status = str(record.get("status", "unreviewed")).strip()
    return status if status in {"unreviewed", "reviewed", "ignored", "needsReReview"} else "unreviewed"


def _chunk_change_counts(chunk: dict[str, Any]) -> dict[str, int]:
    add_lines = 0
    delete_lines = 0
    context_lines = 0
    for line in chunk.get("lines", []) or []:
        kind = str(line.get("kind", "")).strip()
        if kind == "add":
            add_lines += 1
        elif kind == "delete":
            delete_lines += 1
        else:
            context_lines += 1
    return {
        "addLines": add_lines,
        "deleteLines": delete_lines,
        "contextLines": context_lines,
        "changedLines": add_lines + delete_lines,
    }


def _chunk_hotspot_score(doc: dict[str, Any], chunk_id: str, chunk: dict[str, Any], thresholds: dict[str, int]) -> int:
    counts = _chunk_change_counts(chunk)
    status = _review_status(doc, chunk_id)
    score = counts["changedLines"]
    if counts["addLines"] and counts["deleteLines"]:
        score += thresholds["hotspotBonusMixedChange"]
    if status in {"unreviewed", "needsReReview"}:
        score += thresholds["hotspotBonusNeedsReview"]
    record = doc.get("reviews", {}).get(chunk_id) if isinstance(doc.get("reviews"), dict) else None
    if isinstance(record, dict):
        has_chunk_comment = str(record.get("comment", "")).strip()
        has_line_comments = isinstance(record.get("lineComments"), list) and bool(record.get("lineComments"))
        if has_chunk_comment or has_line_comments:
            score += thresholds["hotspotBonusHasComments"]
    return score


def compute_group_reviewability(
    doc: dict[str, Any],
    group_id: str,
    *,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_thresholds = normalize_reviewability_thresholds(thresholds)
    chunk_map = {
        str(chunk.get("id", "")).strip(): chunk
        for chunk in doc.get("chunks", [])
        if isinstance(chunk, dict) and str(chunk.get("id", "")).strip()
    }
    chunk_ids = _chunk_ids_for_group(doc, group_id)
    chunk_stats: list[tuple[str, dict[str, Any], dict[str, int], int]] = []
    for chunk_id in chunk_ids:
        chunk = chunk_map.get(chunk_id)
        if not isinstance(chunk, dict):
            continue
        counts = _chunk_change_counts(chunk)
        score = _chunk_hotspot_score(doc, chunk_id, chunk, normalized_thresholds)
        chunk_stats.append((chunk_id, chunk, counts, score))

    file_paths = {
        str(chunk.get("filePath", "")).strip()
        for _, chunk, _, _ in chunk_stats
        if str(chunk.get("filePath", "")).strip()
    }
    add_lines = sum(counts["addLines"] for _, _, counts, _ in chunk_stats)
    delete_lines = sum(counts["deleteLines"] for _, _, counts, _ in chunk_stats)
    changed_lines = add_lines + delete_lines
    reviewed_count = sum(1 for chunk_id in chunk_ids if _review_status(doc, chunk_id) in {"reviewed", "ignored"})
    brief = doc.get("groupBriefs", {}).get(group_id, {}) if isinstance(doc.get("groupBriefs"), dict) else {}
    has_summary = isinstance(brief, dict) and bool(str(brief.get("summary", "")).strip())
    has_focus_points = isinstance(brief, dict) and isinstance(brief.get("focusPoints"), list) and bool(brief.get("focusPoints"))
    has_test_evidence = isinstance(brief, dict) and isinstance(brief.get("testEvidence"), list) and bool(brief.get("testEvidence"))
    has_questions = isinstance(brief, dict) and isinstance(brief.get("questionsForReviewer"), list) and bool(brief.get("questionsForReviewer"))

    reasons: list[str] = []
    if len(chunk_ids) > normalized_thresholds["resliceChunkCount"]:
        reasons.append(f"chunk count {len(chunk_ids)} > {normalized_thresholds['resliceChunkCount']}")
    if changed_lines > normalized_thresholds["resliceChangedLines"]:
        reasons.append(f"changed lines {changed_lines} > {normalized_thresholds['resliceChangedLines']}")
    if len(file_paths) > normalized_thresholds["resliceFileCount"]:
        reasons.append(f"file count {len(file_paths)} > {normalized_thresholds['resliceFileCount']}")
    if reasons:
        verdict = "needs_reslice"
    else:
        handoff_gaps: list[str] = []
        if not has_summary:
            handoff_gaps.append("missing summary")
        if not has_focus_points:
            handoff_gaps.append("missing focusPoints")
        if not has_test_evidence:
            handoff_gaps.append("missing testEvidence")
        if handoff_gaps:
            verdict = "needs_handoff"
            reasons = handoff_gaps
        elif (
            len(chunk_ids) > normalized_thresholds["denseChunkCount"]
            or changed_lines > normalized_thresholds["denseChangedLines"]
            or len(file_paths) > normalized_thresholds["denseFileCount"]
        ):
            verdict = "dense"
            reasons = []
            if len(chunk_ids) > normalized_thresholds["denseChunkCount"]:
                reasons.append(f"chunk count {len(chunk_ids)} > {normalized_thresholds['denseChunkCount']}")
            if changed_lines > normalized_thresholds["denseChangedLines"]:
                reasons.append(f"changed lines {changed_lines} > {normalized_thresholds['denseChangedLines']}")
            if len(file_paths) > normalized_thresholds["denseFileCount"]:
                reasons.append(f"file count {len(file_paths)} > {normalized_thresholds['denseFileCount']}")
        else:
            verdict = "good"

    ranked_chunk_ids = [
        chunk_id
        for chunk_id, _, counts, score in sorted(
            chunk_stats,
            key=lambda item: (-item[3], -item[2]["changedLines"], item[0]),
        )
    ]
    must_read_count = min(normalized_thresholds["mustReadCount"], len(ranked_chunk_ids))
    must_read_chunks = ranked_chunk_ids[:must_read_count]
    # Three mutually exclusive buckets:
    #   mustReadChunks  — top-N by priority score (read these first)
    #   hotspotChunks   — unreviewed/needsReReview chunks outside mustRead
    #   skimmableChunks — reviewed/ignored chunks outside mustRead
    must_read_set = set(must_read_chunks)
    hotspot_chunks = [
        chunk_id for chunk_id in ranked_chunk_ids
        if chunk_id not in must_read_set and _review_status(doc, chunk_id) in {"unreviewed", "needsReReview"}
    ]
    skimmable_chunks = [
        chunk_id
        for chunk_id in ranked_chunk_ids  # symmetric with hotspot_chunks: both exclude orphaned IDs
        if chunk_id not in must_read_set and _review_status(doc, chunk_id) in {"reviewed", "ignored"}
    ]

    return {
        "groupId": group_id,
        "groupName": _group_name(doc, group_id),
        "verdict": verdict,
        "reasons": reasons,
        "chunkCount": len(chunk_ids),
        "fileCount": len(file_paths),
        "addLines": add_lines,
        "deleteLines": delete_lines,
        "changedLines": changed_lines,
        "reviewedCount": reviewed_count,
        "totalCount": len(chunk_ids),
        "hasSummary": has_summary,
        "hasFocusPoints": has_focus_points,
        "hasTestEvidence": has_test_evidence,
        "hasQuestions": has_questions,
        "mustReadChunks": must_read_chunks,
        "hotspotChunks": hotspot_chunks,
        "skimmableChunks": skimmable_chunks,
    }


def compute_all_group_reviewability(
    doc: dict[str, Any],
    *,
    thresholds: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    groups = safe_groups(doc)
    for group in groups:
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            continue
        results.append(compute_group_reviewability(doc, group_id, thresholds=thresholds))
    return results


def reviewability_report_to_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps({"groups": rows}, ensure_ascii=False, indent=2)
