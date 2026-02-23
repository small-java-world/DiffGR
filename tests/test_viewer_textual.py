import asyncio
import unittest
from pathlib import Path

from diffgr.viewer_textual import DiffgrTextualApp, build_group_diff_report_rows, format_file_label
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
        self.assertEqual(done_cell, "[x]")

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
        self.assertEqual(done_cell, "[ ]")

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
