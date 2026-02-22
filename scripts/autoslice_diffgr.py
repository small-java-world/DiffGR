#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.autoslice import autoslice_document_by_commits  # noqa: E402
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-slice a DiffGR document into virtual PR groups.")
    parser.add_argument("--repo", default=".", help="Path to git repository (default: current directory).")
    parser.add_argument("--base", default="samples/ts20-base", help="Base ref for slicing (default: samples/ts20-base).")
    parser.add_argument(
        "--feature",
        default="samples/ts20-feature-5pr",
        help="Feature ref for slicing (default: samples/ts20-feature-5pr).",
    )
    parser.add_argument(
        "--input",
        default="samples/diffgr/ts20-5pr.diffgr.json",
        help="Input DiffGR JSON path (default: samples/diffgr/ts20-5pr.diffgr.json).",
    )
    parser.add_argument(
        "--output",
        default="samples/diffgr/ts20-5pr.autosliced.diffgr.json",
        help="Output DiffGR JSON path.",
    )
    parser.add_argument("--max-commits", type=int, default=50, help="Max commits to slice (default: 50).")
    parser.add_argument(
        "--name-style",
        choices=["subject", "pr"],
        default="subject",
        help="Group naming style (default: subject).",
    )
    parser.add_argument(
        "--no-split",
        action="store_true",
        help="Do not split multi-change hunks into smaller chunks before assignment.",
    )
    parser.add_argument(
        "--context-lines",
        type=int,
        default=3,
        help="Context lines to include around each change block when splitting (default: 3).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo = Path(args.repo).resolve()
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = repo / input_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = repo / output_path

    try:
        doc = load_json(input_path)
        validate_document(doc)
        new_doc, warnings = autoslice_document_by_commits(
            repo=repo,
            doc=doc,
            base_ref=args.base,
            feature_ref=args.feature,
            max_commits=args.max_commits,
            name_style=args.name_style,
            split_chunks=not args.no_split,
            context_lines=args.context_lines,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            __import__("json").dumps(new_doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    meta = new_doc.get("meta", {}).get("x-autoslice", {})
    commit_count = len(meta.get("commits", []) or [])
    unassigned_count = int(meta.get("unassignedCount", 0))
    print(f"Wrote: {output_path}")
    print(f"Groups: {commit_count}")
    print(f"Unassigned: {unassigned_count}")
    if warnings:
        for warning in warnings:
            print(f"[warning] {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
