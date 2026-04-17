#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_state import STATE_DIFF_SECTIONS, diff_review_states, iter_review_state_diff_rows, iter_review_state_selection_tokens, load_review_state  # noqa: E402
from diffgr.viewer_core import print_error, print_json, resolve_script_path  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diff two DiffGR state JSON files.")
    parser.add_argument("--base", required=True, help="Base state JSON path.")
    parser.add_argument("--other", required=True, help="Other state JSON path.")
    parser.add_argument("--json", action="store_true", help="Output JSON diff only.")
    parser.add_argument("--tokens-only", action="store_true", help="Print selection tokens only.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    base_path = resolve_script_path(args.base, ROOT)
    other_path = resolve_script_path(args.other, ROOT)
    try:
        base_state = load_review_state(base_path)
        other_state = load_review_state(other_path)
        diff = diff_review_states(base_state, other_state)
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    if args.json:
        print_json(diff)
        return 0
    if args.tokens_only:
        for token in iter_review_state_selection_tokens(diff):
            print(token)
        return 0

    rows = iter_review_state_diff_rows(diff)
    print(f"Base: {base_path}")
    print(f"Other: {other_path}")
    for key in STATE_DIFF_SECTIONS:
        section = diff.get(key, {}) if isinstance(diff.get(key), dict) else {}
        print(
            f"{key}:"
            f" added={section.get('addedCount', 0)}"
            f" removed={section.get('removedCount', 0)}"
            f" changed={section.get('changedCount', 0)}"
            f" unchanged={section.get('unchangedCount', 0)}"
        )
        section_rows = [row for row in rows if str(row.get("section", "")) == key]
        for label in ("added", "removed", "changed"):
            label_rows = [row for row in section_rows if str(row.get("changeKind", "")) == label]
            if not label_rows:
                continue
            print(f"  {label}:")
            for row in label_rows:
                select = row.get("selectionToken")
                suffix = f" [select: {select}]" if select else ""
                print(f"    - {row.get('key', '')}: {row.get('preview', '')}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
