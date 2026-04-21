use serde_json::Value;
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_diffgrctl"))
}

fn temp_dir(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let dir = std::env::temp_dir().join(format!("diffgr-parity-cli-{name}-{nonce}"));
    fs::create_dir_all(&dir).unwrap();
    dir
}

fn sample_doc(path: &PathBuf) {
    fs::write(
        path,
        r#"{
  "format": "diffgr",
  "version": 1,
  "meta": {"title": "CLI parity sample", "source": {"headSha": "head"}},
  "groups": [{"id": "g-all", "name": "All", "order": 1, "tags": []}],
  "assignments": {"g-all": ["c1"]},
  "chunks": [{
    "id": "c1",
    "filePath": "src/lib.rs",
    "header": "fn demo",
    "old": {"start": 1, "count": 1},
    "new": {"start": 1, "count": 1},
    "lines": [
      {"kind": "delete", "text": "old", "oldLine": 1, "newLine": null},
      {"kind": "add", "text": "new", "oldLine": null, "newLine": 1}
    ],
    "fingerprints": {"stable": "stable-c1"}
  }],
  "reviews": {"c1": {"status": "reviewed"}},
  "groupBriefs": {},
  "analysisState": {},
  "threadState": {},
  "patch": "diff --git a/src/lib.rs b/src/lib.rs\n"
}"#,
    )
    .unwrap();
}

#[test]
fn parity_audit_reports_every_python_script_covered() {
    let output = Command::new(bin())
        .args(["parity-audit", "--json"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["ok"], true);
    assert!(value["scriptCount"].as_u64().unwrap() >= 31);
    assert_eq!(value["scriptCount"], value["coveredCount"]);
}

#[test]
fn python_script_aliases_accept_python_style_options() {
    let dir = temp_dir("aliases");
    let doc = dir.join("review.diffgr.json");
    sample_doc(&doc);

    let view = Command::new(bin())
        .args([
            "view-diffgr",
            doc.to_str().unwrap(),
            "--status",
            "reviewed",
            "--file",
            "src/",
            "--chunk",
            "c1",
            "--json",
        ])
        .output()
        .unwrap();
    assert!(
        view.status.success(),
        "{}",
        String::from_utf8_lossy(&view.stderr)
    );
    let value: Value = serde_json::from_slice(&view.stdout).unwrap();
    assert_eq!(value["chunks"].as_array().unwrap().len(), 1);
    assert_eq!(value["statuses"]["c1"], "reviewed");

    let state_out = dir.join("review.state.json");
    let extract = Command::new(bin())
        .args([
            "extract-diffgr-state",
            "--input",
            doc.to_str().unwrap(),
            "--output",
            state_out.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(
        extract.status.success(),
        "{}",
        String::from_utf8_lossy(&extract.stderr)
    );
    assert!(state_out.exists());

    let bundle = dir.join("bundle.diffgr.json");
    let state = dir.join("bundle.state.json");
    let manifest = dir.join("bundle.manifest.json");
    let export = Command::new(bin())
        .args([
            "export-review-bundle",
            "--input",
            doc.to_str().unwrap(),
            "--bundle-out",
            bundle.to_str().unwrap(),
            "--state-out",
            state.to_str().unwrap(),
            "--manifest-out",
            manifest.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(
        export.status.success(),
        "{}",
        String::from_utf8_lossy(&export.stderr)
    );
    assert!(bundle.exists() && state.exists() && manifest.exists());

    let html = dir.join("report.html");
    let export_html = Command::new(bin())
        .args([
            "export-diffgr-html",
            "--input",
            doc.to_str().unwrap(),
            "--output",
            html.to_str().unwrap(),
            "--state",
            state_out.to_str().unwrap(),
            "--group",
            "g-all",
            "--title",
            "Custom Report",
            "--save-state-url",
            "/api/state",
            "--save-state-label",
            "Store",
            "--impact-old",
            doc.to_str().unwrap(),
            "--impact-state",
            state_out.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(
        export_html.status.success(),
        "{}",
        String::from_utf8_lossy(&export_html.stderr)
    );
    let html_text = fs::read_to_string(&html).unwrap();
    assert!(html_text.contains("Custom Report"));
    assert!(html_text.contains("Store"));
    assert!(html_text.contains("Impact Preview"));

    let _ = fs::remove_dir_all(dir);
}
