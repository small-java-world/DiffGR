from __future__ import annotations

import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath
from typing import Any

from diffgr.group_brief_utils import merge_group_brief_payload, normalize_brief_items
from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual import events
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Footer, Header, Input, Static, Rule, TextArea
from rich.text import Text
from rich.syntax import Syntax
from .html_report import render_group_diff_html
from .impact_merge import build_impact_preview_report, preview_impact_merge
from .impact_merge import format_impact_preview_text
from .review_state import (
    STATE_DIFF_SECTIONS,
    apply_review_state_selection,
    apply_review_state,
    format_merge_preview_text,
    diff_review_states,
    extract_review_state,
    iter_review_state_diff_rows,
    iter_review_state_selection_tokens,
    load_review_state,
    merge_review_states,
    parse_review_state_selection,
    preview_merge_review_states,
    preview_review_state_selection,
    review_state_fingerprint,
    save_review_state,
    summarize_merge_result,
)
from .diff_utils import line_anchor_key, normalize_line_number
from .viewer_core import load_json, validate_document, write_json
from .review_split import build_group_output_filename, split_document_by_group
from .approval import (
    REASON_APPROVED,
    REASON_CHANGES_REQUESTED,
    REASON_REVOKED,
    approve_group,
    check_group_approval,
    request_changes_on_group,
)
from .generator import iso_utc_now


def normalize_diff_syntax_theme(value: Any, *, fallback: str = "github-dark") -> str:
    name = str(value or "").strip()
    if not name:
        return fallback
    try:
        from pygments.styles import get_style_by_name

        get_style_by_name(name)
        return name
    except Exception:
        return fallback


def normalize_ui_density(value: Any, *, fallback: str = "normal") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"compact", "normal", "comfortable"}:
        return raw
    return fallback


def _preferred_pygments_themes() -> list[str]:
    """Return a short, curated list of themes that look good on dark backgrounds."""
    candidates = [
        "github-dark",
        "one-dark",
        "nord",
        "dracula",
        "monokai",
        "material",
        "gruvbox-dark",
        "solarized-dark",
    ]
    try:
        from pygments.styles import get_all_styles

        available = set(get_all_styles())
        return [name for name in candidates if name in available]
    except Exception:
        # rich bundles pygments, but keep it robust in case of partial installs.
        return candidates[:3]

try:
    from rapidfuzz import fuzz as rapidfuzz_fuzz
except Exception:  # noqa: BLE001
    rapidfuzz_fuzz = None

try:
    from diff_match_patch import diff_match_patch
except Exception:  # noqa: BLE001
    diff_match_patch = None


PSEUDO_ALL = "__all__"
PSEUDO_UNASSIGNED = "__unassigned__"
RESERVED_GROUP_IDS = {"unassigned"}
EDITOR_MODE_AUTO = "auto"
EDITOR_MODE_VSCODE = "vscode"
EDITOR_MODE_CURSOR = "cursor"
EDITOR_MODE_DEFAULT_APP = "default-app"
EDITOR_MODE_CUSTOM = "custom"
VALID_EDITOR_MODES = {
    EDITOR_MODE_AUTO,
    EDITOR_MODE_VSCODE,
    EDITOR_MODE_CURSOR,
    EDITOR_MODE_DEFAULT_APP,
    EDITOR_MODE_CUSTOM,
}


def safe_group_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9\\-]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        slug = "slice"
    return f"g-{slug}"


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9\\-]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "report"


def format_file_label(file_path: str) -> str:
    normalized = str(file_path).replace("\\", "/").strip()
    if not normalized:
        return "-"
    path_obj = PurePosixPath(normalized)
    name = path_obj.name or normalized
    parent = str(path_obj.parent)
    if parent in {"", "."}:
        return name
    parent_parts = [part for part in parent.split("/") if part and part != "."]
    if len(parent_parts) > 2:
        parent_display = f".../{'/'.join(parent_parts[-2:])}"
    else:
        parent_display = "/".join(parent_parts)
    return f"{name} ({parent_display})"


def format_comment_lines(comment: str, *, max_width: int = 96, max_lines: int = 8) -> list[str]:
    clean = str(comment).strip()
    if not clean:
        return []

    lines: list[str] = []
    for raw_line in clean.splitlines():
        if not raw_line.strip():
            if lines and lines[-1] != "":
                lines.append("")
            continue
        wrapped = textwrap.wrap(
            raw_line,
            width=max_width,
            break_long_words=False,
            break_on_hyphens=False,
            drop_whitespace=False,
        )
        lines.extend(wrapped if wrapped else [raw_line])

    if len(lines) > max_lines:
        hidden = len(lines) - max_lines
        lines = lines[:max_lines]
        lines.append(f"... ({hidden} more line(s))")
    return lines



def normalize_editor_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode not in VALID_EDITOR_MODES:
        return EDITOR_MODE_AUTO
    return mode


@dataclass(frozen=True)
class GroupRow:
    group_id: str
    name: str


@dataclass(frozen=True)
class GroupReportRow:
    row_type: str
    old_line: str
    old_text: str
    new_line: str
    new_text: str
    chunk_id: str = ""


def build_group_diff_report_rows(
    chunks: list[dict[str, Any]],
    *,
    max_lines_per_chunk: int = 120,
) -> list[GroupReportRow]:
    rows: list[GroupReportRow] = []
    if not chunks:
        return [
            GroupReportRow(
                row_type="info",
                old_line="",
                old_text="(no chunks in current group/filter)",
                new_line="",
                new_text="",
            )
        ]

    def _build_file_border(label: str) -> str:
        prefix = f"── {label} "
        line_len = 240
        if len(prefix) >= line_len:
            return prefix
        return prefix + ("─" * (line_len - len(prefix)))

    current_file = ""
    plain_border = "─" * 240
    for chunk in chunks:
        file_path = str(chunk.get("filePath", "-"))
        file_label = format_file_label(file_path)
        if file_path != current_file:
            if rows:
                rows.append(
                    GroupReportRow(
                        row_type="file_border",
                        old_line="",
                        old_text=plain_border,
                        new_line="",
                        new_text=plain_border,
                    )
                )
                rows.append(GroupReportRow(row_type="spacer", old_line="", old_text="", new_line="", new_text=""))
            current_file = file_path
            file_border = _build_file_border(file_label)
            rows.append(
                GroupReportRow(
                    row_type="file_border",
                    old_line="",
                    old_text=file_border,
                    new_line="",
                    new_text=file_border,
                )
            )

        chunk_id = str(chunk.get("id", ""))
        old = chunk.get("old", {}) or {}
        new = chunk.get("new", {}) or {}
        header = str(chunk.get("header", ""))
        assigned_groups = [str(name) for name in (chunk.get("_assignedGroups") or []) if str(name)]
        group_hint = f" groups={','.join(assigned_groups)}" if assigned_groups else ""
        rows.append(
            GroupReportRow(
                row_type="chunk",
                old_line="",
                old_text=(
                    f"[{chunk_id[:12]}] {file_label} "
                    f"old {old.get('start', '?')},{old.get('count', '?')} -> "
                    f"new {new.get('start', '?')},{new.get('count', '?')}{group_hint}"
                ),
                new_line="",
                new_text=header if header else "(no header)",
                chunk_id=chunk_id,
            )
        )

        comment_lines = format_comment_lines(str(chunk.get("_comment", "")), max_width=88, max_lines=6)
        for index, comment_line in enumerate(comment_lines):
            prefix = "COMMENT: " if index == 0 else "         "
            rows.append(
                GroupReportRow(
                    row_type="comment",
                    old_line="",
                    old_text="",
                    new_line="",
                    new_text=f"{prefix}{comment_line}",
                    chunk_id=chunk_id,
                )
            )

        line_comment_map: dict[str, list[str]] = {}
        for line_comment in chunk.get("_lineComments", []) or []:
            if not isinstance(line_comment, dict):
                continue
            comment_text = str(line_comment.get("comment", "")).strip()
            if not comment_text:
                continue
            key = line_anchor_key(
                str(line_comment.get("lineType", "")),
                line_comment.get("oldLine"),
                line_comment.get("newLine"),
            )
            line_comment_map.setdefault(key, []).append(comment_text)

        lines = list(chunk.get("lines") or [])
        if not lines:
            rows.append(GroupReportRow(row_type="meta", old_line="", old_text="(no lines)", new_line="", new_text="", chunk_id=chunk_id))
            continue

        for line in lines[:max_lines_per_chunk]:
            kind = str(line.get("kind", ""))
            text = str(line.get("text", ""))

            if kind == "add":
                old_text = ""
                new_text = f"+ {text}"
                row_type = "add"
            elif kind == "delete":
                old_text = f"- {text}"
                new_text = ""
                row_type = "delete"
            elif kind == "context":
                old_text = f"  {text}"
                new_text = f"  {text}"
                row_type = "context"
            else:
                old_text = text
                new_text = text
                row_type = "meta"

            rows.append(
                GroupReportRow(
                    row_type=row_type,
                    old_line="" if line.get("oldLine") is None else str(line.get("oldLine")),
                    old_text=old_text,
                    new_line="" if line.get("newLine") is None else str(line.get("newLine")),
                    new_text=new_text,
                    chunk_id=chunk_id,
                )
            )
            anchor = line_anchor_key(kind, line.get("oldLine"), line.get("newLine"))
            for anchor_comment in line_comment_map.get(anchor, []):
                wrapped = format_comment_lines(anchor_comment, max_width=78, max_lines=4)
                for wrapped_index, wrapped_line in enumerate(wrapped):
                    prefix = "COMMENT: " if wrapped_index == 0 else "         "
                    rows.append(
                        GroupReportRow(
                            row_type="comment",
                            old_line="",
                            old_text="",
                            new_line="",
                            new_text=f"{prefix}{wrapped_line}",
                            chunk_id=chunk_id,
                        )
                    )

        hidden = len(lines) - max_lines_per_chunk
        if hidden > 0:
            rows.append(
                GroupReportRow(
                    row_type="meta",
                    old_line="",
                    old_text=f"... {hidden} more lines",
                    new_line="",
                    new_text="",
                    chunk_id=chunk_id,
                )
            )
    return rows


class NameModal(ModalScreen[str | None]):
    class Submitted(Message):
        def __init__(self, value: str | None) -> None:
            super().__init__()
            self.value = value

    CSS = """
    NameModal {
        align: center middle;
    }
    #dialog {
        width: 70%;
        max-width: 80;
        border: round #8338ec;
        padding: 1 2;
        background: #0b0f19;
    }
    #buttons {
        height: auto;
        layout: horizontal;
        align: right middle;
        padding-top: 1;
    }
    """

    def __init__(
        self,
        title: str,
        placeholder: str,
        initial: str = "",
        *,
        allow_empty: bool = False,
    ) -> None:
        super().__init__()
        self.dialog_title = title
        self.placeholder = placeholder
        self.initial = initial
        self.allow_empty = allow_empty

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"[b]{self.dialog_title}[/b]")
            yield Input(value=self.initial, placeholder=self.placeholder, id="name_input")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("OK", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#name_input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        value = self.query_one("#name_input", Input).value
        if self.allow_empty:
            self.dismiss(value.strip())
            return
        stripped = value.strip()
        self.dismiss(stripped if stripped else None)


class TextReportModal(ModalScreen[None]):
    CSS = """
    TextReportModal {
        align: center middle;
    }
    #text-report-dialog {
        width: 88%;
        height: 80%;
        border: round #3a86ff;
        padding: 1 2;
        background: #0b0f19;
    }
    #text-report-body {
        height: 1fr;
        min-height: 12;
    }
    #text-report-buttons {
        height: auto;
        layout: horizontal;
        align: right middle;
        padding-top: 1;
    }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.dialog_title = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="text-report-dialog"):
            yield Static(f"[b]{self.dialog_title}[/b]")
            area = TextArea(self.body, id="text-report-body")
            area.read_only = True
            yield area
            with Horizontal(id="text-report-buttons"):
                yield Button("Close", id="close", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)


class TextInputModal(ModalScreen[str | None]):
    CSS = """
    TextInputModal {
        align: center middle;
    }
    #text-input-dialog {
        width: 88%;
        height: 72%;
        border: round #ff006e;
        padding: 1 2;
        background: #0b0f19;
    }
    #text-input-body {
        height: 1fr;
        min-height: 10;
    }
    #text-input-buttons {
        height: auto;
        layout: horizontal;
        align: right middle;
        padding-top: 1;
    }
    """

    def __init__(self, title: str, placeholder: str, initial: str = "") -> None:
        super().__init__()
        self.dialog_title = title
        self.placeholder = placeholder
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="text-input-dialog"):
            yield Static(f"[b]{self.dialog_title}[/b]")
            yield Static(self.placeholder)
            yield TextArea(self.initial, id="text-input-body")
            with Horizontal(id="text-input-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Apply", id="apply", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#text-input-body", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self.dismiss(self.query_one("#text-input-body", TextArea).text.strip())


class ConfirmModal(ModalScreen[bool]):
    CSS = """
    ConfirmModal {
        align: center middle;
    }
    #confirm-dialog {
        width: 88%;
        max-width: 100;
        border: round #ffb703;
        padding: 1 2;
        background: #0b0f19;
    }
    #confirm-body {
        padding: 1 0;
    }
    #confirm-buttons {
        height: auto;
        layout: horizontal;
        align: right middle;
        padding-top: 1;
    }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.dialog_title = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(f"[b]{self.dialog_title}[/b]")
            yield Static(self.body, id="confirm-body")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Apply", id="apply", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#apply", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "apply")


class SettingsModal(ModalScreen[dict[str, str] | None]):
    CSS = """
    SettingsModal {
        align: center middle;
    }
    #settings-dialog {
        width: 88%;
        max-width: 110;
        border: round #2ec4b6;
        padding: 1 2;
        background: #0b0f19;
    }
    #settings-buttons {
        height: auto;
        layout: horizontal;
        align: right middle;
        padding-top: 1;
    }
    #settings-hint {
        color: #9db0c8;
        padding-bottom: 1;
    }
    """

    def __init__(
        self,
        editor_mode: str,
        custom_editor_command: str,
        diff_syntax: bool,
        diff_syntax_theme: str,
        ui_density: str,
        diff_auto_wrap: bool,
    ) -> None:
        super().__init__()
        self.editor_mode = normalize_editor_mode(editor_mode)
        self.custom_editor_command = str(custom_editor_command)
        self.diff_syntax = bool(diff_syntax)
        self.diff_syntax_theme = normalize_diff_syntax_theme(diff_syntax_theme)
        self.ui_density = normalize_ui_density(ui_density)
        self.diff_auto_wrap = bool(diff_auto_wrap)

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            yield Static("[b]Viewer Settings[/b]")
            yield Static(
                "editor mode: auto / vscode / cursor / default-app / custom\n"
                "custom command supports placeholders: {path} and optional {line}\n"
                "diff syntax: on/off (rich Syntax / Pygments)\n"
                "diff syntax theme: e.g. github-dark / nord / dracula (Shift+T cycles)\n"
                "ui density: compact / normal / comfortable (terminal font size is controlled by your terminal)\n"
                "diff auto wrap: on/off (wrap long diff lines in chunk detail)",
                id="settings-hint",
            )
            yield Input(value=self.editor_mode, placeholder="editor mode", id="editor_mode")
            yield Input(
                value=self.custom_editor_command,
                placeholder="custom command (used only when mode=custom)",
                id="editor_command",
            )
            yield Input(
                value="on" if self.diff_syntax else "off",
                placeholder="diff syntax (on/off)",
                id="diff_syntax",
            )
            yield Input(
                value=self.diff_syntax_theme,
                placeholder="diff syntax theme (e.g. github-dark / one-dark / nord)",
                id="diff_syntax_theme",
            )
            yield Input(
                value=self.ui_density,
                placeholder="ui density (compact/normal/comfortable)",
                id="ui_density",
            )
            yield Input(
                value="on" if self.diff_auto_wrap else "off",
                placeholder="diff auto wrap (on/off)",
                id="diff_auto_wrap",
            )
            with Horizontal(id="settings-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#editor_mode", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
            self.dismiss(
                {
                    "editor_mode": self.query_one("#editor_mode", Input).value.strip(),
                    "custom_editor_command": self.query_one("#editor_command", Input).value.strip(),
                "diff_syntax": self.query_one("#diff_syntax", Input).value.strip(),
                "diff_syntax_theme": self.query_one("#diff_syntax_theme", Input).value.strip(),
                "ui_density": self.query_one("#ui_density", Input).value.strip(),
                    "diff_auto_wrap": self.query_one("#diff_auto_wrap", Input).value.strip(),
                }
            )


class GroupBriefModal(ModalScreen[dict[str, Any] | None]):
    CSS = """
    GroupBriefModal {
        align: center middle;
    }
    #group-brief-dialog {
        width: 92%;
        max-width: 120;
        height: 85%;
        border: round #4cc9f0;
        padding: 1 2;
        background: #0b0f19;
    }
    .group-brief-label {
        color: #9db0c8;
        padding-top: 1;
    }
    .group-brief-area {
        height: 1fr;
        min-height: 4;
    }
    #group-brief-buttons {
        height: auto;
        layout: horizontal;
        align: right middle;
        padding-top: 1;
    }
    """

    def __init__(self, group_name: str, brief: dict[str, Any]) -> None:
        super().__init__()
        self.group_name = group_name
        self.brief = brief

    def compose(self) -> ComposeResult:
        with Vertical(id="group-brief-dialog"):
            yield Static(f"[b]Review Handoff [{self.group_name}][/b]")
            yield Static("status: draft / ready / acknowledged / stale", classes="group-brief-label")
            yield Input(value=str(self.brief.get("status", "draft")), placeholder="status", id="brief_status")
            yield Static("summary", classes="group-brief-label")
            yield TextArea(str(self.brief.get("summary", "")), id="brief_summary", classes="group-brief-area")
            yield Static("focus points (one per line)", classes="group-brief-label")
            yield TextArea(
                "\n".join(str(item) for item in (self.brief.get("focusPoints") or [])),
                id="brief_focus_points",
                classes="group-brief-area",
            )
            yield Static("test evidence (one per line)", classes="group-brief-label")
            yield TextArea(
                "\n".join(str(item) for item in (self.brief.get("testEvidence") or [])),
                id="brief_test_evidence",
                classes="group-brief-area",
            )
            yield Static("known tradeoffs (one per line)", classes="group-brief-label")
            yield TextArea(
                "\n".join(str(item) for item in (self.brief.get("knownTradeoffs") or [])),
                id="brief_tradeoffs",
                classes="group-brief-area",
            )
            yield Static("questions for reviewer (one per line)", classes="group-brief-label")
            yield TextArea(
                "\n".join(str(item) for item in (self.brief.get("questionsForReviewer") or [])),
                id="brief_questions",
                classes="group-brief-area",
            )
            with Horizontal(id="group-brief-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Delete", id="delete")
                yield Button("Save", id="save", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#brief_status", Input).focus()

    def _normalize_items(self, value: str) -> list[str]:
        items: list[str] = []
        for raw_line in str(value or "").splitlines():
            item = raw_line.strip()
            if item:
                items.append(item)
        return items

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "delete":
            self.dismiss({"delete": True})
            return
        self.dismiss(
            {
                "status": self.query_one("#brief_status", Input).value.strip(),
                "summary": self.query_one("#brief_summary", TextArea).text.strip(),
                "focusPoints": self._normalize_items(self.query_one("#brief_focus_points", TextArea).text),
                "testEvidence": self._normalize_items(self.query_one("#brief_test_evidence", TextArea).text),
                "knownTradeoffs": self._normalize_items(self.query_one("#brief_tradeoffs", TextArea).text),
                "questionsForReviewer": self._normalize_items(self.query_one("#brief_questions", TextArea).text),
            }
        )


class GroupBriefViewerModal(ModalScreen[dict[str, Any] | None]):
    """Read-only PR-body viewer for a group brief.

    Dismisses with:
    - ``None``                          → close
    - ``{"action": "edit"}``            → open handoff editor
    - ``{"action": "approve",   "approved_by": str}``
    - ``{"action": "request_changes", "requested_by": str, "comment": str}``
    """

    CSS = """
    GroupBriefViewerModal {
        align: center middle;
    }
    #group-brief-viewer-dialog {
        width: 92%;
        max-width: 120;
        height: 90%;
        border: round #4cc9f0;
        padding: 1 2;
        background: #0b0f19;
    }
    #brief-viewer-head {
        layout: horizontal;
        height: auto;
    }
    #brief-viewer-heading {
        width: 1fr;
    }
    #brief-viewer-status-badge {
        width: auto;
        padding: 0 1;
    }
    #brief-viewer-body {
        height: 1fr;
        overflow-y: auto;
    }
    .brief-viewer-section-label {
        color: #7a9dc8;
        text-style: bold;
        padding-top: 1;
    }
    #brief-viewer-decision {
        height: auto;
        border-top: solid #2a3a4a;
        padding-top: 1;
        margin-top: 1;
    }
    .decision-label {
        color: #9db0c8;
        padding-top: 1;
    }
    #bv-comment {
        height: 3;
        margin-top: 0;
    }
    #brief-viewer-buttons {
        height: auto;
        layout: horizontal;
        align: right middle;
        padding-top: 1;
    }
    """

    def __init__(
        self,
        group_name: str,
        brief: dict[str, Any],
        approval_icon: Text,
        unreviewed_count: int = 0,
    ) -> None:
        super().__init__()
        self.group_name = group_name
        self.brief = brief
        self.approval_icon = approval_icon
        self.unreviewed_count = unreviewed_count

    def compose(self) -> ComposeResult:
        status = str(self.brief.get("status", "draft"))
        summary = str(self.brief.get("summary", "")).strip()
        focus = [str(x) for x in (self.brief.get("focusPoints") or [])]
        tests = [str(x) for x in (self.brief.get("testEvidence") or [])]
        tradeoffs = [str(x) for x in (self.brief.get("knownTradeoffs") or [])]
        questions = [str(x) for x in (self.brief.get("questionsForReviewer") or [])]

        with Vertical(id="group-brief-viewer-dialog"):
            with Horizontal(id="brief-viewer-head"):
                yield Static(f"[b]Review Handoff \u2014 {self.group_name}[/b]", id="brief-viewer-heading")
                yield Static(f"[{status}]", id="brief-viewer-status-badge")
            with VerticalScroll(id="brief-viewer-body"):
                if summary:
                    yield Static(summary)
                else:
                    yield Static("[dim]No summary yet.[/dim]")
                if focus:
                    yield Static("[b]Focus Points[/b]", classes="brief-viewer-section-label")
                    for item in focus:
                        yield Static(f"• {item}")
                if tests:
                    yield Static("[b]Test Evidence[/b]", classes="brief-viewer-section-label")
                    for item in tests:
                        yield Static(f"• {item}")
                if tradeoffs:
                    yield Static("[b]Known Tradeoffs[/b]", classes="brief-viewer-section-label")
                    for item in tradeoffs:
                        yield Static(f"• {item}")
                if questions:
                    yield Static("[b]Questions for Reviewer[/b]", classes="brief-viewer-section-label")
                    for item in questions:
                        yield Static(f"• {item}")
            with Vertical(id="brief-viewer-decision"):
                yield Static(
                    Text.assemble("Approval: ", self.approval_icon),
                    classes="decision-label",
                )
                if self.unreviewed_count > 0:
                    yield Static(
                        f"[yellow]未レビュー {self.unreviewed_count} 件あり[/yellow]",
                        classes="decision-label",
                    )
                yield Static("差し戻し理由（任意）", classes="decision-label")
                yield TextArea("", id="bv-comment")
            with Horizontal(id="brief-viewer-buttons"):
                yield Button("閉じる", id="close")
                yield Button("引継ぎメモ編集", id="edit")
                yield Button("✗ 差し戻し", id="request-changes", variant="error")
                yield Button("✓ 承認", id="approve", variant="success")

    def on_mount(self) -> None:
        self.query_one("#approve", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
            return
        if event.button.id == "edit":
            self.dismiss({"action": "edit"})
            return
        comment = self.query_one("#bv-comment", TextArea).text.strip()
        if event.button.id == "approve":
            self.dismiss({"action": "approve"})
        elif event.button.id == "request-changes":
            self.dismiss({"action": "request_changes", "comment": comment})



class PaneSplitter(Widget):
    """Draggable vertical bar that resizes the left/right panes."""

    DEFAULT_CSS = """
    PaneSplitter {
        width: 1;
        background: #1a2232;
    }
    PaneSplitter:hover {
        background: #4cc9f0;
    }
    PaneSplitter.-dragging {
        background: #4cc9f0;
    }
    """

    _dragging: bool = False

    def render(self) -> str:
        return ""

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self.add_class("-dragging")
        self.capture_mouse()
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.remove_class("-dragging")
        self.release_mouse()
        app = self.app
        if hasattr(app, "_persist_document_state"):
            app._persist_document_state()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        app = self.app
        screen_width = self.screen.size.width
        if screen_width <= 0 or not hasattr(app, "left_pane_pct"):
            return
        new_pct = app._clamp_left_pane_pct(int((event.screen_x / screen_width) * 100))
        if new_pct != app.left_pane_pct:
            app.left_pane_pct = new_pct
            app._apply_main_split_widths()
            app._rerender_lines_if_width_sensitive()
            app._refresh_topbar()
        event.stop()


class ChunkTable(DataTable):
    def _app_mark_reviewed(self) -> None:
        mark = getattr(self.app, "action_mark_selected_reviewed", None)
        if callable(mark):
            mark()

    def _app_mark_unreviewed(self) -> None:
        mark = getattr(self.app, "action_mark_selected_unreviewed", None)
        if callable(mark):
            mark()

    def on_key(self, event: events.Key) -> None:
        if event.key in {"backspace", "ctrl+h"}:
            self._app_mark_unreviewed()
            event.prevent_default()
            event.stop()
            return
        if event.key == "shift+space":
            self._app_mark_reviewed()
            event.prevent_default()
            event.stop()
            return
        if event.key == "space" or event.character in {" ", "　"}:
            toggle = getattr(self.app, "action_toggle_reviewed_checkbox", None)
            if callable(toggle):
                toggle()
            event.prevent_default()
            event.stop()
            return


class DiffgrTextualApp(App[None]):
    MIN_LEFT_PANE_PCT = 28
    MAX_LEFT_PANE_PCT = 72
    SPLIT_STEP_PCT = 4
    MIN_DIFF_OLD_RATIO = 0.25
    MAX_DIFF_OLD_RATIO = 0.75
    DIFF_RATIO_STEP = 0.05
    AUTOSAVE_INTERVAL_SEC = 20
    AUTO_SPLIT_MANIFEST_NAME = "manifest.json"
    KEYMAP_REV = "km-20260223-4"

    CSS = """
    Screen { layout: vertical; }
    #topbar { height: 3; border: round #3a86ff; padding: 0 1; }
    #main { height: 1fr; }
    #left { width: 52%; border: round #4cc9f0; }
    #right { width: 1fr; border: round #f72585; padding: 0 1; }
    #groups { height: 10; }
    #filter { height: 3; border: round #2ec4b6; margin: 1 1; }
    #chunks { height: 1fr; }
    #meta { height: 14; border: none; padding: 0 1; background: #0b0f19; }
    #right_sep { color: #1a2232; }
    #lines { height: 1fr; }
    #lines .datatable--cursor {
        background: #1e3a5f;
        text-style: bold;
    }
    #lines:focus .datatable--cursor {
        background: #1e3a5f;
        text-style: bold;
    }
    #lines .datatable--fixed-cursor {
        background: #1e3a5f;
        text-style: bold;
    }
    #lines .datatable--header-cursor {
        background: #1e3a5f;
        text-style: bold;
    }
    """

    CONTEXT_LINE_BG = "#0f1724"
    UI_DENSITY_CELL_PADDING = {
        "compact": 0,
        "normal": 1,
        "comfortable": 2,
    }

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("/", "focus_filter", "Filter"),
        Binding("r", "reset_filter", "Reset Filter"),
        Binding("g", "focus_groups", "Groups"),
        Binding("c", "focus_chunks", "Chunks"),
        Binding("l", "focus_lines", "Lines"),
        Binding("n", "new_group", "New Group"),
        Binding("e", "rename_group", "Rename Group"),
        Binding("a", "assign_chunk", "Assign"),
        Binding("u", "unassign_chunk", "Unassign"),
        Binding("p", "view_group_brief", "PR Body"),
        Binding("b", "edit_group_brief", "Brief"),
        Binding("shift+b", "cycle_group_brief_status", "Brief Status"),
        Binding("m", "edit_comment", "Comment"),
        Binding("o", "open_chunk_file", "Open File"),
        Binding("t", "open_settings", "Settings"),
        Binding("d", "toggle_group_report", "Diff Report"),
        Binding("v", "toggle_chunk_detail_view", "Detail View"),
        Binding("z", "toggle_context_lines", "Focus Changes"),
        Binding("w", "toggle_auto_wrap", "Wrap"),
        Binding("1", "set_status('unreviewed')", "Unreviewed"),
        Binding("2", "set_status('reviewed')", "Reviewed"),
        Binding("3", "set_status('needsReReview')", "ReReview"),
        Binding("4", "set_status('ignored')", "Ignored"),
        Binding("shift+up", "extend_chunk_selection_up", "Select Up"),
        Binding("shift+down", "extend_chunk_selection_down", "Select Down"),
        Binding("k", "extend_chunk_selection_up", "Select Up"),
        Binding("j", "extend_chunk_selection_down", "Select Down"),
        Binding("x", "toggle_current_chunk_selection", "Toggle Select"),
        Binding("ctrl+a", "select_all_visible_chunks", "Select All"),
        Binding("escape", "clear_chunk_multi_selection", "Clear Selection"),
        Binding("[", "move_split_left", "Split <-", priority=True),
        Binding("]", "move_split_right", "Split ->", priority=True),
        Binding("alt+left", "move_diff_split_left", "Diff <-", priority=True, show=False),
        Binding("alt+right", "move_diff_split_right", "Diff ->", priority=True, show=False),
        Binding("s", "save", "Save"),
        Binding("h", "export_html", "Export HTML"),
        Binding("shift+h", "export_state", "Export State"),
        Binding("shift+i", "import_state", "Import State"),
        Binding("ctrl+b", "bind_state", "Bind State"),
        Binding("ctrl+u", "unbind_state", "Unbind State"),
        Binding("ctrl+d", "diff_state", "Diff State"),
        Binding("ctrl+shift+d", "impact_preview", "Impact Preview"),
        Binding("ctrl+alt+d", "merge_preview", "Merge Preview"),
        Binding("ctrl+m", "merge_state", "Merge State"),
        Binding("ctrl+shift+m", "apply_state_selection", "Apply State"),
        Binding("ctrl+alt+m", "apply_impact_plan", "Impact Apply"),
        Binding("=", "zoom_in", "Zoom +"),
        Binding("-", "zoom_out", "Zoom -"),
        Binding("shift+t", "cycle_diff_syntax_theme", "Theme"),
    ]

    def __init__(
        self,
        source_path: Path,
        doc: dict[str, Any],
        warnings: list[str],
        chunk_map: dict[str, Any],
        status_map: dict[str, str],
        page_size: int,
        state_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.source_path = source_path
        self.state_path = state_path
        self.doc = doc
        self.warnings = warnings
        self.chunk_map = chunk_map
        self.status_map = status_map
        self.page_size = page_size

        self.filter_text = ""
        self.current_group_id = PSEUDO_ALL
        self.filtered_chunk_ids: list[str] = []
        self.selected_chunk_id: str | None = None
        self.selected_chunk_ids: set[str] = set()
        self._chunk_selection_anchor_index: int | None = None
        self.chunk_detail_view_mode = "compact"
        self.group_report_mode = False
        self.show_context_lines = True
        self._lines_table_mode: str | None = None
        self._lines_side_by_side_widths: tuple[int, int] | None = None
        self.left_pane_pct = 52
        self.diff_old_ratio = 0.50
        self._group_report_row_chunk_by_key: dict[str, str] = {}
        self._chunk_line_anchor_by_row_key: dict[str, dict[str, Any]] = {}
        self._selected_line_anchor: dict[str, Any] | None = None
        self._suppress_chunk_table_events = False
        self._has_unsaved_changes = False
        self._last_saved_at: dt.datetime | None = None
        self._last_save_kind = "-"
        self.editor_mode = EDITOR_MODE_AUTO
        self.custom_editor_command = ""
        self.diff_syntax = True
        self.diff_syntax_theme = "github-dark"
        self.diff_auto_wrap = True
        self._syntax_by_lexer: dict[str, Syntax] = {}
        self._assigned_chunk_ids_cache: set[str] | None = None
        self._chunk_group_ids_cache: dict[str, list[str]] = {}
        self._group_metrics_cache: dict[str, dict[str, int]] = {}
        self._group_report_rows_cache_key: tuple[tuple[str, ...], int] | None = None
        self._group_report_rows_cache: list[GroupReportRow] | None = None
        self._group_report_rows_revision = 0
        self._last_state_diff_tokens: list[str] = []
        self._last_impact_selection_plans: dict[str, list[str]] = {}
        self._last_impact_rebased_state: dict[str, Any] | None = None
        self._last_impact_preview_report: dict[str, Any] | None = None
        self._last_impact_source_label: str = ""
        self._last_impact_state_path: Path | None = None
        self._last_impact_state_fingerprint: str = ""
        self.ui_density = "normal"
        self.settings_path = self._viewer_settings_path()
        self._settings_load_error: str | None = None
        self._dmp_engine = diff_match_patch() if diff_match_patch is not None else None
        if self._dmp_engine is not None:
            self._dmp_engine.Diff_Timeout = 0
        self._load_viewer_settings()
        self._restore_document_state()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="topbar")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield DataTable(id="groups", cursor_type="row")
                yield Input(placeholder="Filter chunks by file/chunk/header/status...", id="filter")
                yield ChunkTable(id="chunks", cursor_type="row")
            yield PaneSplitter(id="main_splitter")
            with Vertical(id="right"):
                yield Static("Select a chunk from the left.", id="meta")
                yield Rule(id="right_sep")
                yield DataTable(
                    id="lines",
                    cursor_type="row",
                    # Keep syntax colors while still allowing CSS to remove cursor background fill.
                    cursor_foreground_priority="renderable",
                    cursor_background_priority="css",
                )
        yield Footer()

    def on_mount(self) -> None:
        group_table = self.query_one("#groups", DataTable)
        group_table.add_columns("name", "brief", "total", "pending", "reviewed", "ignored")
        chunk_table = self.query_one("#chunks", DataTable)
        chunk_table.add_columns("sel", "done", "status", "note", "chunk", "file", "old", "new", "header")
        self.query_one("#filter", Input).value = self.filter_text
        self._switch_lines_table_mode("chunk")
        self._apply_main_split_widths()
        self._apply_ui_density()

        self._refresh_groups(select_group_id=self.current_group_id)
        self._apply_chunk_filter(keep_selection=bool(self.selected_chunk_id))
        self.query_one("#groups", DataTable).focus()
        if self._settings_load_error:
            self.notify(f"Settings load failed: {self._settings_load_error}", severity="warning", timeout=2.4)
        self.set_interval(self.AUTOSAVE_INTERVAL_SEC, self._auto_save_tick)

    def _viewer_settings_path(self) -> Path:
        configured = str(os.environ.get("DIFFGR_VIEWER_SETTINGS", "")).strip()
        if configured:
            return Path(configured).expanduser()
        return Path.home() / ".diffgr" / "viewer_settings.json"

    def _analysis_state(self) -> dict[str, Any]:
        current = self.doc.get("analysisState")
        if not isinstance(current, dict):
            current = {}
            self.doc["analysisState"] = current
        return current

    def _thread_state(self) -> dict[str, Any]:
        current = self.doc.get("threadState")
        if not isinstance(current, dict):
            current = {}
            self.doc["threadState"] = current
        return current

    def _restore_document_state(self) -> None:
        analysis_state = self._analysis_state()
        thread_state = self._thread_state()

        group_id = str(analysis_state.get("currentGroupId", "")).strip()
        if group_id:
            self.current_group_id = group_id
        self.filter_text = str(analysis_state.get("filterText", "")).strip().lower()
        selected_chunk_id = str(analysis_state.get("selectedChunkId", "")).strip()
        self.selected_chunk_id = selected_chunk_id or None
        self.selected_chunk_ids = {selected_chunk_id} if selected_chunk_id else set()
        self.group_report_mode = bool(analysis_state.get("groupReportMode", self.group_report_mode))
        detail_view = str(analysis_state.get("chunkDetailViewMode", self.chunk_detail_view_mode)).strip()
        if detail_view in {"compact", "side_by_side"}:
            self.chunk_detail_view_mode = detail_view
        self.show_context_lines = bool(analysis_state.get("showContextLines", self.show_context_lines))

        left_pane_pct = analysis_state.get("leftPanePct")
        if isinstance(left_pane_pct, (int, float)):
            self.left_pane_pct = self._clamp_left_pane_pct(int(left_pane_pct))
        diff_old_ratio = analysis_state.get("diffOldRatio")
        if isinstance(diff_old_ratio, (int, float)):
            self.diff_old_ratio = self._clamp_diff_old_ratio(float(diff_old_ratio))

        anchor = thread_state.get("selectedLineAnchor")
        if isinstance(anchor, dict):
            anchor_key = str(anchor.get("anchorKey", "")).strip()
            line_type = str(anchor.get("lineType", "")).strip()
            if anchor_key and line_type:
                self._selected_line_anchor = {
                    "anchorKey": anchor_key,
                    "oldLine": normalize_line_number(anchor.get("oldLine")),
                    "newLine": normalize_line_number(anchor.get("newLine")),
                    "lineType": line_type,
                }

    def _persist_document_state(self) -> None:
        analysis_state = self._analysis_state()
        analysis_state["currentGroupId"] = str(self.current_group_id or "")
        analysis_state["filterText"] = str(self.filter_text or "")
        analysis_state["selectedChunkId"] = str(self.selected_chunk_id or "")
        analysis_state["groupReportMode"] = bool(self.group_report_mode)
        analysis_state["chunkDetailViewMode"] = str(self.chunk_detail_view_mode)
        analysis_state["showContextLines"] = bool(self.show_context_lines)
        analysis_state["leftPanePct"] = int(self.left_pane_pct)
        analysis_state["diffOldRatio"] = float(self.diff_old_ratio)

        thread_state = self._thread_state()
        if self._selected_line_anchor:
            thread_state["selectedLineAnchor"] = {
                "anchorKey": str(self._selected_line_anchor.get("anchorKey", "")),
                "oldLine": normalize_line_number(self._selected_line_anchor.get("oldLine")),
                "newLine": normalize_line_number(self._selected_line_anchor.get("newLine")),
                "lineType": str(self._selected_line_anchor.get("lineType", "")),
            }
        else:
            thread_state.pop("selectedLineAnchor", None)

    def _load_viewer_settings(self) -> None:
        self.editor_mode = EDITOR_MODE_AUTO
        self.custom_editor_command = ""
        self.diff_syntax = True
        self.diff_syntax_theme = "github-dark"
        self.diff_auto_wrap = True
        self.ui_density = "normal"
        path = self.settings_path
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            self.editor_mode = normalize_editor_mode(payload.get("editorMode"))
            self.custom_editor_command = str(payload.get("customEditorCommand", "")).strip()
            if "diffSyntax" in payload:
                self.diff_syntax = bool(payload.get("diffSyntax"))
            if isinstance(payload.get("diffSyntaxTheme"), str) and str(payload.get("diffSyntaxTheme")).strip():
                self.diff_syntax_theme = normalize_diff_syntax_theme(payload.get("diffSyntaxTheme"))
            if "diffAutoWrap" in payload:
                self.diff_auto_wrap = bool(payload.get("diffAutoWrap"))
            if "uiDensity" in payload:
                self.ui_density = normalize_ui_density(payload.get("uiDensity"))
        except Exception as error:  # noqa: BLE001
            self._settings_load_error = str(error)

    def _save_viewer_settings(self) -> bool:
        try:
            payload = {
                "editorMode": normalize_editor_mode(self.editor_mode),
                "customEditorCommand": str(self.custom_editor_command).strip(),
                "diffSyntax": bool(self.diff_syntax),
                "diffSyntaxTheme": normalize_diff_syntax_theme(self.diff_syntax_theme),
                "diffAutoWrap": bool(self.diff_auto_wrap),
                "uiDensity": normalize_ui_density(self.ui_density),
            }
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(self.settings_path, payload)
            return True
        except Exception as error:  # noqa: BLE001
            self.notify(f"Settings save failed: {error}", severity="error", timeout=2.4)
            return False

    def _editor_setting_label(self) -> str:
        if self.editor_mode == EDITOR_MODE_CUSTOM:
            return "custom" if self.custom_editor_command else "custom(!)"
        return self.editor_mode

    def action_open_settings(self) -> None:
        def _on_dismiss(value: dict[str, str] | None) -> None:
            if not isinstance(value, dict):
                return
            next_mode = normalize_editor_mode(value.get("editor_mode"))
            next_custom = str(value.get("custom_editor_command", "")).strip()
            next_diff_syntax_raw = str(value.get("diff_syntax", "")).strip().lower()
            next_diff_syntax = self.diff_syntax
            if next_diff_syntax_raw in {"on", "true", "1", "yes", "y"}:
                next_diff_syntax = True
            elif next_diff_syntax_raw in {"off", "false", "0", "no", "n"}:
                next_diff_syntax = False
            next_theme = normalize_diff_syntax_theme(value.get("diff_syntax_theme"), fallback=self.diff_syntax_theme)
            next_density = normalize_ui_density(value.get("ui_density"), fallback=self.ui_density)
            next_auto_wrap_raw = str(value.get("diff_auto_wrap", "")).strip().lower()
            next_auto_wrap = self.diff_auto_wrap
            if next_auto_wrap_raw in {"on", "true", "1", "yes", "y"}:
                next_auto_wrap = True
            elif next_auto_wrap_raw in {"off", "false", "0", "no", "n"}:
                next_auto_wrap = False
            if next_mode == EDITOR_MODE_CUSTOM and not next_custom:
                self.notify("custom mode requires command template", severity="warning", timeout=2.0)
                return
            changed = (
                next_mode != self.editor_mode
                or next_custom != self.custom_editor_command
                or next_diff_syntax != self.diff_syntax
                or next_theme != self.diff_syntax_theme
                or next_auto_wrap != self.diff_auto_wrap
                or next_density != self.ui_density
            )
            self.editor_mode = next_mode
            self.custom_editor_command = next_custom
            self.diff_syntax = next_diff_syntax
            self.diff_syntax_theme = next_theme
            self.diff_auto_wrap = next_auto_wrap
            self.ui_density = next_density
            self._syntax_by_lexer = {}
            self._apply_ui_density()
            self._rerender_lines_if_width_sensitive()
            if changed and self._save_viewer_settings():
                self.notify(f"Settings saved: editor={self._editor_setting_label()}", timeout=1.5)
            self._refresh_topbar()

        self.push_screen(
            SettingsModal(
                self.editor_mode,
                self.custom_editor_command,
                self.diff_syntax,
                self.diff_syntax_theme,
                self.ui_density,
                self.diff_auto_wrap,
            ),
            callback=_on_dismiss,
        )

    def action_toggle_auto_wrap(self) -> None:
        self.diff_auto_wrap = not bool(self.diff_auto_wrap)
        self._rerender_lines_if_width_sensitive()
        self._save_viewer_settings()
        self.notify(f"Auto wrap: {'ON' if self.diff_auto_wrap else 'OFF'}", timeout=1.0)
        self._refresh_topbar()

    def action_cycle_diff_syntax_theme(self) -> None:
        themes = _preferred_pygments_themes()
        if not themes:
            self.notify("No syntax themes available", severity="warning", timeout=1.4)
            return
        current = normalize_diff_syntax_theme(self.diff_syntax_theme, fallback=themes[0])
        try:
            index = themes.index(current)
        except ValueError:
            index = -1
        self.diff_syntax_theme = themes[(index + 1) % len(themes)]
        self._syntax_by_lexer = {}
        self._save_viewer_settings()
        self.notify(f"Syntax theme: {self.diff_syntax_theme}", timeout=1.1)
        if self.selected_chunk_id and not self.group_report_mode:
            self._show_chunk(self.selected_chunk_id)
        self._refresh_topbar()

    def _apply_ui_density(self) -> None:
        """Apply UI density tweaks (padding) to mimic a 'zoom' effect in a terminal UI.

        Note: terminal font size itself is controlled by the terminal emulator.
        """
        padding = int(self.UI_DENSITY_CELL_PADDING.get(self.ui_density, 1))
        for selector in ("#groups", "#chunks", "#lines"):
            try:
                table = self.query_one(selector, DataTable)
                table.cell_padding = padding
            except Exception:
                pass

    def action_zoom_in(self) -> None:
        order = ["compact", "normal", "comfortable"]
        current = normalize_ui_density(self.ui_density)
        idx = order.index(current) if current in order else 1
        self.ui_density = order[min(len(order) - 1, idx + 1)]
        self._apply_ui_density()
        self._rerender_lines_if_width_sensitive()
        self._save_viewer_settings()
        self.notify(f"UI density: {self.ui_density}", timeout=1.0)
        self._refresh_topbar()

    def action_zoom_out(self) -> None:
        order = ["compact", "normal", "comfortable"]
        current = normalize_ui_density(self.ui_density)
        idx = order.index(current) if current in order else 1
        self.ui_density = order[max(0, idx - 1)]
        self._apply_ui_density()
        self._rerender_lines_if_width_sensitive()
        self._save_viewer_settings()
        self.notify(f"UI density: {self.ui_density}", timeout=1.0)
        self._refresh_topbar()

    def _syntax_lexer_for_file(self, file_path: str, code_hint: str | None = None) -> str | None:
        raw = str(file_path or "").strip()
        if not raw:
            return None
        try:
            lexer = Syntax.guess_lexer(raw, code_hint)
            return str(lexer).strip() if lexer else None
        except Exception:
            return None

    def _syntax_highlight_line(self, text: str, *, lexer: str) -> Text:
        cached = self._syntax_by_lexer.get(lexer)
        if cached is None:
            cached = Syntax(
                "",
                lexer,
                theme=self.diff_syntax_theme,
                line_numbers=False,
                word_wrap=False,
                # Use terminal default background so DataTable cursor/selection doesn't create
                # hard-to-read color blocks behind tokens.
                background_color="default",
            )
            self._syntax_by_lexer[lexer] = cached
        return cached.highlight(text)

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_reset_filter(self) -> None:
        self.query_one("#filter", Input).value = ""
        self.filter_text = ""
        self._apply_chunk_filter()

    def action_focus_groups(self) -> None:
        self.query_one("#groups", DataTable).focus()

    def action_focus_chunks(self) -> None:
        self.query_one("#chunks", DataTable).focus()

    def action_focus_lines(self) -> None:
        self.query_one("#lines", DataTable).focus()

    def action_toggle_group_report(self) -> None:
        self.group_report_mode = not self.group_report_mode
        self._selected_line_anchor = None
        self._chunk_line_anchor_by_row_key = {}
        self._persist_document_state()
        if self.group_report_mode:
            self._show_current_group_report(target_chunk_id=self.selected_chunk_id)
            self.notify("Group diff report: ON", timeout=1.2)
        else:
            if self.selected_chunk_id:
                self._show_chunk(self.selected_chunk_id)
            self.notify("Group diff report: OFF", timeout=1.2)
        self._refresh_topbar()

    def action_toggle_chunk_detail_view(self) -> None:
        if self.group_report_mode:
            return
        self.chunk_detail_view_mode = "side_by_side" if self.chunk_detail_view_mode == "compact" else "compact"
        self._persist_document_state()
        if self.selected_chunk_id:
            self._show_chunk(self.selected_chunk_id)
        self.notify(
            f"Detail view: {'old/new side-by-side' if self.chunk_detail_view_mode == 'side_by_side' else 'compact'}",
            timeout=1.0,
        )
        self._refresh_topbar()

    def action_toggle_context_lines(self) -> None:
        """Toggle showing unchanged (context) lines in chunk detail view."""
        if self.group_report_mode:
            return
        self.show_context_lines = not bool(self.show_context_lines)
        self._persist_document_state()
        if self.selected_chunk_id:
            self._show_chunk(self.selected_chunk_id)
        self.notify(f"Context lines: {'ON' if self.show_context_lines else 'OFF'}", timeout=1.0)
        self._refresh_topbar()

    def _resolve_chunk_file_path(self, raw_path: str) -> Path | None:
        normalized = str(raw_path).strip()
        if not normalized or normalized == "-":
            return None
        candidate = Path(normalized)
        if candidate.is_absolute():
            return candidate

        search_roots: list[Path] = [Path.cwd()]
        source_parent = self.source_path.parent
        search_roots.append(source_parent)
        if source_parent.parent != source_parent:
            search_roots.append(source_parent.parent)

        seen: set[str] = set()
        resolved_candidates: list[Path] = []
        for root in search_roots:
            resolved = (root / candidate).resolve()
            key = str(resolved).lower()
            if key in seen:
                continue
            seen.add(key)
            resolved_candidates.append(resolved)
            if resolved.exists():
                return resolved
        return resolved_candidates[0] if resolved_candidates else candidate.resolve()

    def _resolve_state_path(self, raw_path: str) -> Path | None:
        normalized = str(raw_path).strip()
        if not normalized:
            return None
        candidate = Path(normalized).expanduser()
        if candidate.is_absolute():
            return candidate

        search_roots: list[Path] = [Path.cwd(), self.source_path.parent]
        if self.source_path.parent.parent != self.source_path.parent:
            search_roots.append(self.source_path.parent.parent)

        seen: set[str] = set()
        resolved_candidates: list[Path] = []
        for root in search_roots:
            resolved = (root / candidate).resolve()
            key = str(resolved).lower()
            if key in seen:
                continue
            seen.add(key)
            resolved_candidates.append(resolved)
            if resolved.exists():
                return resolved
        return resolved_candidates[0] if resolved_candidates else candidate.resolve()

    def _rebuild_status_map_from_doc(self) -> None:
        reviews = self.doc.get("reviews", {})
        if not isinstance(reviews, dict):
            reviews = {}
        for chunk_id in list(self.chunk_map.keys()):
            record = reviews.get(chunk_id, {})
            if not isinstance(record, dict):
                record = {}
            status = str(record.get("status", "unreviewed"))
            if status not in {"unreviewed", "reviewed", "ignored", "needsReReview"}:
                status = "unreviewed"
            self.status_map[chunk_id] = status

    def _apply_imported_state(self, state: dict[str, Any]) -> None:
        self.doc = apply_review_state(self.doc, state)
        self._rebuild_status_map_from_doc()
        self._invalidate_group_metrics()
        self._invalidate_group_report_rows_cache()
        self._selected_line_anchor = None
        self.selected_chunk_id = None
        self.selected_chunk_ids = set()
        self._chunk_selection_anchor_index = None
        self._restore_document_state()
        try:
            filter_input = self.query_one("#filter", Input)
            filter_input.value = self.filter_text
        except Exception:
            pass
        self._refresh_groups(select_group_id=self.current_group_id)
        self._apply_chunk_filter(keep_selection=bool(self.selected_chunk_id))

    def _import_state_from_path(self, path: Path) -> bool:
        state = load_review_state(path)
        self._apply_imported_state(state)
        self._clear_cached_selection_sources()
        self._mark_dirty()
        return True

    def _format_state_diff_report(self, diff: dict[str, Any], target_label: str) -> str:
        lines = [f"State Diff vs {target_label}"]
        rows = iter_review_state_diff_rows(diff)
        for key in STATE_DIFF_SECTIONS:
            section = diff.get(key, {}) if isinstance(diff.get(key), dict) else {}
            lines.append(
                f"{key}: added={section.get('addedCount', 0)} removed={section.get('removedCount', 0)} "
                f"changed={section.get('changedCount', 0)} unchanged={section.get('unchangedCount', 0)}"
            )
            for row in rows:
                if str(row.get("section", "")) != key:
                    continue
                token = str(row.get("selectionToken", "")).strip()
                suffix = f" [select: {token}]" if token else ""
                lines.append(f"  - {row.get('key', '')}: {row.get('preview', '')}{suffix}")
        return "\n".join(lines)

    def _format_impact_preview_report(
        self,
        preview: dict[str, Any],
        *,
        old_label: str,
        new_label: str,
        state_label: str,
        ) -> str:
        return format_impact_preview_text(
            preview,
            old_label=old_label,
            new_label=new_label,
            state_label=state_label,
        )

    def _format_merge_preview_report(self, preview: dict[str, Any], *, state_label: str) -> str:
        return format_merge_preview_text(preview, target_label=state_label)

    def _clear_cached_selection_sources(self) -> None:
        self._last_state_diff_tokens = []
        self._last_impact_selection_plans = {}
        self._last_impact_rebased_state = None
        self._last_impact_preview_report = None
        self._last_impact_source_label = ""
        self._last_impact_state_path = None
        self._last_impact_state_fingerprint = ""

    def _expand_selection_tokens(self, tokens: list[str]) -> tuple[list[str], str | None]:
        expanded: list[str] = []
        used_plan: str | None = None
        saw_explicit_token = False
        for raw in tokens:
            token = str(raw).strip()
            if not token:
                continue
            if token.startswith("@"):
                if saw_explicit_token:
                    raise RuntimeError("impact selection plans cannot be mixed with explicit selection tokens")
                plan_name = token[1:].strip()
                if plan_name not in {"handoffs", "reviews", "ui", "all"}:
                    raise RuntimeError(f"unknown impact selection plan: {plan_name}")
                if used_plan is not None and used_plan != plan_name:
                    raise RuntimeError("only one impact selection plan can be used at a time")
                plan_tokens = self._last_impact_selection_plans.get(plan_name, [])
                if not plan_tokens:
                    raise RuntimeError(f"impact selection plan is not available: {plan_name}")
                if self.state_path is not None and self._last_impact_state_path is not None:
                    if self.state_path.resolve() != self._last_impact_state_path.resolve():
                        raise RuntimeError("impact selection plan is stale for the current bound state; run impact preview again")
                used_plan = plan_name
                for plan_token in plan_tokens:
                    if plan_token not in expanded:
                        expanded.append(plan_token)
                continue
            if used_plan is not None:
                raise RuntimeError("impact selection plans cannot be mixed with explicit selection tokens")
            saw_explicit_token = True
            if token not in expanded:
                expanded.append(token)
        return expanded, used_plan

    def _preferred_open_line(self, chunk_id: str) -> int | None:
        if self._selected_line_anchor:
            new_line = normalize_line_number(self._selected_line_anchor.get("newLine"))
            old_line = normalize_line_number(self._selected_line_anchor.get("oldLine"))
            if new_line and new_line > 0:
                return new_line
            if old_line and old_line > 0:
                return old_line
        chunk = self.chunk_map.get(chunk_id) or {}
        new_start = normalize_line_number((chunk.get("new") or {}).get("start"))
        old_start = normalize_line_number((chunk.get("old") or {}).get("start"))
        if new_start and new_start > 0:
            return new_start
        if old_start and old_start > 0:
            return old_start
        return None

    def _open_default_app(self, path: Path) -> bool:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603
            return True
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603
        return True

    def _open_with_custom_editor(self, path: Path, *, line: int | None = None) -> bool:
        template = self.custom_editor_command.strip()
        if not template:
            return False
        tokens = shlex.split(template, posix=(os.name != "nt"))
        if not tokens:
            return False
        line_token = "" if line is None or line <= 0 else str(line)
        includes_path = False
        args: list[str] = []
        for token in tokens:
            if "{path}" in token:
                includes_path = True
            args.append(token.replace("{path}", str(path)).replace("{line}", line_token))
        if not includes_path:
            args.append(str(path))
        subprocess.Popen(args)  # noqa: S603
        return True

    def _open_with_editor_command(self, executable: str, path: Path, *, line: int | None = None) -> bool:
        editor_cmd = shutil.which(executable)
        if not editor_cmd:
            return False
        if line is not None and line > 0:
            subprocess.Popen([editor_cmd, "-g", f"{path}:{line}"])  # noqa: S603
        else:
            subprocess.Popen([editor_cmd, str(path)])  # noqa: S603
        return True

    def _open_file_path(self, path: Path, *, line: int | None = None) -> bool:
        mode = normalize_editor_mode(self.editor_mode)
        if mode == EDITOR_MODE_CUSTOM:
            return self._open_with_custom_editor(path, line=line)
        if mode == EDITOR_MODE_VSCODE:
            return self._open_with_editor_command("code", path, line=line)
        if mode == EDITOR_MODE_CURSOR:
            return self._open_with_editor_command("cursor", path, line=line)
        if mode == EDITOR_MODE_DEFAULT_APP:
            return self._open_default_app(path)

        if self._open_with_editor_command("code", path, line=line):
            return True
        if self._open_with_editor_command("cursor", path, line=line):
            return True
        return self._open_default_app(path)

    def action_open_chunk_file(self) -> None:
        if not self.selected_chunk_id:
            self.notify("No chunk selected.", timeout=1.2)
            return
        chunk_id = self.selected_chunk_id
        chunk = self.chunk_map.get(chunk_id)
        if not isinstance(chunk, dict):
            self.notify("Selected chunk is not available.", severity="error", timeout=1.8)
            return
        raw_path = str(chunk.get("filePath", "")).strip()
        path = self._resolve_chunk_file_path(raw_path)
        if path is None:
            self.notify("No file path in selected chunk.", severity="warning", timeout=1.8)
            return
        line = self._preferred_open_line(chunk_id)
        try:
            opened = self._open_file_path(path, line=line)
        except Exception as error:  # noqa: BLE001
            self.notify(f"Open failed: {error}", severity="error", timeout=2.2)
            return
        if not opened:
            self.notify(f"Open failed: {path}", severity="error", timeout=2.2)
            return
        suffix = f":{line}" if line else ""
        self.notify(f"Opened: {path}{suffix}", timeout=1.2)

    def _focused_is_text_input(self) -> bool:
        try:
            return isinstance(self.focused, (Input, TextArea))
        except ScreenStackError:
            return False

    def action_move_split_left(self) -> None:
        if self._focused_is_text_input():
            return
        self._nudge_main_split(-self.SPLIT_STEP_PCT)

    def action_move_split_right(self) -> None:
        if self._focused_is_text_input():
            return
        self._nudge_main_split(self.SPLIT_STEP_PCT)

    def action_move_diff_split_left(self) -> None:
        self._nudge_diff_split(-self.DIFF_RATIO_STEP)

    def action_move_diff_split_right(self) -> None:
        self._nudge_diff_split(self.DIFF_RATIO_STEP)

    def _clamp_left_pane_pct(self, value: int) -> int:
        return max(self.MIN_LEFT_PANE_PCT, min(self.MAX_LEFT_PANE_PCT, value))

    def _apply_main_split_widths(self) -> None:
        self.left_pane_pct = self._clamp_left_pane_pct(self.left_pane_pct)
        self.query_one("#left", Vertical).styles.width = f"{self.left_pane_pct}%"

    def _nudge_main_split(self, delta_pct: int) -> None:
        next_pct = self._clamp_left_pane_pct(self.left_pane_pct + delta_pct)
        if next_pct == self.left_pane_pct:
            return
        self.left_pane_pct = next_pct
        self._apply_main_split_widths()
        self._persist_document_state()
        self._rerender_lines_if_width_sensitive()
        self._refresh_topbar()

    def _clamp_diff_old_ratio(self, value: float) -> float:
        return max(self.MIN_DIFF_OLD_RATIO, min(self.MAX_DIFF_OLD_RATIO, value))

    def _nudge_diff_split(self, delta: float) -> None:
        next_ratio = self._clamp_diff_old_ratio(self.diff_old_ratio + delta)
        if abs(next_ratio - self.diff_old_ratio) < 1e-9:
            return
        self.diff_old_ratio = next_ratio
        self._persist_document_state()
        self._rerender_lines_if_width_sensitive()
        self._refresh_topbar()

    def _group_report_text_widths(self, total_width: int | None = None) -> tuple[int, int]:
        # Derive widths from the actual widget size to avoid header/body separator drift.
        # `total_width` is kept for fallback/testing.
        right_width = None
        try:
            right_width = int(self.query_one("#lines", DataTable).size.width)
        except Exception:
            right_width = None
        if right_width is None or right_width <= 0:
            if total_width is None:
                total_width = int(self.size.width)
            total_width = max(80, total_width)
            right_pane_pct = max(1, 100 - self.left_pane_pct)
            right_width = max(36, int(total_width * (right_pane_pct / 100.0)))

        # 4 columns: old#(5), old(text), new#(5), new(text). Account for separators/padding.
        reserved = 5 + 5 + 6  # numbers + spacing/separators
        available = max(28, int(right_width) - reserved)
        old_width = int(round(available * self.diff_old_ratio))
        old_width = max(12, min(available - 12, old_width))
        new_width = max(12, available - old_width)
        return old_width, new_width

    def _switch_lines_table_mode(self, mode: str) -> DataTable:
        lines_table = self.query_one("#lines", DataTable)
        expected_column_count = 4
        has_expected_columns = len(lines_table.ordered_columns) == expected_column_count
        if mode == "chunk":
            mode = "chunk_compact"
        needs_width_columns = mode in {"group_report", "chunk_side_by_side"}
        desired_widths: tuple[int, int] | None = None
        if needs_width_columns:
            desired_widths = self._group_report_text_widths()
        width_changed = bool(needs_width_columns and desired_widths and desired_widths != self._lines_side_by_side_widths)

        if self._lines_table_mode != mode or not has_expected_columns or width_changed:
            lines_table.clear(columns=True)
            if mode == "group_report":
                old_width, new_width = desired_widths if desired_widths is not None else self._group_report_text_widths()
                lines_table.add_column("old#", width=5)
                lines_table.add_column("old", width=old_width)
                lines_table.add_column("new#", width=5)
                lines_table.add_column("new", width=new_width)
                self._lines_side_by_side_widths = (old_width, new_width)
            elif mode == "chunk_side_by_side":
                old_width, new_width = desired_widths if desired_widths is not None else self._group_report_text_widths()
                lines_table.add_column("old#", width=5)
                lines_table.add_column("old", width=old_width)
                lines_table.add_column("new#", width=5)
                lines_table.add_column("new", width=new_width)
                self._lines_side_by_side_widths = (old_width, new_width)
            else:
                lines_table.add_columns("old", "new", "kind", "content")
                self._lines_side_by_side_widths = None
            self._lines_table_mode = mode
        else:
            lines_table.clear(columns=False)
        return lines_table

    def _rerender_lines_if_width_sensitive(self) -> None:
        try:
            if self.group_report_mode:
                self._show_current_group_report(target_chunk_id=self.selected_chunk_id)
                return
            if self.selected_chunk_id and (self.chunk_detail_view_mode == "side_by_side" or self.diff_auto_wrap):
                self._show_chunk(self.selected_chunk_id)
        except Exception:
            # Ignore transient layout-time errors; normal rendering path will repaint.
            return

    def on_resize(self, _event: events.Resize) -> None:
        # Keep side-by-side/group-report column widths aligned with current terminal size.
        self._rerender_lines_if_width_sensitive()

    def _render_report_number(self, value: str, row_type: str, side: str, selected: bool = False) -> Text:
        if selected:
            # Selection should not add any background fill; keep it readable on add/delete rows.
            return Text(value, style="bold underline #ffe5a6")
        style = "dim #91a2bb"
        if row_type == "add" and side == "new":
            style = "bold #52d38a"
        elif row_type == "delete" and side == "old":
            style = "bold #ff6b7d"
        elif row_type == "comment":
            style = "bold #c8b75b"
        return Text(value, style=style)

    def _render_report_text(self, value: str, row_type: str, side: str, selected: bool = False) -> Text:
        if selected:
            # Selection should not add any background fill; keep it readable on add/delete rows.
            return Text(value, style="bold underline #ffe5a6")
        if row_type == "file_border":
            rendered = Text(value, style="bold #8fb4ff on #11213a")
        elif row_type == "file":
            rendered = Text(value, style="bold #09111d on #8fb4ff")
        elif row_type == "chunk":
            if side == "new":
                rendered = Text(value, style="bold #cddfff on #1a2f54")
            else:
                rendered = Text(value, style="bold #bcd7ff on #1a2f54")
        elif row_type == "add":
            if side == "new":
                # Softer than neon green; easier to read with selection underline.
                rendered = Text(value, style="bold #eafff0 on #103a26")
            else:
                rendered = Text(value, style="dim #5b7d6c")
        elif row_type == "delete":
            if side == "old":
                rendered = Text(value, style="bold #ffe7ea on #3a131b")
            else:
                rendered = Text(value, style="dim #8a6a6f")
        elif row_type == "context":
            rendered = Text(value, style=f"#d3deee on {self.CONTEXT_LINE_BG}")
        elif row_type == "comment":
            if side == "new":
                rendered = Text(value, style="bold #fff3cc on #3a2b08")
            else:
                rendered = Text(value, style="dim #7a7360")
        elif row_type == "meta":
            rendered = Text(value, style="italic #9db0c8")
        elif row_type == "spacer":
            rendered = Text("", style="#0b0f16")
        elif row_type == "info":
            rendered = Text(value, style="italic #9db0c8")
        else:
            rendered = Text(value, style="#c7d4e8")
        return rendered

    def _line_similarity_score(self, left: str, right: str) -> float:
        if not left and not right:
            return 1.0
        if rapidfuzz_fuzz is not None:
            return float(rapidfuzz_fuzz.ratio(left, right)) / 100.0
        return SequenceMatcher(a=left, b=right, autojunk=False).ratio()

    def _build_intraline_pair_map(self, lines: list[dict[str, Any]]) -> dict[int, str]:
        pair_map: dict[int, str] = {}
        index = 0
        while index < len(lines):
            kind = str(lines[index].get("kind", ""))
            if kind not in {"add", "delete"}:
                index += 1
                continue

            block_start = index
            while index < len(lines) and str(lines[index].get("kind", "")) in {"add", "delete"}:
                index += 1
            block = lines[block_start:index]
            deletes: list[tuple[int, str]] = []
            adds: list[tuple[int, str]] = []
            for offset, line in enumerate(block):
                absolute_index = block_start + offset
                text = str(line.get("text", ""))
                line_kind = str(line.get("kind", ""))
                if line_kind == "delete":
                    deletes.append((absolute_index, text))
                elif line_kind == "add":
                    adds.append((absolute_index, text))
            if not deletes or not adds:
                continue

            candidates: list[tuple[float, int, int]] = []
            for delete_row_index, delete_text in deletes:
                for add_row_index, add_text in adds:
                    score = self._line_similarity_score(delete_text, add_text)
                    candidates.append((score, delete_row_index, add_row_index))
            candidates.sort(key=lambda item: item[0], reverse=True)

            used_delete_rows: set[int] = set()
            used_add_rows: set[int] = set()
            for score, delete_row_index, add_row_index in candidates:
                if delete_row_index in used_delete_rows or add_row_index in used_add_rows:
                    continue
                # Keep unrelated add/delete lines unpaired to reduce noisy intraline highlight.
                if score < 0.20:
                    continue
                delete_text = next(text for row, text in deletes if row == delete_row_index)
                add_text = next(text for row, text in adds if row == add_row_index)
                pair_map[delete_row_index] = add_text
                pair_map[add_row_index] = delete_text
                used_delete_rows.add(delete_row_index)
                used_add_rows.add(add_row_index)
        return pair_map

    def _render_chunk_kind_badge(self, kind: str) -> Text:
        label = {
            "context": "CTX",
            "add": "ADD",
            "delete": "DEL",
            "meta": "META",
            "comment": "NOTE",
            "line-comment": "NOTE",
        }.get(kind, str(kind).upper())
        style = {
            "context": "bold #d3deee on #24334e",
            "add": "bold #eafff0 on #103a26",
            "delete": "bold #ffe7ea on #3a131b",
            "meta": "bold #d6e0f2 on #33405a",
            "comment": "bold #fff3cc on #3a2b08",
            "line-comment": "bold #fff3cc on #3a2b08",
        }.get(kind, "bold #d3deee on #2d3e5c")
        return Text(f" {label} ", style=style)

    def _render_chunk_content_text(
        self,
        kind: str,
        text: str,
        *,
        pair_text: str | None = None,
        file_path: str = "",
    ) -> Text:
        prefix = {
            "context": "  ",
            "add": "+ ",
            "delete": "- ",
            "meta": "\\ ",
            "comment": "! ",
            "line-comment": "! ",
        }.get(kind, "? ")
        prefix_style = {
            # Context lines should remain readable; avoid dimming the gutter too much.
            "context": "#9db0c8",
            "add": "bold #52d38a",
            "delete": "bold #ff6b7d",
            "meta": "italic #9db0c8",
            "comment": "bold #f3e6b3",
            "line-comment": "bold #f3e6b3",
        }.get(kind, "#c7d4e8")

        lexer = None
        if self.diff_syntax and kind in {"context", "add", "delete"}:
            lexer = self._syntax_lexer_for_file(file_path, code_hint=text)
        if lexer:
            rendered = Text(prefix, style=prefix_style)
            rendered.append(self._syntax_highlight_line(text, lexer=lexer))
        else:
            base_style = {
                "context": "#d3deee",
                "add": "bold #c4f8d1",
                "delete": "bold #ffd3d7",
                "meta": "italic #9db0c8",
                "comment": "bold #f3e6b3",
                "line-comment": "bold #f3e6b3",
            }.get(kind, "#c7d4e8")
            rendered = Text(prefix + text, style=base_style)
        if kind == "context":
            # Give unchanged lines a subtle background so they don't visually merge with add/delete rows.
            rendered.stylize(f"on {self.CONTEXT_LINE_BG}")
        if kind not in {"add", "delete"} or pair_text is None:
            return rendered

        old_text = pair_text if kind == "add" else text
        new_text = text if kind == "add" else pair_text
        prefix_len = len(prefix)
        applied_by_dmp = False
        if self._dmp_engine is not None:
            diffs = self._dmp_engine.diff_main(old_text, new_text, False)
            self._dmp_engine.diff_cleanupSemantic(diffs)
            old_pos = 0
            new_pos = 0
            for op, segment in diffs:
                seg_len = len(segment)
                if seg_len == 0:
                    continue
                if op == 0:
                    old_pos += seg_len
                    new_pos += seg_len
                    continue
                if op < 0:
                    if kind == "delete":
                        rendered.stylize("bold underline #ff93a0", prefix_len + old_pos, prefix_len + old_pos + seg_len)
                        applied_by_dmp = True
                    old_pos += seg_len
                    continue
                if op > 0:
                    if kind == "add":
                        rendered.stylize("bold underline #69d28f", prefix_len + new_pos, prefix_len + new_pos + seg_len)
                        applied_by_dmp = True
                    new_pos += seg_len
                    continue
        if applied_by_dmp:
            return rendered

        opcodes = SequenceMatcher(a=old_text, b=new_text, autojunk=False).get_opcodes()
        for tag, old_start, old_end, new_start, new_end in opcodes:
            if tag == "equal":
                continue
            if kind == "add":
                if new_end > new_start:
                    rendered.stylize("bold underline #69d28f", prefix_len + new_start, prefix_len + new_end)
            else:
                if old_end > old_start:
                    rendered.stylize("bold underline #ff93a0", prefix_len + old_start, prefix_len + old_end)
        return rendered

    def _add_left_border(self, value: str, row_type: str) -> str:
        if row_type == "spacer":
            return ""
        if not value:
            return "│"
        return f"│ {value}"

    def _comment_for_chunk(self, chunk_id: str) -> str:
        record = self.doc.get("reviews", {}).get(chunk_id, {})
        if not isinstance(record, dict):
            return ""
        value = record.get("comment")
        if value is None:
            return ""
        return str(value).strip()

    def _line_comments_for_chunk(self, chunk_id: str) -> list[dict[str, Any]]:
        record = self.doc.get("reviews", {}).get(chunk_id, {})
        if not isinstance(record, dict):
            return []
        raw_line_comments = record.get("lineComments")
        if not isinstance(raw_line_comments, list):
            return []

        line_comments: list[dict[str, Any]] = []
        for item in raw_line_comments:
            if not isinstance(item, dict):
                continue
            comment = str(item.get("comment", "")).strip()
            if not comment:
                continue
            old_line = normalize_line_number(item.get("oldLine"))
            new_line = normalize_line_number(item.get("newLine"))
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
            line_comments.append(
                {
                    "oldLine": old_line,
                    "newLine": new_line,
                    "lineType": line_type,
                    "comment": comment,
                }
            )
        return line_comments

    def _line_comment_map_for_chunk(self, chunk_id: str) -> dict[str, list[str]]:
        line_comment_map: dict[str, list[str]] = {}
        for item in self._line_comments_for_chunk(chunk_id):
            key = line_anchor_key(str(item.get("lineType", "")), item.get("oldLine"), item.get("newLine"))
            line_comment_map.setdefault(key, []).append(str(item.get("comment", "")))
        return line_comment_map

    def _line_comment_for_anchor(self, chunk_id: str, old_line: Any, new_line: Any, line_type: str) -> str:
        key = line_anchor_key(line_type, old_line, new_line)
        comments = self._line_comment_map_for_chunk(chunk_id).get(key, [])
        return comments[0].strip() if comments else ""

    def _line_comment_count_for_chunk(self, chunk_id: str) -> int:
        return len(self._line_comments_for_chunk(chunk_id))

    def _group_brief_for_group(self, group_id: str) -> dict[str, Any]:
        group_briefs = self.doc.get("groupBriefs", {})
        if not isinstance(group_briefs, dict):
            return {}
        brief = group_briefs.get(group_id, {})
        return brief if isinstance(brief, dict) else {}

    def _group_brief_status_for_group(self, group_id: str) -> str:
        if group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return "n/a"
        brief = self._group_brief_for_group(group_id)
        status = str(brief.get("status", "draft")).strip()
        return status if status in {"draft", "ready", "acknowledged", "stale"} else "draft"

    def _group_brief_summary_for_group(self, group_id: str) -> str:
        if group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return ""
        brief = self._group_brief_for_group(group_id)
        return str(brief.get("summary", "")).strip()

    def _group_brief_display_for_group(self, group_id: str) -> str:
        if group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return "-"
        brief = self._group_brief_for_group(group_id)
        if not brief:
            return "-"
        status = self._group_brief_status_for_group(group_id)
        return {"acknowledged": "ack"}.get(status, status)

    def _approval_icon_for_group(self, group_id: str) -> Text:
        """Return a compact approval icon to prefix the group name."""
        if group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return Text("  ", style="dim")
        status = check_group_approval(self.doc, group_id)
        if status.approved and status.valid:
            return Text("✓ ", style="green")
        if status.approved and not status.valid:
            return Text("~ ", style="yellow")
        if status.reason == REASON_CHANGES_REQUESTED:
            return Text("✗ ", style="red")
        if status.reason == REASON_REVOKED:
            return Text("↩ ", style="yellow")
        return Text("  ", style="dim")

    def _normalized_group_brief_items(self, values: Any) -> list[str]:
        return normalize_brief_items(values)

    def _set_group_brief_payload_for_group(self, group_id: str, payload: dict[str, Any]) -> None:
        if group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return
        group_briefs: dict[str, Any] = self.doc.setdefault("groupBriefs", {})
        if not isinstance(group_briefs, dict):
            group_briefs = {}
            self.doc["groupBriefs"] = group_briefs
        before_state = json.dumps(group_briefs.get(group_id), ensure_ascii=False, sort_keys=True, default=str)
        fallback_status = self._group_brief_status_for_group(group_id)
        if fallback_status == "n/a":
            fallback_status = "draft"
        brief = merge_group_brief_payload(group_briefs.get(group_id), payload, fallback_status=fallback_status)
        if brief is not None:
            group_briefs[group_id] = brief
        else:
            group_briefs.pop(group_id, None)
        after_state = json.dumps(group_briefs.get(group_id), ensure_ascii=False, sort_keys=True, default=str)
        if before_state != after_state:
            self._mark_dirty()

    def _set_group_brief_for_group(self, group_id: str, *, summary: str, status: str | None = None) -> None:
        if group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return
        brief = self._group_brief_for_group(group_id)
        self._set_group_brief_payload_for_group(
            group_id,
            {
                "status": status or self._group_brief_status_for_group(group_id),
                "summary": summary,
                "focusPoints": brief.get("focusPoints", []),
                "testEvidence": brief.get("testEvidence", []),
                "knownTradeoffs": brief.get("knownTradeoffs", []),
                "questionsForReviewer": brief.get("questionsForReviewer", []),
            },
        )

    def _set_group_brief_status_for_group(self, group_id: str, status: str) -> None:
        if group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return
        if status not in {"draft", "ready", "acknowledged", "stale"}:
            return
        group_briefs: dict[str, Any] = self.doc.setdefault("groupBriefs", {})
        if not isinstance(group_briefs, dict):
            group_briefs = {}
            self.doc["groupBriefs"] = group_briefs
        before_state = json.dumps(group_briefs.get(group_id), ensure_ascii=False, sort_keys=True, default=str)
        brief = group_briefs.get(group_id, {})
        if not isinstance(brief, dict):
            brief = {}
        brief["status"] = status
        if not str(brief.get("summary", "")).strip():
            brief.setdefault("summary", "")
        group_briefs[group_id] = brief
        after_state = json.dumps(group_briefs.get(group_id), ensure_ascii=False, sort_keys=True, default=str)
        if before_state != after_state:
            self._mark_dirty()

    def _all_comments_text_for_chunk(self, chunk_id: str) -> str:
        chunks: list[str] = []
        chunk_comment = self._comment_for_chunk(chunk_id)
        if chunk_comment:
            chunks.append(chunk_comment)
        for item in self._line_comments_for_chunk(chunk_id):
            comment = str(item.get("comment", "")).strip()
            if comment:
                chunks.append(comment)
        return " ".join(chunks).strip()

    def _has_any_comment_for_chunk(self, chunk_id: str) -> bool:
        return bool(self._all_comments_text_for_chunk(chunk_id))

    def _set_comment_for_chunk(self, chunk_id: str, comment: str) -> None:
        reviews: dict[str, Any] = self.doc.setdefault("reviews", {})
        before_state = json.dumps(reviews.get(chunk_id), ensure_ascii=False, sort_keys=True, default=str)
        record = reviews.get(chunk_id, {})
        if not isinstance(record, dict):
            record = {}
        clean = comment.strip()
        if clean:
            record["comment"] = clean
        else:
            record.pop("comment", None)

        if record:
            reviews[chunk_id] = record
        else:
            reviews.pop(chunk_id, None)
        after_state = json.dumps(reviews.get(chunk_id), ensure_ascii=False, sort_keys=True, default=str)
        if before_state != after_state:
            self._invalidate_group_report_rows_cache()
            self._mark_dirty()

    def _set_line_comment_for_anchor(
        self,
        chunk_id: str,
        *,
        old_line: Any,
        new_line: Any,
        line_type: str,
        comment: str,
    ) -> None:
        reviews: dict[str, Any] = self.doc.setdefault("reviews", {})
        before_state = json.dumps(reviews.get(chunk_id), ensure_ascii=False, sort_keys=True, default=str)
        record = reviews.get(chunk_id, {})
        if not isinstance(record, dict):
            record = {}

        raw_line_comments = record.get("lineComments")
        existing = raw_line_comments if isinstance(raw_line_comments, list) else []
        target_anchor_key = line_anchor_key(line_type, old_line, new_line)
        kept: list[dict[str, Any]] = []
        for item in existing:
            if not isinstance(item, dict):
                continue
            item_comment = str(item.get("comment", "")).strip()
            if not item_comment:
                continue
            item_key = line_anchor_key(str(item.get("lineType", "")), item.get("oldLine"), item.get("newLine"))
            if item_key == target_anchor_key:
                continue
            kept.append(item)

        clean = comment.strip()
        if clean:
            kept.append(
                {
                    "oldLine": normalize_line_number(old_line),
                    "newLine": normalize_line_number(new_line),
                    "lineType": line_type,
                    "comment": clean,
                    "updatedAt": iso_utc_now(),
                }
            )

        if kept:
            record["lineComments"] = kept
        else:
            record.pop("lineComments", None)

        if record:
            reviews[chunk_id] = record
        else:
            reviews.pop(chunk_id, None)
        after_state = json.dumps(reviews.get(chunk_id), ensure_ascii=False, sort_keys=True, default=str)
        if before_state != after_state:
            self._invalidate_group_report_rows_cache()
            self._mark_dirty()

    def action_new_group(self) -> None:
        def _on_dismiss(result: str | None) -> None:
            if not result:
                return
            new_id = safe_group_id(result)
            existing = {group.get("id") for group in self.doc.get("groups", []) if isinstance(group, dict)}
            suffix = 1
            candidate = new_id
            while candidate in existing or candidate in RESERVED_GROUP_IDS:
                suffix += 1
                candidate = f"{new_id}-{suffix}"
            new_id = candidate

            self.doc.setdefault("groups", []).append({"id": new_id, "name": result, "order": len(existing) + 1, "tags": ["slice"]})
            self.doc.setdefault("assignments", {})[new_id] = []
            self._invalidate_group_assignment_indexes()
            self._mark_dirty()
            self.current_group_id = new_id
            self._refresh_groups(select_group_id=new_id)
            self._apply_chunk_filter()

        self.push_screen(NameModal("New Group (Japanese name OK)", "例: 認証周り / UI調整 / PR3…"), callback=_on_dismiss)

    def action_rename_group(self) -> None:
        if self.current_group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return
        group_id = self.current_group_id
        groups = self.doc.get("groups", [])
        current = next((g for g in groups if isinstance(g, dict) and g.get("id") == group_id), None)
        if not current:
            return
        current_name = str(current.get("name", ""))

        def _on_dismiss(result: str | None) -> None:
            if not result:
                return
            groups_inner = self.doc.get("groups", [])
            current_inner = next((g for g in groups_inner if isinstance(g, dict) and g.get("id") == group_id), None)
            if not current_inner:
                return
            if str(current_inner.get("name", "")) == result:
                return
            current_inner["name"] = result
            self._invalidate_group_report_rows_cache()
            self._mark_dirty()
            self._refresh_groups(select_group_id=group_id)

        self.push_screen(NameModal("Rename Group", "新しい名前（日本語OK）", initial=current_name), callback=_on_dismiss)

    def action_assign_chunk(self) -> None:
        if self.current_group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return
        if not self.selected_chunk_id:
            return
        chunk_id = self.selected_chunk_id
        assignments: dict[str, Any] = self.doc.setdefault("assignments", {})
        changed = False

        # Remove from any group first (enforce at-most-one-group behavior).
        for group_id, items in assignments.items():
            if isinstance(items, list) and chunk_id in items:
                items[:] = [c for c in items if c != chunk_id]
                changed = True

        target = assignments.setdefault(self.current_group_id, [])
        if isinstance(target, list) and chunk_id not in target:
            target.append(chunk_id)
            changed = True

        if changed:
            self._invalidate_group_assignment_indexes()
            self._mark_dirty()
        self._refresh_groups(select_group_id=self.current_group_id)
        self._apply_chunk_filter(keep_selection=True)

    def action_unassign_chunk(self) -> None:
        if not self.selected_chunk_id:
            return
        chunk_id = self.selected_chunk_id
        assignments: dict[str, Any] = self.doc.setdefault("assignments", {})
        changed = False
        for group_id, items in assignments.items():
            if isinstance(items, list) and chunk_id in items:
                items[:] = [c for c in items if c != chunk_id]
                changed = True
        if changed:
            self._invalidate_group_assignment_indexes()
            self._mark_dirty()
        self._refresh_groups(select_group_id=self.current_group_id)
        self._apply_chunk_filter(keep_selection=True)

    def action_edit_comment(self) -> None:
        if not self.selected_chunk_id:
            return
        chunk_id = self.selected_chunk_id
        focused_widget = self.focused
        editing_line_anchor = (
            not self.group_report_mode
            and isinstance(focused_widget, DataTable)
            and focused_widget.id == "lines"
            and self._selected_line_anchor is not None
        )

        if editing_line_anchor:
            anchor = self._selected_line_anchor or {}
            old_line = normalize_line_number(anchor.get("oldLine"))
            new_line = normalize_line_number(anchor.get("newLine"))
            line_type = str(anchor.get("lineType", "context"))
            initial = self._line_comment_for_anchor(chunk_id, old_line, new_line, line_type)
            old_text = "-" if old_line is None else str(old_line)
            new_text = "-" if new_line is None else str(new_line)

            def _on_line_dismiss(result: str | None) -> None:
                if result is None:
                    return
                self._set_line_comment_for_anchor(
                    chunk_id,
                    old_line=old_line,
                    new_line=new_line,
                    line_type=line_type,
                    comment=result,
                )
                self._apply_chunk_filter(keep_selection=True)
                if self.group_report_mode:
                    self._show_current_group_report(target_chunk_id=chunk_id)
                else:
                    self._show_chunk(chunk_id)
                self.notify("Line comment updated", timeout=1.1)

            self.push_screen(
                NameModal(
                    f"Line Comment (old {old_text} / new {new_text})",
                    "行コメントを入力（空で削除）",
                    initial=initial,
                    allow_empty=True,
                ),
                callback=_on_line_dismiss,
            )
            return

        initial = self._comment_for_chunk(chunk_id)

        def _on_chunk_dismiss(result: str | None) -> None:
            if result is None:
                return
            self._set_comment_for_chunk(chunk_id, result)
            self._apply_chunk_filter(keep_selection=True)
            if self.group_report_mode:
                self._show_current_group_report(target_chunk_id=chunk_id)
            else:
                self._show_chunk(chunk_id)
            self.notify("Comment updated", timeout=1.1)

        self.push_screen(
            NameModal(
                "Review Comment",
                "コメントを入力（空で削除）",
                initial=initial,
                allow_empty=True,
            ),
            callback=_on_chunk_dismiss,
        )

    def action_view_group_brief(self) -> None:
        group_id = self._effective_group_id()
        if group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            self.notify("Select a concrete group to view its PR body.", timeout=1.2)
            return
        group_name = self._group_display_name(group_id)
        brief = self._group_brief_for_group(group_id)
        approval_icon = self._approval_icon_for_group(group_id)
        unreviewed_count = self._compute_group_metrics(group_id).get("pending", 0)

        def _on_dismiss(result: dict[str, Any] | None) -> None:
            if result is None:
                return
            action = result.get("action")
            if action == "edit":
                self.action_edit_group_brief()
                return
            if action == "approve":
                try:
                    updated = approve_group(self.doc, group_id, approved_by=self._git_username(), force=True)
                except ValueError as exc:
                    self.notify(str(exc), severity="error", timeout=3.0)
                    return
                group_briefs: dict[str, Any] = self.doc.setdefault("groupBriefs", {})
                if not isinstance(group_briefs, dict):
                    group_briefs = {}
                    self.doc["groupBriefs"] = group_briefs
                new_entry = updated.get("groupBriefs", {}).get(group_id)
                group_briefs[group_id] = new_entry if isinstance(new_entry, dict) else {}
                self._mark_dirty()
                self._refresh_groups(select_group_id=group_id)
                self._render_current_selection()
                self.notify(f"Approved {group_name!r}", severity="information", timeout=1.5)
            elif action == "request_changes":
                updated = request_changes_on_group(
                    self.doc, group_id,
                    requested_by=self._git_username(),
                    comment=result.get("comment") or None,
                )
                group_briefs = self.doc.setdefault("groupBriefs", {})
                if not isinstance(group_briefs, dict):
                    group_briefs = {}
                    self.doc["groupBriefs"] = group_briefs
                new_entry = updated.get("groupBriefs", {}).get(group_id)
                group_briefs[group_id] = new_entry if isinstance(new_entry, dict) else {}
                self._mark_dirty()
                self._refresh_groups(select_group_id=group_id)
                self._render_current_selection()
                self.notify(f"Changes requested on {group_name!r}", severity="warning", timeout=1.5)

        self.push_screen(
            GroupBriefViewerModal(group_name, brief, approval_icon, unreviewed_count=unreviewed_count),
            callback=_on_dismiss,
        )

    def action_edit_group_brief(self) -> None:
        if self.current_group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            self.notify("Select a concrete group to edit its brief.", timeout=1.2)
            return
        group_id = self.current_group_id
        group_name = self._group_display_name(group_id)
        initial = self._group_brief_for_group(group_id)

        def _on_dismiss(result: str | None) -> None:
            if result is None:
                return
            if isinstance(result, dict) and result.get("delete"):
                self._set_group_brief_payload_for_group(
                    group_id,
                    {
                        "status": "draft",
                        "summary": "",
                        "focusPoints": [],
                        "testEvidence": [],
                        "knownTradeoffs": [],
                        "questionsForReviewer": [],
                    },
                )
            elif isinstance(result, dict):
                self._set_group_brief_payload_for_group(group_id, result)
            if self.group_report_mode:
                self._show_current_group_report(target_chunk_id=self.selected_chunk_id)
            elif self.selected_chunk_id:
                self._show_chunk(self.selected_chunk_id)
            self.notify("Group brief updated", timeout=1.1)

        self.push_screen(
            GroupBriefModal(
                group_name,
                initial,
            ),
            callback=_on_dismiss,
        )

    def _git_username(self) -> str:
        """Return git config user.name, falling back to the OS login name."""
        try:
            result = subprocess.run(
                ["git", "config", "user.name"],
                capture_output=True, text=True, timeout=2,
            )
            name = result.stdout.strip()
            if name:
                return name
        except Exception:
            pass
        try:
            import getpass
            return getpass.getuser()
        except Exception:
            return "reviewer"

    def _effective_group_id(self) -> str:
        """Return the group ID at the groups DataTable cursor position.

        Falls back to ``current_group_id`` so that callers who rely on the
        cached value (e.g. after programmatic refresh) still get a result.
        The DataTable cursor is the authoritative source because
        ``RowHighlighted`` may not have fired yet when the user presses a key
        immediately after the table is rendered.
        """
        try:
            group_table = self.query_one("#groups", DataTable)
            row_keys = list(group_table.rows.keys())
            cursor_row = int(group_table.cursor_row)
            if 0 <= cursor_row < len(row_keys):
                gid = str(row_keys[cursor_row].value)
                self.current_group_id = gid  # keep in sync
                return gid
        except Exception:
            pass
        return self.current_group_id

    def action_cycle_group_brief_status(self) -> None:
        if self.current_group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            self.notify("Select a concrete group to change brief status.", timeout=1.2)
            return
        statuses = ["draft", "ready", "acknowledged", "stale"]
        current = self._group_brief_status_for_group(self.current_group_id)
        try:
            next_status = statuses[(statuses.index(current) + 1) % len(statuses)]
        except ValueError:
            next_status = "draft"
        self._set_group_brief_status_for_group(self.current_group_id, next_status)
        if self.group_report_mode:
            self._show_current_group_report(target_chunk_id=self.selected_chunk_id)
        elif self.selected_chunk_id:
            self._show_chunk(self.selected_chunk_id)
        self.notify(f"Group brief status: {next_status}", timeout=1.0)

    def _effective_chunk_selection(self) -> list[str]:
        if self.selected_chunk_ids:
            ordered = [chunk_id for chunk_id in self.filtered_chunk_ids if chunk_id in self.selected_chunk_ids]
            if ordered:
                return ordered
        if self.selected_chunk_id:
            return [self.selected_chunk_id]
        return []

    def _set_status_for_chunk(self, chunk_id: str, status: str) -> None:
        reviews: dict[str, Any] = self.doc.setdefault("reviews", {})
        record = reviews.get(chunk_id, {})
        if not isinstance(record, dict):
            record = {}
        record["status"] = status
        if status == "reviewed":
            record["reviewedAt"] = iso_utc_now()
        reviews[chunk_id] = record
        self.status_map[chunk_id] = status
        affected_group_ids = {PSEUDO_ALL, PSEUDO_UNASSIGNED, *self._group_ids_for_chunk(chunk_id)}
        self._invalidate_group_metrics(affected_group_ids)
        self._mark_dirty()

    def _render_current_selection(self) -> None:
        if self.group_report_mode:
            self._show_current_group_report(target_chunk_id=self.selected_chunk_id)
            return
        if self.selected_chunk_id:
            self._show_chunk(self.selected_chunk_id)

    def action_set_status(self, status: str) -> None:
        if status not in {"unreviewed", "reviewed", "ignored", "needsReReview"}:
            return
        targets = self._effective_chunk_selection()
        if not targets:
            return
        for chunk_id in targets:
            self._set_status_for_chunk(chunk_id, status)
        self._refresh_groups(select_group_id=self.current_group_id)
        self._apply_chunk_filter(keep_selection=True)
        self._render_current_selection()

    def action_toggle_reviewed_checkbox(self) -> None:
        targets = self._effective_chunk_selection()
        if not targets:
            return
        all_reviewed = all(self.status_map.get(chunk_id, "unreviewed") == "reviewed" for chunk_id in targets)
        self.action_set_status("unreviewed" if all_reviewed else "reviewed")

    def action_mark_selected_reviewed(self) -> None:
        self.action_set_status("reviewed")

    def action_mark_selected_unreviewed(self) -> None:
        self.action_set_status("unreviewed")

    def action_toggle_current_chunk_selection(self) -> None:
        if not self.selected_chunk_id:
            return
        chunk_id = self.selected_chunk_id
        if chunk_id in self.selected_chunk_ids:
            self.selected_chunk_ids.discard(chunk_id)
        else:
            self.selected_chunk_ids.add(chunk_id)
        if not self.selected_chunk_ids:
            self.selected_chunk_ids = {chunk_id}
        if self.selected_chunk_id not in self.selected_chunk_ids:
            self.selected_chunk_id = next(
                (cid for cid in self.filtered_chunk_ids if cid in self.selected_chunk_ids),
                chunk_id,
            )
        self._set_chunk_selection_anchor_from_current()
        self._refresh_chunk_selection_markers()
        self._persist_document_state()
        self._refresh_topbar()

    def action_select_all_visible_chunks(self) -> None:
        if not self.filtered_chunk_ids:
            return
        self.selected_chunk_ids = set(self.filtered_chunk_ids)
        if not self.selected_chunk_id or self.selected_chunk_id not in self.selected_chunk_ids:
            self.selected_chunk_id = self.filtered_chunk_ids[0]
            self._select_chunk_row(self.selected_chunk_id)
        self._set_chunk_selection_anchor_from_current()
        self._refresh_chunk_selection_markers()
        self._persist_document_state()
        self._refresh_topbar()

    def action_clear_chunk_multi_selection(self) -> None:
        if not self.selected_chunk_id:
            self.selected_chunk_ids = set()
            self._chunk_selection_anchor_index = None
            self._refresh_chunk_selection_markers()
            self._persist_document_state()
            self._refresh_topbar()
            return
        self.selected_chunk_ids = {self.selected_chunk_id}
        self._set_chunk_selection_anchor_from_current()
        self._refresh_chunk_selection_markers()
        self._persist_document_state()
        self._refresh_topbar()

    def _set_chunk_selection_anchor_from_current(self) -> None:
        if not self.selected_chunk_id:
            self._chunk_selection_anchor_index = None
            return
        try:
            self._chunk_selection_anchor_index = self.filtered_chunk_ids.index(self.selected_chunk_id)
        except ValueError:
            self._chunk_selection_anchor_index = None

    def _set_single_chunk_selection(self, chunk_id: str) -> None:
        self.selected_chunk_id = chunk_id
        self.selected_chunk_ids = {chunk_id}
        self._set_chunk_selection_anchor_from_current()
        self._refresh_chunk_selection_markers()
        self._persist_document_state()

    def _refresh_chunk_selection_markers(self) -> None:
        try:
            chunk_table = self.query_one("#chunks", DataTable)
            for row_index, row_key in enumerate(chunk_table.rows.keys()):
                row_chunk_id = str(row_key.value)
                marker = "*" if row_chunk_id in self.selected_chunk_ids else ""
                chunk_table.update_cell_at((row_index, 0), marker, update_width=False)
        except Exception:
            pass

    def _extend_chunk_selection(self, step: int) -> None:
        if step == 0 or not self.filtered_chunk_ids:
            return
        chunk_table = self.query_one("#chunks", DataTable)
        try:
            current_index = int(chunk_table.cursor_row)
        except Exception:
            current_index = 0
        current_index = max(0, min(len(self.filtered_chunk_ids) - 1, current_index))
        anchor_index = self._chunk_selection_anchor_index
        if anchor_index is None:
            anchor_index = current_index
        anchor_index = max(0, min(len(self.filtered_chunk_ids) - 1, anchor_index))
        new_index = max(0, min(len(self.filtered_chunk_ids) - 1, current_index + step))
        if new_index == current_index and self.selected_chunk_ids:
            return
        start = min(anchor_index, new_index)
        end = max(anchor_index, new_index)
        self.selected_chunk_ids = set(self.filtered_chunk_ids[start : end + 1])
        self.selected_chunk_id = self.filtered_chunk_ids[new_index]
        self._chunk_selection_anchor_index = anchor_index
        try:
            self._suppress_chunk_table_events = True
            chunk_table.move_cursor(row=new_index, column=0, animate=False, scroll=True)
        except Exception:
            pass
        finally:
            self._suppress_chunk_table_events = False
        self._refresh_chunk_selection_markers()
        self._render_current_selection()

    def action_extend_chunk_selection_up(self) -> None:
        self._extend_chunk_selection(-1)

    def action_extend_chunk_selection_down(self) -> None:
        self._extend_chunk_selection(1)

    def action_save(self) -> None:
        self._save_document(auto=False, force=True)

    def action_export_html(self) -> None:
        try:
            self._persist_document_state()
            if self.current_group_id == PSEUDO_ALL:
                selector = "all"
                group_label = "all"
            elif self.current_group_id == PSEUDO_UNASSIGNED:
                selector = "unassigned"
                group_label = "unassigned"
            else:
                selector = self.current_group_id
                group_label = safe_slug(self._group_display_name(self.current_group_id))

            timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            output_dir = Path.cwd() / "out" / "reports"
            output_dir.mkdir(parents=True, exist_ok=True)
            file_stem = safe_slug(self.source_path.stem)
            output_path = output_dir / f"{file_stem}-{group_label}-{timestamp}.html"
            impact_preview_report = self._last_impact_preview_report if isinstance(self._last_impact_preview_report, dict) else None
            impact_state_label = self._last_impact_state_path.name if self._last_impact_state_path is not None else None
            impact_state_fingerprint = self._last_impact_state_fingerprint or None

            html = render_group_diff_html(
                self.doc,
                group_selector=selector,
                report_title=None,
                state_source_label=str(self.state_path.name) if self.state_path is not None else None,
                impact_preview_report=impact_preview_report,
                impact_preview_label=(
                    str(impact_preview_report.get("sourceLabel", "")) if isinstance(impact_preview_report, dict) else None
                ),
                impact_state_label=impact_state_label,
                impact_state_fingerprint=impact_state_fingerprint,
            )
            output_path.write_text(html, encoding="utf-8")
            self.notify(f"HTML exported: {output_path}", timeout=2.8)
        except Exception as error:  # noqa: BLE001
            self.notify(f"HTML export failed: {error}", severity="error", timeout=3.2)

    def action_export_state(self) -> None:
        try:
            self._persist_document_state()
            timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            output_dir = Path.cwd() / "out" / "state"
            output_dir.mkdir(parents=True, exist_ok=True)
            file_stem = safe_slug(self.source_path.stem)
            output_path = output_dir / f"{file_stem}-{timestamp}.state.json"

            state = extract_review_state(self.doc)
            write_json(output_path, state)
            self.notify(f"State exported: {output_path}", timeout=2.8)
        except Exception as error:  # noqa: BLE001
            self.notify(f"State export failed: {error}", severity="error", timeout=3.2)

    def action_import_state(self) -> None:
        def _on_dismiss(result: str | None) -> None:
            if not result:
                return
            path = self._resolve_state_path(result)
            if path is None:
                self.notify("State import failed: path is required", severity="error", timeout=2.4)
                return
            try:
                self._import_state_from_path(path)
                self.notify(f"State imported: {path}", timeout=2.8)
            except Exception as error:  # noqa: BLE001
                self.notify(f"State import failed: {error}", severity="error", timeout=3.2)

        self.push_screen(
            NameModal(
                "Import State JSON",
                "state file path (e.g. out/state/review.state.json)",
                allow_empty=False,
            ),
            callback=_on_dismiss,
        )

    def action_bind_state(self) -> None:
        def _on_dismiss(result: str | None) -> None:
            if not result:
                return
            path = self._resolve_state_path(result)
            if path is None:
                self.notify("State bind failed: path is required", severity="error", timeout=2.4)
                return
            previous = self.state_path
            self.state_path = path
            self._clear_cached_selection_sources()
            self._refresh_topbar_safe()
            if previous and previous != path:
                self.notify(f"State bound: {path} (replaced {previous.name})", timeout=2.6)
            else:
                self.notify(f"State bound: {path}", timeout=2.2)

        self.push_screen(
            NameModal(
                "Bind State JSON",
                "default state file path for save/diff/merge",
                initial=str(self.state_path) if self.state_path is not None else "",
                allow_empty=False,
            ),
            callback=_on_dismiss,
        )

    def action_unbind_state(self) -> None:
        self.state_path = None
        self._clear_cached_selection_sources()
        self._refresh_topbar_safe()
        self.notify("State unbound: saving returns to .diffgr.json", timeout=2.1)

    def action_diff_state(self) -> None:
        if self.state_path is None:
            self.notify("State diff failed: bind a state file first", severity="warning", timeout=2.4)
            return
        try:
            current = extract_review_state(self.doc)
            target = load_review_state(self.state_path)
            diff = diff_review_states(current, target)
            self._last_state_diff_tokens = list(iter_review_state_selection_tokens(diff))
            changed = sum(int(diff.get(section, {}).get("changedCount", 0)) for section in diff)
            added = sum(int(diff.get(section, {}).get("addedCount", 0)) for section in diff)
            removed = sum(int(diff.get(section, {}).get("removedCount", 0)) for section in diff)
            self.notify(
                f"State diff vs {self.state_path.name}: changed={changed} added={added} removed={removed} tokens={len(self._last_state_diff_tokens)}",
                timeout=3.2,
            )
            self.push_screen(TextReportModal(f"State Diff [{self.state_path.name}]", self._format_state_diff_report(diff, self.state_path.name)))
        except Exception as error:  # noqa: BLE001
            self.notify(f"State diff failed: {error}", severity="error", timeout=3.0)

    def action_impact_preview(self) -> None:
        initial_lines = [""]
        initial_lines.append(str(self.source_path))
        if self.state_path is not None:
            initial_lines.append(str(self.state_path))

        def _on_dismiss(result: str | None) -> None:
            if not result:
                return
            try:
                lines = [line.strip() for line in str(result).splitlines()]
                old_raw = lines[0] if len(lines) > 0 else ""
                new_raw = lines[1] if len(lines) > 1 else ""
                state_raw = lines[2] if len(lines) > 2 else ""
                if not old_raw:
                    raise RuntimeError("old diffgr path is required")
                old_path = self._resolve_state_path(old_raw)
                if old_path is None:
                    raise RuntimeError("old diffgr path is required")
                new_path = self._resolve_state_path(new_raw) if new_raw else self.source_path
                state_path = self._resolve_state_path(state_raw) if state_raw else self.state_path
                if state_path is None:
                    raise RuntimeError("state path is required when no bound state is configured")
                old_doc = load_json(old_path)
                validate_document(old_doc)
                new_doc = load_json(new_path)
                validate_document(new_doc)
                review_state = load_review_state(state_path)
                preview = preview_impact_merge(
                    old_doc=old_doc,
                    new_doc=new_doc,
                    state=review_state,
                )
                report = build_impact_preview_report(
                    preview,
                    old_label=old_path.name,
                    new_label=new_path.name,
                    state_label=state_path.name,
                )
                selection_plans = report.get("selectionPlans", {}) if isinstance(report.get("selectionPlans"), dict) else {}
                self._last_impact_selection_plans = {
                    plan_name: [str(item) for item in plan.get("tokens", []) if str(item)]
                    for plan_name, plan in selection_plans.items()
                    if isinstance(plan, dict)
                }
                self._last_impact_rebased_state = preview.get("rebasedState") if isinstance(preview.get("rebasedState"), dict) else None
                self._last_impact_preview_report = report
                self._last_impact_source_label = f"{old_path.name} -> {new_path.name} using {state_path.name}"
                self._last_impact_state_path = state_path.resolve()
                self._last_impact_state_fingerprint = review_state_fingerprint(review_state)
                self.push_screen(
                    TextReportModal(
                        f"Impact Preview [{old_path.name} -> {new_path.name}]",
                        self._format_impact_preview_report(
                            preview,
                            old_label=old_path.name,
                            new_label=new_path.name,
                            state_label=state_path.name,
                        ),
                    )
                )
            except Exception as error:  # noqa: BLE001
                self.notify(f"Impact preview failed: {error}", severity="error", timeout=3.0)

        self.push_screen(
            TextInputModal(
                "Impact Preview",
                "line1: old diffgr path\nline2: new diffgr path (blank = current doc)\nline3: state path (blank = bound state)",
                initial="\n".join(initial_lines),
            ),
            callback=_on_dismiss,
        )

    def action_merge_state(self) -> None:
        if self.state_path is None:
            self.notify("State merge failed: bind a state file first", severity="warning", timeout=2.4)
            return
        try:
            base_state = extract_review_state(self.doc)
            merged_state, merge_warnings, applied = merge_review_states(
                base_state,
                [(str(self.state_path), load_review_state(self.state_path))],
            )
            self._apply_imported_state(merged_state)
            self._mark_dirty()
            summary = summarize_merge_result(base_state, merged_state, merge_warnings)
            changed = sum(int(summary["diff"].get(section, {}).get("changedCount", 0)) for section in summary["diff"])
            kinds = summary.get("warnings", {}).get("kinds", {}) if isinstance(summary.get("warnings"), dict) else {}
            self.notify(
                f"State merged: {self.state_path.name} applied={applied} changed={changed} "
                f"warnings={summary['warnings']['total']} status={kinds.get('statusConflict', 0)} brief={kinds.get('groupBriefConflict', 0)}",
                timeout=3.4,
            )
        except Exception as error:  # noqa: BLE001
            self.notify(f"State merge failed: {error}", severity="error", timeout=3.0)

    def action_merge_preview(self) -> None:
        if self.state_path is None:
            self.notify("State merge preview failed: bind a state file first", severity="warning", timeout=2.4)
            return
        try:
            preview = preview_merge_review_states(
                extract_review_state(self.doc),
                [(str(self.state_path), load_review_state(self.state_path))],
            )
            self.push_screen(
                TextReportModal(
                    f"State Merge Preview [{self.state_path.name}]",
                    self._format_merge_preview_report(preview, state_label=self.state_path.name),
                )
            )
        except Exception as error:  # noqa: BLE001
            self.notify(f"State merge preview failed: {error}", severity="error", timeout=3.0)

    def action_apply_state_selection(self) -> None:
        if self.state_path is None and self._last_impact_rebased_state is None:
            self.notify("State apply failed: bind a state file first or run impact preview", severity="warning", timeout=2.4)
            return

        def _on_dismiss(result: str | None) -> None:
            if not result:
                return
            try:
                raw_tokens = [line.strip() for line in str(result).splitlines() if line.strip()]
                selection_tokens, used_plan = self._expand_selection_tokens(raw_tokens)
                base_state = extract_review_state(self.doc)
                source_label: str
                if used_plan is not None and self._last_impact_rebased_state is not None:
                    if self._last_impact_state_path is None:
                        raise RuntimeError("impact selection plan source state is unavailable; run impact preview again")
                    base_state = load_review_state(self._last_impact_state_path)
                    other_state = self._last_impact_rebased_state
                    source_label = f"impact:{used_plan}"
                elif self.state_path is not None:
                    other_state = load_review_state(self.state_path)
                    source_label = self.state_path.name
                else:
                    raise RuntimeError("impact selection plan is not available")
                preview = preview_review_state_selection(base_state, other_state, selection_tokens)
            except Exception as error:  # noqa: BLE001
                self.notify(f"State apply failed: {error}", severity="error", timeout=3.0)
                return

            summary = preview["summary"]
            source_detail = ""
            if used_plan is not None and self._last_impact_source_label:
                source_detail = f"source={self._last_impact_source_label}\n"
            body = (
                f"path={source_label}\n"
                f"{source_detail}"
                f"tokens={summary.get('tokenCount', 0)} selected={summary.get('selectedKeyCount', 0)} "
                f"no-op={summary.get('noOpCount', 0)} changed-sections={summary.get('changedSectionCount', 0)}\n\n"
                f"{self._format_state_diff_report(preview['resultDiff'], f'selected apply -> {source_label}')}"
            )

            def _on_confirm(confirmed: bool) -> None:
                if not confirmed:
                    return
                self._apply_imported_state(preview["nextState"])
                self._mark_dirty()
                self.notify(
                    f"State selection applied: {source_label} applied={summary.get('appliedCount', 0)} no-op={summary.get('noOpCount', 0)}",
                    timeout=3.2,
                )

            self.push_screen(ConfirmModal("Apply Selected State", body), callback=_on_confirm)

        self.push_screen(
            TextInputModal(
                "Apply Selected State",
                "one selection token per line, e.g. reviews:c1\nthreadState.__files:src/my file.ts\nUse Ctrl+D first to inspect/copy tokens or Ctrl+Shift+D then @handoffs/@reviews/@ui/@all.\nDo not mix @plans with explicit tokens.",
                initial="\n".join(self._last_state_diff_tokens),
            ),
            callback=_on_dismiss,
        )

    def action_apply_impact_plan(self) -> None:
        if self._last_impact_rebased_state is None or not self._last_impact_selection_plans:
            self.notify("Impact apply failed: run impact preview first", severity="warning", timeout=2.6)
            return

        def _on_plan(result: str | None) -> None:
            if not result:
                return
            plan_name = str(result).strip().lower()
            if plan_name not in {"handoffs", "reviews", "ui", "all"}:
                self.notify("Impact apply failed: plan must be one of handoffs/reviews/ui/all", severity="error", timeout=3.0)
                return
            try:
                if self.state_path is not None and self._last_impact_state_path is not None:
                    if self.state_path.resolve() != self._last_impact_state_path.resolve():
                        raise RuntimeError("impact selection plan is stale for the current bound state; run impact preview again")
                selection_tokens = [str(item) for item in self._last_impact_selection_plans.get(plan_name, []) if str(item)]
                source_label = f"impact:{plan_name}"
                source_detail = f"source={self._last_impact_source_label}\n" if self._last_impact_source_label else ""
                if self._last_impact_state_path is None:
                    raise RuntimeError("impact selection plan source state is unavailable; run impact preview again")
                base_state = load_review_state(self._last_impact_state_path)
                if not selection_tokens:
                    body = (
                        f"path={source_label}\n"
                        f"{source_detail}"
                        "tokens=0 selected=0 no-op=0 changed-sections=0\n\n"
                        "State Diff vs selected apply -> impact plan is empty"
                    )
                    self.push_screen(TextReportModal("Impact Plan Apply", body))
                    return
                preview = preview_review_state_selection(
                    base_state,
                    self._last_impact_rebased_state,
                    selection_tokens,
                )
            except Exception as error:  # noqa: BLE001
                self.notify(f"Impact apply failed: {error}", severity="error", timeout=3.0)
                return

            summary = preview["summary"]
            body = (
                f"path={source_label}\n"
                f"{source_detail}"
                f"tokens={summary.get('tokenCount', 0)} selected={summary.get('selectedKeyCount', 0)} "
                f"no-op={summary.get('noOpCount', 0)} changed-sections={summary.get('changedSectionCount', 0)}\n\n"
                f"{self._format_state_diff_report(preview['resultDiff'], f'selected apply -> {source_label}')}"
            )

            def _on_confirm(confirmed: bool) -> None:
                if not confirmed:
                    return
                self._apply_imported_state(preview["nextState"])
                self._mark_dirty()
                self.notify(
                    f"Impact plan applied: {source_label} applied={summary.get('appliedCount', 0)} no-op={summary.get('noOpCount', 0)}",
                    timeout=3.2,
                )

            self.push_screen(ConfirmModal("Impact Plan Apply", body), callback=_on_confirm)

        self.push_screen(
            NameModal(
                "Impact Plan Apply",
                "plan name: handoffs | reviews | ui | all",
                initial="handoffs",
                allow_empty=False,
            ),
            callback=_on_plan,
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "filter":
            return
        self.filter_text = event.value.strip().lower()
        self._persist_document_state()
        self._apply_chunk_filter()

    def on_key(self, event: events.Key) -> None:
        focused = self.focused
        if isinstance(focused, Input):
            return
        if isinstance(focused, DataTable) and focused.id == "chunks":
            return
        if event.key in {"backspace", "ctrl+h"}:
            self.action_mark_selected_unreviewed()
            event.prevent_default()
            event.stop()
            return
        if event.key in {"space", "shift+space"} or event.character == " ":
            self.action_mark_selected_reviewed()
            event.prevent_default()
            event.stop()
            return

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "groups":
            group_id = str(event.row_key.value)
            self.current_group_id = group_id
            self._persist_document_state()
            self._apply_chunk_filter()
            return
        if event.data_table.id == "chunks":
            if self._suppress_chunk_table_events:
                return
            if event.row_key.value is None:
                return
            chunk_id = str(event.row_key.value)
            self._set_single_chunk_selection(chunk_id)
            self._persist_document_state()
            if self.group_report_mode:
                self._show_current_group_report(target_chunk_id=chunk_id)
            else:
                self._show_chunk(chunk_id)
            return
        if event.data_table.id == "lines" and self.group_report_mode:
            if event.row_key.value is None:
                return
            self._sync_selection_from_report_row_key(str(event.row_key.value))
            return
        if event.data_table.id == "lines" and not self.group_report_mode:
            if event.row_key.value is None:
                return
            self._sync_selection_from_chunk_line_row_key(str(event.row_key.value))
            return

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "lines" and not self.group_report_mode:
            if event.row_key.value is None:
                return
            self._sync_selection_from_chunk_line_row_key(str(event.row_key.value))
            return
        if event.data_table.id == "groups":
            if event.row_key.value is not None:
                self.current_group_id = str(event.row_key.value)
            return
        if event.data_table.id != "chunks":
            return
        if self._suppress_chunk_table_events:
            return
        if event.row_key.value is None:
            return
        chunk_id = str(event.row_key.value)
        if chunk_id == self.selected_chunk_id:
            return
        self._set_single_chunk_selection(chunk_id)
        self._persist_document_state()
        if self.group_report_mode:
            self._show_current_group_report(target_chunk_id=chunk_id)
        else:
            self._show_chunk(chunk_id)

    def _compute_group_metrics(self, group_id: str) -> dict[str, int]:
        cached = self._group_metrics_cache.get(group_id)
        if cached is not None:
            return dict(cached)
        if group_id == PSEUDO_ALL:
            chunk_ids = set(self.chunk_map.keys())
        elif group_id == PSEUDO_UNASSIGNED:
            chunk_ids = set(self.chunk_map.keys()) - self._assigned_chunk_ids()
        else:
            assigned = self.doc.get("assignments", {}).get(group_id, [])
            chunk_ids = set(assigned) if isinstance(assigned, list) else set()

        reviewed = sum(1 for c in chunk_ids if self.status_map.get(c, "unreviewed") == "reviewed")
        ignored = sum(1 for c in chunk_ids if self.status_map.get(c, "unreviewed") == "ignored")
        pending = sum(
            1
            for c in chunk_ids
            if self.status_map.get(c, "unreviewed") in {"unreviewed", "needsReReview"}
        )
        metrics = {"total": len(chunk_ids), "pending": pending, "reviewed": reviewed, "ignored": ignored}
        self._group_metrics_cache[group_id] = metrics
        return dict(metrics)

    def _assigned_chunk_ids(self) -> set[str]:
        if self._assigned_chunk_ids_cache is not None:
            return set(self._assigned_chunk_ids_cache)
        assigned: set[str] = set()
        for values in self.doc.get("assignments", {}).values():
            if isinstance(values, list):
                assigned.update(values)
        self._assigned_chunk_ids_cache = assigned
        return set(assigned)

    def _refresh_groups(self, select_group_id: str | None = None) -> None:
        group_table = self.query_one("#groups", DataTable)
        group_table.clear(columns=False)

        rows: list[GroupRow] = [
            GroupRow(PSEUDO_ALL, "すべて（All）"),
            GroupRow(PSEUDO_UNASSIGNED, "未割当（Unassigned）"),
        ]
        for group in self.doc.get("groups", []):
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("id", ""))
            if group_id in RESERVED_GROUP_IDS:
                continue
            name = str(group.get("name", group_id))
            rows.append(GroupRow(group_id, name))

        for row in rows:
            m = self._compute_group_metrics(row.group_id)
            icon = self._approval_icon_for_group(row.group_id)
            name_cell = icon + Text(row.name)
            group_table.add_row(
                name_cell,
                self._group_brief_display_for_group(row.group_id),
                str(m["total"]),
                str(m["pending"]),
                str(m["reviewed"]),
                str(m["ignored"]),
                key=row.group_id,
            )

        target = select_group_id or self.current_group_id
        try:
            group_table.cursor_coordinate = (0, 0)
            for i, r in enumerate(rows):
                if r.group_id == target:
                    group_table.cursor_coordinate = (i, 0)
                    break
        except Exception:
            pass

        self._refresh_topbar()

    def _refresh_topbar_safe(self) -> None:
        try:
            self._refresh_topbar()
        except Exception:
            pass

    def _invalidate_group_assignment_indexes(self) -> None:
        self._assigned_chunk_ids_cache = None
        self._chunk_group_ids_cache.clear()
        self._group_metrics_cache.clear()
        self._invalidate_group_report_rows_cache()

    def _invalidate_group_metrics(self, group_ids: set[str] | None = None) -> None:
        if group_ids is None:
            self._group_metrics_cache.clear()
            return
        for group_id in group_ids:
            self._group_metrics_cache.pop(group_id, None)

    def _invalidate_group_report_rows_cache(self) -> None:
        self._group_report_rows_cache_key = None
        self._group_report_rows_cache = None
        self._group_report_rows_revision += 1

    def _group_ids_for_chunk(self, chunk_id: str) -> list[str]:
        cached = self._chunk_group_ids_cache.get(chunk_id)
        if cached is not None:
            return list(cached)
        group_ids: list[str] = []
        assignments = self.doc.get("assignments", {})
        if isinstance(assignments, dict):
            for group_id, chunk_ids in assignments.items():
                if isinstance(chunk_ids, list) and chunk_id in chunk_ids:
                    group_ids.append(str(group_id))
        group_ids = sorted(set(group_ids))
        self._chunk_group_ids_cache[chunk_id] = group_ids
        return list(group_ids)

    def _safe_notify(self, message: str, *, timeout: float = 1.5, severity: str | None = None) -> None:
        try:
            self.notify(message, timeout=timeout, severity=severity)
        except Exception:
            pass

    def _mark_dirty(self) -> None:
        self._has_unsaved_changes = True
        self._refresh_topbar_safe()

    def _save_state_label(self) -> str:
        if self._has_unsaved_changes:
            return "save=dirty"
        if self._last_saved_at is None:
            return "save=clean"
        stamp = self._last_saved_at.strftime("%H:%M:%S")
        return f"save=clean({self._last_save_kind}@{stamp})"

    def _bound_state_label(self) -> str:
        if self.state_path is None:
            return "state=doc"
        return f"state={self.state_path.name}"

    def _auto_split_output_dir(self) -> Path:
        configured = str(os.environ.get("DIFFGR_AUTO_SPLIT_DIR", "")).strip()
        if configured:
            configured_path = Path(configured).expanduser()
            if not configured_path.is_absolute():
                configured_path = self.source_path.parent / configured_path
            return configured_path
        if self.source_path.parent.name.lower() == "reviewers":
            return self.source_path.parent
        reviewers_dir = self.source_path.parent / "reviewers"
        if reviewers_dir.is_dir():
            return reviewers_dir
        return self.source_path.parent / f"{safe_slug(self.source_path.stem)}.reviewers"

    def _sync_split_review_files(self) -> tuple[int, Path]:
        meta = self.doc.get("meta", {})
        if isinstance(meta, dict) and isinstance(meta.get("x-reviewSplit"), dict):
            return 0, self.source_path.parent
        split_items = split_document_by_group(self.doc, include_empty=False)
        output_dir = self._auto_split_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        source_path = str(self.source_path.resolve())
        manifest_path = output_dir / self.AUTO_SPLIT_MANIFEST_NAME
        previous_paths: set[str] = set()
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(manifest, dict) and str(manifest.get("source", "")) == source_path:
                    for item in manifest.get("files", []):
                        if not isinstance(item, dict):
                            continue
                        rel_path = str(item.get("path", "")).strip()
                        if rel_path:
                            previous_paths.add(rel_path)
            except Exception:
                pass

        manifest_items: list[dict[str, Any]] = []
        current_paths: set[str] = set()
        for index, (group, group_doc) in enumerate(split_items, start=1):
            group_id = str(group.get("id", ""))
            group_name = str(group.get("name", group_id))
            filename = build_group_output_filename(index, group_id, group_name)
            target = output_dir / filename
            write_json(target, group_doc)
            current_paths.add(filename)
            manifest_items.append(
                {
                    "groupId": group_id,
                    "groupName": group_name,
                    "chunkCount": len(group_doc.get("chunks", [])),
                    "path": filename,
                }
            )

        for stale_rel_path in sorted(previous_paths - current_paths):
            stale_path = output_dir / stale_rel_path
            if stale_path.is_file():
                try:
                    stale_path.unlink()
                except Exception:
                    pass

        manifest_payload = {
            "source": source_path,
            "fileCount": len(manifest_items),
            "files": manifest_items,
            "updatedAt": iso_utc_now(),
        }
        write_json(manifest_path, manifest_payload)
        return len(manifest_items), output_dir

    def _save_document(self, *, auto: bool, force: bool) -> bool:
        if not force and not self._has_unsaved_changes:
            return False
        try:
            self._persist_document_state()
            if self.state_path is not None:
                save_review_state(self.state_path, extract_review_state(self.doc))
                self._has_unsaved_changes = False
                self._last_saved_at = dt.datetime.now()
                self._last_save_kind = "auto" if auto else "manual"
                self._refresh_topbar_safe()
                if auto:
                    self._safe_notify(
                        f"Auto-saved state: {self.state_path.name}",
                        timeout=0.9,
                    )
                else:
                    self._safe_notify(
                        f"Saved state: {self.state_path}",
                        timeout=1.5,
                    )
                return True
            backup = self.source_path.with_suffix(self.source_path.suffix + ".bak")
            if not backup.exists():
                backup.write_text(self.source_path.read_text(encoding="utf-8"), encoding="utf-8")
            write_json(self.source_path, self.doc)
            split_count, split_dir = self._sync_split_review_files()
            self._has_unsaved_changes = False
            self._last_saved_at = dt.datetime.now()
            self._last_save_kind = "auto" if auto else "manual"
            self._refresh_topbar_safe()
            if auto:
                self._safe_notify(
                    f"Auto-saved: {self.source_path.name} + split:{split_count}",
                    timeout=0.9,
                )
            else:
                self._safe_notify(
                    f"Saved: {self.source_path} (split:{split_count} -> {split_dir.name})",
                    timeout=1.5,
                )
            return True
        except Exception as error:  # noqa: BLE001
            self._safe_notify(f"Save failed: {error}", severity="error", timeout=3.0)
            return False

    def _auto_save_tick(self) -> None:
        if not self._has_unsaved_changes:
            return
        self._save_document(auto=True, force=False)

    def _refresh_topbar(self) -> None:
        title = str(self.doc.get("meta", {}).get("title", "-"))
        group_name = self._group_display_name(self.current_group_id)
        m_all = self._compute_group_metrics(PSEUDO_ALL)
        m_cur = self._compute_group_metrics(self.current_group_id)
        cur_rate = self._reviewed_rate(m_cur)
        all_rate = self._reviewed_rate(m_all)
        selected_count = len(self._effective_chunk_selection())
        save_state = self._save_state_label()
        bound_state = self._bound_state_label()
        detail_view = "side-by-side" if self.chunk_detail_view_mode == "side_by_side" else "compact"
        warnings_text = f"warnings={len(self.warnings)}"
        filter_display = self.filter_text if self.filter_text else "none"
        editor_label = self._editor_setting_label()
        ctx_label = "all" if self.show_context_lines else "changes"
        syntax_label = "on" if self.diff_syntax else "off"
        theme_label = self.diff_syntax_theme
        wrap_label = "on" if self.diff_auto_wrap else "off"
        text = (
            f"[b]{title}[/b]  "
            f"group={group_name}  "
            f"cur(total={m_cur['total']} pending={m_cur['pending']} reviewed={m_cur['reviewed']} rate={cur_rate:.1f}%)  "
            f"all(total={m_all['total']} pending={m_all['pending']} reviewed={m_all['reviewed']} rate={all_rate:.1f}%)  "
            f"selected={selected_count}  "
            f"{save_state}  "
            f"{bound_state}  "
            f"editor={editor_label}  "
            f"syntax={syntax_label} theme={theme_label}  "
            f"wrap={wrap_label}  "
            f"autosave={self.AUTOSAVE_INTERVAL_SEC}s  "
            f"{self.KEYMAP_REV}  "
            f"split={self.left_pane_pct}:{100 - self.left_pane_pct}  "
            f"diff={self.diff_old_ratio * 100:.0f}:{(1 - self.diff_old_ratio) * 100:.0f}  "
            f"view={'group-diff' if self.group_report_mode else 'chunk'}  detailView={detail_view}  ctx={ctx_label}  "
            f"{warnings_text}  filter={filter_display}  "
            f"[dim]keys: n/e=group, a/u=assign, b=brief, l=lines, m=comment(line/chunk), o=open-file, t=settings, d=report, v=view, z=focus-changes, w=wrap, Shift+T=theme, h=html, Shift+H=export-state, Shift+I=import-state, Ctrl+B=bind-state, Ctrl+U=unbind-state, Ctrl+D=diff-state, Ctrl+Shift+D=impact-preview, Ctrl+Alt+D=merge-preview, Ctrl+M=merge-state, Ctrl+Shift+M=apply-state, Ctrl+Alt+M=impact-apply, 1-4=status, Shift+Up/Down or j/k=range-select, Space=toggle done<->undone, Shift+Space=done(reviewed), Backspace or 1=undone(unreviewed), x=toggle-select, Ctrl+A=select-all, Esc=clear-select, [ ]/Ctrl+Arrows=split, Alt+Arrows=diff, s=save[/dim]"
        )
        self.query_one("#topbar", Static).update(text)

    def _reviewed_rate(self, metrics: dict[str, int]) -> float:
        total = int(metrics.get("total", 0))
        if total <= 0:
            return 0.0
        reviewed = int(metrics.get("reviewed", 0))
        return (reviewed / total) * 100.0

    def _done_checkbox_for_status(self, status: str) -> str:
        return "[✅]" if status == "reviewed" else "[  ]"

    def _group_display_name(self, group_id: str) -> str:
        if group_id == PSEUDO_ALL:
            return "All"
        if group_id == PSEUDO_UNASSIGNED:
            return "Unassigned"
        for group in self.doc.get("groups", []):
            if isinstance(group, dict) and group.get("id") == group_id:
                return str(group.get("name", group_id))
        return group_id

    def _chunks_for_current_group(self) -> list[dict[str, Any]]:
        if self.current_group_id == PSEUDO_ALL:
            ids = list(self.chunk_map.keys())
        elif self.current_group_id == PSEUDO_UNASSIGNED:
            ids = list(set(self.chunk_map.keys()) - self._assigned_chunk_ids())
        else:
            assigned = self.doc.get("assignments", {}).get(self.current_group_id, [])
            ids = list(assigned) if isinstance(assigned, list) else []
        chunks = [self.chunk_map[c] for c in ids if c in self.chunk_map]
        return sorted(
            chunks,
            key=lambda chunk: (
                chunk.get("filePath", ""),
                chunk.get("old", {}).get("start", 0),
                chunk.get("id", ""),
            ),
        )

    def _matches_filter(self, chunk: dict[str, Any]) -> bool:
        if not self.filter_text:
            return True
        status = self.status_map.get(chunk["id"], "unreviewed")
        header = str(chunk.get("header", ""))
        comment = self._all_comments_text_for_chunk(chunk["id"])
        haystack = " ".join([chunk["id"], chunk.get("filePath", ""), header, status, comment]).lower()
        return self.filter_text in haystack

    def _apply_chunk_filter(self, keep_selection: bool = False) -> None:
        chunk_table = self.query_one("#chunks", DataTable)
        chunk_table.clear(columns=False)
        self.filtered_chunk_ids = []

        chunks = [c for c in self._chunks_for_current_group() if self._matches_filter(c)]
        visible_chunk_ids = [str(chunk.get("id", "")) for chunk in chunks if str(chunk.get("id", ""))]
        if self.selected_chunk_ids:
            self.selected_chunk_ids = {chunk_id for chunk_id in self.selected_chunk_ids if chunk_id in visible_chunk_ids}
        if self.selected_chunk_id and self.selected_chunk_id not in visible_chunk_ids:
            self.selected_chunk_id = None
        if not self.selected_chunk_id and self.selected_chunk_ids:
            self.selected_chunk_id = next((chunk_id for chunk_id in visible_chunk_ids if chunk_id in self.selected_chunk_ids), None)
        if self.selected_chunk_id and not self.selected_chunk_ids:
            self.selected_chunk_ids = {self.selected_chunk_id}

        for chunk in chunks:
            chunk_id = chunk["id"]
            self.filtered_chunk_ids.append(chunk_id)
            status = self.status_map.get(chunk_id, "unreviewed")
            comment_flag = "C" if self._has_any_comment_for_chunk(chunk_id) else ""
            chunk_table.add_row(
                "*" if chunk_id in self.selected_chunk_ids else "",
                self._done_checkbox_for_status(status),
                status,
                comment_flag,
                chunk_id[:12],
                format_file_label(str(chunk.get("filePath", "-"))),
                f"{chunk.get('old', {}).get('start', '?')},{chunk.get('old', {}).get('count', '?')}",
                f"{chunk.get('new', {}).get('start', '?')},{chunk.get('new', {}).get('count', '?')}",
                str(chunk.get("header", "")),
                key=chunk_id,
            )

        self._refresh_topbar()

        if self.group_report_mode:
            self._selected_line_anchor = None
            self._chunk_line_anchor_by_row_key = {}
            if self.filtered_chunk_ids and (self.selected_chunk_id not in self.filtered_chunk_ids):
                self.selected_chunk_id = self.filtered_chunk_ids[0]
                self.selected_chunk_ids = {self.selected_chunk_id}
                self._set_chunk_selection_anchor_from_current()
                self._select_chunk_row(self.selected_chunk_id)
            self._show_current_group_report(target_chunk_id=self.selected_chunk_id)
            return

        if keep_selection and self.selected_chunk_id in self.filtered_chunk_ids:
            self.selected_chunk_ids = {
                chunk_id for chunk_id in self.selected_chunk_ids if chunk_id in self.filtered_chunk_ids
            } or {self.selected_chunk_id}
            self._set_chunk_selection_anchor_from_current()
            self._select_chunk_row(self.selected_chunk_id)
            return
        if self.filtered_chunk_ids:
            first = self.filtered_chunk_ids[0]
            self.selected_chunk_id = first
            self.selected_chunk_ids = {first}
            self._set_chunk_selection_anchor_from_current()
            self._select_chunk_row(first)
            self._show_chunk(first)
        else:
            self.selected_chunk_id = None
            self.selected_chunk_ids = set()
            self._chunk_selection_anchor_index = None
            self._selected_line_anchor = None
            self._chunk_line_anchor_by_row_key = {}
            self.query_one("#meta", Static).update("No chunks match current selection/filter.")
            self.query_one("#lines", DataTable).clear(columns=False)
        self._persist_document_state()

    def _visible_chunks_for_report(self) -> list[dict[str, Any]]:
        return [self.chunk_map[cid] for cid in self.filtered_chunk_ids if cid in self.chunk_map]

    def _groups_for_chunk(self, chunk_id: str) -> list[str]:
        return [self._group_display_name(group_id) for group_id in self._group_ids_for_chunk(chunk_id)]

    def _show_current_group_report(self, target_chunk_id: str | None = None) -> None:
        group_name = self._group_display_name(self.current_group_id)
        chunks = self._visible_chunks_for_report()
        chunks_for_view: list[dict[str, Any]] = []
        for chunk in chunks:
            chunk_view = dict(chunk)
            chunk_id = str(chunk.get("id", ""))
            chunk_view["_assignedGroups"] = self._groups_for_chunk(chunk_id)
            chunk_view["_comment"] = self._comment_for_chunk(chunk_id)
            chunk_view["_lineComments"] = self._line_comments_for_chunk(chunk_id)
            chunks_for_view.append(chunk_view)
        file_count = len({str(chunk.get("filePath", "")) for chunk in chunks})
        selected_summary = "-"
        selected_comment = "(none)"
        selected_line_comment_count = 0
        group_brief = self._group_brief_summary_for_group(self.current_group_id) or "(none)"
        group_brief_status = self._group_brief_status_for_group(self.current_group_id)
        if target_chunk_id and target_chunk_id in self.chunk_map:
            selected_chunk = self.chunk_map[target_chunk_id]
            selected_summary = (
                f"{target_chunk_id[:12]} "
                f"{format_file_label(str(selected_chunk.get('filePath', '-')))}"
            )
            selected_comment = self._comment_for_chunk(target_chunk_id) or "(none)"
            selected_line_comment_count = self._line_comment_count_for_chunk(target_chunk_id)
        self.query_one("#meta", Static).update(
            "\n".join(
                [
                    f"[b]group[/b] {group_name}",
                    f"[b]mode[/b] group diff report",
                    f"[b]chunks[/b] {len(chunks)}",
                    f"[b]files[/b] {file_count}",
                    f"[b]group brief[/b] {group_brief_status} / {group_brief}",
                    f"[b]selected chunk[/b] {selected_summary}",
                    f"[b]comment[/b] {selected_comment}",
                    f"[b]line comments[/b] {selected_line_comment_count}",
                    f"[b]scope[/b] chunk-level assignment (line-level ownership is not tracked)",
                    "[dim]Press [b]d[/b] to return to single-chunk view.[/dim]",
                ]
            )
        )

        lines_table = self._switch_lines_table_mode("group_report")
        cache_key = (tuple(self.filtered_chunk_ids), self._group_report_rows_revision)
        rows = self._group_report_rows_cache
        if rows is None or self._group_report_rows_cache_key != cache_key:
            rows = build_group_diff_report_rows(chunks_for_view)
            self._group_report_rows_cache = rows
            self._group_report_rows_cache_key = cache_key
        self._group_report_row_chunk_by_key = {}
        target_row_index: int | None = None
        for row_index, row in enumerate(rows):
            row_key = f"r-{row_index}"
            if row.chunk_id:
                self._group_report_row_chunk_by_key[row_key] = row.chunk_id
            is_selected = bool(target_chunk_id and row.chunk_id == target_chunk_id and row.row_type == "chunk")
            old_text = row.old_text
            new_text = row.new_text
            if is_selected:
                old_text = f">> {old_text}"
                new_text = f">> {new_text}" if new_text else ">>"
            old_text = self._add_left_border(old_text, row.row_type)
            new_text = self._add_left_border(new_text, row.row_type)
            lines_table.add_row(
                self._render_report_number(row.old_line, row.row_type, "old", selected=is_selected),
                self._render_report_text(old_text, row.row_type, "old", selected=is_selected),
                self._render_report_number(row.new_line, row.row_type, "new", selected=is_selected),
                self._render_report_text(new_text, row.row_type, "new", selected=is_selected),
                key=row_key,
            )
            if (
                target_row_index is None
                and target_chunk_id
                and row.row_type == "chunk"
                and row.chunk_id == target_chunk_id
            ):
                target_row_index = row_index
        if target_row_index is not None:
            try:
                viewport_height = max(1, int(lines_table.scrollable_content_region.height))
                target_scroll_y = max(0, target_row_index - (viewport_height // 2))
                lines_table.scroll_to(y=target_scroll_y, animate=False, force=True, immediate=True)
                lines_table.move_cursor(row=target_row_index, column=0, animate=False, scroll=False)
            except Exception:
                pass

    def _sync_selection_from_report_row_key(self, row_key_value: str, *, refresh_report: bool = True) -> bool:
        chunk_id = self._group_report_row_chunk_by_key.get(row_key_value)
        if not chunk_id:
            return False
        if chunk_id == self.selected_chunk_id:
            return False
        self.selected_chunk_id = chunk_id
        self.selected_chunk_ids = {chunk_id}
        self._set_chunk_selection_anchor_from_current()
        self._refresh_chunk_selection_markers()
        self._select_chunk_row(chunk_id)
        self._persist_document_state()
        if refresh_report and self.group_report_mode:
            self._show_current_group_report(target_chunk_id=chunk_id)
        return True

    def _sync_selection_from_chunk_line_row_key(self, row_key_value: str) -> bool:
        anchor = self._chunk_line_anchor_by_row_key.get(row_key_value)
        if not anchor:
            return False

        anchor_key = str(anchor.get("anchorKey", ""))
        selected_key = str(self._selected_line_anchor.get("anchorKey", "")) if self._selected_line_anchor else ""
        if anchor_key and anchor_key == selected_key:
            return False
        self._selected_line_anchor = dict(anchor)
        self._persist_document_state()
        if self.selected_chunk_id and not self.group_report_mode:
            self._update_chunk_meta(self.selected_chunk_id)
        return True

    def _select_chunk_row(self, chunk_id: str) -> None:
        chunk_table = self.query_one("#chunks", DataTable)
        try:
            self._suppress_chunk_table_events = True
            for row_index, row_key in enumerate(chunk_table.rows.keys()):
                if str(row_key.value) == chunk_id:
                    chunk_table.cursor_coordinate = (row_index, 0)
                    break
        except Exception:
            pass
        finally:
            self._suppress_chunk_table_events = False

    def _select_lines_row(self, row_key_value: str) -> None:
        lines_table = self.query_one("#lines", DataTable)
        try:
            for row_index, row_key in enumerate(lines_table.rows.keys()):
                if str(row_key.value) == row_key_value:
                    lines_table.cursor_coordinate = (row_index, 0)
                    break
        except Exception:
            pass

    def _build_chunk_meta_lines(self, chunk_id: str) -> list[str]:
        chunk = self.chunk_map.get(chunk_id)
        if chunk is None:
            return ["No chunk selected."]
        assigned_groups = self._groups_for_chunk(chunk_id)
        file_path = str(chunk.get("filePath", "-"))

        meta_lines = [
            f"[b]group brief[/b] {self._group_brief_status_for_group(self.current_group_id)} / {self._group_brief_summary_for_group(self.current_group_id) or '(none)'}",
            f"[b]comment[/b] {self._comment_for_chunk(chunk_id) or '(none)'}",
            f"[b]line comments[/b] {self._line_comment_count_for_chunk(chunk_id)}",
            f"[b]path[/b] {file_path}",
            f"[b]assigned groups[/b] {', '.join(assigned_groups) if assigned_groups else '(none)'}",
        ]

        if self._selected_line_anchor:
            selected = self._selected_line_anchor
            old_line = normalize_line_number(selected.get("oldLine"))
            new_line = normalize_line_number(selected.get("newLine"))
            line_type = str(selected.get("lineType", "context"))
            old_text = "-" if old_line is None else str(old_line)
            new_text = "-" if new_line is None else str(new_line)
            anchor_comment = self._line_comment_for_anchor(chunk_id, old_line, new_line, line_type)
            meta_lines.append(f"[b]selected line[/b] old {old_text} / new {new_text} ({line_type})")
            meta_lines.append(f"[b]selected line comment[/b] {anchor_comment or '(none)'}")

        return meta_lines

    def _update_chunk_meta(self, chunk_id: str) -> None:
        self.query_one("#meta", Static).update("\n".join(self._build_chunk_meta_lines(chunk_id)))

    def _chunk_line_wrap_width(self, *, side_by_side: bool) -> int:
        if not self.diff_auto_wrap:
            return 0
        try:
            lines_width = int(self.query_one("#lines", DataTable).size.width)
        except Exception:
            lines_width = 0
        if lines_width <= 0:
            lines_width = 120
        if side_by_side:
            if self._lines_side_by_side_widths:
                old_width, new_width = self._lines_side_by_side_widths
                content_width = max(int(old_width), int(new_width))
            else:
                content_width = max(24, int(lines_width * 0.45))
            return max(24, content_width - 3)
        return max(30, lines_width - 24)

    def _wrap_diff_line_text(self, text: str, *, width: int) -> list[str]:
        if width <= 0:
            return [str(text)]
        chunks: list[str] = []
        raw_lines = str(text).replace("\t", "    ").splitlines()
        if not raw_lines:
            raw_lines = [""]
        for raw_line in raw_lines:
            wrapped = textwrap.wrap(
                raw_line,
                width=max(1, int(width)),
                replace_whitespace=False,
                drop_whitespace=False,
                break_long_words=True,
                break_on_hyphens=False,
            )
            chunks.extend(wrapped if wrapped else [""])
        return chunks

    def _show_chunk(self, chunk_id: str) -> None:
        chunk = self.chunk_map.get(chunk_id)
        if chunk is None:
            return
        previous_anchor_key = ""
        if self._selected_line_anchor:
            previous_anchor_key = str(self._selected_line_anchor.get("anchorKey", ""))
        self._chunk_line_anchor_by_row_key = {}
        self._selected_line_anchor = None

        side_by_side = self.chunk_detail_view_mode == "side_by_side"
        lines_table_mode = "chunk_side_by_side" if side_by_side else "chunk_compact"
        lines_table = self._switch_lines_table_mode(lines_table_mode)
        wrap_width = self._chunk_line_wrap_width(side_by_side=side_by_side)
        comment_lines = format_comment_lines(self._comment_for_chunk(chunk_id), max_width=110, max_lines=10)
        if comment_lines:
            for index, comment_line in enumerate(comment_lines):
                if index == 0:
                    text = f"COMMENT: {comment_line}"
                else:
                    text = f"         {comment_line}"
                if side_by_side:
                    lines_table.add_row(
                        "",
                        Text(""),
                        "",
                        self._render_chunk_content_text("comment", text, file_path=str(chunk.get("filePath", ""))),
                        key=f"chunk-comment-{index}",
                    )
                else:
                    lines_table.add_row(
                        "",
                        "",
                        self._render_chunk_kind_badge("comment"),
                        self._render_chunk_content_text("comment", text, file_path=str(chunk.get("filePath", ""))),
                        key=f"chunk-comment-{index}",
                    )
            if side_by_side:
                lines_table.add_row("", Text(""), "", Text(""), key="chunk-comment-sep")
            else:
                lines_table.add_row("", "", self._render_chunk_kind_badge("meta"), Text(""), key="chunk-comment-sep")

        line_comment_map = self._line_comment_map_for_chunk(chunk_id)
        lines = list(chunk.get("lines", [])[: max(200, self.page_size * 30)])

        if not self.show_context_lines:
            hidden_ctx = 0
            kept_ctx = 0
            for line in lines:
                kind = str(line.get("kind", ""))
                if kind != "context":
                    continue
                old_line = normalize_line_number(line.get("oldLine"))
                new_line = normalize_line_number(line.get("newLine"))
                anchor_key = line_anchor_key(kind, old_line, new_line)
                if anchor_key in line_comment_map:
                    kept_ctx += 1
                else:
                    hidden_ctx += 1
            hint = f"Context lines hidden: {hidden_ctx} (kept commented: {kept_ctx}). Press 'z' to show all."
            if side_by_side:
                lines_table.add_row(
                    "",
                    Text(""),
                    "",
                    self._render_chunk_content_text("meta", hint, file_path=str(chunk.get("filePath", ""))),
                    key="ctx-hidden-hint",
                )
            else:
                lines_table.add_row(
                    "",
                    "",
                    self._render_chunk_kind_badge("meta"),
                    self._render_chunk_content_text("meta", hint, file_path=str(chunk.get("filePath", ""))),
                    key="ctx-hidden-hint",
                )
        pair_map = self._build_intraline_pair_map(lines)
        selected_row_key: str | None = None
        first_line_row_key: str | None = None
        for line_index, line in enumerate(lines):
            kind = str(line.get("kind", ""))
            old_line = normalize_line_number(line.get("oldLine"))
            new_line = normalize_line_number(line.get("newLine"))
            anchor_key = line_anchor_key(str(kind), old_line, new_line)
            if not self.show_context_lines and kind == "context" and anchor_key not in line_comment_map:
                continue
            row_key_value = f"line-{line_index}"
            if first_line_row_key is None:
                first_line_row_key = row_key_value
            self._chunk_line_anchor_by_row_key[row_key_value] = {
                "anchorKey": anchor_key,
                "oldLine": old_line,
                "newLine": new_line,
                "lineType": str(kind),
            }
            raw_text = str(line.get("text", ""))
            wrapped_chunks = self._wrap_diff_line_text(raw_text, width=wrap_width)
            for wrapped_index, wrapped_text in enumerate(wrapped_chunks):
                is_primary_line = wrapped_index == 0
                content = self._render_chunk_content_text(
                    kind,
                    wrapped_text,
                    pair_text=pair_map.get(line_index) if is_primary_line else None,
                    file_path=str(chunk.get("filePath", "")),
                )
                row_key = row_key_value if is_primary_line else f"{row_key_value}-wrap-{wrapped_index}"
                old_number = ""
                new_number = ""
                if is_primary_line:
                    old_number = "" if line.get("oldLine") is None else str(line.get("oldLine"))
                    new_number = "" if line.get("newLine") is None else str(line.get("newLine"))
                if side_by_side:
                    if kind == "add":
                        old_cell = Text("", style="dim #47715a")
                        new_cell = content
                    elif kind == "delete":
                        old_cell = content
                        new_cell = Text("", style="dim #47715a")
                    elif kind == "context":
                        old_cell = self._render_chunk_content_text("context", wrapped_text, file_path=str(chunk.get("filePath", "")))
                        new_cell = self._render_chunk_content_text("context", wrapped_text, file_path=str(chunk.get("filePath", "")))
                    else:
                        old_cell = self._render_chunk_content_text("meta", wrapped_text, file_path=str(chunk.get("filePath", "")))
                        new_cell = self._render_chunk_content_text("meta", wrapped_text, file_path=str(chunk.get("filePath", "")))
                    lines_table.add_row(
                        old_number,
                        old_cell,
                        new_number,
                        new_cell,
                        key=row_key,
                    )
                else:
                    lines_table.add_row(
                        old_number,
                        new_number,
                        self._render_chunk_kind_badge(kind),
                        content,
                        key=row_key,
                    )
            if previous_anchor_key and previous_anchor_key == anchor_key:
                selected_row_key = row_key_value
                self._selected_line_anchor = dict(self._chunk_line_anchor_by_row_key[row_key_value])

            line_comments = line_comment_map.get(anchor_key, [])
            for comment_index, line_comment in enumerate(line_comments):
                wrapped_comments = format_comment_lines(line_comment, max_width=110, max_lines=6)
                for wrapped_index, wrapped_line in enumerate(wrapped_comments):
                    if wrapped_index == 0:
                        comment_text = f"COMMENT: {wrapped_line}"
                    else:
                        comment_text = f"         {wrapped_line}"
                    if side_by_side:
                        lines_table.add_row(
                            "",
                            Text(""),
                            "",
                            self._render_chunk_content_text("line-comment", comment_text, file_path=str(chunk.get("filePath", ""))),
                            key=f"line-comment-{line_index}-{comment_index}-{wrapped_index}",
                        )
                    else:
                        lines_table.add_row(
                            "",
                            "",
                            self._render_chunk_kind_badge("line-comment"),
                            self._render_chunk_content_text("line-comment", comment_text, file_path=str(chunk.get("filePath", ""))),
                            key=f"line-comment-{line_index}-{comment_index}-{wrapped_index}",
                        )

        if selected_row_key:
            self._select_lines_row(selected_row_key)
        elif first_line_row_key:
            self._select_lines_row(first_line_row_key)
            self._selected_line_anchor = dict(self._chunk_line_anchor_by_row_key[first_line_row_key])
        self._update_chunk_meta(chunk_id)
        self._persist_document_state()


def launch_textual_viewer(
    doc: dict[str, Any],
    warnings: list[str],
    chunk_map: dict[str, Any],
    status_map: dict[str, str],
    page_size: int,
    source_path: Path,
    state_path: Path | None = None,
) -> int:
    app = DiffgrTextualApp(source_path, doc, warnings, chunk_map, status_map, page_size, state_path=state_path)
    app.run()
    return 0
