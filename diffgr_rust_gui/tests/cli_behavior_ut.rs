mod support;

use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_diffgrctl"))
}

fn write_doc(dir: &Path) -> PathBuf {
    let path = dir.join("review.diffgr.json");
    fs::write(
        &path,
        serde_json::to_string_pretty(&support::rich_doc()).unwrap(),
    )
    .unwrap();
    path
}

fn write_state(dir: &Path) -> PathBuf {
    let path = dir.join("review.state.json");
    fs::write(
        &path,
        serde_json::to_string_pretty(&support::minimal_state()).unwrap(),
    )
    .unwrap();
    path
}

fn json_stdout(output: std::process::Output) -> Value {
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}

#[test]
fn cli_help_succeeds_and_lists_core_commands() {
    let output = Command::new(bin()).arg("--help").output().unwrap();
    assert!(output.status.success());
    let text = String::from_utf8_lossy(&output.stdout);
    assert!(text.contains("generate"));
    assert!(text.contains("view"));
    assert!(text.contains("parity-audit"));
}

#[test]
fn cli_unknown_command_fails_with_help_hint() {
    let output = Command::new(bin()).arg("not-a-command").output().unwrap();
    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("Unknown command"));
    assert!(stderr.contains("--help"));
}

#[test]
fn cli_summarize_json_reports_chunks_and_files() {
    let root = support::temp_dir("cli_summarize");
    let doc = write_doc(&root);
    let output = Command::new(bin())
        .args([
            "summarize-diffgr",
            "--input",
            doc.to_str().unwrap(),
            "--json",
        ])
        .output()
        .unwrap();
    let value = json_stdout(output);
    assert_eq!(value["chunks"], json!(3));
    assert!(value["files"]
        .as_array()
        .unwrap()
        .iter()
        .any(|row| row["filePath"] == json!("README.md")));
    fs::remove_dir_all(root).ok();
}

#[test]
fn cli_summarize_state_json_reports_section_counts() {
    let root = support::temp_dir("cli_state_summary");
    let state = write_state(&root);
    let output = Command::new(bin())
        .args([
            "summarize-diffgr-state",
            "--input",
            state.to_str().unwrap(),
            "--json",
        ])
        .output()
        .unwrap();
    let value = json_stdout(output);
    assert_eq!(value["counts"]["reviews"], json!(2));
    assert!(value["fingerprint"].as_str().unwrap().len() >= 32);
    fs::remove_dir_all(root).ok();
}

#[test]
fn cli_extract_state_can_print_to_stdout() {
    let root = support::temp_dir("cli_extract_stdout");
    let doc = write_doc(&root);
    let output = Command::new(bin())
        .args(["extract-diffgr-state", "--input", doc.to_str().unwrap()])
        .output()
        .unwrap();
    let value = json_stdout(output);
    assert_eq!(value["reviews"]["c-ui-login"]["status"], json!("reviewed"));
    fs::remove_dir_all(root).ok();
}

#[test]
fn cli_apply_state_writes_composed_document() {
    let root = support::temp_dir("cli_apply_state");
    let doc = write_doc(&root);
    let state = write_state(&root);
    let output_path = root.join("composed.diffgr.json");
    let output = Command::new(bin())
        .args([
            "apply-diffgr-state",
            "--input",
            doc.to_str().unwrap(),
            "--state",
            state.to_str().unwrap(),
            "--output",
            output_path.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let composed: Value = serde_json::from_str(&fs::read_to_string(&output_path).unwrap()).unwrap();
    assert_eq!(composed["reviews"]["c-docs"]["status"], json!("ignored"));
    fs::remove_dir_all(root).ok();
}

#[test]
fn cli_diff_state_tokens_only_prints_selection_tokens() {
    let root = support::temp_dir("cli_diff_tokens");
    let base = root.join("base.state.json");
    let incoming = root.join("incoming.state.json");
    fs::write(
        &base,
        serde_json::to_string_pretty(
            &json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}}),
        )
        .unwrap(),
    )
    .unwrap();
    fs::write(
        &incoming,
        serde_json::to_string_pretty(&support::minimal_state()).unwrap(),
    )
    .unwrap();
    let output = Command::new(bin())
        .args([
            "diff-diffgr-state",
            "--base",
            base.to_str().unwrap(),
            "--incoming",
            incoming.to_str().unwrap(),
            "--tokens-only",
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.lines().any(|line| line == "reviews:c-ui-login"));
    fs::remove_dir_all(root).ok();
}

#[test]
fn cli_merge_state_preview_does_not_require_output() {
    let root = support::temp_dir("cli_merge_preview");
    let base = root.join("base.state.json");
    let incoming = write_state(&root);
    fs::write(
        &base,
        serde_json::to_string_pretty(
            &json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}}),
        )
        .unwrap(),
    )
    .unwrap();
    let output = Command::new(bin())
        .args([
            "merge-diffgr-state",
            "--base",
            base.to_str().unwrap(),
            "--input",
            incoming.to_str().unwrap(),
            "--preview",
        ])
        .output()
        .unwrap();
    let value = json_stdout(output);
    assert!(value["applied"].as_u64().unwrap() >= 2);
    fs::remove_dir_all(root).ok();
}

#[test]
fn cli_coverage_json_succeeds_for_fully_assigned_document() {
    let root = support::temp_dir("cli_coverage");
    let doc = write_doc(&root);
    let output = Command::new(bin())
        .args([
            "check-virtual-pr-coverage",
            "--input",
            doc.to_str().unwrap(),
            "--json",
        ])
        .output()
        .unwrap();
    let value = json_stdout(output);
    assert_eq!(value["ok"], json!(true));
    fs::remove_dir_all(root).ok();
}

#[test]
fn cli_check_approval_json_exits_nonzero_when_not_all_approved_but_prints_report() {
    let root = support::temp_dir("cli_check_approval");
    let doc = write_doc(&root);
    let output = Command::new(bin())
        .args([
            "check-virtual-pr-approval",
            "--input",
            doc.to_str().unwrap(),
            "--json",
        ])
        .output()
        .unwrap();
    assert!(!output.status.success());
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["allApproved"], json!(false));
    fs::remove_dir_all(root).ok();
}

#[test]
fn cli_view_app_once_uses_terminal_view_alias() {
    let root = support::temp_dir("cli_view_app_once");
    let doc = write_doc(&root);
    let output = Command::new(bin())
        .args(["view-diffgr-app", doc.to_str().unwrap(), "--once", "--json"])
        .output()
        .unwrap();
    let value = json_stdout(output);
    assert_eq!(value["chunks"].as_array().unwrap().len(), 3);
    fs::remove_dir_all(root).ok();
}

#[test]
fn cli_apply_layout_alias_writes_output_and_preserves_warning_free_layout() {
    let root = support::temp_dir("cli_apply_layout");
    let doc = write_doc(&root);
    let layout = root.join("layout.json");
    let output_path = root.join("layout-applied.diffgr.json");
    fs::write(
        &layout,
        serde_json::to_string_pretty(&json!({
            "groups": [{"id": "g-all", "name": "All", "order": 1}],
            "assignments": {"g-all": ["c-ui-login", "c-api-route", "c-docs"]}
        }))
        .unwrap(),
    )
    .unwrap();
    let output = Command::new(bin())
        .args([
            "apply-diffgr-layout",
            "--input",
            doc.to_str().unwrap(),
            "--layout",
            layout.to_str().unwrap(),
            "--output",
            output_path.to_str().unwrap(),
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let saved: Value = serde_json::from_str(&fs::read_to_string(&output_path).unwrap()).unwrap();
    assert_eq!(saved["groups"].as_array().unwrap().len(), 1);
    fs::remove_dir_all(root).ok();
}
