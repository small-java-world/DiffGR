#!/usr/bin/env python3
"""Verify the virtual PR review gate assets."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

MARKERS = {
    "src/vpr.rs": [
        "VirtualPrReviewReport",
        "VirtualPrRiskItem",
        "analyze_virtual_pr",
        "virtual_pr_report_json_value",
        "virtual_pr_report_markdown",
        "virtual_pr_reviewer_prompt_markdown",
        "build_file_hotspots",
        "build_group_readiness",
    ],
    "src/app.rs": [
        "DetailTab::VirtualPr",
        "draw_virtual_pr_panel",
        "VirtualPrReportCache",
        "仮想PRレビューゲート",
        "高リスクレビューqueue",
        "File hotspots",
        "Group readiness",
    ],
    "src/bin/diffgrctl.rs": [
        "virtual-pr-review",
        "vpr-review",
        "review-gate",
        "--fail-on-blockers",
        "--max-items",
        "cmd_virtual_pr_review",
    ],
    "tests/vpr_review_ut.rs": [
        "vpr_gate_finds_blockers",
        "vpr_gate_ready_doc_can_pass",
        "vpr_gate_markdown_has_sections",
        "vpr_gate_prompt_has_expected_output",
    ],
}


def count_tests(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip() == "#[test]")


def run(root: Path) -> dict:
    checks = []
    missing = []
    for rel, markers in MARKERS.items():
        path = root / rel
        if not path.exists():
            checks.append({"name": rel, "ok": False, "missing": ["<file>"]})
            missing.append(rel)
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        miss = [m for m in markers if m not in text]
        checks.append({"name": rel, "ok": not miss, "missing": miss})
    tests = count_tests(root / "tests" / "vpr_review_ut.rs") if (root / "tests" / "vpr_review_ut.rs").exists() else 0
    wrapper_files = [
        "virtual-pr-review.ps1",
        "virtual-pr-review.sh",
        "windows/virtual-pr-review-windows.ps1",
        "Virtual PR Review Gate.cmd",
    ]
    missing_wrappers = [rel for rel in wrapper_files if not (root / rel).exists()]
    docs = ["README.md", "TESTING.md", "WINDOWS.md", "CHANGELOG.md", "SELF_REVIEW.md"]
    missing_doc_markers = []
    for rel in docs:
        text = (root / rel).read_text(encoding="utf-8", errors="ignore") if (root / rel).exists() else ""
        if "Virtual PR review" not in text and "仮想PR" not in text:
            missing_doc_markers.append(rel)
    return {
        "format": "diffgr-virtual-pr-review-audit-result",
        "ok": all(c["ok"] for c in checks) and tests >= 95 and not missing_wrappers and not missing_doc_markers,
        "tests": tests,
        "minimumTests": 95,
        "checks": checks,
        "missingWrappers": missing_wrappers,
        "missingDocMarkers": missing_doc_markers,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify virtual PR review gate assets")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-audit", default="VIRTUAL_PR_REVIEW_AUDIT.json")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = run(root)
    (root / args.write_audit).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Virtual PR review gate: {'ok' if result['ok'] else 'failed'} ({result['tests']} tests)")
        for check in result["checks"]:
            print(f"- {'ok' if check['ok'] else 'NG'}: {check['name']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
