mod support;

use diffgr_gui::ops::{self, RebaseOptions};
use serde_json::{json, Value};
use std::fs;

#[test]
fn more_ops_sha256_ignores_object_key_order_but_not_array_order() {
    let a = json!({"b": 2, "a": [1, 2]});
    let b = json!({"a": [1, 2], "b": 2});
    let c = json!({"a": [2, 1], "b": 2});
    assert_eq!(ops::sha256_hex_value(&a), ops::sha256_hex_value(&b));
    assert_ne!(ops::sha256_hex_value(&a), ops::sha256_hex_value(&c));
}

#[test]
fn more_ops_write_text_file_replaces_existing_file_atomically_enough_for_reader() {
    let root = support::temp_dir("more_ops_write_text");
    let path = root.join("nested").join("report.md");
    ops::write_text_file(&path, "old").unwrap();
    ops::write_text_file(&path, "new").unwrap();
    assert_eq!(fs::read_to_string(&path).unwrap(), "new");
    let leftovers = fs::read_dir(path.parent().unwrap())
        .unwrap()
        .filter_map(Result::ok)
        .filter(|e| e.file_name().to_string_lossy().contains(".tmp"))
        .count();
    assert_eq!(leftovers, 0);
    fs::remove_dir_all(root).ok();
}

#[test]
fn more_ops_read_json_missing_file_reports_path() {
    let root = support::temp_dir("more_ops_missing_json");
    let err = ops::read_json_file(&root.join("missing.json")).unwrap_err();
    assert!(err.contains("missing.json"));
    fs::remove_dir_all(root).ok();
}

#[test]
fn more_ops_build_diffgr_empty_diff_creates_empty_all_group() {
    let doc = ops::build_diffgr_from_diff_text("", "Empty", "main", "head", "b", "h", "m", false)
        .unwrap();
    assert_eq!(doc["chunks"].as_array().unwrap().len(), 0);
    assert_eq!(doc["groups"][0]["id"], json!("g-all"));
    assert!(doc.get("patch").is_none());
}

#[test]
fn more_ops_build_diffgr_include_patch_preserves_original_diff_text() {
    let diff = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n";
    let doc = ops::build_diffgr_from_diff_text(diff, "Patch", "main", "head", "b", "h", "m", true)
        .unwrap();
    assert_eq!(doc["patch"], json!(diff));
}

#[test]
fn more_ops_build_diffgr_hunk_without_count_defaults_to_one() {
    let diff =
        "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -7 +9 @@ label\n-old\n+new\n";
    let doc =
        ops::build_diffgr_from_diff_text(diff, "Ranges", "main", "head", "b", "h", "m", false)
            .unwrap();
    assert_eq!(doc["chunks"][0]["old"], json!({"start": 7, "count": 1}));
    assert_eq!(doc["chunks"][0]["new"], json!({"start": 9, "count": 1}));
    assert_eq!(doc["chunks"][0]["header"], json!("label"));
}

#[test]
fn more_ops_build_diffgr_binary_meta_only_change_creates_meta_chunk() {
    let diff = "diff --git a/logo.png b/logo.png\nnew file mode 100644\nindex 000..111\nBinary files /dev/null and b/logo.png differ\n";
    let doc =
        ops::build_diffgr_from_diff_text(diff, "Binary", "main", "head", "b", "h", "m", false)
            .unwrap();
    assert_eq!(doc["chunks"].as_array().unwrap().len(), 1);
    assert_eq!(doc["chunks"][0]["filePath"], json!("logo.png"));
    assert!(doc["chunks"][0]["meta"].is_object());
}

#[test]
fn more_ops_split_chunk_by_change_blocks_keeps_meta_only_as_single_piece() {
    let chunk = json!({"id": "meta", "filePath": "a", "old": {"start": 0, "count": 0}, "new": {"start": 0, "count": 0}, "lines": [], "meta": {"diffHeaderLines": ["Binary files differ"]}});
    let pieces = ops::split_chunk_by_change_blocks(&chunk, 1);
    assert_eq!(pieces.len(), 1);
    assert_eq!(pieces[0]["id"], json!("meta"));
}

#[test]
fn more_ops_split_chunk_by_change_blocks_splits_distant_changes() {
    let chunk = json!({
        "id": "c", "filePath": "a.rs", "old": {"start": 1, "count": 8}, "new": {"start": 1, "count": 8},
        "lines": [
            {"kind": "context", "text": "a", "oldLine": 1, "newLine": 1},
            {"kind": "add", "text": "b", "oldLine": null, "newLine": 2},
            {"kind": "context", "text": "c", "oldLine": 2, "newLine": 3},
            {"kind": "context", "text": "d", "oldLine": 3, "newLine": 4},
            {"kind": "context", "text": "e", "oldLine": 4, "newLine": 5},
            {"kind": "delete", "text": "f", "oldLine": 5, "newLine": null},
            {"kind": "add", "text": "g", "oldLine": null, "newLine": 6}
        ]
    });
    let pieces = ops::split_chunk_by_change_blocks(&chunk, 1);
    assert!(pieces.len() >= 2);
}

#[test]
fn more_ops_change_fingerprint_ignores_line_numbers() {
    let left = json!({"filePath": "a.rs", "lines": [{"kind": "add", "text": "same", "oldLine": null, "newLine": 10}]});
    let right = json!({"filePath": "a.rs", "lines": [{"kind": "add", "text": "same", "oldLine": null, "newLine": 99}]});
    assert_eq!(
        ops::change_fingerprint_for_chunk(&left),
        ops::change_fingerprint_for_chunk(&right)
    );
}

#[test]
fn more_ops_apply_slice_patch_empty_patch_is_metadata_only() {
    let out = ops::apply_slice_patch(&support::rich_doc(), &json!({})).unwrap();
    assert_eq!(out["meta"]["x-slicePatch"]["renameCount"], json!(0));
    assert_eq!(out["meta"]["x-slicePatch"]["moveCount"], json!(0));
}

#[test]
fn more_ops_apply_slice_patch_renames_and_prunes_now_empty_groups() {
    let out = ops::apply_slice_patch(
        &support::rich_doc(),
        &json!({
            "rename": {"g-ui": "UI renamed"},
            "move": [{"chunk": "c-ui-login", "to": "g-api"}]
        }),
    )
    .unwrap();
    assert!(out["groups"]
        .as_array()
        .unwrap()
        .iter()
        .all(|g| g["id"] != json!("g-empty")));
    assert!(
        out["groups"]
            .as_array()
            .unwrap()
            .iter()
            .any(|g| g["name"] == json!("UI renamed"))
            || out["groups"]
                .as_array()
                .unwrap()
                .iter()
                .all(|g| g["id"] != json!("g-ui"))
    );
    assert!(out["assignments"]["g-api"]
        .as_array()
        .unwrap()
        .iter()
        .any(|id| id == "c-ui-login"));
}

#[test]
fn more_ops_apply_slice_patch_rejects_unknown_move_group() {
    let err = ops::apply_slice_patch(
        &support::rich_doc(),
        &json!({"move": [{"chunk": "c-docs", "to": "missing"}]}),
    )
    .unwrap_err();
    assert!(err.contains("Unknown group id"));
}

#[test]
fn more_ops_apply_slice_patch_rejects_unknown_move_chunk() {
    let err = ops::apply_slice_patch(
        &support::rich_doc(),
        &json!({"move": [{"chunk": "missing", "to": "g-ui"}]}),
    )
    .unwrap_err();
    assert!(err.contains("Unknown chunk id"));
}

#[test]
fn more_ops_refine_group_names_adds_slice_refine_metadata() {
    let refined = ops::refine_group_names_ja(&support::rich_doc());
    assert!(refined["meta"]["x-sliceRefine"].is_object());
    assert_eq!(refined["meta"]["x-sliceRefine"]["lang"], json!("ja"));
}

#[test]
fn more_ops_ai_refine_prompt_respects_max_chunks_per_group_marker() {
    let prompt = ops::build_ai_refine_prompt_markdown(&support::rich_doc(), 1);
    assert!(prompt.contains("DiffGR 仮想PR分割"));
    assert!(prompt.contains("... (1 more)") || prompt.contains("c-api-route"));
}

#[test]
fn more_ops_extract_review_state_omits_layout_sections() {
    let state = ops::extract_review_state(&support::rich_doc());
    assert!(state["reviews"].is_object());
    assert!(state.get("groups").is_none());
    assert!(state.get("chunks").is_none());
}

#[test]
fn more_ops_apply_review_state_accepts_wrapped_state() {
    let out = ops::apply_review_state(
        &support::rich_doc(),
        &json!({"state": support::minimal_state()}),
    )
    .unwrap();
    assert_eq!(out["reviews"]["c-docs"]["status"], json!("ignored"));
}

#[test]
fn more_ops_merge_review_states_later_inputs_win_for_comments() {
    let base = json!({"reviews": {"c": {"status": "reviewed", "comment": "base"}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let one = json!({"reviews": {"c": {"status": "reviewed", "comment": "one"}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let two = json!({"reviews": {"c": {"status": "reviewed", "comment": "two"}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let (merged, _, applied) =
        ops::merge_review_states(&base, &[("one".to_owned(), one), ("two".to_owned(), two)])
            .unwrap();
    assert_eq!(applied, 2);
    assert_eq!(merged["reviews"]["c"]["comment"], json!("two"));
}

#[test]
fn more_ops_diff_review_states_no_changes_has_zero_counts() {
    let state = support::minimal_state();
    let diff = ops::diff_review_states(&state, &state).unwrap();
    for section in ["reviews", "groupBriefs", "analysisState", "threadState"] {
        assert_eq!(diff[section]["addedCount"], json!(0));
        assert_eq!(diff[section]["removedCount"], json!(0));
        assert_eq!(diff[section]["changedCount"], json!(0));
    }
}

#[test]
fn more_ops_apply_review_state_selection_rejects_bad_token_shape() {
    let err = ops::apply_review_state_selection(
        &support::minimal_state(),
        &support::minimal_state(),
        &["bad-token".to_owned()],
    )
    .unwrap_err();
    assert!(err.contains("Invalid selection token"));
}

#[test]
fn more_ops_apply_review_state_selection_rejects_unknown_section() {
    let err = ops::apply_review_state_selection(
        &support::minimal_state(),
        &support::minimal_state(),
        &["unknown:key".to_owned()],
    )
    .unwrap_err();
    assert!(err.contains("Unknown selection section"));
}

#[test]
fn more_ops_apply_review_state_selection_can_remove_missing_other_value() {
    let base = json!({"reviews": {"c": {"status": "reviewed"}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let other = json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let (out, applied) =
        ops::apply_review_state_selection(&base, &other, &["reviews:c".to_owned()]).unwrap();
    assert_eq!(applied, 1);
    assert!(out["reviews"].get("c").is_none());
}

#[test]
fn more_ops_preview_review_state_selection_reports_changed_tokens() {
    let base = json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let other = support::minimal_state();
    let preview =
        ops::preview_review_state_selection(&base, &other, &["reviews:c-ui-login".to_owned()])
            .unwrap();
    assert_eq!(preview["appliedCount"], json!(1));
    assert!(preview["changedTokens"]
        .as_array()
        .unwrap()
        .iter()
        .any(|v| v == "reviews:c-ui-login"));
}

#[test]
fn more_ops_split_document_by_group_manifest_names_are_filesafe() {
    let root = support::temp_dir("more_ops_split_safe");
    let mut raw = support::rich_doc();
    raw["groups"][0]["name"] = json!("UI / login & spinner");
    let summary = ops::split_document_by_group(&raw, &root, false).unwrap();
    assert!(summary.written.iter().any(|path| path
        .file_name()
        .unwrap()
        .to_string_lossy()
        .contains("UI-login-spinner")));
    fs::remove_dir_all(root).ok();
}

#[test]
fn more_ops_merge_group_review_documents_filters_unknown_analysis_selection() {
    let mut review = support::rich_doc();
    review["analysisState"] = json!({"selectedChunkId": "missing", "currentGroupId": "missing"});
    let (merged, _, _) = ops::merge_group_review_documents(
        &support::rich_doc(),
        &[("review".to_owned(), review)],
        true,
        false,
    )
    .unwrap();
    assert!(
        merged["analysisState"].get("selectedChunkId").is_none()
            || merged["analysisState"]["selectedChunkId"] != json!("missing")
    );
}

#[test]
fn more_ops_summarize_state_fingerprint_is_stable_for_key_order() {
    let one =
        json!({"reviews": {"a": {}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let two =
        json!({"threadState": {}, "analysisState": {}, "groupBriefs": {}, "reviews": {"a": {}}});
    assert_eq!(
        ops::summarize_state(&one).unwrap()["fingerprint"],
        ops::summarize_state(&two).unwrap()["fingerprint"]
    );
}

#[test]
fn more_ops_reviewability_report_returns_one_row_per_group() {
    let report = ops::reviewability_report(&support::rich_doc()).unwrap();
    assert_eq!(report["groups"].as_array().unwrap().len(), 3);
    assert!(report["groups"]
        .as_array()
        .unwrap()
        .iter()
        .any(|row| row["groupId"] == json!("g-ui")));
}

#[test]
fn more_ops_coverage_report_detects_duplicate_assignments() {
    let mut raw = support::rich_doc();
    raw["assignments"]["g-ui"] = json!(["c-ui-login", "c-docs"]);
    let report = ops::coverage_report(&raw).unwrap();
    assert_eq!(report["ok"], json!(false));
    assert!(report["duplicated"]
        .as_array()
        .unwrap()
        .iter()
        .any(|row| row["chunkId"] == json!("c-docs")));
}

#[test]
fn more_ops_build_html_report_rejects_impact_state_without_old_doc() {
    let err = ops::build_html_report_with_options(
        &support::rich_doc(),
        None,
        None,
        Some(&support::minimal_state()),
        None,
        None,
        None,
        None,
    )
    .unwrap_err();
    assert!(err.contains("impact-state"));
}

#[test]
fn more_ops_build_html_report_group_selector_all_keeps_all_chunks() {
    let html = ops::build_html_report_with_options(
        &support::rich_doc(),
        None,
        None,
        None,
        Some("all"),
        None,
        None,
        None,
    )
    .unwrap();
    assert!(html.contains("c-ui-login"));
    assert!(html.contains("c-api-route"));
}

#[test]
fn more_ops_export_review_bundle_to_paths_writes_three_artifacts() {
    let root = support::temp_dir("more_ops_bundle_paths");
    let bundle = root.join("bundle.diffgr.json");
    let state = root.join("review.state.json");
    let manifest = root.join("review.manifest.json");
    let summary =
        ops::export_review_bundle_to_paths(&support::rich_doc(), &bundle, &state, &manifest)
            .unwrap();
    assert_eq!(summary.written.len(), 3);
    assert!(bundle.exists() && state.exists() && manifest.exists());
    fs::remove_dir_all(root).ok();
}

#[test]
fn more_ops_verify_review_bundle_expected_head_mismatch_is_error() {
    let state = ops::extract_review_state(&support::rich_doc());
    let manifest = ops::build_review_bundle_manifest(&support::rich_doc(), &state);
    let report = ops::verify_review_bundle(
        &support::rich_doc(),
        &state,
        &manifest,
        Some("not-head-sha"),
        false,
    )
    .unwrap();
    assert!(!report.ok);
    assert!(report.errors.iter().any(|e| e.contains("head")));
}

#[test]
fn more_ops_rebase_summary_json_exposes_new_fields() {
    let (_, summary) = ops::rebase_state_with_options(
        &support::rebase_old_doc(),
        &support::rebase_new_doc(),
        &ops::extract_review_state(&support::rebase_old_doc()),
        &RebaseOptions::default(),
    )
    .unwrap();
    let json = ops::rebase_summary_json(&summary);
    assert!(json.get("matchedStrong").is_some());
    assert!(json.get("matchedStable").is_some());
    assert!(json.get("changedToNeedsReReview").is_some());
}

#[test]
fn more_ops_rebase_no_line_comments_drops_carried_line_comments() {
    let options = RebaseOptions {
        carry_line_comments: false,
        ..RebaseOptions::default()
    };
    let (rebased, _) = ops::rebase_state_with_options(
        &support::rebase_old_doc(),
        &support::rebase_new_doc(),
        &ops::extract_review_state(&support::rebase_old_doc()),
        &options,
    )
    .unwrap();
    let has_line_comments = rebased["reviews"]
        .as_object()
        .unwrap()
        .values()
        .any(|record| record.get("lineComments").is_some());
    assert!(!has_line_comments);
}

#[test]
fn more_ops_rebase_reviews_keep_new_groups_option_preserves_new_group_layout() {
    let options = RebaseOptions {
        preserve_groups: false,
        ..RebaseOptions::default()
    };
    let (rebased, _) = ops::rebase_reviews_document_with_options(
        &support::rebase_old_doc(),
        &support::rebase_new_doc(),
        &options,
    )
    .unwrap();
    assert!(rebased["groups"]
        .as_array()
        .unwrap()
        .iter()
        .any(|g| g["id"] == json!("g-new")));
}

#[test]
fn more_ops_approval_report_before_approval_is_not_all_approved() {
    let report = ops::approval_report(&support::rich_doc()).unwrap();
    assert_eq!(report["allApproved"], json!(false));
}

#[test]
fn more_ops_request_changes_all_groups_records_comment() {
    let out = ops::request_changes(&support::rich_doc(), &[], "reviewer", "please adjust").unwrap();
    for group in ["g-ui", "g-api", "g-empty"] {
        assert_eq!(
            out["groupBriefs"][group]["approval"]["state"],
            json!("changesRequested")
        );
        assert_eq!(
            out["groupBriefs"][group]["approval"]["comment"],
            json!("please adjust")
        );
    }
}

#[test]
fn more_ops_approve_groups_empty_target_means_all_groups_with_force() {
    let out = ops::approve_groups(&support::rich_doc(), &[], "reviewer", true).unwrap();
    for group in ["g-ui", "g-api", "g-empty"] {
        assert_eq!(
            out["groupBriefs"][group]["approval"]["state"],
            json!("approved")
        );
    }
}

#[test]
fn more_ops_impact_report_with_options_records_grouping_and_match_options() {
    let report = ops::impact_report_with_options(
        &support::rebase_old_doc(),
        &support::rebase_new_doc(),
        None,
        "new",
        0.42,
        7,
    )
    .unwrap();
    assert_eq!(report["grouping"], json!("new"));
    assert_eq!(report["match"]["similarityThreshold"], json!(0.42));
    assert_eq!(report["match"]["maxItemsPerGroup"], json!(7));
}

#[test]
fn more_ops_format_impact_report_markdown_limits_group_rows() {
    let report =
        ops::impact_report(&support::rebase_old_doc(), &support::rebase_new_doc(), None).unwrap();
    let markdown = ops::format_impact_report_markdown(&report, 1);
    assert!(markdown.contains("DiffGR Impact Report"));
    assert!(markdown.contains("old chunks"));
}

#[test]
fn more_ops_apply_layout_rejects_duplicate_group_ids() {
    let err = ops::apply_layout(
        &support::rich_doc(),
        &json!({"groups": [{"id": "g", "name": "One"}, {"id": "g", "name": "Two"}]}),
    )
    .unwrap_err();
    assert!(err.contains("Duplicate group id"));
}

#[test]
fn more_ops_apply_layout_warns_for_unknown_group_and_unassigned_chunks() {
    let (_out, warnings) = ops::apply_layout(
        &support::rich_doc(),
        &json!({"assignments": {"missing": ["c-docs"], "g-ui": ["c-ui-login"]}}),
    )
    .unwrap();
    assert!(warnings.iter().any(|w| w.contains("unknown group")));
    assert!(warnings.iter().any(|w| w.contains("not assigned")));
}

#[test]
fn more_ops_apply_layout_merges_group_briefs_without_dropping_existing_fields() {
    let (out, _) = ops::apply_layout(
        &support::rich_doc(),
        &json!({"groupBriefs": {"g-ui": {"testEvidence": ["cargo test"]}}}),
    )
    .unwrap();
    assert_eq!(
        out["groupBriefs"]["g-ui"]["summary"],
        json!("Login spinner UI")
    );
    assert_eq!(
        out["groupBriefs"]["g-ui"]["testEvidence"],
        json!(["cargo test"])
    );
}
