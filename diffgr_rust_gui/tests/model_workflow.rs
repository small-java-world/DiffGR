use diffgr_gui::model::{
    normalize_state_payload, DiffgrDocument, GroupBriefDraft, LineAnchor, ReviewStatus,
};
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::process;
use std::time::{SystemTime, UNIX_EPOCH};

fn sample_doc() -> Value {
    json!({
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "integration workflow"},
        "groups": [{"id": "g", "name": "Group", "order": 1}],
        "chunks": [
            {
                "id": "c1",
                "filePath": "src/lib.rs",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 2},
                "lines": [
                    {"kind": "context", "text": "pub fn a() {}", "oldLine": 1, "newLine": 1},
                    {"kind": "add", "text": "pub fn b() {}", "oldLine": null, "newLine": 2}
                ]
            }
        ],
        "assignments": {"g": ["c1"]},
        "reviews": {}
    })
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time moves forward")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "diffgr_gui_integration_{}_{}_{}",
        label,
        process::id(),
        nanos
    ))
}

#[test]
fn review_state_roundtrips_through_public_api() {
    let root = unique_temp_dir("roundtrip");
    fs::create_dir_all(&root).unwrap();
    let state_path = root.join("review.state.json");

    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    let anchor = LineAnchor {
        line_type: "add".to_owned(),
        old_line: None,
        new_line: Some(2),
    };
    doc.set_status("c1", ReviewStatus::Reviewed);
    doc.set_comment("c1", "ship it");
    doc.set_line_comment("c1", &anchor, "added API is covered");
    doc.write_state(&state_path).unwrap();

    let mut restored = DiffgrDocument::from_value(sample_doc()).unwrap();
    restored.apply_state_file(&state_path).unwrap();
    assert_eq!(restored.status_for("c1"), ReviewStatus::Reviewed);
    assert_eq!(restored.comment_for("c1"), "ship it");
    assert_eq!(
        restored.line_comment_for("c1", &anchor),
        "added API is covered"
    );

    fs::remove_dir_all(root).ok();
}

#[test]
fn group_brief_public_api_keeps_pipe_list_fields() {
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    doc.set_group_brief_from_draft(
        "g",
        &GroupBriefDraft {
            status: "ready".to_owned(),
            summary: "ready for review".to_owned(),
            focus_points: "Windows build | unit tests".to_owned(),
            test_evidence: "cargo test --all-targets".to_owned(),
            ..GroupBriefDraft::default()
        },
    );

    let brief = doc.group_brief_draft("g");
    assert_eq!(brief.status, "ready");
    assert_eq!(brief.focus_points, "Windows build | unit tests");
    assert_eq!(
        doc.extract_state()["groupBriefs"]["g"]["focusPoints"],
        json!(["Windows build", "unit tests"])
    );
}

#[test]
fn state_payload_normalization_requires_state_object_keys() {
    assert!(normalize_state_payload(json!({"reviews": {}})).is_ok());
    assert!(
        normalize_state_payload(json!({"state": {"analysisState": {"filterText": "src"}}})).is_ok()
    );
    assert!(normalize_state_payload(json!({"state": {"reviews": []}})).is_err());
}
