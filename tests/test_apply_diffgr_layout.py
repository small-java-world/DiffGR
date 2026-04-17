import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.apply_diffgr_layout import apply_layout, main  # noqa: E402


def make_doc() -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "UT"},
        "groups": [{"id": "g1", "name": "G1", "order": 1}],
        "chunks": [
            {
                "id": "c1",
                "filePath": "src/a.ts",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 1},
                "header": "h1",
                "lines": [],
            }
        ],
        "assignments": {"g1": ["c1"]},
        "reviews": {},
    }


class TestApplyLayout(unittest.TestCase):
    # --- groups ---

    def test_groups_replaces_existing(self):
        doc = make_doc()
        layout = {"groups": [{"id": "g2", "name": "新グループ", "order": 1}]}
        out, warnings = apply_layout(doc, layout)
        self.assertEqual(len(out["groups"]), 1)
        self.assertEqual(out["groups"][0]["id"], "g2")
        self.assertEqual(out["groups"][0]["name"], "新グループ")
        self.assertEqual(warnings, [])

    def test_groups_prunes_stale_assignments(self):
        doc = make_doc()
        # g1 の assignments があるが、layout で g2 に置き換えると g1 は除去される
        layout = {"groups": [{"id": "g2", "name": "G2", "order": 1}]}
        out, _ = apply_layout(doc, layout)
        self.assertNotIn("g1", out.get("assignments", {}))

    def test_groups_prunes_stale_group_briefs(self):
        doc = make_doc()
        doc["groupBriefs"] = {"g1": {"summary": "old"}}
        layout = {"groups": [{"id": "g2", "name": "G2", "order": 1}]}
        out, _ = apply_layout(doc, layout)
        self.assertNotIn("g1", out.get("groupBriefs", {}))

    def test_groups_normalizes_order_from_index(self):
        doc = make_doc()
        layout = {
            "groups": [
                {"id": "ga", "name": "A"},  # order 省略 → index 0+1 = 1
                {"id": "gb", "name": "B"},  # order 省略 → index 1+1 = 2
            ]
        }
        out, _ = apply_layout(doc, layout)
        orders = {g["id"]: g["order"] for g in out["groups"]}
        self.assertEqual(orders["ga"], 1)
        self.assertEqual(orders["gb"], 2)

    def test_groups_rejects_duplicate_id(self):
        doc = make_doc()
        layout = {
            "groups": [
                {"id": "g1", "name": "A", "order": 1},
                {"id": "g1", "name": "B", "order": 2},
            ]
        }
        with self.assertRaises(ValueError):
            apply_layout(doc, layout)

    def test_groups_rejects_missing_id(self):
        doc = make_doc()
        layout = {"groups": [{"name": "No ID", "order": 1}]}
        with self.assertRaises(ValueError):
            apply_layout(doc, layout)

    def test_groups_rejects_missing_name(self):
        doc = make_doc()
        layout = {"groups": [{"id": "g1", "order": 1}]}
        with self.assertRaises(ValueError):
            apply_layout(doc, layout)

    # --- assignments ---

    def test_assignments_replaces_existing(self):
        doc = make_doc()
        doc["groups"].append({"id": "g2", "name": "G2", "order": 2})
        layout = {"assignments": {"g2": ["c1"]}}
        out, _ = apply_layout(doc, layout)
        self.assertNotIn("g1", out["assignments"])
        self.assertEqual(out["assignments"]["g2"], ["c1"])

    def test_assignments_warns_unknown_group(self):
        doc = make_doc()
        layout = {"assignments": {"g99": ["c1"]}}
        out, warnings = apply_layout(doc, layout)
        self.assertTrue(any("g99" in w for w in warnings))
        self.assertNotIn("g99", out["assignments"])

    def test_assignments_warns_unknown_chunk(self):
        doc = make_doc()
        layout = {"assignments": {"g1": ["c99"]}}
        _, warnings = apply_layout(doc, layout)
        self.assertTrue(any("c99" in w for w in warnings))

    def test_assignments_warns_multi_assigned_chunk(self):
        doc = make_doc()
        doc["groups"].append({"id": "g2", "name": "G2", "order": 2})
        layout = {"assignments": {"g1": ["c1"], "g2": ["c1"]}}
        out, warnings = apply_layout(doc, layout)
        self.assertTrue(any("multiple groups" in w for w in warnings))
        # c1 は最初に出現した g1 にのみ残る
        assigned_groups = [gid for gid, ids in out["assignments"].items() if "c1" in ids]
        self.assertEqual(len(assigned_groups), 1)

    def test_assignments_warns_unassigned_chunks(self):
        doc = make_doc()
        doc["groups"].append({"id": "g2", "name": "G2", "order": 2})
        # c1 を割り当てない
        layout = {"assignments": {"g2": []}}
        _, warnings = apply_layout(doc, layout)
        self.assertTrue(any("not assigned" in w for w in warnings))

    # --- groupBriefs ---

    def test_group_briefs_merges_into_existing(self):
        doc = make_doc()
        doc["groupBriefs"] = {"g1": {"status": "draft", "summary": "old"}}
        layout = {"groupBriefs": {"g1": {"summary": "new", "extra": "x"}}}
        out, _ = apply_layout(doc, layout)
        # summary は上書き、status は既存維持、extra は追加
        self.assertEqual(out["groupBriefs"]["g1"]["summary"], "new")
        self.assertEqual(out["groupBriefs"]["g1"]["status"], "draft")
        self.assertEqual(out["groupBriefs"]["g1"]["extra"], "x")

    def test_group_briefs_rejects_non_object_brief(self):
        doc = make_doc()
        layout = {"groupBriefs": {"g1": "not a dict"}}
        with self.assertRaises(ValueError):
            apply_layout(doc, layout)

    # --- 組み合わせ ---

    def test_no_layout_keys_returns_unchanged_doc(self):
        doc = make_doc()
        out, warnings = apply_layout(doc, {})
        self.assertEqual(out["groups"], doc["groups"])
        self.assertEqual(out["assignments"], doc["assignments"])
        self.assertEqual(warnings, [])

    def test_partial_layout_groups_only_preserves_existing_assignments(self):
        doc = make_doc()
        layout = {"groups": [{"id": "g1", "name": "G1 renamed", "order": 1}]}
        out, _ = apply_layout(doc, layout)
        # assignments は変更されていない（groups 置き換えで g1 は残存）
        self.assertIn("g1", out["assignments"])
        self.assertEqual(out["groups"][0]["name"], "G1 renamed")


class TestApplyDiffgrLayoutMain(unittest.TestCase):
    def _write_json(self, path: Path, obj: dict) -> None:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_main_writes_output_and_prints_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.diffgr.json"
            layout_path = root / "layout.json"
            output_path = root / "out" / "output.diffgr.json"
            self._write_json(input_path, make_doc())
            self._write_json(layout_path, {"groups": [{"id": "g1", "name": "G1", "order": 1}]})

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["--input", str(input_path), "--layout", str(layout_path), "--output", str(output_path)])

            self.assertEqual(code, 0)
            self.assertTrue(output_path.exists())
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["groups"][0]["id"], "g1")
            out_text = stdout.getvalue()
            self.assertIn("Wrote:", out_text)
            self.assertIn("Applied:", out_text)
            self.assertIn("groups", out_text)

    def test_main_warns_unknown_group_to_stderr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.diffgr.json"
            layout_path = root / "layout.json"
            output_path = root / "output.diffgr.json"
            self._write_json(input_path, make_doc())
            self._write_json(layout_path, {"assignments": {"g99": ["c1"]}})

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main(["--input", str(input_path), "--layout", str(layout_path), "--output", str(output_path)])

            self.assertEqual(code, 0)
            self.assertIn("[warn]", stderr.getvalue())
            self.assertIn("g99", stderr.getvalue())

    def test_main_returns_1_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "input.diffgr.json"
            layout_path = root / "layout.json"
            output_path = root / "output.diffgr.json"
            input_path.write_text("not json", encoding="utf-8")
            self._write_json(layout_path, {})

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main(["--input", str(input_path), "--layout", str(layout_path), "--output", str(output_path)])

            self.assertEqual(code, 1)
            self.assertIn("[error]", stderr.getvalue())

    def test_main_returns_1_on_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            missing = root / "nonexistent.json"
            layout_path = root / "layout.json"
            output_path = root / "output.diffgr.json"
            self._write_json(layout_path, {})

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main(["--input", str(missing), "--layout", str(layout_path), "--output", str(output_path)])

            self.assertEqual(code, 1)
            self.assertIn("[error]", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
