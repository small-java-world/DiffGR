from __future__ import annotations

import copy
import re
from typing import Any

from diffgr.group_utils import ordered_groups as _ordered_groups
from diffgr.review_state import merge_review_states, normalize_review_state_payload
from diffgr.viewer_core import build_chunk_map


def _safe_token(value: str, *, fallback: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip())
    token = re.sub(r"-{2,}", "-", token).strip("-")
    return token or fallback


def build_group_output_filename(index: int, group_id: str, group_name: str) -> str:
    group_id_token = _safe_token(group_id, fallback=f"g{index:02d}")
    group_name_token = _safe_token(group_name, fallback="group")
    return f"{index:02d}-{group_id_token}-{group_name_token}.diffgr.json"


def build_group_review_document(doc: dict[str, Any], group_id: str) -> dict[str, Any]:
    chunk_map = build_chunk_map(doc)
    assigned = doc.get("assignments", {}).get(group_id, [])
    assigned_ids = [str(chunk_id) for chunk_id in assigned if str(chunk_id) in chunk_map]

    groups = [group for group in doc.get("groups", []) if isinstance(group, dict) and group.get("id") == group_id]
    group_name = str(groups[0].get("name", group_id)) if groups else group_id
    group_block = groups[0] if groups else {"id": group_id, "name": group_name, "order": 1}

    base_meta = copy.deepcopy(doc.get("meta", {})) if isinstance(doc.get("meta"), dict) else {}
    source_title = str(base_meta.get("title", "DiffGR"))
    base_meta["title"] = f"{source_title} [{group_name}]"
    base_meta["x-reviewSplit"] = {
        "groupId": group_id,
        "groupName": group_name,
        "chunkCount": len(assigned_ids),
    }

    reviews = doc.get("reviews", {})
    review_subset: dict[str, Any] = {}
    if isinstance(reviews, dict):
        for chunk_id in assigned_ids:
            review = reviews.get(chunk_id)
            if isinstance(review, dict):
                review_subset[chunk_id] = copy.deepcopy(review)

    group_briefs = doc.get("groupBriefs", {})
    brief_subset: dict[str, Any] = {}
    if isinstance(group_briefs, dict):
        brief = group_briefs.get(group_id)
        if isinstance(brief, dict):
            brief_subset[group_id] = copy.deepcopy(brief)

    analysis_state = doc.get("analysisState", {})
    analysis_subset: dict[str, Any] = {}
    if isinstance(analysis_state, dict):
        analysis_subset = copy.deepcopy(analysis_state)
        analysis_subset["currentGroupId"] = group_id
        selected_chunk_id = str(analysis_subset.get("selectedChunkId", "")).strip()
        if selected_chunk_id and selected_chunk_id not in assigned_ids:
            analysis_subset.pop("selectedChunkId", None)

    thread_state = doc.get("threadState", {})
    thread_subset: dict[str, Any] = {}
    if isinstance(thread_state, dict):
        allowed_file_keys = {
            str((chunk_map[chunk_id].get("filePath", "") or "")).strip().lower()
            for chunk_id in assigned_ids
            if chunk_id in chunk_map
        }
        for key, value in thread_state.items():
            if key in assigned_ids:
                thread_subset[key] = copy.deepcopy(value)
                continue
            if key == "__files" and isinstance(value, dict):
                file_subset = {
                    file_key: copy.deepcopy(file_value)
                    for file_key, file_value in value.items()
                    if str(file_key).strip().lower() in allowed_file_keys
                }
                if file_subset:
                    thread_subset[key] = file_subset
                continue
            if key == "selectedLineAnchor" and isinstance(value, dict):
                selected_chunk_id = str(analysis_subset.get("selectedChunkId", "")).strip()
                if selected_chunk_id and selected_chunk_id in assigned_ids:
                    thread_subset[key] = copy.deepcopy(value)

    return {
        "format": "diffgr",
        "version": 1,
        "meta": base_meta,
        "groups": [copy.deepcopy(group_block)],
        "chunks": [copy.deepcopy(chunk_map[chunk_id]) for chunk_id in assigned_ids],
        "assignments": {group_id: list(assigned_ids)},
        "reviews": review_subset,
        "groupBriefs": brief_subset,
        "analysisState": analysis_subset,
        "threadState": thread_subset,
    }


def split_document_by_group(doc: dict[str, Any], *, include_empty: bool = False) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    outputs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    assignments = doc.get("assignments", {})
    for group in _ordered_groups(doc):
        group_id = str(group.get("id", ""))
        if not group_id:
            continue
        assigned = assignments.get(group_id, [])
        has_chunk = isinstance(assigned, list) and len(assigned) > 0
        if not include_empty and not has_chunk:
            continue
        outputs.append((group, build_group_review_document(doc, group_id)))
    return outputs


def _merge_analysis_state_records(base_record: dict[str, Any], incoming_record: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base_record)
    for key, value in incoming_record.items():
        merged[key] = copy.deepcopy(value)
    return merged


def _merge_thread_state_records(base_record: dict[str, Any], incoming_record: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base_record)
    for key, value in incoming_record.items():
        if key == "__files" and isinstance(value, dict):
            existing = merged.get("__files", {})
            if not isinstance(existing, dict):
                existing = {}
            for file_key, file_value in value.items():
                existing[str(file_key)] = copy.deepcopy(file_value)
            merged["__files"] = existing
            continue
        merged[str(key)] = copy.deepcopy(value)
    return merged


def merge_reviews_into_base(
    base_doc: dict[str, Any],
    review_docs: list[tuple[str, dict[str, Any]]],
    *,
    clear_base_reviews: bool = False,
    strict: bool = False,
) -> tuple[dict[str, Any], list[str], int]:
    merged = copy.deepcopy(base_doc)
    base_state = normalize_review_state_payload(
        {
            "reviews": {} if clear_base_reviews else merged.get("reviews", {}),
            "groupBriefs": merged.get("groupBriefs", {}),
            "analysisState": merged.get("analysisState", {}),
            "threadState": merged.get("threadState", {}),
        }
    )

    chunk_ids = {
        str(chunk.get("id"))
        for chunk in merged.get("chunks", [])
        if isinstance(chunk, dict) and str(chunk.get("id", ""))
    }
    group_ids = {
        str(group.get("id"))
        for group in merged.get("groups", [])
        if isinstance(group, dict) and str(group.get("id", ""))
    }
    file_keys = {
        str((chunk.get("filePath", "") or "")).strip().lower()
        for chunk in merged.get("chunks", [])
        if isinstance(chunk, dict) and str(chunk.get("filePath", "")).strip()
    }

    warnings: list[str] = []
    filtered_review_states: list[tuple[str, dict[str, Any]]] = []
    for source_name, review_doc in review_docs:
        filtered_state = {
            "reviews": {},
            "groupBriefs": {},
            "analysisState": {},
            "threadState": {},
        }
        reviews = review_doc.get("reviews", {})
        if not isinstance(reviews, dict):
            message = f"{source_name}: `reviews` must be object."
            if strict:
                raise RuntimeError(message)
            warnings.append(message)
            continue
        for chunk_id, review_record in reviews.items():
            chunk_id_str = str(chunk_id)
            if chunk_id_str not in chunk_ids:
                message = f"{source_name}: unknown chunk id in reviews: {chunk_id_str}"
                if strict:
                    raise RuntimeError(message)
                warnings.append(message)
                continue
            if not isinstance(review_record, dict):
                message = f"{source_name}: review record must be object for chunk: {chunk_id_str}"
                if strict:
                    raise RuntimeError(message)
                warnings.append(message)
                continue
            filtered_state["reviews"][chunk_id_str] = copy.deepcopy(review_record)

        group_briefs = review_doc.get("groupBriefs", {})
        if group_briefs is None:
            group_briefs = {}
        if not isinstance(group_briefs, dict):
            message = f"{source_name}: `groupBriefs` must be object."
            if strict:
                raise RuntimeError(message)
            warnings.append(message)
            continue
        for group_id, brief_record in group_briefs.items():
            group_id_str = str(group_id)
            if group_id_str not in group_ids:
                message = f"{source_name}: unknown group id in groupBriefs: {group_id_str}"
                if strict:
                    raise RuntimeError(message)
                warnings.append(message)
                continue
            if not isinstance(brief_record, dict):
                message = f"{source_name}: group brief record must be object for group: {group_id_str}"
                if strict:
                    raise RuntimeError(message)
                warnings.append(message)
                continue
            filtered_state["groupBriefs"][group_id_str] = copy.deepcopy(brief_record)

        analysis_state = review_doc.get("analysisState", {})
        if analysis_state is None:
            analysis_state = {}
        if not isinstance(analysis_state, dict):
            message = f"{source_name}: `analysisState` must be object."
            if strict:
                raise RuntimeError(message)
            warnings.append(message)
        else:
            filtered_analysis_state: dict[str, Any] = {}
            for key, value in analysis_state.items():
                if key == "currentGroupId":
                    group_id = str(value or "").strip()
                    if group_id and group_id in group_ids:
                        filtered_analysis_state[key] = group_id
                    continue
                if key == "selectedChunkId":
                    chunk_id = str(value or "").strip()
                    if chunk_id and chunk_id in chunk_ids:
                        filtered_analysis_state[key] = chunk_id
                    continue
                filtered_analysis_state[key] = copy.deepcopy(value)
            if filtered_analysis_state:
                filtered_state["analysisState"] = filtered_analysis_state

        thread_state = review_doc.get("threadState", {})
        if thread_state is None:
            thread_state = {}
        if not isinstance(thread_state, dict):
            message = f"{source_name}: `threadState` must be object."
            if strict:
                raise RuntimeError(message)
            warnings.append(message)
            continue
        filtered_thread_state: dict[str, Any] = {}
        for key, value in thread_state.items():
            key_str = str(key)
            if key_str in chunk_ids:
                filtered_thread_state[key_str] = copy.deepcopy(value)
                continue
            if key_str == "__files" and isinstance(value, dict):
                file_subset = {
                    str(file_key): copy.deepcopy(file_value)
                    for file_key, file_value in value.items()
                    if str(file_key).strip().lower() in file_keys
                }
                if file_subset:
                    filtered_thread_state[key_str] = file_subset
                continue
            if key_str == "selectedLineAnchor" and isinstance(value, dict):
                filtered_thread_state[key_str] = copy.deepcopy(value)
        if filtered_thread_state:
            filtered_state["threadState"] = filtered_thread_state
        filtered_review_states.append((source_name, filtered_state))

    merged_state, merge_warnings, applied = merge_review_states(base_state, filtered_review_states)
    warnings.extend(merge_warnings)
    for key, value in merged_state.items():
        if key == "reviews" or value:
            merged[key] = value
        else:
            merged.pop(key, None)
    return merged, warnings, applied
