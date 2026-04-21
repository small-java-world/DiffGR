#!/usr/bin/env python3
"""Apply AI-generated layout (groups, assignments, groupBriefs) to a DiffGR JSON.

Typical usage:
    python3 scripts/apply_diffgr_layout.py \\
        --input pr.diffgr.json \\
        --layout layout.json \\
        --output pr.diffgr.json

The layout JSON may contain any combination of:
    - groups[]           : group definitions (replaces existing groups)
    - assignments{}      : chunk-id lists per group (replaces existing assignments)
    - groupBriefs{}      : Review Handoff per group (merged into review state)
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.viewer_core import load_json, print_error, validate_document, write_json  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply AI-generated layout (groups/assignments/groupBriefs) to a DiffGR JSON."
    )
    parser.add_argument("--input", required=True, help="Input DiffGR JSON path.")
    parser.add_argument("--layout", required=True, help="Layout JSON path (AI output).")
    parser.add_argument("--output", required=True, help="Output DiffGR JSON path.")
    return parser.parse_args(argv)


def _normalize_group(raw: object, order: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"Each group must be a JSON object, got: {type(raw)}")
    gid = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not gid:
        raise ValueError(f"Group missing 'id': {raw}")
    if not name:
        raise ValueError(f"Group '{gid}' missing 'name'")
    raw_tags = raw.get("tags")
    if raw_tags is None:
        tags: list[str] = []
    elif not isinstance(raw_tags, list):
        raise ValueError(f"Group '{gid}' field 'tags' must be a JSON array, got: {type(raw_tags)}")
    else:
        tags = [str(t) for t in raw_tags]
    return {
        "id": gid,
        "name": name,
        "order": int(raw.get("order") or order),
        "tags": tags,
    }


def apply_layout(doc: dict, layout: dict) -> tuple[dict, list[str]]:
    """Return (updated_doc, warnings)."""
    out = copy.deepcopy(doc)
    warnings: list[str] = []

    known_chunk_ids: set[str] = {str(c["id"]) for c in (out.get("chunks") or []) if "id" in c}

    # --- groups ---
    raw_groups = layout.get("groups")
    if raw_groups is not None:
        if not isinstance(raw_groups, list):
            raise ValueError("'groups' must be a JSON array.")
        normalized: list[dict] = []
        seen_ids: set[str] = set()
        for i, raw in enumerate(raw_groups):
            g = _normalize_group(raw, order=i + 1)
            if g["id"] in seen_ids:
                raise ValueError(f"Duplicate group id: {g['id']}")
            seen_ids.add(g["id"])
            normalized.append(g)
        out["groups"] = normalized
        # Prune stale references from assignments and groupBriefs
        valid_group_ids = {g["id"] for g in normalized}
        if isinstance(out.get("assignments"), dict):
            out["assignments"] = {
                str(gid): list(ids)
                for gid, ids in out["assignments"].items()
                if str(gid) in valid_group_ids and isinstance(ids, list)
            }
        if isinstance(out.get("groupBriefs"), dict):
            out["groupBriefs"] = {
                str(gid): brief
                for gid, brief in out["groupBriefs"].items()
                if str(gid) in valid_group_ids
            }

    # --- assignments ---
    raw_assignments = layout.get("assignments")
    if raw_assignments is not None:
        if not isinstance(raw_assignments, dict):
            raise ValueError("'assignments' must be a JSON object.")
        group_ids = {g["id"] for g in (out.get("groups") or [])}
        new_assignments: dict[str, list[str]] = {}
        assigned: set[str] = set()
        for gid, chunk_ids in raw_assignments.items():
            if not isinstance(chunk_ids, list):
                raise ValueError(f"assignments['{gid}'] must be a list.")
            if gid not in group_ids:
                warnings.append(f"assignments references unknown group '{gid}' — skipped")
                continue
            valid: list[str] = []
            for cid in chunk_ids:
                cid_str = str(cid)
                if cid_str not in known_chunk_ids:
                    warnings.append(f"assignments['{gid}'] references unknown chunk '{cid_str[:16]}…' — skipped")
                    continue
                if cid_str in assigned:
                    warnings.append(f"Chunk '{cid_str[:16]}…' assigned to multiple groups — keeping first")
                    continue
                assigned.add(cid_str)
                valid.append(cid_str)
            if valid:
                new_assignments[gid] = valid
        unassigned = known_chunk_ids - assigned
        if unassigned:
            warnings.append(f"{len(unassigned)} chunk(s) not assigned to any group")
        out["assignments"] = new_assignments

    # --- groupBriefs ---
    raw_briefs = layout.get("groupBriefs")
    if raw_briefs is not None:
        if not isinstance(raw_briefs, dict):
            raise ValueError("'groupBriefs' must be a JSON object.")
        existing = copy.deepcopy(out.get("groupBriefs")) if isinstance(out.get("groupBriefs"), dict) else {}
        for gid, brief in raw_briefs.items():
            if not isinstance(brief, dict):
                raise ValueError(f"groupBriefs['{gid}'] must be a JSON object.")
            base = existing.get(gid) if isinstance(existing.get(gid), dict) else {}
            existing[str(gid)] = {**base, **brief}
        out["groupBriefs"] = existing

    return out, warnings


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    layout_path = Path(args.layout)
    if not layout_path.is_absolute():
        layout_path = ROOT / layout_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    try:
        doc = load_json(input_path)
        validate_document(doc)
        layout_raw = load_json(layout_path)
        out, warnings = apply_layout(doc, layout_raw)
        for w in warnings:
            print(f"[warn] {w}", file=sys.stderr)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(output_path, out)
        print(f"Wrote: {output_path}")
        groups_applied = "groups" in layout_raw
        assignments_applied = "assignments" in layout_raw
        briefs_applied = "groupBriefs" in layout_raw
        applied = [k for k, v in [("groups", groups_applied), ("assignments", assignments_applied), ("groupBriefs", briefs_applied)] if v]
        print(f"Applied: {', '.join(applied)}")
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
