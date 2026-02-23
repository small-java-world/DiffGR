#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.impact import build_impact_report  # noqa: E402
from diffgr.review_history import append_review_history, build_rebase_history_entry  # noqa: E402
from diffgr.review_rebase import rebase_review_state  # noqa: E402
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebase review state (groups/assignments/reviews) from an old DiffGR file onto a new DiffGR file."
    )
    parser.add_argument("--old", required=True, help="Previously reviewed DiffGR JSON path (source of review state).")
    parser.add_argument("--new", required=True, help="Newly generated DiffGR JSON path (target snapshot).")
    parser.add_argument("--output", required=True, help="Output rebased DiffGR JSON path.")
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
    parser.add_argument(
        "--impact-grouping",
        choices=["old", "new"],
        default="old",
        help="Grouping for impact scope history (default: old).",
    )
    parser.add_argument("--no-history", action="store_true", help="Do not write meta.x-reviewHistory/x-impactScope.")
    parser.add_argument("--history-label", help="Optional label for this rebase history event.")
    parser.add_argument("--history-actor", help="Optional actor/reviewer name for history event.")
    parser.add_argument(
        "--history-max-entries",
        type=int,
        default=100,
        help="Max x-reviewHistory entries to keep (default: 100).",
    )
    parser.add_argument(
        "--history-max-ids-per-group",
        type=int,
        default=200,
        help="Max chunk ids to keep per group in history impactScope (default: 200).",
    )
    parser.add_argument("--json-summary", action="store_true", help="Print summary as JSON.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    old_path = Path(args.old)
    if not old_path.is_absolute():
        old_path = ROOT / old_path
    new_path = Path(args.new)
    if not new_path.is_absolute():
        new_path = ROOT / new_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    try:
        old_doc = load_json(old_path.resolve())
        validate_document(old_doc)
        new_doc = load_json(new_path.resolve())
        validate_document(new_doc)

        out_doc, summary, warnings = rebase_review_state(
            old_doc=old_doc,
            new_doc=new_doc,
            preserve_groups=not bool(args.keep_new_groups),
            carry_line_comments=not bool(args.no_line_comments),
            similarity_threshold=float(args.similarity_threshold),
        )
        summary_payload = {
            "matchedStrong": summary.matched_strong,
            "matchedStable": summary.matched_stable,
            "matchedDelta": summary.matched_delta,
            "matchedSimilar": summary.matched_similar,
            "carriedReviews": summary.carried_reviews,
            "carriedReviewed": summary.carried_reviewed,
            "changedToNeedsReReview": summary.changed_to_needs_rereview,
            "unmappedNewChunks": summary.unmapped_new_chunks,
        }
        impact = build_impact_report(
            old_doc=old_doc,
            new_doc=out_doc,
            grouping=str(args.impact_grouping),
            similarity_threshold=float(args.similarity_threshold),
            max_items_per_group=5000,
            preview_lines=3,
        )
        if not args.no_history:
            entry = build_rebase_history_entry(
                old_doc=old_doc,
                new_doc=new_doc,
                summary=summary_payload,
                impact=impact,
                old_path=str(old_path.resolve()),
                new_path=str(new_path.resolve()),
                output_path=str(output_path.resolve()),
                keep_new_groups=bool(args.keep_new_groups),
                carry_line_comments=not bool(args.no_line_comments),
                similarity_threshold=float(args.similarity_threshold),
                warnings=warnings,
                label=args.history_label,
                actor=args.history_actor,
                max_ids_per_group=int(args.history_max_ids_per_group),
            )
            append_review_history(out_doc, entry, max_entries=int(args.history_max_entries))
        validate_document(out_doc)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    impact_scope = out_doc.get("meta", {}).get("x-impactScope", {})
    impacted_groups: list[object] = []
    unaffected_groups: list[object] = []
    if isinstance(impact_scope, dict):
        impacted_groups_raw = impact_scope.get("impactedGroups", [])
        unaffected_groups_raw = impact_scope.get("unaffectedGroups", [])
        if isinstance(impacted_groups_raw, list):
            impacted_groups = impacted_groups_raw
        if isinstance(unaffected_groups_raw, list):
            unaffected_groups = unaffected_groups_raw
    if not impacted_groups and not unaffected_groups:
        groups = impact.get("groups", []) if isinstance(impact, dict) else []
        if isinstance(groups, list):
            impacted_groups = [g for g in groups if isinstance(g, dict) and str(g.get("action", "")) == "review"]
            unaffected_groups = [g for g in groups if isinstance(g, dict) and str(g.get("action", "")) != "review"]

    if args.json_summary:
        print(
            json.dumps(
                {
                    "matchedStrong": summary.matched_strong,
                    "matchedStable": summary.matched_stable,
                    "matchedDelta": summary.matched_delta,
                    "matchedSimilar": summary.matched_similar,
                    "carriedReviews": summary.carried_reviews,
                    "carriedReviewed": summary.carried_reviewed,
                    "changedToNeedsReReview": summary.changed_to_needs_rereview,
                    "unmappedNewChunks": summary.unmapped_new_chunks,
                    "impactedGroupCount": len(impacted_groups) if isinstance(impacted_groups, list) else 0,
                    "unaffectedGroupCount": len(unaffected_groups) if isinstance(unaffected_groups, list) else 0,
                    "warnings": warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"Wrote: {output_path}")
        print(f"Matched (strong): {summary.matched_strong}")
        print(f"Matched (stable): {summary.matched_stable}")
        print(f"Matched (delta): {summary.matched_delta}")
        print(f"Matched (similar): {summary.matched_similar}")
        print(f"Carried reviews: {summary.carried_reviews} (reviewed={summary.carried_reviewed})")
        print(f"Changed -> needsReReview: {summary.changed_to_needs_rereview}")
        print(f"Unmapped new chunks: {summary.unmapped_new_chunks}")
        if isinstance(impacted_groups, list) and isinstance(unaffected_groups, list):
            print(f"Impacted groups: {len(impacted_groups)}")
            print(f"Unaffected groups: {len(unaffected_groups)}")
        if warnings:
            for warning in warnings:
                print(f"[warning] {warning}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
