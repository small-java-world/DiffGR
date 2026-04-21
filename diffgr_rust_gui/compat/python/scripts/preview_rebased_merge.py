#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.impact_merge import build_impact_preview_report, format_impact_preview_text, preview_impact_merge  # noqa: E402
from diffgr.review_state import load_diffgr_document, load_review_state  # noqa: E402
from diffgr.viewer_core import print_error, print_json, resolve_script_path  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview impact-aware state rebase/merge between old/new DiffGR snapshots.")
    parser.add_argument("--old", required=True, help="Old DiffGR JSON path.")
    parser.add_argument("--new", required=True, help="New DiffGR JSON path.")
    parser.add_argument("--state", required=True, help="State JSON extracted from old snapshot.")
    parser.add_argument("--json", action="store_true", help="Output JSON only.")
    parser.add_argument("--tokens-only", choices=("handoffs", "reviews", "ui", "all"), help="Print tokens for a named selection plan only.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    old_path = resolve_script_path(args.old, ROOT)
    new_path = resolve_script_path(args.new, ROOT)
    state_path = resolve_script_path(args.state, ROOT)
    try:
        preview = preview_impact_merge(
            old_doc=load_diffgr_document(old_path),
            new_doc=load_diffgr_document(new_path),
            state=load_review_state(state_path),
        )
        report = build_impact_preview_report(
            preview,
            old_label=old_path.name,
            new_label=new_path.name,
            state_label=state_path.name,
        )
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    if args.json:
        payload = dict(preview)
        payload["report"] = report
        print_json(payload)
        return 0
    if args.tokens_only:
        selection_plans = report.get("selectionPlans", {}) if isinstance(report.get("selectionPlans"), dict) else {}
        plan = selection_plans.get(args.tokens_only, {}) if isinstance(selection_plans.get(args.tokens_only), dict) else {}
        for token in plan.get("tokens", []) if isinstance(plan.get("tokens"), list) else []:
            print(str(token))
        return 0

    print(format_impact_preview_text(preview, old_label=old_path.name, new_label=new_path.name, state_label=state_path.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
