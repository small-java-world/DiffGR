mod support;

use diffgr_gui::ops::{self, AutosliceOptions, GenerateOptions, RebaseOptions, RebaseSummary};
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;

#[test]
fn ops_build_diffgr_empty_diff_produces_valid_empty_document() {
    let doc = ops::build_diffgr_from_diff_text("", "Empty", "main", "head", "b", "h", "m", false)
        .unwrap();
    assert_eq!(doc["format"], json!("diffgr"));
    assert_eq!(doc["chunks"].as_array().unwrap().len(), 0);
    assert_eq!(doc["assignments"]["g-all"].as_array().unwrap().len(), 0);
}

#[test]
fn ops_build_diffgr_ignores_preamble_before_first_diff() {
    let diff = "noise before diff\ndiff --git a/a.rs b/a.rs\n--- a/a.rs\n+++ b/a.rs\n@@ -3 +4 @@ fn a\n-old\n+new\n";
    let doc =
        ops::build_diffgr_from_diff_text(diff, "Preamble", "main", "head", "b", "h", "m", false)
            .unwrap();
    let chunk = &doc["chunks"][0];
    assert_eq!(chunk["old"]["start"], json!(3));
    assert_eq!(chunk["old"]["count"], json!(1));
    assert_eq!(chunk["new"]["start"], json!(4));
    assert_eq!(chunk["new"]["count"], json!(1));
}

#[test]
fn ops_build_diffgr_rejects_unsupported_hunk_header() {
    let diff = "diff --git a/a.rs b/a.rs\n--- a/a.rs\n+++ b/a.rs\n@@ bad header @@\n-old\n+new\n";
    let err = ops::build_diffgr_from_diff_text(diff, "Bad", "main", "head", "b", "h", "m", false)
        .unwrap_err();
    assert!(err.contains("Unsupported hunk header"));
}

#[test]
fn ops_build_diffgr_records_no_newline_marker_as_meta_line() {
    let diff = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1,1 +1,1 @@\n-old\n\\ No newline at end of file\n+new\n";
    let doc =
        ops::build_diffgr_from_diff_text(diff, "Marker", "main", "head", "b", "h", "m", false)
            .unwrap();
    let lines = doc["chunks"][0]["lines"].as_array().unwrap();
    assert!(lines
        .iter()
        .any(|line| line["kind"] == json!("meta")
            && line["text"] == json!("No newline at end of file")));
}

#[test]
fn ops_build_diffgr_handles_quoted_paths_with_backslash_escapes() {
    let diff = "diff --git \"a/dir\\ name/a.txt\" \"b/dir\\ name/a.txt\"\n--- \"a/dir\\ name/a.txt\"\n+++ \"b/dir\\ name/a.txt\"\n@@ -1,1 +1,1 @@\n-old\n+new\n";
    let doc =
        ops::build_diffgr_from_diff_text(diff, "Quoted", "main", "head", "b", "h", "m", false)
            .unwrap();
    assert_eq!(doc["chunks"][0]["filePath"], json!("dir name/a.txt"));
}

#[test]
fn ops_canonical_json_sorted_preserves_array_order_but_sorts_object_keys() {
    let left = json!({"z": 0, "a": [2, 1], "m": {"b": true, "a": false}});
    let rendered = ops::canonical_json_sorted(&left);
    assert!(rendered.starts_with("{\"a\":[2,1],\"m\":{"));
    assert!(rendered.contains("\"a\":false,\"b\":true"));
}

#[test]
fn ops_read_json_file_reports_invalid_json_with_path() {
    let root = support::temp_dir("ops_bad_json");
    let path = root.join("bad.json");
    fs::write(&path, "{bad").unwrap();
    let err = ops::read_json_file(&path).unwrap_err();
    assert!(err.contains("bad.json"));
    assert!(err.contains("invalid JSON"));
    fs::remove_dir_all(root).ok();
}

#[test]
fn ops_write_and_read_json_file_roundtrip() {
    let root = support::temp_dir("ops_json_roundtrip");
    let path = root.join("nested").join("value.json");
    ops::write_json_file(&path, &json!({"b": 2, "a": 1})).unwrap();
    let loaded = ops::read_json_file(&path).unwrap();
    assert_eq!(loaded["a"], json!(1));
    assert_eq!(loaded["b"], json!(2));
    fs::remove_dir_all(root).ok();
}

#[test]
fn ops_apply_review_state_rejects_bad_state_shape() {
    let err = ops::apply_review_state(&support::rich_doc(), &json!({"reviews": []})).unwrap_err();
    assert!(err.contains("reviews"));
}

#[test]
fn ops_merge_review_states_warns_and_keeps_base_for_non_object_review_record() {
    let base = json!({
        "reviews": {"c1": {"status": "reviewed", "comment": "base"}},
        "groupBriefs": {},
        "analysisState": {},
        "threadState": {}
    });
    let incoming =
        json!({"reviews": {"c1": true}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let (merged, warnings, applied) =
        ops::merge_review_states(&base, &[("bad.state".to_owned(), incoming)]).unwrap();
    assert_eq!(applied, 1);
    assert_eq!(merged["reviews"]["c1"]["comment"], json!("base"));
    assert!(warnings.iter().any(|w| w.contains("must be object")));
}

#[test]
fn ops_merge_review_states_merges_thread_files_per_file() {
    let base = json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {"__files": {"a.rs": {"expanded": true}}}});
    let incoming = json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {"__files": {"b.rs": {"expanded": false}}}});
    let (merged, _, applied) =
        ops::merge_review_states(&base, &[("incoming".to_owned(), incoming)]).unwrap();
    assert_eq!(applied, 1);
    assert_eq!(
        merged["threadState"]["__files"]["a.rs"]["expanded"],
        json!(true)
    );
    assert_eq!(
        merged["threadState"]["__files"]["b.rs"]["expanded"],
        json!(false)
    );
}

#[test]
fn ops_diff_review_states_counts_unchanged_added_removed_changed_details() {
    let base = json!({
        "reviews": {"same": {"status": "reviewed"}, "removed": {"status": "ignored"}, "changed": {"status": "reviewed"}},
        "groupBriefs": {},
        "analysisState": {},
        "threadState": {}
    });
    let incoming = json!({
        "reviews": {"same": {"status": "reviewed"}, "added": {"status": "reviewed"}, "changed": {"status": "needsReReview"}},
        "groupBriefs": {},
        "analysisState": {},
        "threadState": {}
    });
    let diff = ops::diff_review_states(&base, &incoming).unwrap();
    assert_eq!(diff["reviews"]["unchangedCount"], json!(1));
    assert_eq!(diff["reviews"]["addedCount"], json!(1));
    assert_eq!(diff["reviews"]["removedCount"], json!(1));
    assert_eq!(diff["reviews"]["changedCount"], json!(1));
    assert!(
        diff["reviews"]["changedDetails"].as_array().unwrap()[0]["selectionToken"]
            .as_str()
            .unwrap()
            .starts_with("reviews:")
    );
}

#[test]
fn ops_selection_tokens_from_diff_include_added_removed_and_changed() {
    let base = json!({"reviews": {"removed": {}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let incoming = json!({"reviews": {"added": {}}, "groupBriefs": {}, "analysisState": {"filterText": "src"}, "threadState": {}});
    let diff = ops::diff_review_states(&base, &incoming).unwrap();
    let tokens = ops::selection_tokens_from_diff(&diff);
    assert!(tokens.contains(&"reviews:removed".to_owned()));
    assert!(tokens.contains(&"reviews:added".to_owned()));
    assert!(tokens.contains(&"analysisState:filterText".to_owned()));
}

#[test]
fn ops_preview_review_state_selection_with_empty_tokens_is_noop() {
    let state = json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let preview = ops::preview_review_state_selection(&state, &state, &[]).unwrap();
    assert_eq!(preview["appliedCount"], json!(0));
    assert!(preview["changedTokens"].as_array().unwrap().is_empty());
}

#[test]
fn ops_split_document_by_group_skips_empty_groups_by_default() {
    let root = support::temp_dir("ops_split_default");
    let summary = ops::split_document_by_group(&support::rich_doc(), &root, false).unwrap();
    let names = summary
        .written
        .iter()
        .map(|p| p.file_name().unwrap().to_string_lossy().to_string())
        .collect::<Vec<_>>();
    assert!(names.iter().any(|name| name.contains("g-ui")));
    assert!(names.iter().any(|name| name.contains("g-api")));
    assert!(!names.iter().any(|name| name.contains("g-empty")));
    assert!(root.join("manifest.json").exists());
    fs::remove_dir_all(root).ok();
}

#[test]
fn ops_split_document_by_group_can_include_empty_groups() {
    let root = support::temp_dir("ops_split_empty");
    let summary = ops::split_document_by_group(&support::rich_doc(), &root, true).unwrap();
    let names = summary
        .written
        .iter()
        .map(|p| p.file_name().unwrap().to_string_lossy().to_string())
        .collect::<Vec<_>>();
    assert!(names.iter().any(|name| name.contains("g-empty")));
    fs::remove_dir_all(root).ok();
}

#[test]
fn ops_merge_group_review_documents_warns_for_unknowns_when_not_strict() {
    let mut review = support::rich_doc();
    review["reviews"]["missing"] = json!({"status": "reviewed"});
    review["groupBriefs"]["missing-group"] = json!({"summary": "bad"});
    let (merged, warnings, applied) = ops::merge_group_review_documents(
        &support::rich_doc(),
        &[("review".to_owned(), review)],
        true,
        false,
    )
    .unwrap();
    assert!(applied > 0);
    assert!(warnings.iter().any(|w| w.contains("unknown chunk")));
    assert!(warnings.iter().any(|w| w.contains("unknown group")));
    assert!(merged["reviews"].get("missing").is_none());
}

#[test]
fn ops_merge_group_review_documents_errors_for_unknowns_when_strict() {
    let mut review = support::rich_doc();
    review["reviews"] = json!({"missing": {"status": "reviewed"}});
    let err = ops::merge_group_review_documents(
        &support::rich_doc(),
        &[("review".to_owned(), review)],
        false,
        true,
    )
    .unwrap_err();
    assert!(err.contains("unknown chunk"));
}

#[test]
fn ops_summarize_document_returns_error_payload_for_invalid_doc() {
    let summary = ops::summarize_document(&json!({"format": "wrong"}));
    assert_eq!(summary["ok"], json!(false));
}

#[test]
fn ops_reviewability_report_marks_large_group_hotspot() {
    let mut raw = support::rich_doc();
    let mut lines = Vec::new();
    for idx in 0..81 {
        lines.push(json!({"kind": "add", "text": format!("line {idx}"), "oldLine": null, "newLine": idx + 1}));
    }
    raw["chunks"][0]["lines"] = Value::Array(lines);
    let report = ops::reviewability_report(&raw).unwrap();
    let ui = report["groups"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["groupId"] == json!("g-ui"))
        .unwrap();
    assert_eq!(ui["hotspots"].as_array().unwrap().len(), 1);
}

#[test]
fn ops_coverage_report_with_limits_embeds_limited_prompt() {
    let mut raw = support::rich_doc();
    raw["assignments"] = json!({"g-ui": [], "g-api": [], "g-empty": []});
    let report = ops::coverage_report_with_limits(&raw, 1, 1).unwrap();
    assert_eq!(report["ok"], json!(false));
    assert!(report["prompt"]
        .as_str()
        .unwrap()
        .contains("Unassigned chunks"));
}

#[test]
fn ops_build_html_report_applies_state_group_filter_title_and_save_widget() {
    let html = ops::build_html_report_with_options(
        &support::rich_doc(),
        Some(&support::minimal_state()),
        None,
        None,
        Some("g-ui"),
        Some("Custom & Report"),
        Some("/api/state"),
        Some("Store State"),
    )
    .unwrap();
    assert!(html.contains("Custom &amp; Report"));
    assert!(html.contains("Store State"));
    assert!(html.contains("/api/state"));
    assert!(html.contains("c-ui-login"));
    assert!(!html.contains("c-api-route"));
}

#[test]
fn ops_build_html_report_requires_impact_old_when_impact_state_is_supplied() {
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
    assert!(err.contains("impact-state requires --impact-old"));
}

#[test]
fn ops_export_review_bundle_to_paths_writes_all_requested_paths() {
    let root = support::temp_dir("ops_bundle_paths");
    let bundle = root.join("custom.bundle.json");
    let state = root.join("custom.state.json");
    let manifest = root.join("custom.manifest.json");
    let summary =
        ops::export_review_bundle_to_paths(&support::rich_doc(), &bundle, &state, &manifest)
            .unwrap();
    assert_eq!(
        summary.written,
        vec![bundle.clone(), state.clone(), manifest.clone()]
    );
    assert!(bundle.exists() && state.exists() && manifest.exists());
    fs::remove_dir_all(root).ok();
}

#[test]
fn ops_verify_review_bundle_detects_expected_head_mismatch() {
    let mut bundle = support::rich_doc();
    bundle["reviews"] = json!({});
    bundle.as_object_mut().unwrap().remove("groupBriefs");
    bundle.as_object_mut().unwrap().remove("analysisState");
    bundle.as_object_mut().unwrap().remove("threadState");
    let state = ops::extract_review_state(&support::rich_doc());
    let manifest = ops::build_review_bundle_manifest(&bundle, &state);
    let report =
        ops::verify_review_bundle(&bundle, &state, &manifest, Some("different-head"), false)
            .unwrap();
    assert!(!report.ok);
    assert!(report
        .errors
        .iter()
        .any(|err| err.contains("Expected head")));
}

#[test]
fn ops_verify_review_bundle_require_approvals_fails_when_not_all_approved() {
    let mut bundle = support::rich_doc();
    bundle["reviews"] = json!({});
    bundle.as_object_mut().unwrap().remove("groupBriefs");
    bundle.as_object_mut().unwrap().remove("analysisState");
    bundle.as_object_mut().unwrap().remove("threadState");
    let state = ops::extract_review_state(&support::rich_doc());
    let manifest = ops::build_review_bundle_manifest(&bundle, &state);
    let report = ops::verify_review_bundle(&bundle, &state, &manifest, None, true).unwrap();
    assert!(!report.ok);
    assert!(report
        .errors
        .iter()
        .any(|err| err.contains("Not all groups")));
    assert!(report.approval_report.is_some());
}

#[test]
fn ops_approval_functions_default_to_all_groups() {
    let mut raw = support::rich_doc();
    raw["reviews"] = json!({
        "c-ui-login": {"status": "reviewed"},
        "c-api-route": {"status": "reviewed"},
        "c-docs": {"status": "reviewed"}
    });
    let approved = ops::approve_groups(&raw, &[], "alice", true).unwrap();
    let report = ops::approval_report(&approved).unwrap();
    assert_eq!(report["groups"].as_array().unwrap().len(), 3);
    assert!(report["groups"]
        .as_array()
        .unwrap()
        .iter()
        .all(|row| row["approved"].as_bool().unwrap()));
}

#[test]
fn ops_request_changes_targets_selected_groups_only() {
    let changed = ops::request_changes(
        &support::rich_doc(),
        &["g-ui".to_owned()],
        "bob",
        "please fix",
    )
    .unwrap();
    assert_eq!(
        changed["groupBriefs"]["g-ui"]["approval"]["state"],
        json!("changesRequested")
    );
    assert!(changed["groupBriefs"]
        .get("g-api")
        .and_then(|v| v.get("approval"))
        .is_none());
}

#[test]
fn ops_impact_report_with_options_records_option_metadata() {
    let report = ops::impact_report_with_options(
        &support::rich_doc(),
        &support::rich_doc(),
        None,
        "group",
        0.75,
        5,
    )
    .unwrap();
    assert_eq!(report["grouping"], json!("group"));
    assert_eq!(report["match"]["similarityThreshold"], json!(0.75));
    assert_eq!(report["match"]["maxItemsPerGroup"], json!(5));
}

#[test]
fn ops_format_impact_report_markdown_limits_group_rows() {
    let mut report = ops::impact_report(&support::rich_doc(), &support::rich_doc(), None).unwrap();
    report["groups"].as_array_mut().unwrap().push(json!({"groupId": "extra", "groupName": "Extra", "action": "review", "totalNew": 1, "unchanged": 0, "newChunks": 1, "changed": 0}));
    let markdown = ops::format_impact_report_markdown(&report, 1);
    assert!(markdown.contains("# DiffGR Impact Report"));
    assert!(
        markdown.contains("### g-api")
            || markdown.contains("### g-empty")
            || markdown.contains("### g-ui")
    );
    assert!(!markdown.contains("### extra"));
}

#[test]
fn ops_rebase_summary_json_exposes_python_compatible_counters() {
    let summary = RebaseSummary {
        mapped_reviews: 2,
        unmapped_reviews: 1,
        mapped_thread_entries: 3,
        matched_strong: 4,
        matched_stable: 5,
        matched_delta: 6,
        matched_similar: 7,
        carried_reviews: 8,
        carried_reviewed: 9,
        changed_to_needs_rereview: 10,
        unmapped_new_chunks: 11,
        warnings: vec!["warn".to_owned()],
    };
    let value = ops::rebase_summary_json(&summary);
    assert_eq!(value["mappedReviews"], json!(2));
    assert_eq!(value["matchedSimilar"], json!(7));
    assert_eq!(value["changedToNeedsReReview"], json!(10));
}

#[test]
fn ops_rebase_state_options_can_drop_line_comments_and_new_group_briefs() {
    let (state, summary) = ops::rebase_state_with_options(
        &support::rebase_old_doc(),
        &support::rebase_new_doc(),
        &ops::extract_review_state(&support::rebase_old_doc()),
        &RebaseOptions {
            preserve_groups: false,
            carry_line_comments: false,
            similarity_threshold: 0.1,
        },
    )
    .unwrap();
    assert!(summary.mapped_reviews >= 3);
    assert!(state["reviews"]
        .as_object()
        .unwrap()
        .values()
        .all(|record| record.get("lineComments").is_none()));
    assert!(state["groupBriefs"].as_object().unwrap().is_empty());
}

#[test]
fn ops_append_rebase_history_metadata_trims_history_to_max_entries() {
    let old_doc = support::rebase_old_doc();
    let new_doc = support::rebase_new_doc();
    let (_, summary) =
        ops::rebase_state(&old_doc, &new_doc, &ops::extract_review_state(&old_doc)).unwrap();
    let mut target = new_doc.clone();
    ops::append_rebase_history_metadata(
        &mut target,
        &old_doc,
        &new_doc,
        &summary,
        Some("first"),
        Some("alice"),
        1,
        1,
    )
    .unwrap();
    ops::append_rebase_history_metadata(
        &mut target,
        &old_doc,
        &new_doc,
        &summary,
        Some("second"),
        Some("bob"),
        1,
        1,
    )
    .unwrap();

    let history = target["meta"]["x-reviewHistory"].as_array().unwrap();
    assert_eq!(history.len(), 1);
    assert_eq!(history[0]["label"], json!("second"));
    assert!(target["meta"].get("x-impactScope").is_some());
}

#[test]
fn ops_apply_layout_rejects_duplicate_groups_and_bad_assignment_shapes() {
    let duplicate = ops::apply_layout(
        &support::rich_doc(),
        &json!({"groups": [{"id": "g1", "name": "One"}, {"id": "g1", "name": "Again"}]}),
    )
    .unwrap_err();
    assert!(duplicate.contains("Duplicate group id"));

    let bad_assignment = ops::apply_layout(
        &support::rich_doc(),
        &json!({"assignments": {"g-ui": "not-list"}}),
    )
    .unwrap_err();
    assert!(bad_assignment.contains("must be a list"));
}

#[test]
fn ops_apply_layout_warns_for_unknown_groups_unknown_chunks_and_duplicates() {
    let (_next, warnings) = ops::apply_layout(
        &support::rich_doc(),
        &json!({
            "assignments": {
                "g-ui": ["c-ui-login", "c-docs"],
                "g-api": ["c-docs", "missing"],
                "ghost": ["c-api-route"]
            }
        }),
    )
    .unwrap();
    assert!(warnings.iter().any(|w| w.contains("unknown group")));
    assert!(warnings.iter().any(|w| w.contains("unknown chunk")));
    assert!(warnings.iter().any(|w| w.contains("multiple groups")));
}

#[test]
fn ops_apply_slice_patch_ignores_empty_move_items_and_keeps_metadata_counts() {
    let patched = ops::apply_slice_patch(
        &support::rich_doc(),
        &json!({"rename": {"g-ui": "UI Renamed"}, "move": [{"chunk": "", "to": "g-ui"}]}),
    )
    .unwrap();
    assert_eq!(patched["groups"][0]["name"], json!("UI Renamed"));
    assert_eq!(patched["meta"]["x-slicePatch"]["renameCount"], json!(1));
    assert_eq!(patched["meta"]["x-slicePatch"]["moveCount"], json!(1));
}

#[test]
fn ops_apply_slice_patch_rejects_unknown_group() {
    let err = ops::apply_slice_patch(
        &support::rich_doc(),
        &json!({"move": [{"chunk": "c-docs", "to": "missing"}]}),
    )
    .unwrap_err();
    assert!(err.contains("Unknown group id"));
}

#[test]
fn ops_refine_group_names_ja_renames_group_from_content_keywords() {
    let doc = json!({
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "refine"},
        "groups": [{"id": "g1", "name": "Group 1", "order": 1}],
        "chunks": [{
            "id": "c1",
            "filePath": "web/component.tsx",
            "header": "Button component",
            "old": {"start": 1, "count": 1},
            "new": {"start": 1, "count": 1},
            "lines": [{"kind": "add", "text": "<button>OK</button>", "oldLine": null, "newLine": 1}]
        }],
        "assignments": {"g1": ["c1"]},
        "reviews": {}
    });
    let refined = ops::refine_group_names_ja(&doc);
    assert_eq!(refined["groups"][0]["name"], json!("画面/UI"));
    assert_eq!(
        refined["meta"]["x-sliceRefine"]["method"],
        json!("heuristic-rust")
    );
}

#[test]
fn ops_ai_refine_prompt_truncates_chunks_per_group() {
    let prompt = ops::build_ai_refine_prompt_markdown(&support::rich_doc(), 1);
    assert!(prompt.contains("DiffGR 仮想PR分割"));
    assert!(prompt.contains("... (1 more)"));
}

#[test]
fn ops_autoslice_rejects_invalid_name_style_before_git_access() {
    let err = ops::autoslice_document_by_commits(
        &support::rich_doc(),
        &AutosliceOptions {
            name_style: "bad-style".to_owned(),
            ..AutosliceOptions::default()
        },
    )
    .unwrap_err();
    assert!(err.contains("name_style"));
}

#[test]
fn ops_generate_document_from_missing_repo_reports_git_failure() {
    let options = GenerateOptions {
        repo: PathBuf::from("/path/that/does/not/exist/diffgr-ut"),
        base: "main".to_owned(),
        feature: "HEAD".to_owned(),
        title: "missing".to_owned(),
        include_patch: false,
    };
    let err = ops::build_diffgr_document(&options).unwrap_err();
    assert!(err.to_lowercase().contains("git"));
}
