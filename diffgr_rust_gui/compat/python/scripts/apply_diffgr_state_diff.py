#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.impact_merge import preview_impact_apply  # noqa: E402
from diffgr.review_state import load_review_state, preview_review_state_selection  # noqa: E402
from diffgr.viewer_core import load_json, print_error, print_json, resolve_script_path, validate_document, write_json  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply selected DiffGR state diff keys from one state JSON to another.")
    parser.add_argument("--base", required=True, help="Base state JSON path.")
    parser.add_argument("--other", help="Other state JSON path.")
    parser.add_argument("--select", action="append", default=[], help="Selection token. Repeatable.")
    parser.add_argument("--impact-old", help="Old .diffgr.json path for impact-aware selection plan apply.")
    parser.add_argument("--impact-new", help="New .diffgr.json path for impact-aware selection plan apply.")
    parser.add_argument("--impact-plan", choices=["handoffs", "reviews", "ui", "all"], help="Impact selection plan name.")
    parser.add_argument("--output", help="Output state JSON path.")
    parser.add_argument("--preview", action="store_true", help="Preview selected apply without writing output.")
    parser.add_argument("--json-summary", action="store_true", help="Print summary as JSON.")
    return parser.parse_args(argv)


def _format_result_diff(diff: dict) -> list[str]:
    lines: list[str] = []
    for key in ("reviews", "groupBriefs", "analysisState", "threadState"):
        section = diff.get(key, {}) if isinstance(diff.get(key), dict) else {}
        lines.append(
            f"{key}: added={section.get('addedCount', 0)} "
            f"removed={section.get('removedCount', 0)} "
            f"changed={section.get('changedCount', 0)} "
            f"unchanged={section.get('unchangedCount', 0)}"
        )
    return lines


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    base_path = resolve_script_path(args.base, ROOT)
    use_impact_plan = bool(args.impact_old or args.impact_new or args.impact_plan)
    if use_impact_plan and args.select:
        print("[error] --select cannot be combined with --impact-old/--impact-new/--impact-plan.", file=sys.stderr)
        return 2
    if use_impact_plan:
        if not (args.impact_old and args.impact_new and args.impact_plan):
            print("[error] --impact-old, --impact-new, and --impact-plan must be provided together.", file=sys.stderr)
            return 2
        other_path = None
    else:
        if not args.other:
            print("[error] --other is required unless --impact-old/--impact-new/--impact-plan is used.", file=sys.stderr)
            return 2
        other_path = resolve_script_path(args.other, ROOT)
    if not use_impact_plan and not args.select:
        print("[error] At least one --select token is required.", file=sys.stderr)
        return 2
    if not args.preview and not args.output:
        print("[error] --output is required unless --preview is set.", file=sys.stderr)
        return 2
    try:
        base_state = load_review_state(base_path)
        source_label: str
        selection_tokens: list[str]
        if use_impact_plan:
            old_path = resolve_script_path(args.impact_old, ROOT)
            new_path = resolve_script_path(args.impact_new, ROOT)
            old_doc = load_json(old_path)
            validate_document(old_doc)
            new_doc = load_json(new_path)
            validate_document(new_doc)
            impact_apply = preview_impact_apply(
                old_doc=old_doc,
                new_doc=new_doc,
                state=base_state,
                plan=args.impact_plan,
                old_label=old_path.name,
                new_label=new_path.name,
                state_label=base_path.name,
            )
            preview = impact_apply["selectionPreview"]
            selection_tokens = [str(item) for item in impact_apply["selectionTokens"]]
            source_label = f"{impact_apply['sourceLabel']} plan={args.impact_plan}"
        else:
            other_state = load_review_state(other_path)
            preview = preview_review_state_selection(base_state, other_state, args.select)
            selection_tokens = list(args.select)
            source_label = str(other_path)
        applied = int(preview["summary"].get("appliedCount", 0)) if isinstance(preview, dict) else 0
        output_path = resolve_script_path(args.output, ROOT) if args.output else None
        if not args.preview and output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            next_state = impact_apply["nextState"] if use_impact_plan else preview["nextState"]
            write_json(output_path, next_state)
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    if args.json_summary:
        print_json({
            "base": str(base_path),
            "other": str(other_path) if other_path is not None else None,
            "output": str(output_path) if output_path is not None else None,
            "preview": bool(args.preview),
            "selection": selection_tokens,
            "source": source_label,
            "impactPlan": args.impact_plan if use_impact_plan else None,
            "appliedCount": applied,
            "noOpCount": int(preview["summary"].get("noOpCount", 0)) if isinstance(preview, dict) else 0,
            "changedSectionCount": int(preview["summary"].get("changedSectionCount", 0)) if isinstance(preview, dict) else 0,
        })
    else:
        if output_path is not None and not args.preview:
            print(f"Wrote: {output_path}")
        else:
            print(f"Preview: {source_label}")
        print(f"Selection: {' '.join(selection_tokens)}")
        print(f"Applied: {applied}")
        print(f"No-op: {int(preview['summary'].get('noOpCount', 0)) if isinstance(preview, dict) else 0}")
        print(f"Changed sections: {int(preview['summary'].get('changedSectionCount', 0)) if isinstance(preview, dict) else 0}")
        print("Result Diff:")
        result_diff = preview["resultDiff"] if isinstance(preview, dict) else {"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}}
        for line in _format_result_diff(result_diff):
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
