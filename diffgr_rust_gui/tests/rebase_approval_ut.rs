mod support;

use diffgr_gui::ops::{self, RebaseOptions};
use serde_json::json;

#[test]
fn approve_groups_requires_reviewed_chunks_unless_forced() {
    let doc = support::rich_doc();
    let err = ops::approve_groups(&doc, &["g-api".to_owned()], "alice", false).unwrap_err();
    assert!(err.contains("unreviewed") || err.contains("reviewed"));

    let approved = ops::approve_groups(&doc, &["g-api".to_owned()], "alice", true).unwrap();
    let report = ops::approval_report(&approved).unwrap();
    let g_api = report["groups"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["groupId"].as_str() == Some("g-api"))
        .unwrap();
    assert_eq!(g_api["approved"], json!(true));
}

#[test]
fn request_changes_overrides_approval_and_records_comment() {
    let doc =
        ops::approve_groups(&support::rich_doc(), &["g-ui".to_owned()], "alice", true).unwrap();
    let changed =
        ops::request_changes(&doc, &["g-ui".to_owned()], "bob", "please add tests").unwrap();
    let approval = &changed["groupBriefs"]["g-ui"]["approval"];
    assert_eq!(approval["state"], json!("changesRequested"));
    assert_eq!(approval["approved"], json!(false));
    assert_eq!(approval["comment"], json!("please add tests"));
}

#[test]
fn approval_report_marks_fingerprint_invalidation() {
    let mut approved =
        ops::approve_groups(&support::rich_doc(), &["g-ui".to_owned()], "alice", true).unwrap();
    assert_eq!(
        ops::approval_report(&approved).unwrap()["groups"][0]["valid"],
        json!(true)
    );
    approved["chunks"][0]["lines"][1]["text"] = json!("changed after approval");
    let report = ops::approval_report(&approved).unwrap();
    let g_ui = report["groups"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["groupId"].as_str() == Some("g-ui"))
        .unwrap();
    assert_eq!(g_ui["approved"], json!(true));
    assert_eq!(g_ui["valid"], json!(false));
    assert_eq!(g_ui["reason"], json!("invalidated_fingerprint"));
}

#[test]
fn rebase_state_maps_strong_stable_and_similar_matches() {
    let old_doc = support::rebase_old_doc();
    let new_doc = support::rebase_new_doc();
    let state = ops::extract_review_state(&old_doc);
    let (rebased, summary) = ops::rebase_state_with_options(
        &old_doc,
        &new_doc,
        &state,
        &RebaseOptions {
            similarity_threshold: 0.50,
            ..RebaseOptions::default()
        },
    )
    .unwrap();

    assert_eq!(summary.mapped_reviews, 3);
    assert_eq!(summary.unmapped_reviews, 1);
    assert_eq!(summary.matched_strong, 1);
    assert!(summary.matched_stable >= 1);
    assert!(summary.matched_similar >= 1);
    assert_eq!(rebased["reviews"]["same-id"]["status"], json!("reviewed"));
    assert_eq!(
        rebased["reviews"]["new-stable"]["status"],
        json!("reviewed")
    );
    assert_eq!(
        rebased["reviews"]["new-similar"]["status"],
        json!("needsReReview")
    );
    assert!(rebased["reviews"]["new-similar"]
        .get("lineComments")
        .is_none());
    assert!(summary.warnings.iter().any(|w| w.contains("old-gone")));
}

#[test]
fn rebase_state_can_drop_line_comments_even_for_stable_matches() {
    let old_doc = support::rebase_old_doc();
    let new_doc = support::rebase_new_doc();
    let state = ops::extract_review_state(&old_doc);
    let (rebased, _summary) = ops::rebase_state_with_options(
        &old_doc,
        &new_doc,
        &state,
        &RebaseOptions {
            carry_line_comments: false,
            similarity_threshold: 0.50,
            ..RebaseOptions::default()
        },
    )
    .unwrap();

    assert!(rebased["reviews"]["same-id"].get("lineComments").is_none());
    assert!(rebased["reviews"]["new-stable"]
        .get("lineComments")
        .is_none());
}

#[test]
fn rebase_state_marks_group_briefs_stale_and_invalidates_approval_when_head_changes() {
    let old_doc = support::rebase_old_doc();
    let new_doc = support::rebase_new_doc();
    let state = ops::extract_review_state(&old_doc);
    let (rebased, _summary) = ops::rebase_state(&old_doc, &new_doc, &state).unwrap();

    assert_eq!(rebased["groupBriefs"]["g-old"]["status"], json!("stale"));
    assert_eq!(
        rebased["groupBriefs"]["g-old"]["approval"]["state"],
        json!("invalidated")
    );
    assert_eq!(
        rebased["groupBriefs"]["g-old"]["approval"]["approved"],
        json!(false)
    );
}

#[test]
fn rebase_state_preserve_groups_false_keeps_only_new_group_brief_targets() {
    let old_doc = support::rebase_old_doc();
    let mut new_doc = support::rebase_new_doc();
    let mut state = ops::extract_review_state(&old_doc);
    state["groupBriefs"]["g-new"] = json!({"status": "ready", "summary": "new target"});
    new_doc["groups"][0]["id"] = json!("g-new");

    let (rebased, _summary) = ops::rebase_state_with_options(
        &old_doc,
        &new_doc,
        &state,
        &RebaseOptions {
            preserve_groups: false,
            similarity_threshold: 0.50,
            ..RebaseOptions::default()
        },
    )
    .unwrap();
    assert!(rebased["groupBriefs"].get("g-old").is_none());
    assert_eq!(
        rebased["groupBriefs"]["g-new"]["summary"],
        json!("new target")
    );
}

#[test]
fn rebase_reviews_document_preserves_old_layout_by_default() {
    let old_doc = support::rebase_old_doc();
    let new_doc = support::rebase_new_doc();
    let (rebased, summary) = ops::rebase_reviews_document_with_options(
        &old_doc,
        &new_doc,
        &RebaseOptions {
            similarity_threshold: 0.50,
            ..RebaseOptions::default()
        },
    )
    .unwrap();

    assert!(summary.mapped_reviews >= 3);
    assert!(rebased["groups"]
        .as_array()
        .unwrap()
        .iter()
        .any(|g| g["id"].as_str() == Some("g-old")));
    assert!(rebased["assignments"]["g-old"]
        .as_array()
        .unwrap()
        .iter()
        .any(|id| id.as_str() == Some("new-stable")));
    assert!(rebased["meta"].get("x-reviewRebase").is_some());
}

#[test]
fn rebase_reviews_document_can_keep_new_layout() {
    let old_doc = support::rebase_old_doc();
    let new_doc = support::rebase_new_doc();
    let (rebased, _summary) = ops::rebase_reviews_document_with_options(
        &old_doc,
        &new_doc,
        &RebaseOptions {
            preserve_groups: false,
            similarity_threshold: 0.50,
            ..RebaseOptions::default()
        },
    )
    .unwrap();

    assert_eq!(rebased["groups"][0]["id"], json!("g-new"));
    assert!(rebased["assignments"]["g-new"]
        .as_array()
        .unwrap()
        .iter()
        .any(|id| id.as_str() == Some("new-only")));
}

#[test]
fn append_rebase_history_metadata_trims_history_and_records_scope() {
    let old_doc = support::rebase_old_doc();
    let new_doc = support::rebase_new_doc();
    let (_rebased_state, summary) =
        ops::rebase_state(&old_doc, &new_doc, &ops::extract_review_state(&old_doc)).unwrap();
    let mut doc = new_doc.clone();
    doc["meta"]["x-reviewHistory"] = json!([
        {"type": "old1"},
        {"type": "old2"}
    ]);

    ops::append_rebase_history_metadata(
        &mut doc,
        &old_doc,
        &new_doc,
        &summary,
        Some("nightly"),
        Some("ci"),
        2,
        1,
    )
    .unwrap();

    let history = doc["meta"]["x-reviewHistory"].as_array().unwrap();
    assert_eq!(history.len(), 2);
    assert_eq!(history[1]["label"], json!("nightly"));
    assert_eq!(history[1]["actor"], json!("ci"));
    assert!(doc["meta"].get("x-impactScope").is_some());
}

#[test]
fn impact_report_with_options_and_markdown_include_matching_metadata() {
    let old_doc = support::rebase_old_doc();
    let new_doc = support::rebase_new_doc();
    let report =
        ops::impact_report_with_options(&old_doc, &new_doc, None, "group", 0.42, 7).unwrap();
    assert_eq!(report["grouping"], json!("group"));
    assert_eq!(report["match"]["similarityThreshold"], json!(0.42));
    let markdown = ops::format_impact_report_markdown(&report, 10);
    assert!(markdown.contains("DiffGR Impact Report"));
    assert!(markdown.contains("new only"));
}

#[test]
fn rebase_summary_json_exposes_python_compatible_counters() {
    let old_doc = support::rebase_old_doc();
    let new_doc = support::rebase_new_doc();
    let (_rebased, summary) =
        ops::rebase_state(&old_doc, &new_doc, &ops::extract_review_state(&old_doc)).unwrap();
    let json = ops::rebase_summary_json(&summary);
    for key in [
        "mappedReviews",
        "unmappedReviews",
        "matchedStrong",
        "matchedStable",
        "matchedDelta",
        "matchedSimilar",
        "changedToNeedsReReview",
        "unmappedNewChunks",
    ] {
        assert!(json.get(key).is_some(), "missing {key}");
    }
}
