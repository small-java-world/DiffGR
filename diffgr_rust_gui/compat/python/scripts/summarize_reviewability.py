#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.reviewability import compute_all_group_reviewability, reviewability_report_to_json  # noqa: E402
from diffgr.viewer_core import load_json, print_error, print_warning, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize reviewability for each DiffGR group.")
    parser.add_argument("--input", required=True, help="Input .diffgr.json path.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON.")
    return parser.parse_args(argv)


def _print_rows(rows: list[dict[str, object]]) -> None:
    for row in rows:
        reasons = ", ".join(str(reason) for reason in row.get("reasons", []))
        verdict = str(row.get("verdict", ""))
        chunk_count = row.get("chunkCount")
        file_count = row.get("fileCount")
        reviewed = row.get("reviewedCount")
        total = row.get("totalCount")
        suffix = f" — {reasons}" if reasons else ""
        print(
            f"[info] {row.get('groupId')} ({row.get('groupName')}): {verdict} "
            f"[{reviewed}/{total}] chunks={chunk_count} files={file_count}{suffix}"
        )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input).resolve()
    try:
        doc = load_json(input_path)
        warnings = validate_document(doc)
        for warning in warnings:
            print_warning(warning)
        rows = compute_all_group_reviewability(doc)
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    if args.as_json:
        print(reviewability_report_to_json(rows))
    else:
        _print_rows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
