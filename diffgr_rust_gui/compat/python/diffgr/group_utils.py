from __future__ import annotations

from typing import Any


def group_sort_key(group: dict[str, Any]) -> tuple:
    """Sort key for groups: order (None last), then name, then id."""
    return (
        group.get("order") is None,
        group.get("order", 0),
        str(group.get("name", "")),
        str(group.get("id", "")),
    )


def safe_groups(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Return groups from a document, filtering out non-dict entries."""
    return [group for group in (doc.get("groups") or []) if isinstance(group, dict)]


def ordered_groups(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Return groups from a document sorted by group_sort_key."""
    groups = safe_groups(doc)
    groups.sort(key=group_sort_key)
    return groups


def chunk_change_preview(chunk: dict[str, Any], *, max_lines: int = 6, include_meta: bool = False) -> str:
    """Build a short text preview of changed lines in a chunk.

    When include_meta is False (default), only add/delete lines are shown.
    When include_meta is True, all non-context lines are shown (add, delete, meta, etc.).
    """
    lines: list[str] = []
    for ln in chunk.get("lines") or []:
        kind = ln.get("kind")
        if include_meta:
            if not kind or kind == "context":
                continue
        else:
            if kind not in {"add", "delete"}:
                continue
        text = str(ln.get("text", ""))
        if kind in {"add", "delete"} and text.strip() == "":
            continue
        lines.append(f"{kind}: {text}")
        if len(lines) >= max_lines:
            break
    if not lines:
        return "(meta-only)" if include_meta else "(no add/delete lines)"
    return " / ".join(lines)
