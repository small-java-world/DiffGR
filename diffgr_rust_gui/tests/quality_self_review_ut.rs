// Static self-review and GUI-completion UTs.
// These tests intentionally verify checked-in contracts and assets; they complement
// cargo-level integration tests and parity smoke scripts.

const APP: &str = include_str!("../src/app.rs");
const CLI: &str = include_str!("../src/bin/diffgrctl.rs");
const VERIFY_SELF_REVIEW: &str = include_str!("../tools/verify_self_review.py");
const VERIFY_GUI_COMPLETION: &str = include_str!("../tools/verify_gui_completion.py");
const SELF_REVIEW_MD: &str = include_str!("../SELF_REVIEW.md");
const TESTING_MD: &str = include_str!("../TESTING.md");
const WINDOWS_MD: &str = include_str!("../WINDOWS.md");
const CHANGELOG_MD: &str = include_str!("../CHANGELOG.md");
const CARGO_TOML: &str = include_str!("../Cargo.toml");
const UT_MATRIX: &str = include_str!("../UT_MATRIX.json");
const SELF_REVIEW_AUDIT: &str = include_str!("../SELF_REVIEW_AUDIT.json");
const GUI_COMPLETION_AUDIT: &str = include_str!("../GUI_COMPLETION_AUDIT.json");
const SELF_REVIEW_SH: &str = include_str!("../self-review.sh");
const QUALITY_REVIEW_SH: &str = include_str!("../quality-review.sh");
const COMPLETION_REVIEW_SH: &str = include_str!("../completion-review.sh");
const SELF_REVIEW_PS1: &str = include_str!("../self-review.ps1");
const QUALITY_REVIEW_PS1: &str = include_str!("../quality-review.ps1");
const COMPLETION_REVIEW_PS1: &str = include_str!("../completion-review.ps1");

fn extract_struct_body<'a>(source: &'a str, name: &str) -> &'a str {
    let needle = format!("struct {name}");
    let start = source.find(&needle).expect("struct not found");
    let open = source[start..].find('{').expect("struct open brace") + start + 1;
    let close = source[open..]
        .find(
            "}
",
        )
        .expect("struct close brace")
        + open;
    &source[open..close]
}

fn extract_constructor_body<'a>(source: &'a str, fn_name: &str) -> &'a str {
    let needle = format!("fn {fn_name}");
    let start = source.find(&needle).expect("function not found");
    let ctor = source[start..]
        .find("VisibleCacheKey {")
        .expect("constructor")
        + start;
    let open = source[ctor..].find('{').expect("constructor open brace") + ctor + 1;
    let close = source[open..]
        .find(
            "}
    }",
        )
        .expect("constructor close brace")
        + open;
    &source[open..close]
}

fn collect_field_names(body: &str) -> Vec<String> {
    body.lines()
        .filter_map(|line| {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with("//") || !trimmed.contains(':') {
                return None;
            }
            Some(trimmed.split(':').next().unwrap().trim().to_owned())
        })
        .collect()
}

#[test]
fn quality_self_review_gui_marker_001_pendingdocumentload() {
    assert!(
        APP.contains("PendingDocumentLoad"),
        "missing GUI marker: PendingDocumentLoad"
    );
}

#[test]
fn quality_self_review_gui_marker_002_pendingstatesave() {
    assert!(
        APP.contains("PendingStateSave"),
        "missing GUI marker: PendingStateSave"
    );
}

#[test]
fn quality_self_review_gui_marker_003_show_rows() {
    assert!(APP.contains("show_rows"), "missing GUI marker: show_rows");
}

#[test]
fn quality_self_review_gui_marker_004_cached_chunk_row() {
    assert!(
        APP.contains("cached_chunk_row"),
        "missing GUI marker: cached_chunk_row"
    );
}

#[test]
fn quality_self_review_gui_marker_005_max_chunk_row_cache() {
    assert!(
        APP.contains("MAX_CHUNK_ROW_CACHE"),
        "missing GUI marker: MAX_CHUNK_ROW_CACHE"
    );
}

#[test]
fn quality_self_review_gui_marker_006_chunk_row_cache_retain_radius() {
    assert!(
        APP.contains("CHUNK_ROW_CACHE_RETAIN_RADIUS"),
        "missing GUI marker: CHUNK_ROW_CACHE_RETAIN_RADIUS"
    );
}

#[test]
fn quality_self_review_gui_marker_007_prune_chunk_row_cache_around() {
    assert!(
        APP.contains("prune_chunk_row_cache_around"),
        "missing GUI marker: prune_chunk_row_cache_around"
    );
}

#[test]
fn quality_self_review_gui_marker_008_filter_apply_deadline() {
    assert!(
        APP.contains("filter_apply_deadline"),
        "missing GUI marker: filter_apply_deadline"
    );
}

#[test]
fn quality_self_review_gui_marker_009_maybe_apply_debounced_filters() {
    assert!(
        APP.contains("maybe_apply_debounced_filters"),
        "missing GUI marker: maybe_apply_debounced_filters"
    );
}

#[test]
fn quality_self_review_gui_marker_010_smooth_scroll_repaint() {
    assert!(
        APP.contains("smooth_scroll_repaint"),
        "missing GUI marker: smooth_scroll_repaint"
    );
}

#[test]
fn quality_self_review_gui_marker_011_clip_for_display() {
    assert!(
        APP.contains("clip_for_display"),
        "missing GUI marker: clip_for_display"
    );
}

#[test]
fn quality_self_review_gui_marker_012_draw_virtual_text() {
    assert!(
        APP.contains("draw_virtual_text"),
        "missing GUI marker: draw_virtual_text"
    );
}

#[test]
fn quality_self_review_gui_marker_013_difflineindexcache() {
    assert!(
        APP.contains("DiffLineIndexCache"),
        "missing GUI marker: DiffLineIndexCache"
    );
}

#[test]
fn quality_self_review_gui_marker_014_request_repaint_after() {
    assert!(
        APP.contains("request_repaint_after"),
        "missing GUI marker: request_repaint_after"
    );
}

#[test]
fn quality_self_review_gui_marker_015_reduce_motion() {
    assert!(
        APP.contains("reduce_motion"),
        "missing GUI marker: reduce_motion"
    );
}

#[test]
fn quality_self_review_gui_marker_016_persist_egui_memory() {
    assert!(
        APP.contains("persist_egui_memory"),
        "missing GUI marker: persist_egui_memory"
    );
}

#[test]
fn quality_self_review_gui_marker_017_state_json() {
    assert!(
        APP.contains("State JSONをコピー"),
        "missing GUI marker: State JSONをコピー"
    );
}

#[test]
fn quality_self_review_gui_marker_018_marker_18() {
    assert!(
        APP.contains("自己レビュー / 品質ゲート"),
        "missing GUI marker: 自己レビュー / 品質ゲート"
    );
}

#[test]
fn quality_self_review_gui_marker_019_background_io() {
    assert!(
        APP.contains("background_io"),
        "missing GUI marker: background_io"
    );
}

#[test]
fn quality_self_review_gui_marker_020_max_rendered_diff_chars() {
    assert!(
        APP.contains("MAX_RENDERED_DIFF_CHARS"),
        "missing GUI marker: MAX_RENDERED_DIFF_CHARS"
    );
}

#[test]
fn quality_self_review_gui_marker_021_draw_performance_overlay() {
    assert!(
        APP.contains("draw_performance_overlay"),
        "missing GUI marker: draw_performance_overlay"
    );
}

#[test]
fn quality_self_review_gui_marker_022_draw_diagnostics_panel() {
    assert!(
        APP.contains("draw_diagnostics_panel"),
        "missing GUI marker: draw_diagnostics_panel"
    );
}

#[test]
fn quality_self_review_gui_marker_023_copy_self_review_report() {
    assert!(
        APP.contains("copy_self_review_report"),
        "missing GUI marker: copy_self_review_report"
    );
}

#[test]
fn quality_self_review_gui_marker_024_save_self_review_report() {
    assert!(
        APP.contains("save_self_review_report"),
        "missing GUI marker: save_self_review_report"
    );
}

#[test]
fn quality_self_review_gui_marker_025_performance_health_label() {
    assert!(
        APP.contains("performance_health_label"),
        "missing GUI marker: performance_health_label"
    );
}

#[test]
fn quality_self_review_gui_marker_026_slow_frame_count() {
    assert!(
        APP.contains("slow_frame_count"),
        "missing GUI marker: slow_frame_count"
    );
}

#[test]
fn quality_self_review_gui_marker_027_frame_time_ema_ms() {
    assert!(
        APP.contains("frame_time_ema_ms"),
        "missing GUI marker: frame_time_ema_ms"
    );
}

#[test]
fn quality_self_review_gui_marker_028_show_performance_overlay() {
    assert!(
        APP.contains("show_performance_overlay"),
        "missing GUI marker: show_performance_overlay"
    );
}

#[test]
fn quality_self_review_gui_marker_029_marker_29() {
    assert!(APP.contains("診断"), "missing GUI marker: 診断");
}

#[test]
fn quality_self_review_gui_marker_030_on() {
    assert!(
        APP.contains("滑らかスクロールON"),
        "missing GUI marker: 滑らかスクロールON"
    );
}

#[test]
fn quality_self_review_gui_marker_031_marker_31() {
    assert!(
        APP.contains("低メモリ寄り"),
        "missing GUI marker: 低メモリ寄り"
    );
}

#[test]
fn quality_self_review_gui_marker_032_marker_32() {
    assert!(
        APP.contains("読込/自動保存を別スレッド"),
        "missing GUI marker: 読込/自動保存を別スレッド"
    );
}

#[test]
fn quality_self_review_gui_marker_033_marker_33() {
    assert!(
        APP.contains("超長行を省略描画"),
        "missing GUI marker: 超長行を省略描画"
    );
}

#[test]
fn quality_self_review_gui_marker_034_state() {
    assert!(APP.contains("State差分"), "missing GUI marker: State差分");
}

#[test]
fn quality_self_review_gui_marker_035_html() {
    assert!(APP.contains("HTML保存"), "missing GUI marker: HTML保存");
}

#[test]
fn quality_self_review_gui_marker_036_approval() {
    assert!(APP.contains("Approval"), "missing GUI marker: Approval");
}

#[test]
fn quality_self_review_gui_marker_037_coverage() {
    assert!(APP.contains("Coverage"), "missing GUI marker: Coverage");
}

#[test]
fn quality_self_review_gui_marker_038_layout() {
    assert!(APP.contains("Layout"), "missing GUI marker: Layout");
}

#[test]
fn quality_self_review_gui_marker_039_impact() {
    assert!(APP.contains("Impact"), "missing GUI marker: Impact");
}

#[test]
fn quality_self_review_gui_marker_040_tools() {
    assert!(APP.contains("Tools"), "missing GUI marker: Tools");
}

#[test]
fn quality_self_review_cli_marker_001_quality_review() {
    assert!(
        CLI.contains("quality-review"),
        "missing CLI marker: quality-review"
    );
}

#[test]
fn quality_self_review_cli_marker_002_self_review() {
    assert!(
        CLI.contains("self-review"),
        "missing CLI marker: self-review"
    );
}

#[test]
fn quality_self_review_cli_marker_003_gui_quality() {
    assert!(
        CLI.contains("gui-quality"),
        "missing CLI marker: gui-quality"
    );
}

#[test]
fn quality_self_review_cli_marker_004_cmd_quality_review() {
    assert!(
        CLI.contains("cmd_quality_review"),
        "missing CLI marker: cmd_quality_review"
    );
}

#[test]
fn quality_self_review_cli_marker_005_count_python_wrappers_for_rows() {
    assert!(
        CLI.contains("count_python_wrappers_for_rows"),
        "missing CLI marker: count_python_wrappers_for_rows"
    );
}

#[test]
fn quality_self_review_cli_marker_006_quality_markers() {
    assert!(
        CLI.contains("QUALITY_MARKERS"),
        "missing CLI marker: QUALITY_MARKERS"
    );
}

#[test]
fn quality_self_review_cli_marker_007_count_quality_markers() {
    assert!(
        CLI.contains("count_quality_markers"),
        "missing CLI marker: count_quality_markers"
    );
}

#[test]
fn quality_self_review_cli_marker_008_count_checked_in_rust_tests() {
    assert!(
        CLI.contains("count_checked_in_rust_tests"),
        "missing CLI marker: count_checked_in_rust_tests"
    );
}

#[test]
fn quality_self_review_cli_marker_009_visible_cache_key_compile_guard() {
    assert!(
        CLI.contains("visible_cache_key_compile_guard"),
        "missing CLI marker: visible_cache_key_compile_guard"
    );
}

#[test]
fn quality_self_review_cli_marker_010_json_file_array_len() {
    assert!(
        CLI.contains("json_file_array_len"),
        "missing CLI marker: json_file_array_len"
    );
}

#[test]
fn quality_self_review_cli_marker_011_json_number() {
    assert!(
        CLI.contains("json_number"),
        "missing CLI marker: json_number"
    );
}

#[test]
fn quality_self_review_cli_marker_012_python_script_parity_rows() {
    assert!(
        CLI.contains("python_script_parity_rows"),
        "missing CLI marker: python_script_parity_rows"
    );
}

#[test]
fn quality_self_review_cli_marker_013_generate_diffgr() {
    assert!(
        CLI.contains("generate-diffgr"),
        "missing CLI marker: generate-diffgr"
    );
}

#[test]
fn quality_self_review_cli_marker_014_autoslice_diffgr() {
    assert!(
        CLI.contains("autoslice-diffgr"),
        "missing CLI marker: autoslice-diffgr"
    );
}

#[test]
fn quality_self_review_cli_marker_015_refine_slices() {
    assert!(
        CLI.contains("refine-slices"),
        "missing CLI marker: refine-slices"
    );
}

#[test]
fn quality_self_review_cli_marker_016_view_diffgr_app() {
    assert!(
        CLI.contains("view-diffgr-app"),
        "missing CLI marker: view-diffgr-app"
    );
}

#[test]
fn quality_self_review_cli_marker_017_export_diffgr_html() {
    assert!(
        CLI.contains("export-diffgr-html"),
        "missing CLI marker: export-diffgr-html"
    );
}

#[test]
fn quality_self_review_cli_marker_018_serve_diffgr_report() {
    assert!(
        CLI.contains("serve-diffgr-report"),
        "missing CLI marker: serve-diffgr-report"
    );
}

#[test]
fn quality_self_review_cli_marker_019_extract_diffgr_state() {
    assert!(
        CLI.contains("extract-diffgr-state"),
        "missing CLI marker: extract-diffgr-state"
    );
}

#[test]
fn quality_self_review_cli_marker_020_apply_diffgr_state() {
    assert!(
        CLI.contains("apply-diffgr-state"),
        "missing CLI marker: apply-diffgr-state"
    );
}

#[test]
fn quality_self_review_cli_marker_021_diff_diffgr_state() {
    assert!(
        CLI.contains("diff-diffgr-state"),
        "missing CLI marker: diff-diffgr-state"
    );
}

#[test]
fn quality_self_review_cli_marker_022_merge_diffgr_state() {
    assert!(
        CLI.contains("merge-diffgr-state"),
        "missing CLI marker: merge-diffgr-state"
    );
}

#[test]
fn quality_self_review_cli_marker_023_apply_diffgr_state_diff() {
    assert!(
        CLI.contains("apply-diffgr-state-diff"),
        "missing CLI marker: apply-diffgr-state-diff"
    );
}

#[test]
fn quality_self_review_cli_marker_024_split_group_reviews() {
    assert!(
        CLI.contains("split-group-reviews"),
        "missing CLI marker: split-group-reviews"
    );
}

#[test]
fn quality_self_review_cli_marker_025_merge_group_reviews() {
    assert!(
        CLI.contains("merge-group-reviews"),
        "missing CLI marker: merge-group-reviews"
    );
}

#[test]
fn quality_self_review_cli_marker_026_impact_report() {
    assert!(
        CLI.contains("impact-report"),
        "missing CLI marker: impact-report"
    );
}

#[test]
fn quality_self_review_cli_marker_027_preview_rebased_merge() {
    assert!(
        CLI.contains("preview-rebased-merge"),
        "missing CLI marker: preview-rebased-merge"
    );
}

#[test]
fn quality_self_review_cli_marker_028_rebase_diffgr_state() {
    assert!(
        CLI.contains("rebase-diffgr-state"),
        "missing CLI marker: rebase-diffgr-state"
    );
}

#[test]
fn quality_self_review_cli_marker_029_rebase_reviews() {
    assert!(
        CLI.contains("rebase-reviews"),
        "missing CLI marker: rebase-reviews"
    );
}

#[test]
fn quality_self_review_cli_marker_030_export_review_bundle() {
    assert!(
        CLI.contains("export-review-bundle"),
        "missing CLI marker: export-review-bundle"
    );
}

#[test]
fn quality_self_review_cli_marker_031_verify_review_bundle() {
    assert!(
        CLI.contains("verify-review-bundle"),
        "missing CLI marker: verify-review-bundle"
    );
}

#[test]
fn quality_self_review_cli_marker_032_approve_virtual_pr() {
    assert!(
        CLI.contains("approve-virtual-pr"),
        "missing CLI marker: approve-virtual-pr"
    );
}

#[test]
fn quality_self_review_cli_marker_033_request_changes() {
    assert!(
        CLI.contains("request-changes"),
        "missing CLI marker: request-changes"
    );
}

#[test]
fn quality_self_review_cli_marker_034_check_virtual_pr_approval() {
    assert!(
        CLI.contains("check-virtual-pr-approval"),
        "missing CLI marker: check-virtual-pr-approval"
    );
}

#[test]
fn quality_self_review_cli_marker_035_check_virtual_pr_coverage() {
    assert!(
        CLI.contains("check-virtual-pr-coverage"),
        "missing CLI marker: check-virtual-pr-coverage"
    );
}

#[test]
fn quality_self_review_cli_marker_036_summarize_diffgr() {
    assert!(
        CLI.contains("summarize-diffgr"),
        "missing CLI marker: summarize-diffgr"
    );
}

#[test]
fn quality_self_review_cli_marker_037_summarize_diffgr_state() {
    assert!(
        CLI.contains("summarize-diffgr-state"),
        "missing CLI marker: summarize-diffgr-state"
    );
}

#[test]
fn quality_self_review_cli_marker_038_summarize_reviewability() {
    assert!(
        CLI.contains("summarize-reviewability"),
        "missing CLI marker: summarize-reviewability"
    );
}

#[test]
fn quality_self_review_cli_marker_039_run_agent_cli() {
    assert!(
        CLI.contains("run-agent-cli"),
        "missing CLI marker: run-agent-cli"
    );
}

#[test]
fn quality_self_review_cli_marker_040_keep_new_groups() {
    assert!(
        CLI.contains("--keep-new-groups"),
        "missing CLI marker: --keep-new-groups"
    );
}

#[test]
fn quality_self_review_cli_marker_041_no_line_comments() {
    assert!(
        CLI.contains("--no-line-comments"),
        "missing CLI marker: --no-line-comments"
    );
}

#[test]
fn quality_self_review_cli_marker_042_impact_grouping() {
    assert!(
        CLI.contains("--impact-grouping"),
        "missing CLI marker: --impact-grouping"
    );
}

#[test]
fn quality_self_review_cli_marker_043_save_state_url() {
    assert!(
        CLI.contains("--save-state-url"),
        "missing CLI marker: --save-state-url"
    );
}

#[test]
fn quality_self_review_cli_marker_044_schema() {
    assert!(CLI.contains("--schema"), "missing CLI marker: --schema");
}

#[test]
fn quality_self_review_cli_marker_045_timeout() {
    assert!(CLI.contains("--timeout"), "missing CLI marker: --timeout");
}

#[test]
fn quality_self_review_tool_marker_001_expected_python_scripts() {
    assert!(
        VERIFY_SELF_REVIEW.contains("EXPECTED_PYTHON_SCRIPTS"),
        "missing tool/doc marker: EXPECTED_PYTHON_SCRIPTS"
    );
}

#[test]
fn quality_self_review_tool_marker_002_expected_wrappers() {
    assert!(
        VERIFY_SELF_REVIEW.contains("EXPECTED_WRAPPERS"),
        "missing tool/doc marker: EXPECTED_WRAPPERS"
    );
}

#[test]
fn quality_self_review_tool_marker_003_expected_functional_scenarios() {
    assert!(
        VERIFY_SELF_REVIEW.contains("EXPECTED_FUNCTIONAL_SCENARIOS"),
        "missing tool/doc marker: EXPECTED_FUNCTIONAL_SCENARIOS"
    );
}

#[test]
fn quality_self_review_tool_marker_004_expected_compat_sources() {
    assert!(
        VERIFY_SELF_REVIEW.contains("EXPECTED_COMPAT_SOURCES"),
        "missing tool/doc marker: EXPECTED_COMPAT_SOURCES"
    );
}

#[test]
fn quality_self_review_tool_marker_005_expected_python_options() {
    assert!(
        VERIFY_SELF_REVIEW.contains("EXPECTED_PYTHON_OPTIONS"),
        "missing tool/doc marker: EXPECTED_PYTHON_OPTIONS"
    );
}

#[test]
fn quality_self_review_tool_marker_006_min_rust_tests() {
    assert!(
        VERIFY_SELF_REVIEW.contains("MIN_RUST_TESTS"),
        "missing tool/doc marker: MIN_RUST_TESTS"
    );
}

#[test]
fn quality_self_review_tool_marker_007_gui_markers() {
    assert!(
        VERIFY_SELF_REVIEW.contains("GUI_MARKERS"),
        "missing tool/doc marker: GUI_MARKERS"
    );
}

#[test]
fn quality_self_review_tool_marker_008_visible_cache_struct_fields() {
    assert!(
        VERIFY_SELF_REVIEW.contains("visible_cache_struct_fields"),
        "missing tool/doc marker: visible_cache_struct_fields"
    );
}

#[test]
fn quality_self_review_tool_marker_009_visible_cache_constructor_fields() {
    assert!(
        VERIFY_SELF_REVIEW.contains("visible_cache_constructor_fields"),
        "missing tool/doc marker: visible_cache_constructor_fields"
    );
}

#[test]
fn quality_self_review_tool_marker_010_verify_manifest() {
    assert!(
        VERIFY_SELF_REVIEW.contains("verify_manifest"),
        "missing tool/doc marker: verify_manifest"
    );
}

#[test]
fn quality_self_review_tool_marker_011_verify_gui() {
    assert!(
        VERIFY_SELF_REVIEW.contains("verify_gui"),
        "missing tool/doc marker: verify_gui"
    );
}

#[test]
fn quality_self_review_tool_marker_012_subgates() {
    assert!(
        VERIFY_SELF_REVIEW.contains("subgates"),
        "missing tool/doc marker: subgates"
    );
}

#[test]
fn quality_self_review_tool_marker_013_strict() {
    assert!(
        VERIFY_SELF_REVIEW.contains("--strict"),
        "missing tool/doc marker: --strict"
    );
}

#[test]
fn quality_self_review_tool_marker_014_self_review_audit_json() {
    assert!(
        VERIFY_SELF_REVIEW.contains("SELF_REVIEW_AUDIT.json"),
        "missing tool/doc marker: SELF_REVIEW_AUDIT.json"
    );
}

#[test]
fn quality_self_review_tool_marker_015_diffgr_gui_completion_verify_result() {
    assert!(
        VERIFY_GUI_COMPLETION.contains("diffgr-gui-completion-verify-result"),
        "missing tool/doc marker: diffgr-gui-completion-verify-result"
    );
}

#[test]
fn quality_self_review_tool_marker_016_check_subgates() {
    assert!(
        VERIFY_GUI_COMPLETION.contains("--check-subgates"),
        "missing tool/doc marker: --check-subgates"
    );
}

#[test]
fn quality_self_review_tool_marker_017_gui_completion_audit_json() {
    assert!(
        VERIFY_GUI_COMPLETION.contains("GUI_COMPLETION_AUDIT.json"),
        "missing tool/doc marker: GUI_COMPLETION_AUDIT.json"
    );
}

#[test]
fn quality_self_review_tool_marker_018_verify_self_review() {
    assert!(
        VERIFY_GUI_COMPLETION.contains("verify_self_review"),
        "missing tool/doc marker: verify_self_review"
    );
}

#[test]
fn quality_self_review_tool_marker_019_windows_gates() {
    assert!(
        SELF_REVIEW_MD.contains("Windows gates"),
        "missing tool/doc marker: Windows gates"
    );
}

#[test]
fn quality_self_review_tool_marker_020_shell_gates() {
    assert!(
        SELF_REVIEW_MD.contains("Shell gates"),
        "missing tool/doc marker: Shell gates"
    );
}

#[test]
fn quality_self_review_tool_marker_021_marker_21() {
    assert!(
        SELF_REVIEW_MD.contains("診断"),
        "missing tool/doc marker: 診断"
    );
}

#[test]
fn quality_self_review_tool_marker_022_hud() {
    assert!(
        SELF_REVIEW_MD.contains("性能HUD"),
        "missing tool/doc marker: 性能HUD"
    );
}

#[test]
fn quality_self_review_file_exists_001_self_review_sh() {
    assert!(
        std::path::Path::new("self-review.sh").exists(),
        "missing file: self-review.sh"
    );
}

#[test]
fn quality_self_review_file_exists_002_self_review_ps1() {
    assert!(
        std::path::Path::new("self-review.ps1").exists(),
        "missing file: self-review.ps1"
    );
}

#[test]
fn quality_self_review_file_exists_003_windows_self_review_windows_ps1() {
    assert!(
        std::path::Path::new("windows/self-review-windows.ps1").exists(),
        "missing file: windows/self-review-windows.ps1"
    );
}

#[test]
fn quality_self_review_file_exists_004_self_review_cmd() {
    assert!(
        std::path::Path::new("Self Review.cmd").exists(),
        "missing file: Self Review.cmd"
    );
}

#[test]
fn quality_self_review_file_exists_005_quality_review_sh() {
    assert!(
        std::path::Path::new("quality-review.sh").exists(),
        "missing file: quality-review.sh"
    );
}

#[test]
fn quality_self_review_file_exists_006_quality_review_ps1() {
    assert!(
        std::path::Path::new("quality-review.ps1").exists(),
        "missing file: quality-review.ps1"
    );
}

#[test]
fn quality_self_review_file_exists_007_windows_quality_review_windows_ps1() {
    assert!(
        std::path::Path::new("windows/quality-review-windows.ps1").exists(),
        "missing file: windows/quality-review-windows.ps1"
    );
}

#[test]
fn quality_self_review_file_exists_008_quality_review_cmd() {
    assert!(
        std::path::Path::new("Quality Review.cmd").exists(),
        "missing file: Quality Review.cmd"
    );
}

#[test]
fn quality_self_review_file_exists_009_completion_review_sh() {
    assert!(
        std::path::Path::new("completion-review.sh").exists(),
        "missing file: completion-review.sh"
    );
}

#[test]
fn quality_self_review_file_exists_010_completion_review_ps1() {
    assert!(
        std::path::Path::new("completion-review.ps1").exists(),
        "missing file: completion-review.ps1"
    );
}

#[test]
fn quality_self_review_file_exists_011_windows_gui_completion_verify_windows_ps1() {
    assert!(
        std::path::Path::new("windows/gui-completion-verify-windows.ps1").exists(),
        "missing file: windows/gui-completion-verify-windows.ps1"
    );
}

#[test]
fn quality_self_review_file_exists_012_python_gui_completion_verify_cmd() {
    assert!(
        std::path::Path::new("Python GUI Completion Verify.cmd").exists(),
        "missing file: Python GUI Completion Verify.cmd"
    );
}

#[test]
fn quality_self_review_file_exists_013_tools_verify_self_review_py() {
    assert!(
        std::path::Path::new("tools/verify_self_review.py").exists(),
        "missing file: tools/verify_self_review.py"
    );
}

#[test]
fn quality_self_review_file_exists_014_tools_verify_gui_completion_py() {
    assert!(
        std::path::Path::new("tools/verify_gui_completion.py").exists(),
        "missing file: tools/verify_gui_completion.py"
    );
}

#[test]
fn quality_self_review_file_exists_015_self_review_md() {
    assert!(
        std::path::Path::new("SELF_REVIEW.md").exists(),
        "missing file: SELF_REVIEW.md"
    );
}

#[test]
fn quality_self_review_file_exists_016_self_review_audit_json() {
    assert!(
        std::path::Path::new("SELF_REVIEW_AUDIT.json").exists(),
        "missing file: SELF_REVIEW_AUDIT.json"
    );
}

#[test]
fn quality_self_review_file_exists_017_gui_completion_audit_json() {
    assert!(
        std::path::Path::new("GUI_COMPLETION_AUDIT.json").exists(),
        "missing file: GUI_COMPLETION_AUDIT.json"
    );
}

#[test]
fn quality_self_review_visible_cache_fields_match_constructor() {
    let struct_body = extract_struct_body(APP, "VisibleCacheKey");
    let ctor_body = extract_constructor_body(APP, "visible_cache_key");
    let mut struct_fields = collect_field_names(struct_body);
    let mut ctor_fields = collect_field_names(ctor_body);
    struct_fields.sort();
    ctor_fields.sort();
    assert_eq!(struct_fields, ctor_fields);
}

#[test]
fn quality_self_review_visible_cache_has_no_stale_input_fields() {
    let struct_body = extract_struct_body(APP, "VisibleCacheKey");
    assert!(!struct_body.contains("file_filter_input"));
    assert!(!struct_body.contains("content_filter_input"));
    assert!(!struct_body.contains("filter_apply_deadline"));
}

#[test]
fn quality_self_review_chunk_cache_is_bounded() {
    assert!(APP.contains("const MAX_CHUNK_ROW_CACHE: usize"));
    assert!(APP.contains("while self.visible_cache.rows.len() > MAX_CHUNK_ROW_CACHE"));
    assert!(APP.contains("CHUNK_ROW_CACHE_RETAIN_RADIUS"));
}

#[test]
fn quality_self_review_diagnostics_tab_is_selectable() {
    assert!(APP.contains("DetailTab::Diagnostics"));
    assert!(APP.contains("tab.label()"));
    assert!(APP.contains("draw_diagnostics_panel"));
}

#[test]
fn quality_self_review_top_bar_exposes_performance_hud() {
    assert!(APP.contains("性能HUD"));
    assert!(APP.contains("show_performance_overlay"));
    assert!(APP.contains("draw_performance_overlay"));
}

#[test]
fn quality_self_review_tools_panel_exposes_gate_commands() {
    assert!(APP.contains("自己レビュー / 品質ゲート"));
    assert!(APP.contains("self-review.ps1"));
    assert!(APP.contains("quality-review-windows.ps1"));
}

#[test]
fn quality_self_review_cli_has_usage_and_aliases() {
    assert!(CLI.contains("quality-review           Self-review"));
    assert!(CLI.contains(r#""quality-review" | "self-review" | "gui-quality""#));
}

#[test]
fn quality_self_review_cli_static_gate_has_expected_checks() {
    for marker in [
        "python script entries",
        "PowerShell wrappers",
        "shell wrappers",
        "native functional scenarios",
        "GUI quality markers",
        "Rust UT count",
        "static compile guard",
    ] {
        assert!(CLI.contains(marker), "missing CLI quality check {marker}");
    }
}

#[test]
fn quality_self_review_tool_minimums_are_high_enough() {
    assert!(VERIFY_SELF_REVIEW.contains("MIN_RUST_TESTS = 500"));
    assert!(VERIFY_SELF_REVIEW.contains("EXPECTED_PYTHON_SCRIPTS = 31"));
    assert!(VERIFY_SELF_REVIEW.contains("EXPECTED_PYTHON_OPTIONS = 80"));
}

#[test]
fn quality_self_review_audit_json_has_expected_format() {
    assert!(SELF_REVIEW_AUDIT.contains("diffgr-self-review-result"));
    assert!(GUI_COMPLETION_AUDIT.contains("diffgr-gui-completion-verify-result"));
}

#[test]
fn quality_self_review_ut_matrix_contains_new_category() {
    assert!(UT_MATRIX.contains("quality self review and GUI completion"));
    assert!(UT_MATRIX.contains("quality_self_review_ut.rs"));
    assert!(UT_MATRIX.contains("minimumRustTestCount"));
}

#[test]
fn quality_self_review_docs_reference_cargo_gates() {
    assert!(SELF_REVIEW_MD.contains("cargo test --all-targets"));
    assert!(TESTING_MD.contains("Consolidated self-review UT gates"));
    assert!(WINDOWS_MD.contains("Self-review / GUI completion checks"));
}

#[test]
fn quality_self_review_new_version_is_documented() {
    assert!(CARGO_TOML.contains(r#"version = "0.4.1""#));
    assert!(CHANGELOG_MD.contains("0.4.1 - UT depth expansion"));
}

#[test]
fn quality_self_review_shell_wrappers_call_expected_tools() {
    assert!(SELF_REVIEW_SH.contains("verify_self_review.py"));
    assert!(QUALITY_REVIEW_SH.contains("verify_self_review.py"));
    assert!(COMPLETION_REVIEW_SH.contains("verify_gui_completion.py"));
}

#[test]
fn quality_self_review_windows_wrappers_expose_json_switch() {
    assert!(SELF_REVIEW_PS1.contains("[switch]$Json"));
    assert!(QUALITY_REVIEW_PS1.contains("[switch]$Json"));
    assert!(COMPLETION_REVIEW_PS1.contains("[switch]$Json"));
}

#[test]
fn quality_self_review_python_wrapper_contract_001_generate_diffgr() {
    let ps1 = std::path::Path::new("scripts").join("generate_diffgr.ps1");
    let sh = std::path::Path::new("scripts").join("generate_diffgr.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for generate_diffgr"
    );
    assert!(sh.exists(), "missing shell wrapper for generate_diffgr");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_002_autoslice_diffgr() {
    let ps1 = std::path::Path::new("scripts").join("autoslice_diffgr.ps1");
    let sh = std::path::Path::new("scripts").join("autoslice_diffgr.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for autoslice_diffgr"
    );
    assert!(sh.exists(), "missing shell wrapper for autoslice_diffgr");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_003_refine_slices() {
    let ps1 = std::path::Path::new("scripts").join("refine_slices.ps1");
    let sh = std::path::Path::new("scripts").join("refine_slices.sh");
    assert!(ps1.exists(), "missing PowerShell wrapper for refine_slices");
    assert!(sh.exists(), "missing shell wrapper for refine_slices");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_004_prepare_review() {
    let ps1 = std::path::Path::new("scripts").join("prepare_review.ps1");
    let sh = std::path::Path::new("scripts").join("prepare_review.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for prepare_review"
    );
    assert!(sh.exists(), "missing shell wrapper for prepare_review");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_005_run_agent_cli() {
    let ps1 = std::path::Path::new("scripts").join("run_agent_cli.ps1");
    let sh = std::path::Path::new("scripts").join("run_agent_cli.sh");
    assert!(ps1.exists(), "missing PowerShell wrapper for run_agent_cli");
    assert!(sh.exists(), "missing shell wrapper for run_agent_cli");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_006_apply_slice_patch() {
    let ps1 = std::path::Path::new("scripts").join("apply_slice_patch.ps1");
    let sh = std::path::Path::new("scripts").join("apply_slice_patch.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for apply_slice_patch"
    );
    assert!(sh.exists(), "missing shell wrapper for apply_slice_patch");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_007_apply_diffgr_layout() {
    let ps1 = std::path::Path::new("scripts").join("apply_diffgr_layout.ps1");
    let sh = std::path::Path::new("scripts").join("apply_diffgr_layout.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for apply_diffgr_layout"
    );
    assert!(sh.exists(), "missing shell wrapper for apply_diffgr_layout");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_008_view_diffgr() {
    let ps1 = std::path::Path::new("scripts").join("view_diffgr.ps1");
    let sh = std::path::Path::new("scripts").join("view_diffgr.sh");
    assert!(ps1.exists(), "missing PowerShell wrapper for view_diffgr");
    assert!(sh.exists(), "missing shell wrapper for view_diffgr");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_009_view_diffgr_app() {
    let ps1 = std::path::Path::new("scripts").join("view_diffgr_app.ps1");
    let sh = std::path::Path::new("scripts").join("view_diffgr_app.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for view_diffgr_app"
    );
    assert!(sh.exists(), "missing shell wrapper for view_diffgr_app");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_010_export_diffgr_html() {
    let ps1 = std::path::Path::new("scripts").join("export_diffgr_html.ps1");
    let sh = std::path::Path::new("scripts").join("export_diffgr_html.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for export_diffgr_html"
    );
    assert!(sh.exists(), "missing shell wrapper for export_diffgr_html");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_011_serve_diffgr_report() {
    let ps1 = std::path::Path::new("scripts").join("serve_diffgr_report.ps1");
    let sh = std::path::Path::new("scripts").join("serve_diffgr_report.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for serve_diffgr_report"
    );
    assert!(sh.exists(), "missing shell wrapper for serve_diffgr_report");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_012_extract_diffgr_state() {
    let ps1 = std::path::Path::new("scripts").join("extract_diffgr_state.ps1");
    let sh = std::path::Path::new("scripts").join("extract_diffgr_state.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for extract_diffgr_state"
    );
    assert!(
        sh.exists(),
        "missing shell wrapper for extract_diffgr_state"
    );
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_013_apply_diffgr_state() {
    let ps1 = std::path::Path::new("scripts").join("apply_diffgr_state.ps1");
    let sh = std::path::Path::new("scripts").join("apply_diffgr_state.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for apply_diffgr_state"
    );
    assert!(sh.exists(), "missing shell wrapper for apply_diffgr_state");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_014_diff_diffgr_state() {
    let ps1 = std::path::Path::new("scripts").join("diff_diffgr_state.ps1");
    let sh = std::path::Path::new("scripts").join("diff_diffgr_state.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for diff_diffgr_state"
    );
    assert!(sh.exists(), "missing shell wrapper for diff_diffgr_state");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_015_merge_diffgr_state() {
    let ps1 = std::path::Path::new("scripts").join("merge_diffgr_state.ps1");
    let sh = std::path::Path::new("scripts").join("merge_diffgr_state.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for merge_diffgr_state"
    );
    assert!(sh.exists(), "missing shell wrapper for merge_diffgr_state");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_016_apply_diffgr_state_diff() {
    let ps1 = std::path::Path::new("scripts").join("apply_diffgr_state_diff.ps1");
    let sh = std::path::Path::new("scripts").join("apply_diffgr_state_diff.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for apply_diffgr_state_diff"
    );
    assert!(
        sh.exists(),
        "missing shell wrapper for apply_diffgr_state_diff"
    );
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_017_split_group_reviews() {
    let ps1 = std::path::Path::new("scripts").join("split_group_reviews.ps1");
    let sh = std::path::Path::new("scripts").join("split_group_reviews.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for split_group_reviews"
    );
    assert!(sh.exists(), "missing shell wrapper for split_group_reviews");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_018_merge_group_reviews() {
    let ps1 = std::path::Path::new("scripts").join("merge_group_reviews.ps1");
    let sh = std::path::Path::new("scripts").join("merge_group_reviews.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for merge_group_reviews"
    );
    assert!(sh.exists(), "missing shell wrapper for merge_group_reviews");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_019_impact_report() {
    let ps1 = std::path::Path::new("scripts").join("impact_report.ps1");
    let sh = std::path::Path::new("scripts").join("impact_report.sh");
    assert!(ps1.exists(), "missing PowerShell wrapper for impact_report");
    assert!(sh.exists(), "missing shell wrapper for impact_report");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_020_preview_rebased_merge() {
    let ps1 = std::path::Path::new("scripts").join("preview_rebased_merge.ps1");
    let sh = std::path::Path::new("scripts").join("preview_rebased_merge.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for preview_rebased_merge"
    );
    assert!(
        sh.exists(),
        "missing shell wrapper for preview_rebased_merge"
    );
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_021_rebase_diffgr_state() {
    let ps1 = std::path::Path::new("scripts").join("rebase_diffgr_state.ps1");
    let sh = std::path::Path::new("scripts").join("rebase_diffgr_state.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for rebase_diffgr_state"
    );
    assert!(sh.exists(), "missing shell wrapper for rebase_diffgr_state");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_022_rebase_reviews() {
    let ps1 = std::path::Path::new("scripts").join("rebase_reviews.ps1");
    let sh = std::path::Path::new("scripts").join("rebase_reviews.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for rebase_reviews"
    );
    assert!(sh.exists(), "missing shell wrapper for rebase_reviews");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_023_export_review_bundle() {
    let ps1 = std::path::Path::new("scripts").join("export_review_bundle.ps1");
    let sh = std::path::Path::new("scripts").join("export_review_bundle.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for export_review_bundle"
    );
    assert!(
        sh.exists(),
        "missing shell wrapper for export_review_bundle"
    );
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_024_verify_review_bundle() {
    let ps1 = std::path::Path::new("scripts").join("verify_review_bundle.ps1");
    let sh = std::path::Path::new("scripts").join("verify_review_bundle.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for verify_review_bundle"
    );
    assert!(
        sh.exists(),
        "missing shell wrapper for verify_review_bundle"
    );
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_025_approve_virtual_pr() {
    let ps1 = std::path::Path::new("scripts").join("approve_virtual_pr.ps1");
    let sh = std::path::Path::new("scripts").join("approve_virtual_pr.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for approve_virtual_pr"
    );
    assert!(sh.exists(), "missing shell wrapper for approve_virtual_pr");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_026_request_changes() {
    let ps1 = std::path::Path::new("scripts").join("request_changes.ps1");
    let sh = std::path::Path::new("scripts").join("request_changes.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for request_changes"
    );
    assert!(sh.exists(), "missing shell wrapper for request_changes");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_027_check_virtual_pr_approval() {
    let ps1 = std::path::Path::new("scripts").join("check_virtual_pr_approval.ps1");
    let sh = std::path::Path::new("scripts").join("check_virtual_pr_approval.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for check_virtual_pr_approval"
    );
    assert!(
        sh.exists(),
        "missing shell wrapper for check_virtual_pr_approval"
    );
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_028_check_virtual_pr_coverage() {
    let ps1 = std::path::Path::new("scripts").join("check_virtual_pr_coverage.ps1");
    let sh = std::path::Path::new("scripts").join("check_virtual_pr_coverage.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for check_virtual_pr_coverage"
    );
    assert!(
        sh.exists(),
        "missing shell wrapper for check_virtual_pr_coverage"
    );
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_029_summarize_diffgr() {
    let ps1 = std::path::Path::new("scripts").join("summarize_diffgr.ps1");
    let sh = std::path::Path::new("scripts").join("summarize_diffgr.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for summarize_diffgr"
    );
    assert!(sh.exists(), "missing shell wrapper for summarize_diffgr");
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_030_summarize_diffgr_state() {
    let ps1 = std::path::Path::new("scripts").join("summarize_diffgr_state.ps1");
    let sh = std::path::Path::new("scripts").join("summarize_diffgr_state.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for summarize_diffgr_state"
    );
    assert!(
        sh.exists(),
        "missing shell wrapper for summarize_diffgr_state"
    );
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}

#[test]
fn quality_self_review_python_wrapper_contract_031_summarize_reviewability() {
    let ps1 = std::path::Path::new("scripts").join("summarize_reviewability.ps1");
    let sh = std::path::Path::new("scripts").join("summarize_reviewability.sh");
    assert!(
        ps1.exists(),
        "missing PowerShell wrapper for summarize_reviewability"
    );
    assert!(
        sh.exists(),
        "missing shell wrapper for summarize_reviewability"
    );
    let ps1_text = std::fs::read_to_string(ps1).unwrap();
    let sh_text = std::fs::read_to_string(sh).unwrap();
    assert!(ps1_text.contains("CompatPython"));
    assert!(sh_text.contains("compat-python"));
}
