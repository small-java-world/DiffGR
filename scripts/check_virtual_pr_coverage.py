#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.virtual_pr_coverage import (  # noqa: E402
    analyze_virtual_pr_coverage,
    build_ai_fix_coverage_prompt_markdown,
    coverage_issue_to_json,
)
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check that virtual PR assignments cover all chunks exactly once.")
    parser.add_argument("--input", required=True, help="Input .diffgr.json path.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output result as JSON.")
    parser.add_argument("--write-prompt", help="Write an AI fix prompt markdown to this path.")
    parser.add_argument("--max-chunks-per-group", type=int, default=20, help="Max sample chunks per group in prompt.")
    parser.add_argument("--max-problem-chunks", type=int, default=80, help="Max problem chunks in prompt sections.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path

    try:
        doc = load_json(input_path.resolve())
        warnings = validate_document(doc)
        issue = analyze_virtual_pr_coverage(doc)
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    if args.as_json:
        print(coverage_issue_to_json(issue))
    else:
        chunk_count = len([c for c in doc.get("chunks", []) if isinstance(c, dict)])
        group_count = len([g for g in doc.get("groups", []) if isinstance(g, dict)])
        print(f"Chunks: {chunk_count}")
        print(f"Groups: {group_count}")
        print(f"Unassigned: {len(issue.unassigned)}")
        print(f"Duplicated: {len(issue.duplicated)}")
        print(f"Unknown groups in assignments: {len(issue.unknown_groups)}")
        print(f"Unknown chunks in assignments: {len(issue.unknown_chunks)}")
        if warnings:
            print(f"Document warnings: {len(warnings)}", file=sys.stderr)
            for warning in warnings:
                print(f"[warning] {warning}", file=sys.stderr)

    if args.write_prompt and not issue.ok:
        prompt_path = Path(args.write_prompt)
        if not prompt_path.is_absolute():
            prompt_path = ROOT / prompt_path
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(
            build_ai_fix_coverage_prompt_markdown(
                doc,
                issue,
                max_chunks_per_group=max(1, int(args.max_chunks_per_group)),
                max_problem_chunks=max(1, int(args.max_problem_chunks)),
            ),
            encoding="utf-8",
        )
        print(f"Wrote prompt: {prompt_path}")

    return 0 if issue.ok else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
