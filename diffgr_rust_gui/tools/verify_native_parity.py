#!/usr/bin/env python3
"""Strict native Rust parity gate for the DiffGR Python script surface.

This verifier is intentionally conservative and standard-library only. It does
not prove semantic identity, but it catches the common regressions that turned a
Python feature into a wrapper-only or compatibility-only feature: missing native
command alias, missing option spelling, missing Windows/shell wrapper, or a
wrapper that no longer defaults to the Rust CLI.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


def fail_json(errors: list[str], payload: dict[str, Any], as_json: bool) -> int:
    payload = dict(payload)
    payload["ok"] = False
    payload["errors"] = errors
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
    return 1


def command_candidates(stem: str) -> set[str]:
    hyphen = stem.replace("_", "-")
    candidates = {stem, hyphen}
    explicit = {
        "generate_diffgr": {"generate", "generate-diffgr", "generate_diffgr"},
        "autoslice_diffgr": {"autoslice", "autoslice-diffgr", "autoslice_diffgr"},
        "refine_slices": {"refine", "refine-slices", "refine_slices"},
        "prepare_review": {"prepare", "prepare-review", "prepare_review"},
        "run_agent_cli": {"run-agent", "run-agent-cli", "run_agent_cli"},
        "apply_diffgr_layout": {"apply-layout", "apply-diffgr-layout", "apply_diffgr_layout"},
        "view_diffgr_app": {"view-app", "view-diffgr-app", "view_diffgr_app"},
        "view_diffgr": {"view", "view-diffgr", "view_diffgr"},
        "export_diffgr_html": {"export-html", "export-diffgr-html", "export_diffgr_html"},
        "serve_diffgr_report": {"serve-html", "serve-diffgr-report", "serve_diffgr_report"},
        "extract_diffgr_state": {"extract-state", "extract-diffgr-state", "extract_diffgr_state"},
        "apply_diffgr_state": {"apply-state", "apply-diffgr-state", "apply_diffgr_state"},
        "diff_diffgr_state": {"diff-state", "diff-diffgr-state", "diff_diffgr_state"},
        "merge_diffgr_state": {"merge-state", "merge-diffgr-state", "merge_diffgr_state"},
        "apply_diffgr_state_diff": {"apply-state-diff", "apply-diffgr-state-diff", "apply_diffgr_state_diff"},
        "rebase_diffgr_state": {"rebase-state", "rebase-diffgr-state", "rebase_diffgr_state"},
        "export_review_bundle": {"export-bundle", "export-review-bundle", "export_review_bundle"},
        "verify_review_bundle": {"verify-bundle", "verify-review-bundle", "verify_review_bundle"},
        "approve_virtual_pr": {"approve", "approve-virtual-pr", "approve_virtual_pr"},
        "check_virtual_pr_approval": {"check-approval", "check-virtual-pr-approval", "check_virtual_pr_approval"},
        "check_virtual_pr_coverage": {"coverage", "check-virtual-pr-coverage", "check_virtual_pr_coverage"},
        "summarize_diffgr": {"summarize", "summarize-diffgr", "summarize_diffgr"},
        "summarize_diffgr_state": {"summarize-state", "summarize-diffgr-state", "summarize_diffgr_state"},
        "summarize_reviewability": {"reviewability", "summarize-reviewability", "summarize_reviewability"},
    }
    candidates.update(explicit.get(stem, set()))
    return candidates


def option_names(entry: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for arg in entry.get("arguments", []):
        for name in arg.get("names", []):
            if isinstance(name, str) and name.startswith("--"):
                out.append(name)
    return sorted(set(out))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify native Rust coverage for every original Python DiffGR script.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="project root")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--check-compat", action="store_true", help="also run tools/verify_python_parity.py --compile --smoke")
    parser.add_argument("--cargo-check", action="store_true", help="run cargo check --all-targets when cargo is available")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    manifest_path = root / "PYTHON_PARITY_MANIFEST.json"
    scenario_path = root / "NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json"
    if not manifest_path.exists():
        return fail_json([f"missing {manifest_path}"], {}, args.json)
    if not scenario_path.exists():
        return fail_json([f"missing {scenario_path}"], {}, args.json)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenarios_doc = json.loads(scenario_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries", [])
    cli_path = root / "src" / "bin" / "diffgrctl.rs"
    ops_path = root / "src" / "ops.rs"
    app_path = root / "src" / "app.rs"
    rust_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (cli_path, ops_path, app_path) if path.exists())
    rust_string_literals = set(re.findall(r'"(--[A-Za-z0-9][A-Za-z0-9_-]*)"', rust_text))

    errors: list[str] = []
    command_rows: list[dict[str, Any]] = []
    all_options: set[str] = set()

    for entry in entries:
        stem = entry["stem"]
        aliases = command_candidates(stem)
        alias_hits = sorted(alias for alias in aliases if f'"{alias}"' in rust_text)
        if not alias_hits:
            errors.append(f"{stem}: no native diffgrctl command alias found in Rust source")

        ps1 = root / "scripts" / f"{stem}.ps1"
        sh = root / "scripts" / f"{stem}.sh"
        py = root / "compat" / "python" / "scripts" / f"{stem}.py"
        for path in (ps1, sh, py):
            if not path.exists():
                errors.append(f"{stem}: missing {path.relative_to(root)}")
        if ps1.exists():
            ps1_text = ps1.read_text(encoding="utf-8", errors="ignore")
            if "diffgrctl.ps1" not in ps1_text or "compat-python.ps1" not in ps1_text:
                errors.append(f"{stem}: PowerShell wrapper must have Rust default and compat fallback")
        if sh.exists():
            sh_text = sh.read_text(encoding="utf-8", errors="ignore")
            if "diffgrctl.sh" not in sh_text or "compat-python.sh" not in sh_text:
                errors.append(f"{stem}: shell wrapper must have Rust default and compat fallback")

        missing_options = []
        opts = option_names(entry)
        for opt in opts:
            all_options.add(opt)
            if opt not in rust_string_literals:
                missing_options.append(opt)
        if missing_options:
            errors.append(f"{stem}: Python options not referenced by native Rust source: {', '.join(missing_options)}")

        command_rows.append({
            "stem": stem,
            "script": entry.get("script"),
            "nativeAliasesFound": alias_hits,
            "pythonOptionCount": len(opts),
            "missingNativeOptions": missing_options,
            "wrapperPs1": ps1.exists(),
            "wrapperSh": sh.exists(),
            "compatPython": py.exists(),
        })

    if len(entries) != 31:
        errors.append(f"expected 31 Python script entries, found {len(entries)}")

    manifest_stems = sorted(entry.get("stem", "") for entry in entries)
    scenario_stems = sorted(item.get("script", "") for item in scenarios_doc.get("scenarios", []))
    if len(scenario_stems) != 31:
        errors.append(f"expected 31 functional parity scenarios, found {len(scenario_stems)}")
    missing_scenarios = sorted(set(manifest_stems) - set(scenario_stems))
    extra_scenarios = sorted(set(scenario_stems) - set(manifest_stems))
    if missing_scenarios:
        errors.append("missing functional parity scenarios: " + ", ".join(missing_scenarios))
    if extra_scenarios:
        errors.append("unknown functional parity scenarios: " + ", ".join(extra_scenarios))

    # Extra semantic guards for the historically easy-to-miss rebase surface.
    for guard in ("--keep-new-groups", "--no-line-comments", "--impact-grouping", "rebase_state_with_options", "rebase_reviews_document_with_options"):
        if guard not in rust_text:
            errors.append(f"native rebase parity guard missing: {guard}")

    compat_result = None
    if args.check_compat:
        proc = subprocess.run(
            [sys.executable, str(root / "tools" / "verify_python_parity.py"), "--root", str(root), "--compile", "--smoke", "--json"],
            cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        compat_result = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        if proc.returncode != 0:
            errors.append("strict Python compatibility verifier failed")

    cargo_result = None
    if args.cargo_check:
        import shutil
        cargo = shutil.which("cargo")
        if cargo:
            proc = subprocess.run([cargo, "check", "--all-targets"], cwd=str(root), text=True)
            cargo_result = {"available": True, "returncode": proc.returncode}
            if proc.returncode != 0:
                errors.append("cargo check --all-targets failed")
        else:
            cargo_result = {"available": False, "returncode": None}

    payload = {
        "format": "diffgr-native-python-parity-audit-result",
        "ok": not errors,
        "scriptCount": len(entries),
        "uniquePythonOptionCount": len(all_options),
        "functionalScenarioCount": len(scenario_stems),
        "commands": command_rows,
        "missingNativeOptions": sorted({opt for row in command_rows for opt in row["missingNativeOptions"]}),
        "compatVerifier": compat_result,
        "cargoCheck": cargo_result,
    }
    if errors:
        return fail_json(errors, payload, args.json)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"[OK] native Rust command aliases verified for {len(entries)} Python scripts")
        print(f"[OK] all {len(all_options)} unique Python CLI option spellings are referenced by Rust source")
        print(f"[OK] functional parity scenario matrix covers {len(scenario_stems)} Python scripts")
        print("[OK] PowerShell/shell wrappers default to Rust and keep explicit Python compatibility fallback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
