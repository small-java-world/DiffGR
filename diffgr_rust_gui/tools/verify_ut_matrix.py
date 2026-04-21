#!/usr/bin/env python3
"""Static unit-test coverage gate for the Rust DiffGR project.

This does not replace `cargo test`; it verifies that the checked-in UT suite covers
all intended feature buckets before Cargo is available on a machine.  The scanner
is intentionally line-based rather than regex-based so large Rust sources cannot
trigger catastrophic backtracking.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def count_tests(path: Path) -> tuple[int, list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    names: list[str] = []
    count = 0
    for index, line in enumerate(lines):
        if line.strip() != "#[test]":
            continue
        count += 1
        for next_line in lines[index + 1:index + 8]:
            stripped = next_line.strip()
            if stripped.startswith("fn ") or stripped.startswith("pub fn "):
                fn_part = stripped.split("fn ", 1)[1]
                name = fn_part.split("(", 1)[0].strip()
                if name:
                    names.append(name)
                break
    return count, names


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify the Rust UT matrix.")
    parser.add_argument("--matrix", default="UT_MATRIX.json")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list", action="store_true", help="Print per-file test counts.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    matrix_path = root / args.matrix
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))

    all_files = sorted(
        set(str(p.relative_to(root)) for p in root.glob("tests/*.rs"))
        | set(str(p.relative_to(root)) for p in root.glob("src/*.rs"))
        | set(str(p.relative_to(root)) for p in root.glob("src/bin/*.rs"))
    )
    file_counts: dict[str, int] = {}
    test_names: dict[str, list[str]] = {}
    missing_files: list[str] = []
    duplicate_names: list[str] = []
    seen_names: dict[str, str] = {}

    for rel in all_files:
        path = root / rel
        if not path.exists():
            missing_files.append(rel)
            continue
        count, names = count_tests(path)
        file_counts[rel] = count
        test_names[rel] = names
        for name in names:
            if name in seen_names:
                duplicate_names.append(f"{name}: {seen_names[name]} and {rel}")
            seen_names[name] = rel

    category_results = []
    for category in matrix.get("categories", []):
        files = category.get("files", [])
        missing = [rel for rel in files if not (root / rel).exists()]
        text = "\n".join((root / rel).read_text(encoding="utf-8") for rel in files if (root / rel).exists())
        count = sum(file_counts.get(rel, 0) for rel in files)
        missing_keywords = [kw for kw in category.get("keywords", []) if kw not in text]
        ok = not missing and count >= int(category.get("minimumTestCount", 0)) and not missing_keywords
        category_results.append({
            "name": category.get("name"),
            "ok": ok,
            "testCount": count,
            "minimumTestCount": category.get("minimumTestCount", 0),
            "missingFiles": missing,
            "missingKeywords": missing_keywords,
        })

    total = sum(file_counts.values())
    result = {
        "ok": total >= int(matrix.get("minimumRustTestCount", 0))
        and not missing_files
        and not duplicate_names
        and all(row["ok"] for row in category_results),
        "totalRustTests": total,
        "minimumRustTestCount": matrix.get("minimumRustTestCount", 0),
        "fileCounts": file_counts,
        "categories": category_results,
        "missingFiles": missing_files,
        "duplicateTestNames": duplicate_names,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.list:
        for rel, count in sorted(file_counts.items()):
            print(f"{count:3d} {rel}")
        print(f"total {total}")
    else:
        status = "ok" if result["ok"] else "failed"
        print(f"UT matrix {status}: {total} Rust tests")
        for row in category_results:
            mark = "ok" if row["ok"] else "NG"
            print(f"- {mark}: {row['name']} ({row['testCount']}/{row['minimumTestCount']})")
        if duplicate_names:
            print("duplicate test names:", file=sys.stderr)
            for item in duplicate_names:
                print(f"  {item}", file=sys.stderr)
        if missing_files:
            print("missing files:", file=sys.stderr)
            for item in missing_files:
                print(f"  {item}", file=sys.stderr)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
