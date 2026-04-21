mod support;

use diffgr_gui::model::{
    normalize_state_payload, DiffLine, DiffgrDocument, GroupBriefDraft, LineAnchor, ReviewStatus,
};
use serde_json::{json, Value};
use std::fs;

fn doc() -> DiffgrDocument {
    DiffgrDocument::from_value(support::rich_doc()).unwrap()
}

#[test]
fn more_model_review_status_roundtrip_and_toggle_contract() {
    assert_eq!(ReviewStatus::from_str("reviewed").as_str(), "reviewed");
    assert_eq!(ReviewStatus::from_str("ignored").as_str(), "ignored");
    assert_eq!(
        ReviewStatus::from_str("needsReReview").as_str(),
        "needsReReview"
    );
    assert_eq!(
        ReviewStatus::from_str("anything-else"),
        ReviewStatus::Unreviewed
    );
    assert_eq!(
        ReviewStatus::Reviewed.next_review_toggle(),
        ReviewStatus::Unreviewed
    );
    assert_eq!(
        ReviewStatus::Ignored.next_review_toggle(),
        ReviewStatus::Reviewed
    );
    assert!(!ReviewStatus::Ignored.is_tracked());
}

#[test]
fn more_model_diff_line_prefix_anchor_and_label_are_stable() {
    let line = DiffLine {
        kind: "add".to_owned(),
        text: "x".to_owned(),
        old_line: None,
        new_line: Some(42),
    };
    assert_eq!(line.prefix(), "+");
    let anchor = line.anchor();
    assert_eq!(anchor.key(), "add::42");
    assert_eq!(anchor.label(), "add old:- new:42");
}

#[test]
fn more_model_chunk_helpers_return_short_ids_ranges_and_counts() {
    let doc = doc();
    let chunk = doc.chunk_by_id("c-ui-login").unwrap();
    assert_eq!(chunk.short_id(), "c-ui-lo");
    assert_eq!(chunk.old_range_label(), "10+2");
    assert_eq!(chunk.new_range_label(), "10+3");
    assert_eq!(chunk.change_counts(), (1, 0));
}

#[test]
fn more_model_status_counts_total_pending_and_tracked_match_fixture() {
    let counts = doc().status_counts();
    assert_eq!(counts.total(), 3);
    assert_eq!(counts.reviewed, 1);
    assert_eq!(counts.needs_re_review, 1);
    assert_eq!(counts.unreviewed, 1);
    assert_eq!(counts.pending(), 2);
    assert_eq!(counts.tracked(), 3);
}

#[test]
fn more_model_metrics_update_after_ignoring_chunk() {
    let mut doc = doc();
    doc.set_status("c-docs", ReviewStatus::Ignored);
    let metrics = doc.metrics();
    assert_eq!(metrics.tracked, 2);
    assert_eq!(metrics.reviewed, 1);
    assert_eq!(metrics.pending, 1);
    assert!(metrics.coverage_rate > 0.49 && metrics.coverage_rate < 0.51);
}

#[test]
fn more_model_group_metrics_none_includes_all_groups() {
    let metrics = doc().group_metrics(None);
    assert_eq!(metrics.tracked, 3);
    assert_eq!(metrics.reviewed, 1);
    assert_eq!(metrics.pending, 2);
}

#[test]
fn more_model_group_metrics_some_limits_to_selected_group() {
    let metrics = doc().group_metrics(Some("g-ui"));
    assert_eq!(metrics.tracked, 1);
    assert_eq!(metrics.reviewed, 1);
    assert_eq!(metrics.pending, 0);
}

#[test]
fn more_model_file_summaries_include_chunk_and_line_comment_counts() {
    let rows = doc().file_summaries();
    let ui = rows
        .iter()
        .find(|row| row.file_path == "src/ui/login.rs")
        .unwrap();
    assert_eq!(ui.chunks, 1);
    assert_eq!(ui.reviewed, 1);
    assert_eq!(ui.comments, 2);
    assert_eq!(ui.tracked(), 1);
    assert_eq!(ui.coverage_rate(), 1.0);
}

#[test]
fn more_model_set_status_for_chunks_skips_unknown_and_counts_changes() {
    let mut doc = doc();
    let ids = vec![
        "c-docs".to_owned(),
        "missing".to_owned(),
        "c-ui-login".to_owned(),
    ];
    let changed = doc.set_status_for_chunks(&ids, ReviewStatus::Reviewed);
    assert_eq!(changed, 1);
    assert_eq!(doc.status_for("c-docs"), ReviewStatus::Reviewed);
}

#[test]
fn more_model_unreviewed_status_prunes_empty_review_record() {
    let mut doc = doc();
    doc.set_comment("c-docs", " temporary ");
    assert_eq!(doc.comment_for("c-docs"), "temporary");
    doc.set_comment("c-docs", "   ");
    doc.set_status("c-docs", ReviewStatus::Unreviewed);
    assert!(doc.raw["reviews"].get("c-docs").is_none());
}

#[test]
fn more_model_line_comment_replace_does_not_duplicate_anchor() {
    let mut doc = doc();
    let anchor = LineAnchor {
        line_type: "add".to_owned(),
        old_line: None,
        new_line: Some(11),
    };
    doc.set_line_comment("c-ui-login", &anchor, "first");
    doc.set_line_comment("c-ui-login", &anchor, "second");
    assert_eq!(doc.line_comment_for("c-ui-login", &anchor), "second");
    assert_eq!(doc.line_comment_count_for("c-ui-login"), 1);
}

#[test]
fn more_model_line_comment_removal_clears_matching_selected_anchor() {
    let mut doc = doc();
    let anchor = LineAnchor {
        line_type: "add".to_owned(),
        old_line: None,
        new_line: Some(99),
    };
    doc.set_line_comment("c-docs", &anchor, "note");
    assert_eq!(doc.selected_line_anchor_from_state(), Some(anchor.clone()));
    doc.set_line_comment("c-docs", &anchor, "");
    assert_eq!(doc.selected_line_anchor_from_state(), None);
}

#[test]
fn more_model_analysis_state_set_get_and_remove_roundtrip() {
    let mut doc = doc();
    doc.set_analysis_string("filterText", Some("  routes  "));
    assert_eq!(doc.analysis_string("filterText").as_deref(), Some("routes"));
    doc.set_analysis_string("filterText", Some("  "));
    assert!(doc.analysis_string("filterText").is_none());
}

#[test]
fn more_model_normalize_state_accepts_wrapped_state_payload() {
    let normalized = normalize_state_payload(json!({"state": support::minimal_state()})).unwrap();
    assert!(normalized["reviews"].is_object());
    assert!(normalized["groupBriefs"].is_object());
    assert!(normalized["analysisState"].is_object());
    assert!(normalized["threadState"].is_object());
}

#[test]
fn more_model_normalize_state_rejects_scalar_payload() {
    let err = normalize_state_payload(json!(true)).unwrap_err();
    assert!(err.contains("JSON object"));
}

#[test]
fn more_model_normalize_state_rejects_object_without_state_sections() {
    let err = normalize_state_payload(json!({"hello": "world"})).unwrap_err();
    assert!(err.contains("reviews"));
}

#[test]
fn more_model_apply_state_value_removes_empty_optional_sections_but_keeps_reviews() {
    let mut doc = doc();
    doc.apply_state_value(
        json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}}),
    )
    .unwrap();
    assert!(doc.raw.get("reviews").unwrap().is_object());
    assert!(doc.raw.get("groupBriefs").is_none());
    assert!(doc.raw.get("analysisState").is_none());
    assert!(doc.raw.get("threadState").is_none());
}

#[test]
fn more_model_extract_state_always_has_four_sections() {
    let state = doc().extract_state();
    for key in ["reviews", "groupBriefs", "analysisState", "threadState"] {
        assert!(state[key].is_object(), "{key} missing from extracted state");
    }
}

#[test]
fn more_model_state_diff_against_value_reports_added_and_changed() {
    let report = doc()
        .state_diff_against_value(support::minimal_state())
        .unwrap();
    assert!(report.changed_total() > 0);
    let reviews = report.section("reviews").unwrap();
    assert!(
        reviews.added.contains(&"c-docs".to_owned())
            || reviews.changed.contains(&"c-ui-login".to_owned())
    );
}

#[test]
fn more_model_merge_state_preview_applies_incoming_precedence() {
    let preview = doc()
        .merge_state_value(support::minimal_state(), "incoming")
        .unwrap();
    assert!(preview.applied_reviews >= 1);
    assert_eq!(
        preview.merged_state["reviews"]["c-ui-login"]["comment"],
        json!("state comment")
    );
}

#[test]
fn more_model_apply_merged_state_preview_changes_document() {
    let mut doc = doc();
    let preview = doc
        .merge_state_value(support::minimal_state(), "incoming")
        .unwrap();
    doc.apply_merged_state_preview(preview).unwrap();
    assert_eq!(doc.status_for("c-docs"), ReviewStatus::Ignored);
}

#[test]
fn more_model_group_brief_draft_invalid_status_falls_back_to_draft() {
    let mut raw = support::rich_doc();
    raw["groupBriefs"]["g-ui"]["status"] = json!("not-valid");
    let doc = DiffgrDocument::from_value(raw).unwrap();
    assert_eq!(doc.group_brief_draft("g-ui").status, "draft");
}

#[test]
fn more_model_group_brief_pipe_lists_roundtrip() {
    let mut doc = doc();
    let draft = GroupBriefDraft {
        status: "ready".to_owned(),
        summary: "summary".to_owned(),
        updated_at: "now".to_owned(),
        source_head: "head".to_owned(),
        focus_points: "one | two |  | three".to_owned(),
        test_evidence: "cargo test".to_owned(),
        known_tradeoffs: "none".to_owned(),
        questions_for_reviewer: "q1 | q2".to_owned(),
        mentions: "@alice | @bob".to_owned(),
    };
    doc.set_group_brief_from_draft("g-empty", &draft);
    let reread = doc.group_brief_draft("g-empty");
    assert_eq!(reread.status, "ready");
    assert_eq!(reread.focus_points, "one | two | three");
    assert_eq!(reread.mentions, "@alice | @bob");
}

#[test]
fn more_model_group_brief_empty_draft_removes_record() {
    let mut doc = doc();
    let mut draft = GroupBriefDraft::default();
    draft.status.clear();
    doc.set_group_brief_from_draft("g-ui", &draft);
    assert!(doc.raw["groupBriefs"].get("g-ui").is_none());
}

#[test]
fn more_model_create_group_duplicate_is_error() {
    let mut doc = doc();
    let err = doc.create_group("g-ui", "Duplicate", &[]).unwrap_err();
    assert!(err.contains("already exists"));
}

#[test]
fn more_model_rename_group_unknown_is_error() {
    let mut doc = doc();
    let err = doc.rename_group("missing", "Name", &[]).unwrap_err();
    assert!(err.contains("Group not found"));
}

#[test]
fn more_model_delete_group_removes_assignment_and_brief() {
    let mut doc = doc();
    doc.delete_group_keep_chunks_unassigned("g-ui").unwrap();
    assert!(doc.group_by_id("g-ui").is_none());
    assert!(doc.assignments.get("g-ui").is_none());
    assert!(doc.raw["groupBriefs"].get("g-ui").is_none());
    assert!(doc
        .unassigned_chunk_ids()
        .contains(&"c-ui-login".to_owned()));
}

#[test]
fn more_model_assign_chunk_to_group_moves_from_previous_group() {
    let mut doc = doc();
    doc.assign_chunk_to_group("c-docs", "g-ui").unwrap();
    assert_eq!(
        doc.primary_group_for_chunk("c-docs").as_deref(),
        Some("g-ui")
    );
    assert!(!doc
        .assignments
        .get("g-api")
        .unwrap()
        .contains(&"c-docs".to_owned()));
}

#[test]
fn more_model_assign_chunk_unknown_chunk_and_group_are_errors() {
    let mut doc = doc();
    assert!(doc
        .assign_chunk_to_group("missing", "g-ui")
        .unwrap_err()
        .contains("Chunk not found"));
    assert!(doc
        .assign_chunk_to_group("c-docs", "missing")
        .unwrap_err()
        .contains("Group not found"));
}

#[test]
fn more_model_unassign_chunk_errors_for_unknown_chunk() {
    let mut doc = doc();
    let err = doc.unassign_chunk("missing").unwrap_err();
    assert!(err.contains("Chunk not found"));
}

#[test]
fn more_model_apply_layout_patch_value_moves_and_renames() {
    let mut doc = doc();
    let changed = doc
        .apply_layout_patch_value(&json!({
            "rename": {"g-api": "API renamed"},
            "move": [{"chunk": "c-docs", "to": "g-ui"}]
        }))
        .unwrap();
    assert!(changed >= 1);
    assert_eq!(doc.group_by_id("g-api").unwrap().name, "API renamed");
    assert_eq!(
        doc.primary_group_for_chunk("c-docs").as_deref(),
        Some("g-ui")
    );
}

#[test]
fn more_model_coverage_detects_duplicate_and_unknown_references() {
    let mut raw = support::rich_doc();
    raw["assignments"] = json!({"g-ui": ["c-ui-login", "c-docs"], "g-api": ["c-docs", "missing"], "missing-group": ["c-api-route"]});
    let doc = DiffgrDocument::from_value(raw).unwrap();
    let issue = doc.analyze_coverage();
    assert!(!issue.ok());
    assert!(issue.duplicated.contains_key("c-docs"));
    assert!(issue.unknown_groups.contains(&"missing-group".to_owned()));
    assert!(issue.unknown_chunks.contains_key("missing"));
    assert!(issue.problem_count() >= 3);
}

#[test]
fn more_model_coverage_fix_prompt_reports_none_when_covered() {
    let prompt = doc().coverage_fix_prompt_markdown_limited(1, 1);
    assert!(prompt.contains("(none)") || prompt.contains("既に網羅"));
}

#[test]
fn more_model_split_group_review_document_rejects_unknown_group() {
    let err = doc().split_group_review_document("missing").unwrap_err();
    assert!(err.contains("Group not found"));
}

#[test]
fn more_model_split_group_review_document_contains_only_selected_group_chunks() {
    let split = doc().split_group_review_document("g-ui").unwrap();
    assert_eq!(split["groups"].as_array().unwrap().len(), 1);
    assert_eq!(split["chunks"].as_array().unwrap().len(), 1);
    assert!(split["reviews"].get("c-api-route").is_none());
}

#[test]
fn more_model_html_report_escapes_title_and_contains_chunk_ids() {
    let mut raw = support::rich_doc();
    raw["meta"]["title"] = json!("<b>danger</b>");
    let html = DiffgrDocument::from_value(raw)
        .unwrap()
        .review_html_report();
    assert!(html.contains("&lt;b&gt;danger&lt;/b&gt;"));
    assert!(html.contains("c-ui-login"));
}

#[test]
fn more_model_approval_force_allows_empty_group_but_regular_approval_rejects_it() {
    let mut doc = doc();
    assert!(doc
        .approve_group("g-empty", "alice", false)
        .unwrap_err()
        .contains("no assigned chunks"));
    doc.approve_group("g-empty", "alice", true).unwrap();
    let status = doc.check_group_approval("g-empty");
    assert!(status.approved);
}

#[test]
fn more_model_request_changes_and_revoke_use_default_reviewer_reason() {
    let mut doc = doc();
    doc.request_changes_on_group("g-ui", " ", " fix it ")
        .unwrap();
    assert_eq!(
        doc.raw["groupBriefs"]["g-ui"]["approval"]["state"],
        json!("changesRequested")
    );
    assert_eq!(
        doc.raw["groupBriefs"]["g-ui"]["approval"]["changesRequestedBy"],
        json!("reviewer")
    );
    doc.revoke_group_approval("g-ui", " ", " ").unwrap();
    assert_eq!(
        doc.raw["groupBriefs"]["g-ui"]["approval"]["state"],
        json!("revoked")
    );
    assert_eq!(
        doc.raw["groupBriefs"]["g-ui"]["approval"]["invalidationReason"],
        json!("revoked")
    );
}

#[test]
fn more_model_approval_report_json_and_markdown_have_same_group_count() {
    let doc = doc();
    let json_report = doc.approval_report_json_value();
    let markdown = doc.approval_report_markdown();
    assert_eq!(
        json_report["groups"].as_array().unwrap().len(),
        doc.groups.len()
    );
    assert!(markdown.contains("DiffGR Approval Report"));
}

#[test]
fn more_model_write_full_document_creates_backup_with_json_bak_suffix() {
    let root = support::temp_dir("more_model_backup");
    let path = root.join("review.diffgr.json");
    fs::write(&path, "{\"old\":true}\n").unwrap();
    doc().write_full_document(&path, true).unwrap();
    assert!(path.exists());
    assert!(root.join("review.diffgr.json.bak").exists());
    fs::remove_dir_all(root).ok();
}

#[test]
fn more_model_write_state_creates_parent_dirs_and_roundtrips() {
    let root = support::temp_dir("more_model_write_state");
    let path = root.join("nested").join("review.state.json");
    doc().write_state(&path).unwrap();
    let state: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
    assert!(state["reviews"].is_object());
    fs::remove_dir_all(root).ok();
}

#[test]
fn more_model_load_rejects_missing_required_key_with_specific_message() {
    let mut raw = support::rich_doc();
    raw.as_object_mut().unwrap().remove("reviews");
    let err = DiffgrDocument::from_value(raw).unwrap_err();
    assert!(err.contains("Missing required key: reviews"));
}
