#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_state import build_merge_preview_report, format_merge_preview_text, load_review_state, preview_merge_review_states  # noqa: E402
from diffgr.viewer_core import print_error, print_json, print_warning, resolve_script_path, write_json  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge multiple DiffGR state JSON files deterministically.")
    parser.add_argument("--base", required=True, help="Base state JSON path.")
    parser.add_argument("--input", action="append", default=[], help="Input state JSON path. Repeatable.")
    parser.add_argument("--input-glob", action="append", default=[], help="Input glob for state JSON files. Repeatable.")
    parser.add_argument("--output", help="Output state JSON path.")
    parser.add_argument("--preview", action="store_true", help="Preview merge result without writing output.")
    parser.add_argument("--json-summary", action="store_true", help="Print summary as JSON.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    base_path = resolve_script_path(args.base, ROOT)
    if not args.preview and not args.output:
        print("[error] --output is required unless --preview is used.", file=sys.stderr)
        return 1
    output_path = resolve_script_path(args.output, ROOT) if args.output else None

    input_paths: list[Path] = []
    for item in args.input:
        input_paths.append(resolve_script_path(item, ROOT))
    for pattern in args.input_glob:
        expanded = sorted(glob.glob(pattern))
        if not expanded:
            print_warning(f"No files matched glob: {pattern}")
        for item in expanded:
            input_paths.append(resolve_script_path(item, ROOT))

    unique_inputs: list[Path] = []
    seen: set[str] = set()
    for path in input_paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_inputs.append(path)

    try:
        base_state = load_review_state(base_path)
        incoming_states = [(str(path), load_review_state(path)) for path in unique_inputs]
        preview = preview_merge_review_states(base_state, incoming_states)
        merged = preview["mergedState"]
        warnings = preview["warnings"]
        applied = int(preview["applied"])
        summary = preview["summary"]
        if not args.preview and output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(output_path, merged)
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    if args.json_summary:
        print_json({
            "base": str(base_path),
            "inputs": [str(path) for path in unique_inputs],
            "output": str(output_path) if output_path is not None else "",
            "preview": bool(args.preview),
            "appliedReviews": applied,
            "warningCount": len(warnings),
            "warnings": warnings,
            "summary": summary,
            "report": build_merge_preview_report(preview, target_label=str(base_path)),
        })
    else:
        if args.preview:
            print(f"Preview: {base_path}")
        else:
            print(f"Wrote: {output_path}")
        print(format_merge_preview_text(preview, target_label=str(base_path)))
        if warnings:
            for warning in warnings:
                print_warning(warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
