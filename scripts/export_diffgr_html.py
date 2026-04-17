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
from diffgr.impact_merge import build_impact_preview_report, preview_impact_merge  # noqa: E402
from diffgr.review_state import apply_review_state, build_review_state_diff_report, extract_review_state, load_review_state, review_state_fingerprint  # noqa: E402
from diffgr.viewer_core import load_json, print_error, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export DiffGR group diff report as HTML.")
    parser.add_argument("--input", required=True, help="Input .diffgr.json path.")
    parser.add_argument("--output", required=True, help="Output HTML path.")
    parser.add_argument("--state", help="Optional external state JSON to overlay before rendering.")
    parser.add_argument(
        "--group",
        default="all",
        help="Group selector. Use group id (e.g. g-pr01) or exact group name (e.g. 計算倍率変更). Default: all.",
    )
    parser.add_argument("--title", help="Optional custom report title.")
    parser.add_argument("--save-state-url", help="Optional POST endpoint to save review state from HTML.")
    parser.add_argument("--save-state-label", default="Save State", help="Label for save button.")
    parser.add_argument("--impact-old", help="Optional old .diffgr.json path for Impact Preview.")
    parser.add_argument("--impact-state", help="Optional review state JSON path for Impact Preview.")
    parser.add_argument("--open", action="store_true", help="Open the generated HTML in your default browser.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    state_path = Path(args.state) if args.state else None
    if state_path is not None and not state_path.is_absolute():
        state_path = ROOT / state_path
    impact_old_path = Path(args.impact_old) if args.impact_old else None
    if impact_old_path is not None and not impact_old_path.is_absolute():
        impact_old_path = ROOT / impact_old_path
    impact_state_path = Path(args.impact_state) if args.impact_state else None
    if impact_state_path is not None and not impact_state_path.is_absolute():
        impact_state_path = ROOT / impact_state_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    try:
        if bool(impact_old_path) != bool(impact_state_path):
            raise RuntimeError("--impact-old and --impact-state must be provided together.")
        if state_path is not None and impact_state_path is not None and state_path.resolve() != impact_state_path.resolve():
            raise RuntimeError("--state and --impact-state must point to the same state file.")
        doc = load_json(input_path)
        validate_document(doc)
        impact_preview_payload = None
        impact_preview_report = None
        impact_preview_label = None
        if impact_old_path is not None and impact_state_path is not None:
            old_doc = load_json(impact_old_path)
            validate_document(old_doc)
            impact_state = load_review_state(impact_state_path)
            impact_preview_payload = preview_impact_merge(
                old_doc=old_doc,
                new_doc=doc,
                state=impact_state,
            )
            impact_preview_label = f"{impact_old_path.name} -> {input_path.name} using {impact_state_path.name}"
            impact_preview_report = build_impact_preview_report(
                impact_preview_payload,
                old_label=impact_old_path.name,
                new_label=input_path.name,
                state_label=impact_state_path.name,
            )
            impact_state_fingerprint = review_state_fingerprint(impact_state)
        else:
            impact_state_fingerprint = None
        state_diff_report = None
        if state_path is not None:
            imported_state = load_review_state(state_path)
            base_state = extract_review_state(doc)
            doc = apply_review_state(doc, imported_state)
            state_diff_report = build_review_state_diff_report(
                base_state,
                imported_state,
                source_label=str(state_path.name),
            )
        html = render_group_diff_html(
            doc,
            group_selector=args.group,
            report_title=args.title,
            save_state_url=args.save_state_url,
            save_state_label=args.save_state_label,
            state_source_label=str(state_path.name) if state_path is not None else None,
            state_diff_report=state_diff_report,
            impact_preview_payload=impact_preview_payload,
            impact_preview_report=impact_preview_report,
            impact_preview_label=impact_preview_label,
            impact_state_label=str(impact_state_path.name) if impact_state_path is not None else None,
            impact_state_fingerprint=impact_state_fingerprint,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    print(f"Wrote: {output_path}")
    if args.open:
        webbrowser.open(output_path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
