#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.autoslice import autoslice_document_by_commits  # noqa: E402
from diffgr.generator import build_diffgr_document, parse_generate_args  # noqa: E402
from diffgr.slice_refine import refine_group_names_ja  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate -> autoslice -> refine (one command).")
    parser.add_argument("--repo", default=".", help="Path to git repository (default: current directory).")
    parser.add_argument("--base", default="samples/ts20-base", help="Base ref.")
    parser.add_argument("--feature", default="samples/ts20-feature-5pr", help="Feature ref.")
    parser.add_argument("--title", default="DiffGR review bundle", help="meta.title")
    parser.add_argument("--no-patch", action="store_true", help="Do not include optional patch field.")
    parser.add_argument(
        "--output",
        default="samples/diffgr/ts20-5pr.review.diffgr.json",
        help="Output DiffGR JSON path.",
    )
    parser.add_argument("--name-style", choices=["subject", "pr"], default="pr", help="Autoslice group naming.")
    parser.add_argument("--max-commits", type=int, default=50, help="Max commits to slice.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo = Path(args.repo).resolve()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = repo / output_path

    try:
        base_doc = build_diffgr_document(
            repo=repo,
            base_ref=args.base,
            feature_ref=args.feature,
            title=args.title,
            include_patch=not args.no_patch,
        )
        autosliced, warnings = autoslice_document_by_commits(
            repo=repo,
            doc=base_doc,
            base_ref=args.base,
            feature_ref=args.feature,
            max_commits=args.max_commits,
            name_style=args.name_style,
            split_chunks=True,
            context_lines=3,
        )
        refined = refine_group_names_ja(autosliced)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(refined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    print(f"Wrote: {output_path}")
    if warnings:
        for warning in warnings:
            print(f"[warning] {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

