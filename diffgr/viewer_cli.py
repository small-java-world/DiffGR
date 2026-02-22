from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from .viewer_core import (
    VALID_STATUSES,
    build_indexes,
    compute_metrics,
    filter_chunks,
    load_json,
    resolve_input_path,
    validate_document,
)
from .viewer_render import (
    render_chunk_detail,
    render_chunks,
    render_groups,
    render_summary,
)


def parse_view_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="View DiffGR JSON in a readable terminal format.")
    parser.add_argument("path", help="Path to .diffgr.json")
    parser.add_argument("--group", help="Filter by group id")
    parser.add_argument("--chunk", help="Show detail of one chunk id")
    parser.add_argument("--status", choices=sorted(VALID_STATUSES), help="Filter by review status")
    parser.add_argument("--file", dest="file_contains", help="Filter chunks by file path substring")
    parser.add_argument("--max-lines", type=int, default=120, help="Max lines in chunk detail view")
    parser.add_argument("--show-patch", action="store_true", help="Show optional patch field")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output filtered view as JSON")
    return parser.parse_args(argv)


def run_view(argv: list[str]) -> int:
    args = parse_view_args(argv)
    path = resolve_input_path(Path(args.path), search_roots=[Path(__file__).resolve().parents[1]])
    console = Console()
    try:
        doc = load_json(path)
        warnings = validate_document(doc)
        chunk_map, status_map = build_indexes(doc)
        chunks = filter_chunks(
            doc=doc,
            chunk_map=chunk_map,
            status_map=status_map,
            group_id=args.group,
            chunk_id=args.chunk,
            status_filter=args.status,
            file_contains=args.file_contains,
        )
    except LookupError as error:
        print(f"[error] {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    if not chunks:
        print("[error] No chunks matched filters.", file=sys.stderr)
        return 2

    if args.as_json:
        payload = {
            "warnings": warnings,
            "chunks": chunks,
            "statuses": {chunk["id"]: status_map.get(chunk["id"], "unreviewed") for chunk in chunks},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    metrics = compute_metrics(doc, status_map)
    render_summary(console, doc, metrics, len(warnings))
    if warnings:
        for warning in warnings:
            console.print(f"[yellow]warning:[/yellow] {warning}")
    render_groups(console, doc)
    render_chunks(console, chunks, status_map)

    if args.chunk:
        target = chunks[0]
        render_chunk_detail(console, target, status_map.get(target["id"], "unreviewed"), args.max_lines)

    if args.show_patch and "patch" in doc:
        patch_text = str(doc["patch"]).strip()
        console.print(Panel(patch_text if patch_text else "(empty)", title="Patch", border_style="magenta"))
    return 0
