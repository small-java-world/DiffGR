#!/usr/bin/env python3
"""CI gate: check that all virtual PRs are approved and up-to-date.

Exit codes:
  0 — all groups approved and valid
  1 — error (bad input, missing file, etc.)
  2 — one or more groups not approved or invalidated
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.approval import (  # noqa: E402
    ApprovalReport,
    approval_report_to_json,
    check_all_approvals,
    check_approvals_against_regenerated,
)
from diffgr.viewer_core import load_json, print_error, print_warning, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that all virtual PRs in a diffgr document are approved."
    )
    parser.add_argument("--input", required=True, help="Input .diffgr.json path.")
    parser.add_argument("--repo", help="Git repo path (enables full regeneration check).")
    parser.add_argument("--base", help="Base ref for regeneration (requires --repo).")
    parser.add_argument("--feature", help="Feature ref for regeneration (requires --repo).")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON.")
    parser.add_argument(
        "--strict-full-check",
        action="store_true",
        help="When set, regeneration failure is a hard error (exit 1) instead of fallback.",
    )
    return parser.parse_args(argv)


def _try_regenerate(repo: Path, base: str, feature: str) -> dict | None:
    """Attempt to regenerate a diffgr doc from git refs. Returns None on failure."""
    try:
        from diffgr.generator import build_diffgr_document  # local import

        return build_diffgr_document(repo, base, feature, title="CI regeneration", include_patch=False)
    except Exception as error:  # noqa: BLE001
        print_warning(f"Could not regenerate diffgr from git: {error}")
        return None


def _print_report(report: ApprovalReport) -> None:
    for s in report.groups:
        icon = "[ok]" if (s.approved and s.valid) else "[fail]"
        print(f"  {icon} {s.group_id} ({s.group_name}): {s.reason} [{s.reviewed_count}/{s.total_count}]")
    if report.warnings:
        for w in report.warnings:
            print(f"  [warning] {w}", file=sys.stderr)
    status = "PASS" if report.all_approved else "FAIL"
    print(f"\nResult: {status}")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path

    try:
        doc = load_json(input_path.resolve())
        doc_warnings = validate_document(doc)
        for w in doc_warnings:
            print_warning(w)
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    # Validate --repo/--base/--feature: all-or-nothing
    regen_flags = [args.repo, args.base, args.feature]
    regen_specified = [f for f in regen_flags if f]
    if 0 < len(regen_specified) < 3:
        missing = []
        if not args.repo:
            missing.append("--repo")
        if not args.base:
            missing.append("--base")
        if not args.feature:
            missing.append("--feature")
        print(
            f"[error] --repo, --base, --feature must all be specified together (missing: {', '.join(missing)})",
            file=sys.stderr,
        )
        return 1

    # Full regeneration path (requires --repo --base --feature)
    report: ApprovalReport | None = None
    if args.repo and args.base and args.feature:
        repo_path = Path(args.repo)
        new_doc = _try_regenerate(repo_path, args.base, args.feature)
        if new_doc is not None:
            report = check_approvals_against_regenerated(doc, new_doc)
        elif args.strict_full_check:
            print("[error] Regeneration failed and --strict-full-check is set.", file=sys.stderr)
            return 1

    if report is None:
        report = check_all_approvals(doc)

    if args.as_json:
        print(approval_report_to_json(report))
    else:
        _print_report(report)

    return 0 if report.all_approved else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
