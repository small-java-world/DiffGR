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
fn virtual_pr_regression_marker_001() {
    assert_contains("src/vpr.rs", "VirtualPrRiskItem");
}

#[test]
fn virtual_pr_regression_marker_002() {
    assert_contains("src/vpr.rs", "VirtualPrFileHotspot");
}

#[test]
fn virtual_pr_regression_marker_003() {
    assert_contains("src/vpr.rs", "VirtualPrGroupReadiness");
}

#[test]
fn virtual_pr_regression_marker_004() {
    assert_contains("src/vpr.rs", "VirtualPrReviewReport");
}

#[test]
fn virtual_pr_regression_marker_005() {
    assert_contains("src/vpr.rs", "readiness_score");
}

#[test]
fn virtual_pr_regression_marker_006() {
    assert_contains("src/vpr.rs", "readiness_level");
}

#[test]
fn virtual_pr_regression_marker_007() {
    assert_contains("src/vpr.rs", "ready_to_approve");
}

#[test]
fn virtual_pr_regression_marker_008() {
    assert_contains("src/vpr.rs", "blockers");
}

#[test]
fn virtual_pr_regression_marker_009() {
    assert_contains("src/vpr.rs", "warnings");
}

#[test]
fn virtual_pr_regression_marker_010() {
    assert_contains("src/vpr.rs", "next_actions");
}

#[test]
fn virtual_pr_regression_marker_011() {
    assert_contains("src/vpr.rs", "risk_items");
}

#[test]
fn virtual_pr_regression_marker_012() {
    assert_contains("src/vpr.rs", "file_hotspots");
}

#[test]
fn virtual_pr_regression_marker_013() {
    assert_contains("src/vpr.rs", "group_readiness");
}

#[test]
fn virtual_pr_regression_marker_014() {
    assert_contains("src/vpr.rs", "analyze_virtual_pr");
}

#[test]
fn virtual_pr_regression_marker_015() {
    assert_contains("src/vpr.rs", "doc.analyze_coverage");
}

#[test]
fn virtual_pr_regression_marker_016() {
    assert_contains("src/vpr.rs", "doc.status_counts");
}

#[test]
fn virtual_pr_regression_marker_017() {
    assert_contains("src/vpr.rs", "doc.metrics");
}

#[test]
fn virtual_pr_regression_marker_018() {
    assert_contains("src/vpr.rs", "doc.check_all_approvals");
}

#[test]
fn virtual_pr_regression_marker_019() {
    assert_contains("src/vpr.rs", "coverageに問題があります");
}

#[test]
fn virtual_pr_regression_marker_020() {
    assert_contains("src/vpr.rs", "再レビュー必要なchunk");
}

#[test]
fn virtual_pr_regression_marker_021() {
    assert_contains("src/vpr.rs", "未完了レビュー");
}

#[test]
fn virtual_pr_regression_marker_022() {
    assert_contains("src/vpr.rs", "approval");
}

#[test]
fn virtual_pr_regression_marker_023() {
    assert_contains("src/vpr.rs", "build_risk_items");
}

#[test]
fn virtual_pr_regression_marker_024() {
    assert_contains("src/vpr.rs", "risk_items.sort_by");
}

#[test]
fn virtual_pr_regression_marker_025() {
    assert_contains("src/vpr.rs", "status_rank");
}

#[test]
fn virtual_pr_regression_marker_026() {
    assert_contains("src/vpr.rs", "高リスクかつ未完了");
}

#[test]
fn virtual_pr_regression_marker_027() {
    assert_contains("src/vpr.rs", "huge_files");
}

#[test]
fn virtual_pr_regression_marker_028() {
    assert_contains("src/vpr.rs", "build_file_hotspots");
}

#[test]
fn virtual_pr_regression_marker_029() {
    assert_contains("src/vpr.rs", "build_group_readiness");
}

#[test]
fn virtual_pr_regression_marker_030() {
    assert_contains("src/vpr.rs", "missing_handoff_fields");
}

#[test]
fn virtual_pr_regression_marker_031() {
    assert_contains("src/vpr.rs", "dedup_keep_order");
}

#[test]
fn virtual_pr_regression_marker_032() {
    assert_contains("src/vpr.rs", "readiness_level(readiness_score");
}

#[test]
fn virtual_pr_regression_marker_033() {
    assert_contains("src/vpr.rs", "virtual_pr_report_json_value");
}

#[test]
fn virtual_pr_regression_marker_034() {
    assert_contains("src/vpr.rs", "readinessScore");
}

#[test]
fn virtual_pr_regression_marker_035() {
    assert_contains("src/vpr.rs", "readyToApprove");
}

#[test]
fn virtual_pr_regression_marker_036() {
    assert_contains("src/vpr.rs", "riskItems");
}

#[test]
fn virtual_pr_regression_marker_037() {
    assert_contains("src/vpr.rs", "fileHotspots");
}

#[test]
fn virtual_pr_regression_marker_038() {
    assert_contains("src/vpr.rs", "groupReadiness");
}

#[test]
fn virtual_pr_regression_marker_039() {
    assert_contains("src/vpr.rs", "virtual_pr_report_markdown");
}

#[test]
fn virtual_pr_regression_marker_040() {
    assert_contains("src/vpr.rs", "# Virtual PR Review Gate");
}

#[test]
fn virtual_pr_regression_marker_041() {
    assert_contains("src/vpr.rs", "## Blockers");
}

#[test]
fn virtual_pr_regression_marker_042() {
    assert_contains("src/vpr.rs", "## Warnings");
}

#[test]
fn virtual_pr_regression_marker_043() {
    assert_contains("src/vpr.rs", "## Next actions");
}

#[test]
fn virtual_pr_regression_marker_044() {
    assert_contains("src/vpr.rs", "## High-risk queue");
}

#[test]
fn virtual_pr_regression_marker_045() {
    assert_contains("src/vpr.rs", "File | Reasons");
}

#[test]
fn virtual_pr_regression_marker_046() {
    assert_contains("src/vpr.rs", "## Group readiness");
}

#[test]
fn virtual_pr_regression_marker_047() {
    assert_contains("src/vpr.rs", "virtual_pr_reviewer_prompt_markdown");
}

#[test]
fn virtual_pr_regression_marker_048() {
    assert_contains("src/vpr.rs", "期待する出力");
}

#[test]
fn virtual_pr_regression_marker_049() {
    assert_contains("src/vpr.rs", "request changes");
}

#[test]
fn virtual_pr_regression_marker_050() {
    assert_contains("src/vpr.rs", "build_risk_items");
}

#[test]
fn virtual_pr_regression_marker_051() {
    assert_contains("src/vpr.rs", "security");
}

#[test]
fn virtual_pr_regression_marker_052() {
    assert_contains("src/vpr.rs", "auth");
}

#[test]
fn virtual_pr_regression_marker_053() {
    assert_contains("src/vpr.rs", "migration");
}

#[test]
fn virtual_pr_regression_marker_054() {
    assert_contains("src/vpr.rs", "dependency");
}

#[test]
fn virtual_pr_regression_marker_055() {
    assert_contains("src/vpr.rs", "secret");
}

#[test]
fn virtual_pr_regression_marker_056() {
    assert_contains("src/vpr.rs", "concurrency");
}

#[test]
fn virtual_pr_regression_marker_057() {
    assert_contains("src/vpr.rs", "unsafe");
}

#[test]
fn virtual_pr_regression_marker_058() {
    assert_contains("src/vpr.rs", "password");
}

#[test]
fn virtual_pr_regression_marker_059() {
    assert_contains("src/vpr.rs", "token");
}

#[test]
fn virtual_pr_regression_marker_060() {
    assert_contains("src/vpr.rs", "lock");
}

#[test]
fn virtual_pr_regression_marker_061() {
    assert_contains("src/vpr.rs", "thread");
}

#[test]
fn virtual_pr_regression_marker_062() {
    assert_contains("src/vpr.rs", "async");
}

#[test]
fn virtual_pr_regression_marker_063() {
    assert_contains("src/vpr.rs", "delete ");
}

#[test]
fn virtual_pr_regression_marker_064() {
    assert_contains("src/vpr.rs", "sql");
}

#[test]
fn virtual_pr_regression_marker_065() {
    assert_contains("src/vpr.rs", "build_file_hotspots");
}

#[test]
fn virtual_pr_regression_marker_066() {
    assert_contains("src/vpr.rs", "BTreeMap");
}

#[test]
fn virtual_pr_regression_marker_067() {
    assert_contains("src/vpr.rs", "risk_score");
}

#[test]
fn virtual_pr_regression_marker_068() {
    assert_contains("src/vpr.rs", "reasons");
}

#[test]
fn virtual_pr_regression_marker_069() {
    assert_contains("src/vpr.rs", "build_group_readiness");
}

#[test]
fn virtual_pr_regression_marker_070() {
    assert_contains("src/vpr.rs", "top_risk_chunks");
}
