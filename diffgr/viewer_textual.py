from __future__ import annotations

import datetime as dt
import json
import re
import textwrap
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual import events
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static
from rich.text import Text
from .html_report import render_group_diff_html

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


def iso_utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def normalize_line_number(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def line_anchor_key(old_line: Any, new_line: Any, line_type: str) -> str:
    old_value = normalize_line_number(old_line)
    new_value = normalize_line_number(new_line)
    old_token = "" if old_value is None else str(old_value)
    new_token = "" if new_value is None else str(new_value)
    return f"{line_type}:{old_token}:{new_token}"


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
                line_comment.get("oldLine"),
                line_comment.get("newLine"),
                str(line_comment.get("lineType", "")),
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
            anchor = line_anchor_key(line.get("oldLine"), line.get("newLine"), kind)
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
    KEYMAP_REV = "km-20260223-1"

    CSS = """
    Screen { layout: vertical; }
    #topbar { height: 3; border: round #3a86ff; padding: 0 1; }
    #main { height: 1fr; }
    #left { width: 52%; border: round #4cc9f0; }
    #right { width: 48%; border: round #f72585; }
    #groups { height: 10; }
    #filter { height: 3; border: round #2ec4b6; margin: 1 1; }
    #chunks { height: 1fr; }
    #meta { height: 10; border: round #8338ec; padding: 0 1; }
    #lines { height: 1fr; }
    """

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
        Binding("m", "edit_comment", "Comment"),
        Binding("d", "toggle_group_report", "Diff Report"),
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
        Binding("[", "move_split_left", "Split <-"),
        Binding("]", "move_split_right", "Split ->"),
        Binding("ctrl+left", "move_split_left", "Split <-"),
        Binding("ctrl+right", "move_split_right", "Split ->"),
        Binding("alt+left", "move_diff_split_left", "Diff <-"),
        Binding("alt+right", "move_diff_split_right", "Diff ->"),
        Binding("s", "save", "Save"),
        Binding("h", "export_html", "Export HTML"),
    ]

    def __init__(
        self,
        source_path: Path,
        doc: dict[str, Any],
        warnings: list[str],
        chunk_map: dict[str, Any],
        status_map: dict[str, str],
        page_size: int,
    ) -> None:
        super().__init__()
        self.source_path = source_path
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
        self.group_report_mode = False
        self._lines_table_mode: str | None = None
        self.left_pane_pct = 52
        self.diff_old_ratio = 0.50
        self._group_report_row_chunk_by_key: dict[str, str] = {}
        self._chunk_line_anchor_by_row_key: dict[str, dict[str, Any]] = {}
        self._selected_line_anchor: dict[str, Any] | None = None
        self._suppress_chunk_table_events = False
        self._has_unsaved_changes = False
        self._last_saved_at: dt.datetime | None = None
        self._last_save_kind = "-"
        self._dmp_engine = diff_match_patch() if diff_match_patch is not None else None
        if self._dmp_engine is not None:
            self._dmp_engine.Diff_Timeout = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="topbar")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield DataTable(id="groups", cursor_type="row")
                yield Input(placeholder="Filter chunks by file/chunk/header/status...", id="filter")
                yield ChunkTable(id="chunks", cursor_type="row")
            with Vertical(id="right"):
                yield Static("Select a chunk from the left.", id="meta")
                yield DataTable(id="lines", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        group_table = self.query_one("#groups", DataTable)
        group_table.add_columns("name", "total", "pending", "reviewed", "ignored")
        chunk_table = self.query_one("#chunks", DataTable)
        chunk_table.add_columns("sel", "done", "status", "note", "chunk", "file", "old", "new", "header")
        self._switch_lines_table_mode("chunk")
        self._apply_main_split_widths()

        self._refresh_groups()
        self._apply_chunk_filter()
        self.query_one("#groups", DataTable).focus()
        self.set_interval(self.AUTOSAVE_INTERVAL_SEC, self._auto_save_tick)

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
        if self.group_report_mode:
            self._show_current_group_report(target_chunk_id=self.selected_chunk_id)
            self.notify("Group diff report: ON", timeout=1.2)
        else:
            if self.selected_chunk_id:
                self._show_chunk(self.selected_chunk_id)
            self.notify("Group diff report: OFF", timeout=1.2)
        self._refresh_topbar()

    def action_move_split_left(self) -> None:
        self._nudge_main_split(-self.SPLIT_STEP_PCT)

    def action_move_split_right(self) -> None:
        self._nudge_main_split(self.SPLIT_STEP_PCT)

    def action_move_diff_split_left(self) -> None:
        self._nudge_diff_split(-self.DIFF_RATIO_STEP)

    def action_move_diff_split_right(self) -> None:
        self._nudge_diff_split(self.DIFF_RATIO_STEP)

    def _clamp_left_pane_pct(self, value: int) -> int:
        return max(self.MIN_LEFT_PANE_PCT, min(self.MAX_LEFT_PANE_PCT, value))

    def _apply_main_split_widths(self) -> None:
        self.left_pane_pct = self._clamp_left_pane_pct(self.left_pane_pct)
        right_pane_pct = 100 - self.left_pane_pct
        left_pane = self.query_one("#left", Vertical)
        right_pane = self.query_one("#right", Vertical)
        left_pane.styles.width = f"{self.left_pane_pct}%"
        right_pane.styles.width = f"{right_pane_pct}%"

    def _nudge_main_split(self, delta_pct: int) -> None:
        next_pct = self._clamp_left_pane_pct(self.left_pane_pct + delta_pct)
        if next_pct == self.left_pane_pct:
            return
        self.left_pane_pct = next_pct
        self._apply_main_split_widths()
        if self.group_report_mode:
            self._show_current_group_report(target_chunk_id=self.selected_chunk_id)
        self._refresh_topbar()

    def _clamp_diff_old_ratio(self, value: float) -> float:
        return max(self.MIN_DIFF_OLD_RATIO, min(self.MAX_DIFF_OLD_RATIO, value))

    def _nudge_diff_split(self, delta: float) -> None:
        next_ratio = self._clamp_diff_old_ratio(self.diff_old_ratio + delta)
        if abs(next_ratio - self.diff_old_ratio) < 1e-9:
            return
        self.diff_old_ratio = next_ratio
        if self.group_report_mode:
            self._show_current_group_report(target_chunk_id=self.selected_chunk_id)
        self._refresh_topbar()

    def _group_report_text_widths(self, total_width: int | None = None) -> tuple[int, int]:
        if total_width is None:
            total_width = int(self.size.width)
        total_width = max(80, total_width)
        right_pane_pct = max(1, 100 - self.left_pane_pct)
        right_width = max(36, int(total_width * (right_pane_pct / 100.0)))
        available = max(28, right_width - 16)
        old_width = int(round(available * self.diff_old_ratio))
        old_width = max(12, min(available - 12, old_width))
        new_width = max(12, available - old_width)
        return old_width, new_width

    def _switch_lines_table_mode(self, mode: str) -> DataTable:
        lines_table = self.query_one("#lines", DataTable)
        expected_column_count = 4
        has_expected_columns = len(lines_table.ordered_columns) == expected_column_count
        if self._lines_table_mode != mode or not has_expected_columns:
            lines_table.clear(columns=True)
            if mode == "group_report":
                old_width, new_width = self._group_report_text_widths()
                lines_table.add_column("old#", width=5)
                lines_table.add_column("old", width=old_width)
                lines_table.add_column("new#", width=5)
                lines_table.add_column("new", width=new_width)
            else:
                lines_table.add_columns("old", "new", "kind", "content")
            self._lines_table_mode = mode
        else:
            lines_table.clear(columns=False)
        return lines_table

    def _render_report_number(self, value: str, row_type: str, side: str, selected: bool = False) -> Text:
        if selected:
            return Text(value, style="bold #13231a on #aef2be")
        style = "dim #91a2bb"
        if row_type == "add" and side == "new":
            style = "bold #1f8f49"
        elif row_type == "delete" and side == "old":
            style = "bold #c63e51"
        elif row_type == "comment":
            style = "bold #c8b75b"
        return Text(value, style=style)

    def _render_report_text(self, value: str, row_type: str, side: str, selected: bool = False) -> Text:
        if selected:
            return Text(value, style="bold #13231a on #aef2be")
        if row_type == "file_border":
            return Text(value, style="bold #8fb4ff on #11213a")
        if row_type == "file":
            return Text(value, style="bold #09111d on #8fb4ff")
        if row_type == "chunk":
            if side == "new":
                return Text(value, style="bold #cddfff on #1a2f54")
            return Text(value, style="bold #bcd7ff on #1a2f54")
        if row_type == "add":
            if side == "new":
                return Text(value, style="bold #02170c on #92f2ae")
            return Text(value, style="dim #47715a")
        if row_type == "delete":
            if side == "old":
                return Text(value, style="bold #200307 on #ffb3bb")
            return Text(value, style="dim #84575c")
        if row_type == "context":
            return Text(value, style="#c7d4e8")
        if row_type == "comment":
            if side == "new":
                return Text(value, style="bold #1e1a06 on #ffe7a1")
            return Text(value, style="dim #7a7360")
        if row_type == "meta":
            return Text(value, style="italic #9db0c8")
        if row_type == "spacer":
            return Text("", style="#0b0f16")
        if row_type == "info":
            return Text(value, style="italic #9db0c8")
        return Text(value, style="#c7d4e8")

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
            "add": "bold #072010 on #92f2ae",
            "delete": "bold #2a030a on #ffb3bb",
            "meta": "bold #d6e0f2 on #33405a",
            "comment": "bold #2d2004 on #ffe7a1",
            "line-comment": "bold #2d2004 on #ffe7a1",
        }.get(kind, "bold #d3deee on #2d3e5c")
        return Text(f" {label} ", style=style)

    def _render_chunk_content_text(self, kind: str, text: str, *, pair_text: str | None = None) -> Text:
        prefix = {
            "context": "  ",
            "add": "+ ",
            "delete": "- ",
            "meta": "\\ ",
            "comment": "! ",
            "line-comment": "! ",
        }.get(kind, "? ")
        base_style = {
            "context": "#c7d4e8",
            "add": "bold #c4f8d1",
            "delete": "bold #ffd3d7",
            "meta": "italic #9db0c8",
            "comment": "bold #f3e6b3",
            "line-comment": "bold #f3e6b3",
        }.get(kind, "#c7d4e8")
        rendered = Text(prefix + text, style=base_style)
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
                        rendered.stylize("bold #300008 on #ff93a0", prefix_len + old_pos, prefix_len + old_pos + seg_len)
                        applied_by_dmp = True
                    old_pos += seg_len
                    continue
                if op > 0:
                    if kind == "add":
                        rendered.stylize("bold #01150a on #69d28f", prefix_len + new_pos, prefix_len + new_pos + seg_len)
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
                    rendered.stylize("bold #01150a on #69d28f", prefix_len + new_start, prefix_len + new_end)
            else:
                if old_end > old_start:
                    rendered.stylize("bold #300008 on #ff93a0", prefix_len + old_start, prefix_len + old_end)
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
            key = line_anchor_key(item.get("oldLine"), item.get("newLine"), str(item.get("lineType", "")))
            line_comment_map.setdefault(key, []).append(str(item.get("comment", "")))
        return line_comment_map

    def _line_comment_for_anchor(self, chunk_id: str, old_line: Any, new_line: Any, line_type: str) -> str:
        key = line_anchor_key(old_line, new_line, line_type)
        comments = self._line_comment_map_for_chunk(chunk_id).get(key, [])
        return comments[0].strip() if comments else ""

    def _line_comment_count_for_chunk(self, chunk_id: str) -> int:
        return len(self._line_comments_for_chunk(chunk_id))

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
        target_anchor_key = line_anchor_key(old_line, new_line, line_type)
        kept: list[dict[str, Any]] = []
        for item in existing:
            if not isinstance(item, dict):
                continue
            item_comment = str(item.get("comment", "")).strip()
            if not item_comment:
                continue
            item_key = line_anchor_key(item.get("oldLine"), item.get("newLine"), str(item.get("lineType", "")))
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
        self._refresh_topbar()

    def action_clear_chunk_multi_selection(self) -> None:
        if not self.selected_chunk_id:
            self.selected_chunk_ids = set()
            self._chunk_selection_anchor_index = None
            self._refresh_chunk_selection_markers()
            self._refresh_topbar()
            return
        self.selected_chunk_ids = {self.selected_chunk_id}
        self._set_chunk_selection_anchor_from_current()
        self._refresh_chunk_selection_markers()
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

            html = render_group_diff_html(self.doc, group_selector=selector, report_title=None)
            output_path.write_text(html, encoding="utf-8")
            self.notify(f"HTML exported: {output_path}", timeout=2.8)
        except Exception as error:  # noqa: BLE001
            self.notify(f"HTML export failed: {error}", severity="error", timeout=3.2)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "filter":
            return
        self.filter_text = event.value.strip().lower()
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
            self._apply_chunk_filter()
            return
        if event.data_table.id == "chunks":
            if self._suppress_chunk_table_events:
                return
            if event.row_key.value is None:
                return
            chunk_id = str(event.row_key.value)
            self._set_single_chunk_selection(chunk_id)
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
        if self.group_report_mode:
            self._show_current_group_report(target_chunk_id=chunk_id)
        else:
            self._show_chunk(chunk_id)

    def _compute_group_metrics(self, group_id: str) -> dict[str, int]:
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
        return {"total": len(chunk_ids), "pending": pending, "reviewed": reviewed, "ignored": ignored}

    def _assigned_chunk_ids(self) -> set[str]:
        assigned: set[str] = set()
        for values in self.doc.get("assignments", {}).values():
            if isinstance(values, list):
                assigned.update(values)
        return assigned

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
            group_table.add_row(
                row.name,
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

    def _save_document(self, *, auto: bool, force: bool) -> bool:
        if not force and not self._has_unsaved_changes:
            return False
        try:
            backup = self.source_path.with_suffix(self.source_path.suffix + ".bak")
            if not backup.exists():
                backup.write_text(self.source_path.read_text(encoding="utf-8"), encoding="utf-8")
            self.source_path.write_text(json.dumps(self.doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._has_unsaved_changes = False
            self._last_saved_at = dt.datetime.now()
            self._last_save_kind = "auto" if auto else "manual"
            self._refresh_topbar_safe()
            if auto:
                self._safe_notify(f"Auto-saved: {self.source_path.name}", timeout=0.9)
            else:
                self._safe_notify(f"Saved: {self.source_path}", timeout=1.5)
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
        warnings_text = f"warnings={len(self.warnings)}"
        filter_display = self.filter_text if self.filter_text else "none"
        text = (
            f"[b]{title}[/b]  "
            f"group={group_name}  "
            f"cur(total={m_cur['total']} pending={m_cur['pending']} reviewed={m_cur['reviewed']} rate={cur_rate:.1f}%)  "
            f"all(total={m_all['total']} pending={m_all['pending']} reviewed={m_all['reviewed']} rate={all_rate:.1f}%)  "
            f"selected={selected_count}  "
            f"{save_state}  "
            f"autosave={self.AUTOSAVE_INTERVAL_SEC}s  "
            f"{self.KEYMAP_REV}  "
            f"split={self.left_pane_pct}:{100 - self.left_pane_pct}  "
            f"diff={self.diff_old_ratio * 100:.0f}:{(1 - self.diff_old_ratio) * 100:.0f}  "
            f"view={'group-diff' if self.group_report_mode else 'chunk'}  "
            f"{warnings_text}  filter={filter_display}  "
            f"[dim]keys: n/e=group, a/u=assign, l=lines, m=comment(line/chunk), d=report, h=html, 1-4=status, Shift+Up/Down or j/k=range-select, Space=toggle done<->undone, Shift+Space=done(reviewed), Backspace or 1=undone(unreviewed), x=toggle-select, Ctrl+A=select-all, Esc=clear-select, [ ]/Ctrl+Arrows=split, Alt+Arrows=diff, s=save[/dim]"
        )
        self.query_one("#topbar", Static).update(text)

    def _reviewed_rate(self, metrics: dict[str, int]) -> float:
        total = int(metrics.get("total", 0))
        if total <= 0:
            return 0.0
        reviewed = int(metrics.get("reviewed", 0))
        return (reviewed / total) * 100.0

    def _done_checkbox_for_status(self, status: str) -> str:
        return "[x]" if status == "reviewed" else "[ ]"

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

    def _visible_chunks_for_report(self) -> list[dict[str, Any]]:
        return [self.chunk_map[cid] for cid in self.filtered_chunk_ids if cid in self.chunk_map]

    def _groups_for_chunk(self, chunk_id: str) -> list[str]:
        labels: list[str] = []
        assignments = self.doc.get("assignments", {})
        if isinstance(assignments, dict):
            for group_id, chunk_ids in assignments.items():
                if isinstance(chunk_ids, list) and chunk_id in chunk_ids:
                    labels.append(self._group_display_name(str(group_id)))
        return sorted(set(labels))

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
                    f"[b]selected chunk[/b] {selected_summary}",
                    f"[b]comment[/b] {selected_comment}",
                    f"[b]line comments[/b] {selected_line_comment_count}",
                    f"[b]scope[/b] chunk-level assignment (line-level ownership is not tracked)",
                    "[dim]Press [b]d[/b] to return to single-chunk view.[/dim]",
                ]
            )
        )

        lines_table = self._switch_lines_table_mode("group_report")
        rows = build_group_diff_report_rows(chunks_for_view)
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
        status = self.status_map.get(chunk_id, "unreviewed")
        group_name = self._group_display_name(self.current_group_id)
        assigned_groups = self._groups_for_chunk(chunk_id)
        file_path = str(chunk.get("filePath", "-"))

        meta_lines = [
            f"[b]group[/b] {group_name}",
            f"[b]chunk[/b] {chunk_id}",
            f"[b]status[/b] {status}",
            f"[b]comment[/b] {self._comment_for_chunk(chunk_id) or '(none)'}",
            f"[b]line comments[/b] {self._line_comment_count_for_chunk(chunk_id)}",
            f"[b]file[/b] {format_file_label(file_path)}",
            f"[b]path[/b] {file_path}",
            f"[b]old[/b] {chunk.get('old', {})}",
            f"[b]new[/b] {chunk.get('new', {})}",
            f"[b]header[/b] {chunk.get('header', '')}",
            f"[b]assigned groups[/b] {', '.join(assigned_groups) if assigned_groups else '(none)'}",
            f"[b]scope[/b] chunk-level assignment (line-level ownership is not tracked)",
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

    def _show_chunk(self, chunk_id: str) -> None:
        chunk = self.chunk_map.get(chunk_id)
        if chunk is None:
            return
        previous_anchor_key = ""
        if self._selected_line_anchor:
            previous_anchor_key = str(self._selected_line_anchor.get("anchorKey", ""))
        self._chunk_line_anchor_by_row_key = {}
        self._selected_line_anchor = None

        lines_table = self._switch_lines_table_mode("chunk")
        comment_lines = format_comment_lines(self._comment_for_chunk(chunk_id), max_width=110, max_lines=10)
        if comment_lines:
            for index, comment_line in enumerate(comment_lines):
                if index == 0:
                    text = f"COMMENT: {comment_line}"
                else:
                    text = f"         {comment_line}"
                lines_table.add_row(
                    "",
                    "",
                    self._render_chunk_kind_badge("comment"),
                    self._render_chunk_content_text("comment", text),
                    key=f"chunk-comment-{index}",
                )
            lines_table.add_row("", "", self._render_chunk_kind_badge("meta"), Text(""), key="chunk-comment-sep")

        line_comment_map = self._line_comment_map_for_chunk(chunk_id)
        lines = list(chunk.get("lines", [])[: max(200, self.page_size * 30)])
        pair_map = self._build_intraline_pair_map(lines)
        selected_row_key: str | None = None
        first_line_row_key: str | None = None
        for line_index, line in enumerate(lines):
            kind = line.get("kind", "")
            old_line = normalize_line_number(line.get("oldLine"))
            new_line = normalize_line_number(line.get("newLine"))
            anchor_key = line_anchor_key(old_line, new_line, str(kind))
            row_key_value = f"line-{line_index}"
            if first_line_row_key is None:
                first_line_row_key = row_key_value
            self._chunk_line_anchor_by_row_key[row_key_value] = {
                "anchorKey": anchor_key,
                "oldLine": old_line,
                "newLine": new_line,
                "lineType": str(kind),
            }
            content = self._render_chunk_content_text(
                str(kind),
                str(line.get("text", "")),
                pair_text=pair_map.get(line_index),
            )
            lines_table.add_row(
                "" if line.get("oldLine") is None else str(line.get("oldLine")),
                "" if line.get("newLine") is None else str(line.get("newLine")),
                self._render_chunk_kind_badge(str(kind)),
                content,
                key=row_key_value,
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
                    lines_table.add_row(
                        "",
                        "",
                        self._render_chunk_kind_badge("line-comment"),
                        self._render_chunk_content_text("line-comment", comment_text),
                        key=f"line-comment-{line_index}-{comment_index}-{wrapped_index}",
                    )

        if selected_row_key:
            self._select_lines_row(selected_row_key)
        elif first_line_row_key:
            self._select_lines_row(first_line_row_key)
            self._selected_line_anchor = dict(self._chunk_line_anchor_by_row_key[first_line_row_key])
        self._update_chunk_meta(chunk_id)


def launch_textual_viewer(
    doc: dict[str, Any],
    warnings: list[str],
    chunk_map: dict[str, Any],
    status_map: dict[str, str],
    page_size: int,
    source_path: Path,
) -> int:
    app = DiffgrTextualApp(source_path, doc, warnings, chunk_map, status_map, page_size)
    app.run()
    return 0
