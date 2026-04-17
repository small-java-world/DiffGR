#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_bundle import load_bundle_artifacts, verify_review_bundle_artifacts  # noqa: E402
from diffgr.viewer_core import print_error  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify immutable review bundle artifacts in cross-repo CI.")
    parser.add_argument("--bundle", required=True, help="Path to bundle.diffgr.json.")
    parser.add_argument("--state", required=True, help="Path to review.state.json.")
    parser.add_argument("--manifest", required=True, help="Path to review.manifest.json.")
    parser.add_argument("--expected-head", help="Expected source head SHA/ref.")
    parser.add_argument("--require-approvals", action="store_true", help="Require all groups to be approved.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output JSON report.")
    return parser.parse_args(argv)


def _print_result(result: dict) -> None:
    status = "PASS" if result.get("ok") else "FAIL"
    print(f"Result: {status}")
    for error in result.get("errors", []):
        print(f"  [error] {error}", file=sys.stderr)
    for warning in result.get("warnings", []):
        print(f"  [warning] {warning}", file=sys.stderr)
    approval_report = result.get("approvalReport")
    if isinstance(approval_report, dict):
        for group in approval_report.get("groups", []):
            icon = "[ok]" if group.get("approved") and group.get("valid") else "[fail]"
            print(
                f"  {icon} {group.get('groupId')} ({group.get('groupName')}): "
                f"{group.get('reason')} [{group.get('reviewedCount')}/{group.get('totalCount')}]"
            )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        bundle_doc, state, manifest = load_bundle_artifacts(
            bundle_path=Path(args.bundle).resolve(),
            state_path=Path(args.state).resolve(),
            manifest_path=Path(args.manifest).resolve(),
        )
        result = verify_review_bundle_artifacts(
            bundle_doc,
            state,
            manifest,
            expected_head=args.expected_head,
            require_approvals=args.require_approvals,
        )
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_result(result)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
