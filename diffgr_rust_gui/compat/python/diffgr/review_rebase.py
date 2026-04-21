from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from typing import Any

from diffgr.diff_utils import line_anchor_key as _line_anchor_key
from diffgr.generator import canonical_json as _canonical_json, iso_utc_now as _iso_utc_now, sha256_hex as _sha256_hex
from diffgr.group_brief_utils import normalize_group_brief_status
from diffgr.review_utils import VALID_REVIEW_STATUSES, normalize_review_status

try:
    from rapidfuzz import fuzz as rapidfuzz_fuzz
except Exception:  # noqa: BLE001
    rapidfuzz_fuzz = None


def stable_fingerprint_for_chunk(chunk: dict[str, Any]) -> str:
    fingerprints = chunk.get("fingerprints")
    if isinstance(fingerprints, dict) and isinstance(fingerprints.get("stable"), str) and fingerprints["stable"]:
        return str(fingerprints["stable"])
    stable_input = {
        "filePath": str(chunk.get("filePath", "")),
        "lines": [{"kind": line.get("kind"), "text": line.get("text")} for line in (chunk.get("lines") or [])],
    }
    return _sha256_hex(stable_input)


def content_stable_fingerprint_for_chunk(chunk: dict[str, Any]) -> str:
    stable_input = {
        "header": str(chunk.get("header", "")),
        "lines": [{"kind": line.get("kind"), "text": line.get("text")} for line in (chunk.get("lines") or [])],
    }
    return _sha256_hex(stable_input)


def change_fingerprint_for_chunk(chunk: dict[str, Any]) -> str:
    """Fingerprint based on add/delete content only (ignore context and line numbers).

    This is used to detect 'no semantic diff change' even when the surrounding context
    lines change and stable fingerprints no longer match.
    """

    change_lines: list[dict[str, Any]] = []
    for line in chunk.get("lines") or []:
        kind = str(line.get("kind", ""))
        if kind not in {"add", "delete"}:
            continue
        change_lines.append({"kind": kind, "text": line.get("text")})
    change_input = {
        "filePath": str(chunk.get("filePath", "")),
        "lines": change_lines,
    }
    return _sha256_hex(change_input)


def _chunk_signature_text(chunk: dict[str, Any], *, include_path: bool = True) -> str:
    parts: list[str] = []
    if include_path:
        parts.append(str(chunk.get("filePath", "")))
    header = chunk.get("header")
    if header:
        parts.append(str(header))
    for line in chunk.get("lines") or []:
        kind = str(line.get("kind", ""))
        text = str(line.get("text", ""))
        if not kind or kind == "context":
            continue
        parts.append(f"{kind}:{text}")
    return "\n".join(parts)


def _similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if rapidfuzz_fuzz is not None:
        return float(rapidfuzz_fuzz.ratio(a, b)) / 100.0
    # Fallback: cheap ratio via common substring lengths.
    import difflib

    return difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio()


def _normalize_status(value: Any) -> str:
    return normalize_review_status(value, strict=True)


def _group_order_map(doc: dict[str, Any]) -> dict[str, int]:
    order_by_id: dict[str, int] = {}
    for group in doc.get("groups", []) or []:
        if not isinstance(group, dict):
            continue
        gid = str(group.get("id", "")).strip()
        if not gid:
            continue
        try:
            order_by_id[gid] = int(group.get("order", 0))
        except Exception:
            order_by_id[gid] = 0
    return order_by_id


def _group_for_chunk(doc: dict[str, Any], chunk_id: str) -> str | None:
    assignments = doc.get("assignments", {})
    if not isinstance(assignments, dict):
        return None
    candidates: list[str] = []
    for gid, ids in assignments.items():
        if not isinstance(ids, list):
            continue
        if chunk_id in ids:
            candidates.append(str(gid))
    if not candidates:
        return None
    order_by_id = _group_order_map(doc)
    candidates.sort(key=lambda gid: (gid not in order_by_id, order_by_id.get(gid, 0), gid))
    return candidates[0]


def _remap_line_comments_for_stable_match(
    old_chunk: dict[str, Any],
    new_chunk: dict[str, Any],
    old_record: dict[str, Any],
) -> list[dict[str, Any]]:
    old_line_comments = old_record.get("lineComments")
    if not isinstance(old_line_comments, list):
        return []
    old_lines = list(old_chunk.get("lines") or [])
    new_lines = list(new_chunk.get("lines") or [])
    if len(old_lines) != len(new_lines):
        return []

    old_index_by_anchor: dict[str, int] = {}
    for idx, line in enumerate(old_lines):
        kind = str(line.get("kind", ""))
        old_index_by_anchor[_line_anchor_key(kind, line.get("oldLine"), line.get("newLine"))] = idx

    remapped: list[dict[str, Any]] = []
    for item in old_line_comments:
        if not isinstance(item, dict):
            continue
        comment = str(item.get("comment", "")).strip()
        if not comment:
            continue
        kind = str(item.get("lineType", "")) or "context"
        key = _line_anchor_key(kind, item.get("oldLine"), item.get("newLine"))
        idx = old_index_by_anchor.get(key)
        if idx is None:
            continue
        new_line = new_lines[idx]
        remapped_item: dict[str, Any] = {
            "oldLine": new_line.get("oldLine"),
            "newLine": new_line.get("newLine"),
            "lineType": kind,
            "comment": comment,
        }
        if "updatedAt" in item:
            remapped_item["updatedAt"] = item.get("updatedAt")
        remapped.append(remapped_item)
    return remapped


def _remap_selected_line_anchor_for_stable_match(
    old_chunk: dict[str, Any],
    new_chunk: dict[str, Any],
    anchor: dict[str, Any],
) -> dict[str, Any] | None:
    kind = str(anchor.get("lineType", "")).strip() or "context"
    key = _line_anchor_key(kind, anchor.get("oldLine"), anchor.get("newLine"))
    old_lines = list(old_chunk.get("lines") or [])
    new_lines = list(new_chunk.get("lines") or [])
    if len(old_lines) != len(new_lines):
        return None
    old_index_by_anchor: dict[str, int] = {}
    for idx, line in enumerate(old_lines):
        line_kind = str(line.get("kind", ""))
        old_index_by_anchor[_line_anchor_key(line_kind, line.get("oldLine"), line.get("newLine"))] = idx
    idx = old_index_by_anchor.get(key)
    if idx is None:
        return None
    mapped_line = new_lines[idx]
    return {
        "anchorKey": _line_anchor_key(kind, mapped_line.get("oldLine"), mapped_line.get("newLine")),
        "oldLine": mapped_line.get("oldLine"),
        "newLine": mapped_line.get("newLine"),
        "lineType": kind,
    }


@dataclass(frozen=True)
class ChunkMatch:
    old_id: str
    new_id: str
    kind: str  # strong|stable|delta|similar
    score: float


@dataclass(frozen=True)
class RebaseSummary:
    matched_strong: int
    matched_stable: int
    matched_delta: int
    matched_similar: int
    carried_reviews: int
    carried_reviewed: int
    changed_to_needs_rereview: int
    unmapped_new_chunks: int


def _build_chunk_maps(doc: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    chunk_by_id: dict[str, dict[str, Any]] = {}
    stable_to_ids: dict[str, list[str]] = {}
    for chunk in doc.get("chunks", []) or []:
        if not isinstance(chunk, dict):
            continue
        cid = str(chunk.get("id", "")).strip()
        if not cid:
            continue
        chunk_by_id[cid] = chunk
        stable = stable_fingerprint_for_chunk(chunk)
        stable_to_ids.setdefault(stable, []).append(cid)
    return chunk_by_id, stable_to_ids


def _build_content_stable_map(doc: dict[str, Any], *, skip_ids: set[str] | None = None) -> dict[str, list[str]]:
    skip = skip_ids or set()
    content_to_ids: dict[str, list[str]] = {}
    for chunk in doc.get("chunks", []) or []:
        if not isinstance(chunk, dict):
            continue
        cid = str(chunk.get("id", "")).strip()
        if not cid or cid in skip:
            continue
        fp = content_stable_fingerprint_for_chunk(chunk)
        content_to_ids.setdefault(fp, []).append(cid)
    return content_to_ids


def _pair_by_range_closeness(
    old_ids: list[str],
    new_ids: list[str],
    old_chunk_by_id: dict[str, dict[str, Any]],
    new_chunk_by_id: dict[str, dict[str, Any]],
) -> list[tuple[str, str]]:
    # Greedy matching by closest new.start then old.start.
    def _start(chunk: dict[str, Any], side: str) -> int:
        rng = chunk.get(side) or {}
        try:
            return int(rng.get("start", 0))
        except Exception:
            return 0

    remaining_new = set(new_ids)
    pairs: list[tuple[str, str]] = []
    for old_id in old_ids:
        old_chunk = old_chunk_by_id.get(old_id) or {}
        candidates: list[tuple[int, int, str]] = []
        for new_id in remaining_new:
            new_chunk = new_chunk_by_id.get(new_id) or {}
            candidates.append(
                (
                    abs(_start(old_chunk, "new") - _start(new_chunk, "new")),
                    abs(_start(old_chunk, "old") - _start(new_chunk, "old")),
                    new_id,
                )
            )
        if not candidates:
            continue
        candidates.sort()
        chosen = candidates[0][2]
        remaining_new.remove(chosen)
        pairs.append((old_id, chosen))
    return pairs


def match_chunks(
    old_doc: dict[str, Any],
    new_doc: dict[str, Any],
    *,
    similarity_threshold: float = 0.86,
) -> tuple[list[ChunkMatch], list[str]]:
    old_chunk_by_id, old_stable_to_ids = _build_chunk_maps(old_doc)
    new_chunk_by_id, new_stable_to_ids = _build_chunk_maps(new_doc)

    warnings: list[str] = []
    matches: list[ChunkMatch] = []
    used_old: set[str] = set()
    used_new: set[str] = set()

    # 1) strong match by chunk id
    for cid in new_chunk_by_id.keys():
        if cid in old_chunk_by_id:
            matches.append(ChunkMatch(old_id=cid, new_id=cid, kind="strong", score=1.0))
            used_old.add(cid)
            used_new.add(cid)

    # 2) stable fingerprint match (possibly many-to-many)
    for stable, new_ids in new_stable_to_ids.items():
        old_ids = old_stable_to_ids.get(stable) or []
        new_ids_unmatched = [cid for cid in new_ids if cid not in used_new]
        old_ids_unmatched = [cid for cid in old_ids if cid not in used_old]
        if not new_ids_unmatched or not old_ids_unmatched:
            continue

        if len(new_ids_unmatched) == 1 and len(old_ids_unmatched) == 1:
            old_id = old_ids_unmatched[0]
            new_id = new_ids_unmatched[0]
            matches.append(ChunkMatch(old_id=old_id, new_id=new_id, kind="stable", score=1.0))
            used_old.add(old_id)
            used_new.add(new_id)
            continue

        if len(new_ids_unmatched) == len(old_ids_unmatched):
            pairs = _pair_by_range_closeness(old_ids_unmatched, new_ids_unmatched, old_chunk_by_id, new_chunk_by_id)
            for old_id, new_id in pairs:
                if old_id in used_old or new_id in used_new:
                    continue
                matches.append(ChunkMatch(old_id=old_id, new_id=new_id, kind="stable", score=1.0))
                used_old.add(old_id)
                used_new.add(new_id)
            continue

        warnings.append(
            f"Ambiguous stable match skipped (stable={stable[:12]}..., old={len(old_ids_unmatched)}, new={len(new_ids_unmatched)})"
        )

    # 3) change fingerprint match (add/delete only; ignore context)
    old_change_to_ids: dict[str, list[str]] = {}
    new_change_to_ids: dict[str, list[str]] = {}
    for cid, chunk in old_chunk_by_id.items():
        if cid in used_old:
            continue
        fp = change_fingerprint_for_chunk(chunk)
        old_change_to_ids.setdefault(fp, []).append(cid)
    for cid, chunk in new_chunk_by_id.items():
        if cid in used_new:
            continue
        fp = change_fingerprint_for_chunk(chunk)
        new_change_to_ids.setdefault(fp, []).append(cid)

    for fp, new_ids in new_change_to_ids.items():
        old_ids = old_change_to_ids.get(fp) or []
        new_ids_unmatched = [cid for cid in new_ids if cid not in used_new]
        old_ids_unmatched = [cid for cid in old_ids if cid not in used_old]
        if not new_ids_unmatched or not old_ids_unmatched:
            continue

        if len(new_ids_unmatched) == 1 and len(old_ids_unmatched) == 1:
            old_id = old_ids_unmatched[0]
            new_id = new_ids_unmatched[0]
            matches.append(ChunkMatch(old_id=old_id, new_id=new_id, kind="delta", score=1.0))
            used_old.add(old_id)
            used_new.add(new_id)
            continue

        if len(new_ids_unmatched) == len(old_ids_unmatched):
            pairs = _pair_by_range_closeness(old_ids_unmatched, new_ids_unmatched, old_chunk_by_id, new_chunk_by_id)
            for old_id, new_id in pairs:
                if old_id in used_old or new_id in used_new:
                    continue
                matches.append(ChunkMatch(old_id=old_id, new_id=new_id, kind="delta", score=1.0))
                used_old.add(old_id)
                used_new.add(new_id)
            continue

        warnings.append(
            f"Ambiguous change match skipped (fp={fp[:12]}..., old={len(old_ids_unmatched)}, new={len(new_ids_unmatched)})"
        )

    # 4) content-stable match (ignore filePath; useful for rename-only moves)
    old_content_to_ids = _build_content_stable_map(old_doc, skip_ids=used_old)
    new_content_to_ids = _build_content_stable_map(new_doc, skip_ids=used_new)
    for fp, new_ids in new_content_to_ids.items():
        old_ids = old_content_to_ids.get(fp) or []
        new_ids_unmatched = [cid for cid in new_ids if cid not in used_new]
        old_ids_unmatched = [cid for cid in old_ids if cid not in used_old]
        if not new_ids_unmatched or not old_ids_unmatched:
            continue

        if len(new_ids_unmatched) == 1 and len(old_ids_unmatched) == 1:
            old_id = old_ids_unmatched[0]
            new_id = new_ids_unmatched[0]
            matches.append(ChunkMatch(old_id=old_id, new_id=new_id, kind="stable", score=0.99))
            used_old.add(old_id)
            used_new.add(new_id)
            continue

        if len(new_ids_unmatched) == len(old_ids_unmatched):
            pairs = _pair_by_range_closeness(old_ids_unmatched, new_ids_unmatched, old_chunk_by_id, new_chunk_by_id)
            for old_id, new_id in pairs:
                if old_id in used_old or new_id in used_new:
                    continue
                matches.append(ChunkMatch(old_id=old_id, new_id=new_id, kind="stable", score=0.99))
                used_old.add(old_id)
                used_new.add(new_id)
            continue

        warnings.append(
            f"Ambiguous content-stable match skipped (fp={fp[:12]}..., old={len(old_ids_unmatched)}, new={len(new_ids_unmatched)})"
        )

    # 5) similarity match across remaining chunks; same-path gets a small bonus
    if similarity_threshold <= 0:
        return matches, warnings
    if similarity_threshold > 0.99:
        similarity_threshold = 0.99

    old_ids_remaining = [cid for cid in old_chunk_by_id.keys() if cid not in used_old]
    new_ids_remaining = [cid for cid in new_chunk_by_id.keys() if cid not in used_new]
    old_texts = {cid: _chunk_signature_text(old_chunk_by_id[cid], include_path=False) for cid in old_ids_remaining}
    candidates: list[tuple[float, str, str]] = []
    for new_id in new_ids_remaining:
        new_chunk = new_chunk_by_id[new_id]
        new_text = _chunk_signature_text(new_chunk, include_path=False)
        best_score = -1.0
        best_old_id = ""
        for old_id in old_ids_remaining:
            old_chunk = old_chunk_by_id[old_id]
            score = _similarity(old_texts[old_id], new_text)
            if str(old_chunk.get("filePath", "")) == str(new_chunk.get("filePath", "")):
                score = min(1.0, score + 0.05)
            if score > best_score:
                best_score = score
                best_old_id = old_id
        if best_score >= similarity_threshold and best_old_id:
            candidates.append((best_score, best_old_id, new_id))

    candidates.sort(key=lambda item: item[0], reverse=True)
    for score, old_id, new_id in candidates:
        if old_id in used_old or new_id in used_new:
            continue
        matches.append(ChunkMatch(old_id=old_id, new_id=new_id, kind="similar", score=float(score)))
        used_old.add(old_id)
        used_new.add(new_id)

    return matches, warnings


def _safe_copy_review_record(record: dict[str, Any]) -> dict[str, Any]:
    copied = copy.deepcopy(record)
    if not isinstance(copied, dict):
        return {}
    status = _normalize_status(copied.get("status"))
    copied["status"] = status
    return copied


def rebase_review_state(
    *,
    old_doc: dict[str, Any],
    new_doc: dict[str, Any],
    preserve_groups: bool = True,
    carry_line_comments: bool = True,
    similarity_threshold: float = 0.86,
    mark_reviewed_changed_as_needs_rereview: bool = True,
) -> tuple[dict[str, Any], RebaseSummary, list[str]]:
    new_out = copy.deepcopy(new_doc)

    matches, warnings = match_chunks(old_doc, new_doc, similarity_threshold=similarity_threshold)
    old_chunk_by_id, _ = _build_chunk_maps(old_doc)
    new_chunk_by_id, _ = _build_chunk_maps(new_doc)

    old_to_new: dict[str, ChunkMatch] = {m.old_id: m for m in matches}
    new_to_old: dict[str, ChunkMatch] = {m.new_id: m for m in matches}

    old_reviews = old_doc.get("reviews", {})
    if not isinstance(old_reviews, dict):
        old_reviews = {}

    out_reviews: dict[str, Any] = {}
    carried_reviews = 0
    carried_reviewed = 0
    changed_to_needs = 0

    for new_id, match in new_to_old.items():
        old_id = match.old_id
        old_record = old_reviews.get(old_id)
        if not isinstance(old_record, dict) or not old_record:
            continue
        record = _safe_copy_review_record(old_record)
        status_old = _normalize_status(record.get("status"))
        status_new = status_old
        if match.kind == "similar" and mark_reviewed_changed_as_needs_rereview and status_old == "reviewed":
            status_new = "needsReReview"
            record["status"] = status_new
            changed_to_needs += 1

        if carry_line_comments and match.kind in {"strong", "stable"}:
            old_chunk = old_chunk_by_id.get(old_id) or {}
            new_chunk = new_chunk_by_id.get(new_id) or {}
            remapped = _remap_line_comments_for_stable_match(old_chunk, new_chunk, old_record)
            if remapped:
                record["lineComments"] = remapped
            else:
                # If we can't remap safely, drop them to avoid wrong anchors.
                record.pop("lineComments", None)
        else:
            record.pop("lineComments", None)

        out_reviews[new_id] = record
        carried_reviews += 1
        if status_new == "reviewed":
            carried_reviewed += 1

    new_out["reviews"] = out_reviews

    out_groups = new_out.get("groups", [])
    out_assignments = new_out.get("assignments", {})
    if preserve_groups:
        out_groups = copy.deepcopy(old_doc.get("groups", []))
        # Keep every old group key even if it becomes empty after rebase.
        out_assignments = {
            str(group.get("id")): []
            for group in out_groups
            if isinstance(group, dict) and str(group.get("id", ""))
        }
        old_assignments = old_doc.get("assignments", {})
        if isinstance(old_assignments, dict):
            for group_id, chunk_ids in old_assignments.items():
                if not isinstance(chunk_ids, list):
                    continue
                for old_chunk_id in chunk_ids:
                    old_chunk_id_str = str(old_chunk_id)
                    match = old_to_new.get(old_chunk_id_str)
                    if not match:
                        continue
                    group_id_str = str(group_id)
                    if group_id_str not in out_assignments:
                        continue
                    if match.new_id not in out_assignments[group_id_str]:
                        out_assignments[group_id_str].append(match.new_id)

        # Keep only groups with valid ids; assignments keys must exist in groups.
        group_ids = {str(g.get("id")) for g in out_groups if isinstance(g, dict) and str(g.get("id", ""))}
        out_assignments = {gid: ids for gid, ids in out_assignments.items() if gid in group_ids and isinstance(ids, list)}

        old_group_briefs = old_doc.get("groupBriefs", {})
        if isinstance(old_group_briefs, dict):
            source_old = old_doc.get("meta", {}).get("source", {}) if isinstance(old_doc.get("meta"), dict) else {}
            source_new = new_doc.get("meta", {}).get("source", {}) if isinstance(new_doc.get("meta"), dict) else {}
            old_head = str(source_old.get("headSha") or source_old.get("head") or "").strip()
            new_head = str(source_new.get("headSha") or source_new.get("head") or "").strip()
            rebased_group_briefs: dict[str, Any] = {}
            for group_id in group_ids:
                brief = old_group_briefs.get(group_id)
                if not isinstance(brief, dict):
                    continue
                rebased_brief = copy.deepcopy(brief)
                if old_head and new_head and old_head != new_head:
                    rebased_brief["status"] = "stale"
                    if "approval" in rebased_brief and isinstance(rebased_brief["approval"], dict):
                        invalidation_ts = _iso_utc_now()
                        rebased_brief["approval"]["state"] = "invalidated"
                        rebased_brief["approval"]["approved"] = False
                        rebased_brief["approval"]["invalidatedAt"] = invalidation_ts
                        rebased_brief["approval"]["decisionAt"] = invalidation_ts
                        rebased_brief["approval"]["invalidationReason"] = "head_changed"
                else:
                    rebased_brief["status"] = normalize_group_brief_status(rebased_brief.get("status"), strict=True)
                rebased_group_briefs[group_id] = rebased_brief
            if rebased_group_briefs:
                new_out["groupBriefs"] = rebased_group_briefs

    old_analysis_state = old_doc.get("analysisState", {})
    if isinstance(old_analysis_state, dict):
        rebased_analysis_state = copy.deepcopy(old_analysis_state)
        current_group_id = str(rebased_analysis_state.get("currentGroupId", "")).strip()
        valid_group_ids = {
            str(group.get("id"))
            for group in out_groups
            if isinstance(group, dict) and str(group.get("id", "")).strip()
        }
        if current_group_id and current_group_id not in valid_group_ids:
            rebased_analysis_state.pop("currentGroupId", None)
        selected_chunk_id = str(rebased_analysis_state.get("selectedChunkId", "")).strip()
        if selected_chunk_id:
            match = old_to_new.get(selected_chunk_id)
            if match:
                rebased_analysis_state["selectedChunkId"] = match.new_id
            else:
                rebased_analysis_state.pop("selectedChunkId", None)
        if rebased_analysis_state:
            new_out["analysisState"] = rebased_analysis_state

    old_thread_state = old_doc.get("threadState", {})
    if isinstance(old_thread_state, dict):
        rebased_thread_state: dict[str, Any] = {}
        new_file_keys = {
            str((chunk.get("filePath", "") or "")).strip().lower()
            for chunk in new_out.get("chunks", [])
            if isinstance(chunk, dict) and str(chunk.get("filePath", "")).strip()
        }
        for key, value in old_thread_state.items():
            key_str = str(key)
            if key_str == "__files" and isinstance(value, dict):
                file_subset = {
                    str(file_key): copy.deepcopy(file_value)
                    for file_key, file_value in value.items()
                    if str(file_key).strip().lower() in new_file_keys
                }
                if file_subset:
                    rebased_thread_state[key_str] = file_subset
                continue
            if key_str == "selectedLineAnchor" and isinstance(value, dict):
                selected_old_chunk_id = ""
                analysis_state = new_out.get("analysisState", {})
                if isinstance(analysis_state, dict):
                    for old_chunk_id, match in old_to_new.items():
                        if str(analysis_state.get("selectedChunkId", "")).strip() == match.new_id:
                            selected_old_chunk_id = old_chunk_id
                            break
                if selected_old_chunk_id:
                    match = old_to_new.get(selected_old_chunk_id)
                    if match and match.kind in {"strong", "stable"}:
                        old_chunk = old_chunk_by_id.get(selected_old_chunk_id) or {}
                        new_chunk = new_chunk_by_id.get(match.new_id) or {}
                        remapped_anchor = _remap_selected_line_anchor_for_stable_match(old_chunk, new_chunk, value)
                        if remapped_anchor:
                            rebased_thread_state[key_str] = remapped_anchor
                continue
            match = old_to_new.get(key_str)
            if match:
                rebased_thread_state[match.new_id] = copy.deepcopy(value)
        if rebased_thread_state:
            new_out["threadState"] = rebased_thread_state

    new_out["groups"] = out_groups
    new_out["assignments"] = out_assignments
    new_out.setdefault("meta", {})
    new_out["meta"]["x-reviewRebase"] = {
        "matchedStrong": sum(1 for m in matches if m.kind == "strong"),
        "matchedStable": sum(1 for m in matches if m.kind == "stable"),
        "matchedDelta": sum(1 for m in matches if m.kind == "delta"),
        "matchedSimilar": sum(1 for m in matches if m.kind == "similar"),
        "carriedReviews": carried_reviews,
        "carriedReviewed": carried_reviewed,
        "changedToNeedsReReview": changed_to_needs,
        "similarityThreshold": similarity_threshold,
        "preserveGroups": bool(preserve_groups),
        "carryLineComments": bool(carry_line_comments),
    }

    matched_strong = sum(1 for m in matches if m.kind == "strong")
    matched_stable = sum(1 for m in matches if m.kind == "stable")
    matched_delta = sum(1 for m in matches if m.kind == "delta")
    matched_similar = sum(1 for m in matches if m.kind == "similar")
    unmapped_new = len(new_chunk_by_id) - len(new_to_old)

    summary = RebaseSummary(
        matched_strong=matched_strong,
        matched_stable=matched_stable,
        matched_delta=matched_delta,
        matched_similar=matched_similar,
        carried_reviews=carried_reviews,
        carried_reviewed=carried_reviewed,
        changed_to_needs_rereview=changed_to_needs,
        unmapped_new_chunks=unmapped_new,
    )
    return new_out, summary, warnings
