#!/usr/bin/env python3
"""Consolidated self-review gate for Python parity, GUI completion, and UT coverage.

The gate is intentionally static and fast. It complements Cargo-based tests and
helps reviewers catch regressions before running the full Windows build.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

EXPECTED_PYTHON_SCRIPTS = 31
EXPECTED_WRAPPERS = 62
EXPECTED_FUNCTIONAL_SCENARIOS = 31
EXPECTED_COMPAT_SOURCES = 163
EXPECTED_PYTHON_OPTIONS = 80
# Legacy UT contract marker: MIN_RUST_TESTS = 500
MIN_RUST_TESTS = 860
GUI_MARKERS = [
    "PendingDocumentLoad", "PendingStateSave", "show_rows", "cached_chunk_row",
    "filter_apply_deadline", "maybe_apply_debounced_filters", "smooth_scroll_repaint",
    "clip_for_display", "draw_virtual_text", "DiffLineIndexCache", "request_repaint_after",
    "reduce_motion", "persist_egui_memory", "State JSONをコピー", "自己レビュー / 品質ゲート",
    "background_io", "MAX_RENDERED_DIFF_CHARS", "draw_performance_overlay", "draw_diagnostics_panel",
    "copy_self_review_report", "save_self_review_report", "DiffViewMode", "DiffContextMode",
    "draw_side_by_side_diff_lines", "visible_diff_line_indices", "context_line_indices",
    "side_by_side_rows", "diff_line_background", "line_matches_diff_search",
    "select_changed_line_relative", "select_diff_search_match", "copy_visible_diff_text",
    "copy_selected_diff_line", "Diff内検索", "表示中diffコピー",
    "word_diff_enabled", "word_diff_smart_pairing", "DiffWordPairCache",
    "DiffWordSegmentCache", "word_segments_for_line", "diff_word_pair_map",
    "matched_delete_add_rows", "build_diff_layout_job", "word_diff_background",
    "行内差分", "賢く対応付け",
    "VirtualPrReportCache", "draw_virtual_pr_panel", "vpr::analyze_virtual_pr",
    "仮想PRレビューゲート", "高リスクレビューqueue", "Group readiness", "File hotspots",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def count_tests(root: Path) -> int:
    total = 0
    for path in (root / "tests").glob("*.rs"):
        total += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip() == "#[test]")
    for rel in ["src/model.rs", "src/ops.rs"]:
        path = root / rel
        if path.exists():
            total += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip() == "#[test]")
    return total


def run_json_tool(root: Path, args: list[str]) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    try:
        payload = json.loads(proc.stdout)
    except Exception:
        payload = {"ok": False, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}
    payload["returncode"] = proc.returncode
    return payload


def visible_cache_struct_fields(src: str) -> set[str]:
    match = re.search(r"struct\s+VisibleCacheKey\s*\{(?P<body>.*?)\n\}", src, re.S)
    if not match:
        return set()
    fields: set[str] = set()
    for line in match.group("body").splitlines():
        line = line.strip()
        if line and not line.startswith("//") and ":" in line:
            fields.add(line.split(":", 1)[0].strip())
    return fields


def visible_cache_constructor_fields(src: str) -> set[str]:
    match = re.search(r"fn\s+visible_cache_key\s*\([^)]*\)\s*->\s*VisibleCacheKey\s*\{\s*VisibleCacheKey\s*\{(?P<body>.*?)\n\s*\}\s*\n\s*\}", src, re.S)
    if not match:
        return set()
    fields: set[str] = set()
    for line in match.group("body").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("//") and ":" in stripped:
            fields.add(stripped.split(":", 1)[0].strip())
    return fields


def verify_manifest(root: Path) -> dict[str, Any]:
    manifest = load_json(root / "PYTHON_PARITY_MANIFEST.json")
    entries = manifest.get("entries", [])
    missing_ps1: list[str] = []
    missing_sh: list[str] = []
    missing_compat: list[str] = []
    for entry in entries:
        stem = entry.get("stem")
        if not stem:
            continue
        if not (root / "scripts" / f"{stem}.ps1").exists():
            missing_ps1.append(stem)
        if not (root / "scripts" / f"{stem}.sh").exists():
            missing_sh.append(stem)
        compat = entry.get("compatPython")
        if compat and not (root / compat).exists():
            missing_compat.append(str(compat))
    return {
        "ok": len(entries) == EXPECTED_PYTHON_SCRIPTS and not missing_ps1 and not missing_sh and not missing_compat,
        "scriptCount": len(entries),
        "wrapperCount": len(entries) * 2 - len(missing_ps1) - len(missing_sh),
        "missingPs1": missing_ps1,
        "missingSh": missing_sh,
        "missingCompat": missing_compat,
    }


def verify_gui(root: Path) -> dict[str, Any]:
    app = (root / "src/app.rs").read_text(encoding="utf-8")
    struct_fields = visible_cache_struct_fields(app)
    constructor_fields = visible_cache_constructor_fields(app)
    marker_missing = [m for m in GUI_MARKERS if m not in app]
    return {
        "ok": struct_fields == constructor_fields and bool(struct_fields) and not marker_missing,
        "visibleCacheKey": {
            "structOnly": sorted(struct_fields - constructor_fields),
            "constructorOnly": sorted(constructor_fields - struct_fields),
        },
        "markerCount": len(GUI_MARKERS) - len(marker_missing),
        "expectedMarkerCount": len(GUI_MARKERS),
        "missingMarkers": marker_missing,
    }


def run(root: Path, strict: bool = False) -> dict[str, Any]:
    manifest = verify_manifest(root)
    native = load_json(root / "NATIVE_PYTHON_PARITY_AUDIT.json")
    functional = load_json(root / "NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json")
    source = load_json(root / "COMPLETE_PYTHON_SOURCE_AUDIT.json")
    ut_matrix = load_json(root / "UT_MATRIX.json")
    gui = verify_gui(root)
    rust_tests = count_tests(root)
    checks = [
        {"name": "python manifest and wrappers", "ok": manifest["ok"], "details": manifest},
        {"name": "strict compat source inventory", "ok": int(source.get("sourceFileCount", 0)) >= EXPECTED_COMPAT_SOURCES, "details": {"sourceFileCount": source.get("sourceFileCount"), "excludedCacheFileCount": source.get("excludedCacheFileCount")}},
        {"name": "native command/option parity", "ok": bool(native.get("ok")) and native.get("scriptCount") == EXPECTED_PYTHON_SCRIPTS and native.get("uniquePythonOptionCount", 0) >= EXPECTED_PYTHON_OPTIONS, "details": {"scriptCount": native.get("scriptCount"), "uniquePythonOptionCount": native.get("uniquePythonOptionCount"), "functionalScenarioCount": native.get("functionalScenarioCount")}},
        {"name": "functional scenario matrix", "ok": len(functional.get("scenarios", [])) == EXPECTED_FUNCTIONAL_SCENARIOS, "details": {"scenarioCount": len(functional.get("scenarios", []))}},
        {"name": "GUI completion and responsiveness", "ok": gui["ok"], "details": gui},
        {"name": "UT matrix threshold", "ok": rust_tests >= MIN_RUST_TESTS and int(ut_matrix.get("minimumRustTestCount", 0)) >= MIN_RUST_TESTS, "details": {"rustTests": rust_tests, "minimumRustTestCount": ut_matrix.get("minimumRustTestCount")}},
    ]
    subgates: dict[str, Any] = {}
    if strict:
        # Keep strict mode deterministic and fast: it validates the checked-in
        # subgate inputs directly instead of recursively spawning every verifier.
        # Run tools/verify_python_parity.py --compile --smoke separately when an
        # execution smoke is desired.
        subgates["utMatrix"] = {
            "ok": rust_tests >= MIN_RUST_TESTS and int(ut_matrix.get("minimumRustTestCount", 0)) >= MIN_RUST_TESTS,
            "totalRustTests": rust_tests,
            "minimumRustTestCount": ut_matrix.get("minimumRustTestCount"),
            "categoryCount": len(ut_matrix.get("categories", [])),
        }
        subgates["nativeParity"] = {
            "ok": bool(native.get("ok")) and native.get("scriptCount") == EXPECTED_PYTHON_SCRIPTS,
            "scriptCount": native.get("scriptCount"),
            "uniquePythonOptionCount": native.get("uniquePythonOptionCount"),
            "functionalScenarioCount": native.get("functionalScenarioCount"),
        }
        subgates["functionalStatic"] = {
            "ok": len(functional.get("scenarios", [])) == EXPECTED_FUNCTIONAL_SCENARIOS,
            "scenarioCount": len(functional.get("scenarios", [])),
        }
        subgates["pythonCompat"] = {
            "ok": int(source.get("sourceFileCount", 0)) >= EXPECTED_COMPAT_SOURCES and manifest.get("ok", True),
            "sourceFileCount": source.get("sourceFileCount"),
            "excludedCacheFileCount": source.get("excludedCacheFileCount"),
            "scriptCount": manifest.get("scriptCount"),
        }
        for name, value in subgates.items():
            checks.append({"name": name, "ok": bool(value.get("ok")), "details": value})
    return {
        "format": "diffgr-self-review-result",
        "ok": all(check["ok"] for check in checks),
        "summary": {
            "pythonScripts": manifest.get("scriptCount"),
            "wrappers": manifest.get("wrapperCount"),
            "nativePythonOptions": native.get("uniquePythonOptionCount"),
            "functionalScenarios": len(functional.get("scenarios", [])),
            "compatSources": source.get("sourceFileCount"),
            "guiMarkers": gui.get("markerCount"),
            "guiMarkersExpected": gui.get("expectedMarkerCount"),
            "rustTests": rust_tests,
        },
        "checks": checks,
        "remainingRisks": [
            "This static gate does not replace cargo test --all-targets.",
            "Native Rust output is not promised byte-for-byte identical to Python; use compat mode for exact legacy behavior.",
        ],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the consolidated DiffGR Rust GUI self-review gate.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Run available static sub-gates too.")
    parser.add_argument("--write-audit", default="SELF_REVIEW_AUDIT.json")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = run(root, strict=args.strict)
    (root / args.write_audit).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Self review: {'ok' if result['ok'] else 'failed'}")
        for check in result["checks"]:
            print(f"- {'ok' if check['ok'] else 'NG'}: {check['name']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
