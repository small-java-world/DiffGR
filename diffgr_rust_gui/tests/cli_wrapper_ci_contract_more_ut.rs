use std::fs;
use std::path::PathBuf;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn read(rel: &str) -> String {
    fs::read_to_string(root().join(rel)).unwrap_or_else(|err| panic!("failed to read {rel}: {err}"))
}

fn assert_contains(rel: &str, marker: &str) {
    let text = read(rel);
    assert!(text.contains(marker), "missing marker `{marker}` in {rel}");
}

fn assert_file_exists(rel: &str) {
    assert!(root().join(rel).exists(), "missing file: {rel}");
}

fn count_tests(rel: &str) -> usize {
    read(rel)
        .lines()
        .filter(|line| line.trim() == "#[test]")
        .count()
}

fn assert_count_at_least(rel: &str, minimum: usize) {
    let count = count_tests(rel);
    assert!(
        count >= minimum,
        "{rel} has {count} tests, expected >= {minimum}"
    );
}

#[test]
fn cli_wrapper_ci_contract_marker_001() {
    assert_contains("src/bin/diffgrctl.rs", "generate-diffgr");
}

#[test]
fn cli_wrapper_ci_contract_marker_002() {
    assert_contains("src/bin/diffgrctl.rs", "autoslice-diffgr");
}

#[test]
fn cli_wrapper_ci_contract_marker_003() {
    assert_contains("src/bin/diffgrctl.rs", "refine-slices");
}

#[test]
fn cli_wrapper_ci_contract_marker_004() {
    assert_contains("src/bin/diffgrctl.rs", "prepare-review");
}

#[test]
fn cli_wrapper_ci_contract_marker_005() {
    assert_contains("src/bin/diffgrctl.rs", "run-agent-cli");
}

#[test]
fn cli_wrapper_ci_contract_marker_006() {
    assert_contains("src/bin/diffgrctl.rs", "apply_slice_patch");
}

#[test]
fn cli_wrapper_ci_contract_marker_007() {
    assert_contains("src/bin/diffgrctl.rs", "apply_diffgr_layout");
}

#[test]
fn cli_wrapper_ci_contract_marker_008() {
    assert_contains("src/bin/diffgrctl.rs", "view_diffgr");
}

#[test]
fn cli_wrapper_ci_contract_marker_009() {
    assert_contains("src/bin/diffgrctl.rs", "view_diffgr_app");
}

#[test]
fn cli_wrapper_ci_contract_marker_010() {
    assert_contains("src/bin/diffgrctl.rs", "export_diffgr_html");
}

#[test]
fn cli_wrapper_ci_contract_marker_011() {
    assert_contains("src/bin/diffgrctl.rs", "serve_diffgr_report");
}

#[test]
fn cli_wrapper_ci_contract_marker_012() {
    assert_contains("src/bin/diffgrctl.rs", "extract_diffgr_state");
}

#[test]
fn cli_wrapper_ci_contract_marker_013() {
    assert_contains("src/bin/diffgrctl.rs", "apply_diffgr_state");
}

#[test]
fn cli_wrapper_ci_contract_marker_014() {
    assert_contains("src/bin/diffgrctl.rs", "diff_diffgr_state");
}

#[test]
fn cli_wrapper_ci_contract_marker_015() {
    assert_contains("src/bin/diffgrctl.rs", "merge_diffgr_state");
}

#[test]
fn cli_wrapper_ci_contract_marker_016() {
    assert_contains("src/bin/diffgrctl.rs", "apply_diffgr_state_diff");
}

#[test]
fn cli_wrapper_ci_contract_marker_017() {
    assert_contains("src/bin/diffgrctl.rs", "split_group_reviews");
}

#[test]
fn cli_wrapper_ci_contract_marker_018() {
    assert_contains("src/bin/diffgrctl.rs", "merge_group_reviews");
}

#[test]
fn cli_wrapper_ci_contract_marker_019() {
    assert_contains("src/bin/diffgrctl.rs", "impact_report");
}

#[test]
fn cli_wrapper_ci_contract_marker_020() {
    assert_contains("src/bin/diffgrctl.rs", "preview_rebased_merge");
}

#[test]
fn cli_wrapper_ci_contract_marker_021() {
    assert_contains("src/bin/diffgrctl.rs", "rebase_diffgr_state");
}

#[test]
fn cli_wrapper_ci_contract_marker_022() {
    assert_contains("src/bin/diffgrctl.rs", "rebase_reviews");
}

#[test]
fn cli_wrapper_ci_contract_marker_023() {
    assert_contains("src/bin/diffgrctl.rs", "export_review_bundle");
}

#[test]
fn cli_wrapper_ci_contract_marker_024() {
    assert_contains("src/bin/diffgrctl.rs", "verify_review_bundle");
}

#[test]
fn cli_wrapper_ci_contract_marker_025() {
    assert_contains("src/bin/diffgrctl.rs", "approve_virtual_pr");
}

#[test]
fn cli_wrapper_ci_contract_marker_026() {
    assert_contains("src/bin/diffgrctl.rs", "request_changes");
}

#[test]
fn cli_wrapper_ci_contract_marker_027() {
    assert_contains("src/bin/diffgrctl.rs", "check_virtual_pr_approval");
}

#[test]
fn cli_wrapper_ci_contract_marker_028() {
    assert_contains("src/bin/diffgrctl.rs", "check_virtual_pr_coverage");
}

#[test]
fn cli_wrapper_ci_contract_marker_029() {
    assert_contains("src/bin/diffgrctl.rs", "summarize_diffgr");
}

#[test]
fn cli_wrapper_ci_contract_marker_030() {
    assert_contains("src/bin/diffgrctl.rs", "summarize_diffgr_state");
}

#[test]
fn cli_wrapper_ci_contract_marker_031() {
    assert_contains("src/bin/diffgrctl.rs", "summarize_reviewability");
}

#[test]
fn cli_wrapper_ci_contract_marker_032() {
    assert_contains("src/bin/diffgrctl.rs", "virtual-pr-review");
}

#[test]
fn cli_wrapper_ci_contract_marker_033() {
    assert_contains("src/bin/diffgrctl.rs", "vpr-review");
}

#[test]
fn cli_wrapper_ci_contract_marker_034() {
    assert_contains("src/bin/diffgrctl.rs", "review-gate");
}

#[test]
fn cli_wrapper_ci_contract_marker_035() {
    assert_contains("src/bin/diffgrctl.rs", "quality-review");
}

#[test]
fn cli_wrapper_ci_contract_marker_036() {
    assert_contains("src/bin/diffgrctl.rs", "parity-audit");
}

#[test]
fn cli_wrapper_ci_contract_marker_037() {
    assert_contains("src/bin/diffgrctl.rs", "--input");
}

#[test]
fn cli_wrapper_ci_contract_marker_038() {
    assert_contains("src/bin/diffgrctl.rs", "--output");
}

#[test]
fn cli_wrapper_ci_contract_marker_039() {
    assert_contains("src/bin/diffgrctl.rs", "--state");
}

#[test]
fn cli_wrapper_ci_contract_marker_040() {
    assert_contains("src/bin/diffgrctl.rs", "--json");
}

#[test]
fn cli_wrapper_ci_contract_marker_041() {
    assert_contains("src/bin/diffgrctl.rs", "--markdown");
}

#[test]
fn cli_wrapper_ci_contract_marker_042() {
    assert_contains("src/bin/diffgrctl.rs", "--prompt");
}

#[test]
fn cli_wrapper_ci_contract_marker_043() {
    assert_contains("src/bin/diffgrctl.rs", "--max-items");
}

#[test]
fn cli_wrapper_ci_contract_marker_044() {
    assert_contains("src/bin/diffgrctl.rs", "--fail-on-blockers");
}

#[test]
fn cli_wrapper_ci_contract_marker_045() {
    assert_contains("src/bin/diffgrctl.rs", "--base");
}

#[test]
fn cli_wrapper_ci_contract_marker_046() {
    assert_contains("src/bin/diffgrctl.rs", "--feature");
}

#[test]
fn cli_wrapper_ci_contract_marker_047() {
    assert_contains("src/bin/diffgrctl.rs", "--group");
}

#[test]
fn cli_wrapper_ci_contract_marker_048() {
    assert_contains("src/bin/diffgrctl.rs", "--all");
}

#[test]
fn cli_wrapper_ci_contract_marker_049() {
    assert_contains("src/bin/diffgrctl.rs", "--bundle-out");
}

#[test]
fn cli_wrapper_ci_contract_marker_050() {
    assert_contains("src/bin/diffgrctl.rs", "--state-out");
}

#[test]
fn cli_wrapper_ci_contract_marker_051() {
    assert_contains("src/bin/diffgrctl.rs", "--manifest-out");
}

#[test]
fn cli_wrapper_ci_contract_marker_052() {
    assert_contains("src/bin/diffgrctl.rs", "--keep-new-groups");
}

#[test]
fn cli_wrapper_ci_contract_marker_053() {
    assert_contains("src/bin/diffgrctl.rs", "--no-line-comments");
}

#[test]
fn cli_wrapper_ci_contract_marker_054() {
    assert_contains("src/bin/diffgrctl.rs", "--impact-grouping");
}

#[test]
fn cli_wrapper_ci_contract_marker_055() {
    assert_contains("src/bin/diffgrctl.rs", "--save-state-url");
}

#[test]
fn cli_wrapper_ci_contract_marker_056() {
    assert_contains("src/bin/diffgrctl.rs", "--timeout");
}

#[test]
fn cli_wrapper_ci_contract_marker_057() {
    assert_contains("diffgrctl.ps1", "windows\\diffgrctl-windows.ps1");
}

#[test]
fn cli_wrapper_ci_contract_marker_058() {
    assert_contains("diffgrctl.sh", "scripts/diffgrctl.sh");
}

#[test]
fn cli_wrapper_ci_contract_marker_059() {
    assert_contains("windows/diffgrctl-windows.ps1", "diffgrctl.exe");
}

#[test]
fn cli_wrapper_ci_contract_marker_060() {
    assert_contains(
        "windows/test-windows.ps1",
        "testArgs = @('test', '--all-targets')",
    );
}

#[test]
fn cli_wrapper_ci_contract_marker_061() {
    assert_contains("windows/build-windows.ps1", "buildArgs = @('build')");
}

#[test]
fn cli_wrapper_ci_contract_marker_062() {
    assert_contains("windows/ut-matrix-windows.ps1", "verify_ut_matrix.py");
}

#[test]
fn cli_wrapper_ci_contract_marker_063() {
    assert_contains("windows/virtual-pr-review-windows.ps1", "FailOnBlockers");
}

#[test]
fn cli_wrapper_ci_contract_marker_064() {
    assert_contains(
        "windows/quality-review-windows.ps1",
        "verify_self_review.py",
    );
}

#[test]
fn cli_wrapper_ci_contract_marker_065() {
    assert_contains(
        "windows/native-functional-parity-windows.ps1",
        "native-functional-parity.ps1",
    );
}

#[test]
fn cli_wrapper_ci_contract_marker_066() {
    assert_contains(
        "windows/python-compat-verify-windows.ps1",
        "compat-python-verify.ps1",
    );
}

#[test]
fn cli_wrapper_ci_contract_marker_067() {
    assert_contains("virtual-pr-review.ps1", "diffgrctl.ps1");
}

#[test]
fn cli_wrapper_ci_contract_marker_068() {
    assert_contains("virtual-pr-review.sh", "virtual-pr-review");
}

#[test]
fn cli_wrapper_ci_contract_marker_069() {
    assert_contains(
        "virtual-pr-review-verify.ps1",
        "verify_virtual_pr_review.py",
    );
}

#[test]
fn cli_wrapper_ci_contract_marker_070() {
    assert_contains("virtual-pr-review-verify.sh", "verify_virtual_pr_review.py");
}
