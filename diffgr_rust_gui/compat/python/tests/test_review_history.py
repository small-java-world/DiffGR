import unittest

from diffgr.review_history import append_review_history, build_rebase_history_entry


class TestReviewHistory(unittest.TestCase):
    def test_build_rebase_history_entry_contains_impacted_and_unaffected(self):
        old_doc = {
            "meta": {
                "title": "old",
                "source": {
                    "type": "git_compare",
                    "base": "main",
                    "head": "feature",
                    "baseSha": "a" * 40,
                    "headSha": "b" * 40,
                },
            }
        }
        new_doc = {
            "meta": {
                "title": "new",
                "source": {
                    "type": "git_compare",
                    "base": "main",
                    "head": "feature2",
                    "baseSha": "a" * 40,
                    "headSha": "c" * 40,
                },
            }
        }
        summary = {
            "matchedStrong": 10,
            "matchedStable": 2,
            "matchedDelta": 1,
            "matchedSimilar": 3,
            "carriedReviews": 11,
            "carriedReviewed": 9,
            "changedToNeedsReReview": 3,
            "unmappedNewChunks": 4,
        }
        impact = {
            "grouping": "old",
            "coverageNew": {"ok": True, "unassigned": [], "duplicated": {}, "unknown_groups": [], "unknown_chunks": {}},
            "newOnlyChunkIds": ["n1"],
            "oldOnlyChunkIds": ["o1"],
            "match": {"counts": {"strong": 10, "stable": 2, "delta": 1, "similar": 3}},
            "groups": [
                {
                    "id": "g1",
                    "name": "A",
                    "order": 1,
                    "action": "review",
                    "changed": 1,
                    "removed": 0,
                    "new": 0,
                    "unchanged": 3,
                    "changedChunkIds": ["c1"],
                    "removedChunkIds": [],
                    "newChunkIds": [],
                    "unchangedChunkIds": ["c2", "c3", "c4"],
                },
                {
                    "id": "g2",
                    "name": "B",
                    "order": 2,
                    "action": "skip",
                    "changed": 0,
                    "removed": 0,
                    "new": 0,
                    "unchanged": 5,
                    "changedChunkIds": [],
                    "removedChunkIds": [],
                    "newChunkIds": [],
                    "unchangedChunkIds": ["x1"],
                },
            ],
        }

        entry = build_rebase_history_entry(
            old_doc=old_doc,
            new_doc=new_doc,
            summary=summary,
            impact=impact,
            old_path="old.json",
            new_path="new.json",
            output_path="out.json",
            keep_new_groups=False,
            carry_line_comments=True,
            similarity_threshold=0.86,
            warnings=[],
            label="fix-1",
            actor="alice",
        )
        self.assertEqual(entry["type"], "rebase")
        self.assertEqual(entry["label"], "fix-1")
        self.assertEqual(entry["actor"], "alice")
        scope = entry["impactScope"]
        self.assertEqual(scope["impactedGroupCount"], 1)
        self.assertEqual(scope["unaffectedGroupCount"], 1)
        self.assertEqual(scope["impactedGroups"][0]["id"], "g1")
        self.assertEqual(scope["unaffectedGroups"][0]["id"], "g2")
        self.assertIn("changedChunkIdsTruncated", scope["impactedGroups"][0])
        self.assertEqual(scope["impactedGroups"][0]["changedChunkIdsTruncated"], 0)

    def test_build_rebase_history_entry_caps_chunk_ids_per_group(self):
        old_doc = {"meta": {"title": "old"}}
        new_doc = {"meta": {"title": "new"}}
        summary = {
            "matchedStrong": 0,
            "matchedStable": 0,
            "matchedDelta": 0,
            "matchedSimilar": 0,
            "carriedReviews": 0,
            "carriedReviewed": 0,
            "changedToNeedsReReview": 0,
            "unmappedNewChunks": 0,
        }
        impact = {
            "grouping": "old",
            "coverageNew": {"ok": True, "unassigned": [], "duplicated": {}, "unknown_groups": [], "unknown_chunks": {}},
            "newOnlyChunkIds": [],
            "oldOnlyChunkIds": [],
            "match": {"counts": {"strong": 0, "stable": 0, "delta": 0, "similar": 0}},
            "groups": [
                {
                    "id": "g1",
                    "name": "A",
                    "action": "review",
                    "changed": 3,
                    "removed": 0,
                    "new": 0,
                    "unchanged": 0,
                    "changedChunkIds": ["c1", "c2", "c3"],
                }
            ],
        }
        entry = build_rebase_history_entry(
            old_doc=old_doc,
            new_doc=new_doc,
            summary=summary,
            impact=impact,
            old_path="old.json",
            new_path="new.json",
            output_path="out.json",
            keep_new_groups=False,
            carry_line_comments=True,
            similarity_threshold=0.86,
            warnings=[],
            max_ids_per_group=2,
        )
        impacted = entry["impactScope"]["impactedGroups"][0]
        self.assertEqual(impacted["changedChunkIds"], ["c1", "c2"])
        self.assertEqual(impacted["changedChunkIdsTruncated"], 1)

    def test_append_review_history_keeps_last_n(self):
        doc = {"meta": {"title": "x"}}
        append_review_history(doc, {"type": "rebase", "n": 1, "impactScope": {"impactedGroupCount": 1}}, max_entries=2)
        append_review_history(doc, {"type": "rebase", "n": 2, "impactScope": {"impactedGroupCount": 2}}, max_entries=2)
        append_review_history(doc, {"type": "rebase", "n": 3, "impactScope": {"impactedGroupCount": 3}}, max_entries=2)
        history = doc["meta"]["x-reviewHistory"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["n"], 2)
        self.assertEqual(history[1]["n"], 3)
        self.assertEqual(doc["meta"]["x-impactScope"]["impactedGroupCount"], 3)


if __name__ == "__main__":
    unittest.main()
