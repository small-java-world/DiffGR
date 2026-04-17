#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_state import load_review_state, summarize_review_state  # noqa: E402
from diffgr.viewer_core import print_error, print_json  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a DiffGR state JSON.")
    parser.add_argument("--input", required=True, help="Input state JSON path.")
    parser.add_argument("--json", action="store_true", help="Output JSON summary only.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    try:
        state = load_review_state(input_path.resolve())
        summary = summarize_review_state(state)
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    if args.json:
        print_json(summary)
        return 0

    reviews = summary.get("reviews", {}) if isinstance(summary.get("reviews"), dict) else {}
    briefs = summary.get("groupBriefs", {}) if isinstance(summary.get("groupBriefs"), dict) else {}
    analysis_state = summary.get("analysisState", {}) if isinstance(summary.get("analysisState"), dict) else {}
    thread_state = summary.get("threadState", {}) if isinstance(summary.get("threadState"), dict) else {}
    review_counts = reviews.get("statusCounts", {}) if isinstance(reviews.get("statusCounts"), dict) else {}
    brief_counts = briefs.get("statusCounts", {}) if isinstance(briefs.get("statusCounts"), dict) else {}

    print(f"File: {input_path.resolve()}")
    print(
        "Reviews:"
        f" total={reviews.get('total', 0)}"
        f" reviewed={review_counts.get('reviewed', 0)}"
        f" unreviewed={review_counts.get('unreviewed', 0)}"
        f" needsReReview={review_counts.get('needsReReview', 0)}"
        f" ignored={review_counts.get('ignored', 0)}"
        f" invalid={review_counts.get('invalid', 0)}"
    )
    print(
        "Comments:"
        f" chunk={reviews.get('chunkCommentCount', 0)}"
        f" line={reviews.get('lineCommentCount', 0)}"
    )
    print(
        "Briefs:"
        f" total={briefs.get('total', 0)}"
        f" draft={brief_counts.get('draft', 0)}"
        f" ready={brief_counts.get('ready', 0)}"
        f" ack={brief_counts.get('acknowledged', 0)}"
        f" stale={brief_counts.get('stale', 0)}"
        f" invalid={brief_counts.get('invalid', 0)}"
    )
    print(
        "Analysis:"
        f" present={bool(analysis_state.get('present'))}"
        f" group={analysis_state.get('currentGroupId') or '-'}"
        f" chunk={analysis_state.get('selectedChunkId') or '-'}"
        f" filter={analysis_state.get('filterText') or '-'}"
        f" mode={'group-report' if bool(analysis_state.get('groupReportMode')) else 'chunk'}"
        f" detail={analysis_state.get('chunkDetailViewMode') or '-'}"
        f" ctx={'all' if bool(analysis_state.get('showContextLines', True)) else 'changes'}"
    )
    print(
        "Thread:"
        f" present={bool(thread_state.get('present'))}"
        f" chunkEntries={thread_state.get('chunkEntryCount', 0)}"
        f" fileEntries={thread_state.get('fileEntryCount', 0)}"
        f" lineAnchor={bool(thread_state.get('hasSelectedLineAnchor'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
