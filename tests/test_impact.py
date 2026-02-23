import unittest

from diffgr.impact import build_impact_report


def make_doc(*, title: str, groups: list[dict], chunks: list[dict], assignments: dict) -> dict:
    return {
        "format": "diffgr",
        "version": 1,
        "meta": {"title": title, "createdAt": "2026-02-23T00:00:00Z"},
        "groups": groups,
        "chunks": chunks,
        "assignments": assignments,
        "reviews": {},
    }


def make_chunk(*, chunk_id: str, file_path: str, header: str, lines: list[dict]) -> dict:
    return {
        "id": chunk_id,
        "filePath": file_path,
        "old": {"start": 1, "count": 1},
        "new": {"start": 1, "count": 1},
        "header": header,
        "lines": lines,
    }


class TestImpactReport(unittest.TestCase):
    def test_group_impact_classification_old_grouping(self):
        old_doc = make_doc(
            title="old",
            groups=[{"id": "g1", "name": "G1", "order": 1}, {"id": "g2", "name": "G2", "order": 2}],
            chunks=[
                make_chunk(
                    chunk_id="old1",
                    file_path="src/a.ts",
                    header="h1",
                    lines=[
                        {"kind": "context", "text": "const x = 1;", "oldLine": 1, "newLine": 1},
                        {"kind": "add", "text": "return x + 1;", "oldLine": None, "newLine": 2},
                    ],
                ),
                make_chunk(
                    chunk_id="old2",
                    file_path="src/b.ts",
                    header="h2",
                    lines=[
                        {"kind": "add", "text": "return 1;", "oldLine": None, "newLine": 1},
                    ],
                ),
            ],
            assignments={"g1": ["old1"], "g2": ["old2"]},
        )

        new_doc = make_doc(
            title="new",
            groups=[{"id": "g-all", "name": "All", "order": 1}],
            chunks=[
                # old1: context changed but add/delete identical -> delta (no impact)
                make_chunk(
                    chunk_id="new1",
                    file_path="src/a.ts",
                    header="h1",
                    lines=[
                        {"kind": "context", "text": "const x = 2;", "oldLine": 1, "newLine": 1},
                        {"kind": "add", "text": "return x + 1;", "oldLine": None, "newLine": 2},
                    ],
                ),
                # old2: add line changed -> similar (impact)
                make_chunk(
                    chunk_id="new2",
                    file_path="src/b.ts",
                    header="h2",
                    lines=[
                        {"kind": "add", "text": "return 2;", "oldLine": None, "newLine": 1},
                    ],
                ),
                # new-only chunk
                make_chunk(
                    chunk_id="new3",
                    file_path="src/c.ts",
                    header="h3",
                    lines=[
                        {"kind": "add", "text": "new stuff", "oldLine": None, "newLine": 1},
                    ],
                ),
            ],
            assignments={"g-all": ["new1", "new2", "new3"]},
        )

        report = build_impact_report(old_doc=old_doc, new_doc=new_doc, grouping="old", similarity_threshold=0.70)

        counts = report["match"]["counts"]
        self.assertEqual(counts["delta"], 1)
        self.assertEqual(counts["similar"], 1)
        self.assertEqual(report["match"]["newOnly"], 1)

        groups = {g["id"]: g for g in report["groups"]}
        self.assertEqual(groups["g1"]["action"], "skip")
        self.assertEqual(groups["g1"]["changed"], 0)
        self.assertEqual(groups["g1"]["unchanged"], 1)
        self.assertEqual(groups["g2"]["action"], "review")
        self.assertEqual(groups["g2"]["changed"], 1)

        new_only = report["newOnlyChunks"]
        self.assertEqual(len(new_only), 1)
        self.assertEqual(new_only[0]["id"], "new3")


if __name__ == "__main__":
    unittest.main()

