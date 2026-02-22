from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VALID_STATUSES = {"unreviewed", "reviewed", "ignored", "needsReReview"}


def resolve_input_path(path: Path, search_roots: list[Path] | None = None) -> Path:
    if path.is_absolute():
        return path
    primary = (Path.cwd() / path).resolve()
    if primary.exists():
        return primary
    for root in search_roots or []:
        candidate = (root / path).resolve()
        if candidate.exists():
            return candidate
    return primary


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"File not found: {path}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Invalid JSON: {error}") from error


def validate_document(doc: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    required_keys = ["format", "version", "meta", "groups", "chunks", "assignments", "reviews"]
    for key in required_keys:
        if key not in doc:
            raise RuntimeError(f"Missing required key: {key}")
    if doc["format"] != "diffgr":
        raise RuntimeError(f"Unsupported format: {doc['format']}")
    if doc["version"] != 1:
        raise RuntimeError(f"Unsupported version: {doc['version']}")

    groups = doc["groups"]
    chunks = doc["chunks"]
    assignments = doc["assignments"]
    reviews = doc["reviews"]

    group_ids = [group.get("id") for group in groups if isinstance(group, dict)]
    chunk_ids = [chunk.get("id") for chunk in chunks if isinstance(chunk, dict)]
    if len(group_ids) != len(set(group_ids)):
        warnings.append("Duplicate group ids detected.")
    if len(chunk_ids) != len(set(chunk_ids)):
        warnings.append("Duplicate chunk ids detected.")

    group_set = set(group_ids)
    chunk_set = set(chunk_ids)
    for group_id, assigned in assignments.items():
        if group_id not in group_set:
            warnings.append(f"Assignment key not in groups: {group_id}")
        if not isinstance(assigned, list):
            warnings.append(f"Assignment value must be array: {group_id}")
            continue
        for chunk_id in assigned:
            if chunk_id not in chunk_set:
                warnings.append(f"Assigned chunk id not found: {chunk_id}")

    for chunk_id in reviews.keys():
        if chunk_id not in chunk_set:
            warnings.append(f"Review key chunk id not found: {chunk_id}")
    return warnings


def build_indexes(doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    chunk_map = {chunk["id"]: chunk for chunk in doc["chunks"]}
    status_map: dict[str, str] = {}
    for chunk_id in chunk_map.keys():
        status = doc["reviews"].get(chunk_id, {}).get("status", "unreviewed")
        if status not in VALID_STATUSES:
            status = "unreviewed"
        status_map[chunk_id] = status
    return chunk_map, status_map


def compute_metrics(doc: dict[str, Any], status_map: dict[str, str]) -> dict[str, Any]:
    chunk_ids = {chunk["id"] for chunk in doc["chunks"]}
    assigned: set[str] = set()
    for values in doc["assignments"].values():
        if isinstance(values, list):
            assigned.update(values)
    unassigned = chunk_ids - assigned
    ignored = {chunk_id for chunk_id, status in status_map.items() if status == "ignored"}
    tracked = chunk_ids - ignored
    reviewed = {chunk_id for chunk_id in tracked if status_map.get(chunk_id) == "reviewed"}
    pending = {
        chunk_id
        for chunk_id in tracked
        if status_map.get(chunk_id) in {"unreviewed", "needsReReview"}
    }
    tracked_count = len(tracked)
    coverage_rate = 1.0 if tracked_count == 0 else len(reviewed) / tracked_count
    return {
        "Unassigned": len(unassigned),
        "Reviewed": len(reviewed),
        "Pending": len(pending),
        "Tracked": tracked_count,
        "CoverageRate": coverage_rate,
    }


def filter_chunks(
    doc: dict[str, Any],
    chunk_map: dict[str, Any],
    status_map: dict[str, str],
    group_id: str | None,
    chunk_id: str | None,
    status_filter: str | None,
    file_contains: str | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]]
    if group_id:
        assigned = doc["assignments"].get(group_id)
        if assigned is None:
            raise LookupError(f"Group not found in assignments: {group_id}")
        candidates = [chunk_map[item] for item in assigned if item in chunk_map]
    else:
        candidates = list(chunk_map.values())

    if chunk_id:
        candidates = [item for item in candidates if item.get("id") == chunk_id]
    if status_filter:
        candidates = [item for item in candidates if status_map.get(item["id"]) == status_filter]
    if file_contains:
        lookup = file_contains.lower()
        candidates = [item for item in candidates if lookup in item.get("filePath", "").lower()]
    return candidates
