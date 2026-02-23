import asyncio
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffgr.viewer_textual import DiffgrTextualApp, build_group_diff_report_rows, format_file_label, normalize_editor_mode
from textual.widgets import DataTable


def make_chunk(
    *,
    chunk_id: str,
    file_path: str,
    old_start: int,
    old_count: int,
    new_start: int,
    new_count: int,
    header: str,
    lines: list[dict],
) -> dict:
    return {
        "id": chunk_id,
        "filePath": file_path,
        "old": {"start": old_start, "count": old_count},
        "new": {"start": new_start, "count": new_count},
        "header": header,
        "lines": lines,
    }


class TestViewerTextualReport(unittest.TestCase):
    def _make_key_test_app(self, *, initial_status: str = "unreviewed") -> tuple[DiffgrTextualApp, dict[str, str]]:
        doc = {"groups": [], "assignments": {}, "meta": {"title": "KeyTest"}, "reviews": {}}
        chunk_map = {
            "c1": {
                "id": "c1",
                "filePath": "src/a.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 1},
                "header": "h1",
                "lines": [],
            },
            "c2": {
                "id": "c2",
                "filePath": "src/a.ts",
                "old": {"start": 2, "count": 1},
                "new": {"start": 2, "count": 1},
                "header": "h2",
                "lines": [],
            },
            "c3": {
                "id": "c3",
                "filePath": "src/a.ts",
                "old": {"start": 3, "count": 1},
                "new": {"start": 3, "count": 1},
                "header": "h3",
                "lines": [],
            },
        }
        status_map = {chunk_id: initial_status for chunk_id in chunk_map}
        app = DiffgrTextualApp(Path("dummy.diffgr.json"), doc, [], chunk_map, status_map, 15)
        return app, status_map

    def _cell_text(self, value: object) -> str:
        if hasattr(value, "plain"):
            return str(getattr(value, "plain"))
        return str(value)

    def test_space_key_marks_done_in_runtime_and_updates_done_column(self):
        app, status_map = self._make_key_test_app(initial_status="unreviewed")
        done_cell = ""

        async def _run() -> None:
            nonlocal done_cell
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.press("space")
                await pilot.pause()
                table = app.query_one("#chunks", DataTable)
                done_cell = self._cell_text(table.get_cell_at((0, 1)))

        asyncio.run(_run())
        self.assertEqual(status_map["c1"], "reviewed")
        self.assertEqual(done_cell, "[✅]")

    def test_shift_space_key_marks_done_in_runtime(self):
        app, status_map = self._make_key_test_app(initial_status="unreviewed")

        async def _run() -> None:
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.press("shift+space")
                await pilot.pause()

        asyncio.run(_run())
        self.assertEqual(status_map["c1"], "reviewed")

    def test_space_key_toggles_done_to_undone_in_runtime(self):
        app, status_map = self._make_key_test_app(initial_status="reviewed")

        async def _run() -> None:
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.press("space")
                await pilot.pause()

        asyncio.run(_run())
        self.assertEqual(status_map["c1"], "unreviewed")

    def test_shift_space_key_keeps_done_when_already_done_in_runtime(self):
        app, status_map = self._make_key_test_app(initial_status="reviewed")

        async def _run() -> None:
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.press("shift+space")
                await pilot.pause()

        asyncio.run(_run())
        self.assertEqual(status_map["c1"], "reviewed")

    def test_backspace_key_marks_undone_in_runtime(self):
        app, status_map = self._make_key_test_app(initial_status="reviewed")
        done_cell = ""

        async def _run() -> None:
            nonlocal done_cell
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.press("backspace")
                await pilot.pause()
                table = app.query_one("#chunks", DataTable)
                done_cell = self._cell_text(table.get_cell_at((0, 1)))

        asyncio.run(_run())
        self.assertEqual(status_map["c1"], "unreviewed")
        self.assertEqual(done_cell, "[  ]")

    def test_space_marks_selected_range_done_in_runtime(self):
        app, status_map = self._make_key_test_app(initial_status="unreviewed")

        async def _run() -> None:
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.press("down")
                await pilot.press("j")
                await pilot.press("space")
                await pilot.pause()

        asyncio.run(_run())
        self.assertEqual(status_map["c1"], "unreviewed")
        self.assertEqual(status_map["c2"], "reviewed")
        self.assertEqual(status_map["c3"], "reviewed")

    def test_space_toggles_selected_range_to_undone_in_runtime(self):
        app, status_map = self._make_key_test_app(initial_status="reviewed")

        async def _run() -> None:
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.press("down")
                await pilot.press("j")
                await pilot.press("space")
                await pilot.pause()

        asyncio.run(_run())
        self.assertEqual(status_map["c1"], "reviewed")
        self.assertEqual(status_map["c2"], "unreviewed")
        self.assertEqual(status_map["c3"], "unreviewed")

    def test_space_marks_done_even_when_lines_table_is_focused(self):
        app, status_map = self._make_key_test_app(initial_status="unreviewed")

        async def _run() -> None:
            async with app.run_test() as pilot:
                await pilot.press("l")
                await pilot.press("space")
                await pilot.pause()

        asyncio.run(_run())
        self.assertEqual(status_map["c1"], "reviewed")

    def test_format_file_label_prefers_basename_and_short_parent(self):
        self.assertEqual(format_file_label("src/a.ts"), "a.ts (src)")
        self.assertEqual(
            format_file_label("samples/ts20-pr-sim/src/modules/module01.ts"),
            "module01.ts (.../src/modules)",
        )

    def test_build_group_diff_report_rows_groups_by_file(self):
        chunks = [
            make_chunk(
                chunk_id="c1",
                file_path="src/a.ts",
                old_start=1,
                old_count=1,
                new_start=1,
                new_count=2,
                header="function a()",
                lines=[
                    {"kind": "context", "text": "a", "oldLine": 1, "newLine": 1},
                    {"kind": "add", "text": "b", "oldLine": None, "newLine": 2},
                ],
            ),
            make_chunk(
                chunk_id="c2",
                file_path="src/b.ts",
                old_start=2,
                old_count=1,
                new_start=2,
                new_count=1,
                header="function b()",
                lines=[
                    {"kind": "delete", "text": "old", "oldLine": 2, "newLine": None},
                ],
            ),
        ]

        rows = build_group_diff_report_rows(chunks)
        kinds = [row.row_type for row in rows]
        self.assertIn("file_border", kinds)
        self.assertIn("chunk", kinds)
        self.assertIn("add", kinds)
        self.assertIn("delete", kinds)
        self.assertTrue(any(row.row_type == "file_border" and "a.ts (src)" in row.old_text for row in rows))
        self.assertTrue(any(row.row_type == "file_border" and "b.ts (src)" in row.old_text for row in rows))
        self.assertTrue(any(row.row_type == "file_border" and "──" in row.old_text for row in rows))

    def test_build_group_diff_report_rows_truncates_long_chunks(self):
        lines = [{"kind": "add", "text": f"line-{idx}", "oldLine": None, "newLine": idx} for idx in range(1, 8)]
        chunks = [
            make_chunk(
                chunk_id="c1",
                file_path="src/a.ts",
                old_start=1,
                old_count=1,
                new_start=1,
                new_count=7,
                header="function a()",
                lines=lines,
            )
        ]

        rows = build_group_diff_report_rows(chunks, max_lines_per_chunk=3)
        add_rows = [row for row in rows if row.row_type == "add"]
        self.assertEqual(len(add_rows), 3)
        self.assertTrue(any("more lines" in row.old_text for row in rows))

    def test_build_group_diff_report_rows_handles_empty(self):
        rows = build_group_diff_report_rows([])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].row_type, "info")
        self.assertIn("no chunks", rows[0].old_text)

    def test_build_group_diff_report_rows_chunk_row_includes_file_and_group_hint(self):
        chunks = [
            make_chunk(
                chunk_id="c1",
                file_path="src/a.ts",
                old_start=10,
                old_count=3,
                new_start=10,
                new_count=4,
                header="header a",
                lines=[{"kind": "add", "text": "x", "oldLine": None, "newLine": 11}],
            )
        ]
        chunks[0]["_assignedGroups"] = ["PR-4", "Auth"]

        rows = build_group_diff_report_rows(chunks)
        chunk_rows = [row for row in rows if row.row_type == "chunk"]
        self.assertEqual(len(chunk_rows), 1)
        self.assertIn("a.ts (src)", chunk_rows[0].old_text)
        self.assertIn("groups=PR-4,Auth", chunk_rows[0].old_text)

    def test_switch_lines_table_mode_rebuilds_columns_when_missing(self):
        class StubTable:
            def __init__(self) -> None:
                self.ordered_columns: list[str] = []
                self.clear_calls: list[bool] = []

            def clear(self, *, columns: bool) -> None:
                self.clear_calls.append(columns)
                if columns:
                    self.ordered_columns = []

            def add_columns(self, *names: str) -> None:
                self.ordered_columns = list(names)

        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        table = StubTable()
        app.query_one = lambda *_args, **_kwargs: table  # type: ignore[method-assign]

        app._lines_table_mode = "chunk"
        app._switch_lines_table_mode("chunk")

        self.assertEqual(table.ordered_columns, ["old", "new", "kind", "content"])
        self.assertEqual(table.clear_calls, [True])

    def test_switch_lines_table_mode_side_by_side_uses_old_new_four_columns(self):
        class StubTable:
            def __init__(self) -> None:
                self.ordered_columns: list[str] = []
                self.clear_calls: list[bool] = []

            def clear(self, *, columns: bool) -> None:
                self.clear_calls.append(columns)
                if columns:
                    self.ordered_columns = []

            def add_columns(self, *names: str) -> None:
                self.ordered_columns = list(names)

            def add_column(self, name: str, **_kwargs) -> None:
                self.ordered_columns.append(name)

        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        table = StubTable()
        app.query_one = lambda *_args, **_kwargs: table  # type: ignore[method-assign]
        app._group_report_text_widths = lambda *_args, **_kwargs: (42, 42)  # type: ignore[method-assign]

        app._lines_table_mode = "chunk_compact"
        app._switch_lines_table_mode("chunk_side_by_side")

        self.assertEqual(table.ordered_columns, ["old#", "old", "new#", "new"])
        self.assertEqual(table.clear_calls, [True])

    def test_switch_lines_table_mode_side_by_side_rebuilds_when_width_changes(self):
        class StubTable:
            def __init__(self) -> None:
                self.ordered_columns: list[str] = []
                self.clear_calls: list[bool] = []

            def clear(self, *, columns: bool) -> None:
                self.clear_calls.append(columns)
                if columns:
                    self.ordered_columns = []

            def add_columns(self, *names: str) -> None:
                self.ordered_columns = list(names)

            def add_column(self, name: str, **_kwargs) -> None:
                self.ordered_columns.append(name)

        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        table = StubTable()
        table.ordered_columns = ["old#", "old", "new#", "new"]
        app.query_one = lambda *_args, **_kwargs: table  # type: ignore[method-assign]
        app._group_report_text_widths = lambda *_args, **_kwargs: (46, 34)  # type: ignore[method-assign]
        app._lines_table_mode = "chunk_side_by_side"
        app._lines_side_by_side_widths = (40, 40)

        app._switch_lines_table_mode("chunk_side_by_side")

        self.assertEqual(table.clear_calls, [True])
        self.assertEqual(table.ordered_columns, ["old#", "old", "new#", "new"])
        self.assertEqual(app._lines_side_by_side_widths, (46, 34))

    def test_switch_lines_table_mode_side_by_side_skips_rebuild_when_width_same(self):
        class StubTable:
            def __init__(self) -> None:
                self.ordered_columns: list[str] = []
                self.clear_calls: list[bool] = []

            def clear(self, *, columns: bool) -> None:
                self.clear_calls.append(columns)
                if columns:
                    self.ordered_columns = []

            def add_columns(self, *names: str) -> None:
                self.ordered_columns = list(names)

            def add_column(self, name: str, **_kwargs) -> None:
                self.ordered_columns.append(name)

        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        table = StubTable()
        table.ordered_columns = ["old#", "old", "new#", "new"]
        app.query_one = lambda *_args, **_kwargs: table  # type: ignore[method-assign]
        app._group_report_text_widths = lambda *_args, **_kwargs: (40, 40)  # type: ignore[method-assign]
        app._lines_table_mode = "chunk_side_by_side"
        app._lines_side_by_side_widths = (40, 40)

        app._switch_lines_table_mode("chunk_side_by_side")

        self.assertEqual(table.clear_calls, [False])
        self.assertEqual(table.ordered_columns, ["old#", "old", "new#", "new"])
        self.assertEqual(app._lines_side_by_side_widths, (40, 40))

    def test_on_resize_rerenders_width_sensitive_view(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        calls: list[str] = []
        app._rerender_lines_if_width_sensitive = lambda: calls.append("rerender")  # type: ignore[method-assign]

        app.on_resize(mock.Mock())

        self.assertEqual(calls, ["rerender"])

    def test_toggle_context_lines_toggles_and_rerenders_chunk(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {"c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []}},
            {},
            15,
        )
        app.selected_chunk_id = "c1"
        show_calls: list[str] = []
        notices: list[str] = []
        refresh_calls: list[bool] = []
        app._show_chunk = lambda cid: show_calls.append(cid)  # type: ignore[method-assign]
        app.notify = lambda message, **_kwargs: notices.append(str(message))  # type: ignore[method-assign]
        app._refresh_topbar = lambda: refresh_calls.append(True)  # type: ignore[method-assign]

        self.assertTrue(app.show_context_lines)
        app.action_toggle_context_lines()
        self.assertFalse(app.show_context_lines)
        self.assertEqual(show_calls, ["c1"])
        self.assertEqual(refresh_calls, [True])
        self.assertTrue(any("Context lines: OFF" in item for item in notices))

        app.action_toggle_context_lines()
        self.assertTrue(app.show_context_lines)
        self.assertEqual(show_calls, ["c1", "c1"])
        self.assertEqual(refresh_calls, [True, True])
        self.assertTrue(any("Context lines: ON" in item for item in notices))

    def test_toggle_context_lines_noop_in_group_report_mode(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {"c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []}},
            {},
            15,
        )
        app.group_report_mode = True
        app.selected_chunk_id = "c1"
        app._show_chunk = lambda *_args, **_kwargs: self.fail("must not rerender in group mode")  # type: ignore[method-assign]
        app.notify = lambda *_args, **_kwargs: self.fail("must not notify in group mode")  # type: ignore[method-assign]
        app._refresh_topbar = lambda: self.fail("must not refresh in group mode")  # type: ignore[method-assign]
        before = app.show_context_lines

        app.action_toggle_context_lines()

        self.assertEqual(app.show_context_lines, before)

    def test_zoom_in_and_out_clamps_density(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        notices: list[str] = []
        app._apply_ui_density = lambda: None  # type: ignore[method-assign]
        app._rerender_lines_if_width_sensitive = lambda: None  # type: ignore[method-assign]
        app._save_viewer_settings = lambda: True  # type: ignore[method-assign]
        app._refresh_topbar = lambda: None  # type: ignore[method-assign]
        app.notify = lambda message, **_kwargs: notices.append(str(message))  # type: ignore[method-assign]

        app.ui_density = "comfortable"
        app.action_zoom_in()
        self.assertEqual(app.ui_density, "comfortable")

        app.ui_density = "compact"
        app.action_zoom_out()
        self.assertEqual(app.ui_density, "compact")
        self.assertTrue(any("UI density:" in item for item in notices))

    def test_cycle_diff_syntax_theme_cycles_and_rerenders_chunk(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {"c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []}},
            {},
            15,
        )
        app.selected_chunk_id = "c1"
        app.diff_syntax_theme = "github-dark"
        app._syntax_by_lexer = {"python": mock.Mock()}  # type: ignore[assignment]
        show_calls: list[str] = []
        notices: list[str] = []
        refresh_calls: list[bool] = []
        app._show_chunk = lambda cid: show_calls.append(cid)  # type: ignore[method-assign]
        app._save_viewer_settings = lambda: True  # type: ignore[method-assign]
        app.notify = lambda message, **_kwargs: notices.append(str(message))  # type: ignore[method-assign]
        app._refresh_topbar = lambda: refresh_calls.append(True)  # type: ignore[method-assign]

        with mock.patch("diffgr.viewer_textual._preferred_pygments_themes", return_value=["github-dark", "nord", "dracula"]):
            app.action_cycle_diff_syntax_theme()
            self.assertEqual(app.diff_syntax_theme, "nord")
            self.assertEqual(show_calls, ["c1"])
            self.assertEqual(app._syntax_by_lexer, {})
            app.action_cycle_diff_syntax_theme()
            self.assertEqual(app.diff_syntax_theme, "dracula")

        self.assertEqual(len(refresh_calls), 2)
        self.assertTrue(any("Syntax theme:" in item for item in notices))

    def test_cycle_diff_syntax_theme_handles_no_theme_list(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        notices: list[str] = []
        app._save_viewer_settings = lambda: self.fail("must not save when no themes")  # type: ignore[method-assign]
        app.notify = lambda message, **_kwargs: notices.append(str(message))  # type: ignore[method-assign]
        before = app.diff_syntax_theme

        with mock.patch("diffgr.viewer_textual._preferred_pygments_themes", return_value=[]):
            app.action_cycle_diff_syntax_theme()

        self.assertEqual(app.diff_syntax_theme, before)
        self.assertTrue(any("No syntax themes available" in item for item in notices))

    def test_rerender_lines_if_width_sensitive_routes_by_mode(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {"c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []}},
            {},
            15,
        )
        app.selected_chunk_id = "c1"
        report_calls: list[str | None] = []
        chunk_calls: list[str] = []
        app._show_current_group_report = lambda target_chunk_id=None: report_calls.append(target_chunk_id)  # type: ignore[method-assign]
        app._show_chunk = lambda chunk_id: chunk_calls.append(chunk_id)  # type: ignore[method-assign]

        app.group_report_mode = True
        app._rerender_lines_if_width_sensitive()
        self.assertEqual(report_calls, ["c1"])
        self.assertEqual(chunk_calls, [])

        app.group_report_mode = False
        app.chunk_detail_view_mode = "side_by_side"
        app._rerender_lines_if_width_sensitive()
        self.assertEqual(chunk_calls, ["c1"])

    def test_rerender_lines_if_width_sensitive_swallows_render_errors(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {"c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []}},
            {},
            15,
        )
        app.group_report_mode = True
        app.selected_chunk_id = "c1"
        app._show_current_group_report = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]

        app._rerender_lines_if_width_sensitive()

    def test_toggle_chunk_detail_view_toggles_and_rerenders_chunk(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {"c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []}},
            {},
            15,
        )
        app.selected_chunk_id = "c1"
        show_calls: list[str] = []
        app._show_chunk = lambda cid: show_calls.append(cid)  # type: ignore[method-assign]
        app._refresh_topbar = lambda: None  # type: ignore[method-assign]
        app.notify = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        self.assertEqual(app.chunk_detail_view_mode, "compact")
        app.action_toggle_chunk_detail_view()
        self.assertEqual(app.chunk_detail_view_mode, "side_by_side")
        self.assertEqual(show_calls, ["c1"])

        app.action_toggle_chunk_detail_view()
        self.assertEqual(app.chunk_detail_view_mode, "compact")
        self.assertEqual(show_calls, ["c1", "c1"])

    def test_toggle_chunk_detail_view_noop_in_group_report_mode(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {"c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []}},
            {},
            15,
        )
        app.group_report_mode = True
        app.selected_chunk_id = "c1"
        app._show_chunk = lambda *_args, **_kwargs: self.fail("must not rerender in group mode")  # type: ignore[method-assign]
        app._refresh_topbar = lambda: None  # type: ignore[method-assign]
        app.notify = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        app.action_toggle_chunk_detail_view()

        self.assertEqual(app.chunk_detail_view_mode, "compact")

    def test_resolve_chunk_file_path_resolves_relative_from_source_parent_parent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "samples" / "diffgr"
            source_dir.mkdir(parents=True, exist_ok=True)
            source_path = source_dir / "sample.diffgr.json"
            source_path.write_text("{}", encoding="utf-8")
            target = root / "src" / "mod.ts"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("export const x = 1;\n", encoding="utf-8")
            app = DiffgrTextualApp(
                source_path,
                {"groups": [], "assignments": {}, "meta": {}},
                [],
                {},
                {},
                15,
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                resolved = app._resolve_chunk_file_path("src/mod.ts")
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(resolved, (root / "src" / "mod.ts").resolve())

    def test_preferred_open_line_uses_selected_anchor_then_chunk_new(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {"c1": {"id": "c1", "filePath": "src/a.ts", "old": {"start": 7}, "new": {"start": 11}, "lines": []}},
            {},
            15,
        )
        app._selected_line_anchor = {"newLine": 33, "oldLine": 22}
        self.assertEqual(app._preferred_open_line("c1"), 33)

        app._selected_line_anchor = {"newLine": None, "oldLine": 22}
        self.assertEqual(app._preferred_open_line("c1"), 22)

        app._selected_line_anchor = None
        self.assertEqual(app._preferred_open_line("c1"), 11)

    def test_action_open_chunk_file_opens_resolved_path_with_line(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {"c1": {"id": "c1", "filePath": "src/a.ts", "old": {"start": 7}, "new": {"start": 11}, "lines": []}},
            {},
            15,
        )
        app.selected_chunk_id = "c1"
        expected = Path("C:/temp/a.ts")
        app._resolve_chunk_file_path = lambda _raw: expected  # type: ignore[method-assign]
        calls: list[tuple[Path, int | None]] = []
        app._open_file_path = lambda path, line=None: calls.append((path, line)) or True  # type: ignore[method-assign]
        app.notify = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        app.action_open_chunk_file()

        self.assertEqual(calls, [(expected, 11)])

    def test_load_viewer_settings_reads_mode_and_custom_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "viewer_settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "editorMode": "custom",
                        "customEditorCommand": "code -g {path}:{line}",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            previous_env = os.environ.get("DIFFGR_VIEWER_SETTINGS")
            os.environ["DIFFGR_VIEWER_SETTINGS"] = str(settings_path)
            try:
                app = DiffgrTextualApp(
                    Path("dummy.diffgr.json"),
                    {"groups": [], "assignments": {}, "meta": {}},
                    [],
                    {},
                    {},
                    15,
                )
            finally:
                if previous_env is None:
                    os.environ.pop("DIFFGR_VIEWER_SETTINGS", None)
                else:
                    os.environ["DIFFGR_VIEWER_SETTINGS"] = previous_env

            self.assertEqual(app.editor_mode, "custom")
            self.assertEqual(app.custom_editor_command, "code -g {path}:{line}")

    def test_save_viewer_settings_writes_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "viewer_settings.json"
            previous_env = os.environ.get("DIFFGR_VIEWER_SETTINGS")
            os.environ["DIFFGR_VIEWER_SETTINGS"] = str(settings_path)
            try:
                app = DiffgrTextualApp(
                    Path("dummy.diffgr.json"),
                    {"groups": [], "assignments": {}, "meta": {}},
                    [],
                    {},
                    {},
                    15,
                )
                app.editor_mode = "cursor"
                app.custom_editor_command = "cursor {path}"
                saved = app._save_viewer_settings()
            finally:
                if previous_env is None:
                    os.environ.pop("DIFFGR_VIEWER_SETTINGS", None)
                else:
                    os.environ["DIFFGR_VIEWER_SETTINGS"] = previous_env

            self.assertTrue(saved)
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["editorMode"], "cursor")
            self.assertEqual(payload["customEditorCommand"], "cursor {path}")

    def test_open_file_path_uses_custom_editor_template(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.editor_mode = "custom"
        app.custom_editor_command = "my-editor --line {line} {path}"
        target = Path("C:/tmp/my file.ts")

        with mock.patch("diffgr.viewer_textual.subprocess.Popen") as popen_mock:
            opened = app._open_file_path(target, line=42)

        self.assertTrue(opened)
        popen_mock.assert_called_once_with(["my-editor", "--line", "42", str(target)])

    def test_open_with_custom_editor_appends_path_when_placeholder_missing(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.custom_editor_command = "my-editor --wait"
        target = Path("C:/tmp/a.ts")

        with mock.patch("diffgr.viewer_textual.subprocess.Popen") as popen_mock:
            opened = app._open_with_custom_editor(target, line=None)

        self.assertTrue(opened)
        popen_mock.assert_called_once_with(["my-editor", "--wait", str(target)])

    def test_open_file_path_auto_fallback_uses_code_cursor_then_default(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.editor_mode = "auto"
        target = Path("C:/tmp/f.ts")
        app._open_with_editor_command = mock.Mock(side_effect=[False, False])  # type: ignore[method-assign]
        app._open_default_app = mock.Mock(return_value=True)  # type: ignore[method-assign]

        opened = app._open_file_path(target, line=10)

        self.assertTrue(opened)
        self.assertEqual(
            app._open_with_editor_command.call_args_list,
            [
                mock.call("code", target, line=10),
                mock.call("cursor", target, line=10),
            ],
        )
        app._open_default_app.assert_called_once_with(target)

    def test_action_open_settings_rejects_custom_without_command(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.editor_mode = "vscode"
        app.custom_editor_command = "code -g {path}:{line}"
        app._save_viewer_settings = lambda: self.fail("must not save invalid custom settings")  # type: ignore[method-assign]
        app._refresh_topbar = lambda: None  # type: ignore[method-assign]
        notices: list[str] = []
        app.notify = lambda message, **_kwargs: notices.append(str(message))  # type: ignore[method-assign]

        def _push_screen(_screen, callback):
            callback({"editor_mode": "custom", "custom_editor_command": "   "})

        app.push_screen = _push_screen  # type: ignore[method-assign]

        app.action_open_settings()

        self.assertEqual(app.editor_mode, "vscode")
        self.assertEqual(app.custom_editor_command, "code -g {path}:{line}")
        self.assertTrue(any("custom mode requires command template" in item for item in notices))

    def test_action_open_settings_saves_mode_and_command(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.editor_mode = "auto"
        app.custom_editor_command = ""
        save_called: list[bool] = []
        refresh_called: list[bool] = []
        notices: list[str] = []
        app._save_viewer_settings = lambda: save_called.append(True) or True  # type: ignore[method-assign]
        app._refresh_topbar = lambda: refresh_called.append(True)  # type: ignore[method-assign]
        app.notify = lambda message, **_kwargs: notices.append(str(message))  # type: ignore[method-assign]

        def _push_screen(_screen, callback):
            callback({"editor_mode": "custom", "custom_editor_command": "zed {path}:{line}"})

        app.push_screen = _push_screen  # type: ignore[method-assign]

        app.action_open_settings()

        self.assertEqual(app.editor_mode, "custom")
        self.assertEqual(app.custom_editor_command, "zed {path}:{line}")
        self.assertEqual(save_called, [True])
        self.assertEqual(refresh_called, [True])
        self.assertTrue(any("Settings saved: editor=custom" in item for item in notices))

    def test_done_checkbox_symbols_are_fixed(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        self.assertEqual(app._done_checkbox_for_status("reviewed"), "[✅]")
        self.assertEqual(app._done_checkbox_for_status("unreviewed"), "[  ]")

    def test_normalize_editor_mode_defaults_to_auto_on_invalid(self):
        self.assertEqual(normalize_editor_mode("vscode"), "vscode")
        self.assertEqual(normalize_editor_mode("  cursor  "), "cursor")
        self.assertEqual(normalize_editor_mode("unknown-editor"), "auto")
        self.assertEqual(normalize_editor_mode(None), "auto")

    def test_render_report_selected_styles_use_underline_not_background_fill(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )

        number = app._render_report_number("10", "add", "new", selected=True)
        text = app._render_report_text("sample", "add", "new", selected=True)

        self.assertIn("underline", number.style)
        self.assertNotIn(" on ", number.style)
        self.assertIn("underline", text.style)
        self.assertNotIn(" on ", text.style)

    def test_clamp_left_pane_pct_respects_min_max(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        self.assertEqual(app._clamp_left_pane_pct(-1), app.MIN_LEFT_PANE_PCT)
        self.assertEqual(app._clamp_left_pane_pct(100), app.MAX_LEFT_PANE_PCT)
        self.assertEqual(app._clamp_left_pane_pct(52), 52)

    def test_apply_main_split_widths_updates_left_and_right_panes(self):
        class StubStyles:
            def __init__(self) -> None:
                self.width = ""

        class StubPane:
            def __init__(self) -> None:
                self.styles = StubStyles()

        left = StubPane()
        right = StubPane()
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.left_pane_pct = 60
        app.query_one = lambda selector, *_args, **_kwargs: left if selector == "#left" else right  # type: ignore[method-assign]

        app._apply_main_split_widths()

        self.assertEqual(left.styles.width, "60%")
        self.assertEqual(right.styles.width, "40%")

    def test_move_split_actions_adjust_ratio_within_bounds(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.left_pane_pct = 52
        app._apply_main_split_widths = lambda: None  # type: ignore[method-assign]
        app._refresh_topbar = lambda: None  # type: ignore[method-assign]

        app.action_move_split_right()
        self.assertEqual(app.left_pane_pct, 56)

        app.action_move_split_left()
        self.assertEqual(app.left_pane_pct, 52)

        app.left_pane_pct = app.MAX_LEFT_PANE_PCT
        app.action_move_split_right()
        self.assertEqual(app.left_pane_pct, app.MAX_LEFT_PANE_PCT)

    def test_move_split_actions_trigger_rerender_and_refresh_when_changed(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.left_pane_pct = 52
        rerender_calls: list[bool] = []
        refresh_calls: list[bool] = []
        app._apply_main_split_widths = lambda: None  # type: ignore[method-assign]
        app._rerender_lines_if_width_sensitive = lambda: rerender_calls.append(True)  # type: ignore[method-assign]
        app._refresh_topbar = lambda: refresh_calls.append(True)  # type: ignore[method-assign]

        app.action_move_split_right()

        self.assertEqual(app.left_pane_pct, 56)
        self.assertEqual(rerender_calls, [True])
        self.assertEqual(refresh_calls, [True])

    def test_move_split_right_noop_at_max_does_not_rerender(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.left_pane_pct = app.MAX_LEFT_PANE_PCT
        app._apply_main_split_widths = lambda: self.fail("must not apply widths on no-op")  # type: ignore[method-assign]
        app._rerender_lines_if_width_sensitive = lambda: self.fail("must not rerender on no-op")  # type: ignore[method-assign]
        app._refresh_topbar = lambda: self.fail("must not refresh on no-op")  # type: ignore[method-assign]

        app.action_move_split_right()
        self.assertEqual(app.left_pane_pct, app.MAX_LEFT_PANE_PCT)

    def test_clamp_diff_old_ratio_respects_min_max(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        self.assertEqual(app._clamp_diff_old_ratio(-1.0), app.MIN_DIFF_OLD_RATIO)
        self.assertEqual(app._clamp_diff_old_ratio(2.0), app.MAX_DIFF_OLD_RATIO)
        self.assertEqual(app._clamp_diff_old_ratio(0.5), 0.5)

    def test_group_report_text_widths_follow_ratio(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.left_pane_pct = 52
        app.diff_old_ratio = 0.70

        old_width, new_width = app._group_report_text_widths(total_width=140)

        self.assertGreater(old_width, new_width)
        self.assertGreaterEqual(old_width, 12)
        self.assertGreaterEqual(new_width, 12)

    def test_group_report_text_widths_prefers_lines_widget_width(self):
        class StubSize:
            def __init__(self, width: int) -> None:
                self.width = width

        class StubLinesTable:
            def __init__(self, width: int) -> None:
                self.size = StubSize(width)

        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.diff_old_ratio = 0.50
        app.query_one = lambda *_args, **_kwargs: StubLinesTable(88)  # type: ignore[method-assign]

        old_width, new_width = app._group_report_text_widths(total_width=200)

        self.assertEqual((old_width, new_width), (36, 36))

    def test_group_report_text_widths_falls_back_when_lines_unavailable(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.left_pane_pct = 52
        app.diff_old_ratio = 0.50
        app.query_one = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no widget"))  # type: ignore[method-assign]

        old_width, new_width = app._group_report_text_widths(total_width=120)

        self.assertGreaterEqual(old_width, 12)
        self.assertGreaterEqual(new_width, 12)
        self.assertEqual(old_width + new_width, 41)

    def test_move_diff_split_actions_adjust_ratio_within_bounds(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.diff_old_ratio = 0.50
        app._show_current_group_report = lambda *_, **__: None  # type: ignore[method-assign]
        app._refresh_topbar = lambda: None  # type: ignore[method-assign]

        app.action_move_diff_split_right()
        self.assertAlmostEqual(app.diff_old_ratio, 0.55)

        app.action_move_diff_split_left()
        self.assertAlmostEqual(app.diff_old_ratio, 0.50)

        app.diff_old_ratio = app.MAX_DIFF_OLD_RATIO
        app.action_move_diff_split_right()
        self.assertAlmostEqual(app.diff_old_ratio, app.MAX_DIFF_OLD_RATIO)

    def test_move_diff_split_noop_at_max_does_not_rerender(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.diff_old_ratio = app.MAX_DIFF_OLD_RATIO
        app._rerender_lines_if_width_sensitive = lambda: self.fail("must not rerender on no-op")  # type: ignore[method-assign]
        app._refresh_topbar = lambda: self.fail("must not refresh on no-op")  # type: ignore[method-assign]

        app.action_move_diff_split_right()
        self.assertAlmostEqual(app.diff_old_ratio, app.MAX_DIFF_OLD_RATIO)

    def test_apply_ui_density_sets_padding_for_all_tables(self):
        class StubTable:
            def __init__(self) -> None:
                self.cell_padding = -1

        groups = StubTable()
        chunks = StubTable()
        lines = StubTable()
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.ui_density = "comfortable"

        def _query_one(selector, *_args, **_kwargs):
            mapping = {"#groups": groups, "#chunks": chunks, "#lines": lines}
            return mapping[selector]

        app.query_one = _query_one  # type: ignore[method-assign]

        app._apply_ui_density()

        self.assertEqual(groups.cell_padding, 2)
        self.assertEqual(chunks.cell_padding, 2)
        self.assertEqual(lines.cell_padding, 2)

    def test_toggle_reviewed_checkbox_switches_between_reviewed_and_unreviewed(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {"c1": {}}},
            [],
            {"c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []}},
            {"c1": "unreviewed"},
            15,
        )
        app.selected_chunk_id = "c1"
        app._refresh_groups = lambda *_, **__: None  # type: ignore[method-assign]
        app._apply_chunk_filter = lambda *_, **__: None  # type: ignore[method-assign]
        app._show_chunk = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        app.action_toggle_reviewed_checkbox()
        self.assertEqual(app.status_map["c1"], "reviewed")
        self.assertEqual(app.doc["reviews"]["c1"]["status"], "reviewed")
        self.assertTrue(app.doc["reviews"]["c1"].get("reviewedAt"))

        app.action_toggle_reviewed_checkbox()
        self.assertEqual(app.status_map["c1"], "unreviewed")
        self.assertEqual(app.doc["reviews"]["c1"]["status"], "unreviewed")

    def test_effective_chunk_selection_orders_multi_selection_by_filtered_order(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.filtered_chunk_ids = ["c2", "c1", "c3"]
        app.selected_chunk_ids = {"c1", "c2"}
        app.selected_chunk_id = "c1"

        self.assertEqual(app._effective_chunk_selection(), ["c2", "c1"])

    def test_set_status_applies_to_all_selected_chunks(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {"c1": {}, "c2": {}}},
            [],
            {
                "c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []},
                "c2": {"id": "c2", "filePath": "src/b.ts", "old": {}, "new": {}, "header": "", "lines": []},
            },
            {"c1": "unreviewed", "c2": "needsReReview"},
            15,
        )
        app.filtered_chunk_ids = ["c1", "c2"]
        app.selected_chunk_ids = {"c1", "c2"}
        app.selected_chunk_id = "c2"
        app._refresh_groups = lambda *_, **__: None  # type: ignore[method-assign]
        app._apply_chunk_filter = lambda *_, **__: None  # type: ignore[method-assign]
        app._render_current_selection = lambda: None  # type: ignore[method-assign]

        app.action_set_status("reviewed")

        self.assertEqual(app.status_map["c1"], "reviewed")
        self.assertEqual(app.status_map["c2"], "reviewed")
        self.assertEqual(app.doc["reviews"]["c1"]["status"], "reviewed")
        self.assertEqual(app.doc["reviews"]["c2"]["status"], "reviewed")

    def test_mark_selected_unreviewed_applies_to_all_selected_chunks(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {"c1": {}, "c2": {}}},
            [],
            {
                "c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []},
                "c2": {"id": "c2", "filePath": "src/b.ts", "old": {}, "new": {}, "header": "", "lines": []},
            },
            {"c1": "reviewed", "c2": "reviewed"},
            15,
        )
        app.filtered_chunk_ids = ["c1", "c2"]
        app.selected_chunk_ids = {"c1", "c2"}
        app.selected_chunk_id = "c2"
        app._refresh_groups = lambda *_, **__: None  # type: ignore[method-assign]
        app._apply_chunk_filter = lambda *_, **__: None  # type: ignore[method-assign]
        app._render_current_selection = lambda: None  # type: ignore[method-assign]

        app.action_mark_selected_unreviewed()

        self.assertEqual(app.status_map["c1"], "unreviewed")
        self.assertEqual(app.status_map["c2"], "unreviewed")

    def test_toggle_reviewed_checkbox_toggles_all_selected_chunks(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {"c1": {}, "c2": {}}},
            [],
            {
                "c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []},
                "c2": {"id": "c2", "filePath": "src/b.ts", "old": {}, "new": {}, "header": "", "lines": []},
            },
            {"c1": "reviewed", "c2": "reviewed"},
            15,
        )
        app.filtered_chunk_ids = ["c1", "c2"]
        app.selected_chunk_ids = {"c1", "c2"}
        app.selected_chunk_id = "c2"
        app._refresh_groups = lambda *_, **__: None  # type: ignore[method-assign]
        app._apply_chunk_filter = lambda *_, **__: None  # type: ignore[method-assign]
        app._render_current_selection = lambda: None  # type: ignore[method-assign]

        app.action_toggle_reviewed_checkbox()
        self.assertEqual(app.status_map["c1"], "unreviewed")
        self.assertEqual(app.status_map["c2"], "unreviewed")

    def test_select_all_visible_chunks_marks_all_as_selected(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.filtered_chunk_ids = ["c1", "c2", "c3"]
        app.selected_chunk_id = "c2"
        app.selected_chunk_ids = {"c2"}
        app._refresh_chunk_selection_markers = lambda: None  # type: ignore[method-assign]
        app._refresh_topbar = lambda: None  # type: ignore[method-assign]

        app.action_select_all_visible_chunks()

        self.assertEqual(app.selected_chunk_ids, {"c1", "c2", "c3"})
        self.assertEqual(app.selected_chunk_id, "c2")

    def test_clear_chunk_multi_selection_keeps_current_only(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.filtered_chunk_ids = ["c1", "c2", "c3"]
        app.selected_chunk_id = "c2"
        app.selected_chunk_ids = {"c1", "c2", "c3"}
        app._refresh_chunk_selection_markers = lambda: None  # type: ignore[method-assign]
        app._refresh_topbar = lambda: None  # type: ignore[method-assign]

        app.action_clear_chunk_multi_selection()

        self.assertEqual(app.selected_chunk_ids, {"c2"})
        self.assertEqual(app.selected_chunk_id, "c2")

    def test_toggle_current_chunk_selection_readds_current_when_last_removed(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.filtered_chunk_ids = ["c1"]
        app.selected_chunk_id = "c1"
        app.selected_chunk_ids = {"c1"}
        app._refresh_chunk_selection_markers = lambda: None  # type: ignore[method-assign]
        app._refresh_topbar = lambda: None  # type: ignore[method-assign]

        app.action_toggle_current_chunk_selection()

        self.assertEqual(app.selected_chunk_ids, {"c1"})
        self.assertEqual(app.selected_chunk_id, "c1")

    def test_refresh_topbar_includes_reviewed_rate_percent(self):
        class StubStatic:
            def __init__(self) -> None:
                self.value = ""

            def update(self, text: str) -> None:
                self.value = text

        topbar = StubStatic()
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {"title": "Sample"}},
            [],
            {
                "c1": {"id": "c1", "filePath": "src/a.ts", "old": {}, "new": {}, "header": "", "lines": []},
                "c2": {"id": "c2", "filePath": "src/b.ts", "old": {}, "new": {}, "header": "", "lines": []},
            },
            {"c1": "reviewed", "c2": "unreviewed"},
            15,
        )
        app.query_one = lambda selector, *_args, **_kwargs: topbar if selector == "#topbar" else None  # type: ignore[method-assign]

        app._refresh_topbar()

        self.assertIn("cur(total=2 pending=1 reviewed=1 rate=50.0%)", topbar.value)
        self.assertIn("all(total=2 pending=1 reviewed=1 rate=50.0%)", topbar.value)
        self.assertIn("detailView=compact", topbar.value)

    def test_set_comment_for_chunk_marks_dirty(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {}},
            [],
            {},
            {},
            15,
        )
        self.assertFalse(app._has_unsaved_changes)

        app._set_comment_for_chunk("c1", "needs follow-up")

        self.assertTrue(app._has_unsaved_changes)

    def test_save_document_clears_dirty_and_persists_file(self):
        doc = {"groups": [], "assignments": {}, "meta": {"title": "Sample"}, "reviews": {"c1": {"comment": "x"}}}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.diffgr.json"
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            app = DiffgrTextualApp(path, doc, [], {}, {}, 15)
            app._has_unsaved_changes = True

            saved = app._save_document(auto=False, force=True)

            self.assertTrue(saved)
            self.assertFalse(app._has_unsaved_changes)
            self.assertEqual(app._last_save_kind, "manual")
            self.assertIsNotNone(app._last_saved_at)
            roundtrip = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(roundtrip.get("reviews", {}).get("c1", {}).get("comment"), "x")

    def test_auto_save_tick_runs_only_when_dirty(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {}},
            [],
            {},
            {},
            15,
        )
        calls: list[tuple[bool, bool]] = []
        app._save_document = lambda *, auto, force: calls.append((auto, force)) or True  # type: ignore[method-assign]

        app._has_unsaved_changes = False
        app._auto_save_tick()
        self.assertEqual(calls, [])

        app._has_unsaved_changes = True
        app._auto_save_tick()
        self.assertEqual(calls, [(True, False)])

    def test_refresh_topbar_includes_save_state(self):
        class StubStatic:
            def __init__(self) -> None:
                self.value = ""

            def update(self, text: str) -> None:
                self.value = text

        topbar = StubStatic()
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {"title": "Sample"}},
            [],
            {},
            {},
            15,
        )
        app.query_one = lambda selector, *_args, **_kwargs: topbar if selector == "#topbar" else None  # type: ignore[method-assign]
        app._has_unsaved_changes = True

        app._refresh_topbar()
        self.assertIn("save=dirty", topbar.value)

        app._has_unsaved_changes = False
        app._last_save_kind = "auto"
        app._last_saved_at = dt.datetime(2026, 2, 23, 12, 34, 56)
        app._refresh_topbar()
        self.assertIn("save=clean(auto@12:34:56)", topbar.value)

    def test_add_left_border_prefixes_non_spacer_rows(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        self.assertEqual(app._add_left_border("hello", "context"), "│ hello")
        self.assertEqual(app._add_left_border("", "context"), "│")
        self.assertEqual(app._add_left_border("", "spacer"), "")

    def test_sync_selection_from_report_row_key_updates_chunk_selection(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.group_report_mode = True
        app.selected_chunk_id = "c1"
        app._group_report_row_chunk_by_key = {"r-1": "c2"}
        selected_rows: list[str] = []
        refreshed_with: list[str] = []
        app._select_chunk_row = lambda cid: selected_rows.append(cid)  # type: ignore[method-assign]
        app._show_current_group_report = lambda target_chunk_id=None: refreshed_with.append(str(target_chunk_id))  # type: ignore[method-assign]

        changed = app._sync_selection_from_report_row_key("r-1")

        self.assertTrue(changed)
        self.assertEqual(app.selected_chunk_id, "c2")
        self.assertEqual(selected_rows, ["c2"])
        self.assertEqual(refreshed_with, ["c2"])

    def test_sync_selection_from_report_row_key_ignores_non_chunk_row(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.group_report_mode = True
        app.selected_chunk_id = "c1"
        app._group_report_row_chunk_by_key = {}
        app._select_chunk_row = lambda *_args, **_kwargs: self.fail("should not select")  # type: ignore[method-assign]
        app._show_current_group_report = lambda *_args, **_kwargs: self.fail("should not refresh")  # type: ignore[method-assign]

        changed = app._sync_selection_from_report_row_key("r-0")

        self.assertFalse(changed)
        self.assertEqual(app.selected_chunk_id, "c1")

    def test_sync_selection_from_report_row_key_skips_same_chunk_for_stability(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        app.group_report_mode = True
        app.selected_chunk_id = "c2"
        app._group_report_row_chunk_by_key = {"r-1": "c2"}
        app._select_chunk_row = lambda *_args, **_kwargs: self.fail("should not move cursor")  # type: ignore[method-assign]
        app._show_current_group_report = lambda *_args, **_kwargs: self.fail("should not refresh")  # type: ignore[method-assign]

        changed = app._sync_selection_from_report_row_key("r-1")

        self.assertFalse(changed)
        self.assertEqual(app.selected_chunk_id, "c2")

    def test_select_chunk_row_restores_suppression_flag(self):
        class StubRowKey:
            def __init__(self, value: str) -> None:
                self.value = value

        class StubTable:
            def __init__(self) -> None:
                self.rows = {StubRowKey("c1"): None, StubRowKey("c2"): None}
                self.cursor_coordinate: tuple[int, int] | None = None

        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}},
            [],
            {},
            {},
            15,
        )
        table = StubTable()
        app.query_one = lambda *_args, **_kwargs: table  # type: ignore[method-assign]

        app._select_chunk_row("c2")

        self.assertEqual(app._suppress_chunk_table_events, False)
        self.assertEqual(table.cursor_coordinate, (1, 0))

    def test_set_comment_for_chunk_creates_review_record(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {}},
            [],
            {},
            {},
            15,
        )

        app._set_comment_for_chunk("c1", "looks good")

        self.assertEqual(app._comment_for_chunk("c1"), "looks good")
        self.assertEqual(app.doc["reviews"]["c1"]["comment"], "looks good")

    def test_set_comment_for_chunk_keeps_status_when_comment_cleared(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {"c1": {"status": "reviewed", "comment": "x"}}},
            [],
            {},
            {},
            15,
        )

        app._set_comment_for_chunk("c1", "")

        self.assertEqual(app._comment_for_chunk("c1"), "")
        self.assertEqual(app.doc["reviews"]["c1"], {"status": "reviewed"})

    def test_set_comment_for_chunk_removes_empty_review_record(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {"c1": {"comment": "x"}}},
            [],
            {},
            {},
            15,
        )

        app._set_comment_for_chunk("c1", "   ")

        self.assertNotIn("c1", app.doc["reviews"])

    def test_set_line_comment_for_anchor_creates_review_record(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {}},
            [],
            {},
            {},
            15,
        )

        app._set_line_comment_for_anchor(
            "c1",
            old_line=2,
            new_line=None,
            line_type="delete",
            comment="line note",
        )

        self.assertEqual(app._line_comment_for_anchor("c1", 2, None, "delete"), "line note")
        self.assertEqual(app._line_comment_count_for_chunk("c1"), 1)
        record = app.doc["reviews"]["c1"]["lineComments"][0]
        self.assertEqual(record["oldLine"], 2)
        self.assertIsNone(record["newLine"])
        self.assertEqual(record["lineType"], "delete")
        self.assertEqual(record["comment"], "line note")
        self.assertTrue(record.get("updatedAt"))

    def test_set_line_comment_for_anchor_replaces_existing_same_anchor_only(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {
                "groups": [],
                "assignments": {},
                "meta": {},
                "reviews": {
                    "c1": {
                        "lineComments": [
                            {"oldLine": 2, "newLine": None, "lineType": "delete", "comment": "old note"},
                            {"oldLine": None, "newLine": 2, "lineType": "add", "comment": "keep me"},
                        ]
                    }
                },
            },
            [],
            {},
            {},
            15,
        )

        app._set_line_comment_for_anchor(
            "c1",
            old_line=2,
            new_line=None,
            line_type="delete",
            comment="new note",
        )

        self.assertEqual(app._line_comment_for_anchor("c1", 2, None, "delete"), "new note")
        self.assertEqual(app._line_comment_for_anchor("c1", None, 2, "add"), "keep me")
        self.assertEqual(app._line_comment_count_for_chunk("c1"), 2)

    def test_set_line_comment_for_anchor_removes_empty_review_record(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {
                "groups": [],
                "assignments": {},
                "meta": {},
                "reviews": {
                    "c1": {
                        "lineComments": [
                            {"oldLine": 2, "newLine": None, "lineType": "delete", "comment": "x"},
                        ]
                    }
                },
            },
            [],
            {},
            {},
            15,
        )

        app._set_line_comment_for_anchor(
            "c1",
            old_line=2,
            new_line=None,
            line_type="delete",
            comment="   ",
        )

        self.assertNotIn("c1", app.doc["reviews"])

    def test_build_intraline_pair_map_pairs_delete_and_add_by_block_order(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {}},
            [],
            {},
            {},
            15,
        )
        lines = [
            {"kind": "context", "text": "ctx"},
            {"kind": "delete", "text": "return a + 1;"},
            {"kind": "delete", "text": "const b = x;"},
            {"kind": "add", "text": "return a * 2;"},
            {"kind": "add", "text": "const b = normalize(x);"},
            {"kind": "context", "text": "tail"},
        ]

        pair_map = app._build_intraline_pair_map(lines)

        self.assertEqual(pair_map[1], "return a * 2;")
        self.assertEqual(pair_map[3], "return a + 1;")
        self.assertEqual(pair_map[2], "const b = normalize(x);")
        self.assertEqual(pair_map[4], "const b = x;")

    def test_build_intraline_pair_map_ignores_unpaired_add_or_delete(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {}},
            [],
            {},
            {},
            15,
        )
        lines = [
            {"kind": "delete", "text": "only old"},
            {"kind": "context", "text": "ctx"},
            {"kind": "add", "text": "only new"},
        ]

        pair_map = app._build_intraline_pair_map(lines)

        self.assertEqual(pair_map, {})

    def test_build_intraline_pair_map_prefers_best_similarity_over_position(self):
        app = DiffgrTextualApp(
            Path("dummy.diffgr.json"),
            {"groups": [], "assignments": {}, "meta": {}, "reviews": {}},
            [],
            {},
            {},
            15,
        )
        lines = [
            {"kind": "delete", "text": "alpha gamma"},
            {"kind": "delete", "text": "return user.name"},
            {"kind": "add", "text": "return user.full_name"},
            {"kind": "add", "text": "alpha beta gamma"},
        ]

        pair_map = app._build_intraline_pair_map(lines)

        self.assertEqual(pair_map[0], "alpha beta gamma")
        self.assertEqual(pair_map[3], "alpha gamma")
        self.assertEqual(pair_map[1], "return user.full_name")
        self.assertEqual(pair_map[2], "return user.name")


if __name__ == "__main__":
    unittest.main()
