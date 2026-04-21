use diffgr_gui::ops;
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

fn sample_doc() -> Value {
    ops::build_diffgr_from_diff_text(
        "diff --git a/src/a.rs b/src/a.rs\n--- a/src/a.rs\n+++ b/src/a.rs\n@@ -1,2 +1,2 @@\n fn main() {\n-    println!(\"old\");\n+    println!(\"new\");\ndiff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,1 +1,2 @@\n # Title\n+more\n",
        "Parity sample",
        "main",
        "feature",
        "base-sha",
        "head-sha",
        "merge-base",
        true,
    )
    .expect("sample diff should parse")
}

fn first_chunk_id(doc: &Value) -> String {
    doc["chunks"]
        .as_array()
        .and_then(|chunks| chunks.first())
        .and_then(|chunk| chunk.get("id"))
        .and_then(Value::as_str)
        .unwrap()
        .to_owned()
}

fn temp_dir(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("diffgr-rust-{name}-{nonce}"));
    fs::create_dir_all(&path).unwrap();
    path
}

#[test]
fn generate_extract_apply_state_roundtrip() {
    let doc = sample_doc();
    assert_eq!(doc["chunks"].as_array().unwrap().len(), 2);
    let mut state = ops::extract_review_state(&doc);
    let chunk_id = first_chunk_id(&doc);
    state["reviews"][chunk_id.as_str()] = json!({"status": "reviewed", "comment": "ok"});
    let applied = ops::apply_review_state(&doc, &state).unwrap();
    assert_eq!(applied["reviews"][chunk_id.as_str()]["status"], "reviewed");
}

#[test]
fn apply_layout_replaces_groups_and_assignments() {
    let doc = sample_doc();
    let chunk_id = first_chunk_id(&doc);
    let layout = json!({
        "groups": [
            {"id": "g-rust", "name": "Rust code"},
            {"id": "g-docs", "name": "Docs"}
        ],
        "assignments": {"g-rust": [chunk_id.clone()]},
        "groupBriefs": {"g-rust": {"status": "ready", "summary": "review code"}}
    });
    let (out, warnings) = ops::apply_layout(&doc, &layout).unwrap();
    assert!(warnings.iter().any(|w| w.contains("not assigned")));
    assert_eq!(out["groups"][0]["id"], "g-rust");
    assert_eq!(out["assignments"]["g-rust"][0], chunk_id);
    assert_eq!(out["groupBriefs"]["g-rust"]["summary"], "review code");
}

#[test]
fn slice_patch_renames_group() {
    let doc = sample_doc();
    let patch = json!({"rename": {"g-all": "Renamed all changes"}, "move": []});
    let out = ops::apply_slice_patch(&doc, &patch).unwrap();
    assert_eq!(out["groups"][0]["name"], "Renamed all changes");
}

#[test]
fn state_diff_merge_and_selection_tokens_work() {
    let base = json!({
        "reviews": {"c1": {"status": "unreviewed"}},
        "groupBriefs": {},
        "analysisState": {},
        "threadState": {}
    });
    let incoming = json!({
        "reviews": {"c1": {"status": "reviewed"}, "c2": {"comment": "new"}},
        "groupBriefs": {},
        "analysisState": {},
        "threadState": {}
    });
    let diff = ops::diff_review_states(&base, &incoming).unwrap();
    let tokens = ops::selection_tokens_from_diff(&diff);
    assert!(tokens.iter().any(|token| token == "reviews:c1"));

    let (merged, warnings, applied) =
        ops::merge_review_states(&base, &[("incoming".to_owned(), incoming.clone())]).unwrap();
    assert!(warnings.is_empty());
    assert_eq!(applied, 2);
    assert_eq!(merged["reviews"]["c1"]["status"], "reviewed");

    let (selected, selected_count) =
        ops::apply_review_state_selection(&base, &incoming, &["reviews:c2".to_owned()]).unwrap();
    assert_eq!(selected_count, 1);
    assert_eq!(selected["reviews"]["c2"]["comment"], "new");
}

#[test]
fn split_bundle_verify_html_and_reports_work() {
    let doc = sample_doc();
    let dir = temp_dir("bundle");
    let split = ops::split_document_by_group(&doc, &dir.join("split"), false).unwrap();
    assert!(!split.written.is_empty());

    let bundle_dir = dir.join("bundle");
    ops::export_review_bundle(&doc, &bundle_dir).unwrap();
    let bundle = ops::read_json_file(&bundle_dir.join("bundle.diffgr.json")).unwrap();
    let state = ops::read_json_file(&bundle_dir.join("review.state.json")).unwrap();
    let manifest = ops::read_json_file(&bundle_dir.join("review.manifest.json")).unwrap();
    let verify = ops::verify_review_bundle(&bundle, &state, &manifest, None, false).unwrap();
    assert!(verify.ok, "{:?}", verify.errors);

    let html = ops::build_html_report(&doc, None, None).unwrap();
    assert!(html.contains("DiffGR"));
    assert_eq!(ops::coverage_report(&doc).unwrap()["ok"], true);
    assert!(ops::reviewability_report(&doc).unwrap()["groups"].is_array());

    let _ = fs::remove_dir_all(dir);
}

#[test]
fn rebase_impact_and_approval_work() {
    let doc = sample_doc();
    let chunk_id = first_chunk_id(&doc);
    let mut state = ops::extract_review_state(&doc);
    state["reviews"][chunk_id.as_str()] = json!({"status": "reviewed"});
    let (rebased, summary) = ops::rebase_state(&doc, &doc, &state).unwrap();
    assert_eq!(summary.unmapped_reviews, 0);
    assert_eq!(rebased["reviews"][chunk_id.as_str()]["status"], "reviewed");

    let impact = ops::impact_report(&doc, &doc, None).unwrap();
    assert_eq!(impact["oldChunkCount"], impact["newChunkCount"]);

    let mut reviewed_state = ops::extract_review_state(&doc);
    for chunk in doc["chunks"].as_array().unwrap() {
        let cid = chunk["id"].as_str().unwrap();
        reviewed_state["reviews"][cid] = json!({"status": "reviewed"});
    }
    let reviewed_doc = ops::apply_review_state(&doc, &reviewed_state).unwrap();
    let approved = ops::approve_groups(&reviewed_doc, &[], "tester", true).unwrap();
    assert_eq!(
        ops::approval_report(&approved).unwrap()["allApproved"],
        true
    );
    let changes = ops::request_changes(&approved, &[], "tester", "please update").unwrap();
    assert_eq!(
        ops::approval_report(&changes).unwrap()["allApproved"],
        false
    );
}
