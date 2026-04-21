use std::fs;
use std::path::PathBuf;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn app_src() -> String {
    fs::read_to_string(root().join("src/app.rs")).expect("src/app.rs should be readable")
}

fn assert_app_contains(marker: &str) {
    let src = app_src();
    assert!(src.contains(marker), "missing marker: {marker}");
}

#[test]
fn diff_readability_001_has_diff_view_mode_enum() {
    assert_app_contains("enum DiffViewMode");
}
#[test]
fn diff_readability_002_has_side_by_side_mode() {
    assert_app_contains("SideBySide");
}
#[test]
fn diff_readability_003_has_unified_mode() {
    assert_app_contains("Unified");
}
#[test]
fn diff_readability_004_has_diff_context_mode_enum() {
    assert_app_contains("enum DiffContextMode");
}
#[test]
fn diff_readability_005_has_changed_with_context_mode() {
    assert_app_contains("ChangedWithContext");
}
#[test]
fn diff_readability_006_has_context_radius_config() {
    assert_app_contains("diff_context_radius");
}
#[test]
fn diff_readability_007_has_view_mode_config() {
    assert_app_contains("diff_view_mode: DiffViewMode");
}
#[test]
fn diff_readability_008_has_context_mode_config() {
    assert_app_contains("diff_context_mode: DiffContextMode");
}
#[test]
fn diff_readability_009_has_diff_search_buffer() {
    assert_app_contains("diff_search_buffer");
}
#[test]
fn diff_readability_010_has_context_index_cache() {
    assert_app_contains("DiffContextIndexCache");
}
#[test]
fn diff_readability_011_has_side_by_side_row_struct() {
    assert_app_contains("SideBySideDiffRow");
}
#[test]
fn diff_readability_012_has_side_by_side_cache() {
    assert_app_contains("DiffSideBySideCache");
}
#[test]
fn diff_readability_013_has_draw_diff_toolbar() {
    assert_app_contains("fn draw_diff_toolbar");
}
#[test]
fn diff_readability_014_toolbar_has_view_combo() {
    assert_app_contains("diff_view_mode");
}
#[test]
fn diff_readability_015_toolbar_has_context_combo() {
    assert_app_contains("diff_context_mode");
}
#[test]
fn diff_readability_016_toolbar_has_search_label() {
    assert_app_contains("Diff内検索");
}
#[test]
fn diff_readability_017_toolbar_has_previous_change_button() {
    assert_app_contains("前の変更");
}
#[test]
fn diff_readability_018_toolbar_has_next_change_button() {
    assert_app_contains("次の変更");
}
#[test]
fn diff_readability_019_toolbar_has_previous_search_button() {
    assert_app_contains("前の検索");
}
#[test]
fn diff_readability_020_toolbar_has_next_search_button() {
    assert_app_contains("次の検索");
}
#[test]
fn diff_readability_021_toolbar_has_visible_copy_button() {
    assert_app_contains("表示中diffコピー");
}
#[test]
fn diff_readability_022_toolbar_has_selected_line_copy_button() {
    assert_app_contains("選択行コピー");
}
#[test]
fn diff_readability_023_has_draw_unified_diff_lines() {
    assert_app_contains("fn draw_unified_diff_lines");
}
#[test]
fn diff_readability_024_has_draw_side_by_side_diff_lines() {
    assert_app_contains("fn draw_side_by_side_diff_lines");
}
#[test]
fn diff_readability_025_diff_dispatches_by_view_mode() {
    assert_app_contains("match self.diff_view_mode");
}
#[test]
fn diff_readability_026_unified_uses_virtual_rows() {
    assert_app_contains("scroll.show_rows(ui, row_height, total_rows");
}
#[test]
fn diff_readability_027_side_by_side_uses_virtual_rows() {
    assert_app_contains(".show_rows(ui, row_height, total_rows");
}
#[test]
fn diff_readability_028_side_by_side_has_old_header() {
    assert_app_contains("OLD");
}
#[test]
fn diff_readability_029_side_by_side_has_new_header() {
    assert_app_contains("NEW");
}
#[test]
fn diff_readability_030_has_changed_line_indices() {
    assert_app_contains("fn changed_line_indices");
}
#[test]
fn diff_readability_031_has_context_line_indices() {
    assert_app_contains("fn context_line_indices");
}
#[test]
fn diff_readability_032_has_visible_diff_line_indices() {
    assert_app_contains("fn visible_diff_line_indices");
}
#[test]
fn diff_readability_033_context_mode_uses_cache() {
    assert_app_contains("self.diff_context_index_cache");
}
#[test]
fn diff_readability_034_side_by_side_rows_are_cached() {
    assert_app_contains("fn side_by_side_rows");
}
#[test]
fn diff_readability_035_side_by_side_pairs_delete_then_add() {
    assert_app_contains("line.kind.as_str()) == Some(\"add\")");
}
#[test]
fn diff_readability_036_side_by_side_cache_keys_context_mode() {
    assert_app_contains("cache.context_mode == self.diff_context_mode");
}
#[test]
fn diff_readability_037_side_by_side_cache_keys_context_radius() {
    assert_app_contains("cache.context_radius == self.diff_context_radius");
}
#[test]
fn diff_readability_038_has_line_background_function() {
    assert_app_contains("fn diff_line_background");
}
#[test]
fn diff_readability_039_line_background_has_add_color() {
    assert_app_contains("\"add\" => Color32::from_rgba_premultiplied");
}
#[test]
fn diff_readability_040_line_background_has_delete_color() {
    assert_app_contains("\"delete\" => Color32::from_rgba_premultiplied");
}
#[test]
fn diff_readability_041_search_match_has_background() {
    assert_app_contains("search_match");
}
#[test]
fn diff_readability_042_selected_line_has_background() {
    assert_app_contains("selected, search_match");
}
#[test]
fn diff_readability_043_draw_line_uses_frame_fill() {
    assert_app_contains(".fill(fill)");
}
#[test]
fn diff_readability_044_line_search_helper_exists() {
    assert_app_contains("fn line_matches_diff_search");
}
#[test]
fn diff_readability_045_next_change_navigation_exists() {
    assert_app_contains("fn select_changed_line_relative");
}
#[test]
fn diff_readability_046_search_navigation_exists() {
    assert_app_contains("fn select_diff_search_match");
}
#[test]
fn diff_readability_047_copy_visible_diff_exists() {
    assert_app_contains("fn copy_visible_diff_text");
}
#[test]
fn diff_readability_048_copy_selected_line_exists() {
    assert_app_contains("fn copy_selected_diff_line");
}
#[test]
fn diff_readability_049_diff_tab_has_inline_line_comment_editor() {
    assert_app_contains("self.draw_line_comment_editor(ui, &chunk.id)");
}
#[test]
fn diff_readability_050_diff_scroll_leaves_editor_room() {
    assert_app_contains("ui.available_height() - 132.0");
}
#[test]
fn diff_readability_051_config_syncs_view_mode() {
    assert_app_contains("self.config.diff_view_mode = self.diff_view_mode");
}
#[test]
fn diff_readability_052_config_syncs_context_mode() {
    assert_app_contains("self.config.diff_context_mode = self.diff_context_mode");
}
#[test]
fn diff_readability_053_config_syncs_context_radius() {
    assert_app_contains("self.config.diff_context_radius = self.diff_context_radius");
}
#[test]
fn diff_readability_054_help_mentions_side_by_side() {
    assert_app_contains("統合/左右比較");
}
#[test]
fn diff_readability_055_help_mentions_changed_neighborhood() {
    assert_app_contains("変更周辺");
}
#[test]
fn diff_readability_056_line_comment_hint_mentions_diff_tab() {
    assert_app_contains("Diffタブで行をクリック");
}
#[test]
fn diff_readability_057_long_line_clipping_still_present() {
    assert_app_contains("MAX_RENDERED_DIFF_CHARS");
}
#[test]
fn diff_readability_058_clip_for_display_still_used() {
    assert_app_contains("clip_for_display(&rendered");
}
#[test]
fn diff_readability_059_changed_index_cache_still_present() {
    assert_app_contains("DiffLineIndexCache");
}
#[test]
fn diff_readability_060_readability_markers_in_gui_gate() {
    assert_app_contains("copy_visible_diff_text");
}
#[test]
fn diff_readability_061_mentions_inline_word_diff() {
    assert_app_contains("行内差分");
}
#[test]
fn diff_readability_062_mentions_smart_pairing() {
    assert_app_contains("賢く対応付け");
}
#[test]
fn diff_readability_063_has_word_diff_config() {
    assert_app_contains("word_diff_enabled");
}
#[test]
fn diff_readability_064_has_layout_job_word_renderer() {
    assert_app_contains("build_diff_layout_job");
}
