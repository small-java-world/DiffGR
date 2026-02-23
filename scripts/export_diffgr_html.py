#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.html_report import render_group_diff_html  # noqa: E402
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export DiffGR group diff report as HTML.")
    parser.add_argument("--input", required=True, help="Input .diffgr.json path.")
    parser.add_argument("--output", required=True, help="Output HTML path.")
    parser.add_argument(
        "--group",
        default="all",
        help="Group selector. Use group id (e.g. g-pr01) or exact group name (e.g. 計算倍率変更). Default: all.",
    )
    parser.add_argument("--title", help="Optional custom report title.")
    parser.add_argument("--save-reviews-url", help="Optional POST endpoint to save reviews from HTML.")
    parser.add_argument("--save-reviews-label", default="Save to App", help="Label for save button.")
    parser.add_argument("--open", action="store_true", help="Open the generated HTML in your default browser.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    try:
        doc = load_json(input_path)
        validate_document(doc)
        html = render_group_diff_html(
            doc,
            group_selector=args.group,
            report_title=args.title,
            save_reviews_url=args.save_reviews_url,
            save_reviews_label=args.save_reviews_label,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    print(f"Wrote: {output_path}")
    if args.open:
        webbrowser.open(output_path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
