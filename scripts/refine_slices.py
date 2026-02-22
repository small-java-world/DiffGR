#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.slice_refine import build_ai_refine_prompt_markdown, refine_group_names_ja  # noqa: E402
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refine DiffGR slicing (rename groups, emit AI prompt).")
    parser.add_argument(
        "--input",
        default="samples/diffgr/ts20-5pr.autosliced.diffgr.json",
        help="Input DiffGR JSON path.",
    )
    parser.add_argument(
        "--output",
        default="samples/diffgr/ts20-5pr.refined.diffgr.json",
        help="Output DiffGR JSON path.",
    )
    parser.add_argument(
        "--write-prompt",
        default="samples/diffgr/ts20-5pr.refine-prompt.md",
        help="Write an AI refinement prompt markdown to this path.",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Do not write prompt markdown.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo = ROOT
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = repo / input_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = repo / output_path

    try:
        doc = load_json(input_path)
        validate_document(doc)
        refined = refine_group_names_ja(doc)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(refined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    if not args.no_prompt:
        prompt_path = Path(args.write_prompt)
        if not prompt_path.is_absolute():
            prompt_path = repo / prompt_path
        prompt_path.write_text(build_ai_refine_prompt_markdown(refined), encoding="utf-8")

    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

