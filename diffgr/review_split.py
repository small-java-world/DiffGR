from __future__ import annotations

import copy
import re
from typing import Any


def _safe_token(value: str, *, fallback: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip())
    token = re.sub(r"-{2,}", "-", token).strip("-")
    return token or fallback


def build_group_output_filename(index: int, group_id: str, group_name: str) -> str:
    group_id_token = _safe_token(group_id, fallback=f"g{index:02d}")
    group_name_token = _safe_token(group_name, fallback="group")
    return f"{index:02d}-{group_id_token}-{group_name_token}.diffgr.json"


def _ordered_groups(doc: dict[str, Any]) -> list[dict[str, Any]]:
    groups = [group for group in doc.get("groups", []) if isinstance(group, dict)]
    groups.sort(
        key=lambda item: (
            item.get("order") is None,
            item.get("order", 0),
            str(item.get("name", "")),
            str(item.get("id", "")),
        )
    )
    return groups


def build_group_review_document(doc: dict[str, Any], group_id: str) -> dict[str, Any]:
    chunk_map = {
        str(chunk.get("id")): chunk
        for chunk in doc.get("chunks", [])
        if isinstance(chunk, dict) and str(chunk.get("id", ""))
    }
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

    return {
        "format": "diffgr",
        "version": 1,
        "meta": base_meta,
        "groups": [copy.deepcopy(group_block)],
        "chunks": [copy.deepcopy(chunk_map[chunk_id]) for chunk_id in assigned_ids],
        "assignments": {group_id: list(assigned_ids)},
        "reviews": review_subset,
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


def merge_reviews_into_base(
    base_doc: dict[str, Any],
    review_docs: list[tuple[str, dict[str, Any]]],
    *,
    clear_base_reviews: bool = False,
    strict: bool = False,
) -> tuple[dict[str, Any], list[str], int]:
    merged = copy.deepcopy(base_doc)
    base_reviews = {} if clear_base_reviews else copy.deepcopy(merged.get("reviews", {}))
    if not isinstance(base_reviews, dict):
        base_reviews = {}
    merged["reviews"] = base_reviews

    chunk_ids = {
        str(chunk.get("id"))
        for chunk in merged.get("chunks", [])
        if isinstance(chunk, dict) and str(chunk.get("id", ""))
    }

    warnings: list[str] = []
    applied = 0
    for source_name, review_doc in review_docs:
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
            base_reviews[chunk_id_str] = copy.deepcopy(review_record)
            applied += 1
    return merged, warnings, applied
