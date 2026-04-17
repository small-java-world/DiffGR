from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Prompt

from diffgr.diff_utils import line_anchor_key as _line_anchor_key

from .review_state import (
    apply_review_state_selection,
    apply_review_state,
    diff_review_states,
    extract_review_state,
    load_review_state,
    parse_review_state_selection,
    preview_review_state_selection,
    preview_merge_review_states,
    save_review_state,
    summarize_merge_result,
    summarize_review_state,
)
from .impact_merge import build_impact_preview_report, preview_impact_apply, preview_impact_merge
from .viewer_core import (
    VALID_STATUSES,
    build_indexes,
    compute_metrics,
    filter_chunks,
    load_json,
    resolve_input_path,
    validate_document,
    write_json,
)
from .group_brief_utils import VALID_GROUP_BRIEF_STATUSES
from .viewer_render import (
    render_chunk_detail,
    render_chunks,
    render_command_help,
    render_group_brief_detail,
    render_groups,
    render_impact_preview,
    render_merge_summary,
    render_state_diff,
    render_state_summary,
    render_summary,
)

VALID_STATE_SELECTION_PREFIXES = ("reviews:", "groupBriefs:", "analysisState:", "threadState:", "threadState.__files:")
VALID_GROUP_BRIEF_META_FIELDS = {"updatedAt", "sourceHead"}
VALID_GROUP_BRIEF_LIST_FIELDS = {
    "focus": "focusPoints",
    "focusPoints": "focusPoints",
    "evidence": "testEvidence",
    "testEvidence": "testEvidence",
    "tradeoff": "knownTradeoffs",
    "knownTradeoffs": "knownTradeoffs",
    "question": "questionsForReviewer",
    "questionsForReviewer": "questionsForReviewer",
}


class _PromptOutputPath:
    def __init__(self, path: Path) -> None:
        self._path = path

    def __fspath__(self) -> str:
        return str(self._path)

    def __str__(self) -> str:
        return self._path.as_posix()

    def __repr__(self) -> str:
        return repr(self._path)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _PromptOutputPath):
            return self._path == other._path
        return self._path == other

    def __hash__(self) -> int:
        return hash(self._path)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._path, name)


def _split_prompt_args(raw_value: str) -> list[str]:
    items = [item for item in shlex.split(raw_value.strip(), posix=(sys.platform != "win32")) if item]
    normalized: list[str] = []
    for item in items:
        if len(item) >= 2 and item[0] == item[-1] and item[0] in {'"', "'"}:
            normalized.append(item[1:-1])
        else:
            normalized.append(item)
    return normalized


def _ensure_chunk_review(doc: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    reviews = doc.setdefault("reviews", {})
    record = reviews.get(chunk_id)
    if not isinstance(record, dict):
        record = {}
        reviews[chunk_id] = record
    return record


def _prune_chunk_review(doc: dict[str, Any], chunk_id: str) -> None:
    reviews = doc.get("reviews")
    if not isinstance(reviews, dict):
        return
    record = reviews.get(chunk_id)
    if not isinstance(record, dict):
        reviews.pop(chunk_id, None)
        return
    line_comments = record.get("lineComments")
    if isinstance(line_comments, list) and line_comments:
        return
    if str(record.get("status", "")).strip():
        return
    if str(record.get("comment", "")).strip():
        return
    reviews.pop(chunk_id, None)


def _set_chunk_status(doc: dict[str, Any], status_map: dict[str, str], chunk_id: str, status: str) -> None:
    status_map[chunk_id] = status
    if status == "unreviewed":
        reviews = doc.get("reviews")
        if isinstance(reviews, dict):
            record = reviews.get(chunk_id)
            if isinstance(record, dict):
                record.pop("status", None)
        _prune_chunk_review(doc, chunk_id)
        return
    record = _ensure_chunk_review(doc, chunk_id)
    record["status"] = status


def _set_chunk_comment(doc: dict[str, Any], chunk_id: str, comment: str) -> None:
    normalized = comment.strip()
    if not normalized:
        reviews = doc.get("reviews")
        if isinstance(reviews, dict):
            record = reviews.get(chunk_id)
            if isinstance(record, dict):
                record.pop("comment", None)
        _prune_chunk_review(doc, chunk_id)
        return
    record = _ensure_chunk_review(doc, chunk_id)
    record["comment"] = normalized


def _parse_line_number_token(raw: str) -> int | None:
    token = str(raw or "").strip()
    if token in {"", "-", "none", "null"}:
        return None
    value = int(token)
    if value < 1:
        raise ValueError("line numbers must be >= 1")
    return value


def _set_line_comment(
    doc: dict[str, Any],
    chunk_id: str,
    *,
    old_line: int | None,
    new_line: int | None,
    line_type: str,
    comment: str,
) -> None:
    normalized = comment.strip()
    record = _ensure_chunk_review(doc, chunk_id)
    raw_items = record.get("lineComments")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    kept: list[dict[str, Any]] = []
    found = False
    for item in items:
        if (
            item.get("oldLine") == old_line
            and item.get("newLine") == new_line
            and str(item.get("lineType", "")) == line_type
        ):
            found = True
            if normalized:
                kept.append(
                    {
                        "oldLine": old_line,
                        "newLine": new_line,
                        "lineType": line_type,
                        "comment": normalized,
                    }
                )
            continue
        kept.append(item)
    if normalized and not found:
        kept.append(
            {
                "oldLine": old_line,
                "newLine": new_line,
                "lineType": line_type,
                "comment": normalized,
            }
        )
    if kept:
        record["lineComments"] = kept
    else:
        record.pop("lineComments", None)
    thread_state = doc.setdefault("threadState", {})
    if not isinstance(thread_state, dict):
        thread_state = {}
        doc["threadState"] = thread_state
    if normalized:
        thread_state["selectedLineAnchor"] = {
            "anchorKey": _line_anchor_key(line_type, old_line, new_line),
            "oldLine": old_line,
            "newLine": new_line,
            "lineType": line_type,
        }
    elif isinstance(thread_state.get("selectedLineAnchor"), dict):
        anchor = thread_state["selectedLineAnchor"]
        if (
            anchor.get("oldLine") == old_line
            and anchor.get("newLine") == new_line
            and str(anchor.get("lineType", "")) == line_type
        ):
            thread_state.pop("selectedLineAnchor", None)
    _prune_chunk_review(doc, chunk_id)


def _ensure_group_brief(doc: dict[str, Any], group_id: str) -> dict[str, Any]:
    group_briefs = doc.setdefault("groupBriefs", {})
    record = group_briefs.get(group_id)
    if not isinstance(record, dict):
        record = {}
        group_briefs[group_id] = record
    return record


def _prune_group_brief(doc: dict[str, Any], group_id: str) -> None:
    group_briefs = doc.get("groupBriefs")
    if not isinstance(group_briefs, dict):
        return
    record = group_briefs.get(group_id)
    if not isinstance(record, dict):
        group_briefs.pop(group_id, None)
        return
    if str(record.get("status", "")).strip():
        return
    if str(record.get("summary", "")).strip():
        return
    for key in ("focusPoints", "testEvidence", "knownTradeoffs", "questionsForReviewer", "acknowledgedBy"):
        value = record.get(key)
        if isinstance(value, list) and value:
            return
    group_briefs.pop(group_id, None)


def _set_group_brief_status(doc: dict[str, Any], group_id: str, status: str) -> None:
    normalized = status.strip()
    if not normalized:
        group_briefs = doc.get("groupBriefs")
        if isinstance(group_briefs, dict):
            record = group_briefs.get(group_id)
            if isinstance(record, dict):
                record.pop("status", None)
        _prune_group_brief(doc, group_id)
        return
    record = _ensure_group_brief(doc, group_id)
    record["status"] = normalized


def _set_group_brief_summary(doc: dict[str, Any], group_id: str, summary: str) -> None:
    normalized = summary.strip()
    if not normalized:
        group_briefs = doc.get("groupBriefs")
        if isinstance(group_briefs, dict):
            record = group_briefs.get(group_id)
            if isinstance(record, dict):
                record.pop("summary", None)
        _prune_group_brief(doc, group_id)
        return
    record = _ensure_group_brief(doc, group_id)
    record["summary"] = normalized


def _set_group_brief_meta(doc: dict[str, Any], group_id: str, field: str, value: str) -> None:
    normalized = value.strip()
    if not normalized:
        group_briefs = doc.get("groupBriefs")
        if isinstance(group_briefs, dict):
            record = group_briefs.get(group_id)
            if isinstance(record, dict):
                record.pop(field, None)
        _prune_group_brief(doc, group_id)
        return
    record = _ensure_group_brief(doc, group_id)
    record[field] = normalized


def _set_group_brief_list(doc: dict[str, Any], group_id: str, field: str, raw_items: str) -> None:
    normalized_field = VALID_GROUP_BRIEF_LIST_FIELDS[field]
    kept = [item.strip() for item in raw_items.split("|") if item.strip()]
    if not kept:
        group_briefs = doc.get("groupBriefs")
        if isinstance(group_briefs, dict):
            record = group_briefs.get(group_id)
            if isinstance(record, dict):
                record.pop(normalized_field, None)
        _prune_group_brief(doc, group_id)
        return
    record = _ensure_group_brief(doc, group_id)
    record[normalized_field] = kept


def _set_group_brief_mentions(doc: dict[str, Any], group_id: str, raw_items: str) -> None:
    kept = [item.strip() for item in raw_items.split("|") if item.strip()]
    if not kept:
        group_briefs = doc.get("groupBriefs")
        if isinstance(group_briefs, dict):
            record = group_briefs.get(group_id)
            if isinstance(record, dict):
                record.pop("mentions", None)
        _prune_group_brief(doc, group_id)
        return
    record = _ensure_group_brief(doc, group_id)
    record["mentions"] = kept


def _set_group_brief_acks(doc: dict[str, Any], group_id: str, raw_items: str) -> None:
    kept: list[dict[str, str]] = []
    for item in raw_items.split("|"):
        text = item.strip()
        if not text:
            continue
        parts = [part.strip() for part in text.split(";", maxsplit=2)]
        actor = parts[0] if parts else ""
        if not actor:
            continue
        ack: dict[str, str] = {"actor": actor}
        if len(parts) > 1 and parts[1]:
            ack["at"] = parts[1]
        if len(parts) > 2 and parts[2]:
            ack["note"] = parts[2]
        kept.append(ack)
    if not kept:
        group_briefs = doc.get("groupBriefs")
        if isinstance(group_briefs, dict):
            record = group_briefs.get(group_id)
            if isinstance(record, dict):
                record.pop("acknowledgedBy", None)
        _prune_group_brief(doc, group_id)
        return
    record = _ensure_group_brief(doc, group_id)
    record["acknowledgedBy"] = kept


def _save_prompt_document(doc: dict[str, Any], source_path: Path, state_path: Path | None) -> Path:
    if state_path is not None:
        save_review_state(state_path, extract_review_state(doc))
        return state_path
    backup = source_path.with_suffix(source_path.suffix + ".bak")
    if not backup.exists() and source_path.exists():
        backup.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    write_json(source_path, doc)
    return source_path


def _persist_prompt_analysis_state(
    doc: dict[str, Any],
    *,
    active_group: str | None,
    active_status: str | None,
    active_file: str | None,
    selected_chunk_id: str | None,
) -> None:
    analysis_state = doc.setdefault("analysisState", {})
    if not isinstance(analysis_state, dict):
        analysis_state = {}
        doc["analysisState"] = analysis_state
    if active_group:
        analysis_state["currentGroupId"] = active_group
    else:
        analysis_state.pop("currentGroupId", None)
    if active_status:
        analysis_state["promptStatusFilter"] = active_status
    else:
        analysis_state.pop("promptStatusFilter", None)
    if active_file:
        analysis_state["filterText"] = active_file
    else:
        analysis_state.pop("filterText", None)
    if selected_chunk_id:
        analysis_state["selectedChunkId"] = selected_chunk_id
    else:
        analysis_state.pop("selectedChunkId", None)
    if not analysis_state:
        doc.pop("analysisState", None)


def _restore_prompt_analysis_state(
    doc: dict[str, Any],
    chunk_map: dict[str, Any],
) -> tuple[str | None, str | None, str | None, str | None]:
    analysis_state = doc.get("analysisState")
    if not isinstance(analysis_state, dict):
        return None, None, None, None
    active_group = analysis_state.get("currentGroupId")
    if not isinstance(active_group, str) or active_group not in doc.get("assignments", {}):
        active_group = None
    active_status = analysis_state.get("promptStatusFilter")
    if not isinstance(active_status, str) or active_status not in VALID_STATUSES:
        active_status = None
    active_file = analysis_state.get("filterText")
    if not isinstance(active_file, str) or not active_file.strip():
        active_file = None
    selected_chunk_id = analysis_state.get("selectedChunkId")
    if not isinstance(selected_chunk_id, str) or selected_chunk_id not in chunk_map:
        selected_chunk_id = None
    return active_group, active_status, active_file, selected_chunk_id


def _resolve_prompt_output_path(raw_path: str) -> Path:
    path = Path(raw_path.strip())
    if path.is_absolute():
        return _PromptOutputPath(path)
    return _PromptOutputPath((Path.cwd() / path).resolve())


def _resolve_prompt_state_target(raw_value: str, bound_state_path: Path | None) -> Path | None:
    value = raw_value.strip()
    if value:
        return resolve_input_path(Path(value), search_roots=[Path(__file__).resolve().parents[1]])
    return bound_state_path


def _looks_like_state_selection_token(value: str) -> bool:
    token = str(value or "").strip()
    return any(token.startswith(prefix) for prefix in VALID_STATE_SELECTION_PREFIXES)


def _parse_prompt_state_apply_args(raw_value: str, bound_state_path: Path | None) -> tuple[Path | None, list[str]]:
    parts = _split_prompt_args(raw_value)
    if not parts:
        return None, []
    if _looks_like_state_selection_token(parts[0]):
        return bound_state_path, parts
    target_path = resolve_input_path(Path(parts[0]), search_roots=[Path(__file__).resolve().parents[1]])
    return target_path, parts[1:]


def _replace_prompt_state(
    doc: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], str | None, str | None, str | None, str | None]:
    updated_doc = apply_review_state(doc, state)
    refreshed_chunk_map, refreshed_status_map = build_indexes(updated_doc)
    active_group, active_status, active_file, selected_chunk_id = _restore_prompt_analysis_state(
        updated_doc,
        refreshed_chunk_map,
    )
    return (
        updated_doc,
        refreshed_chunk_map,
        refreshed_status_map,
        active_group,
        active_status,
        active_file,
        selected_chunk_id,
    )


def parse_app_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive DiffGR viewer application.")
    parser.add_argument("path", help="Path to .diffgr.json")
    parser.add_argument("--state", help="Optional external state JSON to overlay before opening.")
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
    source_path: Path,
    state_path: Path | None = None,
) -> int:
    active_group, active_status, active_file, selected_chunk_id = _restore_prompt_analysis_state(doc, chunk_map)
    bound_state_path = state_path

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
        if command == "state-show":
            render_state_summary(
                console,
                summarize_review_state(extract_review_state(doc)),
                bound_state_path=str(bound_state_path) if bound_state_path is not None else None,
            )
            continue
        if command == "state-bind":
            if not value:
                console.print("[red]Usage: state-bind <path-to.state.json>[/red]")
                continue
            try:
                previous = bound_state_path
                bound_state_path = resolve_input_path(Path(value), search_roots=[Path(__file__).resolve().parents[1]])
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]State bind failed:[/red] {error}")
                continue
            if previous is not None and previous != bound_state_path:
                console.print(f"[green]Bound state:[/green] {bound_state_path} [dim](replaced {previous})[/dim]")
            else:
                console.print(f"[green]Bound state:[/green] {bound_state_path}")
            continue
        if command == "state-unbind":
            bound_state_path = None
            console.print("[green]Unbound state:[/green] prompt session no longer has a default state path")
            continue
        if command == "state-load":
            try:
                loaded_state_path = _resolve_prompt_state_target(value, bound_state_path)
                if loaded_state_path is None:
                    console.print("[red]Usage: state-load <path-to.state.json>[/red]")
                    continue
                (
                    doc,
                    chunk_map,
                    refreshed_status_map,
                    active_group,
                    active_status,
                    active_file,
                    selected_chunk_id,
                ) = _replace_prompt_state(doc, load_review_state(loaded_state_path))
                status_map.clear()
                status_map.update(refreshed_status_map)
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]State load failed:[/red] {error}")
                continue
            console.print(f"[green]Loaded state:[/green] {loaded_state_path}")
            render_state_summary(
                console,
                summarize_review_state(extract_review_state(doc)),
                bound_state_path=str(bound_state_path) if bound_state_path is not None else None,
            )
            render_chunks_page(console, get_filtered_chunks(), status_map, page=1, page_size=page_size)
            continue
        if command == "state-diff":
            try:
                diff_state_path = _resolve_prompt_state_target(value, bound_state_path)
                if diff_state_path is None:
                    console.print("[red]Usage: state-diff <path-to.state.json>[/red]")
                    continue
                state_diff = diff_review_states(extract_review_state(doc), load_review_state(diff_state_path))
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]State diff failed:[/red] {error}")
                continue
            render_state_diff(console, state_diff, target_label=str(diff_state_path))
            continue
        if command == "state-apply":
            try:
                apply_state_path, selection_tokens = _parse_prompt_state_apply_args(value, bound_state_path)
                if apply_state_path is None or not selection_tokens:
                    console.print(
                        "[red]Usage: state-apply <path-to.state.json> <selection...> | state-apply <selection...> (with bound state)[/red]"
                    )
                    continue
                base_state = extract_review_state(doc)
                other_state = load_review_state(apply_state_path)
                preview = preview_review_state_selection(base_state, other_state, selection_tokens)
                next_state = preview["nextState"]
                applied = int(preview["summary"].get("appliedCount", 0))
                selection_diff = preview["resultDiff"]
                (
                    doc,
                    chunk_map,
                    refreshed_status_map,
                    active_group,
                    active_status,
                    active_file,
                    selected_chunk_id,
                ) = _replace_prompt_state(doc, next_state)
                status_map.clear()
                status_map.update(refreshed_status_map)
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]State apply failed:[/red] {error}")
                continue
            console.print(
                f"[green]Applied state selection:[/green] {apply_state_path} "
                f"(applied={applied} no-op={preview['summary'].get('noOpCount', 0)} changed-sections={preview['summary'].get('changedSectionCount', 0)})"
            )
            console.print(f"[dim]selection:[/dim] {' '.join(selection_tokens)}")
            render_state_diff(console, selection_diff, target_label=str(apply_state_path))
            render_state_summary(
                console,
                summarize_review_state(extract_review_state(doc)),
                bound_state_path=str(bound_state_path) if bound_state_path is not None else None,
            )
            render_chunks_page(console, get_filtered_chunks(), status_map, page=1, page_size=page_size)
            continue
        if command == "state-apply-preview":
            try:
                apply_state_path, selection_tokens = _parse_prompt_state_apply_args(value, bound_state_path)
                if apply_state_path is None or not selection_tokens:
                    console.print(
                        "[red]Usage: state-apply-preview <path-to.state.json> <selection...> | state-apply-preview <selection...> (with bound state)[/red]"
                    )
                    continue
                preview = preview_review_state_selection(
                    extract_review_state(doc),
                    load_review_state(apply_state_path),
                    selection_tokens,
                )
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]State apply preview failed:[/red] {error}")
                continue
            console.print(
                f"[green]State apply preview:[/green] {apply_state_path} "
                f"(applied={preview['summary'].get('appliedCount', 0)} no-op={preview['summary'].get('noOpCount', 0)} changed-sections={preview['summary'].get('changedSectionCount', 0)})"
            )
            console.print(f"[dim]selection:[/dim] {' '.join(selection_tokens)}")
            render_state_diff(console, preview["resultDiff"], target_label=f"selected apply -> {apply_state_path}")
            continue
        if command == "state-merge":
            try:
                merge_state_path = _resolve_prompt_state_target(value, bound_state_path)
                if merge_state_path is None:
                    console.print("[red]Usage: state-merge <path-to.state.json>[/red]")
                    continue
                base_state = extract_review_state(doc)
                merge_preview = preview_merge_review_states(
                    base_state,
                    [(str(merge_state_path), load_review_state(merge_state_path))],
                )
                merged_state = merge_preview["mergedState"]
                merge_warnings = merge_preview["warnings"]
                applied = int(merge_preview["applied"])
                merge_summary = merge_preview["summary"]
                (
                    doc,
                    chunk_map,
                    refreshed_status_map,
                    active_group,
                    active_status,
                    active_file,
                    selected_chunk_id,
                ) = _replace_prompt_state(doc, merged_state)
                status_map.clear()
                status_map.update(refreshed_status_map)
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]State merge failed:[/red] {error}")
                continue
            console.print(f"[green]Merged state:[/green] {merge_state_path} (applied={applied})")
            render_merge_summary(console, {"summary": merge_summary, "applied": applied}, target_label=str(merge_state_path))
            for warning in merge_warnings:
                console.print(f"[yellow]warning:[/yellow] {warning}")
            render_state_summary(
                console,
                summarize_review_state(extract_review_state(doc)),
                bound_state_path=str(bound_state_path) if bound_state_path is not None else None,
            )
            render_chunks_page(console, get_filtered_chunks(), status_map, page=1, page_size=page_size)
            continue
        if command == "state-merge-preview":
            try:
                merge_state_path = _resolve_prompt_state_target(value, bound_state_path)
                if merge_state_path is None:
                    console.print(
                        "[red]Usage: state-merge-preview <path-to.state.json> | state-merge-preview (with bound state)[/red]"
                    )
                    continue
                merge_preview = preview_merge_review_states(
                    extract_review_state(doc),
                    [(str(merge_state_path), load_review_state(merge_state_path))],
                )
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]State merge preview failed:[/red] {error}")
                continue
            console.print(
                f"[green]Merge preview:[/green] {merge_state_path} (applied={merge_preview['applied']})"
            )
            render_merge_summary(console, merge_preview, target_label=str(merge_state_path))
            continue
        if command == "impact-merge-preview":
            try:
                parts = _split_prompt_args(value)
                if len(parts) < 2:
                    console.print(
                        "[red]Usage: impact-merge-preview <old.diffgr.json> <new.diffgr.json> <state.json?>[/red]"
                    )
                    continue
                old_path = resolve_input_path(Path(parts[0]), search_roots=[Path(__file__).resolve().parents[1]])
                new_path = resolve_input_path(Path(parts[1]), search_roots=[Path(__file__).resolve().parents[1]])
                state_path = None
                if len(parts) >= 3:
                    state_path = resolve_input_path(Path(parts[2]), search_roots=[Path(__file__).resolve().parents[1]])
                else:
                    state_path = bound_state_path
                if state_path is None:
                    console.print(
                        "[red]Usage: impact-merge-preview <old.diffgr.json> <new.diffgr.json> <state.json?>[/red]"
                    )
                    continue
                old_doc = load_json(old_path)
                validate_document(old_doc)
                new_doc = load_json(new_path)
                validate_document(new_doc)
                preview = preview_impact_merge(
                    old_doc=old_doc,
                    new_doc=new_doc,
                    state=load_review_state(state_path),
                )
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]Impact merge preview failed:[/red] {error}")
                continue
            console.print(f"[green]Impact merge preview:[/green] {old_path} -> {new_path} using {state_path}")
            render_impact_preview(
                console,
                preview,
                old_label=old_path.name,
                new_label=new_path.name,
                state_label=state_path.name,
            )
            continue
        if command == "impact-apply-preview":
            try:
                parts = _split_prompt_args(value)
                valid_plans = {"handoffs", "reviews", "ui", "all"}
                if len(parts) < 3:
                    console.print(
                        "[red]Usage: impact-apply-preview <old.diffgr.json> <new.diffgr.json> <state.json?> <handoffs|reviews|ui|all>[/red]"
                    )
                    continue
                plan_name = str(parts[-1]).strip()
                if plan_name not in valid_plans:
                    console.print(
                        "[red]Usage: impact-apply-preview <old.diffgr.json> <new.diffgr.json> <state.json?> <handoffs|reviews|ui|all>[/red]"
                    )
                    continue
                if len(parts) == 3:
                    old_path = resolve_input_path(Path(parts[0]), search_roots=[Path(__file__).resolve().parents[1]])
                    new_path = resolve_input_path(Path(parts[1]), search_roots=[Path(__file__).resolve().parents[1]])
                    state_path = bound_state_path
                elif len(parts) == 4:
                    old_path = resolve_input_path(Path(parts[0]), search_roots=[Path(__file__).resolve().parents[1]])
                    new_path = resolve_input_path(Path(parts[1]), search_roots=[Path(__file__).resolve().parents[1]])
                    state_path = resolve_input_path(Path(parts[2]), search_roots=[Path(__file__).resolve().parents[1]])
                else:
                    console.print(
                        "[red]Usage: impact-apply-preview <old.diffgr.json> <new.diffgr.json> <state.json?> <handoffs|reviews|ui|all>[/red]"
                    )
                    continue
                if state_path is None:
                    console.print(
                        "[red]Usage: impact-apply-preview <old.diffgr.json> <new.diffgr.json> <state.json?> <handoffs|reviews|ui|all>[/red]"
                    )
                    continue
                old_doc = load_json(old_path)
                validate_document(old_doc)
                new_doc = load_json(new_path)
                validate_document(new_doc)
                preview = preview_impact_merge(
                    old_doc=old_doc,
                    new_doc=new_doc,
                    state=load_review_state(state_path),
                )
                report = build_impact_preview_report(
                    preview,
                    old_label=old_path.name,
                    new_label=new_path.name,
                    state_label=state_path.name,
                )
                selection_plans = report.get("selectionPlans", {}) if isinstance(report.get("selectionPlans"), dict) else {}
                plan = selection_plans.get(plan_name, {}) if isinstance(selection_plans.get(plan_name), dict) else {}
                selection_tokens = [str(item) for item in plan.get("tokens", []) if str(item)]
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]Impact apply preview failed:[/red] {error}")
                continue
            console.print(
                f"[green]Impact apply preview:[/green] {old_path} -> {new_path} using {state_path} plan={plan_name}"
            )
            console.print(f"[dim]selection plan:[/dim] {plan_name} tokens={len(selection_tokens)}")
            if not selection_tokens:
                console.print("[yellow]selection plan is empty[/yellow]")
                continue
            try:
                selection_preview = preview_review_state_selection(
                    load_review_state(state_path),
                    preview["rebasedState"],
                    selection_tokens,
                )
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]Impact apply preview failed:[/red] {error}")
                continue
            console.print(f"[dim]selection:[/dim] {' '.join(selection_tokens)}")
            render_state_diff(
                console,
                selection_preview["resultDiff"],
                target_label=f"impact plan {plan_name} -> rebased:{state_path.name}",
            )
            continue
        if command == "impact-apply":
            try:
                parts = _split_prompt_args(value)
                valid_plans = {"handoffs", "reviews", "ui", "all"}
                if len(parts) < 3:
                    console.print(
                        "[red]Usage: impact-apply <old.diffgr.json> <new.diffgr.json> <state.json?> <handoffs|reviews|ui|all>[/red]"
                    )
                    continue
                plan_name = str(parts[-1]).strip()
                if plan_name not in valid_plans:
                    console.print(
                        "[red]Usage: impact-apply <old.diffgr.json> <new.diffgr.json> <state.json?> <handoffs|reviews|ui|all>[/red]"
                    )
                    continue
                if len(parts) == 3:
                    old_path = resolve_input_path(Path(parts[0]), search_roots=[Path(__file__).resolve().parents[1]])
                    new_path = resolve_input_path(Path(parts[1]), search_roots=[Path(__file__).resolve().parents[1]])
                    state_path = bound_state_path
                elif len(parts) == 4:
                    old_path = resolve_input_path(Path(parts[0]), search_roots=[Path(__file__).resolve().parents[1]])
                    new_path = resolve_input_path(Path(parts[1]), search_roots=[Path(__file__).resolve().parents[1]])
                    state_path = resolve_input_path(Path(parts[2]), search_roots=[Path(__file__).resolve().parents[1]])
                else:
                    console.print(
                        "[red]Usage: impact-apply <old.diffgr.json> <new.diffgr.json> <state.json?> <handoffs|reviews|ui|all>[/red]"
                    )
                    continue
                if state_path is None:
                    console.print(
                        "[red]Usage: impact-apply <old.diffgr.json> <new.diffgr.json> <state.json?> <handoffs|reviews|ui|all>[/red]"
                    )
                    continue
                old_doc = load_json(old_path)
                validate_document(old_doc)
                new_doc = load_json(new_path)
                validate_document(new_doc)
                impact_apply = preview_impact_apply(
                    old_doc=old_doc,
                    new_doc=new_doc,
                    state=load_review_state(state_path),
                    plan=plan_name,
                    old_label=old_path.name,
                    new_label=new_path.name,
                    state_label=state_path.name,
                )
                selection_preview = impact_apply["selectionPreview"]
                selection_tokens = impact_apply["selectionTokens"]
                next_state = impact_apply["nextState"]
                if not isinstance(selection_preview, dict):
                    console.print(
                        f"[green]Impact apply:[/green] {old_path} -> {new_path} using {state_path} plan={plan_name}"
                    )
                    console.print(f"[dim]selection plan:[/dim] {plan_name} tokens=0 applied=0 no-op=0 changed-sections=0")
                    console.print("[yellow]selection plan is empty[/yellow]")
                    continue
                (
                    doc,
                    chunk_map,
                    refreshed_status_map,
                    active_group,
                    active_status,
                    active_file,
                    selected_chunk_id,
                ) = _replace_prompt_state(doc, next_state)
                status_map.clear()
                status_map.update(refreshed_status_map)
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]Impact apply failed:[/red] {error}")
                continue
            console.print(
                f"[green]Impact apply:[/green] {old_path} -> {new_path} using {state_path} plan={plan_name}"
            )
            console.print(
                f"[dim]selection plan:[/dim] {plan_name} tokens={len(selection_tokens)} "
                f"applied={selection_preview['summary'].get('appliedCount', 0)} "
                f"no-op={selection_preview['summary'].get('noOpCount', 0)} "
                f"changed-sections={selection_preview['summary'].get('changedSectionCount', 0)}"
            )
            if selection_tokens:
                console.print(f"[dim]selection:[/dim] {' '.join(selection_tokens)}")
            else:
                console.print("[yellow]selection plan is empty[/yellow]")
            render_state_diff(
                console,
                selection_preview["resultDiff"],
                target_label=f"impact plan {plan_name} -> rebased:{state_path.name}",
            )
            render_state_summary(
                console,
                summarize_review_state(extract_review_state(doc)),
                bound_state_path=str(bound_state_path) if bound_state_path is not None else None,
            )
            render_chunks_page(console, get_filtered_chunks(), status_map, page=1, page_size=page_size)
            continue
        if command == "state-reset":
            (
                doc,
                chunk_map,
                refreshed_status_map,
                active_group,
                active_status,
                active_file,
                selected_chunk_id,
            ) = _replace_prompt_state(
                doc,
                {"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}},
            )
            status_map.clear()
            status_map.update(refreshed_status_map)
            console.print("[green]Reset state:[/green] reviews/groupBriefs/analysisState/threadState")
            render_chunks_page(console, get_filtered_chunks(), status_map, page=1, page_size=page_size)
            continue
        if command == "state-save-as":
            try:
                output_path = _resolve_prompt_state_target(value, bound_state_path)
                if output_path is None:
                    console.print("[red]Usage: state-save-as <path-to.state.json>[/red]")
                    continue
                output_path = output_path if output_path.is_absolute() else _resolve_prompt_output_path(str(output_path))
                save_review_state(output_path, extract_review_state(doc))
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]State export failed:[/red] {error}")
                continue
            console.print(f"[green]Wrote state:[/green] {output_path}")
            if bound_state_path is not None and output_path == bound_state_path:
                console.print("[dim]state-save-as target matches current bound state[/dim]")
            continue
        if command == "group":
            if not value or value == "all":
                active_group = None
            elif value in doc.get("assignments", {}):
                active_group = value
            else:
                console.print(f"[red]Unknown group in assignments: {value}[/red]")
                continue
            _persist_prompt_analysis_state(
                doc,
                active_group=active_group,
                active_status=active_status,
                active_file=active_file,
                selected_chunk_id=selected_chunk_id,
            )
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
            _persist_prompt_analysis_state(
                doc,
                active_group=active_group,
                active_status=active_status,
                active_file=active_file,
                selected_chunk_id=selected_chunk_id,
            )
            render_chunks_page(console, get_filtered_chunks(), status_map, page=1, page_size=page_size)
            continue
        if command == "file":
            active_file = None if not value or value == "clear" else value
            _persist_prompt_analysis_state(
                doc,
                active_group=active_group,
                active_status=active_status,
                active_file=active_file,
                selected_chunk_id=selected_chunk_id,
            )
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
            review_record = doc.get("reviews", {}).get(value)
            render_chunk_detail(
                console,
                chunk,
                status,
                max_lines=200,
                review_record=review_record if isinstance(review_record, dict) else None,
            )
            selected_chunk_id = value
            _persist_prompt_analysis_state(
                doc,
                active_group=active_group,
                active_status=active_status,
                active_file=active_file,
                selected_chunk_id=selected_chunk_id,
            )
            continue
        if command == "brief-show":
            if not value:
                console.print("[red]Usage: brief-show <group_id>[/red]")
                continue
            group = next(
                (item for item in doc.get("groups", []) if isinstance(item, dict) and str(item.get("id", "")) == value),
                None,
            )
            if group is None:
                console.print(f"[red]Unknown group: {value}[/red]")
                continue
            assigned = doc.get("assignments", {}).get(value, [])
            brief = doc.get("groupBriefs", {}).get(value)
            render_group_brief_detail(
                console,
                group,
                brief if isinstance(brief, dict) else None,
                len(assigned) if isinstance(assigned, list) else 0,
            )
            continue
        if command == "set-status":
            chunk_and_status = value.split(maxsplit=1)
            if len(chunk_and_status) != 2:
                console.print("[red]Usage: set-status <chunk_id> <status>[/red]")
                continue
            chunk_id, status = chunk_and_status[0], chunk_and_status[1].strip()
            if chunk_id not in chunk_map:
                console.print(f"[red]Chunk not found: {chunk_id}[/red]")
                continue
            if status not in VALID_STATUSES:
                console.print(f"[red]Invalid status: {status}[/red]")
                continue
            _set_chunk_status(doc, status_map, chunk_id, status)
            console.print(f"[green]Updated status:[/green] {chunk_id} -> {status}")
            continue
        if command == "comment":
            chunk_and_comment = value.split(maxsplit=1)
            if not chunk_and_comment:
                console.print("[red]Usage: comment <chunk_id> <text|clear>[/red]")
                continue
            chunk_id = chunk_and_comment[0]
            if chunk_id not in chunk_map:
                console.print(f"[red]Chunk not found: {chunk_id}[/red]")
                continue
            raw_comment = chunk_and_comment[1] if len(chunk_and_comment) > 1 else ""
            normalized = "" if raw_comment.strip().lower() == "clear" else raw_comment
            _set_chunk_comment(doc, chunk_id, normalized)
            if normalized.strip():
                console.print(f"[green]Updated comment:[/green] {chunk_id}")
            else:
                console.print(f"[green]Cleared comment:[/green] {chunk_id}")
            continue
        if command == "line-comment":
            parts = value.split(maxsplit=5)
            if len(parts) < 5:
                console.print(
                    "[red]Usage: line-comment <chunk_id> <oldLine|-> <newLine|-> <lineType> <text|clear>[/red]"
                )
                continue
            chunk_id, raw_old_line, raw_new_line, line_type = parts[:4]
            if chunk_id not in chunk_map:
                console.print(f"[red]Chunk not found: {chunk_id}[/red]")
                continue
            if line_type not in {"context", "add", "delete"}:
                console.print(f"[red]Invalid lineType: {line_type}[/red]")
                continue
            try:
                old_line = _parse_line_number_token(raw_old_line)
                new_line = _parse_line_number_token(raw_new_line)
            except ValueError as error:
                console.print(f"[red]Invalid line number:[/red] {error}")
                continue
            raw_comment = parts[4] if len(parts) == 5 else parts[4] + " " + parts[5]
            normalized = "" if raw_comment.strip().lower() == "clear" else raw_comment
            _set_line_comment(
                doc,
                chunk_id,
                old_line=old_line,
                new_line=new_line,
                line_type=line_type,
                comment=normalized,
            )
            if normalized.strip():
                console.print(f"[green]Updated line comment:[/green] {chunk_id} {line_type} {raw_old_line}/{raw_new_line}")
            else:
                console.print(f"[green]Cleared line comment:[/green] {chunk_id} {line_type} {raw_old_line}/{raw_new_line}")
            continue
        if command == "brief-status":
            group_and_status = value.split(maxsplit=1)
            if len(group_and_status) != 2:
                console.print("[red]Usage: brief-status <group_id> <status|clear>[/red]")
                continue
            group_id, status = group_and_status[0], group_and_status[1].strip()
            if group_id not in doc.get("assignments", {}):
                console.print(f"[red]Unknown group in assignments: {group_id}[/red]")
                continue
            normalized = "" if status.lower() == "clear" else status
            if normalized and normalized not in VALID_GROUP_BRIEF_STATUSES:
                console.print(f"[red]Invalid brief status: {status}[/red]")
                continue
            _set_group_brief_status(doc, group_id, normalized)
            if normalized:
                console.print(f"[green]Updated brief status:[/green] {group_id} -> {normalized}")
            else:
                console.print(f"[green]Cleared brief status:[/green] {group_id}")
            continue
        if command == "brief-meta":
            group_field_and_value = value.split(maxsplit=2)
            if len(group_field_and_value) < 2:
                console.print("[red]Usage: brief-meta <group_id> <updatedAt|sourceHead> <value|clear>[/red]")
                continue
            group_id, field = group_field_and_value[0], group_field_and_value[1]
            if group_id not in doc.get("assignments", {}):
                console.print(f"[red]Unknown group in assignments: {group_id}[/red]")
                continue
            if field not in VALID_GROUP_BRIEF_META_FIELDS:
                console.print(f"[red]Invalid brief meta field: {field}[/red]")
                continue
            raw_value = group_field_and_value[2] if len(group_field_and_value) > 2 else ""
            normalized = "" if raw_value.strip().lower() == "clear" else raw_value
            _set_group_brief_meta(doc, group_id, field, normalized)
            if normalized.strip():
                console.print(f"[green]Updated brief meta:[/green] {group_id} {field}")
            else:
                console.print(f"[green]Cleared brief meta:[/green] {group_id} {field}")
            continue
        if command == "brief":
            group_and_summary = value.split(maxsplit=1)
            if not group_and_summary:
                console.print("[red]Usage: brief <group_id> <summary|clear>[/red]")
                continue
            group_id = group_and_summary[0]
            if group_id not in doc.get("assignments", {}):
                console.print(f"[red]Unknown group in assignments: {group_id}[/red]")
                continue
            raw_summary = group_and_summary[1] if len(group_and_summary) > 1 else ""
            normalized = "" if raw_summary.strip().lower() == "clear" else raw_summary
            _set_group_brief_summary(doc, group_id, normalized)
            if normalized.strip():
                console.print(f"[green]Updated brief:[/green] {group_id}")
            else:
                console.print(f"[green]Cleared brief:[/green] {group_id}")
            continue
        if command == "brief-list":
            group_field_and_value = value.split(maxsplit=2)
            if len(group_field_and_value) < 2:
                console.print(
                    "[red]Usage: brief-list <group_id> <focus|evidence|tradeoff|question> <item1 | item2 | clear>[/red]"
                )
                continue
            group_id, field = group_field_and_value[0], group_field_and_value[1]
            if group_id not in doc.get("assignments", {}):
                console.print(f"[red]Unknown group in assignments: {group_id}[/red]")
                continue
            if field not in VALID_GROUP_BRIEF_LIST_FIELDS:
                console.print(f"[red]Invalid brief list field: {field}[/red]")
                continue
            raw_items = group_field_and_value[2] if len(group_field_and_value) > 2 else ""
            normalized = "" if raw_items.strip().lower() == "clear" else raw_items
            _set_group_brief_list(doc, group_id, field, normalized)
            if normalized.strip():
                console.print(f"[green]Updated brief list:[/green] {group_id} {VALID_GROUP_BRIEF_LIST_FIELDS[field]}")
            else:
                console.print(f"[green]Cleared brief list:[/green] {group_id} {VALID_GROUP_BRIEF_LIST_FIELDS[field]}")
            continue
        if command == "brief-mentions":
            group_and_value = value.split(maxsplit=1)
            if not group_and_value:
                console.print("[red]Usage: brief-mentions <group_id> <mention1 | mention2 | clear>[/red]")
                continue
            group_id = group_and_value[0]
            if group_id not in doc.get("assignments", {}):
                console.print(f"[red]Unknown group in assignments: {group_id}[/red]")
                continue
            raw_items = group_and_value[1] if len(group_and_value) > 1 else ""
            normalized = "" if raw_items.strip().lower() == "clear" else raw_items
            _set_group_brief_mentions(doc, group_id, normalized)
            if normalized.strip():
                console.print(f"[green]Updated brief mentions:[/green] {group_id}")
            else:
                console.print(f"[green]Cleared brief mentions:[/green] {group_id}")
            continue
        if command == "brief-ack":
            group_and_value = value.split(maxsplit=1)
            if not group_and_value:
                console.print("[red]Usage: brief-ack <group_id> <actor;at;note | clear>[/red]")
                continue
            group_id = group_and_value[0]
            if group_id not in doc.get("assignments", {}):
                console.print(f"[red]Unknown group in assignments: {group_id}[/red]")
                continue
            raw_items = group_and_value[1] if len(group_and_value) > 1 else ""
            normalized = "" if raw_items.strip().lower() == "clear" else raw_items
            _set_group_brief_acks(doc, group_id, normalized)
            if normalized.strip():
                console.print(f"[green]Updated brief acknowledgements:[/green] {group_id}")
            else:
                console.print(f"[green]Cleared brief acknowledgements:[/green] {group_id}")
            continue
        if command == "save":
            try:
                saved_path = _save_prompt_document(doc, source_path, bound_state_path)
            except Exception as error:  # noqa: BLE001
                console.print(f"[red]Save failed:[/red] {error}")
                continue
            label = "state" if bound_state_path is not None else "document"
            console.print(f"[green]Saved {label}:[/green] {saved_path}")
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
    state_path: Path | None = None,
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
    return launch_textual_viewer(doc, warnings, chunk_map, status_map, page_size, source_path, state_path)


def run_app(argv: list[str]) -> int:
    args = parse_app_args(argv)
    if args.page_size < 1:
        print("[error] --page-size must be >= 1", file=sys.stderr)
        return 2

    console = Console()
    path = resolve_input_path(Path(args.path), search_roots=[Path(__file__).resolve().parents[1]])
    state_path = resolve_input_path(Path(args.state), search_roots=[Path(__file__).resolve().parents[1]]) if args.state else None
    try:
        doc = load_json(path)
        warnings = validate_document(doc)
        if state_path is not None and state_path.exists():
            doc = apply_review_state(doc, load_review_state(state_path))
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
        return run_prompt_app(console, doc, warnings, chunk_map, status_map, args.page_size, path, state_path)
    return run_textual_app(doc, warnings, chunk_map, status_map, args.page_size, path, state_path)
