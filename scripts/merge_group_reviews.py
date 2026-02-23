#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_split import merge_reviews_into_base  # noqa: E402
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge reviews from per-group DiffGR files into one base DiffGR file.")
    parser.add_argument("--base", required=True, help="Base DiffGR JSON path.")
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Input reviewer DiffGR path. Repeatable.",
    )
    parser.add_argument(
        "--input-glob",
        action="append",
        default=[],
        help="Glob pattern for reviewer files. Repeatable.",
    )
    parser.add_argument("--output", required=True, help="Output merged DiffGR JSON path.")
    parser.add_argument(
        "--clear-base-reviews",
        action="store_true",
        help="Start from empty reviews before merging inputs.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat unknown chunk ids / invalid review record as error.",
    )
    return parser.parse_args(argv)


def _collect_input_paths(raw_inputs: list[str], raw_globs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for item in raw_inputs:
        path = Path(item)
        if not path.is_absolute():
            path = ROOT / path
        paths.append(path.resolve())

    for pattern in raw_globs:
        expanded = glob.glob(str(ROOT / pattern), recursive=True)
        for matched in expanded:
            path = Path(matched).resolve()
            if path.is_file():
                paths.append(path)

    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    unique.sort(key=lambda item: str(item).lower())
    return unique


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    base_path = Path(args.base)
    if not base_path.is_absolute():
        base_path = ROOT / base_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    input_paths = _collect_input_paths(args.input, args.input_glob)
    if not input_paths:
        print("[error] no input review files. use --input or --input-glob", file=sys.stderr)
        return 2

    try:
        base_doc = load_json(base_path.resolve())
        validate_document(base_doc)
        review_docs: list[tuple[str, dict[str, object]]] = []
        for path in input_paths:
            review_doc = load_json(path)
            validate_document(review_doc)
            review_docs.append((str(path), review_doc))

        merged_doc, warnings, applied = merge_reviews_into_base(
            base_doc,
            review_docs,
            clear_base_reviews=bool(args.clear_base_reviews),
            strict=bool(args.strict),
        )
        validate_document(merged_doc)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(merged_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    print(f"Wrote: {output_path}")
    print(f"Merged files: {len(input_paths)}")
    print(f"Applied reviews: {applied}")
    if warnings:
        for warning in warnings:
            print(f"[warning] {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
