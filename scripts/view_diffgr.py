#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError as error:
    print(
        "[error] rich is required. Run: python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1) from error


VALID_STATUSES = {"unreviewed", "reviewed", "ignored", "needsReReview"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="View DiffGR JSON in a readable terminal format."
    )
    parser.add_argument("path", help="Path to .diffgr.json")
    parser.add_argument("--group", help="Filter by group id")
    parser.add_argument("--chunk", help="Show detail of one chunk id")
    parser.add_argument("--status", choices=sorted(VALID_STATUSES), help="Filter by review status")
    parser.add_argument("--file", dest="file_contains", help="Filter chunks by file path substring")
    parser.add_argument("--max-lines", type=int, default=120, help="Max lines in chunk detail view")
    parser.add_argument("--show-patch", action="store_true", help="Show optional patch field")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output filtered view as JSON")
    return parser.parse_args(argv)


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


def status_style(status: str) -> str:
    if status == "reviewed":
        return "green"
    if status == "needsReReview":
        return "yellow"
    if status == "ignored":
        return "dim"
    return "white"


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


def render_summary(
    console: Console,
    doc: dict[str, Any],
    metrics: dict[str, Any],
    warning_count: int,
) -> None:
    source = doc.get("meta", {}).get("source", {})
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("Title", str(doc.get("meta", {}).get("title", "-")))
    table.add_row("CreatedAt", str(doc.get("meta", {}).get("createdAt", "-")))
    table.add_row("Source", f"{source.get('type', '-')} ({source.get('base', '-') } -> {source.get('head', '-')})")
    table.add_row("Groups", str(len(doc.get("groups", []))))
    table.add_row("Chunks", str(len(doc.get("chunks", []))))
    table.add_row("Reviews", str(len(doc.get("reviews", {}))))
    table.add_row("Unassigned", str(metrics["Unassigned"]))
    table.add_row("Reviewed", str(metrics["Reviewed"]))
    table.add_row("Pending", str(metrics["Pending"]))
    table.add_row("Tracked", str(metrics["Tracked"]))
    table.add_row("Coverage", f"{metrics['CoverageRate'] * 100:.1f}%")
    table.add_row("Warnings", str(warning_count))
    console.print(Panel(table, title="DiffGR Summary", border_style="blue"))


def render_groups(console: Console, doc: dict[str, Any]) -> None:
    table = Table(title="Groups", header_style="bold magenta")
    table.add_column("id", style="cyan")
    table.add_column("name")
    table.add_column("order", justify="right")
    table.add_column("chunks", justify="right")
    groups = sorted(
        doc["groups"],
        key=lambda item: (
            item.get("order") is None,
            item.get("order", 0),
            item.get("name", ""),
        ),
    )
    for group in groups:
        group_id = group.get("id", "-")
        assigned = doc["assignments"].get(group_id, [])
        table.add_row(
            str(group_id),
            str(group.get("name", "-")),
            str(group.get("order", "-")),
            str(len(assigned) if isinstance(assigned, list) else 0),
        )
    console.print(table)


def render_chunks(console: Console, chunks: list[dict[str, Any]], status_map: dict[str, str]) -> None:
    table = Table(title=f"Chunks ({len(chunks)})", header_style="bold magenta")
    table.add_column("status", no_wrap=True)
    table.add_column("chunk", no_wrap=True)
    table.add_column("filePath", overflow="ellipsis")
    table.add_column("old", no_wrap=True)
    table.add_column("new", no_wrap=True)
    table.add_column("header", overflow="ellipsis")
    for chunk in chunks:
        status = status_map.get(chunk["id"], "unreviewed")
        status_text = Text(status, style=status_style(status))
        table.add_row(
            status_text,
            chunk["id"][:12],
            chunk.get("filePath", "-"),
            f"{chunk.get('old', {}).get('start', '?')},{chunk.get('old', {}).get('count', '?')}",
            f"{chunk.get('new', {}).get('start', '?')},{chunk.get('new', {}).get('count', '?')}",
            chunk.get("header", ""),
        )
    console.print(table)


def render_chunk_detail(
    console: Console,
    chunk: dict[str, Any],
    status: str,
    max_lines: int,
) -> None:
    meta = Table.grid(padding=(0, 2))
    meta.add_column(style="bold cyan")
    meta.add_column()
    meta.add_row("id", chunk["id"])
    meta.add_row("status", status)
    meta.add_row("filePath", str(chunk.get("filePath", "-")))
    meta.add_row("old", json.dumps(chunk.get("old", {}), ensure_ascii=False))
    meta.add_row("new", json.dumps(chunk.get("new", {}), ensure_ascii=False))
    meta.add_row("header", str(chunk.get("header", "")))
    if "fingerprints" in chunk:
        meta.add_row("fingerprints", json.dumps(chunk["fingerprints"], ensure_ascii=False))
    console.print(Panel(meta, title="Chunk Detail", border_style="green"))

    lines_table = Table(title=f"Lines (max {max_lines})", header_style="bold magenta")
    lines_table.add_column("old", justify="right")
    lines_table.add_column("new", justify="right")
    lines_table.add_column("kind")
    lines_table.add_column("content")
    for line in chunk.get("lines", [])[:max_lines]:
        kind = line.get("kind", "")
        prefix = {"context": " ", "add": "+", "delete": "-", "meta": "\\"}.get(kind, "?")
        style = status_style("reviewed") if kind == "add" else ("red" if kind == "delete" else "white")
        lines_table.add_row(
            str(line.get("oldLine", "")),
            str(line.get("newLine", "")),
            kind,
            Text(prefix + str(line.get("text", "")), style=style),
        )
    console.print(lines_table)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    path = Path(args.path)
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
