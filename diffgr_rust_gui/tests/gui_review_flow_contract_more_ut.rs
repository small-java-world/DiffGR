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
fn gui_review_flow_marker_001() {
    assert_contains("src/app.rs", "enum DetailTab");
}

#[test]
fn gui_review_flow_marker_002() {
    assert_contains("src/app.rs", "DetailTab::Diff");
}

#[test]
fn gui_review_flow_marker_003() {
    assert_contains("src/app.rs", "DetailTab::Review");
}

#[test]
fn gui_review_flow_marker_004() {
    assert_contains("src/app.rs", "DetailTab::Handoff");
}

#[test]
fn gui_review_flow_marker_005() {
    assert_contains("src/app.rs", "DetailTab::Layout");
}

#[test]
fn gui_review_flow_marker_006() {
    assert_contains("src/app.rs", "DetailTab::Coverage");
}

#[test]
fn gui_review_flow_marker_007() {
    assert_contains("src/app.rs", "DetailTab::Impact");
}

#[test]
fn gui_review_flow_marker_008() {
    assert_contains("src/app.rs", "DetailTab::Approval");
}

#[test]
fn gui_review_flow_marker_009() {
    assert_contains("src/app.rs", "DetailTab::VirtualPr");
}

#[test]
fn gui_review_flow_marker_010() {
    assert_contains("src/app.rs", "DetailTab::Tools");
}

#[test]
fn gui_review_flow_marker_011() {
    assert_contains("src/app.rs", "DetailTab::Diagnostics");
}

#[test]
fn gui_review_flow_marker_012() {
    assert_contains("src/app.rs", "DetailTab::Summary");
}

#[test]
fn gui_review_flow_marker_013() {
    assert_contains("src/app.rs", "DetailTab::State");
}

#[test]
fn gui_review_flow_marker_014() {
    assert_contains("src/app.rs", "draw_review_summary_panel");
}

#[test]
fn gui_review_flow_marker_015() {
    assert_contains("src/app.rs", "draw_state_preview");
}

#[test]
fn gui_review_flow_marker_016() {
    assert_contains("src/app.rs", "draw_group_brief_editor");
}

#[test]
fn gui_review_flow_marker_017() {
    assert_contains("src/app.rs", "draw_layout_editor");
}

#[test]
fn gui_review_flow_marker_018() {
    assert_contains("src/app.rs", "draw_coverage_panel");
}

#[test]
fn gui_review_flow_marker_019() {
    assert_contains("src/app.rs", "draw_impact_panel");
}

#[test]
fn gui_review_flow_marker_020() {
    assert_contains("src/app.rs", "draw_approval_panel");
}

#[test]
fn gui_review_flow_marker_021() {
    assert_contains("src/app.rs", "draw_virtual_pr_panel");
}

#[test]
fn gui_review_flow_marker_022() {
    assert_contains("src/app.rs", "draw_tools_panel");
}

#[test]
fn gui_review_flow_marker_023() {
    assert_contains("src/app.rs", "draw_diagnostics_panel");
}

#[test]
fn gui_review_flow_marker_024() {
    assert_contains("src/app.rs", "draw_diff_toolbar");
}

#[test]
fn gui_review_flow_marker_025() {
    assert_contains("src/app.rs", "draw_diff_lines");
}

#[test]
fn gui_review_flow_marker_026() {
    assert_contains("src/app.rs", "draw_side_by_side_diff_lines");
}

#[test]
fn gui_review_flow_marker_027() {
    assert_contains("src/app.rs", "draw_unified_diff_lines");
}

#[test]
fn gui_review_flow_marker_028() {
    assert_contains("src/app.rs", "build_diff_layout_job");
}

#[test]
fn gui_review_flow_marker_029() {
    assert_contains("src/app.rs", "word_diff_enabled");
}

#[test]
fn gui_review_flow_marker_030() {
    assert_contains("src/app.rs", "word_diff_smart_pairing");
}

#[test]
fn gui_review_flow_marker_031() {
    assert_contains("src/app.rs", "DiffWordPairCache");
}

#[test]
fn gui_review_flow_marker_032() {
    assert_contains("src/app.rs", "DiffWordSegmentCache");
}

#[test]
fn gui_review_flow_marker_033() {
    assert_contains("src/app.rs", "DiffSideBySideCache");
}

#[test]
fn gui_review_flow_marker_034() {
    assert_contains("src/app.rs", "DiffContextIndexCache");
}

#[test]
fn gui_review_flow_marker_035() {
    assert_contains("src/app.rs", "PendingDocumentLoad");
}

#[test]
fn gui_review_flow_marker_036() {
    assert_contains("src/app.rs", "PendingStateSave");
}

#[test]
fn gui_review_flow_marker_037() {
    assert_contains("src/app.rs", "VirtualPrReportCache");
}

#[test]
fn gui_review_flow_marker_038() {
    assert_contains("src/app.rs", "performance_health_label");
}

#[test]
fn gui_review_flow_marker_039() {
    assert_contains("src/app.rs", "show_performance_overlay");
}

#[test]
fn gui_review_flow_marker_040() {
    assert_contains("src/app.rs", "smooth_scroll_repaint");
}

#[test]
fn gui_review_flow_marker_041() {
    assert_contains("src/app.rs", "filter_apply_deadline");
}

#[test]
fn gui_review_flow_marker_042() {
    assert_contains("src/app.rs", "clip_for_display");
}

#[test]
fn gui_review_flow_marker_043() {
    assert_contains("src/app.rs", "draw_virtual_text");
}

#[test]
fn gui_review_flow_marker_044() {
    assert_contains("src/app.rs", "MAX_CHUNK_ROW_CACHE");
}

#[test]
fn gui_review_flow_marker_045() {
    assert_contains("src/app.rs", "prune_chunk_row_cache_around");
}

#[test]
fn gui_review_flow_marker_046() {
    assert_contains("src/app.rs", "copy_visible_diff_text");
}

#[test]
fn gui_review_flow_marker_047() {
    assert_contains("src/app.rs", "copy_selected_diff_line");
}

#[test]
fn gui_review_flow_marker_048() {
    assert_contains("src/app.rs", "State差分…");
}

#[test]
fn gui_review_flow_marker_049() {
    assert_contains("src/app.rs", "State merge…");
}

#[test]
fn gui_review_flow_marker_050() {
    assert_contains("src/app.rs", "Coverageを見る");
}

#[test]
fn gui_review_flow_marker_051() {
    assert_contains("src/app.rs", "Impactを見る");
}

#[test]
fn gui_review_flow_marker_052() {
    assert_contains("src/app.rs", "Approvalを見る");
}

#[test]
fn gui_review_flow_marker_053() {
    assert_contains("src/app.rs", "仮想PRゲートを見る");
}

#[test]
fn gui_review_flow_marker_054() {
    assert_contains("src/app.rs", "State JSONを見る");
}

#[test]
fn gui_review_flow_marker_055() {
    assert_contains("src/app.rs", "表示中diffコピー");
}

#[test]
fn gui_review_flow_marker_056() {
    assert_contains("src/app.rs", "選択行コピー");
}

#[test]
fn gui_review_flow_marker_057() {
    assert_contains("src/app.rs", "行内差分");
}

#[test]
fn gui_review_flow_marker_058() {
    assert_contains("src/app.rs", "賢く対応付け");
}

#[test]
fn gui_review_flow_marker_059() {
    assert_contains("src/app.rs", "変更周辺");
}

#[test]
fn gui_review_flow_marker_060() {
    assert_contains("src/app.rs", "前の変更");
}

#[test]
fn gui_review_flow_marker_061() {
    assert_contains("src/app.rs", "次の変更");
}

#[test]
fn gui_review_flow_marker_062() {
    assert_contains("src/app.rs", "前の検索");
}

#[test]
fn gui_review_flow_marker_063() {
    assert_contains("src/app.rs", "次の検索");
}

#[test]
fn gui_review_flow_marker_064() {
    assert_contains("src/app.rs", "最重要chunkへ");
}

#[test]
fn gui_review_flow_marker_065() {
    assert_contains("src/app.rs", "未完了高リスクへ");
}

#[test]
fn gui_review_flow_marker_066() {
    assert_contains("src/app.rs", "Approvalへ");
}

#[test]
fn gui_review_flow_marker_067() {
    assert_contains("src/app.rs", "Coverageへ");
}

#[test]
fn gui_review_flow_marker_068() {
    assert_contains("src/app.rs", "Group readiness");
}

#[test]
fn gui_review_flow_marker_069() {
    assert_contains("src/app.rs", "File hotspots");
}

#[test]
fn gui_review_flow_marker_070() {
    assert_contains("src/app.rs", "GUI診断 / 固まりにくさチェック");
}

#[test]
fn gui_review_flow_marker_071() {
    assert_contains("src/app.rs", "性能HUD");
}

#[test]
fn gui_review_flow_marker_072() {
    assert_contains("src/app.rs", "自己レビュー / 品質ゲート");
}

#[test]
fn gui_review_flow_marker_073() {
    assert_contains("src/app.rs", "quality-review");
}

#[test]
fn gui_review_flow_marker_074() {
    assert_contains("src/app.rs", "State抽出...");
}

#[test]
fn gui_review_flow_marker_075() {
    assert_contains("src/app.rs", "Coverage JSON...");
}

#[test]
fn gui_review_flow_marker_076() {
    assert_contains("src/app.rs", "Layout JSON適用...");
}

#[test]
fn gui_review_flow_marker_077() {
    assert_contains("src/app.rs", "Impact old→current...");
}

#[test]
fn gui_review_flow_marker_078() {
    assert_contains("src/app.rs", "Approval JSON...");
}

#[test]
fn gui_review_flow_marker_079() {
    assert_contains("src/app.rs", "virtual_pr_reviewer_prompt_markdown");
}

#[test]
fn gui_review_flow_marker_080() {
    assert_contains("src/app.rs", "copy_self_review_report");
}
