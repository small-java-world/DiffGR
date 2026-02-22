from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static


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


@dataclass(frozen=True)
class GroupRow:
    group_id: str
    name: str


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
        Binding("1", "set_status('unreviewed')", "Unreviewed"),
        Binding("2", "set_status('reviewed')", "Reviewed"),
        Binding("3", "set_status('needsReReview')", "ReReview"),
        Binding("4", "set_status('ignored')", "Ignored"),
        Binding("s", "save", "Save"),
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
        chunk_table.add_columns("status", "chunk", "filePath", "old", "new", "header")
        lines_table = self.query_one("#lines", DataTable)
        lines_table.add_columns("old", "new", "kind", "content")

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
            chunk_id = str(event.row_key.value)
            self.selected_chunk_id = chunk_id
            self._show_chunk(chunk_id)
            return

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
            f"{warnings_text}  filter={filter_display}  "
            f"[dim]keys: n/e=a group, a/u=assign, 1-4=status, s=save[/dim]"
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
                chunk.get("filePath", "-"),
                f"{chunk.get('old', {}).get('start', '?')},{chunk.get('old', {}).get('count', '?')}",
                f"{chunk.get('new', {}).get('start', '?')},{chunk.get('new', {}).get('count', '?')}",
                str(chunk.get("header", "")),
                key=chunk_id,
            )

        self._refresh_topbar()

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
        meta_lines = [
            f"[b]group[/b] {group_name}",
            f"[b]chunk[/b] {chunk_id}",
            f"[b]status[/b] {status}",
            f"[b]file[/b] {chunk.get('filePath', '-')}",
            f"[b]old[/b] {chunk.get('old', {})}",
            f"[b]new[/b] {chunk.get('new', {})}",
            f"[b]header[/b] {chunk.get('header', '')}",
        ]
        self.query_one("#meta", Static).update("\n".join(meta_lines))

        lines_table = self.query_one("#lines", DataTable)
        lines_table.clear(columns=False)
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
