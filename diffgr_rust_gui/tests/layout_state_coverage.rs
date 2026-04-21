use diffgr_gui::model::{DiffgrDocument, ReviewStatus};
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::process;
use std::time::{SystemTime, UNIX_EPOCH};

fn sample_doc() -> Value {
    json!({
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "parity sample"},
        "groups": [
            {"id": "g1", "name": "One", "order": 1},
            {"id": "g2", "name": "Two", "order": 2}
        ],
        "chunks": [
            {
                "id": "c1",
                "filePath": "src/a.rs",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 2},
                "lines": [
                    {"kind": "context", "text": "a", "oldLine": 1, "newLine": 1},
                    {"kind": "add", "text": "b", "oldLine": null, "newLine": 2}
                ]
            },
            {
                "id": "c2",
                "filePath": "src/b.rs",
                "old": {"start": 5, "count": 1},
                "new": {"start": 5, "count": 1},
                "lines": [
                    {"kind": "delete", "text": "old", "oldLine": 5, "newLine": null},
                    {"kind": "add", "text": "new", "oldLine": null, "newLine": 5}
                ]
            }
        ],
        "assignments": {"g1": ["c1"], "g2": []},
        "reviews": {}
    })
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time moves forward")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "diffgr_gui_parity_{}_{}_{}",
        label,
        process::id(),
        nanos
    ))
}

#[test]
fn group_create_rename_assign_unassign_roundtrip() {
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    assert_eq!(doc.unassigned_chunk_ids(), vec!["c2".to_owned()]);

    doc.create_group("g3", "Three", &["new".to_owned(), "ui".to_owned()])
        .unwrap();
    assert!(doc.group_by_id("g3").is_some());
    doc.rename_group("g3", "Three renamed", &["renamed".to_owned()])
        .unwrap();
    assert_eq!(doc.group_by_id("g3").unwrap().name, "Three renamed");

    doc.assign_chunk_to_group("c2", "g3").unwrap();
    assert_eq!(doc.primary_group_for_chunk("c2"), Some("g3".to_owned()));
    assert!(doc.unassigned_chunk_ids().is_empty());

    doc.unassign_chunk("c2").unwrap();
    assert_eq!(doc.unassigned_chunk_ids(), vec!["c2".to_owned()]);
}

#[test]
fn coverage_detects_unassigned_duplicates_and_unknowns() {
    let mut raw = sample_doc();
    raw["assignments"]["g1"] = json!(["c1", "c2"]);
    raw["assignments"]["g2"] = json!(["c2", "missing"]);
    raw["assignments"]["ghost"] = json!(["c1"]);
    let doc = DiffgrDocument::from_value(raw).unwrap();

    let issue = doc.analyze_coverage();
    assert!(!issue.ok());
    assert!(issue.duplicated.contains_key("c1"));
    assert!(issue.duplicated.contains_key("c2"));
    assert_eq!(issue.unknown_groups, vec!["ghost".to_owned()]);
    assert!(issue.unknown_chunks.contains_key("missing"));

    let prompt = doc.coverage_fix_prompt_markdown();
    assert!(prompt.contains("DiffGR 仮想PR網羅チェック"));
    assert!(prompt.contains("missing"));
}

#[test]
fn layout_patch_renames_and_moves() {
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    let applied = doc
        .apply_layout_patch_value(&json!({
            "rename": {"g2": "Two renamed"},
            "move": [{"chunk": "c2", "to": "g2"}]
        }))
        .unwrap();
    assert_eq!(applied, 2);
    assert_eq!(doc.group_by_id("g2").unwrap().name, "Two renamed");
    assert_eq!(doc.primary_group_for_chunk("c2"), Some("g2".to_owned()));
}

#[test]
fn state_diff_and_merge_preview_follow_python_precedence() {
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    doc.set_status("c1", ReviewStatus::Reviewed);
    doc.set_comment("c1", "base");

    let incoming = json!({
        "reviews": {
            "c1": {"status": "needsReReview", "comment": "incoming"},
            "c2": {"status": "reviewed"}
        },
        "groupBriefs": {
            "g1": {"status": "ready", "summary": "handoff", "focusPoints": ["tests"]}
        },
        "analysisState": {"filterText": "src"},
        "threadState": {"selectedChunkId": "c2"}
    });

    let preview = doc
        .merge_state_value(incoming, "incoming.state.json")
        .unwrap();
    assert_eq!(preview.applied_reviews, 2);
    assert!(!preview.warnings.is_empty());
    assert_eq!(
        preview.merged_state["reviews"]["c1"]["status"],
        json!("needsReReview")
    );
    assert_eq!(
        preview.merged_state["reviews"]["c1"]["comment"],
        json!("incoming")
    );

    let diff = doc
        .state_diff_against_value(preview.merged_state.clone())
        .unwrap();
    assert!(diff.changed_total() >= 4);
    assert!(diff
        .section("reviews")
        .unwrap()
        .changed
        .contains(&"c1".to_owned()));
    assert!(diff
        .section("reviews")
        .unwrap()
        .added
        .contains(&"c2".to_owned()));
}

#[test]
fn split_group_document_and_html_export_are_written() {
    let root = unique_temp_dir("split_html");
    fs::create_dir_all(&root).unwrap();
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    doc.set_status("c1", ReviewStatus::Reviewed);

    let split = doc.split_group_review_document("g1").unwrap();
    assert_eq!(split["groups"][0]["id"], json!("g1"));
    assert_eq!(split["chunks"][0]["id"], json!("c1"));
    assert_eq!(split["analysisState"]["currentGroupId"], json!("g1"));

    let split_path = root.join("g1.diffgr.json");
    let html_path = root.join("review.html");
    doc.write_group_review_document("g1", &split_path).unwrap();
    doc.write_html_report(&html_path).unwrap();
    assert!(fs::read_to_string(split_path).unwrap().contains("\"g1\""));
    let html = fs::read_to_string(html_path).unwrap();
    assert!(html.contains("<!doctype html>"));
    assert!(html.contains("src/a.rs"));

    fs::remove_dir_all(root).ok();
}

#[test]
fn impact_preview_flags_changed_and_new_chunks() {
    let old_doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    let mut new_raw = sample_doc();
    new_raw["chunks"][0]["lines"][1]["text"] = json!("changed");
    new_raw["chunks"].as_array_mut().unwrap().push(json!({
        "id": "c3",
        "filePath": "src/c.rs",
        "old": {"start": 1, "count": 0},
        "new": {"start": 1, "count": 1},
        "lines": [
            {"kind": "add", "text": "brand new", "oldLine": null, "newLine": 1}
        ]
    }));
    new_raw["assignments"]["g1"]
        .as_array_mut()
        .unwrap()
        .push(json!("c3"));
    let new_doc = DiffgrDocument::from_value(new_raw).unwrap();

    let report = new_doc.impact_against(&old_doc);
    assert_eq!(report.changed, 1);
    assert_eq!(report.new_only, 1);
    assert_eq!(
        report
            .groups
            .iter()
            .find(|group| group.id == "g1")
            .unwrap()
            .action,
        "review"
    );
}

#[test]
fn approval_request_changes_and_invalidation_roundtrip() {
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();

    assert!(doc.approve_group("g1", "alice", false).is_err());
    doc.set_status("c1", ReviewStatus::Reviewed);
    doc.approve_group("g1", "alice", false).unwrap();

    let g1 = doc.check_group_approval("g1");
    assert!(g1.approved);
    assert!(g1.valid);
    assert_eq!(g1.reason, "approved");

    let report = doc.check_all_approvals();
    assert!(!report.all_approved);
    assert!(doc
        .approval_report_markdown()
        .contains("DiffGR Approval Report"));

    doc.request_changes_on_group("g1", "bob", "please adjust tests")
        .unwrap();
    let requested = doc.check_group_approval("g1");
    assert!(!requested.approved);
    assert_eq!(requested.reason, "changes_requested");

    doc.set_status("c1", ReviewStatus::Reviewed);
    doc.approve_group("g1", "alice", false).unwrap();
    doc.raw["chunks"][0]["lines"][1]["text"] = json!("fingerprint changed");
    let invalidated = doc.check_group_approval("g1");
    assert!(invalidated.approved);
    assert!(!invalidated.valid);
    assert_eq!(invalidated.reason, "invalidated_fingerprint");

    doc.revoke_group_approval("g1", "alice", "revoked").unwrap();
    let revoked = doc.check_group_approval("g1");
    assert_eq!(revoked.reason, "revoked");
}

#[test]
fn state_merge_uses_approval_decision_precedence() {
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    doc.set_status("c1", ReviewStatus::Reviewed);
    doc.approve_group("g1", "alice", false).unwrap();

    let incoming = json!({
        "groupBriefs": {
            "g1": {
                "approval": {
                    "state": "changesRequested",
                    "approved": false,
                    "decisionAt": "zzzz",
                    "changesRequestedBy": "bob",
                    "comment": "later decision wins"
                }
            }
        }
    });

    let preview = doc.merge_state_value(incoming, "incoming").unwrap();
    assert_eq!(
        preview.merged_state["groupBriefs"]["g1"]["approval"]["state"],
        json!("changesRequested")
    );
    assert_eq!(
        preview.merged_state["groupBriefs"]["g1"]["approval"]["approved"],
        json!(false)
    );
}
