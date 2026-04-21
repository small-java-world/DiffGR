mod support;

use diffgr_gui::model::{DiffLine, DiffgrDocument, GroupBriefDraft, LineAnchor, ReviewStatus};
use serde_json::{json, Value};
use std::fs;

fn doc() -> DiffgrDocument {
    DiffgrDocument::from_value(support::rich_doc()).unwrap()
}

#[test]
fn model_load_from_path_applies_state_overlay() {
    let root = support::temp_dir("model_load_overlay");
    let doc_path = root.join("review.diffgr.json");
    let state_path = root.join("review.state.json");
    fs::write(
        &doc_path,
        serde_json::to_string_pretty(&support::rich_doc()).unwrap(),
    )
    .unwrap();
    fs::write(
        &state_path,
        serde_json::to_string_pretty(&support::minimal_state()).unwrap(),
    )
    .unwrap();

    let loaded = DiffgrDocument::load_from_path(&doc_path, Some(&state_path)).unwrap();
    assert_eq!(loaded.status_for("c-docs"), ReviewStatus::Ignored);
    assert_eq!(loaded.comment_for("c-ui-login"), "state comment");
    assert_eq!(loaded.group_brief_draft("g-ui").status, "acknowledged");

    fs::remove_dir_all(root).ok();
}

#[test]
fn model_load_from_path_reports_missing_document() {
    let root = support::temp_dir("model_missing_doc");
    let err = DiffgrDocument::load_from_path(&root.join("missing.diffgr.json"), None).unwrap_err();
    assert!(err.contains("missing.diffgr.json"));
    fs::remove_dir_all(root).ok();
}

#[test]
fn model_load_from_path_reports_invalid_state_json() {
    let root = support::temp_dir("model_bad_state");
    let doc_path = root.join("review.diffgr.json");
    let state_path = root.join("review.state.json");
    fs::write(
        &doc_path,
        serde_json::to_string_pretty(&support::rich_doc()).unwrap(),
    )
    .unwrap();
    fs::write(&state_path, "{not-json").unwrap();

    let err = DiffgrDocument::load_from_path(&doc_path, Some(&state_path)).unwrap_err();
    assert!(err.contains("invalid state JSON"));
    fs::remove_dir_all(root).ok();
}

#[test]
fn model_create_group_uses_id_as_default_name_and_trims_tags() {
    let mut doc = doc();
    doc.create_group(
        " g-new ",
        "  ",
        &[" ui ".to_owned(), "".to_owned(), " review".to_owned()],
    )
    .unwrap();
    let group = doc.group_by_id("g-new").unwrap();
    assert_eq!(group.name, "g-new");
    assert_eq!(group.tags, vec!["ui".to_owned(), "review".to_owned()]);
    assert!(doc.assignments.get("g-new").unwrap().is_empty());
}

#[test]
fn model_create_group_rejects_empty_and_duplicate_ids() {
    let mut doc = doc();
    assert!(doc
        .create_group("   ", "Empty", &[])
        .unwrap_err()
        .contains("required"));
    assert!(doc
        .create_group("g-ui", "Duplicate", &[])
        .unwrap_err()
        .contains("already exists"));
}

#[test]
fn model_rename_group_blank_name_preserves_current_name_and_removes_tags() {
    let mut doc = doc();
    doc.rename_group("g-ui", "  ", &[]).unwrap();
    let group = doc.group_by_id("g-ui").unwrap();
    assert_eq!(group.name, "UI");
    assert!(group.tags.is_empty());
}

#[test]
fn model_rename_and_delete_group_report_missing_group() {
    let mut doc = doc();
    assert!(doc
        .rename_group("missing", "Missing", &[])
        .unwrap_err()
        .contains("Group not found"));
    assert!(doc
        .delete_group_keep_chunks_unassigned("missing")
        .unwrap_err()
        .contains("Group not found"));
}

#[test]
fn model_delete_group_removes_assignment_and_group_brief() {
    let mut doc = doc();
    assert!(doc.raw["groupBriefs"].get("g-ui").is_some());
    doc.delete_group_keep_chunks_unassigned("g-ui").unwrap();
    assert!(doc.group_by_id("g-ui").is_none());
    assert!(!doc.assignments.contains_key("g-ui"));
    assert!(doc
        .raw
        .get("groupBriefs")
        .and_then(|v| v.get("g-ui"))
        .is_none());
    assert!(doc
        .unassigned_chunk_ids()
        .contains(&"c-ui-login".to_owned()));
}

#[test]
fn model_assign_chunk_moves_from_previous_group_and_deduplicates() {
    let mut doc = doc();
    doc.assign_chunk_to_group("c-docs", "g-ui").unwrap();
    doc.assign_chunk_to_group("c-docs", "g-ui").unwrap();

    assert_eq!(
        doc.primary_group_for_chunk("c-docs"),
        Some("g-ui".to_owned())
    );
    assert!(!doc
        .assignments
        .get("g-api")
        .unwrap()
        .contains(&"c-docs".to_owned()));
    assert_eq!(
        doc.assignments
            .get("g-ui")
            .unwrap()
            .iter()
            .filter(|id| id.as_str() == "c-docs")
            .count(),
        1
    );
}

#[test]
fn model_assign_and_unassign_reject_unknown_ids() {
    let mut doc = doc();
    assert!(doc
        .assign_chunk_to_group("missing", "g-ui")
        .unwrap_err()
        .contains("Chunk not found"));
    assert!(doc
        .assign_chunk_to_group("c-docs", "missing")
        .unwrap_err()
        .contains("Group not found"));
    assert!(doc
        .unassign_chunk("missing")
        .unwrap_err()
        .contains("Chunk not found"));
}

#[test]
fn model_apply_layout_patch_counts_renames_and_nonempty_moves() {
    let mut doc = doc();
    let applied = doc
        .apply_layout_patch_value(&json!({
            "rename": {"g-ui": "UI renamed"},
            "move": [
                {"chunk": "", "to": "g-ui"},
                {"chunk": "c-docs", "to": "g-ui"}
            ]
        }))
        .unwrap();
    assert_eq!(applied, 2);
    assert_eq!(doc.group_by_id("g-ui").unwrap().name, "UI renamed");
    assert_eq!(
        doc.primary_group_for_chunk("c-docs"),
        Some("g-ui".to_owned())
    );
}

#[test]
fn model_apply_layout_patch_rejects_non_object_patch() {
    let mut doc = doc();
    assert!(doc
        .apply_layout_patch_value(&json!([]))
        .unwrap_err()
        .contains("JSON object"));
}

#[test]
fn model_line_anchor_key_and_label_are_stable_for_missing_lines() {
    let anchor = LineAnchor {
        line_type: "add".to_owned(),
        old_line: None,
        new_line: Some(42),
    };
    assert_eq!(anchor.key(), "add::42");
    assert_eq!(anchor.label(), "add old:- new:42");
}

#[test]
fn model_diff_line_prefix_and_anchor_match_kind() {
    let add = DiffLine {
        kind: "add".to_owned(),
        text: "x".to_owned(),
        old_line: None,
        new_line: Some(7),
    };
    let delete = DiffLine {
        kind: "delete".to_owned(),
        text: "x".to_owned(),
        old_line: Some(6),
        new_line: None,
    };
    let context = DiffLine {
        kind: "context".to_owned(),
        text: "x".to_owned(),
        old_line: Some(1),
        new_line: Some(1),
    };

    assert_eq!(add.prefix(), "+");
    assert_eq!(delete.prefix(), "-");
    assert_eq!(context.prefix(), " ");
    assert_eq!(add.anchor().key(), "add::7");
}

#[test]
fn model_line_comment_replacement_keeps_one_entry_per_anchor() {
    let mut doc = doc();
    let anchor = LineAnchor {
        line_type: "add".to_owned(),
        old_line: None,
        new_line: Some(11),
    };
    doc.set_line_comment("c-ui-login", &anchor, "first");
    doc.set_line_comment("c-ui-login", &anchor, "second");

    assert_eq!(doc.line_comment_count_for("c-ui-login"), 1);
    assert_eq!(doc.line_comment_for("c-ui-login", &anchor), "second");
}

#[test]
fn model_line_comment_removal_keeps_other_anchor_and_selected_anchor() {
    let mut doc = doc();
    let a1 = LineAnchor {
        line_type: "add".to_owned(),
        old_line: None,
        new_line: Some(11),
    };
    let a2 = LineAnchor {
        line_type: "context".to_owned(),
        old_line: Some(10),
        new_line: Some(10),
    };
    doc.set_line_comment("c-ui-login", &a1, "one");
    doc.set_line_comment("c-ui-login", &a2, "two");
    doc.set_line_comment("c-ui-login", &a1, "");

    assert_eq!(doc.line_comment_count_for("c-ui-login"), 1);
    assert_eq!(doc.line_comment_for("c-ui-login", &a2), "two");
    assert_eq!(doc.selected_line_anchor_from_state(), Some(a2));
}

#[test]
fn model_analysis_string_trims_values_and_prunes_empty_updates() {
    let mut doc = doc();
    doc.set_analysis_string("temporary", Some("  value  "));
    assert_eq!(doc.analysis_string("temporary"), Some("value".to_owned()));
    doc.set_analysis_string("temporary", Some("   "));
    assert_eq!(doc.analysis_string("temporary"), None);
}

#[test]
fn model_group_brief_invalid_status_reads_as_draft() {
    let mut raw = support::rich_doc();
    raw["groupBriefs"]["g-ui"]["status"] = json!("not-a-status");
    let doc = DiffgrDocument::from_value(raw).unwrap();
    assert_eq!(doc.group_brief_draft("g-ui").status, "draft");
}

#[test]
fn model_group_brief_invalid_status_is_not_written_but_summary_is_kept() {
    let mut doc = doc();
    let draft = GroupBriefDraft {
        status: "bad-status".to_owned(),
        summary: "keep summary".to_owned(),
        ..GroupBriefDraft::default()
    };
    doc.set_group_brief_from_draft("g-api", &draft);

    assert!(doc.raw["groupBriefs"]["g-api"].get("status").is_none());
    assert_eq!(
        doc.raw["groupBriefs"]["g-api"]["summary"],
        json!("keep summary")
    );
    assert_eq!(doc.group_brief_draft("g-api").status, "draft");
}

#[test]
fn model_unknown_chunk_status_and_comment_are_empty_defaults() {
    let doc = doc();
    assert_eq!(doc.status_for("missing"), ReviewStatus::Unreviewed);
    assert_eq!(doc.comment_for("missing"), "");
    assert_eq!(doc.line_comment_count_for("missing"), 0);
}

#[test]
fn model_file_summaries_sort_attention_files_first() {
    let doc = doc();
    let summaries = doc.file_summaries();
    assert_eq!(summaries[0].file_path, "src/api/routes.rs");
    assert_eq!(summaries[0].pending, 1);
    assert!(summaries
        .iter()
        .any(|row| row.file_path == "src/ui/login.rs" && row.reviewed == 1));
}

#[test]
fn model_file_summary_coverage_rate_is_one_when_only_ignored_chunks_are_tracked_out() {
    let mut raw = support::rich_doc();
    raw["reviews"] = json!({
        "c-ui-login": {"status": "ignored"},
        "c-api-route": {"status": "ignored"},
        "c-docs": {"status": "ignored"}
    });
    let doc = DiffgrDocument::from_value(raw).unwrap();
    for summary in doc.file_summaries() {
        assert_eq!(summary.tracked(), 0);
        assert_eq!(summary.coverage_rate(), 1.0);
    }
}

#[test]
fn model_markdown_report_escapes_table_pipes_in_file_paths() {
    let mut raw = support::rich_doc();
    raw["chunks"][0]["filePath"] = json!("src/a|b.rs");
    let doc = DiffgrDocument::from_value(raw).unwrap();
    let report = doc.review_markdown_report();
    assert!(report.contains("src/a\\|b.rs"));
}

#[test]
fn model_write_full_document_without_extension_uses_bak_extension() {
    let root = support::temp_dir("model_backup_no_ext");
    let path = root.join("review-file");
    let mut doc = doc();
    doc.write_full_document(&path, false).unwrap();
    doc.set_comment("c-ui-login", "changed");
    doc.write_full_document(&path, true).unwrap();

    assert!(path.exists());
    assert!(path.with_extension("bak").exists());
    fs::remove_dir_all(root).ok();
}

#[test]
fn model_apply_merged_state_preview_updates_document_state() {
    let mut doc = doc();
    let preview = doc
        .merge_state_value(
            json!({"reviews": {"c-docs": {"status": "reviewed"}}}),
            "incoming",
        )
        .unwrap();
    assert!(preview.diff.changed_total() > 0);
    doc.apply_merged_state_preview(preview).unwrap();
    assert_eq!(doc.status_for("c-docs"), ReviewStatus::Reviewed);
}

#[test]
fn model_state_diff_report_helpers_find_sections_and_totals() {
    let doc = doc();
    let diff = doc
        .state_diff_against_value(json!({
            "reviews": {"c-ui-login": {"status": "ignored"}},
            "groupBriefs": {},
            "analysisState": {},
            "threadState": {}
        }))
        .unwrap();
    assert!(diff.changed_total() >= 1);
    assert!(diff
        .section("reviews")
        .unwrap()
        .changed
        .contains(&"c-ui-login".to_owned()));
    assert!(diff.section("missing").is_none());
}

#[test]
fn model_split_group_review_document_rejects_missing_group() {
    let doc = doc();
    assert!(doc
        .split_group_review_document("missing")
        .unwrap_err()
        .contains("Group not found"));
}

#[test]
fn model_approval_report_json_and_markdown_include_all_groups() {
    let doc = doc();
    let value = doc.approval_report_json_value();
    assert_eq!(value["groups"].as_array().unwrap().len(), doc.groups.len());
    assert!(doc
        .approval_report_markdown()
        .contains("DiffGR Approval Report"));
}

#[test]
fn model_coverage_issue_problem_count_counts_each_issue_bucket() {
    let mut raw = support::rich_doc();
    raw["assignments"] = json!({
        "g-ui": ["c-ui-login", "c-docs"],
        "g-api": ["c-docs", "missing"],
        "ghost": ["c-api-route"]
    });
    let doc = DiffgrDocument::from_value(raw).unwrap();
    let issue = doc.analyze_coverage();
    assert_eq!(
        issue.problem_count(),
        issue.unassigned.len()
            + issue.duplicated.len()
            + issue.unknown_groups.len()
            + issue.unknown_chunks.len()
    );
    assert!(issue.problem_count() >= 3);
}

#[test]
fn model_status_counts_total_pending_and_tracked_remain_consistent() {
    let mut doc = doc();
    doc.set_status("c-ui-login", ReviewStatus::Reviewed);
    doc.set_status("c-api-route", ReviewStatus::NeedsReReview);
    doc.set_status("c-docs", ReviewStatus::Ignored);
    let counts = doc.status_counts();
    assert_eq!(counts.total(), 3);
    assert_eq!(counts.pending(), 1);
    assert_eq!(counts.tracked(), 2);
}

#[test]
fn model_set_status_for_chunks_returns_zero_for_missing_or_same_status() {
    let mut doc = doc();
    doc.set_status("c-ui-login", ReviewStatus::Reviewed);
    let changed = doc.set_status_for_chunks(
        &["c-ui-login".to_owned(), "missing".to_owned()],
        ReviewStatus::Reviewed,
    );
    assert_eq!(changed, 0);
}

#[test]
fn model_apply_state_value_rejects_non_object_state() {
    let mut doc = doc();
    assert!(doc
        .apply_state_value(json!([]))
        .unwrap_err()
        .contains("JSON object"));
}

#[test]
fn model_write_approval_report_json_creates_file() {
    let root = support::temp_dir("model_approval_json");
    let path = root.join("nested").join("approval.json");
    let doc = doc();
    doc.write_approval_report_json(&path).unwrap();
    let saved: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
    assert!(saved["groups"].as_array().unwrap().len() >= 3);
    fs::remove_dir_all(root).ok();
}
