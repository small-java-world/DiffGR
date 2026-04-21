#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_rebase import rebase_review_state  # noqa: E402
from diffgr.review_state import apply_review_state, extract_review_state, load_diffgr_document, load_review_state  # noqa: E402
from diffgr.viewer_core import print_error, print_json, print_warning, resolve_script_path, write_json  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebase standalone DiffGR state JSON from old snapshot to new snapshot.")
    parser.add_argument("--old", required=True, help="Old DiffGR JSON path.")
    parser.add_argument("--new", required=True, help="New DiffGR JSON path.")
    parser.add_argument("--state", required=True, help="Input state JSON path extracted from old snapshot.")
    parser.add_argument("--output", required=True, help="Output rebased state JSON path.")
    parser.add_argument(
        "--keep-new-groups",
        action="store_true",
        help="Keep groups/assignments from --new (default: preserve --old groups/assignments for matched chunks).",
    )
    parser.add_argument(
        "--no-line-comments",
        action="store_true",
        help="Do not carry lineComments (default: carry only for stable/strong matches with safe remap).",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.86,
        help="Similarity threshold (0-1) to detect 'changed but same chunk' and mark reviewed -> needsReReview.",
    )
    parser.add_argument("--json-summary", action="store_true", help="Print summary as JSON.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    old_path = resolve_script_path(args.old, ROOT)
    new_path = resolve_script_path(args.new, ROOT)
    state_path = resolve_script_path(args.state, ROOT)
    output_path = resolve_script_path(args.output, ROOT)

    try:
        old_doc = load_diffgr_document(old_path)
        new_doc = load_diffgr_document(new_path)
        state = load_review_state(state_path)
        old_doc_with_state = apply_review_state(old_doc, state)
        out_doc, summary, warnings = rebase_review_state(
            old_doc=old_doc_with_state,
            new_doc=new_doc,
            preserve_groups=not bool(args.keep_new_groups),
            carry_line_comments=not bool(args.no_line_comments),
            similarity_threshold=float(args.similarity_threshold),
        )
        out_state = extract_review_state(out_doc)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(output_path, out_state)
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    if args.json_summary:
        print_json({
            "matchedStrong": summary.matched_strong,
            "matchedStable": summary.matched_stable,
            "matchedDelta": summary.matched_delta,
            "matchedSimilar": summary.matched_similar,
            "carriedReviews": summary.carried_reviews,
            "carriedReviewed": summary.carried_reviewed,
            "changedToNeedsReReview": summary.changed_to_needs_rereview,
            "unmappedNewChunks": summary.unmapped_new_chunks,
            "warnings": warnings,
        })
    else:
        print(f"Wrote: {output_path}")
        print(f"Matched (strong): {summary.matched_strong}")
        print(f"Matched (stable): {summary.matched_stable}")
        print(f"Matched (delta): {summary.matched_delta}")
        print(f"Matched (similar): {summary.matched_similar}")
        print(f"Carried reviews: {summary.carried_reviews} (reviewed={summary.carried_reviewed})")
        print(f"Changed -> needsReReview: {summary.changed_to_needs_rereview}")
        print(f"Unmapped new chunks: {summary.unmapped_new_chunks}")
        if warnings:
            for warning in warnings:
                print_warning(warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
