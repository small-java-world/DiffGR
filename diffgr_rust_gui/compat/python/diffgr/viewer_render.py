from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from diffgr.review_state import STATE_DIFF_SECTIONS, build_merge_preview_report, iter_review_state_diff_rows


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


def render_state_summary(console: Console, summary: dict[str, Any], *, bound_state_path: str | None = None) -> None:
    reviews = summary.get("reviews", {}) if isinstance(summary.get("reviews"), dict) else {}
    group_briefs = summary.get("groupBriefs", {}) if isinstance(summary.get("groupBriefs"), dict) else {}
    analysis_state = summary.get("analysisState", {}) if isinstance(summary.get("analysisState"), dict) else {}
    thread_state = summary.get("threadState", {}) if isinstance(summary.get("threadState"), dict) else {}

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row(
        "Reviews",
        (
            f"total={reviews.get('total', 0)} "
            f"reviewed={reviews.get('statusCounts', {}).get('reviewed', 0)} "
            f"needsReReview={reviews.get('statusCounts', {}).get('needsReReview', 0)} "
            f"chunkComments={reviews.get('chunkCommentCount', 0)} "
            f"lineComments={reviews.get('lineCommentCount', 0)}"
        ),
    )
    table.add_row(
        "Briefs",
        (
            f"total={group_briefs.get('total', 0)} "
            f"draft={group_briefs.get('statusCounts', {}).get('draft', 0)} "
            f"ready={group_briefs.get('statusCounts', {}).get('ready', 0)} "
            f"ack={group_briefs.get('statusCounts', {}).get('acknowledged', 0)} "
            f"stale={group_briefs.get('statusCounts', {}).get('stale', 0)}"
        ),
    )
    table.add_row(
        "Analysis",
        (
            f"group={analysis_state.get('currentGroupId', '') or '-'} "
            f"chunk={analysis_state.get('selectedChunkId', '') or '-'} "
            f"filter={analysis_state.get('filterText', '') or '-'} "
            f"detail={analysis_state.get('chunkDetailViewMode', '') or '-'}"
        ),
    )
    table.add_row(
        "Thread",
        (
            f"chunks={thread_state.get('chunkEntryCount', 0)} "
            f"files={thread_state.get('fileEntryCount', 0)} "
            f"selectedLineAnchor={'yes' if thread_state.get('hasSelectedLineAnchor') else 'no'}"
        ),
    )
    if bound_state_path:
        table.add_row("BoundState", bound_state_path)
    console.print(Panel(table, title="State Summary", border_style="yellow"))


def render_state_diff(console: Console, diff: dict[str, Any], *, target_label: str) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    for key in STATE_DIFF_SECTIONS:
        section = diff.get(key, {}) if isinstance(diff.get(key), dict) else {}
        table.add_row(
            key,
            (
                f"added={section.get('addedCount', 0)} "
                f"removed={section.get('removedCount', 0)} "
                f"changed={section.get('changedCount', 0)} "
                f"unchanged={section.get('unchangedCount', 0)}"
            ),
        )
    console.print(Panel(table, title=f"State Diff vs {target_label}", border_style="magenta"))

    rows = iter_review_state_diff_rows(diff)
    for key in STATE_DIFF_SECTIONS:
        detail_rows = [
            (
                str(row.get("changeKind", "")),
                str(row.get("key", "")),
                str(row.get("preview", "")),
                str(row.get("selectionToken", "")),
            )
            for row in rows
            if str(row.get("section", "")) == key
        ]
        if not detail_rows:
            continue
        detail_table = Table(title=f"{key} keys", header_style="bold magenta")
        detail_table.add_column("kind", no_wrap=True)
        detail_table.add_column("key", overflow="fold")
        detail_table.add_column("preview", overflow="fold")
        detail_table.add_column("select", overflow="fold")
        for label, key_name, preview, selection_token in detail_rows:
            detail_table.add_row(label, key_name, preview, selection_token)
        console.print(detail_table)


def render_merge_summary(console: Console, preview: dict[str, Any], *, target_label: str) -> None:
    report = build_merge_preview_report(preview, target_label=target_label)
    warnings = report.get("warnings", {}) if isinstance(report.get("warnings"), dict) else {}
    kinds = warnings.get("kinds", {}) if isinstance(warnings.get("kinds"), dict) else {}
    inputs = report.get("inputs", []) if isinstance(report.get("inputs"), list) else []
    brief_changes = report.get("groupBriefChanges", []) if isinstance(report.get("groupBriefChanges"), list) else []
    change_summary = report.get("changeSummary", {}) if isinstance(report.get("changeSummary"), dict) else {}
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("Source", str(report.get("sourceLabel", "")))
    table.add_row(
        "Change Summary",
        f"inputs={change_summary.get('inputCount', 0)} applied={change_summary.get('appliedReviews', 0)}",
    )
    table.add_row(
        "Warnings",
        (
            f"total={warnings.get('total', 0)} "
            f"status={kinds.get('statusConflict', 0)} "
            f"chunkComment={kinds.get('chunkCommentConflict', 0)} "
            f"brief={kinds.get('groupBriefConflict', 0)} "
            f"invalid={kinds.get('invalidReviewRecord', 0) + kinds.get('invalidGroupBriefRecord', 0)}"
        ),
    )
    console.print(Panel(table, title="State Merge Preview", border_style="green"))
    if inputs:
        input_table = Table(title="Change Summary Inputs", header_style="bold magenta")
        input_table.add_column("source", overflow="fold")
        input_table.add_column("reviews", justify="right")
        input_table.add_column("briefs", justify="right")
        input_table.add_column("analysis", justify="right")
        input_table.add_column("thread", justify="right")
        input_table.add_column("files", justify="right")
        for item in inputs:
            if not isinstance(item, dict):
                continue
            input_table.add_row(
                str(item.get("source", "")),
                str(item.get("reviews", 0)),
                str(item.get("groupBriefs", 0)),
                str(item.get("analysisState", 0)),
                str(item.get("threadState", 0)),
                str(item.get("threadStateFiles", 0)),
            )
        console.print(input_table)
    if brief_changes:
        brief_table = Table(title="Group Brief Changes", header_style="bold magenta")
        brief_table.add_column("group", no_wrap=True)
        brief_table.add_column("kind", no_wrap=True)
        brief_table.add_column("status", overflow="fold")
        brief_table.add_column("summary", overflow="fold")
        brief_table.add_column("counts", overflow="fold")
        for item in brief_changes:
            if not isinstance(item, dict):
                continue
            before = item.get("before", {}) if isinstance(item.get("before"), dict) else {}
            after = item.get("after", {}) if isinstance(item.get("after"), dict) else {}
            status = f"{before.get('status', '') or '-'} -> {after.get('status', '') or '-'}"
            summary_text = f"{before.get('summary', '') or '-'} -> {after.get('summary', '') or '-'}"
            counts = (
                f"focus {before.get('focusPointsCount', 0)}->{after.get('focusPointsCount', 0)} "
                f"tests {before.get('testEvidenceCount', 0)}->{after.get('testEvidenceCount', 0)} "
                f"questions {before.get('questionsCount', 0)}->{after.get('questionsCount', 0)}"
            )
            brief_table.add_row(
                str(item.get("groupId", "")),
                str(item.get("changeKind", "")),
                status,
                summary_text,
                counts,
            )
        console.print(brief_table)
    render_state_diff(console, report.get("stateDiff", {}), target_label=target_label)


def render_impact_preview(
    console: Console,
    preview: dict[str, Any],
    *,
    old_label: str,
    new_label: str,
    state_label: str,
) -> None:
    from .impact_merge import build_impact_preview_report

    report = build_impact_preview_report(
        preview,
        old_label=old_label,
        new_label=new_label,
        state_label=state_label,
    )
    impact_summary = report.get("impactSummary", {}) if isinstance(report.get("impactSummary"), dict) else {}
    warning_summary = report.get("warningSummary", {}) if isinstance(report.get("warningSummary"), dict) else {}
    kinds = warning_summary.get("kinds", {}) if isinstance(warning_summary.get("kinds"), dict) else {}
    summary_table = Table.grid(padding=(0, 2))
    summary_table.add_column(style="bold cyan")
    summary_table.add_column()
    summary_table.add_row("Source", str(report.get("sourceLabel", "")))
    change_summary = report.get("changeSummary", {}) if isinstance(report.get("changeSummary"), dict) else {}
    summary_table.add_row(
        "Change Summary",
        (
            f"carriedReviews={change_summary.get('carriedReviews', 0)} "
            f"changedToNeedsReReview={change_summary.get('changedToNeedsReReview', 0)} "
            f"unmappedNewChunks={change_summary.get('unmappedNewChunks', 0)}"
        ),
    )
    summary_table.add_row(
        "Impact",
        "changed groups={changed} unchanged groups={unchanged} newOnly={new_only} oldOnly={old_only}".format(
            changed=impact_summary.get("impactedGroupCount", 0),
            unchanged=impact_summary.get("unchangedGroupCount", 0),
            new_only=len(impact_summary.get("newOnlyChunkIds", []) or []),
            old_only=len(impact_summary.get("oldOnlyChunkIds", []) or []),
        ),
    )
    summary_table.add_row(
        "Warnings",
        (
            f"total={warning_summary.get('total', 0)} "
            f"status={kinds.get('statusConflict', 0)} "
            f"chunkComment={kinds.get('chunkCommentConflict', 0)} "
            f"brief={kinds.get('groupBriefConflict', 0)} "
            f"invalid={kinds.get('invalidReviewRecord', 0) + kinds.get('invalidGroupBriefRecord', 0)} "
            f"rebaseWeak={kinds.get('rebaseWeakMatch', 0)} "
            f"rebaseUnmapped={kinds.get('rebaseUnmappedChunk', 0)}"
        ),
    )
    console.print(Panel(summary_table, title="Impact", border_style="cyan"))

    group_brief_changes = report.get("groupBriefChanges", []) if isinstance(report.get("groupBriefChanges"), list) else []
    if group_brief_changes:
        group_change_table = Table(title="Group Brief Changes", header_style="bold magenta")
        group_change_table.add_column("group", no_wrap=True)
        group_change_table.add_column("kind", no_wrap=True)
        group_change_table.add_column("status", overflow="fold")
        group_change_table.add_column("summary", overflow="fold")
        for item in group_brief_changes:
            if not isinstance(item, dict):
                continue
            before = item.get("before", {}) if isinstance(item.get("before"), dict) else {}
            after = item.get("after", {}) if isinstance(item.get("after"), dict) else {}
            group_change_table.add_row(
                str(item.get("groupId", "")),
                str(item.get("changeKind", "")),
                f"{before.get('status', '') or '-'} -> {after.get('status', '') or '-'}",
                f"{before.get('summary', '') or '-'} -> {after.get('summary', '') or '-'}",
            )
        console.print(group_change_table)

    impacted_groups = report.get("impactedGroups", []) if isinstance(report.get("impactedGroups"), list) else []
    if impacted_groups:
        impacted_table = Table(title="Impacted Groups", header_style="bold magenta")
        impacted_table.add_column("group", no_wrap=True)
        impacted_table.add_column("name", overflow="fold")
        impacted_table.add_column("changed", justify="right")
        impacted_table.add_column("new", justify="right")
        impacted_table.add_column("removed", justify="right")
        for item in impacted_groups:
            if not isinstance(item, dict):
                continue
            impacted_table.add_row(
                str(item.get("groupId", "")),
                str(item.get("name", "")),
                str(item.get("changed", 0)),
                str(item.get("new", 0)),
                str(item.get("removed", 0)),
            )
        console.print(impacted_table)

    affected_briefs = report.get("affectedBriefs", []) if isinstance(report.get("affectedBriefs"), list) else []
    if affected_briefs:
        brief_table = Table(title="Affected Briefs", header_style="bold magenta")
        brief_table.add_column("group", no_wrap=True)
        brief_table.add_column("status", no_wrap=True)
        brief_table.add_column("summary", overflow="fold")
        brief_table.add_column("counts", overflow="fold")
        for item in affected_briefs:
            if not isinstance(item, dict):
                continue
            counts = (
                f"focus {item.get('focusPointsCount', 0)} "
                f"tests {item.get('testEvidenceCount', 0)} "
                f"questions {item.get('questionsCount', 0)}"
            )
            brief_table.add_row(
                str(item.get("groupId", "")),
                str(item.get("status", "") or "-"),
                str(item.get("summary", "") or "-"),
                counts,
            )
        console.print(brief_table)

    selection_plans = report.get("selectionPlans", {}) if isinstance(report.get("selectionPlans"), dict) else {}
    if selection_plans:
        plan_table = Table(title="Selection Plans", header_style="bold magenta")
        plan_table.add_column("plan", no_wrap=True)
        plan_table.add_column("count", justify="right")
        plan_table.add_column("tokens", overflow="fold")
        for plan_name in ("handoffs", "reviews", "ui", "all"):
            plan = selection_plans.get(plan_name, {}) if isinstance(selection_plans.get(plan_name), dict) else {}
            tokens = [str(item) for item in plan.get("tokens", []) if str(item)]
            plan_table.add_row(
                plan_name,
                str(plan.get("count", len(tokens))),
                "\n".join(tokens) if tokens else "-",
            )
        console.print(plan_table)

    render_state_diff(console, report.get("stateDiff", {}), target_label=f"rebased:{state_label}")


def render_groups(console: Console, doc: dict[str, Any]) -> None:
    table = Table(title="Groups", header_style="bold magenta")
    table.add_column("id", style="cyan")
    table.add_column("name")
    table.add_column("order", justify="right")
    table.add_column("chunks", justify="right")
    table.add_column("brief", no_wrap=True)
    table.add_column("summary", overflow="ellipsis")
    groups = sorted(
        doc["groups"],
        key=lambda item: (
            item.get("order") is None,
            item.get("order", 0),
            item.get("name", ""),
        ),
    )
    group_briefs = doc.get("groupBriefs", {}) if isinstance(doc.get("groupBriefs"), dict) else {}
    for group in groups:
        group_id = group.get("id", "-")
        assigned = doc["assignments"].get(group_id, [])
        brief = group_briefs.get(group_id, {}) if isinstance(group_id, str) else {}
        brief_status = brief.get("status", "-") if isinstance(brief, dict) else "-"
        brief_summary = brief.get("summary", "") if isinstance(brief, dict) else ""
        table.add_row(
            str(group_id),
            str(group.get("name", "-")),
            str(group.get("order", "-")),
            str(len(assigned) if isinstance(assigned, list) else 0),
            str(brief_status or "-"),
            str(brief_summary or ""),
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
    review_record: dict[str, Any] | None = None,
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
    if isinstance(review_record, dict):
        comment = str(review_record.get("comment", "") or "").strip()
        line_comments = review_record.get("lineComments")
        if comment:
            meta.add_row("comment", comment)
        if isinstance(line_comments, list):
            meta.add_row("lineComments", str(len(line_comments)))
    if "fingerprints" in chunk:
        meta.add_row("fingerprints", json.dumps(chunk["fingerprints"], ensure_ascii=False))
    console.print(Panel(meta, title="Chunk Detail", border_style="green"))

    if isinstance(review_record, dict):
        line_comments = review_record.get("lineComments")
        if isinstance(line_comments, list) and line_comments:
            comment_table = Table(title="Line Comments", header_style="bold magenta")
            comment_table.add_column("old", justify="right")
            comment_table.add_column("new", justify="right")
            comment_table.add_column("type", no_wrap=True)
            comment_table.add_column("comment")
            for item in line_comments:
                if not isinstance(item, dict):
                    continue
                comment_table.add_row(
                    str(item.get("oldLine", "")),
                    str(item.get("newLine", "")),
                    str(item.get("lineType", "")),
                    str(item.get("comment", "")),
                )
            console.print(comment_table)

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


def render_group_brief_detail(
    console: Console,
    group: dict[str, Any],
    brief: dict[str, Any] | None,
    assigned_count: int,
) -> None:
    meta = Table.grid(padding=(0, 2))
    meta.add_column(style="bold cyan")
    meta.add_column()
    meta.add_row("id", str(group.get("id", "-")))
    meta.add_row("name", str(group.get("name", "-")))
    meta.add_row("order", str(group.get("order", "-")))
    meta.add_row("chunks", str(assigned_count))
    if isinstance(brief, dict):
        meta.add_row("status", str(brief.get("status", "-") or "-"))
        meta.add_row("summary", str(brief.get("summary", "") or ""))
        updated_at = str(brief.get("updatedAt", "") or "").strip()
        source_head = str(brief.get("sourceHead", "") or "").strip()
        if updated_at:
            meta.add_row("updatedAt", updated_at)
        if source_head:
            meta.add_row("sourceHead", source_head)
    else:
        meta.add_row("status", "-")
        meta.add_row("summary", "")
    console.print(Panel(meta, title="Group Brief", border_style="cyan"))

    if isinstance(brief, dict):
        for title, key in (
            ("Focus Points", "focusPoints"),
            ("Test Evidence", "testEvidence"),
            ("Known Tradeoffs", "knownTradeoffs"),
            ("Questions", "questionsForReviewer"),
            ("Mentions", "mentions"),
        ):
            items = brief.get(key)
            if not isinstance(items, list) or not items:
                continue
            table = Table(title=title, header_style="bold magenta")
            table.add_column("#", justify="right", no_wrap=True)
            table.add_column("value")
            for index, item in enumerate(items, start=1):
                table.add_row(str(index), str(item))
            console.print(table)
        acknowledgements = brief.get("acknowledgedBy")
        if isinstance(acknowledgements, list) and acknowledgements:
            table = Table(title="Acknowledged By", header_style="bold magenta")
            table.add_column("#", justify="right", no_wrap=True)
            table.add_column("actor")
            table.add_column("at")
            table.add_column("note")
            for index, item in enumerate(acknowledgements, start=1):
                if not isinstance(item, dict):
                    continue
                table.add_row(
                    str(index),
                    str(item.get("actor", "")),
                    str(item.get("at", "")),
                    str(item.get("note", "")),
                )
            console.print(table)


def render_command_help(console: Console) -> None:
    help_table = Table(title="Commands", header_style="bold magenta")
    help_table.add_column("command", style="cyan", no_wrap=True)
    help_table.add_column("description")
    help_table.add_row("help", "Show this help.")
    help_table.add_row("list [page]", "Show chunk list. Optional page number.")
    help_table.add_row("detail <chunk_id>", "Show one chunk detail.")
    help_table.add_row("brief-show <group_id>", "Show one group handoff detail.")
    help_table.add_row("group <group_id|all>", "Set group filter.")
    help_table.add_row("status <status|all>", "Set status filter.")
    help_table.add_row("file <text|clear>", "Set filePath substring filter.")
    help_table.add_row("set-status <chunk_id> <status>", "Update one chunk review status.")
    help_table.add_row("comment <chunk_id> <text|clear>", "Update one chunk review comment.")
    help_table.add_row(
        "line-comment <chunk_id> <old|-> <new|-> <type> <text|clear>",
        "Update one chunk line comment.",
    )
    help_table.add_row("brief <group_id> <summary|clear>", "Update one group handoff summary.")
    help_table.add_row("brief-status <group_id> <status|clear>", "Update one group handoff status.")
    help_table.add_row("brief-meta <group_id> <updatedAt|sourceHead> <value|clear>", "Update group handoff metadata.")
    help_table.add_row(
        "brief-list <group_id> <focus|evidence|tradeoff|question> <item1 | item2 | clear>",
        "Update one group handoff list field.",
    )
    help_table.add_row("brief-mentions <group_id> <mention1 | mention2 | clear>", "Update group handoff mentions.")
    help_table.add_row("brief-ack <group_id> <actor;at;note | clear>", "Update group handoff acknowledgements.")
    help_table.add_row("save", "Save to .diffgr.json or external state JSON.")
    help_table.add_row("groups", "Show groups summary.")
    help_table.add_row("metrics", "Show dashboard again.")
    help_table.add_row("state-show", "Show current review/state summary.")
    help_table.add_row("state-bind <path>", "Bind a default external state JSON for state commands.")
    help_table.add_row("state-unbind", "Clear the current bound external state JSON.")
    help_table.add_row("state-load <path>", "Load external state JSON into current session.")
    help_table.add_row("state-diff <path>", "Compare current state with external state JSON.")
    help_table.add_row("state-merge <path>", "Merge external state JSON into current session.")
    help_table.add_row("state-merge-preview <path>", "Preview merge effects without mutating current state.")
    help_table.add_row("impact-merge-preview <old> <new> <state?>", "Preview rebased merge with impact summary.")
    help_table.add_row("impact-apply-preview <old> <new> <state?> <plan>", "Preview rebased selective apply for handoffs/reviews/ui/all.")
    help_table.add_row("impact-apply <old> <new> <state?> <plan>", "Apply rebased selective plan to current session.")
    help_table.add_row("state-apply-preview <path?> <selection...>", "Preview selected state apply without mutating current state.")
    help_table.add_row("state-apply <path?> <selection...>", "Apply selected diff keys from external state JSON.")
    help_table.add_row("state-reset", "Clear reviews/groupBriefs/analysisState/threadState.")
    help_table.add_row("state-save-as <path>", "Write current state JSON to a path.")
    help_table.add_row("quit", "Exit application.")
    console.print(help_table)
