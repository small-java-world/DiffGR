from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static
from rich.text import Text
from .html_report import render_group_diff_html


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

    current_file = ""
    for chunk in chunks:
        file_path = str(chunk.get("filePath", "-"))
        file_label = format_file_label(file_path)
        if file_path != current_file:
            if rows:
                rows.append(GroupReportRow(row_type="spacer", old_line="", old_text="", new_line="", new_text=""))
            current_file = file_path
            rows.append(
                GroupReportRow(
                    row_type="file",
                    old_line="",
                    old_text=f"=== {file_label} ===",
                    new_line="",
                    new_text=f"path: {file_path}",
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

    def __init__(self, title: str, placeholder: str, initial: str = "") -> None:
        super().__init__()
        self.dialog_title = title
        self.placeholder = placeholder
        self.initial = initial

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
        value = self.query_one("#name_input", Input).value.strip()
        self.dismiss(value if value else None)


class DiffgrTextualApp(App[None]):
    MIN_LEFT_PANE_PCT = 28
    MAX_LEFT_PANE_PCT = 72
    SPLIT_STEP_PCT = 4
    MIN_DIFF_OLD_RATIO = 0.25
    MAX_DIFF_OLD_RATIO = 0.75
    DIFF_RATIO_STEP = 0.05

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
        Binding("n", "new_group", "New Group"),
        Binding("e", "rename_group", "Rename Group"),
        Binding("a", "assign_chunk", "Assign"),
        Binding("u", "unassign_chunk", "Unassign"),
        Binding("d", "toggle_group_report", "Diff Report"),
        Binding("1", "set_status('unreviewed')", "Unreviewed"),
        Binding("2", "set_status('reviewed')", "Reviewed"),
        Binding("3", "set_status('needsReReview')", "ReReview"),
        Binding("4", "set_status('ignored')", "Ignored"),
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
        self.group_report_mode = False
        self._lines_table_mode: str | None = None
        self.left_pane_pct = 52
        self.diff_old_ratio = 0.50

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="topbar")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield DataTable(id="groups", cursor_type="row")
                yield Input(placeholder="Filter chunks by file/chunk/header/status...", id="filter")
                yield DataTable(id="chunks", cursor_type="row")
            with Vertical(id="right"):
                yield Static("Select a chunk from the left.", id="meta")
                yield DataTable(id="lines", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        group_table = self.query_one("#groups", DataTable)
        group_table.add_columns("name", "total", "pending", "reviewed", "ignored")
        chunk_table = self.query_one("#chunks", DataTable)
        chunk_table.add_columns("status", "chunk", "file", "old", "new", "header")
        self._switch_lines_table_mode("chunk")
        self._apply_main_split_widths()

        self._refresh_groups()
        self._apply_chunk_filter()
        self.query_one("#groups", DataTable).focus()

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

    def action_toggle_group_report(self) -> None:
        self.group_report_mode = not self.group_report_mode
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
        return Text(value, style=style)

    def _render_report_text(self, value: str, row_type: str, side: str, selected: bool = False) -> Text:
        if selected:
            return Text(value, style="bold #13231a on #aef2be")
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
        if row_type == "meta":
            return Text(value, style="italic #9db0c8")
        if row_type == "spacer":
            return Text("", style="#0b0f16")
        if row_type == "info":
            return Text(value, style="italic #9db0c8")
        return Text(value, style="#c7d4e8")

    async def action_new_group(self) -> None:
        result = await self.push_screen_wait(NameModal("New Group (Japanese name OK)", "例: 認証周り / UI調整 / PR3…"))
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
        self.current_group_id = new_id
        self._refresh_groups(select_group_id=new_id)
        self._apply_chunk_filter()

    async def action_rename_group(self) -> None:
        if self.current_group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return
        groups = self.doc.get("groups", [])
        current = next((g for g in groups if isinstance(g, dict) and g.get("id") == self.current_group_id), None)
        if not current:
            return
        current_name = str(current.get("name", ""))
        result = await self.push_screen_wait(NameModal("Rename Group", "新しい名前（日本語OK）", initial=current_name))
        if not result:
            return
        current["name"] = result
        self._refresh_groups(select_group_id=self.current_group_id)

    def action_assign_chunk(self) -> None:
        if self.current_group_id in {PSEUDO_ALL, PSEUDO_UNASSIGNED}:
            return
        if not self.selected_chunk_id:
            return
        chunk_id = self.selected_chunk_id
        assignments: dict[str, Any] = self.doc.setdefault("assignments", {})

        # Remove from any group first (enforce at-most-one-group behavior).
        for group_id, items in assignments.items():
            if isinstance(items, list) and chunk_id in items:
                items[:] = [c for c in items if c != chunk_id]

        target = assignments.setdefault(self.current_group_id, [])
        if isinstance(target, list) and chunk_id not in target:
            target.append(chunk_id)

        self._refresh_groups(select_group_id=self.current_group_id)
        self._apply_chunk_filter(keep_selection=True)

    def action_unassign_chunk(self) -> None:
        if not self.selected_chunk_id:
            return
        chunk_id = self.selected_chunk_id
        assignments: dict[str, Any] = self.doc.setdefault("assignments", {})
        for group_id, items in assignments.items():
            if isinstance(items, list) and chunk_id in items:
                items[:] = [c for c in items if c != chunk_id]
        self._refresh_groups(select_group_id=self.current_group_id)
        self._apply_chunk_filter(keep_selection=True)

    def action_set_status(self, status: str) -> None:
        if not self.selected_chunk_id:
            return
        if status not in {"unreviewed", "reviewed", "ignored", "needsReReview"}:
            return
        chunk_id = self.selected_chunk_id
        reviews: dict[str, Any] = self.doc.setdefault("reviews", {})
        record = reviews.get(chunk_id, {})
        if not isinstance(record, dict):
            record = {}
        record["status"] = status
        if status == "reviewed":
            record["reviewedAt"] = iso_utc_now()
        reviews[chunk_id] = record
        self.status_map[chunk_id] = status
        self._refresh_groups(select_group_id=self.current_group_id)
        self._apply_chunk_filter(keep_selection=True)
        self._show_chunk(chunk_id)

    def action_save(self) -> None:
        try:
            backup = self.source_path.with_suffix(self.source_path.suffix + ".bak")
            if not backup.exists():
                backup.write_text(self.source_path.read_text(encoding="utf-8"), encoding="utf-8")
            self.source_path.write_text(json.dumps(self.doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.notify(f"Saved: {self.source_path}", timeout=1.5)
        except Exception as error:  # noqa: BLE001
            self.notify(f"Save failed: {error}", severity="error", timeout=3.0)

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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "groups":
            group_id = str(event.row_key.value)
            self.current_group_id = group_id
            self._apply_chunk_filter()
            return
        if event.data_table.id == "chunks":
            if event.row_key.value is None:
                return
            chunk_id = str(event.row_key.value)
            self.selected_chunk_id = chunk_id
            if self.group_report_mode:
                self._show_current_group_report(target_chunk_id=chunk_id)
            else:
                self._show_chunk(chunk_id)
            return

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "chunks":
            return
        if event.row_key.value is None:
            return
        chunk_id = str(event.row_key.value)
        if chunk_id == self.selected_chunk_id:
            return
        self.selected_chunk_id = chunk_id
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

    def _refresh_topbar(self) -> None:
        title = str(self.doc.get("meta", {}).get("title", "-"))
        group_name = self._group_display_name(self.current_group_id)
        m_all = self._compute_group_metrics(PSEUDO_ALL)
        m_cur = self._compute_group_metrics(self.current_group_id)
        warnings_text = f"warnings={len(self.warnings)}"
        filter_display = self.filter_text if self.filter_text else "none"
        text = (
            f"[b]{title}[/b]  "
            f"group={group_name}  "
            f"cur(total={m_cur['total']} pending={m_cur['pending']} reviewed={m_cur['reviewed']})  "
            f"all(total={m_all['total']} pending={m_all['pending']} reviewed={m_all['reviewed']})  "
            f"split={self.left_pane_pct}:{100 - self.left_pane_pct}  "
            f"diff={self.diff_old_ratio * 100:.0f}:{(1 - self.diff_old_ratio) * 100:.0f}  "
            f"view={'group-diff' if self.group_report_mode else 'chunk'}  "
            f"{warnings_text}  filter={filter_display}  "
            f"[dim]keys: n/e=group, a/u=assign, d=report, h=html, 1-4=status, [ ]/Ctrl+Arrows=split, Alt+Arrows=diff, s=save[/dim]"
        )
        self.query_one("#topbar", Static).update(text)

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
        haystack = " ".join([chunk["id"], chunk.get("filePath", ""), header, status]).lower()
        return self.filter_text in haystack

    def _apply_chunk_filter(self, keep_selection: bool = False) -> None:
        chunk_table = self.query_one("#chunks", DataTable)
        chunk_table.clear(columns=False)
        self.filtered_chunk_ids = []

        chunks = [c for c in self._chunks_for_current_group() if self._matches_filter(c)]
        for chunk in chunks:
            chunk_id = chunk["id"]
            self.filtered_chunk_ids.append(chunk_id)
            status = self.status_map.get(chunk_id, "unreviewed")
            chunk_table.add_row(
                status,
                chunk_id[:12],
                format_file_label(str(chunk.get("filePath", "-"))),
                f"{chunk.get('old', {}).get('start', '?')},{chunk.get('old', {}).get('count', '?')}",
                f"{chunk.get('new', {}).get('start', '?')},{chunk.get('new', {}).get('count', '?')}",
                str(chunk.get("header", "")),
                key=chunk_id,
            )

        self._refresh_topbar()

        if self.group_report_mode:
            if self.filtered_chunk_ids and (self.selected_chunk_id not in self.filtered_chunk_ids):
                self.selected_chunk_id = self.filtered_chunk_ids[0]
                self._select_chunk_row(self.selected_chunk_id)
            self._show_current_group_report(target_chunk_id=self.selected_chunk_id)
            return

        if keep_selection and self.selected_chunk_id in self.filtered_chunk_ids:
            self._select_chunk_row(self.selected_chunk_id)
            return
        if self.filtered_chunk_ids:
            first = self.filtered_chunk_ids[0]
            self.selected_chunk_id = first
            self._select_chunk_row(first)
            self._show_chunk(first)
        else:
            self.selected_chunk_id = None
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
            chunk_view["_assignedGroups"] = self._groups_for_chunk(str(chunk.get("id", "")))
            chunks_for_view.append(chunk_view)
        file_count = len({str(chunk.get("filePath", "")) for chunk in chunks})
        selected_summary = "-"
        if target_chunk_id and target_chunk_id in self.chunk_map:
            selected_chunk = self.chunk_map[target_chunk_id]
            selected_summary = (
                f"{target_chunk_id[:12]} "
                f"{format_file_label(str(selected_chunk.get('filePath', '-')))}"
            )
        self.query_one("#meta", Static).update(
            "\n".join(
                [
                    f"[b]group[/b] {group_name}",
                    f"[b]mode[/b] group diff report",
                    f"[b]chunks[/b] {len(chunks)}",
                    f"[b]files[/b] {file_count}",
                    f"[b]selected chunk[/b] {selected_summary}",
                    f"[b]scope[/b] chunk-level assignment (line-level ownership is not tracked)",
                    "[dim]Press [b]d[/b] to return to single-chunk view.[/dim]",
                ]
            )
        )

        lines_table = self._switch_lines_table_mode("group_report")
        rows = build_group_diff_report_rows(chunks_for_view)
        target_row_index: int | None = None
        for row_index, row in enumerate(rows):
            is_selected = bool(target_chunk_id and row.chunk_id == target_chunk_id and row.row_type == "chunk")
            old_text = row.old_text
            new_text = row.new_text
            if is_selected:
                old_text = f">> {old_text}"
                new_text = f">> {new_text}" if new_text else ">>"
            lines_table.add_row(
                self._render_report_number(row.old_line, row.row_type, "old", selected=is_selected),
                self._render_report_text(old_text, row.row_type, "old", selected=is_selected),
                self._render_report_number(row.new_line, row.row_type, "new", selected=is_selected),
                self._render_report_text(new_text, row.row_type, "new", selected=is_selected),
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

    def _select_chunk_row(self, chunk_id: str) -> None:
        chunk_table = self.query_one("#chunks", DataTable)
        try:
            for row_index, row_key in enumerate(chunk_table.rows.keys()):
                if str(row_key.value) == chunk_id:
                    chunk_table.cursor_coordinate = (row_index, 0)
                    break
        except Exception:
            pass

    def _show_chunk(self, chunk_id: str) -> None:
        chunk = self.chunk_map.get(chunk_id)
        if chunk is None:
            return
        status = self.status_map.get(chunk_id, "unreviewed")
        group_name = self._group_display_name(self.current_group_id)
        assigned_groups = self._groups_for_chunk(chunk_id)
        file_path = str(chunk.get("filePath", "-"))
        meta_lines = [
            f"[b]group[/b] {group_name}",
            f"[b]chunk[/b] {chunk_id}",
            f"[b]status[/b] {status}",
            f"[b]file[/b] {format_file_label(file_path)}",
            f"[b]path[/b] {file_path}",
            f"[b]old[/b] {chunk.get('old', {})}",
            f"[b]new[/b] {chunk.get('new', {})}",
            f"[b]header[/b] {chunk.get('header', '')}",
            f"[b]assigned groups[/b] {', '.join(assigned_groups) if assigned_groups else '(none)'}",
            f"[b]scope[/b] chunk-level assignment (line-level ownership is not tracked)",
        ]
        self.query_one("#meta", Static).update("\n".join(meta_lines))

        lines_table = self._switch_lines_table_mode("chunk")
        for line in chunk.get("lines", [])[: max(200, self.page_size * 30)]:
            kind = line.get("kind", "")
            prefix = {"context": " ", "add": "+", "delete": "-", "meta": "\\"}.get(kind, "?")
            content = f"{prefix}{line.get('text', '')}"
            lines_table.add_row(
                "" if line.get("oldLine") is None else str(line.get("oldLine")),
                "" if line.get("newLine") is None else str(line.get("newLine")),
                kind,
                content,
            )


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
