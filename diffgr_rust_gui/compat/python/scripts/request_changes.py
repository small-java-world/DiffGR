#!/usr/bin/env python3
"""Record 'changes requested' decisions for one or more groups in a diffgr document."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.approval import request_changes_on_group  # noqa: E402
from diffgr.viewer_core import load_json, print_error, print_warning, validate_document, write_json  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record 'changes requested' decisions for groups in a diffgr document."
    )
    parser.add_argument("--input", required=True, help="Input .diffgr.json path.")
    parser.add_argument("--output", help="Output path (defaults to --input).")
    parser.add_argument(
        "--group",
        action="append",
        dest="groups",
        metavar="GROUP_ID",
        help="Group ID to request changes on (repeatable). Use --all for all groups.",
    )
    parser.add_argument("--requested-by", required=True, help="Name of the reviewer requesting changes.")
    parser.add_argument("--all", dest="all_groups", action="store_true", help="Request changes on all groups.")
    parser.add_argument("--comment", default=None, help="Explanation of the requested changes.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if not args.all_groups and not args.groups:
        print_error("Specify --group GROUP_ID or --all.")
        return 1

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path

    try:
        doc = load_json(input_path.resolve())
        warnings = validate_document(doc)
        for w in warnings:
            print_warning(w)
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    if args.all_groups:
        group_ids = [
            str(g.get("id", "")).strip()
            for g in doc.get("groups", [])
            if isinstance(g, dict) and str(g.get("id", "")).strip()
        ]
    else:
        group_ids = [str(gid).strip() for gid in (args.groups or [])]

    if not group_ids:
        print_error("No groups found to process.")
        return 1

    count = 0
    for group_id in group_ids:
        try:
            doc = request_changes_on_group(
                doc,
                group_id,
                requested_by=args.requested_by,
                comment=args.comment,
            )
            print(f"[ok] Changes requested on group {group_id!r}")
            count += 1
        except Exception as error:  # noqa: BLE001
            print_error(f"Unexpected error for group {group_id!r}: {error}")
            return 1

    output_path = Path(args.output) if args.output else input_path
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(output_path, doc)
        print(f"Wrote {output_path} ({count} group(s) updated)")
    except Exception as error:  # noqa: BLE001
        print_error(f"Failed to write output: {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
