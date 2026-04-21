use diffgr_gui::model::{DiffgrDocument, LineAnchor, ReviewStatus};
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::process;
use std::time::{SystemTime, UNIX_EPOCH};

fn sample_doc() -> Value {
    json!({
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "report sample"},
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
            },
            {
                "id": "c2",
                "filePath": "src/lib.rs",
                "old": {"start": 5, "count": 1},
                "new": {"start": 5, "count": 1},
                "lines": [
                    {"kind": "delete", "text": "old", "oldLine": 5, "newLine": null},
                    {"kind": "add", "text": "new", "oldLine": null, "newLine": 5}
                ]
            },
            {
                "id": "c3",
                "filePath": "README.md",
                "old": {"start": 10, "count": 1},
                "new": {"start": 10, "count": 1},
                "lines": [
                    {"kind": "context", "text": "docs", "oldLine": 10, "newLine": 10}
                ]
            }
        ],
        "assignments": {"g": ["c1", "c2", "c3"]},
        "reviews": {}
    })
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time moves forward")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "diffgr_gui_report_ut_{}_{}_{}",
        label,
        process::id(),
        nanos
    ))
}

#[test]
fn status_counts_and_file_summaries_track_review_progress() {
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    doc.set_status("c1", ReviewStatus::Reviewed);
    doc.set_status("c2", ReviewStatus::NeedsReReview);
    doc.set_status("c3", ReviewStatus::Ignored);
    doc.set_comment("c2", "needs a second look");

    let counts = doc.status_counts();
    assert_eq!(counts.total(), 3);
    assert_eq!(counts.reviewed, 1);
    assert_eq!(counts.needs_re_review, 1);
    assert_eq!(counts.ignored, 1);
    assert_eq!(counts.pending(), 1);
    assert_eq!(counts.tracked(), 2);

    let summaries = doc.file_summaries();
    let rust_file = summaries
        .iter()
        .find(|summary| summary.file_path == "src/lib.rs")
        .unwrap();
    assert_eq!(rust_file.chunks, 2);
    assert_eq!(rust_file.reviewed, 1);
    assert_eq!(rust_file.pending, 1);
    assert_eq!(rust_file.adds, 2);
    assert_eq!(rust_file.deletes, 1);
    assert_eq!(rust_file.comments, 1);
}

#[test]
fn markdown_report_contains_status_file_table_and_comments() {
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    let anchor = LineAnchor {
        line_type: "add".to_owned(),
        old_line: None,
        new_line: Some(2),
    };
    doc.set_status("c1", ReviewStatus::Reviewed);
    doc.set_comment("c1", "ship it");
    doc.set_line_comment("c1", &anchor, "new public API");

    let report = doc.review_markdown_report();
    assert!(report.contains("# DiffGR Review Summary: report sample"));
    assert!(report.contains("- Reviewed: 1"));
    assert!(report.contains("| src/lib.rs |"));
    assert!(report.contains("ship it"));
    assert!(report.contains("new public API"));
}

#[test]
fn write_state_and_report_create_parent_directories() {
    let root = unique_temp_dir("write_parent");
    let state_path = root.join("nested").join("review.state.json");
    let report_path = root.join("nested").join("summary.md");
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    doc.set_status("c1", ReviewStatus::Reviewed);

    doc.write_state(&state_path).unwrap();
    doc.write_review_report(&report_path).unwrap();

    assert!(state_path.exists());
    assert!(report_path.exists());
    assert!(fs::read_to_string(report_path)
        .unwrap()
        .contains("DiffGR Review Summary"));
    fs::remove_dir_all(root).ok();
}

#[test]
fn set_status_for_chunks_changes_only_known_different_chunks() {
    let mut doc = DiffgrDocument::from_value(sample_doc()).unwrap();
    doc.set_status("c1", ReviewStatus::Reviewed);
    let changed = doc.set_status_for_chunks(
        &["c1".to_owned(), "c2".to_owned(), "missing".to_owned()],
        ReviewStatus::Reviewed,
    );
    assert_eq!(changed, 1);
    assert_eq!(doc.status_for("c2"), ReviewStatus::Reviewed);
}
