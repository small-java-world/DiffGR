import unittest
from pathlib import Path

from diffgr.viewer_textual import DiffgrTextualApp, build_group_diff_report_rows, format_file_label


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
        self.assertIn("file", kinds)
        self.assertIn("chunk", kinds)
        self.assertIn("add", kinds)
        self.assertIn("delete", kinds)
        self.assertTrue(any("=== a.ts (src) ===" in row.old_text for row in rows))
        self.assertTrue(any("=== b.ts (src) ===" in row.old_text for row in rows))

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


if __name__ == "__main__":
    unittest.main()
