use serde_json::Value;
use std::collections::BTreeSet;
use std::fs;
use std::path::PathBuf;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}
fn read(rel: &str) -> String {
    fs::read_to_string(root().join(rel)).unwrap()
}
fn manifest() -> Value {
    serde_json::from_str(include_str!("../PYTHON_PARITY_MANIFEST.json")).unwrap()
}
fn scenarios() -> Value {
    serde_json::from_str(include_str!("../NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json")).unwrap()
}

fn assert_wrapper_contract(stem: &str, native: &str) {
    let ps1 = read(&format!("scripts/{stem}.ps1"));
    assert!(
        ps1.contains("[switch]$CompatPython"),
        "{stem}.ps1 lacks -CompatPython switch"
    );
    assert!(
        ps1.contains("$env:DIFFGR_COMPAT_PYTHON"),
        "{stem}.ps1 lacks compat env switch"
    );
    assert!(
        ps1.contains(&format!("compat-python.ps1\" {stem}")),
        "{stem}.ps1 does not call compat python with stem"
    );
    assert!(
        ps1.contains(&format!("diffgrctl.ps1\" {native}")),
        "{stem}.ps1 does not default to native command {native}"
    );
    assert!(
        ps1.trim_end().ends_with("exit $LASTEXITCODE"),
        "{stem}.ps1 should propagate exit code"
    );

    let sh = read(&format!("scripts/{stem}.sh"));
    assert!(
        sh.starts_with("#!/usr/bin/env bash"),
        "{stem}.sh lacks bash shebang"
    );
    assert!(
        sh.contains("set -euo pipefail"),
        "{stem}.sh lacks strict shell mode"
    );
    assert!(
        sh.contains("DIFFGR_COMPAT_PYTHON"),
        "{stem}.sh lacks compat env switch"
    );
    assert!(
        sh.contains("--compat-python"),
        "{stem}.sh lacks explicit compat flag"
    );
    assert!(
        sh.contains(&format!("compat-python.sh\" {stem}")),
        "{stem}.sh does not call compat python with stem"
    );
    assert!(
        sh.contains(&format!("diffgrctl.sh\" {native}")),
        "{stem}.sh does not default to native command {native}"
    );
    assert!(
        root()
            .join(format!("compat/python/scripts/{stem}.py"))
            .exists(),
        "bundled compat python missing for {stem}"
    );
}

#[test]
fn wrapper_contract_for_generate_diffgr() {
    assert_wrapper_contract("generate_diffgr", "generate-diffgr");
}

#[test]
fn wrapper_contract_for_autoslice_diffgr() {
    assert_wrapper_contract("autoslice_diffgr", "autoslice-diffgr");
}

#[test]
fn wrapper_contract_for_refine_slices() {
    assert_wrapper_contract("refine_slices", "refine-slices");
}

#[test]
fn wrapper_contract_for_prepare_review() {
    assert_wrapper_contract("prepare_review", "prepare-review");
}

#[test]
fn wrapper_contract_for_run_agent_cli() {
    assert_wrapper_contract("run_agent_cli", "run-agent-cli");
}

#[test]
fn wrapper_contract_for_apply_slice_patch() {
    assert_wrapper_contract("apply_slice_patch", "apply-slice-patch");
}

#[test]
fn wrapper_contract_for_apply_diffgr_layout() {
    assert_wrapper_contract("apply_diffgr_layout", "apply-diffgr-layout");
}

#[test]
fn wrapper_contract_for_view_diffgr() {
    assert_wrapper_contract("view_diffgr", "view-diffgr");
}

#[test]
fn wrapper_contract_for_view_diffgr_app() {
    assert_wrapper_contract("view_diffgr_app", "view-diffgr-app");
}

#[test]
fn wrapper_contract_for_export_diffgr_html() {
    assert_wrapper_contract("export_diffgr_html", "export-diffgr-html");
}

#[test]
fn wrapper_contract_for_serve_diffgr_report() {
    assert_wrapper_contract("serve_diffgr_report", "serve-diffgr-report");
}

#[test]
fn wrapper_contract_for_extract_diffgr_state() {
    assert_wrapper_contract("extract_diffgr_state", "extract-diffgr-state");
}

#[test]
fn wrapper_contract_for_apply_diffgr_state() {
    assert_wrapper_contract("apply_diffgr_state", "apply-diffgr-state");
}

#[test]
fn wrapper_contract_for_diff_diffgr_state() {
    assert_wrapper_contract("diff_diffgr_state", "diff-diffgr-state");
}

#[test]
fn wrapper_contract_for_merge_diffgr_state() {
    assert_wrapper_contract("merge_diffgr_state", "merge-diffgr-state");
}

#[test]
fn wrapper_contract_for_apply_diffgr_state_diff() {
    assert_wrapper_contract("apply_diffgr_state_diff", "apply-diffgr-state-diff");
}

#[test]
fn wrapper_contract_for_split_group_reviews() {
    assert_wrapper_contract("split_group_reviews", "split-group-reviews");
}

#[test]
fn wrapper_contract_for_merge_group_reviews() {
    assert_wrapper_contract("merge_group_reviews", "merge-group-reviews");
}

#[test]
fn wrapper_contract_for_impact_report() {
    assert_wrapper_contract("impact_report", "impact-report");
}

#[test]
fn wrapper_contract_for_preview_rebased_merge() {
    assert_wrapper_contract("preview_rebased_merge", "preview-rebased-merge");
}

#[test]
fn wrapper_contract_for_rebase_diffgr_state() {
    assert_wrapper_contract("rebase_diffgr_state", "rebase-diffgr-state");
}

#[test]
fn wrapper_contract_for_rebase_reviews() {
    assert_wrapper_contract("rebase_reviews", "rebase-reviews");
}

#[test]
fn wrapper_contract_for_export_review_bundle() {
    assert_wrapper_contract("export_review_bundle", "export-review-bundle");
}

#[test]
fn wrapper_contract_for_verify_review_bundle() {
    assert_wrapper_contract("verify_review_bundle", "verify-review-bundle");
}

#[test]
fn wrapper_contract_for_approve_virtual_pr() {
    assert_wrapper_contract("approve_virtual_pr", "approve-virtual-pr");
}

#[test]
fn wrapper_contract_for_request_changes() {
    assert_wrapper_contract("request_changes", "request-changes");
}

#[test]
fn wrapper_contract_for_check_virtual_pr_approval() {
    assert_wrapper_contract("check_virtual_pr_approval", "check-virtual-pr-approval");
}

#[test]
fn wrapper_contract_for_check_virtual_pr_coverage() {
    assert_wrapper_contract("check_virtual_pr_coverage", "check-virtual-pr-coverage");
}

#[test]
fn wrapper_contract_for_summarize_diffgr() {
    assert_wrapper_contract("summarize_diffgr", "summarize-diffgr");
}

#[test]
fn wrapper_contract_for_summarize_diffgr_state() {
    assert_wrapper_contract("summarize_diffgr_state", "summarize-diffgr-state");
}

#[test]
fn wrapper_contract_for_summarize_reviewability() {
    assert_wrapper_contract("summarize_reviewability", "summarize-reviewability");
}

#[test]
fn wrapper_manifest_has_unique_sorted_stems() {
    let manifest = manifest();
    let entries = manifest["entries"].as_array().unwrap();
    let mut seen = BTreeSet::new();
    for entry in entries {
        assert!(seen.insert(entry["stem"].as_str().unwrap().to_owned()));
    }
    assert_eq!(
        seen.len(),
        manifest["scriptCount"].as_u64().unwrap() as usize
    );
}

#[test]
fn wrapper_scenarios_cover_manifest_stems() {
    let manifest = manifest();
    let scenarios = scenarios();
    let manifest_stems = manifest["entries"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e["stem"].as_str().unwrap())
        .collect::<BTreeSet<_>>();
    let scenario_stems = scenarios["scenarios"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e["script"].as_str().unwrap())
        .collect::<BTreeSet<_>>();
    assert_eq!(manifest_stems, scenario_stems);
}

#[test]
fn wrapper_scripts_readme_mentions_compat_and_native_modes() {
    let readme = read("scripts/README.md");
    assert!(readme.contains("CompatPython") || readme.contains("compat"));
    assert!(readme.contains("diffgrctl"));
}

#[test]
fn wrapper_root_diffgrctl_delegates_to_windows_script() {
    let ps1 = read("diffgrctl.ps1");
    assert!(ps1.contains(r#"windows\diffgrctl-windows.ps1"#));
    assert!(ps1.contains("ValueFromRemainingArguments"));
}

#[test]
fn wrapper_root_shell_delegates_to_cargo_or_binary() {
    let sh = read("diffgrctl.sh");
    assert!(sh.contains("diffgrctl"));
    assert!(sh.contains("cargo") || sh.contains("target/release"));
}

#[test]
fn wrapper_cmd_files_use_powershell_bypass() {
    for rel in [
        "Test.cmd",
        "Build Release.cmd",
        "Run DiffGR Review.cmd",
        "UT Matrix Verify.cmd",
    ] {
        let cmd = read(rel);
        assert!(
            cmd.contains("powershell") || cmd.contains("pwsh"),
            "{rel} should launch PowerShell"
        );
        assert!(
            cmd.contains("ExecutionPolicy") || cmd.contains("-File"),
            "{rel} should be double-click safe"
        );
    }
}

#[test]
fn wrapper_windows_ut_matrix_respects_python_env() {
    let ps1 = read("windows/ut-matrix-windows.ps1");
    assert!(ps1.contains("$env:PYTHON"));
    assert!(ps1.contains("verify_ut_matrix.py"));
}

#[test]
fn wrapper_python_compat_verify_has_compile_and_smoke_flags() {
    let py = read("tools/verify_python_parity.py");
    assert!(py.contains("--compile"));
    assert!(py.contains("--smoke"));
    assert!(py.contains("sourceFilesVerified"));
}

#[test]
fn wrapper_native_functional_verify_mentions_all_scenarios() {
    let py = read("tools/verify_functional_parity.py");
    assert!(py.contains("NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json"));
    assert!(py.contains("31") || py.contains("scriptCount"));
}

#[test]
fn wrapper_no_powershell_wrapper_defaults_to_compat_only() {
    let manifest = manifest();
    for entry in manifest["entries"].as_array().unwrap() {
        let stem = entry["stem"].as_str().unwrap();
        let ps1 = read(&format!("scripts/{stem}.ps1"));
        let compat_pos = ps1.find("compat-python.ps1").unwrap();
        let native_pos = ps1.find("diffgrctl.ps1").unwrap();
        assert!(
            compat_pos < native_pos,
            "{stem}.ps1 should choose compat only in if branch, native in else branch"
        );
    }
}
