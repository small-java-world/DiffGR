mod support;

use diffgr_gui::ops;
use serde_json::json;
use std::fs;

#[test]
fn summarize_document_reports_status_metrics_files_and_warnings() {
    let mut doc = support::rich_doc();
    doc["assignments"]["ghost"] = json!(["missing-chunk"]);
    let summary = ops::summarize_document(&doc);

    assert_eq!(summary["title"], json!("UT rich fixture"));
    assert_eq!(summary["groups"], json!(3));
    assert_eq!(summary["chunks"], json!(3));
    assert_eq!(summary["status"]["reviewed"], json!(1));
    assert_eq!(summary["status"]["needsReReview"], json!(1));
    assert_eq!(summary["metrics"]["tracked"], json!(3));
    assert!(summary["files"]
        .as_array()
        .unwrap()
        .iter()
        .any(|file| file["filePath"].as_str() == Some("src/api/routes.rs")));
    assert!(!summary["warnings"].as_array().unwrap().is_empty());
}

#[test]
fn coverage_report_with_limits_detects_duplicates_unknowns_and_prompt() {
    let mut doc = support::rich_doc();
    doc["assignments"]["g-ui"] = json!(["c-ui-login", "c-docs", "missing"]);
    doc["assignments"]["g-api"] = json!(["c-docs"]);
    doc["assignments"]["ghost"] = json!(["c-api-route"]);

    let report = ops::coverage_report_with_limits(&doc, 1, 2).unwrap();
    assert_eq!(report["ok"], json!(false));
    assert!(report["duplicated"]
        .as_array()
        .unwrap()
        .iter()
        .any(|row| row["chunkId"].as_str() == Some("c-docs")));
    assert!(report["unknownGroups"]
        .as_array()
        .unwrap()
        .contains(&json!("ghost")));
    assert!(report["unknownChunks"]
        .as_object()
        .unwrap()
        .contains_key("missing"));
    assert!(report["prompt"]
        .as_str()
        .unwrap()
        .contains("DiffGR 仮想PR網羅チェック"));
}

#[test]
fn reviewability_report_marks_large_hotspots() {
    let mut doc = support::rich_doc();
    let lines = (0..600)
        .map(|idx| json!({"kind": "add", "text": format!("line {idx}"), "oldLine": null, "newLine": idx + 1}))
        .collect::<Vec<_>>();
    doc["chunks"].as_array_mut().unwrap().push(json!({
        "id": "c-hot",
        "filePath": "src/hot.rs",
        "old": {"start": 1, "count": 0},
        "new": {"start": 1, "count": 600},
        "lines": lines
    }));
    doc["assignments"]["g-ui"]
        .as_array_mut()
        .unwrap()
        .push(json!("c-hot"));

    let report = ops::reviewability_report(&doc).unwrap();
    let g_ui = report["groups"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["groupId"].as_str() == Some("g-ui"))
        .unwrap();
    assert_eq!(g_ui["hotspots"].as_array().unwrap().len(), 1);
    assert_ne!(g_ui["level"], json!("easy"));
}

#[test]
fn html_report_options_filter_group_escape_title_add_save_widget_and_impact() {
    let doc = support::rich_doc();
    let mut old = doc.clone();
    old["chunks"][0]["lines"][1]["text"] = json!("old spinner");
    let html = ops::build_html_report_with_options(
        &doc,
        Some(&support::minimal_state()),
        Some(&old),
        Some(&support::minimal_state()),
        Some("g-ui"),
        Some("Custom <Report>"),
        Some("/api/state"),
        Some("Save <State>"),
    )
    .unwrap();

    assert!(html.contains("Custom &lt;Report&gt;"));
    assert!(html.contains("Save &lt;State&gt;"));
    assert!(html.contains("window.diffgrState"));
    assert!(html.contains("Impact Preview"));
    assert!(html.contains("src/ui/login.rs"));
    assert!(!html.contains("src/api/routes.rs"));
}

#[test]
fn html_report_requires_impact_old_when_impact_state_is_set() {
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
fn export_review_bundle_to_paths_and_verify_success() {
    let root = support::temp_dir("bundle_success");
    let bundle_path = root.join("bundle.diffgr.json");
    let state_path = root.join("review.state.json");
    let manifest_path = root.join("review.manifest.json");

    let summary = ops::export_review_bundle_to_paths(
        &support::rich_doc(),
        &bundle_path,
        &state_path,
        &manifest_path,
    )
    .unwrap();
    assert_eq!(summary.written.len(), 3);
    assert!(bundle_path.exists() && state_path.exists() && manifest_path.exists());

    let bundle = support::read_json(&bundle_path);
    let state = support::read_json(&state_path);
    let manifest = support::read_json(&manifest_path);
    assert_eq!(bundle["reviews"], json!({}));
    assert!(bundle.get("groupBriefs").is_none());
    let report =
        ops::verify_review_bundle(&bundle, &state, &manifest, Some("head-sha"), false).unwrap();
    assert!(report.ok, "{:?}", report.errors);
    assert_eq!(report.computed_manifest["chunkCount"], json!(3));

    fs::remove_dir_all(root).ok();
}

#[test]
fn verify_review_bundle_detects_manifest_tampering_and_mutable_state() {
    let doc = support::rich_doc();
    let state = ops::extract_review_state(&doc);
    let mut bundle = doc.clone();
    bundle["reviews"] = json!({"c-ui-login": {"status": "reviewed"}});
    let mut manifest = ops::build_review_bundle_manifest(&bundle, &state);
    manifest["chunkCount"] = json!(999);

    let report =
        ops::verify_review_bundle(&bundle, &state, &manifest, Some("wrong-head"), false).unwrap();
    assert!(!report.ok);
    assert!(report
        .errors
        .iter()
        .any(|err| err.contains("Manifest mismatch")));
    assert!(report
        .errors
        .iter()
        .any(|err| err.contains("Expected head")));
    assert!(report
        .errors
        .iter()
        .any(|err| err.contains("empty reviews")));
    assert!(report
        .errors
        .iter()
        .any(|err| err.contains("mutable state key")));
}

#[test]
fn verify_review_bundle_warns_about_state_topology_mismatches() {
    let doc = support::rich_doc();
    let bundle = ops::apply_review_state(
        &doc,
        &json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}}),
    )
    .unwrap();
    let mut clean_bundle = bundle.clone();
    clean_bundle.as_object_mut().unwrap().remove("groupBriefs");
    clean_bundle
        .as_object_mut()
        .unwrap()
        .remove("analysisState");
    clean_bundle.as_object_mut().unwrap().remove("threadState");
    let state = json!({
        "reviews": {"missing-chunk": {"status": "reviewed"}},
        "groupBriefs": {"missing-group": {"summary": "x"}},
        "analysisState": {"currentGroupId": "missing-group", "selectedChunkId": "missing-chunk"},
        "threadState": {"missing-chunk": {}, "__files": {"missing.rs": {}}}
    });
    let manifest = ops::build_review_bundle_manifest(&clean_bundle, &state);
    let report = ops::verify_review_bundle(&clean_bundle, &state, &manifest, None, false).unwrap();
    assert!(report.ok);
    assert!(report.warnings.iter().any(|w| w.contains("missing-chunk")));
    assert!(report.warnings.iter().any(|w| w.contains("missing-group")));
    assert!(report.warnings.iter().any(|w| w.contains("missing.rs")));
}

#[test]
fn split_and_merge_group_reviews_roundtrip_with_strict_unknown_detection() {
    let root = support::temp_dir("split_merge");
    let doc = support::rich_doc();
    let summary = ops::split_document_by_group(&doc, &root, true).unwrap();
    assert!(summary
        .written
        .iter()
        .any(|path| path.file_name().unwrap().to_string_lossy() == "manifest.json"));

    let group_doc_path = summary
        .written
        .iter()
        .find(|path| path.file_name().unwrap().to_string_lossy().contains("g-ui"))
        .unwrap();
    let mut review_doc = support::read_json(group_doc_path);
    review_doc["reviews"]["c-ui-login"]["comment"] = json!("merged comment");

    let (merged, warnings, applied) = ops::merge_group_review_documents(
        &doc,
        &[("g-ui".to_owned(), review_doc.clone())],
        false,
        true,
    )
    .unwrap();
    assert!(warnings.iter().any(|w| w.contains("conflict")));
    assert!(applied > 0);
    assert_eq!(
        merged["reviews"]["c-ui-login"]["comment"],
        json!("merged comment")
    );

    review_doc["reviews"]["ghost-chunk"] = json!({"status": "reviewed"});
    assert!(ops::merge_group_review_documents(
        &doc,
        &[("bad".to_owned(), review_doc)],
        false,
        true
    )
    .is_err());

    fs::remove_dir_all(root).ok();
}
