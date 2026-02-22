from __future__ import annotations

from typing import Any


def apply_slice_patch(doc: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    rename: dict[str, str] = patch.get("rename") or {}
    moves: list[dict[str, Any]] = patch.get("move") or []

    groups: list[dict[str, Any]] = doc.get("groups") or []
    chunks: list[dict[str, Any]] = doc.get("chunks") or []
    assignments: dict[str, list[str]] = doc.get("assignments") or {}

    group_ids = {g.get("id") for g in groups if isinstance(g, dict)}
    chunk_ids = {c.get("id") for c in chunks if isinstance(c, dict)}

    for group in groups:
        group_id = group.get("id")
        if not group_id or group_id not in rename:
            continue
        group["name"] = rename[group_id]

    def remove_from_all(chunk_id: str) -> None:
        for group_id, ids in list(assignments.items()):
            if not isinstance(ids, list):
                continue
            if chunk_id in ids:
                assignments[group_id] = [value for value in ids if value != chunk_id]
            if assignments.get(group_id) == []:
                # keep file compact; empty groups can exist in groups[] without an assignments entry
                assignments.pop(group_id, None)

    for move in moves:
        chunk_id = move.get("chunk")
        to_group = move.get("to")
        if not chunk_id or not to_group:
            continue
        if to_group not in group_ids:
            raise RuntimeError(f"Unknown group id in move: {to_group}")
        if chunk_id not in chunk_ids:
            raise RuntimeError(f"Unknown chunk id in move: {chunk_id}")
        remove_from_all(chunk_id)
        assignments.setdefault(to_group, [])
        if chunk_id not in assignments[to_group]:
            assignments[to_group].append(chunk_id)

    doc["groups"] = groups
    doc["assignments"] = assignments
    doc.setdefault("meta", {})
    doc["meta"]["x-slicePatch"] = {"renameCount": len(rename), "moveCount": len(moves)}
    return doc

