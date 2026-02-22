from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Prompt

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
    render_command_help,
    render_groups,
    render_summary,
)


def parse_app_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive DiffGR viewer application.")
    parser.add_argument("path", help="Path to .diffgr.json")
    parser.add_argument("--page-size", type=int, default=15, help="Number of chunks per list page (default: 15).")
    parser.add_argument("--once", action="store_true", help="Print dashboard and first page only, then exit.")
    parser.add_argument(
        "--ui",
        choices=["textual", "prompt"],
        default="textual",
        help="Viewer mode (default: textual).",
    )
    return parser.parse_args(argv)


def render_chunks_page(
    console: Console,
    chunks: list[dict[str, Any]],
    status_map: dict[str, str],
    page: int,
    page_size: int,
) -> None:
    total = len(chunks)
    if total == 0:
        console.print("[yellow]No chunks matched current filters.[/yellow]")
        return
    max_page = (total - 1) // page_size + 1
    page = max(1, min(page, max_page))
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    render_chunks(console, chunks[start:end], status_map)
    console.print(f"[cyan]Page {page}/{max_page}[/cyan]  showing {start + 1}-{end} of {total}")


def run_prompt_app(
    console: Console,
    doc: dict[str, Any],
    warnings: list[str],
    chunk_map: dict[str, Any],
    status_map: dict[str, str],
    page_size: int,
) -> int:
    active_group: str | None = None
    active_status: str | None = None
    active_file: str | None = None

    def get_filtered_chunks() -> list[dict[str, Any]]:
        return filter_chunks(
            doc=doc,
            chunk_map=chunk_map,
            status_map=status_map,
            group_id=active_group,
            chunk_id=None,
            status_filter=active_status,
            file_contains=active_file,
        )

    metrics = compute_metrics(doc, status_map)
    render_summary(console, doc, metrics, len(warnings))
    if warnings:
        for warning in warnings:
            console.print(f"[yellow]warning:[/yellow] {warning}")
    render_chunks_page(console, get_filtered_chunks(), status_map, page=1, page_size=page_size)
    render_command_help(console)

    while True:
        command_line = Prompt.ask("[bold green]diffgr>[/bold green]").strip()
        if not command_line:
            continue
        parts = command_line.split(maxsplit=1)
        command = parts[0].lower()
        value = parts[1].strip() if len(parts) > 1 else ""

        if command in {"quit", "exit"}:
            return 0
        if command == "help":
            render_command_help(console)
            continue
        if command == "groups":
            render_groups(console, doc)
            continue
        if command == "metrics":
            metrics = compute_metrics(doc, status_map)
            render_summary(console, doc, metrics, len(warnings))
            continue
        if command == "group":
            if not value or value == "all":
                active_group = None
            elif value in doc.get("assignments", {}):
                active_group = value
            else:
                console.print(f"[red]Unknown group in assignments: {value}[/red]")
                continue
            render_chunks_page(console, get_filtered_chunks(), status_map, page=1, page_size=page_size)
            continue
        if command == "status":
            if not value or value == "all":
                active_status = None
            elif value in VALID_STATUSES:
                active_status = value
            else:
                console.print(f"[red]Invalid status: {value}[/red]")
                continue
            render_chunks_page(console, get_filtered_chunks(), status_map, page=1, page_size=page_size)
            continue
        if command == "file":
            active_file = None if not value or value == "clear" else value
            render_chunks_page(console, get_filtered_chunks(), status_map, page=1, page_size=page_size)
            continue
        if command == "list":
            page = 1
            if value:
                try:
                    page = int(value)
                except ValueError:
                    console.print(f"[red]Invalid page: {value}[/red]")
                    continue
            render_chunks_page(console, get_filtered_chunks(), status_map, page=page, page_size=page_size)
            continue
        if command == "detail":
            if not value:
                console.print("[red]Usage: detail <chunk_id>[/red]")
                continue
            chunk = chunk_map.get(value)
            if chunk is None:
                console.print(f"[red]Chunk not found: {value}[/red]")
                continue
            status = status_map.get(value, "unreviewed")
            render_chunk_detail(console, chunk, status, max_lines=200)
            continue

        console.print(f"[red]Unknown command: {command}[/red]")
        render_command_help(console)


def run_textual_app(
    doc: dict[str, Any],
    warnings: list[str],
    chunk_map: dict[str, Any],
    status_map: dict[str, str],
    page_size: int,
    source_path: Path,
) -> int:
    try:
        from .viewer_textual import launch_textual_viewer
    except Exception as error:  # noqa: BLE001
        print(
            f"[error] textual UI is unavailable: {error}. "
            "Install dependencies: python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1
    return launch_textual_viewer(doc, warnings, chunk_map, status_map, page_size, source_path)


def run_app(argv: list[str]) -> int:
    args = parse_app_args(argv)
    if args.page_size < 1:
        print("[error] --page-size must be >= 1", file=sys.stderr)
        return 2

    console = Console()
    path = resolve_input_path(Path(args.path), search_roots=[Path(__file__).resolve().parents[1]])
    try:
        doc = load_json(path)
        warnings = validate_document(doc)
        chunk_map, status_map = build_indexes(doc)
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    if args.once:
        metrics = compute_metrics(doc, status_map)
        render_summary(console, doc, metrics, len(warnings))
        if warnings:
            for warning in warnings:
                console.print(f"[yellow]warning:[/yellow] {warning}")
        filtered = filter_chunks(
            doc=doc,
            chunk_map=chunk_map,
            status_map=status_map,
            group_id=None,
            chunk_id=None,
            status_filter=None,
            file_contains=None,
        )
        render_chunks_page(console, filtered, status_map, page=1, page_size=args.page_size)
        return 0

    if args.ui == "prompt":
        return run_prompt_app(console, doc, warnings, chunk_map, status_map, args.page_size)
    return run_textual_app(doc, warnings, chunk_map, status_map, args.page_size, path)
