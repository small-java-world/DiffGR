#!/usr/bin/env python3
"""Verify the expanded Rust UT depth gate.

This gate complements `verify_ut_matrix.py`: it checks that the additional
regression-contract UT files are present, that the matrix itself passes, and that
Cargo-independent assets still describe the intended high-value review flows.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

NEW_TEST_FILES = {
    "tests/ut_depth_quality_more_ut.rs": 90,
    "tests/gui_review_flow_contract_more_ut.rs": 80,
    "tests/virtual_pr_regression_more_ut.rs": 70,
    "tests/cli_wrapper_ci_contract_more_ut.rs": 70,
}
REQUIRED_MARKERS = {
    "UT_MATRIX.json": [
        "expanded UT depth regression guards",
        "gui review flow contract",
        "virtual PR regression matrix",
        "cli wrapper ci contract",
        "minimumRustTestCount",
    ],
    "src/app.rs": [
        "draw_virtual_pr_panel",
        "draw_diagnostics_panel",
        "draw_diff_toolbar",
        "VirtualPrReportCache",
        "DiffWordPairCache",
    ],
    "src/vpr.rs": [
        "VirtualPrReviewReport",
        "build_risk_items",
        "build_file_hotspots",
        "build_group_readiness",
        "virtual_pr_reviewer_prompt_markdown",
    ],
    "src/bin/diffgrctl.rs": [
        "cmd_virtual_pr_review",
        "cmd_quality_review",
        "virtual-pr-review",
        "review-gate",
    ],
}


def count_tests(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip() == "#[test]")


def run_matrix(root: Path) -> dict:
    tool = root / "tools" / "verify_ut_matrix.py"
    proc = subprocess.run([sys.executable, str(tool), "--json"], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return {"ok": False, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    return json.loads(proc.stdout)


def verify(root: Path) -> dict:
    matrix = run_matrix(root)
    file_results = []
    for rel, minimum in NEW_TEST_FILES.items():
        path = root / rel
        exists = path.exists()
        count = count_tests(path) if exists else 0
        file_results.append({"file": rel, "exists": exists, "testCount": count, "minimum": minimum, "ok": exists and count >= minimum})

    marker_results = []
    for rel, markers in REQUIRED_MARKERS.items():
        path = root / rel
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        missing = [marker for marker in markers if marker not in text]
        marker_results.append({"file": rel, "missing": missing, "ok": not missing})

    total_new = sum(row["testCount"] for row in file_results)
    total_tests = int(matrix.get("totalRustTests", 0)) if isinstance(matrix, dict) else 0
    result = {
        "format": "diffgr-ut-depth-audit-result",
        "ok": bool(matrix.get("ok")) and all(row["ok"] for row in file_results) and all(row["ok"] for row in marker_results) and total_new >= 310 and total_tests >= 1180,
        "matrixOk": bool(matrix.get("ok")),
        "totalRustTests": total_tests,
        "minimumRustTestCount": matrix.get("minimumRustTestCount"),
        "newRustTests": total_new,
        "minimumNewRustTests": 310,
        "newTestFiles": file_results,
        "markerChecks": marker_results,
        "matrix": matrix,
    }
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify expanded UT depth assets")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-audit", default="UT_DEPTH_AUDIT.json")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = verify(root)
    (root / args.write_audit).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"UT depth gate: {'ok' if result['ok'] else 'failed'} ({result['totalRustTests']} Rust tests)")
        for row in result["newTestFiles"]:
            print(f"- {'ok' if row['ok'] else 'NG'}: {row['file']} ({row['testCount']}/{row['minimum']})")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
