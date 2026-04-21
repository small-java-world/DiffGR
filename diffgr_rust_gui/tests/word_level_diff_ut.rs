use diffgr_gui::diff_words::{
    line_similarity, match_delete_add_pairs, tokenize_for_word_diff, word_level_segments,
    DiffTextSegment, MAX_LINE_PAIR_CANDIDATES, MAX_WORD_DIFF_LINE_CHARS, MAX_WORD_DIFF_TOKENS,
};
use std::fs;
use std::path::PathBuf;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}
fn app_src() -> String {
    fs::read_to_string(root().join("src/app.rs")).expect("src/app.rs should be readable")
}
fn diff_words_src() -> String {
    fs::read_to_string(root().join("src/diff_words.rs"))
        .expect("src/diff_words.rs should be readable")
}
fn assert_app_contains(marker: &str) {
    let src = app_src();
    assert!(src.contains(marker), "missing app marker: {marker}");
}
fn assert_diff_words_contains(marker: &str) {
    let src = diff_words_src();
    assert!(src.contains(marker), "missing diff_words marker: {marker}");
}

#[test]
fn word_level_diff_001_tokenizer_splits_camel_case() {
    assert_eq!(tokenize_for_word_diff("userID"), vec!["user", "ID"]);
}
#[test]
fn word_level_diff_002_tokenizer_splits_identifier_punctuation() {
    assert_eq!(
        tokenize_for_word_diff("old_value+1"),
        vec!["old", "_", "value", "+", "1"]
    );
}
#[test]
fn word_level_diff_003_tokenizer_preserves_whitespace() {
    assert_eq!(tokenize_for_word_diff("a  b"), vec!["a", "  ", "b"]);
}
#[test]
fn word_level_diff_004_segments_mark_changed_number() {
    let (_, new) = word_level_segments("let count = 1;", "let count = 2;").unwrap();
    assert!(new.iter().any(|s| s.changed && s.text == "2"));
}
#[test]
fn word_level_diff_005_segments_keep_common_prefix() {
    let (old, _) = word_level_segments("return old_value;", "return new_value;").unwrap();
    assert!(old.iter().any(|s| !s.changed && s.text.contains("return ")));
}
#[test]
fn word_level_diff_006_segments_keep_common_suffix() {
    let (_, new) = word_level_segments("return old_value;", "return new_value;").unwrap();
    assert!(new.iter().any(|s| !s.changed && s.text.contains("_value;")));
}
#[test]
fn word_level_diff_007_segments_mark_inserted_word() {
    let (_, new) = word_level_segments("alpha gamma", "alpha beta gamma").unwrap();
    assert!(new.iter().any(|s| s.changed && s.text.contains("beta")));
}
#[test]
fn word_level_diff_008_segments_mark_deleted_word() {
    let (old, _) = word_level_segments("alpha beta gamma", "alpha gamma").unwrap();
    assert!(old.iter().any(|s| s.changed && s.text.contains("beta")));
}
#[test]
fn word_level_diff_009_exact_lines_have_no_changed_segments() {
    let (old, new) = word_level_segments("same line", "same line").unwrap();
    assert!(old.iter().all(|s| !s.changed));
    assert!(new.iter().all(|s| !s.changed));
}
#[test]
fn word_level_diff_010_long_lines_are_skipped() {
    let long = "x".repeat(MAX_WORD_DIFF_LINE_CHARS + 1);
    assert!(word_level_segments(&long, "short").is_none());
}
#[test]
fn word_level_diff_011_similarity_exact_is_one() {
    assert!((line_similarity("abc", "abc") - 1.0).abs() < f32::EPSILON);
}
#[test]
fn word_level_diff_012_similarity_related_exceeds_unrelated() {
    assert!(
        line_similarity("let count = old_total;", "let count = new_total;")
            > line_similarity("abc", "return user;")
    );
}
#[test]
fn word_level_diff_013_similarity_ignores_case_for_matching() {
    assert!(line_similarity("Return User", "return user") > 0.9);
}
#[test]
fn word_level_diff_014_match_pairs_best_related_lines() {
    let lines = [
        "fn alpha()",
        "return beta",
        "fn alpha_new()",
        "return gamma",
    ];
    let matches = match_delete_add_pairs(&[0, 1], &[2, 3], |i| Some(lines[i].to_owned()));
    assert!(matches.iter().any(|m| m.old_index == 0 && m.new_index == 2));
}
#[test]
fn word_level_diff_015_pairing_falls_back_for_large_blocks() {
    let deletes: Vec<usize> = (0..MAX_LINE_PAIR_CANDIDATES).collect();
    let adds: Vec<usize> = (MAX_LINE_PAIR_CANDIDATES..(MAX_LINE_PAIR_CANDIDATES * 2)).collect();
    let matches = match_delete_add_pairs(&deletes, &adds, |i| Some(format!("line {i}")));
    assert_eq!(
        matches.first().map(|m| (m.old_index, m.new_index)),
        Some((0, MAX_LINE_PAIR_CANDIDATES))
    );
}
#[test]
fn word_level_diff_016_segment_struct_is_public_and_cloneable() {
    let segment = DiffTextSegment::new("x", true);
    assert_eq!(
        segment.clone(),
        DiffTextSegment {
            text: "x".to_owned(),
            changed: true
        }
    );
}
#[test]
fn word_level_diff_017_constants_are_reasonable_for_gui() {
    assert!(MAX_WORD_DIFF_TOKENS >= 256);
    assert!(MAX_WORD_DIFF_LINE_CHARS >= 1024);
}

#[test]
fn word_level_diff_018_app_has_word_diff_enabled_config() {
    assert_app_contains(r#"word_diff_enabled: bool"#);
}

#[test]
fn word_level_diff_019_app_has_smart_pairing_config() {
    assert_app_contains(r#"word_diff_smart_pairing: bool"#);
}

#[test]
fn word_level_diff_020_toolbar_has_inline_diff_toggle() {
    assert_app_contains(r#"行内差分"#);
}

#[test]
fn word_level_diff_021_toolbar_has_smart_pairing_toggle() {
    assert_app_contains(r#"賢く対応付け"#);
}

#[test]
fn word_level_diff_022_app_has_word_pair_cache() {
    assert_app_contains(r#"DiffWordPairCache"#);
}

#[test]
fn word_level_diff_023_app_has_word_segment_cache() {
    assert_app_contains(r#"DiffWordSegmentCache"#);
}

#[test]
fn word_level_diff_024_app_has_word_segment_key() {
    assert_app_contains(r#"DiffWordSegmentKey"#);
}

#[test]
fn word_level_diff_025_app_has_pair_map_function() {
    assert_app_contains(r#"fn diff_word_pair_map"#);
}

#[test]
fn word_level_diff_026_app_has_matched_rows_function() {
    assert_app_contains(r#"fn matched_delete_add_rows"#);
}

#[test]
fn word_level_diff_027_app_uses_match_delete_add_pairs() {
    assert_app_contains(r#"match_delete_add_pairs"#);
}

#[test]
fn word_level_diff_028_app_has_word_segments_for_line() {
    assert_app_contains(r#"fn word_segments_for_line"#);
}

#[test]
fn word_level_diff_029_app_uses_word_level_segments() {
    assert_app_contains(r#"word_level_segments"#);
}

#[test]
fn word_level_diff_030_app_has_layout_job_renderer() {
    assert_app_contains(r#"fn build_diff_layout_job"#);
}

#[test]
fn word_level_diff_031_app_uses_egui_layout_job() {
    assert_app_contains(r#"egui::text::LayoutJob"#);
}

#[test]
fn word_level_diff_032_app_has_word_background() {
    assert_app_contains(r#"fn word_diff_background"#);
}

#[test]
fn word_level_diff_033_app_uses_label_sense_click() {
    assert_app_contains(r#"Sense::click"#);
}

#[test]
fn word_level_diff_034_app_has_plain_fallback_renderer() {
    assert_app_contains(r#"fn render_plain_diff_line"#);
}

#[test]
fn word_level_diff_035_app_has_prefix_helper() {
    assert_app_contains(r#"fn diff_line_prefix_text"#);
}

#[test]
fn word_level_diff_036_app_clears_segment_cache_on_toggle() {
    assert_app_contains(r#"self.diff_word_segment_cache = None"#);
}

#[test]
fn word_level_diff_037_app_clears_pair_cache_on_smart_toggle() {
    assert_app_contains(r#"self.diff_word_pair_cache = None"#);
}

#[test]
fn word_level_diff_038_app_low_memory_disables_word_diff() {
    assert_app_contains(r#"config.word_diff_enabled = false"#);
}

#[test]
fn word_level_diff_039_app_syncs_word_diff_enabled() {
    assert_app_contains(r#"self.config.word_diff_enabled = self.word_diff_enabled"#);
}

#[test]
fn word_level_diff_040_app_syncs_smart_pairing() {
    assert_app_contains(r#"self.config.word_diff_smart_pairing = self.word_diff_smart_pairing"#);
}

#[test]
fn word_level_diff_041_app_side_cache_keys_smart_pairing() {
    assert_app_contains(r#"cache.smart_pairing == self.word_diff_smart_pairing"#);
}

#[test]
fn word_level_diff_042_app_pair_cache_keys_smart_pairing() {
    assert_app_contains(r#"smart_pairing: self.word_diff_smart_pairing"#);
}

#[test]
fn word_level_diff_043_app_word_cache_uses_sentinel() {
    assert_app_contains(r#"WORD_DIFF_UNPAIRED_SENTINEL"#);
}

#[test]
fn word_level_diff_044_app_word_diff_limit_checked() {
    assert_app_contains(r#"MAX_WORD_DIFF_LINE_CHARS"#);
}

#[test]
fn word_level_diff_045_app_word_diff_marks_unpaired() {
    assert_app_contains(r#"DiffTextSegment::new(line.text.clone(), true)"#);
}

#[test]
fn word_level_diff_046_app_word_diff_keeps_context_plain() {
    assert_app_contains(r#"matches!(line.kind.as_str(), "add" | "delete")"#);
}

#[test]
fn word_level_diff_047_app_help_mentions_line_diff() {
    assert_app_contains(r#"行内差分は単語/記号単位"#);
}

#[test]
fn word_level_diff_048_app_gui_markers_include_word_diff() {
    assert_app_contains(r#"word_diff_background"#);
}

#[test]
fn word_level_diff_049_diff_words_has_tokenizer() {
    assert_diff_words_contains(r#"pub fn tokenize_for_word_diff"#);
}

#[test]
fn word_level_diff_050_diff_words_has_word_segments() {
    assert_diff_words_contains(r#"pub fn word_level_segments"#);
}

#[test]
fn word_level_diff_051_diff_words_has_similarity() {
    assert_diff_words_contains(r#"pub fn line_similarity"#);
}

#[test]
fn word_level_diff_052_diff_words_has_pairing() {
    assert_diff_words_contains(r#"pub fn match_delete_add_pairs"#);
}

#[test]
fn word_level_diff_053_diff_words_has_threshold() {
    assert_diff_words_contains(r#"LINE_PAIR_SIMILARITY_THRESHOLD"#);
}

#[test]
fn word_level_diff_054_diff_words_has_token_limit() {
    assert_diff_words_contains(r#"MAX_WORD_DIFF_TOKENS"#);
}

#[test]
fn word_level_diff_055_diff_words_has_cell_limit() {
    assert_diff_words_contains(r#"MAX_LINE_PAIR_CANDIDATES"#);
}

#[test]
fn word_level_diff_056_diff_words_uses_lcs_flags() {
    assert_diff_words_contains(r#"lcs_unchanged_flags"#);
}

#[test]
fn word_level_diff_057_diff_words_uses_lcs_len() {
    assert_diff_words_contains(r#"lcs_len"#);
}

#[test]
fn word_level_diff_058_diff_words_splits_case() {
    assert_diff_words_contains(r#"should_split_word"#);
}

#[test]
fn word_level_diff_059_diff_words_uses_jaccard_fallback() {
    assert_diff_words_contains(r#"old_set.intersection"#);
}

#[test]
fn word_level_diff_060_diff_words_greedy_candidates() {
    assert_diff_words_contains(r#"candidates.sort_by"#);
}

#[test]
fn word_level_diff_061_diff_words_avoids_duplicate_pairs() {
    assert_diff_words_contains(r#"used_old.contains"#);
}

#[test]
fn word_level_diff_062_diff_words_has_module_tests() {
    assert_diff_words_contains(r#"word_level_segments_highlight_only_changed_tokens"#);
}
