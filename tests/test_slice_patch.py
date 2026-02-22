import copy
import unittest

from diffgr.slice_patch import apply_slice_patch


def make_doc():
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "UT", "createdAt": "2026-02-22T00:00:00Z"},
        "groups": [
            {"id": "g1", "name": "G1", "order": 1},
            {"id": "g2", "name": "G2", "order": 2},
        ],
        "chunks": [
            {"id": "c1", "filePath": "a", "old": {"start": 1, "count": 1}, "new": {"start": 1, "count": 1}, "lines": []},
            {"id": "c2", "filePath": "b", "old": {"start": 1, "count": 1}, "new": {"start": 1, "count": 1}, "lines": []},
        ],
        "assignments": {"g1": ["c1", "c2"]},
        "reviews": {},
    }


class TestSlicePatch(unittest.TestCase):
    def test_apply_slice_patch_renames_and_moves(self):
        doc = make_doc()
        patch = {"rename": {"g1": "計算", "g2": "正規化"}, "move": [{"chunk": "c2", "to": "g2"}]}
        new_doc = apply_slice_patch(copy.deepcopy(doc), patch)
        names = {g["id"]: g["name"] for g in new_doc["groups"]}
        self.assertEqual(names["g1"], "計算")
        self.assertEqual(names["g2"], "正規化")
        self.assertEqual(new_doc["assignments"]["g1"], ["c1"])
        self.assertEqual(new_doc["assignments"]["g2"], ["c2"])

    def test_apply_slice_patch_rejects_unknown_ids(self):
        doc = make_doc()
        with self.assertRaises(RuntimeError):
            apply_slice_patch(copy.deepcopy(doc), {"move": [{"chunk": "c99", "to": "g2"}]})
        with self.assertRaises(RuntimeError):
            apply_slice_patch(copy.deepcopy(doc), {"move": [{"chunk": "c1", "to": "g99"}]})


if __name__ == "__main__":
    unittest.main()

