from __future__ import annotations

import copy
import json
from html import escape
from typing import Any

from .diff_utils import line_anchor_key as _line_anchor_key, normalize_line_number as _normalize_line_number
from .group_brief_utils import normalize_group_brief_record
from .group_utils import safe_groups
from .impact_merge import build_impact_preview_report
from .review_state import STATE_DIFF_SECTIONS, STATE_SELECTION_SECTIONS, iter_review_state_diff_rows
from .review_utils import VALID_REVIEW_STATUSES
from .viewer_core import build_chunk_map


def _extract_comments_for_chunk(reviews: dict[str, Any], chunk_id: str) -> tuple[str, dict[str, list[str]]]:
    record = reviews.get(chunk_id, {})
    if not isinstance(record, dict):
        return "", {}

    chunk_comment = str(record.get("comment", "")).strip()
    line_comment_map: dict[str, list[str]] = {}
    raw_line_comments = record.get("lineComments")
    if isinstance(raw_line_comments, list):
        for item in raw_line_comments:
            if not isinstance(item, dict):
                continue
            comment = str(item.get("comment", "")).strip()
            if not comment:
                continue
            old_line = _normalize_line_number(item.get("oldLine"))
            new_line = _normalize_line_number(item.get("newLine"))
            line_type = str(item.get("lineType", ""))
            if line_type not in {"add", "delete", "context", "meta"}:
                if old_line is None and new_line is not None:
                    line_type = "add"
                elif old_line is not None and new_line is None:
                    line_type = "delete"
                elif old_line is not None and new_line is not None:
                    line_type = "context"
                else:
                    line_type = "meta"
            key = _line_anchor_key(line_type, old_line, new_line)
            line_comment_map.setdefault(key, []).append(comment)

    return chunk_comment, line_comment_map


def _resolve_group(doc: dict[str, Any], selector: str | None) -> tuple[str | None, str]:
    groups = safe_groups(doc)
    by_id = {str(group.get("id", "")): group for group in groups}

    if not selector or selector.lower() == "all":
        return None, "All Groups"
    if selector.lower() in {"unassigned", "__unassigned__"}:
        return "__unassigned__", "Unassigned"

    if selector in by_id:
        group_name = str(by_id[selector].get("name", selector))
        return selector, group_name

    matched = [group for group in groups if str(group.get("name", "")) == selector]
    if len(matched) == 1:
        group = matched[0]
        group_id = str(group.get("id", ""))
        group_name = str(group.get("name", group_id))
        return group_id, group_name
    if len(matched) > 1:
        ids = ", ".join(str(group.get("id", "")) for group in matched)
        raise RuntimeError(f"Group name is ambiguous: {selector} (matched ids: {ids})")

    raise RuntimeError(f"Group not found: {selector}")


def _collect_chunks_for_group(doc: dict[str, Any], group_id: str | None) -> list[dict[str, Any]]:
    chunks = [chunk for chunk in (doc.get("chunks") or []) if isinstance(chunk, dict)]
    chunk_map = build_chunk_map(chunks)
    assignments = doc.get("assignments") or {}

    if group_id is None:
        selected = list(chunk_map.values())
    elif group_id == "__unassigned__":
        assigned_ids: set[str] = set()
        if isinstance(assignments, dict):
            for values in assignments.values():
                if isinstance(values, list):
                    assigned_ids.update(str(value) for value in values)
        selected = [chunk for chunk_id, chunk in chunk_map.items() if chunk_id not in assigned_ids]
    else:
        assigned_ids = assignments.get(group_id, [])
        if not isinstance(assigned_ids, list):
            assigned_ids = []
        selected = [chunk_map[cid] for cid in assigned_ids if cid in chunk_map]

    return sorted(
        selected,
        key=lambda chunk: (
            str(chunk.get("filePath", "")),
            int((chunk.get("old") or {}).get("start", 0)),
            str(chunk.get("id", "")),
        ),
    )


def _line_kind_stats(chunks: list[dict[str, Any]]) -> dict[str, int]:
    stats = {"add": 0, "delete": 0, "context": 0}
    for chunk in chunks:
        for line in chunk.get("lines") or []:
            kind = str(line.get("kind", ""))
            if kind in stats:
                stats[kind] += 1
    return stats


def _comment_stats(chunks: list[dict[str, Any]], reviews: dict[str, Any]) -> dict[str, int]:
    chunk_comments = 0
    line_comments = 0
    for chunk in chunks:
        chunk_id = str(chunk.get("id", ""))
        chunk_comment, line_comment_map = _extract_comments_for_chunk(reviews, chunk_id)
        if chunk_comment:
            chunk_comments += 1
        line_comments += sum(len(values) for values in line_comment_map.values())
    return {"chunk": chunk_comments, "line": line_comments, "total": chunk_comments + line_comments}


def _review_progress_stats(chunks: list[dict[str, Any]], reviews: dict[str, Any]) -> dict[str, int]:
    total = len(chunks)
    reviewed = 0
    for chunk in chunks:
        chunk_id = str(chunk.get("id", ""))
        if _status_for_chunk(reviews, chunk_id) == "reviewed":
            reviewed += 1
    rate = int(round((reviewed / total) * 100)) if total > 0 else 0
    return {"total": total, "reviewed": reviewed, "rate": rate}


def _build_review_map_items(doc: dict[str, Any], reviews: dict[str, Any], group_briefs: dict[str, Any]) -> list[str]:
    chunk_map = build_chunk_map(doc)
    assignments = doc.get("assignments") or {}
    items: list[str] = []
    for group in safe_groups(doc):
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            continue
        assigned_ids = assignments.get(group_id, [])
        if not isinstance(assigned_ids, list):
            assigned_ids = []
        chunks = [chunk_map[cid] for cid in assigned_ids if cid in chunk_map]
        if not chunks:
            continue
        first_chunk_id = str(chunks[0].get("id", ""))
        anchor = f"chunk-{_safe_html_id(first_chunk_id)}" if first_chunk_id else "top"
        unresolved = 0
        for chunk in chunks:
            chunk_id = str(chunk.get("id", ""))
            status = _status_for_chunk(reviews, chunk_id)
            chunk_comment, line_comment_map = _extract_comments_for_chunk(reviews, chunk_id)
            if status in {"unreviewed", "needsReReview"} or chunk_comment or any(line_comment_map.values()):
                unresolved += 1
        brief = _normalize_group_brief(group_briefs, group_id) or {}
        brief_status = str(brief.get("status", "none")).strip() or "none"
        brief_label = {"acknowledged": "ack"}.get(brief_status, brief_status)
        summary = str(brief.get("summary", "")).strip() or str(group.get("name", group_id))
        items.append(
            "<li class='review-map-item' data-nav-key='{nav_key}' data-nav-type='group'>"
            "<a class='review-map-link' href='#{anchor}'>"
            "<span class='review-map-head'><span class='review-map-id'>{group_id}</span>"
            "<span class='review-map-brief brief-status brief-status-{brief_status_class}'>{brief_label}</span></span>"
            "<span class='review-map-name'>{group_name}</span>"
            "<span class='review-map-summary'>{summary}</span>"
            "<span class='review-map-meta'>chunks {chunk_count} / unresolved {unresolved}</span>"
            "</a></li>".format(
                nav_key=escape(group_id.lower()),
                anchor=escape(anchor),
                group_id=escape(group_id),
                brief_status_class=escape(brief_status if brief_status in {"draft", "ready", "acknowledged", "stale"} else "draft"),
                brief_label=escape(brief_label),
                group_name=escape(str(group.get("name", group_id))),
                summary=escape(summary),
                chunk_count=escape(str(len(chunks))),
                unresolved=escape(str(unresolved)),
            )
        )
    return items


def _status_for_chunk(reviews: dict[str, Any], chunk_id: str) -> str:
    record = reviews.get(chunk_id, {})
    if not isinstance(record, dict):
        return "unreviewed"
    status = str(record.get("status", "unreviewed"))
    if status not in VALID_REVIEW_STATUSES:
        return "unreviewed"
    return status


def _status_badge_html(status: str) -> str:
    label = {
        "unreviewed": "Unreviewed",
        "reviewed": "Reviewed",
        "ignored": "Ignored",
        "needsReReview": "Re-Review",
    }.get(status, status)
    return "<span class='status-badge status-{status}'>{label}</span>".format(
        status=escape(status),
        label=escape(label),
    )


def _anchor_id_from_file(file_path: str, index: int) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in file_path).strip("-").lower()
    safe = "-".join(part for part in safe.split("-") if part)
    if not safe:
        safe = "file"
    return f"file-{index}-{safe}"


def _safe_html_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in str(value)).strip("-").lower()
    safe = "-".join(part for part in safe.split("-") if part)
    return safe or "id"


def _normalize_group_brief(group_briefs: dict[str, Any], group_id: str | None) -> dict[str, Any] | None:
    if not group_id or group_id == "__unassigned__":
        return None
    return normalize_group_brief_record(group_briefs.get(group_id, {}))


def _render_group_approval_summary(brief: dict[str, Any]) -> str:
    approval = brief.get("approval")
    if not isinstance(approval, dict):
        return ""
    state = str(approval.get("state", "")).strip() or ("approved" if approval.get("approved") else "invalidated")
    by = str(approval.get("approvedBy") or approval.get("revokedBy") or "").strip()
    when = str(
        approval.get("approvedAt")
        or approval.get("revokedAt")
        or approval.get("invalidatedAt")
        or approval.get("decisionAt")
        or ""
    ).strip()
    reason = str(approval.get("invalidationReason", "")).strip()
    parts = [f"<strong>{escape(state.upper())}</strong>"]
    meta: list[str] = []
    if by:
        meta.append(f"by {escape(by)}")
    if when:
        meta.append(escape(when))
    if meta:
        parts.append(" · ".join(meta))
    if reason and state != "approved":
        parts.append(f"reason: {escape(reason)}")
    return "<div class='brief-approval-summary'>Approval: {body}</div>".format(body=" · ".join(parts))


def _render_group_brief_list(title: str, items: list[str]) -> str:
    if not items:
        return ""
    rendered_items = "".join(f"<li>{escape(item)}</li>" for item in items)
    return (
        "<div class='brief-block'><h3>{title}</h3><ul>{items}</ul></div>".format(
            title=escape(title),
            items=rendered_items,
        )
    )


def _render_group_brief_card(group_id: str | None, group_name: str, group_briefs: dict[str, Any]) -> str:
    brief = _normalize_group_brief(group_briefs, group_id)
    if group_id is None or group_id == "__unassigned__":
        return ""
    if brief is None:
        brief = {
            "status": "draft",
            "summary": "",
            "focusPoints": [],
            "testEvidence": [],
            "knownTradeoffs": [],
            "questionsForReviewer": [],
        }
    summary = brief.get("summary", "")
    summary_html = (
        f"<p class='brief-summary'>{escape(summary)}</p>"
        if summary
        else "<p class='brief-empty'>No review handoff yet.</p>"
    )
    return (
        "<section id='group-brief-card' class='group-brief-card' data-group-id='{group_id}' data-brief-status='{status}'>"
        "<div class='group-brief-head'>"
        "<div><p class='eyebrow'>Review Handoff</p><h2>{group_name}</h2></div>"
        "<div class='group-brief-actions'>"
        "<span id='group-brief-status' class='brief-status brief-status-{status}'>{status_label}</span>"
        "<button id='view-group-brief' type='button'>View PR Body</button>"
        "<button id='edit-group-brief' type='button'>Edit Handoff</button>"
        "</div>"
        "</div>"
        "{approval_html}"
        "{summary_html}"
        "{focus_html}"
        "{tests_html}"
        "{tradeoffs_html}"
        "{questions_html}"
        "</section>"
    ).format(
        group_id=escape(group_id),
        status=escape(str(brief.get("status", "draft"))),
        status_label=escape(str(brief.get("status", "draft")).upper()),
        group_name=escape(group_name),
        approval_html=_render_group_approval_summary(brief),
        summary_html=summary_html,
        focus_html=_render_group_brief_list("Focus Points", list(brief.get("focusPoints", []))),
        tests_html=_render_group_brief_list("Test Evidence", list(brief.get("testEvidence", []))),
        tradeoffs_html=_render_group_brief_list("Known Tradeoffs", list(brief.get("knownTradeoffs", []))),
        questions_html=_render_group_brief_list("Questions", list(brief.get("questionsForReviewer", []))),
    )


def _render_diff_rows(chunk: dict[str, Any], line_comment_map: dict[str, list[str]]) -> str:
    rows: list[str] = []
    chunk_id = str(chunk.get("id", ""))
    chunk_key = _safe_html_id(chunk_id[:20] if chunk_id else "chunk")
    for index, line in enumerate(chunk.get("lines") or []):
        kind = str(line.get("kind", "context"))
        old_line = "" if line.get("oldLine") is None else str(line.get("oldLine"))
        new_line = "" if line.get("newLine") is None else str(line.get("newLine"))
        text = str(line.get("text", ""))
        row_id = f"l-{chunk_key}-{index}"
        data_text = text.lower()
        anchor_key = _line_anchor_key(kind, line.get("oldLine"), line.get("newLine"))

        if kind == "add":
            old_text = ""
            new_text = text
            row_class = "add"
        elif kind == "delete":
            old_text = text
            new_text = ""
            row_class = "delete"
        elif kind == "context":
            old_text = text
            new_text = text
            row_class = "context"
        else:
            old_text = text
            new_text = text
            row_class = "meta"

        rows.append(
            "<tr id='{row_id}' class='row-{row_class} diff-row' data-kind='{row_class}' data-line-type='{line_type}' "
            "data-anchor-key='{anchor_key}' data-old-line='{old_line_token}' data-new-line='{new_line_token}' "
            "data-chunk-id='{chunk_id}' data-text='{data_text}'>"
            "<td class='num'>{old_line}</td>"
            "<td class='code old'>{old_text}</td>"
            "<td class='num'>{new_line}<button class='line-comment-btn' type='button' data-action='line-comment' title='Comment this line'>C</button></td>"
            "<td class='code new'>{new_text}</td>"
            "</tr>".format(
                row_id=escape(row_id),
                row_class=escape(row_class),
                line_type=escape(kind),
                anchor_key=escape(anchor_key),
                old_line_token=escape(old_line),
                new_line_token=escape(new_line),
                chunk_id=escape(chunk_id),
                data_text=escape(data_text),
                old_line=(
                    "<a class='line-link' href='#{row_id}'>{value}</a>".format(
                        row_id=escape(row_id),
                        value=escape(old_line),
                    )
                    if old_line
                    else ""
                ),
                old_text=escape(old_text),
                new_line=(
                    "<a class='line-link' href='#{row_id}'>{value}</a>".format(
                        row_id=escape(row_id),
                        value=escape(new_line),
                    )
                    if new_line
                    else ""
                ),
                new_text=escape(new_text),
            )
        )
        for comment in line_comment_map.get(anchor_key, []):
            rows.append(
                "<tr class='row-line-comment diff-row' data-kind='line-comment' data-anchor-key='{anchor_key}' "
                "data-chunk-id='{chunk_id}' data-text='{comment_text}'>"
                "<td class='num'></td>"
                "<td class='code old'></td>"
                "<td class='num'></td>"
                "<td class='code new comment'>"
                "<span class='comment-label'>COMMENT</span> {comment}"
                "</td>"
                "</tr>".format(
                    comment=escape(comment),
                    comment_text=escape(comment.lower()),
                    anchor_key=escape(anchor_key),
                    chunk_id=escape(chunk_id),
                )
            )
    return "\n".join(rows)


def render_group_diff_html(
    doc: dict[str, Any],
    *,
    group_selector: str | None,
    report_title: str | None = None,
    save_state_url: str | None = None,
    save_state_label: str | None = None,
    state_source_label: str | None = None,
    state_diff_report: dict[str, Any] | None = None,
    impact_preview_payload: dict[str, Any] | None = None,
    impact_preview_report: dict[str, Any] | None = None,
    impact_preview_label: str | None = None,
    impact_state_label: str | None = None,
    impact_state_fingerprint: str | None = None,
) -> str:
    group_id, group_name = _resolve_group(doc, group_selector)
    chunks = _collect_chunks_for_group(doc, group_id)
    stats = _line_kind_stats(chunks)
    reviews = doc.get("reviews", {}) if isinstance(doc.get("reviews"), dict) else {}
    group_briefs = doc.get("groupBriefs", {}) if isinstance(doc.get("groupBriefs"), dict) else {}
    comment_stats = _comment_stats(chunks, reviews)
    review_stats = _review_progress_stats(chunks, reviews)
    group_brief_card_html = _render_group_brief_card(group_id, group_name, group_briefs)

    chunks_by_file: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        file_path = str(chunk.get("filePath", "(unknown)"))
        chunks_by_file.setdefault(file_path, []).append(chunk)

    page_title = report_title or f"DiffGR Group Report - {group_name}"
    source = doc.get("meta", {}).get("source", {}) if isinstance(doc.get("meta"), dict) else {}
    base = str(source.get("base", "-"))
    head = str(source.get("head", "-"))

    sidebar_nav: list[str] = []
    file_sections: list[str] = []
    inbox_items: list[dict[str, Any]] = []
    comment_items: list[dict[str, Any]] = []
    for index, (file_path, file_chunks) in enumerate(chunks_by_file.items(), start=1):
        anchor = _anchor_id_from_file(file_path, index)
        file_path_key = file_path.lower()
        add_count = 0
        del_count = 0
        file_comment_total = 0
        for chunk in file_chunks:
            chunk_id = str(chunk.get("id", ""))
            chunk_comment, line_comment_map = _extract_comments_for_chunk(reviews, chunk_id)
            file_comment_total += (1 if chunk_comment else 0) + sum(len(values) for values in line_comment_map.values())
            for line in chunk.get("lines") or []:
                kind = str(line.get("kind", ""))
                if kind == "add":
                    add_count += 1
                elif kind == "delete":
                    del_count += 1

        sidebar_nav.append(
            "<li data-nav-key='{file_key}' data-nav-type='file'><a href='#{anchor}'>{file_path}</a> "
            "<span class='file-stats'>chunks {chunks} / +{adds} -{deletes} / comments {comments}</span></li>".format(
                file_key=escape(file_path_key),
                anchor=escape(anchor),
                file_path=escape(file_path),
                chunks=len(file_chunks),
                adds=add_count,
                deletes=del_count,
                comments=file_comment_total,
            )
        )

        chunk_blocks: list[str] = []
        for chunk in file_chunks:
            chunk_id = str(chunk.get("id", ""))
            old = chunk.get("old") or {}
            new = chunk.get("new") or {}
            header = str(chunk.get("header", ""))
            chunk_anchor = f"chunk-{_safe_html_id(chunk_id)}"
            chunk_status = _status_for_chunk(reviews, chunk_id)
            chunk_comment, line_comment_map = _extract_comments_for_chunk(reviews, chunk_id)
            chunk_line_comment_count = sum(len(values) for values in line_comment_map.values())
            chunk_comment_count = (1 if chunk_comment else 0) + chunk_line_comment_count
            line_entries = list(chunk.get("lines") or [])
            chunk_add_count = sum(1 for line in line_entries if str(line.get("kind", "")) == "add")
            chunk_del_count = sum(1 for line in line_entries if str(line.get("kind", "")) == "delete")
            chunk_change_count = chunk_add_count + chunk_del_count
            risk_score = chunk_change_count + (chunk_line_comment_count * 3)
            if chunk_status == "needsReReview":
                risk_score += 30
            elif chunk_status == "unreviewed":
                risk_score += 16
            elif chunk_status == "reviewed":
                risk_score -= 18
            actionable = bool(
                chunk_status in {"unreviewed", "needsReReview"}
                or chunk_comment_count > 0
                or chunk_change_count >= 36
            )
            actionable_reason: list[str] = []
            if chunk_status in {"unreviewed", "needsReReview"}:
                actionable_reason.append(chunk_status)
            if chunk_comment_count > 0:
                actionable_reason.append("comment")
            if chunk_change_count >= 36:
                actionable_reason.append("large-change")
            chunk_reason_text = ", ".join(actionable_reason) if actionable_reason else "normal"

            chunk_key = _safe_html_id(chunk_id)
            anchor_to_row_id: dict[str, str] = {}
            for line_index, line in enumerate(line_entries):
                key = _line_anchor_key(str(line.get("kind", "")), line.get("oldLine"), line.get("newLine"))
                anchor_to_row_id.setdefault(key, f"l-{chunk_key}-{line_index}")

            if chunk_comment:
                comment_items.append(
                    {
                        "anchor": chunk_anchor,
                        "type": "chunk",
                        "chunk_anchor": chunk_anchor,
                        "file_path": file_path,
                        "chunk_id": chunk_id,
                        "status": chunk_status,
                        "text": chunk_comment,
                    }
                )
            for anchor_key, comments in line_comment_map.items():
                target_anchor = anchor_to_row_id.get(anchor_key, chunk_anchor)
                for comment in comments:
                    comment_items.append(
                        {
                            "anchor": target_anchor,
                            "type": "line",
                            "chunk_anchor": chunk_anchor,
                            "anchor_key": anchor_key,
                            "file_path": file_path,
                            "chunk_id": chunk_id,
                            "status": chunk_status,
                            "text": comment,
                        }
                    )

            inbox_priority = risk_score + (chunk_comment_count * 4)
            if chunk_status == "needsReReview":
                inbox_priority += 70
            elif chunk_status == "unreviewed":
                inbox_priority += 48
            elif chunk_status == "ignored":
                inbox_priority -= 8
            elif chunk_status == "reviewed":
                inbox_priority -= 28
            inbox_items.append(
                {
                    "priority": inbox_priority,
                    "anchor": chunk_anchor,
                    "file_path": file_path,
                    "chunk_id": chunk_id,
                    "header": header,
                    "status": chunk_status,
                    "adds": chunk_add_count,
                    "deletes": chunk_del_count,
                    "comments": chunk_comment_count,
                    "actionable": actionable,
                    "reason": chunk_reason_text,
                    "risk": risk_score,
                }
            )

            chunk_comment_block = ""
            if chunk_comment:
                chunk_comment_block = (
                    "<div class='chunk-comment' data-text='{comment_text}'>"
                    "<span class='comment-label'>COMMENT</span> {comment}"
                    "</div>"
                ).format(comment=escape(chunk_comment), comment_text=escape(chunk_comment.lower()))
            chunk_blocks.append(
                "<details id='{chunk_anchor}' class='chunk' data-chunk-id='{chunk_id}' data-chunk-id-key='{chunk_id_attr}' "
                "data-file-path='{file_path}' data-file-path-key='{file_path_key}' data-header='{header}' data-header-key='{header_attr}' "
                "data-has-comment='{has_comment}' data-line-comment-count='{line_comment_count}' "
                "data-comment-count='{comment_count}' data-status='{status}' data-actionable='{actionable}' "
                "data-reason='{reason}' data-risk='{risk}' open>"
                "<summary class='chunk-header'>"
                "<span class='chunk-id'>{chunk_id}</span>"
                "<span class='chunk-range'>old {old_start},{old_count} -> new {new_start},{new_count}</span>"
                "<span class='chunk-title'>{header}</span>"
                "<span class='chunk-status-slot'>{status_badge}</span>"
                "<label class='review-toggle' title='Mark chunk as reviewed'>"
                "<input class='review-checkbox' type='checkbox' data-action='toggle-reviewed' {review_checked}>"
                "<span>確認済み</span>"
                "</label>"
                "<span class='chunk-comment-count'>comments {comment_count} (line {line_comment_count})</span>"
                "<button class='chunk-comment-btn' type='button' data-action='chunk-comment'>Comment</button>"
                "</summary>"
                "{chunk_comment_block}"
                "<table class='diff-table'>"
                "<colgroup><col class='col-num-old'><col class='col-code-old'><col class='col-num-new'><col class='col-code-new'></colgroup>"
                "<thead><tr><th>Old#</th><th>Old</th><th>New#</th><th>New</th></tr></thead>"
                "<tbody>{rows}</tbody>"
                "</table>"
                "</details>".format(
                    chunk_anchor=escape(chunk_anchor),
                    chunk_id=escape(chunk_id),
                    chunk_id_attr=escape(chunk_id.lower()),
                    file_path=escape(file_path),
                    file_path_key=escape(file_path_key),
                    header=escape(header),
                    header_attr=escape(header.lower()),
                    has_comment="1" if chunk_comment_count > 0 else "0",
                    status=escape(chunk_status),
                    actionable="1" if actionable else "0",
                    reason=escape(chunk_reason_text),
                    risk=escape(str(risk_score)),
                    old_start=escape(str(old.get("start", "?"))),
                    old_count=escape(str(old.get("count", "?"))),
                    new_start=escape(str(new.get("start", "?"))),
                    new_count=escape(str(new.get("count", "?"))),
                    status_badge=_status_badge_html(chunk_status),
                    review_checked="checked" if chunk_status == "reviewed" else "",
                    comment_count=chunk_comment_count,
                    line_comment_count=chunk_line_comment_count,
                    chunk_comment_block=chunk_comment_block,
                    rows=_render_diff_rows(chunk, line_comment_map),
                )
            )

        file_sections.append(
            "<details id='{anchor}' class='file-section' data-file='{file_key}' open>"
            "<summary class='file-summarybar'>"
            "<span class='file-path'>{file_path}</span>"
            "<span class='file-summary'>chunks {chunks} / +{adds} -{deletes} / comments {comments}</span>"
            "</summary>"
            "<div class='file-body'>{chunk_blocks}</div>"
            "</details>".format(
                anchor=escape(anchor),
                file_key=escape(file_path_key),
                file_path=escape(file_path),
                chunks=len(file_chunks),
                adds=add_count,
                deletes=del_count,
                comments=file_comment_total,
                chunk_blocks="\n".join(chunk_blocks),
            )
        )

    if not file_sections:
        file_sections.append("<section class='file-section'><p>No chunks found for selected group.</p></section>")

    inbox_items.sort(
        key=lambda item: (
            0 if item.get("actionable") else 1,
            -int(item.get("priority", 0)),
            str(item.get("file_path", "")),
            str(item.get("chunk_id", "")),
        )
    )
    actionable_count = sum(1 for item in inbox_items if bool(item.get("actionable")))
    inbox_html_parts: list[str] = []
    for item in inbox_items:
        status = str(item.get("status", "unreviewed"))
        status_badge = _status_badge_html(status)
        actionable = bool(item.get("actionable"))
        inbox_html_parts.append(
            "<li class='inbox-item {actionable_class}' data-actionable='{actionable_attr}' data-status='{status}' "
            "data-risk='{risk}' data-text='{text_blob}'>"
            "<a class='inbox-link' href='#{anchor}'>"
            "<span class='inbox-head'><span class='inbox-file'>{file_path}</span> <span class='inbox-chunk'>{chunk_id}</span></span>"
            "<span class='inbox-meta'>{status_badge} <span class='risk-badge'>risk {risk}</span> "
            "<span class='delta-badge'>+{adds}/-{deletes}</span> <span class='comment-count-badge'>comments {comments}</span></span>"
            "<span class='inbox-title'>{header}</span>"
            "<span class='inbox-reason'>{reason}</span>"
            "</a>"
            "</li>".format(
                actionable_class="is-actionable" if actionable else "is-normal",
                actionable_attr="1" if actionable else "0",
                status=escape(status),
                risk=escape(str(item.get("risk", 0))),
                text_blob=escape(
                    (
                        str(item.get("file_path", ""))
                        + " "
                        + str(item.get("chunk_id", ""))
                        + " "
                        + str(item.get("header", ""))
                        + " "
                        + str(item.get("reason", ""))
                    ).lower()
                ),
                anchor=escape(str(item.get("anchor", ""))),
                file_path=escape(str(item.get("file_path", ""))),
                chunk_id=escape(str(item.get("chunk_id", ""))[:12]),
                status_badge=status_badge,
                adds=escape(str(item.get("adds", 0))),
                deletes=escape(str(item.get("deletes", 0))),
                comments=escape(str(item.get("comments", 0))),
                header=escape(str(item.get("header", "")) or "(no header)"),
                reason=escape(str(item.get("reason", ""))),
            )
        )
    inbox_items_html = "\n".join(inbox_html_parts) if inbox_html_parts else "<li class='inbox-empty'>(no chunks)</li>"

    comment_items.sort(
        key=lambda item: (
            0 if str(item.get("status", "")) in {"unreviewed", "needsReReview"} else 1,
            str(item.get("file_path", "")),
            str(item.get("chunk_id", "")),
            str(item.get("type", "")),
        )
    )
    comment_html_parts: list[str] = []
    unresolved_comment_count = 0
    for index, item in enumerate(comment_items, start=1):
        status = str(item.get("status", "unreviewed"))
        unresolved = status in {"unreviewed", "needsReReview"}
        if unresolved:
            unresolved_comment_count += 1
        status_badge = _status_badge_html(status)
        item_type = str(item.get("type", "line"))
        item_type_label = "CHUNK" if item_type == "chunk" else "LINE"
        comment_html_parts.append(
            "<li class='comment-item' data-status='{status}' data-unresolved='{unresolved}' data-type='{item_type}' "
            "data-chunk-id='{chunk_id_full}' data-anchor-key='{anchor_key}' data-chunk-anchor='{chunk_anchor}' data-text='{text_blob}'>"
            "<a class='comment-jump' href='#{anchor}'>#{idx}</a>"
            "<div class='comment-body'>"
            "<div class='comment-meta'>"
            "<span class='comment-file'>{file_path}</span>"
            "<span class='comment-chunk'>{chunk_id}</span>"
            "<span class='comment-type'>{item_type_label}</span>"
            "{status_badge}"
            "<button class='comment-edit-btn' type='button' data-action='edit-comment-item'>Edit</button>"
            "</div>"
            "<p class='comment-text'>{comment_text}</p>"
            "</div>"
            "</li>".format(
                status=escape(status),
                unresolved="1" if unresolved else "0",
                item_type=escape(item_type),
                chunk_id_full=escape(str(item.get("chunk_id", ""))),
                anchor_key=escape(str(item.get("anchor_key", ""))),
                chunk_anchor=escape(str(item.get("chunk_anchor", ""))),
                text_blob=escape(
                    (
                        str(item.get("file_path", ""))
                        + " "
                        + str(item.get("chunk_id", ""))
                        + " "
                        + str(item.get("text", ""))
                    ).lower()
                ),
                anchor=escape(str(item.get("anchor", ""))),
                idx=escape(str(index)),
                file_path=escape(str(item.get("file_path", ""))),
                chunk_id=escape(str(item.get("chunk_id", ""))[:12]),
                item_type_label=escape(item_type_label),
                status_badge=status_badge,
                comment_text=escape(str(item.get("text", ""))),
            )
        )
    comment_items_html = "\n".join(comment_html_parts) if comment_html_parts else "<li class='comment-empty'>(no comments)</li>"
    if group_id is None:
        sidebar_nav = _build_review_map_items(doc, reviews, group_briefs)
    sidebar_nav_title = "Review Map" if group_id is None else "Files"

    report_config = {
        "saveStateUrl": str(save_state_url or "").strip(),
        "saveStateLabel": str(save_state_label or "Save State").strip() or "Save State",
        "currentGroupId": group_id or "",
        "stateSourceLabel": ("overlay:" + str(state_source_label).strip()) if str(state_source_label or "").strip() else "embedded",
        "stateDiffReport": state_diff_report if isinstance(state_diff_report, dict) else None,
        "impactPreviewReport": impact_preview_report if isinstance(impact_preview_report, dict) else None,
        "impactPreviewLabel": str(impact_preview_label or "").strip(),
        "impactStateLabel": str(impact_state_label or "").strip(),
        "impactStateFingerprint": str(impact_state_fingerprint or "").strip(),
    }
    impact_toggle_html = ""
    impact_panel_html = ""
    impact_report: dict[str, Any] | None = None
    if isinstance(impact_preview_report, dict):
        impact_report = impact_preview_report
    elif isinstance(impact_preview_payload, dict):
        impact_report = build_impact_preview_report(
            impact_preview_payload,
            old_label="old",
            new_label="new",
            state_label="state",
        )
    if isinstance(impact_report, dict):
        if not isinstance(impact_preview_report, dict) and str(impact_preview_label or "").strip():
            impact_report = {
                **impact_report,
                "sourceLabel": str(impact_preview_label or "").strip(),
                "title": "Impact Preview: " + str(impact_preview_label or "").strip(),
            }
        report_config["impactPreviewReport"] = impact_report
        impact_display_source_label = str(impact_report.get("sourceLabel", "") or "").strip()
        if not impact_display_source_label and str(impact_preview_label or "").strip():
            impact_display_source_label = str(impact_preview_label or "").strip()
        impact_summary = impact_report.get("impactSummary", {})
        if not isinstance(impact_summary, dict):
            impact_summary = {}
        warning_summary = impact_report.get("warningSummary", {})
        if not isinstance(warning_summary, dict):
            warning_summary = {}
        warning_kinds = warning_summary.get("kinds", {})
        if not isinstance(warning_kinds, dict):
            warning_kinds = {}
        change_summary = impact_report.get("changeSummary", {})
        if not isinstance(change_summary, dict):
            change_summary = {}
        state_diff = impact_report.get("stateDiff", {})
        if not isinstance(state_diff, dict):
            state_diff = {}
        group_brief_changes = impact_report.get("groupBriefChanges", [])
        if not isinstance(group_brief_changes, list):
            group_brief_changes = []
        impacted_groups = impact_report.get("impactedGroups", [])
        if not isinstance(impacted_groups, list):
            impacted_groups = []
        affected_briefs = impact_report.get("affectedBriefs", [])
        if not isinstance(affected_briefs, list):
            affected_briefs = []
        selection_plans = impact_report.get("selectionPlans", {})
        if not isinstance(selection_plans, dict):
            selection_plans = {}
        impacted_items: list[str] = []
        for item in impacted_groups:
            if not isinstance(item, dict):
                continue
            impacted_items.append(
                "<li><b>{group_id}</b> {name} <span class='file-stats'>changed {changed} / new {new} / removed {removed}</span></li>".format(
                    group_id=escape(str(item.get("groupId", ""))),
                    name=escape(str(item.get("name", ""))),
                    changed=escape(str(item.get("changed", 0))),
                    new=escape(str(item.get("new", 0))),
                    removed=escape(str(item.get("removed", 0))),
                )
            )
        brief_items: list[str] = []
        for item in affected_briefs:
            if not isinstance(item, dict):
                continue
            brief_items.append(
                (
                    "<li><b>{group_id}</b> "
                    "<span class='status-badge status-{status_key}'>{status}</span> "
                    "<span>{summary}</span> "
                    "<span class='file-stats'>focus {focus} / tests {tests} / questions {questions}</span></li>"
                ).format(
                    group_id=escape(str(item.get("groupId", ""))),
                    status_key=escape(_safe_html_id(str(item.get("status", "") or "draft"))),
                    status=escape(str(item.get("status", "") or "-")),
                    summary=escape(str(item.get("summary", "") or "-")),
                    focus=escape(str(item.get("focusPointsCount", 0))),
                    tests=escape(str(item.get("testEvidenceCount", 0))),
                    questions=escape(str(item.get("questionsCount", 0))),
                )
            )
        group_change_items: list[str] = []
        for item in group_brief_changes:
            if not isinstance(item, dict):
                continue
            before = item.get("before", {}) if isinstance(item.get("before"), dict) else {}
            after = item.get("after", {}) if isinstance(item.get("after"), dict) else {}
            group_change_items.append(
                (
                    "<li><b>{group_id}</b> "
                    "<span class='file-stats'>{kind}</span> "
                    "<span>status {before_status} -&gt; {after_status}</span> "
                    "<span class='file-stats'>summary {before_summary} -&gt; {after_summary}</span></li>"
                ).format(
                    group_id=escape(str(item.get("groupId", ""))),
                    kind=escape(str(item.get("changeKind", ""))),
                    before_status=escape(str(before.get("status", "") or "-")),
                    after_status=escape(str(after.get("status", "") or "-")),
                    before_summary=escape(str(before.get("summary", "") or "-")),
                    after_summary=escape(str(after.get("summary", "") or "-")),
                )
            )
        selection_plan_items: list[str] = []
        for plan_name in ("handoffs", "reviews", "ui", "all"):
            plan = selection_plans.get(plan_name, {})
            if not isinstance(plan, dict):
                plan = {}
            tokens = [str(item) for item in plan.get("tokens", []) if str(item)]
            selection_plan_items.append(
                (
                    "<li data-impact-plan='{plan}' data-impact-tokens='{tokens_json}'>"
                    "<div><b>{plan}</b> <span class='file-stats'>count {count}</span></div>"
                    "<pre class='comment-text'>{tokens_text}</pre>"
                    "<div class='group-brief-actions'>"
                    "<button type='button' data-action='copy-impact-plan'>Copy Tokens</button>"
                    "<button type='button' data-action='apply-impact-plan'>Apply These Tokens</button>"
                    "</div>"
                    "</li>"
                ).format(
                    plan=escape(plan_name),
                    count=escape(str(plan.get("count", len(tokens)))),
                    tokens_text=escape("\n".join(tokens) if tokens else "(no tokens)"),
                    tokens_json=escape(json.dumps(tokens, ensure_ascii=False)),
                )
            )
        diff_rows = list(iter_review_state_diff_rows(state_diff))
        state_diff_items: list[str] = []
        for section_name in ("reviews", "groupBriefs", "analysisState", "threadState"):
            section = state_diff.get(section_name, {}) if isinstance(state_diff.get(section_name), dict) else {}
            state_diff_items.append(
                "<li><b>{section}</b> <span class='file-stats'>added {added} / removed {removed} / changed {changed} / unchanged {unchanged}</span></li>".format(
                    section=escape(section_name),
                    added=escape(str(section.get("addedCount", 0))),
                    removed=escape(str(section.get("removedCount", 0))),
                    changed=escape(str(section.get("changedCount", 0))),
                    unchanged=escape(str(section.get("unchangedCount", 0))),
                )
            )
            for row in diff_rows:
                if str(row.get("section", "")) != section_name:
                    continue
                state_diff_items.append(
                    "<li><span>{key}</span> <span class='file-stats'>{preview}</span></li>".format(
                        key=escape(str(row.get("key", ""))),
                        preview=escape(str(row.get("preview", ""))),
                    )
                )
        impact_toggle_html = '<button id="toggle-impact-preview" type="button">Impact Preview</button>'
        impact_panel_html = """
      <section id="impact-preview-panel" class="inbox-panel" hidden>
        <div class="inbox-headbar">
          <h2>Impact Preview</h2>
          <p class="inbox-sub">{impact_label}</p>
        </div>
        <p class="stats">
          source <span class="v">{source_label}</span>
        </p>
        <p class="stats">
          carried reviews <span class="v">{carried_reviews}</span> / changed to needsReReview <span class="v">{changed_to_needs_rereview}</span> /
          unmapped new chunks <span class="v">{unmapped_new_chunks}</span>
        </p>
        <p class="stats">
          changed groups <span class="v">{changed_groups}</span> / unchanged groups <span class="v">{unchanged_groups}</span> /
          new only <span class="v">{new_only}</span> / old only <span class="v">{old_only}</span>
        </p>
        <p class="stats">
          warnings: status <span class="v">{status_conflict}</span> / chunk comment <span class="v">{chunk_comment_conflict}</span> /
          brief <span class="v">{brief_conflict}</span> / invalid <span class="v">{invalid_count}</span> /
          rebase weak <span class="v">{rebase_weak}</span> / unmapped <span class="v">{rebase_unmapped}</span>
        </p>
        <div class="group-brief-card-grid">
          <section class="group-brief-card">
            <h3>Impact</h3>
            <ol class="comment-list">{impacted_items}</ol>
          </section>
          <section class="group-brief-card">
            <h3>Group Brief Changes</h3>
            <ol class="comment-list">{group_change_items}</ol>
          </section>
          <section class="group-brief-card">
            <h3>Affected Briefs</h3>
            <ol class="comment-list">{brief_items}</ol>
          </section>
          <section class="group-brief-card">
            <h3>Selection Plans</h3>
            <p id="impact-plan-status" class="stats"></p>
            <ol class="comment-list">{selection_plan_items}</ol>
          </section>
          <section class="group-brief-card">
            <h3>State Diff</h3>
            <ol class="comment-list">{state_diff_items}</ol>
          </section>
        </div>
      </section>
""".format(
            impact_label=escape(str(impact_preview_label or "impact preview")),
            source_label=escape(impact_display_source_label or str(impact_report.get("sourceLabel", "") or "-")),
            carried_reviews=escape(str(change_summary.get("carriedReviews", 0))),
            changed_to_needs_rereview=escape(str(change_summary.get("changedToNeedsReReview", 0))),
            unmapped_new_chunks=escape(str(change_summary.get("unmappedNewChunks", 0))),
            changed_groups=escape(str(impact_summary.get("impactedGroupCount", 0))),
            unchanged_groups=escape(str(impact_summary.get("unchangedGroupCount", 0))),
            new_only=escape(str(len(impact_summary.get("newOnlyChunkIds", []) or []))),
            old_only=escape(str(len(impact_summary.get("oldOnlyChunkIds", []) or []))),
            status_conflict=escape(str(warning_kinds.get("statusConflict", 0))),
            chunk_comment_conflict=escape(str(warning_kinds.get("chunkCommentConflict", 0))),
            brief_conflict=escape(str(warning_kinds.get("groupBriefConflict", 0))),
            invalid_count=escape(
                str(
                    int(warning_kinds.get("invalidReviewRecord", 0))
                    + int(warning_kinds.get("invalidGroupBriefRecord", 0))
                )
            ),
            rebase_weak=escape(str(warning_kinds.get("rebaseWeakMatch", 0))),
            rebase_unmapped=escape(str(warning_kinds.get("rebaseUnmappedChunk", 0))),
            impacted_items="".join(impacted_items) if impacted_items else "<li>(no impacted groups)</li>",
            group_change_items="".join(group_change_items) if group_change_items else "<li>(no group brief changes)</li>",
            brief_items="".join(brief_items) if brief_items else "<li>(no affected briefs)</li>",
            state_diff_items="".join(state_diff_items) if state_diff_items else "<li>(no state diff)</li>",
            selection_plan_items="".join(selection_plan_items) if selection_plan_items else "<li>(no selection plans)</li>",
        )
    return """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <style>
    :root {{
      --bg: #0b0d11;
      --panel: #121722;
      --panel2: #0f1420;
      --line: #243041;
      --text: #e8edf5;
      --muted: #9aabc1;
      --add-bg: #0f2a1f;
      --add-line: #1f6e48;
      --del-bg: #34171a;
      --del-line: #7d2c35;
      --ctx-bg: #121722;
      --meta-bg: #1b2232;
      --accent: #5ea3ff;
      --diff-font: 12px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "Yu Gothic UI", "Meiryo", sans-serif;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    .layout {{
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr) 360px;
      min-height: 100vh;
    }}
    .sidebar {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      background: var(--panel);
      border-right: 1px solid var(--line);
      padding: 16px;
    }}
    .main {{
      padding: 18px;
      overflow: auto;
    }}
    .comment-pane {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      background: #101826;
      border-left: 1px solid var(--line);
      padding: 14px 12px;
    }}
    .group-brief-card {{
      background: linear-gradient(135deg, #121d30, #0f1624);
      border: 1px solid #2a3b56;
      border-radius: 14px;
      padding: 16px 18px;
      margin-bottom: 16px;
    }}
    .group-brief-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      margin-bottom: 10px;
    }}
    .group-brief-head h2 {{
      margin: 2px 0 0;
      font-size: 18px;
    }}
    .eyebrow {{
      margin: 0;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #8fb5ef;
    }}
    .group-brief-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .brief-status {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }}
    .brief-status-draft {{ background: #3a2d12; color: #ffd88a; }}
    .brief-status-ready {{ background: #133826; color: #9df0ba; }}
    .brief-status-acknowledged {{ background: #173556; color: #b2d5ff; }}
    .brief-status-stale {{ background: #4a1f28; color: #ffb4c2; }}
    .group-brief-actions button {{
      border: 1px solid #35527d;
      border-radius: 8px;
      background: #172946;
      color: #e6f0ff;
      padding: 8px 12px;
      cursor: pointer;
    }}
    .brief-summary, .brief-empty {{
      margin: 0 0 12px;
      color: #d8e4f7;
      line-height: 1.6;
    }}
    .brief-empty {{ color: var(--muted); }}
    .brief-block {{
      margin-top: 10px;
    }}
    .brief-block h3 {{
      margin: 0 0 6px;
      font-size: 12px;
      color: #9fb9db;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .brief-block ul {{
      margin: 0;
      padding-left: 18px;
      color: #dde7f7;
    }}
    .comment-pane-head h2 {{
      margin: 0 0 4px;
      font-size: 18px;
      color: #d4e2f7;
    }}
    .comment-pane-stats {{
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 12px;
    }}
    .comment-controls {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 6px;
      margin-bottom: 8px;
    }}
    .comment-controls input {{
      width: 100%;
      border: 1px solid #334a6b;
      border-radius: 8px;
      background: #0b1220;
      color: #e8edf5;
      padding: 7px 9px;
      font-size: 12px;
    }}
    .comment-controls button {{
      border: 1px solid #335383;
      border-radius: 8px;
      background: #13233d;
      color: #d7e6ff;
      padding: 7px 10px;
      font-size: 12px;
      cursor: pointer;
      white-space: nowrap;
    }}
    .comment-controls button[aria-pressed="true"] {{
      border-color: #7eb2ff;
      background: #203b66;
      color: #ffffff;
      font-weight: 600;
    }}
    .comment-list {{
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 8px;
    }}
    .comment-item {{
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 8px;
      border: 1px solid #2b3a52;
      border-radius: 10px;
      background: #0d1522;
      padding: 8px;
    }}
    .comment-jump {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 28px;
      height: 28px;
      border-radius: 8px;
      border: 1px solid #3a5d90;
      background: #12233c;
      color: #cfe2ff;
      font-weight: 700;
      font-size: 11px;
      text-decoration: none;
    }}
    .comment-body {{
      min-width: 0;
    }}
    .comment-meta {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin-bottom: 4px;
      font-size: 11px;
      color: #a9bdd9;
    }}
    .comment-file {{
      color: #cddcf2;
      font-weight: 600;
      word-break: break-all;
    }}
    .comment-chunk {{
      color: #93abca;
      font-family: Consolas, "Courier New", monospace;
    }}
    .comment-type {{
      border-radius: 999px;
      padding: 1px 7px;
      border: 1px solid #3a4a64;
      background: #162033;
      color: #d2dff5;
      font-size: 10px;
      font-weight: 700;
    }}
    .comment-edit-btn {{
      margin-left: auto;
      border: 1px solid #4d6ea3;
      border-radius: 7px;
      background: #162746;
      color: #d8e8ff;
      font-size: 11px;
      line-height: 1;
      padding: 4px 8px;
      cursor: pointer;
    }}
    .comment-edit-btn:hover {{
      background: #214172;
    }}
    .comment-text {{
      margin: 0;
      color: #f2f6fd;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .status-badge {{
      border-radius: 999px;
      padding: 1px 8px;
      border: 1px solid #35527a;
      background: #13233f;
      color: #d9e8ff;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .02em;
    }}
    .status-unreviewed {{ border-color: #7f9ccc; background: #203357; color: #e9f2ff; }}
    .status-reviewed {{ border-color: #3b7d5f; background: #173126; color: #c8f4db; }}
    .status-ignored {{ border-color: #5f6a7c; background: #202734; color: #d1d7e1; }}
    .status-needsReReview {{ border-color: #9f6f2d; background: #3d2910; color: #ffe0a9; }}
    .main-toolbar {{
      position: sticky;
      top: 0;
      z-index: 3;
      display: grid;
      grid-template-columns: minmax(220px, 1fr) repeat(7, auto) auto;
      gap: 8px;
      align-items: center;
      padding: 10px;
      margin-bottom: 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #0e1625cc;
      backdrop-filter: blur(3px);
    }}
    .main-toolbar input {{
      width: 100%;
      border: 1px solid #334a6b;
      border-radius: 8px;
      background: #0b1220;
      color: #e8edf5;
      padding: 8px 10px;
      font-size: 12px;
    }}
    .main-toolbar button {{
      border: 1px solid #335383;
      border-radius: 8px;
      background: #13233d;
      color: #d7e6ff;
      padding: 8px 10px;
      font-size: 12px;
      cursor: pointer;
      white-space: nowrap;
    }}
    .main-toolbar button:hover {{
      background: #1a3155;
    }}
    .main-toolbar button[aria-pressed="true"] {{
      border-color: #7eb2ff;
      background: #203b66;
      color: #ffffff;
      font-weight: 600;
    }}
    .main-help {{
      margin: 0 0 12px;
      font-size: 12px;
      color: var(--muted);
    }}
    .main-help a {{
      color: #9fc4ff;
      text-decoration: underline;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 20px;
    }}
    h2 {{
      margin: 0 0 8px;
      font-size: 18px;
      color: #c8d8ef;
    }}
    .meta {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .stats {{
      margin: 8px 0 12px;
      color: var(--muted);
      font-size: 13px;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 6px;
    }}
    .stat {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 6px 8px;
      background: #0d1320;
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 8px;
    }}
    .stat .k {{
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .03em;
    }}
    .stat .v {{
      color: #eaf1fb;
      font-size: 14px;
      font-weight: 700;
    }}
    .controls {{
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 6px;
      margin-bottom: 8px;
    }}
    .controls input {{
      width: 100%;
      border: 1px solid #334a6b;
      border-radius: 8px;
      background: #0b1220;
      color: #e8edf5;
      padding: 7px 10px;
      font-size: 12px;
    }}
    .controls button {{
      border: 1px solid #335383;
      border-radius: 8px;
      background: #13233d;
      color: #d7e6ff;
      padding: 7px 10px;
      font-size: 12px;
      cursor: pointer;
    }}
    .controls button:hover {{
      background: #1a3155;
    }}
    .filter-hit {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 12px;
    }}
    .save-status-ok {{
      color: #9ed8b0;
    }}
    .save-status-error {{
      color: #ffb9c0;
      font-weight: 700;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 0 0 12px;
    }}
    .chip {{
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 11px;
      border: 1px solid var(--line);
      color: #d3deee;
      background: #111a2a;
    }}
    .chip.add {{ background: #123024; border-color: #24563f; }}
    .chip.del {{ background: #3a171d; border-color: #6d2d38; }}
    .chip.ctx {{ background: #1a2233; border-color: #2a3a54; }}
    .chip.cmt {{ background: #2a2110; border-color: #6f5b2d; color: #f6e6c0; }}
    .file-list {{
      margin: 0;
      padding-left: 18px;
      line-height: 1.6;
      font-size: 13px;
    }}
    .sidebar-nav-title {{
      margin: 0 0 8px;
      font-size: 13px;
      color: #c8d8ef;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    .review-map-item {{
      list-style: none;
      margin: 0 0 8px;
      padding: 0;
    }}
    .review-map-link {{
      display: grid;
      gap: 4px;
      border: 1px solid #31435d;
      border-radius: 10px;
      background: #0d1422;
      padding: 8px 10px;
      text-decoration: none;
    }}
    .review-map-head {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
    }}
    .review-map-id {{
      font-size: 11px;
      font-family: Consolas, "Courier New", monospace;
      color: #8db8ff;
    }}
    .review-map-name {{
      color: #ebf2ff;
      font-size: 13px;
      font-weight: 700;
      word-break: break-word;
    }}
    .review-map-summary {{
      color: #b5c6de;
      font-size: 12px;
      line-height: 1.4;
      word-break: break-word;
    }}
    .review-map-meta {{
      color: var(--muted);
      font-size: 11px;
    }}
    .file-stats {{ color: var(--muted); }}
    .inbox-panel {{
      margin: 0 0 12px;
      border: 1px solid #33435d;
      border-radius: 10px;
      background: #101a2a;
      padding: 10px;
    }}
    .inbox-headbar {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 8px;
      margin-bottom: 8px;
    }}
    .inbox-headbar h2 {{
      margin: 0;
      font-size: 16px;
      color: #d3e3fb;
    }}
    .inbox-sub {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
    }}
    .inbox-list {{
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 8px;
    }}
    .inbox-item {{
      border: 1px solid #2b3a52;
      border-radius: 10px;
      background: #0f1726;
      overflow: hidden;
    }}
    .inbox-item.is-actionable {{
      border-color: #4e76aa;
      box-shadow: inset 0 0 0 1px #4e76aa33;
    }}
    .inbox-link {{
      display: grid;
      gap: 4px;
      padding: 8px 10px;
      text-decoration: none;
    }}
    .inbox-head {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 12px;
      color: #d7e4f8;
    }}
    .inbox-file {{
      font-weight: 600;
      word-break: break-all;
    }}
    .inbox-chunk {{
      color: #95aecf;
      font-family: Consolas, "Courier New", monospace;
    }}
    .inbox-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      font-size: 11px;
      color: #b8c8df;
    }}
    .risk-badge, .delta-badge, .comment-count-badge {{
      border-radius: 999px;
      padding: 1px 8px;
      border: 1px solid #3c4f6e;
      background: #162235;
      color: #d6e5ff;
      font-size: 10px;
      font-weight: 700;
    }}
    .inbox-title {{
      color: #e8eef9;
      font-size: 13px;
      font-weight: 600;
      line-height: 1.35;
      word-break: break-word;
    }}
    .inbox-reason {{
      color: var(--muted);
      font-size: 11px;
      text-transform: lowercase;
    }}
    .file-section {{
      margin-bottom: 28px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
      overflow: hidden;
    }}
    .file-summarybar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px 12px;
      margin: 0;
      cursor: pointer;
      padding: 11px 14px;
      background: #121b2b;
      border-bottom: 1px solid var(--line);
      list-style: none;
    }}
    .file-summarybar::-webkit-details-marker {{ display: none; }}
    .file-path {{
      font-size: 15px;
      font-weight: 600;
      color: #c8d8ef;
      word-break: break-all;
    }}
    .file-summary {{
      color: var(--muted);
      font-size: 13px;
    }}
    .file-body {{
      padding: 12px;
    }}
    .chunk {{
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 14px;
      overflow: hidden;
      background: var(--panel2);
    }}
    .chunk-header {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      font-size: 12px;
      background: #1a2233;
      cursor: pointer;
      list-style: none;
    }}
    .chunk-comment-btn {{
      margin-left: 0;
      border: 1px solid #48679a;
      border-radius: 8px;
      background: #152744;
      color: #d7e6ff;
      padding: 4px 8px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
    }}
    .chunk-comment-btn:hover {{
      background: #1d355c;
    }}
    .chunk-header::-webkit-details-marker {{ display: none; }}
    .chunk[open] > .chunk-header {{
      background: #1e2940;
    }}
    .chunk-id {{ color: #9bc0ff; font-weight: 600; }}
    .chunk-range {{ color: #b6c5dc; }}
    .chunk-title {{ color: #d2def0; }}
    .chunk-status-slot {{
      display: inline-flex;
      align-items: center;
    }}
    .review-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-left: 2px;
      border: 1px solid #38537b;
      border-radius: 999px;
      padding: 2px 8px;
      background: #13233f;
      color: #d9e8ff;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
      user-select: none;
    }}
    .review-checkbox {{
      width: 14px;
      height: 14px;
      accent-color: #52d083;
      cursor: pointer;
      margin: 0;
    }}
    .chunk-comment-count {{
      margin-left: auto;
      color: #f7d896;
      font-weight: 600;
    }}
    .chunk-comment {{
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      background: #2a2110;
      color: #f5e9c8;
      font-size: 13px;
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .comment-label {{
      display: inline-block;
      margin-right: 6px;
      padding: 1px 6px;
      border-radius: 999px;
      background: #ffda85;
      color: #3d2a00;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .02em;
    }}
    .diff-table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
    }}
    .diff-table th {{
      text-align: left;
      padding: 6px 8px;
      border-bottom: 1px solid var(--line);
      color: #c5d4eb;
      background: #151c2b;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    .diff-table td {{
      border-bottom: 1px solid #1a2232;
      vertical-align: top;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .diff-table td.num {{
      width: 68px;
      text-align: right;
      padding: 4px 8px;
      color: var(--muted);
      background: #101624;
      white-space: nowrap;
    }}
    .diff-table td.code {{
      padding: 4px 8px;
      font-family: Consolas, "Courier New", monospace;
    }}
    .diff-table {{
      font-size: var(--diff-font);
    }}
    .line-link {{
      color: #94b9f7;
      text-decoration: none;
    }}
    .line-link:hover {{
      text-decoration: underline;
    }}
    .line-comment-btn {{
      margin-left: 6px;
      border: 1px solid #4b6fa7;
      border-radius: 6px;
      background: #162746;
      color: #d8e8ff;
      font-size: 10px;
      line-height: 1;
      padding: 2px 5px;
      cursor: pointer;
      vertical-align: middle;
    }}
    .line-comment-btn:hover {{
      background: #214172;
    }}
    .diff-row.match td.code {{
      box-shadow: inset 0 0 0 1px #7fb4ff66;
    }}
    .diff-row:target td.code {{
      box-shadow: inset 0 0 0 2px #7fb4ffcc;
    }}
    .diff-row:target td.num {{
      box-shadow: inset 0 0 0 2px #7fb4ff66;
    }}
    .chunk.hidden-by-filter {{
      display: none !important;
    }}
    .file-section.hidden-by-filter {{
      display: none !important;
    }}
    body.no-wrap .diff-table td.code {{
      white-space: pre;
      overflow-x: auto;
    }}
    body.compact .chunk-header {{
      padding: 5px 8px;
      font-size: 11px;
    }}
    body.compact .chunk-comment {{
      padding: 6px 8px;
      font-size: 12px;
    }}
    body.compact .diff-table {{
      font-size: calc(var(--diff-font) - 1px);
    }}
    body.compact .diff-table td.num {{
      padding: 2px 6px;
      width: 58px;
    }}
    body.compact .diff-table td.code {{
      padding: 2px 6px;
    }}
    #diff-split-handle {{
      position: fixed;
      top: 0;
      width: 6px;
      height: 100vh;
      cursor: col-resize;
      z-index: 200;
      background: transparent;
      pointer-events: auto;
    }}
    #diff-split-handle::after {{
      content: '';
      position: absolute;
      left: 2px;
      top: 0;
      width: 2px;
      height: 100%;
      background: #3b82f6;
      opacity: 0;
      transition: opacity 0.15s;
    }}
    #diff-split-handle:hover::after,
    #diff-split-handle.dragging::after {{
      opacity: 0.7;
    }}
    .row-context td.code {{ background: var(--ctx-bg); }}
    .row-add td.code {{
      background: var(--add-bg);
      border-left: 2px solid var(--add-line);
    }}
    .row-delete td.code {{
      background: var(--del-bg);
      border-left: 2px solid var(--del-line);
    }}
    .row-meta td.code {{ background: var(--meta-bg); color: #c7d2e8; }}
    .row-line-comment td.code.comment {{
      background: #2a2110;
      color: #f5e9c8;
      border-left: 2px solid #d6a949;
      font-style: italic;
    }}
    .comment-modal {{
      width: min(760px, calc(100vw - 36px));
      max-height: calc(100vh - 36px);
      border: 1px solid #3d5071;
      border-radius: 12px;
      background: #0f1828;
      color: #e8edf5;
      padding: 0;
    }}
    .comment-modal::backdrop {{
      background: rgba(2, 6, 13, 0.72);
      backdrop-filter: blur(2px);
    }}
    .comment-modal-form {{
      display: grid;
      gap: 10px;
      padding: 14px;
    }}
    .comment-modal-title {{
      margin: 0;
      font-size: 18px;
      color: #d8e7ff;
    }}
    .comment-modal-sub {{
      margin: 0;
      color: #a9bdd9;
      font-size: 12px;
    }}
    .comment-modal-textarea {{
      width: 100%;
      min-height: 160px;
      resize: vertical;
      border: 1px solid #35527a;
      border-radius: 8px;
      background: #0a1220;
      color: #edf4ff;
      font-size: 13px;
      line-height: 1.45;
      padding: 10px;
      font-family: "Segoe UI", "Yu Gothic UI", "Meiryo", sans-serif;
    }}
    .comment-modal-actions {{
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .comment-modal-actions button {{
      border: 1px solid #35527a;
      border-radius: 8px;
      background: #152744;
      color: #d7e6ff;
      padding: 7px 12px;
      font-size: 12px;
      cursor: pointer;
    }}
    .comment-modal-actions button:hover {{
      background: #1e365d;
    }}
    .comment-modal-actions .primary {{
      border-color: #4f8eff;
      background: #2354a7;
      color: #ffffff;
      font-weight: 700;
    }}
    .comment-modal-actions .danger {{
      border-color: #9a5a61;
      background: #4d2529;
      color: #ffe2e4;
    }}
    .brief-viewer-head {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }}
    .brief-viewer-head .comment-modal-title {{
      margin: 0;
      flex: 1;
    }}
    .brief-viewer-body {{
      overflow-y: auto;
      flex: 1;
      padding: 4px 0;
    }}
    .brief-viewer-summary {{
      line-height: 1.6;
      margin: 0 0 12px;
      color: #d7e6ff;
    }}
    .brief-viewer-section {{
      margin-bottom: 12px;
    }}
    .brief-viewer-label {{
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .05em;
      color: #7a9dc8;
      margin: 0 0 4px;
    }}
    .brief-viewer-section ul {{
      margin: 0;
      padding-left: 18px;
      color: #c8d9f0;
    }}
    .brief-viewer-section li {{
      margin-bottom: 4px;
      line-height: 1.5;
    }}
    @media (max-width: 1024px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: none;
        border-bottom: 1px solid var(--line);
      }}
      .comment-pane {{
        position: static;
        height: auto;
        border-left: none;
        border-top: 1px solid var(--line);
      }}
      .controls {{
        grid-template-columns: 1fr 1fr 1fr;
      }}
      .main-toolbar {{
        grid-template-columns: 1fr 1fr;
      }}
      .main-toolbar input {{
        grid-column: 1 / -1;
      }}
      .main-toolbar .filter-hit {{
        grid-column: 1 / -1;
      }}
      .comment-controls {{
        grid-template-columns: 1fr;
      }}
      .stats-grid {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }}
    }}
  </style>
</head>
<body id="top">
  <div class="layout">
    <aside class="sidebar">
      <h1>{title}</h1>
      <p class="meta">
        Group: <b>{group_name}</b><br>
        Selector: {selector}<br>
        Source: {base} -> {head}
      </p>
      <div class="stats-grid">
        <div class="stat"><span class="k">Chunks</span><span class="v">{chunk_count}</span></div>
        <div class="stat"><span class="k">Files</span><span class="v">{file_count}</span></div>
        <div class="stat"><span class="k">+ Add</span><span class="v">{adds}</span></div>
        <div class="stat"><span class="k">- Delete</span><span class="v">{deletes}</span></div>
        <div class="stat"><span class="k">Context</span><span class="v">{contexts}</span></div>
        <div class="stat"><span class="k">Comments</span><span id="stat-comments-total" class="v">{comments_total}</span></div>
      </div>
      <p class="stats">reviewed <span id="stat-reviewed-count">{reviewed_count}</span> / <span id="stat-reviewed-total">{reviewed_total}</span> (<span id="stat-reviewed-rate">{reviewed_rate}</span>%)</p>
      <p class="stats">chunk <span id="stat-comments-chunk">{comments_chunk}</span> / line <span id="stat-comments-line">{comments_line}</span></p>
      <div class="controls">
        <input id="file-filter" type="text" placeholder="Filter files..." autocomplete="off" />
        <button id="expand-all" type="button">Expand</button>
        <button id="collapse-all" type="button">Collapse</button>
      </div>
      <p id="file-filter-hit" class="filter-hit">showing all files</p>
      <div class="legend">
        <span class="chip add">+ Add</span>
        <span class="chip del">- Delete</span>
        <span class="chip ctx">Context</span>
        <span class="chip cmt">Comment</span>
      </div>
      <p class="sidebar-nav-title">{sidebar_nav_title}</p>
      <ol class="file-list">
        {sidebar_nav}
      </ol>
    </aside>
    <main class="main">
      <div class="main-toolbar">
        <input id="content-filter" type="text" placeholder="Search in diff text / comments..." autocomplete="off" />
        <button id="toggle-inbox" type="button" aria-pressed="false">Inbox</button>
        <button id="toggle-context" type="button" aria-pressed="false">Hide Context</button>
        <button id="toggle-comments" type="button" aria-pressed="false">Comments Only</button>
        <button id="toggle-wrap" type="button" aria-pressed="true">Wrap</button>
        <button id="toggle-compact" type="button" aria-pressed="false">Compact</button>
        <button id="font-smaller" type="button" title="Decrease diff font size">A-</button>
        <button id="font-larger" type="button" title="Increase diff font size">A+</button>
        <button id="font-reset" type="button" title="Reset diff font size">A0</button>
        <button id="save-state" type="button" hidden>Save State</button>
        <button id="download-json" type="button">Download JSON</button>
        <button id="download-state" type="button">Download State</button>
        <button id="import-state" type="button">Import State</button>
        <button id="diff-state" type="button">Diff State</button>
        <button id="apply-state-selection" type="button">Apply Selected State</button>
        {impact_toggle_html}
        <input id="import-state-file" type="file" accept="application/json,.json" hidden />
        <button id="copy-state" type="button">Copy State</button>
        <span id="state-source-label" class="filter-hit"></span>
        <span id="save-state-status" class="filter-hit"></span>
        <span id="content-filter-hit" class="filter-hit">showing all rows</span>
      </div>
      <section id="inbox-panel" class="inbox-panel" hidden>
        <div class="inbox-headbar">
          <h2>Inbox Queue</h2>
          <p id="inbox-sub" class="inbox-sub">actionable {actionable_count} / total {chunk_count}</p>
        </div>
        <ol id="inbox-list" class="inbox-list">
          {inbox_items_html}
        </ol>
      </section>
      {impact_panel_html}
      <p class="main-help">Shortcuts: <code>/</code> search content, <code>f</code> file filter, <code>i</code> inbox, <code>k</code> jump top actionable, <code>c</code> hide context, <code>m</code> comments only, <code>w</code> wrap, <code>j</code> compact, <code>A-</code>/<code>A+</code> font size, click <code>確認済み</code> to mark reviewed, click <code>Comment</code>/<code>C</code> to post, <a href="#top">Back to top</a></p>
      {group_brief_card_html}
      {file_sections}
    </main>
    <aside class="comment-pane">
      <div class="comment-pane-head">
        <h2>Comments</h2>
        <p class="comment-pane-stats"><span id="comment-total">{comment_entry_count}</span> total / <span id="comment-unresolved">{unresolved_comment_count}</span> unresolved</p>
      </div>
      <div class="comment-controls">
        <input id="comment-filter" type="text" placeholder="Filter comments..." autocomplete="off" />
        <button id="toggle-unresolved-comment" type="button" aria-pressed="false">Unresolved Only</button>
      </div>
      <p id="comment-filter-hit" class="filter-hit">showing all comments</p>
      <ol id="comment-list" class="comment-list">
        {comment_items_html}
      </ol>
    </aside>
  </div>
  <dialog id="comment-editor-modal" class="comment-modal">
    <form id="comment-editor-form" class="comment-modal-form" method="dialog">
      <h3 id="comment-editor-title" class="comment-modal-title">Comment</h3>
      <p id="comment-editor-sub" class="comment-modal-sub">Enter comment text. Empty value deletes existing comment.</p>
      <textarea id="comment-editor-input" class="comment-modal-textarea" autocomplete="off"></textarea>
      <div class="comment-modal-actions">
        <button id="comment-editor-cancel" type="submit" value="cancel">Cancel</button>
        <button id="comment-editor-delete" class="danger" type="submit" value="delete">Delete</button>
        <button id="comment-editor-save" class="primary" type="submit" value="save">Save</button>
      </div>
    </form>
  </dialog>
  <dialog id="state-selection-modal" class="comment-modal">
    <form id="state-selection-form" class="comment-modal-form" method="dialog">
      <h3 class="comment-modal-title">Apply Selected State</h3>
      <p class="comment-modal-sub">Enter one selection token per line, for example: <code>reviews:c1</code>. Use <code>Diff State</code> to inspect/select tokens first.</p>
      <textarea id="state-selection-input" class="comment-modal-textarea" autocomplete="off"></textarea>
      <pre id="state-selection-preview" class="comment-modal-sub" style="white-space:pre-wrap;min-height:8em;max-height:18em;overflow:auto;border:1px solid var(--line);padding:10px;border-radius:10px;background:#0f1420;"></pre>
      <div class="comment-modal-actions">
        <button id="state-selection-cancel" type="submit" value="cancel">Cancel</button>
        <button id="state-selection-preview-btn" type="submit" value="preview">Preview</button>
        <button id="state-selection-apply" type="submit" value="apply" disabled>Apply</button>
      </div>
    </form>
  </dialog>
  <dialog id="state-diff-modal" class="comment-modal">
    <form id="state-diff-form" class="comment-modal-form" method="dialog">
      <h3 class="comment-modal-title">Diff State</h3>
      <p id="state-diff-sub" class="comment-modal-sub">Inspect changed selection tokens, then copy them or open Apply Selected State with the current token set.</p>
      <pre id="state-diff-preview" class="comment-modal-sub" style="white-space:pre-wrap;min-height:12em;max-height:22em;overflow:auto;border:1px solid var(--line);padding:10px;border-radius:10px;background:#0f1420;"></pre>
      <div class="comment-modal-actions">
        <button id="state-diff-close" type="submit" value="close">Close</button>
        <button id="state-diff-copy" type="button">Copy Tokens</button>
        <button id="state-diff-apply" class="primary" type="button">Apply These Tokens</button>
      </div>
    </form>
  </dialog>
  <dialog id="brief-editor-modal" class="comment-modal">
    <form id="brief-editor-form" class="comment-modal-form" method="dialog">
      <h3 class="comment-modal-title">Review Handoff</h3>
      <p class="comment-modal-sub">Group-level context for reviewers. List fields use one item per line.</p>
      <label class="comment-modal-sub" for="brief-status-input">Status</label>
      <select id="brief-status-input" class="comment-modal-textarea" style="height:auto;min-height:0;">
        <option value="draft">draft</option>
        <option value="ready">ready</option>
        <option value="acknowledged">acknowledged</option>
        <option value="stale">stale</option>
      </select>
      <label class="comment-modal-sub" for="brief-summary-input">Summary</label>
      <textarea id="brief-summary-input" class="comment-modal-textarea" autocomplete="off"></textarea>
      <label class="comment-modal-sub" for="brief-focus-input">Focus Points</label>
      <textarea id="brief-focus-input" class="comment-modal-textarea" autocomplete="off"></textarea>
      <label class="comment-modal-sub" for="brief-tests-input">Test Evidence</label>
      <textarea id="brief-tests-input" class="comment-modal-textarea" autocomplete="off"></textarea>
      <label class="comment-modal-sub" for="brief-tradeoffs-input">Known Tradeoffs</label>
      <textarea id="brief-tradeoffs-input" class="comment-modal-textarea" autocomplete="off"></textarea>
      <label class="comment-modal-sub" for="brief-questions-input">Questions</label>
      <textarea id="brief-questions-input" class="comment-modal-textarea" autocomplete="off"></textarea>
      <div class="comment-modal-actions">
        <button id="brief-editor-cancel" type="submit" value="cancel">Cancel</button>
        <button id="brief-editor-delete" class="danger" type="submit" value="delete">Delete</button>
        <button id="brief-editor-save" class="primary" type="submit" value="save">Save</button>
      </div>
    </form>
  </dialog>
  <dialog id="brief-viewer-modal" class="comment-modal">
    <div class="comment-modal-form">
      <div class="brief-viewer-head">
        <h3 class="comment-modal-title" id="brief-viewer-title">Review Handoff</h3>
        <span id="brief-viewer-status" class="brief-status"></span>
      </div>
      <div id="brief-viewer-body" class="brief-viewer-body"></div>
      <div class="comment-modal-actions">
        <button id="brief-viewer-close" type="button">Close</button>
        <button id="brief-viewer-edit" class="primary" type="button">Edit Handoff</button>
      </div>
    </div>
  </dialog>
  <script id="report-doc-json" type="application/json">{doc_json}</script>
  <script id="report-config-json" type="application/json">{report_config_json}</script>
  <script>
    (function () {{
      const docNode = document.getElementById("report-doc-json");
      const configNode = document.getElementById("report-config-json");
      let draftDoc = {{}};
      let reportConfig = {{}};
      try {{
        draftDoc = JSON.parse(docNode ? docNode.textContent : "{{}}");
      }} catch (_error) {{
        draftDoc = {{}};
      }}
      try {{
        reportConfig = JSON.parse(configNode ? configNode.textContent : "{{}}");
      }} catch (_error) {{
        reportConfig = {{}};
      }}
      if (!draftDoc || typeof draftDoc != "object") {{
        draftDoc = {{}};
      }}
      if (!draftDoc.reviews || typeof draftDoc.reviews != "object") {{
        draftDoc.reviews = {{}};
      }}
      if (!draftDoc.groupBriefs || typeof draftDoc.groupBriefs != "object") {{
        draftDoc.groupBriefs = {{}};
      }}
      if (!draftDoc.analysisState || typeof draftDoc.analysisState != "object") {{
        draftDoc.analysisState = {{}};
      }}
      if (!draftDoc.threadState || typeof draftDoc.threadState != "object") {{
        draftDoc.threadState = {{}};
      }}
      if (!reportConfig || typeof reportConfig != "object") {{
        reportConfig = {{}};
      }}
      const saveStateUrl = String(reportConfig.saveStateUrl || "").trim();
      const saveStateLabel = String(reportConfig.saveStateLabel || "Save State").trim() || "Save State";
      const currentGroupId = String(reportConfig.currentGroupId || "").trim();
      const initialStateSourceLabel = String(reportConfig.stateSourceLabel || "").trim();
      const stateDiffSections = {state_diff_sections_json};
      const stateSelectionSections = {state_selection_sections_json};
      const initialStateDiffReport = (reportConfig.stateDiffReport && typeof reportConfig.stateDiffReport == "object")
        ? reportConfig.stateDiffReport
        : null;
      const impactPreviewReport = (reportConfig.impactPreviewReport && typeof reportConfig.impactPreviewReport == "object")
        ? reportConfig.impactPreviewReport
        : null;
      const impactStateLabel = String(reportConfig.impactStateLabel || "").trim();
      const impactStateFingerprint = String(reportConfig.impactStateFingerprint || "").trim();

      const fileInput = document.getElementById("file-filter");
      const contentInput = document.getElementById("content-filter");
      const fileHit = document.getElementById("file-filter-hit");
      const contentHit = document.getElementById("content-filter-hit");
      const navItems = Array.from(document.querySelectorAll(".file-list li[data-nav-key]"));
      const sections = Array.from(document.querySelectorAll(".file-section[data-file]"));
      const expandBtn = document.getElementById("expand-all");
      const collapseBtn = document.getElementById("collapse-all");
      const toggleInboxBtn = document.getElementById("toggle-inbox");
      const toggleImpactPreviewBtn = document.getElementById("toggle-impact-preview");
      const toggleContextBtn = document.getElementById("toggle-context");
      const toggleCommentsBtn = document.getElementById("toggle-comments");
      const toggleWrapBtn = document.getElementById("toggle-wrap");
      const toggleCompactBtn = document.getElementById("toggle-compact");
      const saveStateBtn = document.getElementById("save-state");
      const saveStateStatus = document.getElementById("save-state-status");
      const downloadJsonBtn = document.getElementById("download-json");
      const downloadStateBtn = document.getElementById("download-state");
      const importStateBtn = document.getElementById("import-state");
      const diffStateBtn = document.getElementById("diff-state");
      const applyStateSelectionBtn = document.getElementById("apply-state-selection");
      const importStateFile = document.getElementById("import-state-file");
      const copyStateBtn = document.getElementById("copy-state");
      const stateSourceLabel = document.getElementById("state-source-label");
      const inboxPanel = document.getElementById("inbox-panel");
      const impactPreviewPanel = document.getElementById("impact-preview-panel");
      const inboxList = document.getElementById("inbox-list");
      const inboxSub = document.getElementById("inbox-sub");
      const commentInput = document.getElementById("comment-filter");
      const commentHit = document.getElementById("comment-filter-hit");
      const toggleUnresolvedCommentBtn = document.getElementById("toggle-unresolved-comment");
      const commentList = document.getElementById("comment-list");
      const commentTotal = document.getElementById("comment-total");
      const commentUnresolved = document.getElementById("comment-unresolved");
      const statCommentsTotal = document.getElementById("stat-comments-total");
      const statCommentsChunk = document.getElementById("stat-comments-chunk");
      const statCommentsLine = document.getElementById("stat-comments-line");
      const statReviewedCount = document.getElementById("stat-reviewed-count");
      const statReviewedTotal = document.getElementById("stat-reviewed-total");
      const statReviewedRate = document.getElementById("stat-reviewed-rate");
      const commentEditorModal = document.getElementById("comment-editor-modal");
      const commentEditorForm = document.getElementById("comment-editor-form");
      const commentEditorTitle = document.getElementById("comment-editor-title");
      const commentEditorSub = document.getElementById("comment-editor-sub");
      const commentEditorInput = document.getElementById("comment-editor-input");
      const commentEditorDelete = document.getElementById("comment-editor-delete");
      const stateSelectionModal = document.getElementById("state-selection-modal");
      const stateSelectionForm = document.getElementById("state-selection-form");
      const stateSelectionInput = document.getElementById("state-selection-input");
      const stateSelectionPreview = document.getElementById("state-selection-preview");
      const stateSelectionApply = document.getElementById("state-selection-apply");
      const stateDiffModal = document.getElementById("state-diff-modal");
      const stateDiffPreview = document.getElementById("state-diff-preview");
      const stateDiffSub = document.getElementById("state-diff-sub");
      const stateDiffCopy = document.getElementById("state-diff-copy");
      const stateDiffApply = document.getElementById("state-diff-apply");
      const impactPlanStatus = document.getElementById("impact-plan-status");
      const groupBriefCard = document.getElementById("group-brief-card");
      const groupBriefStatus = document.getElementById("group-brief-status");
      const viewGroupBriefBtn = document.getElementById("view-group-brief");
      const editGroupBriefBtn = document.getElementById("edit-group-brief");
      const briefViewerModal = document.getElementById("brief-viewer-modal");
      const briefViewerTitle = document.getElementById("brief-viewer-title");
      const briefViewerStatus = document.getElementById("brief-viewer-status");
      const briefViewerBody = document.getElementById("brief-viewer-body");
      const briefEditorModal = document.getElementById("brief-editor-modal");
      const briefEditorForm = document.getElementById("brief-editor-form");
      const briefStatusInput = document.getElementById("brief-status-input");
      const briefSummaryInput = document.getElementById("brief-summary-input");
      const briefFocusInput = document.getElementById("brief-focus-input");
      const briefTestsInput = document.getElementById("brief-tests-input");
      const briefTradeoffsInput = document.getElementById("brief-tradeoffs-input");
      const briefQuestionsInput = document.getElementById("brief-questions-input");

      const state = {{
        hideContext: false,
        commentsOnly: false,
        inboxMode: false,
        commentUnresolvedOnly: false,
        importedStateLabel: initialStateSourceLabel || "embedded",
        importedStatePayload: null,
        lastStateSelectionPreview: null,
        lastStateSelectionRaw: "",
        lastStateSelectionBasePayload: null,
        lastStateDiffTokens: [],
      }};

      function normalizeBoolean(value, fallback) {{
        if (typeof value == "boolean") {{
          return value;
        }}
        if (typeof value == "number") {{
          return value !== 0;
        }}
        if (typeof value == "string") {{
          const clean = value.trim().toLowerCase();
          if (["true", "1", "yes", "on"].includes(clean)) {{
            return true;
          }}
          if (["false", "0", "no", "off"].includes(clean)) {{
            return false;
          }}
        }}
        return !!fallback;
      }}

      function analysisStateObject() {{
        if (!draftDoc.analysisState || typeof draftDoc.analysisState != "object") {{
          draftDoc.analysisState = {{}};
        }}
        return draftDoc.analysisState;
      }}

      function threadStateObject() {{
        if (!draftDoc.threadState || typeof draftDoc.threadState != "object") {{
          draftDoc.threadState = {{}};
        }}
        return draftDoc.threadState;
      }}

      function setPressed(button, value) {{
        if (!button) return;
        button.setAttribute("aria-pressed", value ? "true" : "false");
      }}

      // Font size (diff table) zoom controls.
      const FONT_KEY = "diffgr:diffFontPx";
      const rootStyle = document.documentElement.style;
      const fontSmaller = document.getElementById("font-smaller");
      const fontLarger = document.getElementById("font-larger");
      const fontReset = document.getElementById("font-reset");

      function clamp(n, lo, hi) {{
        return Math.max(lo, Math.min(hi, n));
      }}

      function getFontPx() {{
        const raw = localStorage.getItem(FONT_KEY);
        const n = raw ? Number(raw) : NaN;
        return Number.isFinite(n) ? clamp(Math.round(n), 9, 22) : 12;
      }}

      function setFontPx(px) {{
        const n = clamp(Math.round(px), 9, 22);
        rootStyle.setProperty("--diff-font", `${{n}}px`);
        localStorage.setItem(FONT_KEY, String(n));
        analysisStateObject().diffFontPx = n;
      }}

      // Initialize.
      setFontPx(getFontPx());
      fontSmaller?.addEventListener("click", () => setFontPx(getFontPx() - 1));
      fontLarger?.addEventListener("click", () => setFontPx(getFontPx() + 1));
      fontReset?.addEventListener("click", () => setFontPx(12));

      function setSaveStatus(message, isError) {{
        if (!saveStateStatus) {{
          return;
        }}
        saveStateStatus.textContent = String(message || "");
        saveStateStatus.classList.toggle("save-status-error", !!isError);
        saveStateStatus.classList.toggle("save-status-ok", !!message && !isError);
      }}

      function setStateSourceLabel(message) {{
        if (!stateSourceLabel) {{
          return;
        }}
        stateSourceLabel.textContent = message ? ("state source: " + String(message)) : "";
      }}

      function currentStatePayload() {{
        persistAnalysisState();
        persistThreadState();
        return {{
          reviews: draftDoc.reviews || {{}},
          groupBriefs: draftDoc.groupBriefs || {{}},
          analysisState: draftDoc.analysisState || {{}},
          threadState: draftDoc.threadState || {{}},
        }};
      }}

      function normalizeImportedStatePayload(payload) {{
        if (!payload || typeof payload != "object") {{
          throw new Error("State payload must be a JSON object.");
        }}
        const source = (payload.state && typeof payload.state == "object") ? payload.state : payload;
        const keys = ["reviews", "groupBriefs", "analysisState", "threadState"];
        if (!keys.some((key) => key in source)) {{
          throw new Error("State payload must include one or more of: reviews, groupBriefs, analysisState, threadState.");
        }}
        const normalized = {{}};
        for (const key of keys) {{
          const candidate = source[key] || {{}};
          if (candidate && typeof candidate != "object") {{
            throw new Error("`" + key + "` must be a JSON object.");
          }}
          normalized[key] = candidate && typeof candidate == "object" ? candidate : {{}};
        }}
        return normalized;
      }}

      function cloneStateValue(value) {{
        if (value === null || value === undefined) {{
          return value;
        }}
        return JSON.parse(JSON.stringify(value));
      }}

      function previewStateValue(value) {{
        let rendered = "";
        if (typeof value == "string") {{
          rendered = value;
        }} else {{
          try {{
            rendered = JSON.stringify(value);
          }} catch (_error) {{
            rendered = String(value);
          }}
        }}
        if (rendered.length <= 80) {{
          return rendered;
        }}
        return rendered.slice(0, 79) + "…";
      }}

      function canonicalStateValue(value) {{
        if (Array.isArray(value)) {{
          return value.map((item) => canonicalStateValue(item));
        }}
        if (value && typeof value == "object") {{
          const out = {{}};
          for (const key of Object.keys(value).sort()) {{
            out[key] = canonicalStateValue(value[key]);
          }}
          return out;
        }}
        return value;
      }}

      function canonicalStateString(value) {{
        return JSON.stringify(canonicalStateValue(value));
      }}

      function createEmptyDiffSection() {{
        return {{
          added: [],
          removed: [],
          changed: [],
          unchanged: [],
          addedDetails: [],
          removedDetails: [],
          changedDetails: [],
          addedCount: 0,
          removedCount: 0,
          changedCount: 0,
          unchangedCount: 0,
        }};
      }}

      function diffStatePayload(baseState, otherState) {{
        const result = {{}};
        for (const sectionName of stateDiffSections) {{
          const baseMap = (baseState && typeof baseState[sectionName] == "object" && baseState[sectionName]) ? baseState[sectionName] : {{}};
          const otherMap = (otherState && typeof otherState[sectionName] == "object" && otherState[sectionName]) ? otherState[sectionName] : {{}};
          const section = createEmptyDiffSection();
          let allKeys = Array.from(new Set([...Object.keys(baseMap), ...Object.keys(otherMap)])).sort();
          if (sectionName == "threadState") {{
            allKeys = allKeys.filter((itemKey) => itemKey != "__files");
          }}
          for (const itemKey of allKeys) {{
            if (!(itemKey in baseMap)) {{
              section.added.push(itemKey);
              section.addedDetails.push({{
                key: itemKey,
                preview: previewStateValue(otherMap[itemKey]),
                selectionToken: `${{sectionName}}:${{itemKey}}`,
              }});
              continue;
            }}
            if (!(itemKey in otherMap)) {{
              section.removed.push(itemKey);
              section.removedDetails.push({{
                key: itemKey,
                preview: previewStateValue(baseMap[itemKey]),
                selectionToken: `${{sectionName}}:${{itemKey}}`,
              }});
              continue;
            }}
            const left = canonicalStateString(baseMap[itemKey]);
            const right = canonicalStateString(otherMap[itemKey]);
            if (left !== right) {{
              section.changed.push(itemKey);
              section.changedDetails.push({{
                key: itemKey,
                beforePreview: previewStateValue(baseMap[itemKey]),
                afterPreview: previewStateValue(otherMap[itemKey]),
                selectionToken: `${{sectionName}}:${{itemKey}}`,
              }});
              continue;
            }}
            section.unchanged.push(itemKey);
          }}
          if (sectionName == "threadState") {{
            const baseFiles = (baseMap.__files && typeof baseMap.__files == "object") ? baseMap.__files : {{}};
            const otherFiles = (otherMap.__files && typeof otherMap.__files == "object") ? otherMap.__files : {{}};
            const allFileKeys = Array.from(new Set([...Object.keys(baseFiles), ...Object.keys(otherFiles)])).sort();
            for (const fileKey of allFileKeys) {{
              const detailKey = `__files:${{fileKey}}`;
              const selectionToken = `threadState.__files:${{fileKey}}`;
              if (!(fileKey in baseFiles)) {{
                section.added.push(detailKey);
                section.addedDetails.push({{
                  key: detailKey,
                  preview: previewStateValue(otherFiles[fileKey]),
                  selectionToken,
                }});
                continue;
              }}
              if (!(fileKey in otherFiles)) {{
                section.removed.push(detailKey);
                section.removedDetails.push({{
                  key: detailKey,
                  preview: previewStateValue(baseFiles[fileKey]),
                  selectionToken,
                }});
                continue;
              }}
              const left = canonicalStateString(baseFiles[fileKey]);
              const right = canonicalStateString(otherFiles[fileKey]);
              if (left !== right) {{
                section.changed.push(detailKey);
                section.changedDetails.push({{
                  key: detailKey,
                  beforePreview: previewStateValue(baseFiles[fileKey]),
                  afterPreview: previewStateValue(otherFiles[fileKey]),
                  selectionToken,
                }});
                continue;
              }}
              section.unchanged.push(detailKey);
            }}
          }}
          section.addedCount = section.added.length;
          section.removedCount = section.removed.length;
          section.changedCount = section.changed.length;
          section.unchangedCount = section.unchanged.length;
          result[sectionName] = section;
        }}
        return result;
      }}

      function countChangedSections(diff) {{
        let changed = 0;
        for (const key of stateDiffSections) {{
          const section = diff[key] || {{}};
          if (Number(section.addedCount || 0) || Number(section.removedCount || 0) || Number(section.changedCount || 0)) {{
            changed += 1;
          }}
        }}
        return changed;
      }}

      function diffSelectionTokens(diff) {{
        const tokens = [];
        for (const key of stateDiffSections) {{
          const section = diff[key] || {{}};
          for (const label of ["addedDetails", "removedDetails", "changedDetails"]) {{
            const items = Array.isArray(section[label]) ? section[label] : [];
            for (const item of items) {{
              const token = String((item && item.selectionToken) || "").trim();
              if (token && !tokens.includes(token)) {{
                tokens.push(token);
              }}
            }}
          }}
        }}
        return tokens;
      }}

      function buildDiffRows(diff) {{
        const rows = [];
        for (const sectionName of stateDiffSections) {{
          const section = (diff && typeof diff[sectionName] == "object" && diff[sectionName]) ? diff[sectionName] : {{}};
          for (const [detailKey, changeKind] of [["addedDetails", "added"], ["removedDetails", "removed"], ["changedDetails", "changed"]]) {{
            const items = Array.isArray(section[detailKey]) ? section[detailKey] : [];
            for (const item of items) {{
              if (!item || typeof item != "object") continue;
              let preview = String(item.preview || "");
              if (changeKind == "changed") {{
                preview = String(item.beforePreview || "") + " -> " + String(item.afterPreview || "");
              }}
              rows.push({{
                section: sectionName,
                changeKind,
                key: String(item.key || ""),
                preview,
                selectionToken: String(item.selectionToken || ""),
              }});
            }}
          }}
        }}
        return rows;
      }}

      function buildStateDiffReport(baseState, otherState, sourceLabel) {{
        const stateDiff = diffStatePayload(baseState, otherState);
        const rows = buildDiffRows(stateDiff);
        const selectionTokens = diffSelectionTokens(stateDiff);
        const report = {{ stateDiff, rows, selectionTokens }};
        if (sourceLabel) report.sourceLabel = String(sourceLabel).trim();
        return report;
      }}

      function renderDiffSectionLines(diff, rows) {{
        const lines = [];
        const rowsBySection = {{}};
        for (const row of rows) {{
          const s = String(row.section || "");
          if (!rowsBySection[s]) rowsBySection[s] = [];
          rowsBySection[s].push(row);
        }}
        for (const sectionName of stateDiffSections) {{
          const section = (diff[sectionName] && typeof diff[sectionName] == "object") ? diff[sectionName] : {{}};
          lines.push(
            sectionName + ": added=" + Number(section.addedCount || 0) +
            " removed=" + Number(section.removedCount || 0) +
            " changed=" + Number(section.changedCount || 0) +
            " unchanged=" + Number(section.unchangedCount || 0)
          );
          for (const row of (rowsBySection[sectionName] || [])) {{
            const token = String(row.selectionToken || "").trim();
            const suffix = token ? " [select: " + token + "]" : "";
            lines.push("  - " + String(row.key || "") + ": " + String(row.preview || "") + suffix);
          }}
        }}
        return lines;
      }}

      function renderStateDiffReport(report) {{
        if (!report || typeof report != "object") return "";
        const diff = (report.stateDiff && typeof report.stateDiff == "object") ? report.stateDiff : {{}};
        const rows = Array.isArray(report.rows) ? report.rows : [];
        const sourceLabel = String(report.sourceLabel || "").trim();
        const lines = [];
        if (sourceLabel) lines.push("source=" + sourceLabel);
        lines.push(...renderDiffSectionLines(diff, rows));
        return lines.join("\\n");
      }}

      function buildSelectionPreviewReport(rawTokens, sourceLabel, baseLabel) {{
        const preview = previewSelectedStateTokens(rawTokens);
        const rows = buildDiffRows(preview.resultDiff);
        const report = {{
          selection: preview.selection,
          rows,
          summary: {{
            selectedKeyCount: preview.selectedKeyCount,
            noOpCount: preview.noOpCount,
            changedSectionCount: preview.changedSectionCount,
          }},
          resultDiff: preview.resultDiff,
          nextState: preview.nextState,
        }};
        if (sourceLabel) report.sourceLabel = String(sourceLabel || "").trim();
        if (baseLabel) report.baseLabel = String(baseLabel || "").trim();
        return report;
      }}

      function renderSelectionPreviewReport(report) {{
        if (!report || typeof report != "object") return "";
        const summary = (report.summary && typeof report.summary == "object") ? report.summary : {{}};
        const rows = Array.isArray(report.rows) ? report.rows : [];
        const sourceLabel = String(report.sourceLabel || "").trim();
        const baseLabel = String(report.baseLabel || "").trim();
        const selection = (report.selection && typeof report.selection == "object") ? report.selection : {{}};
        const resultDiff = (report.resultDiff && typeof report.resultDiff == "object") ? report.resultDiff : {{}};
        const selectionText = Object.entries(selection)
          .filter((entry) => Array.isArray(entry[1]) && entry[1].length > 0)
          .map((entry) => entry[0] + ": " + entry[1].join(", "))
          .join("\\n");
        return (
          "selected=" + Number(summary.selectedKeyCount || 0) +
          " no-op=" + Number(summary.noOpCount || 0) +
          " changed-sections=" + Number(summary.changedSectionCount || 0) +
          (sourceLabel ? "\\nsource=" + sourceLabel : "") +
          (baseLabel ? "\\nbase=" + baseLabel : "") +
          "\\n\\n" +
          selectionText +
          "\\n\\nState Diff\\n" +
          renderDiffSectionLines(resultDiff, rows).join("\\n")
        );
      }}

      function parseSelectionTokens(raw) {{
        const lines = String(raw || "")
          .split(/\\r?\\n/)
          .map((item) => item.trim())
          .filter(Boolean);
        if (!lines.length) {{
          throw new Error("at least one selection token is required");
        }}
        const parsed = Object.fromEntries(stateSelectionSections.map((section) => [section, []]));
        for (const token of lines) {{
          const colon = token.indexOf(":");
          if (colon <= 0) {{
            throw new Error("invalid selection token: " + token);
          }}
          const section = token.slice(0, colon).trim();
          const rawKeys = token.slice(colon + 1);
          if (!(section in parsed)) {{
            throw new Error("unknown selection section: " + section);
          }}
          const keys = rawKeys.split(",").map((item) => item.trim()).filter(Boolean);
          if (!keys.length) {{
            throw new Error("selection token must include one or more keys: " + token);
          }}
          for (const key of keys) {{
            if (!parsed[section].includes(key)) {{
              parsed[section].push(key);
            }}
          }}
        }}
        return parsed;
      }}

      function collectSelectableTokens(baseState, otherState) {{
        const selectable = Object.fromEntries(stateSelectionSections.map((section) => [section, new Set()]));
        for (const sectionName of stateDiffSections) {{
          const baseMap = (baseState && typeof baseState[sectionName] == "object" && baseState[sectionName]) ? baseState[sectionName] : {{}};
          const otherMap = (otherState && typeof otherState[sectionName] == "object" && otherState[sectionName]) ? otherState[sectionName] : {{}};
          for (const key of new Set([...Object.keys(baseMap), ...Object.keys(otherMap)])) {{
            if (sectionName == "threadState" && key == "__files") {{
              continue;
            }}
            selectable[sectionName].add(key);
          }}
        }}
        const baseFiles = (baseState && baseState.threadState && typeof baseState.threadState.__files == "object" && baseState.threadState.__files) ? baseState.threadState.__files : {{}};
        const otherFiles = (otherState && otherState.threadState && typeof otherState.threadState.__files == "object" && otherState.threadState.__files) ? otherState.threadState.__files : {{}};
        for (const key of new Set([...Object.keys(baseFiles), ...Object.keys(otherFiles)])) {{
          selectable["threadState.__files"].add(key);
        }}
        return selectable;
      }}

      function applySelectionToStatePayload(baseState, otherState, selection) {{
        const nextState = cloneStateValue(baseState);
        for (const section of stateDiffSections.filter((sectionName) => sectionName != "threadState")) {{
          const baseMap = nextState[section] || {{}};
          const otherMap = otherState[section] || {{}};
          for (const key of selection[section]) {{
            if (key in otherMap) {{
              baseMap[key] = cloneStateValue(otherMap[key]);
            }} else {{
              delete baseMap[key];
            }}
          }}
          nextState[section] = baseMap;
        }}
        const baseThread = nextState.threadState || {{}};
        const otherThread = otherState.threadState || {{}};
        for (const key of selection.threadState) {{
          if (key in otherThread) {{
            baseThread[key] = cloneStateValue(otherThread[key]);
          }} else {{
            delete baseThread[key];
          }}
        }}
        const baseFiles = (baseThread.__files && typeof baseThread.__files == "object") ? baseThread.__files : {{}};
        const otherFiles = (otherThread.__files && typeof otherThread.__files == "object") ? otherThread.__files : {{}};
        for (const key of selection["threadState.__files"]) {{
          if (key in otherFiles) {{
            baseFiles[key] = cloneStateValue(otherFiles[key]);
          }} else {{
            delete baseFiles[key];
          }}
        }}
        if (Object.keys(baseFiles).length) {{
          baseThread.__files = baseFiles;
        }} else {{
          delete baseThread.__files;
        }}
        nextState.threadState = baseThread;
        return nextState;
      }}

      function applySelectedStateTokens(rawTokens) {{
        const preview = previewSelectedStateTokens(rawTokens);
        draftDoc.reviews = cloneStateValue(preview.nextState.reviews || {{}});
        draftDoc.groupBriefs = cloneStateValue(preview.nextState.groupBriefs || {{}});
        draftDoc.analysisState = cloneStateValue(preview.nextState.analysisState || {{}});
        draftDoc.threadState = cloneStateValue(preview.nextState.threadState || {{}});
        refreshChunkVisualsFromDraft();
        return preview;
      }}

      function previewSelectedStateTokens(rawTokens) {{
        if (!state.importedStatePayload) {{
          throw new Error("no imported state is available for selective apply");
        }}
        const selection = parseSelectionTokens(rawTokens);
        const current = state.lastStateSelectionBasePayload
          ? cloneStateValue(state.lastStateSelectionBasePayload)
          : currentStatePayload();
        const other = state.importedStatePayload;
        const selectable = collectSelectableTokens(current, other);
        let selectedKeyCount = 0;
        let noOpCount = 0;
        for (const section of Object.keys(selection)) {{
          for (const key of selection[section]) {{
            if (!selectable[section].has(key)) {{
              throw new Error("unknown selection key for " + section + ": " + key);
            }}
            selectedKeyCount += 1;
            let baseValue = null;
            let otherValue = null;
            let basePresent = false;
            let otherPresent = false;
            if (section == "threadState.__files") {{
              const baseFiles = (current.threadState && typeof current.threadState.__files == "object") ? current.threadState.__files : {{}};
              const otherFiles = (other.threadState && typeof other.threadState.__files == "object") ? other.threadState.__files : {{}};
              basePresent = key in baseFiles;
              otherPresent = key in otherFiles;
              baseValue = baseFiles[key];
              otherValue = otherFiles[key];
            }} else {{
              const baseMap = section == "threadState" ? (current.threadState || {{}}) : (current[section] || {{}});
              const otherMap = section == "threadState" ? (other.threadState || {{}}) : (other[section] || {{}});
              basePresent = key in baseMap;
              otherPresent = key in otherMap;
              baseValue = baseMap[key];
              otherValue = otherMap[key];
            }}
            if (basePresent == otherPresent && canonicalStateString(baseValue) == canonicalStateString(otherValue)) {{
              noOpCount += 1;
            }}
          }}
        }}
        const nextState = applySelectionToStatePayload(current, other, selection);
        const resultDiff = diffStatePayload(current, nextState);
        return {{
          selection,
          selectedKeyCount,
          noOpCount,
          changedSectionCount: countChangedSections(resultDiff),
          nextState,
          resultDiff,
        }};
      }}

      if (initialStateSourceLabel && initialStateSourceLabel != "embedded") {{
        state.importedStatePayload = cloneStateValue(currentStatePayload());
      }}

      function escapeHtml(value) {{
        return String(value)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }}

      function normalizeLineToken(value) {{
        if (value === null || value === undefined || value === "") {{
          return "";
        }}
        const num = Number(value);
        if (Number.isFinite(num)) {{
          return String(Math.trunc(num));
        }}
        return String(value).trim();
      }}

      function normalizeLineNumberOrNull(token) {{
        const clean = normalizeLineToken(token);
        if (!clean) {{
          return null;
        }}
        const num = Number(clean);
        if (Number.isFinite(num)) {{
          return Math.trunc(num);
        }}
        return null;
      }}

      function lineAnchorKey(oldLine, newLine, lineType) {{
        return String(lineType || "") + ":" + normalizeLineToken(oldLine) + ":" + normalizeLineToken(newLine);
      }}

      function statusBadgeHtml(status) {{
        const label = {{
          unreviewed: "Unreviewed",
          reviewed: "Reviewed",
          ignored: "Ignored",
          needsReReview: "Re-Review",
        }}[status] || status;
        return "<span class='status-badge status-" + escapeHtml(status) + "'>" + escapeHtml(label) + "</span>";
      }}

      function normalizeBriefList(text) {{
        return String(text || "")
          .split(/\\r?\\n/)
          .map((item) => item.trim())
          .filter((item) => !!item);
      }}

      function cloneJson(value) {{
        if (value === null || value === undefined) {{
          return value;
        }}
        return JSON.parse(JSON.stringify(value));
      }}

      function getGroupBrief(groupId) {{
        const key = String(groupId || "").trim();
        const base = {{
          status: "draft",
          summary: "",
          focusPoints: [],
          testEvidence: [],
          knownTradeoffs: [],
          questionsForReviewer: [],
        }};
        if (!key) {{
          return base;
        }}
        const raw = draftDoc.groupBriefs[key];
        if (!raw || typeof raw != "object") {{
          return base;
        }}
        const normalized = cloneJson(raw) || {{}};
        normalized.status = ["draft", "ready", "acknowledged", "stale"].includes(String(raw.status || "").trim())
          ? String(raw.status || "").trim()
          : "draft";
        normalized.summary = String(raw.summary || "").trim();
        normalized.focusPoints = Array.isArray(raw.focusPoints) ? raw.focusPoints.map((item) => String(item || "").trim()).filter(Boolean) : [];
        normalized.testEvidence = Array.isArray(raw.testEvidence) ? raw.testEvidence.map((item) => String(item || "").trim()).filter(Boolean) : [];
        normalized.knownTradeoffs = Array.isArray(raw.knownTradeoffs) ? raw.knownTradeoffs.map((item) => String(item || "").trim()).filter(Boolean) : [];
        normalized.questionsForReviewer = Array.isArray(raw.questionsForReviewer) ? raw.questionsForReviewer.map((item) => String(item || "").trim()).filter(Boolean) : [];
        normalized.mentions = Array.isArray(raw.mentions) ? raw.mentions.map((item) => String(item || "").trim()).filter(Boolean) : [];
        if (!normalized.mentions.length) {{
          delete normalized.mentions;
        }}
        if (!Array.isArray(raw.acknowledgedBy)) {{
          delete normalized.acknowledgedBy;
        }}
        if (!raw.approval || typeof raw.approval != "object") {{
          delete normalized.approval;
        }}
        return normalized;
      }}

      function setGroupBrief(groupId, brief) {{
        const key = String(groupId || "").trim();
        if (!key) {{
          return;
        }}
        const current = draftDoc.groupBriefs[key];
        const normalized = current && typeof current == "object" ? cloneJson(current) : {{}};
        if (brief && typeof brief == "object") {{
          Object.keys(brief).forEach((keyName) => {{
            if (!["status", "summary", "focusPoints", "testEvidence", "knownTradeoffs", "questionsForReviewer", "mentions", "acknowledgedBy", "approval"].includes(keyName)) {{
              normalized[keyName] = cloneJson(brief[keyName]);
            }}
          }});
        }}
        normalized.status = ["draft", "ready", "acknowledged", "stale"].includes(String(brief.status || "").trim())
          ? String(brief.status || "").trim()
          : "draft";
        normalized.summary = String(brief.summary || "").trim();
        normalized.focusPoints = Array.isArray(brief.focusPoints) ? brief.focusPoints.map((item) => String(item || "").trim()).filter(Boolean) : [];
        normalized.testEvidence = Array.isArray(brief.testEvidence) ? brief.testEvidence.map((item) => String(item || "").trim()).filter(Boolean) : [];
        normalized.knownTradeoffs = Array.isArray(brief.knownTradeoffs) ? brief.knownTradeoffs.map((item) => String(item || "").trim()).filter(Boolean) : [];
        normalized.questionsForReviewer = Array.isArray(brief.questionsForReviewer) ? brief.questionsForReviewer.map((item) => String(item || "").trim()).filter(Boolean) : [];
        if (Array.isArray(brief.mentions)) {{
          normalized.mentions = brief.mentions.map((item) => String(item || "").trim()).filter(Boolean);
          if (!normalized.mentions.length) {{
            delete normalized.mentions;
          }}
        }}
        if (Array.isArray(brief.acknowledgedBy)) {{
          normalized.acknowledgedBy = cloneJson(brief.acknowledgedBy.filter((item) => item && typeof item == "object"));
          if (!normalized.acknowledgedBy.length) {{
            delete normalized.acknowledgedBy;
          }}
        }}
        if (brief.approval && typeof brief.approval == "object") {{
          normalized.approval = cloneJson(brief.approval);
        }}
        const hasContent = !!normalized.summary
          || normalized.focusPoints.length > 0
          || normalized.testEvidence.length > 0
          || normalized.knownTradeoffs.length > 0
          || normalized.questionsForReviewer.length > 0;
        const preserveRecord = !!(normalized.approval && typeof normalized.approval == "object")
          || (Array.isArray(normalized.mentions) && normalized.mentions.length > 0)
          || (Array.isArray(normalized.acknowledgedBy) && normalized.acknowledgedBy.length > 0)
          || Object.keys(normalized).some((keyName) => !["status", "summary", "focusPoints", "testEvidence", "knownTradeoffs", "questionsForReviewer", "mentions", "acknowledgedBy", "approval"].includes(keyName));
        if (!hasContent && normalized.status === "draft" && !preserveRecord) {{
          delete draftDoc.groupBriefs[key];
          return;
        }}
        draftDoc.groupBriefs[key] = normalized;
      }}

      function renderBriefList(title, items) {{
        if (!items || !items.length) {{
          return "";
        }}
        const li = items.map((item) => "<li>" + escapeHtml(item) + "</li>").join("");
        return "<div class='brief-block'><h3>" + escapeHtml(title) + "</h3><ul>" + li + "</ul></div>";
      }}

      function refreshGroupBriefCard() {{
        if (!groupBriefCard || !currentGroupId) {{
          return;
        }}
        const brief = getGroupBrief(currentGroupId);
        groupBriefCard.setAttribute("data-brief-status", brief.status);
        if (groupBriefStatus) {{
          groupBriefStatus.className = "brief-status brief-status-" + brief.status;
          groupBriefStatus.textContent = brief.status.toUpperCase();
        }}
        const summaryEl = groupBriefCard.querySelector(".brief-summary, .brief-empty");
        if (summaryEl) {{
          if (brief.summary) {{
            summaryEl.className = "brief-summary";
            summaryEl.textContent = brief.summary;
          }} else {{
            summaryEl.className = "brief-empty";
            summaryEl.textContent = "No review handoff yet.";
          }}
        }}
        const blocksHost = groupBriefCard;
        blocksHost.querySelectorAll(".brief-block").forEach((node) => node.remove());
        const html = [
          renderBriefList("Focus Points", brief.focusPoints),
          renderBriefList("Test Evidence", brief.testEvidence),
          renderBriefList("Known Tradeoffs", brief.knownTradeoffs),
          renderBriefList("Questions", brief.questionsForReviewer),
        ].join("");
        if (html) {{
          groupBriefCard.insertAdjacentHTML("beforeend", html);
        }}
      }}

      function allChunks() {{
        return Array.from(document.querySelectorAll(".chunk"));
      }}

      function allFileSections() {{
        return Array.from(document.querySelectorAll(".file-section[data-file]"));
      }}

      function persistThreadState() {{
        const nextState = {{}};
        for (const chunk of allChunks()) {{
          const chunkId = String(chunk.getAttribute("data-chunk-id") || "").trim();
          if (!chunkId) {{
            continue;
          }}
          nextState[chunkId] = {{
            open: !!chunk.open,
          }};
        }}
        const fileState = {{}};
        for (const section of allFileSections()) {{
          const fileKey = String(section.getAttribute("data-file") || "").trim();
          if (!fileKey) {{
            continue;
          }}
          fileState[fileKey] = {{
            open: !!section.open,
          }};
        }}
        if (Object.keys(fileState).length > 0) {{
          nextState.__files = fileState;
        }}
        draftDoc.threadState = nextState;
      }}

      function restoreThreadState() {{
        const threadState = threadStateObject();
        const fileState = threadState.__files;
        if (fileState && typeof fileState == "object") {{
          for (const section of allFileSections()) {{
            const fileKey = String(section.getAttribute("data-file") || "").trim();
            const record = fileState[fileKey];
            if (record && typeof record == "object" && "open" in record) {{
              section.open = normalizeBoolean(record.open, true);
            }}
          }}
        }}
        for (const chunk of allChunks()) {{
          const chunkId = String(chunk.getAttribute("data-chunk-id") || "").trim();
          if (!chunkId) {{
            continue;
          }}
          const record = threadState[chunkId];
          if (record && typeof record == "object" && "open" in record) {{
            chunk.open = normalizeBoolean(record.open, true);
          }}
        }}
      }}

      function persistAnalysisState() {{
        const analysisState = analysisStateObject();
        analysisState.fileFilter = fileInput ? String(fileInput.value || "") : "";
        analysisState.contentFilter = contentInput ? String(contentInput.value || "") : "";
        analysisState.commentFilter = commentInput ? String(commentInput.value || "") : "";
        analysisState.hideContext = !!state.hideContext;
        analysisState.commentsOnly = !!state.commentsOnly;
        analysisState.inboxMode = !!state.inboxMode;
        analysisState.commentUnresolvedOnly = !!state.commentUnresolvedOnly;
        analysisState.wrap = toggleWrapBtn ? toggleWrapBtn.getAttribute("aria-pressed") == "true" : true;
        analysisState.compact = toggleCompactBtn ? toggleCompactBtn.getAttribute("aria-pressed") == "true" : false;
        analysisState.diffFontPx = getFontPx();
        analysisState.currentGroupId = currentGroupId;
        analysisState.selectedChunkId = String(analysisState.selectedChunkId || "").trim();
      }}

      function restoreAnalysisState() {{
        const analysisState = analysisStateObject();
        if (fileInput) {{
          fileInput.value = String(analysisState.fileFilter || "");
        }}
        if (contentInput) {{
          contentInput.value = String(analysisState.contentFilter || "");
        }}
        if (commentInput) {{
          commentInput.value = String(analysisState.commentFilter || "");
        }}
        state.hideContext = normalizeBoolean(analysisState.hideContext, false);
        state.commentsOnly = normalizeBoolean(analysisState.commentsOnly, false);
        state.inboxMode = normalizeBoolean(analysisState.inboxMode, false);
        state.commentUnresolvedOnly = normalizeBoolean(analysisState.commentUnresolvedOnly, false);
        setPressed(toggleContextBtn, state.hideContext);
        setPressed(toggleCommentsBtn, state.commentsOnly);
        setPressed(toggleInboxBtn, state.inboxMode);
        setPressed(toggleUnresolvedCommentBtn, state.commentUnresolvedOnly);
        if (inboxPanel) {{
          inboxPanel.hidden = !state.inboxMode;
        }}
        document.body.classList.toggle("inbox-mode", state.inboxMode);
        const wrapEnabled = normalizeBoolean(analysisState.wrap, true);
        setPressed(toggleWrapBtn, wrapEnabled);
        document.body.classList.toggle("no-wrap", !wrapEnabled);
        const compactEnabled = normalizeBoolean(analysisState.compact, false);
        setPressed(toggleCompactBtn, compactEnabled);
        document.body.classList.toggle("compact", compactEnabled);
        if ("diffFontPx" in analysisState) {{
          setFontPx(Number(analysisState.diffFontPx));
        }}
      }}

      function setSelectedChunkId(chunkId) {{
        analysisStateObject().selectedChunkId = String(chunkId || "").trim();
      }}

      function restoreSelectedChunk() {{
        const chunkId = String(analysisStateObject().selectedChunkId || "").trim();
        if (!chunkId) {{
          return;
        }}
        const chunk = findChunkById(chunkId);
        if (!chunk) {{
          return;
        }}
        let node = chunk;
        while (node) {{
          if (node.tagName && node.tagName.toLowerCase() === "details") {{
            node.open = true;
          }}
          node = node.parentElement;
        }}
      }}

      function findChunkById(chunkId) {{
        const target = String(chunkId || "");
        for (const chunk of allChunks()) {{
          if ((chunk.getAttribute("data-chunk-id") || "") === target) {{
            return chunk;
          }}
        }}
        return null;
      }}

      function ensureReviewRecord(chunkId) {{
        const key = String(chunkId || "");
        if (!key) {{
          return null;
        }}
        const current = draftDoc.reviews[key];
        if (!current || typeof current != "object") {{
          draftDoc.reviews[key] = {{}};
        }}
        return draftDoc.reviews[key];
      }}

      function getChunkComment(chunkId) {{
        const record = draftDoc.reviews[String(chunkId || "")];
        if (!record || typeof record != "object") {{
          return "";
        }}
        const comment = String(record.comment || "").trim();
        return comment;
      }}

      function getLineComments(chunkId) {{
        const record = draftDoc.reviews[String(chunkId || "")];
        if (!record || typeof record != "object") {{
          return [];
        }}
        const items = Array.isArray(record.lineComments) ? record.lineComments : [];
        const clean = [];
        for (const item of items) {{
          if (!item || typeof item != "object") {{
            continue;
          }}
          const text = String(item.comment || "").trim();
          if (!text) {{
            continue;
          }}
          let lineType = String(item.lineType || "");
          const oldLine = normalizeLineNumberOrNull(item.oldLine);
          const newLine = normalizeLineNumberOrNull(item.newLine);
          if (!lineType) {{
            if (oldLine === null && newLine !== null) {{
              lineType = "add";
            }} else if (oldLine !== null && newLine === null) {{
              lineType = "delete";
            }} else if (oldLine !== null && newLine !== null) {{
              lineType = "context";
            }} else {{
              lineType = "meta";
            }}
          }}
          clean.push({{
            oldLine: oldLine,
            newLine: newLine,
            lineType: lineType,
            comment: text,
          }});
        }}
        return clean;
      }}

      function getLineCommentForAnchor(chunkId, oldLine, newLine, lineType) {{
        const target = lineAnchorKey(oldLine, newLine, lineType);
        const items = getLineComments(chunkId);
        for (const item of items) {{
          if (lineAnchorKey(item.oldLine, item.newLine, item.lineType) === target) {{
            return item.comment;
          }}
        }}
        return "";
      }}

      function cleanupReviewRecord(chunkId) {{
        const key = String(chunkId || "");
        const record = draftDoc.reviews[key];
        if (!record || typeof record != "object") {{
          delete draftDoc.reviews[key];
          return;
        }}
        const hasComment = String(record.comment || "").trim().length > 0;
        const hasStatus = typeof record.status == "string" && record.status.length > 0;
        const hasLineComments = Array.isArray(record.lineComments) && record.lineComments.length > 0;
        if (!hasComment && !hasStatus && !hasLineComments && !record.reviewedAt) {{
          delete draftDoc.reviews[key];
        }}
      }}

      function setChunkComment(chunkId, commentText) {{
        const record = ensureReviewRecord(chunkId);
        if (!record) {{
          return;
        }}
        const clean = String(commentText || "").trim();
        if (clean) {{
          record.comment = clean;
        }} else {{
          delete record.comment;
        }}
        cleanupReviewRecord(chunkId);
      }}

      function setLineCommentForAnchor(chunkId, oldLine, newLine, lineType, commentText) {{
        const record = ensureReviewRecord(chunkId);
        if (!record) {{
          return;
        }}
        const targetKey = lineAnchorKey(oldLine, newLine, lineType);
        const existing = Array.isArray(record.lineComments) ? record.lineComments : [];
        const kept = [];
        for (const item of existing) {{
          if (!item || typeof item != "object") {{
            continue;
          }}
          const itemKey = lineAnchorKey(item.oldLine, item.newLine, item.lineType);
          if (itemKey === targetKey) {{
            continue;
          }}
          const text = String(item.comment || "").trim();
          if (!text) {{
            continue;
          }}
          kept.push({{
            oldLine: normalizeLineNumberOrNull(item.oldLine),
            newLine: normalizeLineNumberOrNull(item.newLine),
            lineType: String(item.lineType || ""),
            comment: text,
          }});
        }}
        const clean = String(commentText || "").trim();
        if (clean) {{
          kept.push({{
            oldLine: normalizeLineNumberOrNull(oldLine),
            newLine: normalizeLineNumberOrNull(newLine),
            lineType: String(lineType || ""),
            comment: clean,
          }});
        }}
        if (kept.length > 0) {{
          record.lineComments = kept;
        }} else {{
          delete record.lineComments;
        }}
        cleanupReviewRecord(chunkId);
      }}

      function isoUtcNow() {{
        return new Date().toISOString().replace(/\\.\\d{{3}}Z$/, "Z");
      }}

      function normalizeStatus(status) {{
        const value = String(status || "");
        if (value === "unreviewed" || value === "reviewed" || value === "ignored" || value === "needsReReview") {{
          return value;
        }}
        return "unreviewed";
      }}

      function setChunkStatus(chunkId, status) {{
        const record = ensureReviewRecord(chunkId);
        if (!record) {{
          return;
        }}
        const normalized = normalizeStatus(status);
        record.status = normalized;
        if (normalized === "reviewed") {{
          record.reviewedAt = isoUtcNow();
        }} else {{
          delete record.reviewedAt;
        }}
        cleanupReviewRecord(chunkId);
      }}

      function updateChunkStatusVisual(chunkEl, status) {{
        if (!chunkEl) {{
          return;
        }}
        const normalized = normalizeStatus(status);
        chunkEl.setAttribute("data-status", normalized);
        const statusSlot = chunkEl.querySelector(".chunk-status-slot");
        if (statusSlot) {{
          statusSlot.innerHTML = statusBadgeHtml(normalized);
        }}
        const checkbox = chunkEl.querySelector("input[data-action='toggle-reviewed']");
        if (checkbox && checkbox instanceof HTMLInputElement) {{
          checkbox.checked = normalized === "reviewed";
        }}
      }}

      function refreshReviewProgress() {{
        const chunks = allChunks();
        const total = chunks.length;
        let reviewed = 0;
        for (const chunkEl of chunks) {{
          if ((chunkEl.getAttribute("data-status") || "") === "reviewed") {{
            reviewed += 1;
          }}
        }}
        const rate = total > 0 ? Math.round((reviewed / total) * 100) : 0;
        if (statReviewedCount) statReviewedCount.textContent = String(reviewed);
        if (statReviewedTotal) statReviewedTotal.textContent = String(total);
        if (statReviewedRate) statReviewedRate.textContent = String(rate);
      }}

      function openCommentEditor(options) {{
        const title = String((options && options.title) || "Comment");
        const subtitle = String((options && options.subtitle) || "Enter comment text. Empty value deletes existing comment.");
        const initial = String((options && options.initial) || "");
        const fallbackPrompt = String((options && options.fallbackPrompt) || "Comment (empty to delete)");
        const supportsModal = (
          commentEditorModal &&
          typeof commentEditorModal.showModal == "function" &&
          commentEditorForm &&
          commentEditorTitle &&
          commentEditorSub &&
          commentEditorInput &&
          commentEditorDelete
        );
        if (!supportsModal) {{
          return Promise.resolve(window.prompt(fallbackPrompt, initial));
        }}

        return new Promise((resolve) => {{
          let settled = false;
          function finish(value) {{
            if (settled) {{
              return;
            }}
            settled = true;
            resolve(value);
          }}
          function cleanup() {{
            commentEditorModal.removeEventListener("close", onClose);
            commentEditorForm.removeEventListener("submit", onSubmit);
            commentEditorInput.removeEventListener("input", onInput);
          }}
          function onInput() {{
            commentEditorDelete.hidden = commentEditorInput.value.trim().length === 0;
          }}
          function onSubmit(event) {{
            const submitter = event.submitter;
            const action = submitter && typeof submitter.value == "string" ? submitter.value : "";
            if (action === "save") {{
              commentEditorModal.close("save");
              return;
            }}
            if (action === "delete") {{
              commentEditorModal.close("delete");
              return;
            }}
            commentEditorModal.close("cancel");
          }}
          function onClose() {{
            cleanup();
            const action = String(commentEditorModal.returnValue || "cancel");
            if (action === "save") {{
              finish(commentEditorInput.value);
              return;
            }}
            if (action === "delete") {{
              finish("");
              return;
            }}
            finish(null);
          }}

          commentEditorTitle.textContent = title;
          commentEditorSub.textContent = subtitle;
          commentEditorInput.value = initial;
          commentEditorDelete.hidden = initial.trim().length === 0;
          commentEditorForm.addEventListener("submit", onSubmit);
          commentEditorModal.addEventListener("close", onClose);
          commentEditorInput.addEventListener("input", onInput);
          try {{
            commentEditorModal.showModal();
            commentEditorInput.focus();
            commentEditorInput.select();
          }} catch (_error) {{
            cleanup();
            finish(window.prompt(fallbackPrompt, initial));
          }}
        }});
      }}

      function renderBriefSection(label, items) {{
        if (!items || items.length === 0) return "";
        const lis = items.map(item => "<li>" + escapeHtml(String(item)) + "</li>").join("");
        return "<div class='brief-viewer-section'><p class='brief-viewer-label'>" + escapeHtml(label) + "</p><ul>" + lis + "</ul></div>";
      }}

      function openGroupBriefViewer() {{
        if (!currentGroupId || !briefViewerModal || typeof briefViewerModal.showModal != "function") {{
          return;
        }}
        if (briefViewerModal.open) {{
          return;
        }}
        const brief = getGroupBrief(currentGroupId);
        if (briefViewerTitle) {{
          briefViewerTitle.textContent = "Review Handoff \u2014 " + (currentGroupId || "");
        }}
        if (briefViewerStatus) {{
          briefViewerStatus.className = "brief-status brief-status-" + brief.status;
          briefViewerStatus.textContent = brief.status.toUpperCase();
        }}
        if (briefViewerBody) {{
          const summaryHtml = brief.summary
            ? "<p class='brief-viewer-summary'>" + escapeHtml(brief.summary) + "</p>"
            : "<p class='brief-empty'>No summary yet.</p>";
          briefViewerBody.innerHTML =
            summaryHtml +
            renderBriefSection("Focus Points", brief.focusPoints) +
            renderBriefSection("Test Evidence", brief.testEvidence) +
            renderBriefSection("Known Tradeoffs", brief.knownTradeoffs) +
            renderBriefSection("Questions for Reviewer", brief.questionsForReviewer);
        }}
        briefViewerModal.showModal();
      }}

      function openGroupBriefEditor() {{
        if (!currentGroupId || !briefEditorModal || typeof briefEditorModal.showModal != "function" || !briefEditorForm) {{
          return;
        }}
        const brief = getGroupBrief(currentGroupId);
        briefStatusInput.value = brief.status;
        briefSummaryInput.value = brief.summary;
        briefFocusInput.value = brief.focusPoints.join("\\n");
        briefTestsInput.value = brief.testEvidence.join("\\n");
        briefTradeoffsInput.value = brief.knownTradeoffs.join("\\n");
        briefQuestionsInput.value = brief.questionsForReviewer.join("\\n");

        function cleanup() {{
          briefEditorModal.removeEventListener("close", onClose);
          briefEditorForm.removeEventListener("submit", onSubmit);
        }}
        function onSubmit(event) {{
          const submitter = event.submitter;
          const action = submitter && typeof submitter.value == "string" ? submitter.value : "";
          if (action === "save") {{
            briefEditorModal.close("save");
            return;
          }}
          if (action === "delete") {{
            briefEditorModal.close("delete");
            return;
          }}
          briefEditorModal.close("cancel");
        }}
        function onClose() {{
          cleanup();
          const action = String(briefEditorModal.returnValue || "cancel");
          if (action === "save") {{
            setGroupBrief(currentGroupId, {{
              status: briefStatusInput.value,
              summary: briefSummaryInput.value,
              focusPoints: normalizeBriefList(briefFocusInput.value),
              testEvidence: normalizeBriefList(briefTestsInput.value),
              knownTradeoffs: normalizeBriefList(briefTradeoffsInput.value),
              questionsForReviewer: normalizeBriefList(briefQuestionsInput.value),
            }});
            refreshGroupBriefCard();
            setSaveStatus("handoff updated", false);
            return;
          }}
          if (action === "delete") {{
            setGroupBrief(currentGroupId, {{
              status: "draft",
              summary: "",
              focusPoints: [],
              testEvidence: [],
              knownTradeoffs: [],
              questionsForReviewer: [],
            }});
            refreshGroupBriefCard();
            setSaveStatus("handoff cleared", false);
          }}
        }}
        briefEditorForm.addEventListener("submit", onSubmit);
        briefEditorModal.addEventListener("close", onClose);
        briefEditorModal.showModal();
      }}

      function revealTargetById(id) {{
        if (!id) return;
        const target = document.getElementById(id);
        if (!target) return;
        let node = target;
        while (node) {{
          if (node.tagName && node.tagName.toLowerCase() === "details") {{
            node.open = true;
          }}
          node = node.parentElement;
        }}
        const owningChunk = target.closest(".chunk");
        if (owningChunk) {{
          setSelectedChunkId(owningChunk.getAttribute("data-chunk-id") || "");
        }}
        target.scrollIntoView({{ behavior: "smooth", block: "center" }});
      }}

      function directChunkCommentNode(chunkEl) {{
        if (!chunkEl) {{
          return null;
        }}
        for (const child of Array.from(chunkEl.children)) {{
          if (child.classList && child.classList.contains("chunk-comment")) {{
            return child;
          }}
        }}
        return null;
      }}

      function updateChunkCommentVisual(chunkEl, commentText) {{
        if (!chunkEl) {{
          return;
        }}
        const clean = String(commentText || "").trim();
        const existing = directChunkCommentNode(chunkEl);
        if (!clean) {{
          if (existing) {{
            existing.remove();
          }}
          return;
        }}
        const table = chunkEl.querySelector(".diff-table");
        let target = existing;
        if (!target) {{
          target = document.createElement("div");
          target.className = "chunk-comment";
          if (table && table.parentNode === chunkEl) {{
            chunkEl.insertBefore(target, table);
          }} else {{
            chunkEl.appendChild(target);
          }}
        }}
        target.setAttribute("data-text", clean.toLowerCase());
        target.innerHTML = "<span class='comment-label'>COMMENT</span> " + escapeHtml(clean);
      }}

      function updateLineCommentVisual(diffRow, commentText) {{
        if (!diffRow) {{
          return;
        }}
        const anchorKey = diffRow.getAttribute("data-anchor-key") || "";
        const chunkId = diffRow.getAttribute("data-chunk-id") || "";
        const tableBody = diffRow.parentElement;
        if (!tableBody) {{
          return;
        }}
        const toRemove = [];
        let next = diffRow.nextElementSibling;
        while (next && next.classList && next.classList.contains("row-line-comment")) {{
          if ((next.getAttribute("data-anchor-key") || "") !== anchorKey) {{
            break;
          }}
          toRemove.push(next);
          next = next.nextElementSibling;
        }}
        for (const node of toRemove) {{
          node.remove();
        }}
        const clean = String(commentText || "").trim();
        if (!clean) {{
          return;
        }}
        const row = document.createElement("tr");
        row.className = "row-line-comment diff-row";
        row.setAttribute("data-kind", "line-comment");
        row.setAttribute("data-anchor-key", anchorKey);
        row.setAttribute("data-chunk-id", chunkId);
        row.setAttribute("data-text", clean.toLowerCase());
        row.innerHTML =
          "<td class='num'></td>" +
          "<td class='code old'></td>" +
          "<td class='num'></td>" +
          "<td class='code new comment'><span class='comment-label'>COMMENT</span> " + escapeHtml(clean) + "</td>";
        if (next && next.parentNode === tableBody) {{
          tableBody.insertBefore(row, next);
        }} else {{
          tableBody.appendChild(row);
        }}
      }}

      function getChunkStatusFromDraft(chunkId) {{
        const record = draftDoc.reviews[String(chunkId || "")];
        if (!record || typeof record != "object") {{
          return "unreviewed";
        }}
        return normalizeStatus(record.status);
      }}

      function refreshLineCommentVisualsForChunk(chunkEl) {{
        if (!chunkEl) {{
          return;
        }}
        chunkEl.querySelectorAll("tr.row-line-comment").forEach((row) => row.remove());
        const rows = Array.from(chunkEl.querySelectorAll("tr.diff-row"));
        rows.forEach((row) => {{
          const kind = row.getAttribute("data-kind") || "";
          if (kind == "line-comment") {{
            return;
          }}
          const chunkId = row.getAttribute("data-chunk-id") || "";
          const lineType = row.getAttribute("data-line-type") || kind || "context";
          const oldLine = row.getAttribute("data-old-line") || "";
          const newLine = row.getAttribute("data-new-line") || "";
          const comment = getLineCommentForAnchor(chunkId, oldLine, newLine, lineType);
          updateLineCommentVisual(row, comment);
        }});
      }}

      function refreshChunkVisualsFromDraft() {{
        allChunks().forEach((chunkEl) => {{
          const chunkId = chunkEl.getAttribute("data-chunk-id") || "";
          updateChunkStatusVisual(chunkEl, getChunkStatusFromDraft(chunkId));
          updateChunkCommentVisual(chunkEl, getChunkComment(chunkId));
          refreshLineCommentVisualsForChunk(chunkEl);
          refreshChunkCounters(chunkEl);
        }});
        refreshGroupBriefCard();
        restoreThreadState();
        restoreAnalysisState();
        restoreSelectedChunk();
        persistThreadState();
        persistAnalysisState();
        refreshReviewProgress();
        rebuildCommentPaneFromDraft();
        rebuildInboxFromDom();
        applyCommentFilters();
        applyFilters();
      }}

      function applyImportedState(statePayload) {{
        const normalized = normalizeImportedStatePayload(statePayload);
        draftDoc.reviews = cloneStateValue(normalized.reviews || {{}});
        draftDoc.groupBriefs = cloneStateValue(normalized.groupBriefs || {{}});
        draftDoc.analysisState = cloneStateValue(normalized.analysisState || {{}});
        draftDoc.threadState = cloneStateValue(normalized.threadState || {{}});
        state.importedStatePayload = cloneStateValue(normalized);
        refreshChunkVisualsFromDraft();
        updateImpactPlanActions();
      }}

      function refreshChunkCounters(chunkEl) {{
        if (!chunkEl) {{
          return;
        }}
        const chunkId = chunkEl.getAttribute("data-chunk-id") || "";
        const status = chunkEl.getAttribute("data-status") || "unreviewed";
        const chunkComment = getChunkComment(chunkId);
        const lineComments = getLineComments(chunkId);
        const lineCommentCount = lineComments.length;
        const totalCommentCount = (chunkComment ? 1 : 0) + lineCommentCount;

        chunkEl.setAttribute("data-has-comment", chunkComment ? "1" : "0");
        chunkEl.setAttribute("data-line-comment-count", String(lineCommentCount));
        chunkEl.setAttribute("data-comment-count", String(totalCommentCount));

        const summaryCount = chunkEl.querySelector(".chunk-comment-count");
        if (summaryCount) {{
          summaryCount.textContent = "comments " + totalCommentCount + " (line " + lineCommentCount + ")";
        }}

        const addCount = chunkEl.querySelectorAll("tr.diff-row[data-kind='add']").length;
        const delCount = chunkEl.querySelectorAll("tr.diff-row[data-kind='delete']").length;
        const changeCount = addCount + delCount;
        const actionable = (status === "unreviewed" || status === "needsReReview" || totalCommentCount > 0 || changeCount >= 36);
        const reasons = [];
        if (status === "unreviewed" || status === "needsReReview") {{
          reasons.push(status);
        }}
        if (totalCommentCount > 0) {{
          reasons.push("comment");
        }}
        if (changeCount >= 36) {{
          reasons.push("large-change");
        }}
        chunkEl.setAttribute("data-actionable", actionable ? "1" : "0");
        chunkEl.setAttribute("data-reason", reasons.length ? reasons.join(", ") : "normal");
      }}

      function rebuildInboxFromDom() {{
        if (!inboxList) {{
          return;
        }}
        const entries = [];
        for (const chunkEl of allChunks()) {{
          const chunkId = chunkEl.getAttribute("data-chunk-id") || "";
          const filePath = chunkEl.getAttribute("data-file-path") || "";
          const header = chunkEl.getAttribute("data-header") || "";
          const status = chunkEl.getAttribute("data-status") || "unreviewed";
          const comments = Number(chunkEl.getAttribute("data-comment-count") || "0");
          const adds = chunkEl.querySelectorAll("tr.diff-row[data-kind='add']").length;
          const deletes = chunkEl.querySelectorAll("tr.diff-row[data-kind='delete']").length;
          const lineComments = Number(chunkEl.getAttribute("data-line-comment-count") || "0");
          const changeCount = adds + deletes;
          let risk = changeCount + (lineComments * 3);
          if (status === "needsReReview") risk += 30;
          if (status === "unreviewed") risk += 16;
          if (status === "reviewed") risk -= 18;
          const actionable = (chunkEl.getAttribute("data-actionable") || "0") === "1";
          entries.push({{
            anchor: chunkEl.id,
            filePath: filePath,
            chunkId: chunkId,
            header: header,
            status: status,
            comments: comments,
            adds: adds,
            deletes: deletes,
            risk: risk,
            actionable: actionable,
            reason: chunkEl.getAttribute("data-reason") || "normal",
          }});
        }}
        entries.sort((a, b) => {{
          if (a.actionable !== b.actionable) {{
            return a.actionable ? -1 : 1;
          }}
          if (a.risk !== b.risk) {{
            return b.risk - a.risk;
          }}
          if (a.filePath !== b.filePath) {{
            return a.filePath < b.filePath ? -1 : 1;
          }}
          return a.chunkId < b.chunkId ? -1 : 1;
        }});

        const actionableCount = entries.filter((item) => item.actionable).length;
        if (inboxSub) {{
          inboxSub.textContent = "actionable " + actionableCount + " / total " + entries.length;
        }}

        if (!entries.length) {{
          inboxList.innerHTML = "<li class='inbox-empty'>(no chunks)</li>";
          return;
        }}

        const html = [];
        for (const item of entries) {{
          html.push(
            "<li class='inbox-item " + (item.actionable ? "is-actionable" : "is-normal") + "' data-actionable='" + (item.actionable ? "1" : "0") + "'" +
            " data-status='" + escapeHtml(item.status) + "' data-risk='" + escapeHtml(String(item.risk)) + "'" +
            " data-text='" + escapeHtml((item.filePath + " " + item.chunkId + " " + item.header + " " + item.reason).toLowerCase()) + "'>" +
            "<a class='inbox-link' href='#" + escapeHtml(item.anchor) + "'>" +
            "<span class='inbox-head'><span class='inbox-file'>" + escapeHtml(item.filePath) + "</span> <span class='inbox-chunk'>" + escapeHtml(item.chunkId.slice(0, 12)) + "</span></span>" +
            "<span class='inbox-meta'>" + statusBadgeHtml(item.status) +
            " <span class='risk-badge'>risk " + escapeHtml(String(item.risk)) + "</span>" +
            " <span class='delta-badge'>+" + escapeHtml(String(item.adds)) + "/-" + escapeHtml(String(item.deletes)) + "</span>" +
            " <span class='comment-count-badge'>comments " + escapeHtml(String(item.comments)) + "</span></span>" +
            "<span class='inbox-title'>" + escapeHtml(item.header || "(no header)") + "</span>" +
            "<span class='inbox-reason'>" + escapeHtml(item.reason) + "</span>" +
            "</a></li>"
          );
        }}
        inboxList.innerHTML = html.join("");
      }}

      function findRowIdForLineComment(chunkEl, lineComment) {{
        const targetKey = lineAnchorKey(lineComment.oldLine, lineComment.newLine, lineComment.lineType);
        const rows = Array.from(chunkEl.querySelectorAll("tr.diff-row"));
        for (const row of rows) {{
          if ((row.getAttribute("data-kind") || "") === "line-comment") {{
            continue;
          }}
          if ((row.getAttribute("data-anchor-key") || "") === targetKey) {{
            return row.id || chunkEl.id;
          }}
        }}
        return chunkEl.id;
      }}

      function rebuildCommentPaneFromDraft() {{
        if (!commentList) {{
          return;
        }}
        const entries = [];
        let chunkCommentCount = 0;
        let lineCommentCount = 0;
        let unresolvedCount = 0;

        for (const chunkEl of allChunks()) {{
          const chunkId = chunkEl.getAttribute("data-chunk-id") || "";
          if (!chunkId) {{
            continue;
          }}
          const filePath = chunkEl.getAttribute("data-file-path") || "";
          const status = chunkEl.getAttribute("data-status") || "unreviewed";
          const chunkComment = getChunkComment(chunkId);
          if (chunkComment) {{
            chunkCommentCount += 1;
            if (status === "unreviewed" || status === "needsReReview") {{
              unresolvedCount += 1;
            }}
            entries.push({{
              type: "chunk",
              anchor: chunkEl.id,
              chunkAnchor: chunkEl.id,
              anchorKey: "",
              filePath: filePath,
              chunkId: chunkId,
              status: status,
              text: chunkComment,
              unresolved: status === "unreviewed" || status === "needsReReview",
            }});
          }}
          const lineComments = getLineComments(chunkId);
          for (const lineComment of lineComments) {{
            lineCommentCount += 1;
            if (status === "unreviewed" || status === "needsReReview") {{
              unresolvedCount += 1;
            }}
            entries.push({{
              type: "line",
              anchor: findRowIdForLineComment(chunkEl, lineComment),
              chunkAnchor: chunkEl.id,
              anchorKey: lineAnchorKey(lineComment.oldLine, lineComment.newLine, lineComment.lineType),
              filePath: filePath,
              chunkId: chunkId,
              status: status,
              text: lineComment.comment,
              unresolved: status === "unreviewed" || status === "needsReReview",
            }});
          }}
        }}

        entries.sort((a, b) => {{
          if (a.unresolved !== b.unresolved) {{
            return a.unresolved ? -1 : 1;
          }}
          if (a.filePath !== b.filePath) {{
            return a.filePath < b.filePath ? -1 : 1;
          }}
          if (a.chunkId !== b.chunkId) {{
            return a.chunkId < b.chunkId ? -1 : 1;
          }}
          if (a.type !== b.type) {{
            return a.type === "chunk" ? -1 : 1;
          }}
          return 0;
        }});

        if (!entries.length) {{
          commentList.innerHTML = "<li class='comment-empty'>(no comments)</li>";
        }} else {{
          const html = [];
          let index = 1;
          for (const item of entries) {{
            html.push(
              "<li class='comment-item' data-status='" + escapeHtml(item.status) + "' data-unresolved='" + (item.unresolved ? "1" : "0") + "'" +
              " data-type='" + escapeHtml(item.type) + "' data-chunk-id='" + escapeHtml(item.chunkId) + "'" +
              " data-anchor-key='" + escapeHtml(item.anchorKey || "") + "' data-chunk-anchor='" + escapeHtml(item.chunkAnchor || "") + "'" +
              " data-text='" + escapeHtml((item.filePath + " " + item.chunkId + " " + item.text).toLowerCase()) + "'>" +
              "<a class='comment-jump' href='#" + escapeHtml(item.anchor) + "'>#"+ escapeHtml(String(index)) + "</a>" +
              "<div class='comment-body'>" +
              "<div class='comment-meta'>" +
              "<span class='comment-file'>" + escapeHtml(item.filePath) + "</span>" +
              "<span class='comment-chunk'>" + escapeHtml(item.chunkId.slice(0, 12)) + "</span>" +
              "<span class='comment-type'>" + (item.type === "chunk" ? "CHUNK" : "LINE") + "</span>" +
              statusBadgeHtml(item.status) +
              "<button class='comment-edit-btn' type='button' data-action='edit-comment-item'>Edit</button>" +
              "</div>" +
              "<p class='comment-text'>" + escapeHtml(item.text) + "</p>" +
              "</div></li>"
            );
            index += 1;
          }}
          commentList.innerHTML = html.join("");
        }}

        const total = chunkCommentCount + lineCommentCount;
        if (commentTotal) commentTotal.textContent = String(total);
        if (commentUnresolved) commentUnresolved.textContent = String(unresolvedCount);
        if (statCommentsTotal) statCommentsTotal.textContent = String(total);
        if (statCommentsChunk) statCommentsChunk.textContent = String(chunkCommentCount);
        if (statCommentsLine) statCommentsLine.textContent = String(lineCommentCount);
      }}

      async function editChunkComment(chunkEl) {{
        if (!chunkEl) {{
          return;
        }}
        const chunkId = chunkEl.getAttribute("data-chunk-id") || "";
        if (!chunkId) {{
          return;
        }}
        setSelectedChunkId(chunkId);
        const initial = getChunkComment(chunkId);
        const result = await openCommentEditor({{
          title: "Chunk Comment",
          subtitle: "Enter chunk-level review comment. Empty value deletes existing comment.",
          initial: initial,
          fallbackPrompt: "Chunk comment (empty to delete)",
        }});
        if (result === null) {{
          return;
        }}
        setChunkComment(chunkId, result);
        updateChunkCommentVisual(chunkEl, result);
        refreshChunkCounters(chunkEl);
        rebuildCommentPaneFromDraft();
        rebuildInboxFromDom();
        applyFilters();
        applyCommentFilters();
      }}

      async function editLineCommentFromRow(row) {{
        if (!row) {{
          return;
        }}
        if ((row.getAttribute("data-kind") || "") === "line-comment") {{
          return;
        }}
        const chunkId = row.getAttribute("data-chunk-id") || "";
        const lineType = row.getAttribute("data-line-type") || row.getAttribute("data-kind") || "context";
        const oldLine = row.getAttribute("data-old-line") || "";
        const newLine = row.getAttribute("data-new-line") || "";
        if (!chunkId) {{
          return;
        }}
        setSelectedChunkId(chunkId);
        const initial = getLineCommentForAnchor(chunkId, oldLine, newLine, lineType);
        const oldLabel = oldLine || "-";
        const newLabel = newLine || "-";
        const result = await openCommentEditor({{
          title: "Line Comment (old " + oldLabel + " / new " + newLabel + ")",
          subtitle: "Enter line-level review comment. Empty value deletes existing comment.",
          initial: initial,
          fallbackPrompt: "Line comment old " + oldLabel + " / new " + newLabel + " (empty to delete)",
        }});
        if (result === null) {{
          return;
        }}
        setLineCommentForAnchor(chunkId, oldLine, newLine, lineType, result);
        updateLineCommentVisual(row, result);
        const chunkEl = row.closest(".chunk");
        refreshChunkCounters(chunkEl);
        rebuildCommentPaneFromDraft();
        rebuildInboxFromDom();
        applyFilters();
        applyCommentFilters();
      }}

      function findLineRowByAnchorKey(chunkId, anchorKey) {{
        const targetChunk = findChunkById(chunkId);
        if (!targetChunk) {{
          return null;
        }}
        const rows = Array.from(targetChunk.querySelectorAll("tr.diff-row"));
        for (const row of rows) {{
          const kind = row.getAttribute("data-kind") || "";
          if (kind === "line-comment") {{
            continue;
          }}
          if ((row.getAttribute("data-anchor-key") || "") === String(anchorKey || "")) {{
            return row;
          }}
        }}
        return null;
      }}

      async function editCommentItemFromPane(commentItemEl) {{
        if (!commentItemEl) {{
          return;
        }}
        const itemType = commentItemEl.getAttribute("data-type") || "line";
        const chunkId = commentItemEl.getAttribute("data-chunk-id") || "";
        if (!chunkId) {{
          return;
        }}
        if (itemType === "chunk") {{
          const chunkEl = findChunkById(chunkId);
          await editChunkComment(chunkEl);
          return;
        }}
        const anchorKey = commentItemEl.getAttribute("data-anchor-key") || "";
        const row = findLineRowByAnchorKey(chunkId, anchorKey);
        await editLineCommentFromRow(row);
      }}

      function applyFilters() {{
        const fq = ((fileInput && fileInput.value) || "").trim().toLowerCase();
        const cq = ((contentInput && contentInput.value) || "").trim().toLowerCase();
        const visibleFileKeys = new Set();
        let visibleFiles = 0;
        let visibleChunks = 0;
        let visibleRows = 0;

        sections.forEach((section) => {{
          const fileKey = section.getAttribute("data-file") || "";
          const fileNameMatch = !fq || fileKey.includes(fq);
          let sectionVisible = false;

          section.querySelectorAll(".chunk").forEach((chunk) => {{
            const chunkRows = Array.from(chunk.querySelectorAll("tr.diff-row"));
            const chunkComment = chunk.querySelector(".chunk-comment");
            const chunkText = [
              chunk.getAttribute("data-chunk-id") || "",
              chunk.getAttribute("data-header") || "",
              chunkComment ? (chunkComment.getAttribute("data-text") || "") : "",
            ].join(" ");

            let chunkVisibleRows = 0;
            let hasVisibleLineComment = false;
            chunkRows.forEach((row) => {{
              const kind = row.getAttribute("data-kind") || "";
              const rowText = row.getAttribute("data-text") || "";
              const rowQueryMatch = !cq || rowText.includes(cq);
              row.classList.toggle("match", !!cq && rowQueryMatch);

              let rowVisible = rowQueryMatch;
              if (state.hideContext && kind == "context") {{
                rowVisible = false;
              }}
              if (state.commentsOnly && kind != "line-comment") {{
                rowVisible = false;
              }}
              row.style.display = rowVisible ? "" : "none";
              if (rowVisible) {{
                chunkVisibleRows += 1;
                if (kind == "line-comment") {{
                  hasVisibleLineComment = true;
                }}
              }}
            }});

            let chunkCommentVisible = false;
            if (chunkComment) {{
              const commentText = chunkComment.getAttribute("data-text") || "";
              chunkCommentVisible = !cq || commentText.includes(cq);
              chunkComment.style.display = chunkCommentVisible ? "" : "none";
            }}

            let chunkVisible = fileNameMatch && (chunkVisibleRows > 0 || chunkCommentVisible);
            if (state.commentsOnly) {{
              chunkVisible = fileNameMatch && (hasVisibleLineComment || chunkCommentVisible);
            }}
            if (state.inboxMode && chunk.getAttribute("data-actionable") != "1") {{
              chunkVisible = false;
            }}

            chunk.classList.toggle("hidden-by-filter", !chunkVisible);
            if (chunkVisible) {{
              sectionVisible = true;
              visibleChunks += 1;
              visibleRows += chunkVisibleRows;
            }}
          }});

          section.classList.toggle("hidden-by-filter", !sectionVisible);
          if (sectionVisible) {{
            visibleFileKeys.add(fileKey);
            visibleFiles += 1;
          }}
        }});

        navItems.forEach((li) => {{
          const key = li.getAttribute("data-nav-key") || "";
          const navType = li.getAttribute("data-nav-type") || "file";
          const show = navType === "group" ? (!fq || key.includes(fq)) : visibleFileKeys.has(key);
          li.style.display = show ? "" : "none";
        }});

        if (fileHit) {{
          if (!fq && !cq) {{
            fileHit.textContent = "showing all files";
          }} else {{
            fileHit.textContent = "showing " + visibleFiles + " file(s)";
          }}
        }}
        if (contentHit) {{
          if (!cq) {{
            contentHit.textContent = "showing " + visibleChunks + " chunk(s) / " + visibleRows + " row(s)";
          }} else {{
            contentHit.textContent = "query hit: " + visibleChunks + " chunk(s) / " + visibleRows + " row(s)";
          }}
        }}

        const liveInboxItems = Array.from(document.querySelectorAll(".inbox-item"));
        liveInboxItems.forEach((item) => {{
          if (!state.inboxMode) {{
            item.style.display = "";
            return;
          }}
          const actionable = item.getAttribute("data-actionable") === "1";
          item.style.display = actionable ? "" : "none";
        }});
      }}

      function setOpen(value) {{
        sections.forEach((section) => {{
          section.open = value;
          section.querySelectorAll(".chunk").forEach((chunk) => {{
            chunk.open = value;
          }});
        }});
      }}

      if (fileInput) {{
        fileInput.addEventListener("input", () => {{
          persistAnalysisState();
          applyFilters();
        }});
      }}
      if (contentInput) {{
        contentInput.addEventListener("input", () => {{
          persistAnalysisState();
          applyFilters();
        }});
      }}
      if (expandBtn) {{
        expandBtn.addEventListener("click", () => {{
          setOpen(true);
          persistThreadState();
        }});
      }}
      if (collapseBtn) {{
        collapseBtn.addEventListener("click", () => {{
          setOpen(false);
          persistThreadState();
        }});
      }}
      if (toggleInboxBtn) {{
        toggleInboxBtn.addEventListener("click", () => {{
          state.inboxMode = !state.inboxMode;
          setPressed(toggleInboxBtn, state.inboxMode);
          if (inboxPanel) {{
            inboxPanel.hidden = !state.inboxMode;
          }}
          document.body.classList.toggle("inbox-mode", state.inboxMode);
          persistAnalysisState();
          applyFilters();
        }});
      }}
      if (toggleImpactPreviewBtn) {{
        toggleImpactPreviewBtn.addEventListener("click", () => {{
          const next = !(impactPreviewPanel && !impactPreviewPanel.hidden);
          setPressed(toggleImpactPreviewBtn, next);
          if (impactPreviewPanel) {{
            impactPreviewPanel.hidden = !next;
          }}
        }});
      }}
      if (toggleContextBtn) {{
        toggleContextBtn.addEventListener("click", () => {{
          state.hideContext = !state.hideContext;
          setPressed(toggleContextBtn, state.hideContext);
          persistAnalysisState();
          applyFilters();
        }});
      }}
      if (toggleCommentsBtn) {{
        toggleCommentsBtn.addEventListener("click", () => {{
          state.commentsOnly = !state.commentsOnly;
          setPressed(toggleCommentsBtn, state.commentsOnly);
          persistAnalysisState();
          applyFilters();
        }});
      }}
      if (toggleWrapBtn) {{
        toggleWrapBtn.addEventListener("click", () => {{
          const next = toggleWrapBtn.getAttribute("aria-pressed") != "true";
          setPressed(toggleWrapBtn, next);
          document.body.classList.toggle("no-wrap", !next);
          persistAnalysisState();
        }});
      }}
      if (toggleCompactBtn) {{
        toggleCompactBtn.addEventListener("click", () => {{
          const next = toggleCompactBtn.getAttribute("aria-pressed") != "true";
          setPressed(toggleCompactBtn, next);
          document.body.classList.toggle("compact", next);
          persistAnalysisState();
        }});
      }}
      if (toggleUnresolvedCommentBtn) {{
        toggleUnresolvedCommentBtn.addEventListener("click", () => {{
          state.commentUnresolvedOnly = !state.commentUnresolvedOnly;
          setPressed(toggleUnresolvedCommentBtn, state.commentUnresolvedOnly);
          persistAnalysisState();
          applyCommentFilters();
        }});
      }}
      if (commentInput) {{
        commentInput.addEventListener("input", () => {{
          persistAnalysisState();
          applyCommentFilters();
        }});
      }}

      if (downloadJsonBtn) {{
        downloadJsonBtn.addEventListener("click", () => {{
          const output = JSON.stringify(draftDoc, null, 2) + "\\n";
          const blob = new Blob([output], {{ type: "application/json;charset=utf-8" }});
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = "diffgr-reviewed.json";
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);
        }});
      }}
      if (downloadStateBtn) {{
        downloadStateBtn.addEventListener("click", () => {{
          const output = JSON.stringify(currentStatePayload(), null, 2) + "\\n";
          const blob = new Blob([output], {{ type: "application/json;charset=utf-8" }});
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = "diffgr-state.json";
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);
        }});
      }}
      if (importStateBtn && importStateFile) {{
        importStateBtn.addEventListener("click", () => {{
          importStateFile.value = "";
          importStateFile.click();
        }});
        importStateFile.addEventListener("change", async () => {{
          const file = importStateFile.files && importStateFile.files[0];
          if (!file) {{
            return;
          }}
          try {{
            const text = await file.text();
            const payload = JSON.parse(text);
            applyImportedState(payload);
            state.importedStateLabel = "imported:" + (file.name || "state.json");
            setStateSourceLabel(state.importedStateLabel);
            updateImpactPlanActions();
            setSaveStatus("state imported", false);
          }} catch (error) {{
            const message = error && error.message ? error.message : String(error);
            setSaveStatus("state import failed: " + message, true);
            window.alert("Failed to import state: " + message);
          }} finally {{
            importStateFile.value = "";
          }}
        }});
      }}
      if (diffStateBtn) {{
        diffStateBtn.addEventListener("click", () => {{
          if (!state.importedStatePayload) {{
            window.alert("No imported state is available for comparison.");
            return;
          }}
          const label = state.importedStateLabel || "imported state";
          const report = (initialStateDiffReport && state.importedStateLabel === initialStateSourceLabel)
            ? initialStateDiffReport
            : buildStateDiffReport(currentStatePayload(), state.importedStatePayload, label);
          state.lastStateDiffTokens = report.selectionTokens;
          if (stateDiffSub) {{
            stateDiffSub.textContent =
              "State Diff vs " + label +
              " | tokens=" + state.lastStateDiffTokens.length +
              " | Use Copy Tokens or Apply These Tokens.";
          }}
          if (stateDiffPreview) {{
            stateDiffPreview.textContent = renderStateDiffReport(report);
          }}
          if (stateDiffModal) {{
            stateDiffModal.showModal();
          }}
        }});
      }}
      function openStateSelectionWithTokens(tokens) {{
        if (!state.importedStatePayload) {{
          window.alert("No imported state is available for selective apply.");
          return;
        }}
        const normalized = Array.isArray(tokens)
          ? tokens.map((item) => String(item || "").trim()).filter(Boolean)
          : [];
        stateSelectionInput.value = normalized.join("\\n");
        state.lastStateSelectionPreview = null;
        state.lastStateSelectionRaw = "";
        state.lastStateSelectionBasePayload = null;
        if (stateSelectionPreview) {{
          stateSelectionPreview.textContent = "Preview selected tokens to inspect the result diff before apply.";
        }}
        if (stateSelectionApply) {{
          stateSelectionApply.disabled = true;
        }}
        if (stateSelectionModal) {{
          stateSelectionModal.showModal();
          stateSelectionInput.focus();
        }}
      }}
      function openStateSelectionPreviewWithTokens(tokens, sourceLabel, baseStateOverride, baseLabelOverride) {{
        if (!state.importedStatePayload) {{
          window.alert("No imported state is available for selective apply.");
          return;
        }}
        const normalized = Array.isArray(tokens)
          ? tokens.map((item) => String(item || "").trim()).filter(Boolean)
          : [];
        const rawTokens = normalized.join("\\n");
        const baseLabel = String(baseLabelOverride || state.importedStateLabel || "").trim();
        stateSelectionInput.value = rawTokens;
        state.lastStateSelectionBasePayload = baseStateOverride ? cloneStateValue(baseStateOverride) : null;
        if (!normalized.length) {{
          state.lastStateSelectionPreview = null;
          state.lastStateSelectionRaw = rawTokens;
          if (stateSelectionPreview) {{
            stateSelectionPreview.textContent =
              "selected=0 no-op=0 changed-sections=0\\n\\n" +
              "selection plan is empty" +
              (sourceLabel ? "\\nsource=" + sourceLabel : "") +
              (baseLabel ? "\\nbase=" + baseLabel : "");
          }}
          if (stateSelectionApply) {{
            stateSelectionApply.disabled = true;
          }}
          if (stateSelectionModal) {{
            stateSelectionModal.showModal();
            stateSelectionInput.focus();
          }}
          return;
        }}
        const report = buildSelectionPreviewReport(rawTokens, sourceLabel, baseLabel);
        state.lastStateSelectionPreview = report;
        state.lastStateSelectionRaw = rawTokens;
        if (stateSelectionPreview) {{
          stateSelectionPreview.textContent = renderSelectionPreviewReport(report);
        }}
        if (stateSelectionApply) {{
          stateSelectionApply.disabled = false;
        }}
        if (stateSelectionModal) {{
          stateSelectionModal.showModal();
          stateSelectionInput.focus();
        }}
      }}
      function reviewStateFingerprint(payload) {{
        return canonicalStateString(normalizeImportedStatePayload(payload || {{}}));
      }}
      function currentImpactApplyAvailability() {{
        if (!impactStateLabel) {{
          return {{ ok: false, reason: "selection apply unavailable: impact preview has no state source" }};
        }}
        if (!impactStateFingerprint) {{
          return {{ ok: false, reason: "selection apply unavailable: impact state fingerprint is missing" }};
        }}
        if (!state.importedStatePayload) {{
          return {{ ok: false, reason: "selection apply unavailable: import the same state first" }};
        }}
        const currentLabel = String(state.importedStateLabel || "").trim();
        if (reviewStateFingerprint(state.importedStatePayload) == impactStateFingerprint) {{
          return {{ ok: true, reason: "selection apply available via " + currentLabel }};
        }}
        return {{
          ok: false,
          reason: "selection apply unavailable: current state source is " + (currentLabel || "embedded") + "; import the matching " + impactStateLabel + " first",
        }};
      }}
      function updateImpactPlanActions() {{
        const availability = currentImpactApplyAvailability();
        if (impactPlanStatus) {{
          impactPlanStatus.textContent = availability.reason;
        }}
        document.querySelectorAll("[data-action='apply-impact-plan']").forEach((button) => {{
          button.disabled = !availability.ok;
        }});
      }}
      if (stateDiffCopy) {{
        stateDiffCopy.addEventListener("click", async () => {{
          if (!state.lastStateDiffTokens.length) {{
            window.alert("No selection tokens are available in the current diff.");
            return;
          }}
          const text = state.lastStateDiffTokens.join("\\n");
          if (!navigator.clipboard || !navigator.clipboard.writeText) {{
            window.alert("Clipboard API is not available in this browser.");
            return;
          }}
          try {{
            await navigator.clipboard.writeText(text);
            setSaveStatus("state diff tokens copied", false);
          }} catch (_error) {{
            window.alert("Failed to copy state diff tokens.");
          }}
        }});
      }}
      if (stateDiffApply) {{
        stateDiffApply.addEventListener("click", () => {{
          if (!state.importedStatePayload) {{
            window.alert("No imported state is available for selective apply.");
            return;
          }}
          if (!state.lastStateDiffTokens.length) {{
            window.alert("No selection tokens are available in the current diff.");
            return;
          }}
          if (stateDiffModal) {{
            stateDiffModal.close();
          }}
          openStateSelectionWithTokens(state.lastStateDiffTokens);
        }});
      }}
      document.querySelectorAll("[data-action='copy-impact-plan']").forEach((button) => {{
        button.addEventListener("click", async () => {{
          const item = button.closest("[data-impact-plan]");
          const raw = item ? item.getAttribute("data-impact-tokens") || "[]" : "[]";
          let tokens = [];
          try {{
            tokens = JSON.parse(raw);
          }} catch (_error) {{
            tokens = [];
          }}
          if (!Array.isArray(tokens) || !tokens.length) {{
            window.alert("No selection tokens are available for this plan.");
            return;
          }}
          if (!navigator.clipboard || !navigator.clipboard.writeText) {{
            window.alert("Clipboard API is not available in this browser.");
            return;
          }}
          try {{
            await navigator.clipboard.writeText(tokens.join("\\n"));
            setSaveStatus("impact selection tokens copied", false);
          }} catch (_error) {{
            window.alert("Failed to copy impact selection tokens.");
          }}
        }});
      }});
      document.querySelectorAll("[data-action='apply-impact-plan']").forEach((button) => {{
        button.addEventListener("click", () => {{
          const availability = currentImpactApplyAvailability();
          if (!availability.ok) {{
            window.alert(availability.reason);
            return;
          }}
          const item = button.closest("[data-impact-plan]");
          const raw = item ? item.getAttribute("data-impact-tokens") || "[]" : "[]";
          let tokens = [];
          try {{
            tokens = JSON.parse(raw);
          }} catch (_error) {{
            tokens = [];
          }}
          if (impactPreviewPanel) {{
            impactPreviewPanel.hidden = true;
          }}
          if (toggleImpactPreviewBtn) {{
            setPressed(toggleImpactPreviewBtn, false);
          }}
          const planName = item ? String(item.getAttribute("data-impact-plan") || "").trim() : "";
          openStateSelectionPreviewWithTokens(
            tokens,
            planName ? "impact:" + planName : "impact",
            state.importedStatePayload,
            state.importedStateLabel,
          );
        }});
      }});
      if (applyStateSelectionBtn && stateSelectionModal && stateSelectionForm && stateSelectionInput) {{
        applyStateSelectionBtn.addEventListener("click", () => {{
          openStateSelectionWithTokens([]);
        }});
        stateSelectionInput.addEventListener("input", () => {{
          state.lastStateSelectionPreview = null;
          state.lastStateSelectionRaw = "";
          if (stateSelectionPreview) {{
            stateSelectionPreview.textContent = "Preview selected tokens to inspect the result diff before apply.";
          }}
          if (stateSelectionApply) {{
            stateSelectionApply.disabled = true;
          }}
        }});
        stateSelectionForm.addEventListener("submit", (event) => {{
          event.preventDefault();
          const submitter = event.submitter;
          const action = submitter ? submitter.getAttribute("value") : "";
          if (action == "cancel") {{
            stateSelectionModal.close();
            return;
          }}
          try {{
            const rawTokens = stateSelectionInput.value;
            if (action == "preview") {{
              const baseLabel = state.lastStateSelectionBasePayload ? String(state.importedStateLabel || "").trim() : "";
              const report = buildSelectionPreviewReport(rawTokens, null, baseLabel);
              state.lastStateSelectionPreview = report;
              state.lastStateSelectionRaw = rawTokens;
              if (stateSelectionPreview) {{
                stateSelectionPreview.textContent = renderSelectionPreviewReport(report);
              }}
              if (stateSelectionApply) {{
                stateSelectionApply.disabled = false;
              }}
              return;
            }}
            if (action != "apply") {{
              return;
            }}
            if (!state.lastStateSelectionPreview || state.lastStateSelectionRaw !== rawTokens) {{
              if (stateSelectionPreview) {{
                stateSelectionPreview.textContent = "Run Preview first for the current tokens.";
              }}
              if (stateSelectionApply) {{
                stateSelectionApply.disabled = true;
              }}
              return;
            }}
            const appliedPreview = applySelectedStateTokens(rawTokens);
            setSaveStatus(
              "selected state applied (" +
              appliedPreview.selectedKeyCount +
              " key(s), no-op=" + appliedPreview.noOpCount +
              ", changed-sections=" + appliedPreview.changedSectionCount + ")",
              false
            );
            state.lastStateSelectionPreview = null;
            state.lastStateSelectionRaw = "";
            state.lastStateSelectionBasePayload = null;
            stateSelectionModal.close();
          }} catch (error) {{
            const message = error && error.message ? error.message : String(error);
            state.lastStateSelectionPreview = null;
            state.lastStateSelectionRaw = "";
            state.lastStateSelectionBasePayload = null;
            if (stateSelectionApply) {{
              stateSelectionApply.disabled = true;
            }}
            setSaveStatus("state apply failed: " + message, true);
            window.alert("Failed to apply selected state: " + message);
          }}
        }});
      }}
      if (copyStateBtn) {{
        copyStateBtn.addEventListener("click", async () => {{
          const text = JSON.stringify(currentStatePayload(), null, 2);
          if (!navigator.clipboard || !navigator.clipboard.writeText) {{
            window.alert("Clipboard API is not available in this browser.");
            return;
          }}
          try {{
            await navigator.clipboard.writeText(text);
            const original = copyStateBtn.textContent;
            copyStateBtn.textContent = "Copied";
            setTimeout(() => {{
              copyStateBtn.textContent = original;
            }}, 1000);
          }} catch (_error) {{
          window.alert("Failed to copy state.");
          }}
        }});
      }}
      setStateSourceLabel(state.importedStateLabel);
      updateImpactPlanActions();
      if (viewGroupBriefBtn) {{
        viewGroupBriefBtn.addEventListener("click", () => {{
          openGroupBriefViewer();
        }});
      }}
      if (editGroupBriefBtn) {{
        editGroupBriefBtn.addEventListener("click", () => {{
          openGroupBriefEditor();
        }});
      }}
      const briefViewerCloseBtn = document.getElementById("brief-viewer-close");
      const briefViewerEditBtn = document.getElementById("brief-viewer-edit");
      if (briefViewerCloseBtn) {{
        briefViewerCloseBtn.addEventListener("click", () => {{
          if (briefViewerModal) briefViewerModal.close();
        }});
      }}
      if (briefViewerEditBtn) {{
        briefViewerEditBtn.addEventListener("click", () => {{
          if (briefViewerModal) briefViewerModal.close();
          openGroupBriefEditor();
        }});
      }}
      if (saveStateBtn) {{
        if (!saveStateUrl) {{
          saveStateBtn.hidden = true;
          setSaveStatus("", false);
        }} else {{
          saveStateBtn.hidden = false;
          saveStateBtn.textContent = saveStateLabel;
          setSaveStatus("autosave ready", false);
          saveStateBtn.addEventListener("click", async () => {{
            const original = saveStateBtn.textContent || saveStateLabel;
            const payload = currentStatePayload();
            saveStateBtn.disabled = true;
            saveStateBtn.textContent = "Saving...";
            setSaveStatus("saving...", false);
            try {{
              const response = await fetch(saveStateUrl, {{
                method: "POST",
                headers: {{
                  "Content-Type": "application/json",
                }},
                body: JSON.stringify(payload),
              }});
              const raw = await response.text();
              let body = {{}};
              if (raw) {{
                try {{
                  body = JSON.parse(raw);
                }} catch (_error) {{
                  body = {{}};
                }}
              }}
              if (!response.ok) {{
                const detail = body && body.error ? String(body.error) : ("HTTP " + response.status);
                throw new Error(detail);
              }}
              const savedAt = body && body.savedAt ? String(body.savedAt) : "";
              setSaveStatus(savedAt ? ("saved " + savedAt) : "saved", false);
              saveStateBtn.textContent = "Saved";
              setTimeout(() => {{
                saveStateBtn.textContent = original;
              }}, 1000);
            }} catch (error) {{
              const message = error && error.message ? error.message : String(error);
              setSaveStatus("save failed: " + message, true);
              window.alert("Failed to save state: " + message);
            }} finally {{
              saveStateBtn.disabled = false;
            }}
          }});
        }}
      }}

      document.addEventListener("click", (event) => {{
        const target = event.target;
        if (!(target instanceof Element)) {{
          return;
        }}
        if (target.closest("label.review-toggle, input[data-action='toggle-reviewed']")) {{
          event.stopPropagation();
          return;
        }}

        const lineBtn = target.closest("button[data-action='line-comment']");
        if (lineBtn) {{
          event.preventDefault();
          event.stopPropagation();
          const row = lineBtn.closest("tr.diff-row");
          void editLineCommentFromRow(row);
          return;
        }}

        const chunkBtn = target.closest("button[data-action='chunk-comment']");
        if (chunkBtn) {{
          event.preventDefault();
          event.stopPropagation();
          const chunkEl = chunkBtn.closest(".chunk");
          if (chunkEl) {{
            setSelectedChunkId(chunkEl.getAttribute("data-chunk-id") || "");
          }}
          void editChunkComment(chunkEl);
          return;
        }}

        const editCommentBtn = target.closest("button[data-action='edit-comment-item']");
        if (editCommentBtn) {{
          event.preventDefault();
          event.stopPropagation();
          const commentItemEl = editCommentBtn.closest(".comment-item");
          if (commentItemEl) {{
            setSelectedChunkId(commentItemEl.getAttribute("data-chunk-id") || "");
          }}
          void editCommentItemFromPane(commentItemEl);
          return;
        }}

        const jumpLink = target.closest("a.inbox-link, a.comment-jump");
        if (jumpLink) {{
          const href = jumpLink.getAttribute("href") || "";
          if (!href.startsWith("#")) {{
            return;
          }}
          const targetId = href.slice(1);
          if (!targetId) {{
            return;
          }}
          event.preventDefault();
          revealTargetById(targetId);
          return;
        }}
      }});

      document.addEventListener("change", (event) => {{
        const target = event.target;
        if (!(target instanceof Element)) {{
          return;
        }}
        const reviewedInput = target.closest("input[data-action='toggle-reviewed']");
        if (!reviewedInput || !(reviewedInput instanceof HTMLInputElement)) {{
          return;
        }}
        event.stopPropagation();
        const chunkEl = reviewedInput.closest(".chunk");
        if (!chunkEl) {{
          return;
        }}
        const chunkId = chunkEl.getAttribute("data-chunk-id") || "";
        if (!chunkId) {{
          return;
        }}
        const status = reviewedInput.checked ? "reviewed" : "unreviewed";
        setSelectedChunkId(chunkId);
        setChunkStatus(chunkId, status);
        updateChunkStatusVisual(chunkEl, status);
        refreshChunkCounters(chunkEl);
        rebuildCommentPaneFromDraft();
        rebuildInboxFromDom();
        refreshReviewProgress();
        applyFilters();
        applyCommentFilters();
      }});

      allFileSections().forEach((section) => {{
        section.addEventListener("toggle", () => {{
          persistThreadState();
        }});
      }});
      allChunks().forEach((chunkEl) => {{
        chunkEl.addEventListener("toggle", () => {{
          if (chunkEl.open) {{
            setSelectedChunkId(chunkEl.getAttribute("data-chunk-id") || "");
          }}
          persistThreadState();
          persistAnalysisState();
        }});
      }});

      function applyCommentFilters() {{
        const query = ((commentInput && commentInput.value) || "").trim().toLowerCase();
        let visible = 0;
        const liveCommentItems = Array.from(document.querySelectorAll(".comment-item"));
        liveCommentItems.forEach((item) => {{
          const text = item.getAttribute("data-text") || "";
          const unresolved = item.getAttribute("data-unresolved") === "1";
          const queryMatch = !query || text.includes(query);
          const unresolvedMatch = !state.commentUnresolvedOnly || unresolved;
          const show = queryMatch && unresolvedMatch;
          item.style.display = show ? "" : "none";
          if (show) {{
            visible += 1;
          }}
        }});
        if (commentHit) {{
          commentHit.textContent = "showing " + visible + " comment(s)";
        }}
      }}

      document.addEventListener("keydown", (event) => {{
        const tag = ((event.target && event.target.tagName) || "").toLowerCase();
        const editing = tag == "input" || tag == "textarea";
        if (event.key == "/" && !editing) {{
          event.preventDefault();
          if (contentInput) {{
            contentInput.focus();
            contentInput.select();
          }}
          return;
        }}
        if (event.key == "f" && !editing) {{
          event.preventDefault();
          if (fileInput) {{
            fileInput.focus();
            fileInput.select();
          }}
          return;
        }}
        if (event.key == "i" && !editing && toggleInboxBtn) {{
          event.preventDefault();
          toggleInboxBtn.click();
          return;
        }}
        if (event.key == "k" && !editing) {{
          event.preventDefault();
          const firstActionable = document.querySelector(".inbox-item[data-actionable='1'] .inbox-link");
          if (firstActionable && firstActionable.getAttribute("href")) {{
            const targetId = firstActionable.getAttribute("href").replace(/^#/, "");
            revealTargetById(targetId);
          }}
          return;
        }}
        if (event.key == "c" && !editing && toggleContextBtn) {{
          event.preventDefault();
          toggleContextBtn.click();
          return;
        }}
        if (event.key == "m" && !editing && toggleCommentsBtn) {{
          event.preventDefault();
          toggleCommentsBtn.click();
          return;
        }}
        if (event.key == "w" && !editing && toggleWrapBtn) {{
          event.preventDefault();
          toggleWrapBtn.click();
          return;
        }}
        if (event.key == "j" && !editing && toggleCompactBtn) {{
          event.preventDefault();
          toggleCompactBtn.click();
          return;
        }}
        if (event.key == "Escape" && editing) {{
          const target = event.target;
          if (target && typeof target.blur == "function") {{
            target.blur();
          }}
        }}
      }});

      setPressed(toggleWrapBtn, true);
      setPressed(toggleInboxBtn, false);
      setPressed(toggleImpactPreviewBtn, false);
      setPressed(toggleContextBtn, false);
      setPressed(toggleCommentsBtn, false);
      setPressed(toggleCompactBtn, false);
      setPressed(toggleUnresolvedCommentBtn, false);
      if (inboxPanel) {{
        inboxPanel.hidden = true;
      }}
      if (impactPreviewPanel) {{
        impactPreviewPanel.hidden = true;
      }}
      restoreThreadState();
      restoreAnalysisState();
      restoreSelectedChunk();
      for (const chunkEl of allChunks()) {{
        refreshChunkCounters(chunkEl);
      }}
      persistThreadState();
      persistAnalysisState();
      refreshGroupBriefCard();
      refreshReviewProgress();
      rebuildCommentPaneFromDraft();
      rebuildInboxFromDom();
      applyFilters();
      applyCommentFilters();

      // ── Diff old/new column resizer ──────────────────────────
      (function() {{
        const STORAGE_KEY = "diffgr-split-ratio";
        let splitRatio = Math.min(0.85, Math.max(0.15, parseFloat(localStorage.getItem(STORAGE_KEY) || "0.5")));

        function numW() {{
          return document.body.classList.contains("compact") ? 58 : 68;
        }}

        function applyRatio(ratio) {{
          document.querySelectorAll(".diff-table").forEach((table) => {{
            const cols = table.querySelectorAll("col");
            if (cols.length < 4) return;
            const codeW = table.offsetWidth - numW() * 2;
            if (codeW <= 0) return;
            cols[1].style.width = Math.round(codeW * ratio) + "px";
            cols[3].style.width = Math.round(codeW * (1 - ratio)) + "px";
          }});
          splitRatio = ratio;
        }}

        function handleX() {{
          const table = document.querySelector(".diff-table");
          if (!table) return null;
          const rect = table.getBoundingClientRect();
          const codeW = table.offsetWidth - numW() * 2;
          return rect.left + numW() + codeW * splitRatio;
        }}

        function positionHandle(handle) {{
          const x = handleX();
          if (x !== null) handle.style.left = (x - 3) + "px";
        }}

        applyRatio(splitRatio);

        const handle = document.createElement("div");
        handle.id = "diff-split-handle";
        document.body.appendChild(handle);
        positionHandle(handle);

        window.addEventListener("resize", () => {{ applyRatio(splitRatio); positionHandle(handle); }});
        document.addEventListener("scroll", () => positionHandle(handle), true);

        let dragging = false, startX, startRatio;
        handle.addEventListener("mousedown", (e) => {{
          dragging = true;
          startX = e.clientX;
          startRatio = splitRatio;
          handle.classList.add("dragging");
          e.preventDefault();
        }});
        document.addEventListener("mousemove", (e) => {{
          if (!dragging) return;
          const table = document.querySelector(".diff-table");
          if (!table) return;
          const codeW = table.offsetWidth - numW() * 2;
          if (codeW <= 0) return;
          const newRatio = Math.min(0.85, Math.max(0.15, startRatio + (e.clientX - startX) / codeW));
          applyRatio(newRatio);
          positionHandle(handle);
        }});
        document.addEventListener("mouseup", () => {{
          if (!dragging) return;
          dragging = false;
          handle.classList.remove("dragging");
          localStorage.setItem(STORAGE_KEY, String(splitRatio));
        }});
      }})();
    }})();
  </script>
</body>
</html>
""".format(
        page_title=escape(page_title),
        title=escape(page_title),
        group_name=escape(group_name),
        selector=escape(group_selector or "all"),
        base=escape(base),
        head=escape(head),
        chunk_count=len(chunks),
        file_count=len(chunks_by_file),
        adds=stats["add"],
        deletes=stats["delete"],
        contexts=stats["context"],
        comments_total=comment_stats["total"],
        comments_chunk=comment_stats["chunk"],
        comments_line=comment_stats["line"],
        reviewed_count=review_stats["reviewed"],
        reviewed_total=review_stats["total"],
        reviewed_rate=review_stats["rate"],
        actionable_count=actionable_count,
        inbox_items_html=inbox_items_html,
        comment_entry_count=len(comment_items),
        unresolved_comment_count=unresolved_comment_count,
        comment_items_html=comment_items_html,
        group_brief_card_html=group_brief_card_html,
        doc_json=json.dumps(doc, ensure_ascii=False).replace("</", "<\\/"),
        report_config_json=json.dumps(report_config, ensure_ascii=False).replace("</", "<\\/"),
        state_diff_sections_json=json.dumps(list(STATE_DIFF_SECTIONS), ensure_ascii=False),
        state_selection_sections_json=json.dumps(list(STATE_SELECTION_SECTIONS), ensure_ascii=False),
        impact_toggle_html=impact_toggle_html,
        impact_panel_html=impact_panel_html,
        sidebar_nav_title=escape(sidebar_nav_title),
        sidebar_nav="\n".join(sidebar_nav) if sidebar_nav else "<li>(no items)</li>",
        file_sections="\n".join(file_sections),
    )
