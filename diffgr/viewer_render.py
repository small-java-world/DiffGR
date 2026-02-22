from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def status_style(status: str) -> str:
    if status == "reviewed":
        return "green"
    if status == "needsReReview":
        return "yellow"
    if status == "ignored":
        return "dim"
    return "white"


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
    table.add_row("Source", f"{source.get('type', '-')} ({source.get('base', '-')} -> {source.get('head', '-')})")
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


def render_command_help(console: Console) -> None:
    help_table = Table(title="Commands", header_style="bold magenta")
    help_table.add_column("command", style="cyan", no_wrap=True)
    help_table.add_column("description")
    help_table.add_row("help", "Show this help.")
    help_table.add_row("list [page]", "Show chunk list. Optional page number.")
    help_table.add_row("detail <chunk_id>", "Show one chunk detail.")
    help_table.add_row("group <group_id|all>", "Set group filter.")
    help_table.add_row("status <status|all>", "Set status filter.")
    help_table.add_row("file <text|clear>", "Set filePath substring filter.")
    help_table.add_row("groups", "Show groups summary.")
    help_table.add_row("metrics", "Show dashboard again.")
    help_table.add_row("quit", "Exit application.")
    console.print(help_table)
