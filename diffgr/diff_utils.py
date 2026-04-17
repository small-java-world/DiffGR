from __future__ import annotations

from typing import Any


def normalize_line_number(value: Any) -> int | None:
    """Convert a value to an int line number, or None if not convertible."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def line_anchor_key(kind: str, old_line: Any, new_line: Any) -> str:
    """Build a stable anchor key from line kind and line numbers."""
    old_value = normalize_line_number(old_line)
    new_value = normalize_line_number(new_line)
    old_token = "" if old_value is None else str(old_value)
    new_token = "" if new_value is None else str(new_value)
    return f"{kind}:{old_token}:{new_token}"
