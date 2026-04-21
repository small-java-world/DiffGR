mod support;

use diffgr_gui::model::{DiffgrDocument, GroupBriefDraft, LineAnchor, ReviewStatus};
use diffgr_gui::ops;
use serde_json::json;

#[test]
fn apply_layout_replaces_groups_assignments_and_merges_briefs() {
    let doc = support::rich_doc();
    let (out, warnings) = ops::apply_layout(
        &doc,
        &json!({
            "groups": [
                {"id": "g-review", "name": "Review", "order": 10, "tags": ["new"]},
                {"id": "g-docs", "name": "Docs", "order": 20}
            ],
            "assignments": {
                "g-review": ["c-api-route", "c-ui-login", "c-api-route"],
                "g-docs": ["c-docs"],
                "missing-group": ["c-ui-login"]
            },
            "groupBriefs": {"g-review": {"status": "ready", "summary": "merged"}}
        }),
    )
    .unwrap();

    assert!(warnings.iter().any(|w| w.contains("multiple groups")));
    assert!(warnings.iter().any(|w| w.contains("unknown group")));
    assert_eq!(out["groups"].as_array().unwrap().len(), 2);
    assert_eq!(out["assignments"]["g-review"].as_array().unwrap().len(), 2);
    assert_eq!(out["groupBriefs"]["g-review"]["summary"], json!("merged"));
    assert!(out["groupBriefs"].get("g-ui").is_none());
}

#[test]
fn apply_layout_rejects_duplicate_group_ids_and_bad_assignment_shape() {
    let doc = support::rich_doc();
    let duplicate = ops::apply_layout(
        &doc,
        &json!({
            "groups": [
                {"id": "g", "name": "one"},
                {"id": "g", "name": "two"}
            ]
        }),
    )
    .unwrap_err();
    assert!(duplicate.contains("Duplicate group id"));

    let bad_assignment =
        ops::apply_layout(&doc, &json!({"assignments": {"g-ui": "not-list"}})).unwrap_err();
    assert!(bad_assignment.contains("must be a list"));
}

#[test]
fn model_group_brief_draft_trims_lists_and_removes_empty_brief() {
    let mut doc = DiffgrDocument::from_value(support::rich_doc()).unwrap();
    let mut draft = GroupBriefDraft::default();
    draft.status = "acknowledged".to_owned();
    draft.summary = "  summary  ".to_owned();
    draft.focus_points = "one | two | | three".to_owned();
    draft.mentions = "@alice|@bob".to_owned();
    doc.set_group_brief_from_draft("g-empty", &draft);

    let stored = doc.group_brief_draft("g-empty");
    assert_eq!(stored.status, "acknowledged");
    assert_eq!(stored.summary, "summary");
    assert_eq!(stored.focus_points, "one | two | three");
    assert_eq!(stored.mentions, "@alice | @bob");

    let mut empty = GroupBriefDraft::default();
    empty.status.clear();
    doc.set_group_brief_from_draft("g-empty", &empty);
    assert!(doc.raw["groupBriefs"].get("g-empty").is_none());
}

#[test]
fn model_line_comments_update_replace_remove_and_selected_anchor_state() {
    let mut doc = DiffgrDocument::from_value(support::rich_doc()).unwrap();
    let anchor = LineAnchor {
        line_type: "add".to_owned(),
        old_line: None,
        new_line: Some(11),
    };

    assert_eq!(
        doc.line_comment_for("c-ui-login", &anchor),
        "spinner is expected"
    );
    doc.set_line_comment("c-ui-login", &anchor, "updated");
    assert_eq!(doc.line_comment_for("c-ui-login", &anchor), "updated");
    assert_eq!(
        doc.selected_line_anchor_from_state().unwrap().new_line,
        Some(11)
    );

    doc.set_line_comment("c-ui-login", &anchor, "");
    assert_eq!(doc.line_comment_for("c-ui-login", &anchor), "");
    assert!(doc.selected_line_anchor_from_state().is_none());
}

#[test]
fn model_set_status_and_comment_prunes_empty_review_records() {
    let mut doc = DiffgrDocument::from_value(support::rich_doc()).unwrap();
    doc.set_status("c-docs", ReviewStatus::Reviewed);
    doc.set_comment("c-docs", " temporary ");
    assert_eq!(doc.status_for("c-docs"), ReviewStatus::Reviewed);
    assert_eq!(doc.comment_for("c-docs"), "temporary");

    doc.set_status("c-docs", ReviewStatus::Unreviewed);
    doc.set_comment("c-docs", "");
    assert!(doc.raw["reviews"].get("c-docs").is_none());
}

#[test]
fn model_write_full_document_makes_backup_and_state_write_uses_state_only() {
    let root = support::temp_dir("model_write");
    let path = root.join("review.diffgr.json");
    let state_path = root.join("review.state.json");
    let mut doc = DiffgrDocument::from_value(support::rich_doc()).unwrap();

    doc.write_full_document(&path, false).unwrap();
    doc.set_status("c-docs", ReviewStatus::Ignored);
    doc.write_full_document(&path, true).unwrap();
    doc.write_state(&state_path).unwrap();

    assert!(path.exists());
    assert!(path.with_extension("json.bak").exists());
    let state = support::read_json(&state_path);
    assert_eq!(state["reviews"]["c-docs"]["status"], json!("ignored"));
    assert!(state.get("chunks").is_none());

    std::fs::remove_dir_all(root).ok();
}
