use serde_json::Value;
use std::collections::BTreeSet;

fn diffgrctl_source() -> &'static str {
    include_str!("../src/bin/diffgrctl.rs")
}
fn usage_text() -> String {
    let src = diffgrctl_source();
    src.split("fn print_usage()")
        .nth(1)
        .unwrap_or(src)
        .to_owned()
}
fn scenarios() -> Value {
    serde_json::from_str(include_str!("../NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json")).unwrap()
}
fn manifest() -> Value {
    serde_json::from_str(include_str!("../PYTHON_PARITY_MANIFEST.json")).unwrap()
}

fn assert_option_present(option: &str) {
    assert!(
        diffgrctl_source().contains(option),
        "diffgrctl source should contain Python option {option}"
    );
}
fn assert_command_present(command: &str) {
    assert!(
        diffgrctl_source().contains(command),
        "diffgrctl source should expose command/alias {command}"
    );
}

#[test]
fn cli_surface_contains_option_all() {
    assert_option_present("--all");
}

#[test]
fn cli_surface_contains_option_approved_by() {
    assert_option_present("--approved-by");
}

#[test]
fn cli_surface_contains_option_base() {
    assert_option_present("--base");
}

#[test]
fn cli_surface_contains_option_bundle() {
    assert_option_present("--bundle");
}

#[test]
fn cli_surface_contains_option_bundle_out() {
    assert_option_present("--bundle-out");
}

#[test]
fn cli_surface_contains_option_chunk() {
    assert_option_present("--chunk");
}

#[test]
fn cli_surface_contains_option_clear_base_reviews() {
    assert_option_present("--clear-base-reviews");
}

#[test]
fn cli_surface_contains_option_comment() {
    assert_option_present("--comment");
}

#[test]
fn cli_surface_contains_option_config() {
    assert_option_present("--config");
}

#[test]
fn cli_surface_contains_option_context_lines() {
    assert_option_present("--context-lines");
}

#[test]
fn cli_surface_contains_option_copy_prompt() {
    assert_option_present("--copy-prompt");
}

#[test]
fn cli_surface_contains_option_expected_head() {
    assert_option_present("--expected-head");
}

#[test]
fn cli_surface_contains_option_fail_on_truncate() {
    assert_option_present("--fail-on-truncate");
}

#[test]
fn cli_surface_contains_option_feature() {
    assert_option_present("--feature");
}

#[test]
fn cli_surface_contains_option_file() {
    assert_option_present("--file");
}

#[test]
fn cli_surface_contains_option_group() {
    assert_option_present("--group");
}

#[test]
fn cli_surface_contains_option_grouping() {
    assert_option_present("--grouping");
}

#[test]
fn cli_surface_contains_option_history_actor() {
    assert_option_present("--history-actor");
}

#[test]
fn cli_surface_contains_option_history_label() {
    assert_option_present("--history-label");
}

#[test]
fn cli_surface_contains_option_history_max_entries() {
    assert_option_present("--history-max-entries");
}

#[test]
fn cli_surface_contains_option_history_max_ids_per_group() {
    assert_option_present("--history-max-ids-per-group");
}

#[test]
fn cli_surface_contains_option_host() {
    assert_option_present("--host");
}

#[test]
fn cli_surface_contains_option_impact_grouping() {
    assert_option_present("--impact-grouping");
}

#[test]
fn cli_surface_contains_option_impact_new() {
    assert_option_present("--impact-new");
}

#[test]
fn cli_surface_contains_option_impact_old() {
    assert_option_present("--impact-old");
}

#[test]
fn cli_surface_contains_option_impact_plan() {
    assert_option_present("--impact-plan");
}

#[test]
fn cli_surface_contains_option_impact_state() {
    assert_option_present("--impact-state");
}

#[test]
fn cli_surface_contains_option_include_empty() {
    assert_option_present("--include-empty");
}

#[test]
fn cli_surface_contains_option_input() {
    assert_option_present("--input");
}

#[test]
fn cli_surface_contains_option_input_glob() {
    assert_option_present("--input-glob");
}

#[test]
fn cli_surface_contains_option_interactive() {
    assert_option_present("--interactive");
}

#[test]
fn cli_surface_contains_option_json() {
    assert_option_present("--json");
}

#[test]
fn cli_surface_contains_option_json_summary() {
    assert_option_present("--json-summary");
}

#[test]
fn cli_surface_contains_option_keep_new_groups() {
    assert_option_present("--keep-new-groups");
}

#[test]
fn cli_surface_contains_option_layout() {
    assert_option_present("--layout");
}

#[test]
fn cli_surface_contains_option_manifest() {
    assert_option_present("--manifest");
}

#[test]
fn cli_surface_contains_option_manifest_out() {
    assert_option_present("--manifest-out");
}

#[test]
fn cli_surface_contains_option_max_chunks_per_group() {
    assert_option_present("--max-chunks-per-group");
}

#[test]
fn cli_surface_contains_option_max_commits() {
    assert_option_present("--max-commits");
}

#[test]
fn cli_surface_contains_option_max_items() {
    assert_option_present("--max-items");
}

#[test]
fn cli_surface_contains_option_max_lines() {
    assert_option_present("--max-lines");
}

#[test]
fn cli_surface_contains_option_max_problem_chunks() {
    assert_option_present("--max-problem-chunks");
}

#[test]
fn cli_surface_contains_option_name_style() {
    assert_option_present("--name-style");
}

#[test]
fn cli_surface_contains_option_new() {
    assert_option_present("--new");
}

#[test]
fn cli_surface_contains_option_no_copy_prompt() {
    assert_option_present("--no-copy-prompt");
}

#[test]
fn cli_surface_contains_option_no_history() {
    assert_option_present("--no-history");
}

#[test]
fn cli_surface_contains_option_no_line_comments() {
    assert_option_present("--no-line-comments");
}

#[test]
fn cli_surface_contains_option_no_patch() {
    assert_option_present("--no-patch");
}

#[test]
fn cli_surface_contains_option_no_prompt() {
    assert_option_present("--no-prompt");
}

#[test]
fn cli_surface_contains_option_no_split() {
    assert_option_present("--no-split");
}

#[test]
fn cli_surface_contains_option_old() {
    assert_option_present("--old");
}

#[test]
fn cli_surface_contains_option_once() {
    assert_option_present("--once");
}

#[test]
fn cli_surface_contains_option_open() {
    assert_option_present("--open");
}

#[test]
fn cli_surface_contains_option_other() {
    assert_option_present("--other");
}

#[test]
fn cli_surface_contains_option_output() {
    assert_option_present("--output");
}

#[test]
fn cli_surface_contains_option_output_dir() {
    assert_option_present("--output-dir");
}

#[test]
fn cli_surface_contains_option_page_size() {
    assert_option_present("--page-size");
}

#[test]
fn cli_surface_contains_option_patch() {
    assert_option_present("--patch");
}

#[test]
fn cli_surface_contains_option_port() {
    assert_option_present("--port");
}

#[test]
fn cli_surface_contains_option_preview() {
    assert_option_present("--preview");
}

#[test]
fn cli_surface_contains_option_prompt() {
    assert_option_present("--prompt");
}

#[test]
fn cli_surface_contains_option_repo() {
    assert_option_present("--repo");
}

#[test]
fn cli_surface_contains_option_requested_by() {
    assert_option_present("--requested-by");
}

#[test]
fn cli_surface_contains_option_require_approvals() {
    assert_option_present("--require-approvals");
}

#[test]
fn cli_surface_contains_option_save_state_label() {
    assert_option_present("--save-state-label");
}

#[test]
fn cli_surface_contains_option_save_state_url() {
    assert_option_present("--save-state-url");
}

#[test]
fn cli_surface_contains_option_schema() {
    assert_option_present("--schema");
}

#[test]
fn cli_surface_contains_option_select() {
    assert_option_present("--select");
}

#[test]
fn cli_surface_contains_option_show_patch() {
    assert_option_present("--show-patch");
}

#[test]
fn cli_surface_contains_option_similarity_threshold() {
    assert_option_present("--similarity-threshold");
}

#[test]
fn cli_surface_contains_option_state() {
    assert_option_present("--state");
}

#[test]
fn cli_surface_contains_option_state_out() {
    assert_option_present("--state-out");
}

#[test]
fn cli_surface_contains_option_status() {
    assert_option_present("--status");
}

#[test]
fn cli_surface_contains_option_strict() {
    assert_option_present("--strict");
}

#[test]
fn cli_surface_contains_option_strict_full_check() {
    assert_option_present("--strict-full-check");
}

#[test]
fn cli_surface_contains_option_timeout() {
    assert_option_present("--timeout");
}

#[test]
fn cli_surface_contains_option_title() {
    assert_option_present("--title");
}

#[test]
fn cli_surface_contains_option_tokens_only() {
    assert_option_present("--tokens-only");
}

#[test]
fn cli_surface_contains_option_ui() {
    assert_option_present("--ui");
}

#[test]
fn cli_surface_contains_option_write_prompt() {
    assert_option_present("--write-prompt");
}

#[test]
fn cli_surface_exposes_command_generate_diffgr() {
    assert_command_present("generate-diffgr");
    assert_command_present("generate_diffgr");
}

#[test]
fn cli_surface_exposes_command_autoslice_diffgr() {
    assert_command_present("autoslice-diffgr");
    assert_command_present("autoslice_diffgr");
}

#[test]
fn cli_surface_exposes_command_refine_slices() {
    assert_command_present("refine-slices");
    assert_command_present("refine_slices");
}

#[test]
fn cli_surface_exposes_command_prepare_review() {
    assert_command_present("prepare-review");
    assert_command_present("prepare_review");
}

#[test]
fn cli_surface_exposes_command_run_agent_cli() {
    assert_command_present("run-agent-cli");
    assert_command_present("run_agent_cli");
}

#[test]
fn cli_surface_exposes_command_apply_slice_patch() {
    assert_command_present("apply-slice-patch");
    assert_command_present("apply_slice_patch");
}

#[test]
fn cli_surface_exposes_command_apply_diffgr_layout() {
    assert_command_present("apply-diffgr-layout");
    assert_command_present("apply_diffgr_layout");
}

#[test]
fn cli_surface_exposes_command_view_diffgr() {
    assert_command_present("view-diffgr");
    assert_command_present("view_diffgr");
}

#[test]
fn cli_surface_exposes_command_view_diffgr_app() {
    assert_command_present("view-diffgr-app");
    assert_command_present("view_diffgr_app");
}

#[test]
fn cli_surface_exposes_command_export_diffgr_html() {
    assert_command_present("export-diffgr-html");
    assert_command_present("export_diffgr_html");
}

#[test]
fn cli_surface_exposes_command_serve_diffgr_report() {
    assert_command_present("serve-diffgr-report");
    assert_command_present("serve_diffgr_report");
}

#[test]
fn cli_surface_exposes_command_extract_diffgr_state() {
    assert_command_present("extract-diffgr-state");
    assert_command_present("extract_diffgr_state");
}

#[test]
fn cli_surface_exposes_command_apply_diffgr_state() {
    assert_command_present("apply-diffgr-state");
    assert_command_present("apply_diffgr_state");
}

#[test]
fn cli_surface_exposes_command_diff_diffgr_state() {
    assert_command_present("diff-diffgr-state");
    assert_command_present("diff_diffgr_state");
}

#[test]
fn cli_surface_exposes_command_merge_diffgr_state() {
    assert_command_present("merge-diffgr-state");
    assert_command_present("merge_diffgr_state");
}

#[test]
fn cli_surface_exposes_command_apply_diffgr_state_diff() {
    assert_command_present("apply-diffgr-state-diff");
    assert_command_present("apply_diffgr_state_diff");
}

#[test]
fn cli_surface_exposes_command_split_group_reviews() {
    assert_command_present("split-group-reviews");
    assert_command_present("split_group_reviews");
}

#[test]
fn cli_surface_exposes_command_merge_group_reviews() {
    assert_command_present("merge-group-reviews");
    assert_command_present("merge_group_reviews");
}

#[test]
fn cli_surface_exposes_command_impact_report() {
    assert_command_present("impact-report");
    assert_command_present("impact_report");
}

#[test]
fn cli_surface_exposes_command_preview_rebased_merge() {
    assert_command_present("preview-rebased-merge");
    assert_command_present("preview_rebased_merge");
}

#[test]
fn cli_surface_exposes_command_rebase_diffgr_state() {
    assert_command_present("rebase-diffgr-state");
    assert_command_present("rebase_diffgr_state");
}

#[test]
fn cli_surface_exposes_command_rebase_reviews() {
    assert_command_present("rebase-reviews");
    assert_command_present("rebase_reviews");
}

#[test]
fn cli_surface_exposes_command_export_review_bundle() {
    assert_command_present("export-review-bundle");
    assert_command_present("export_review_bundle");
}

#[test]
fn cli_surface_exposes_command_verify_review_bundle() {
    assert_command_present("verify-review-bundle");
    assert_command_present("verify_review_bundle");
}

#[test]
fn cli_surface_exposes_command_approve_virtual_pr() {
    assert_command_present("approve-virtual-pr");
    assert_command_present("approve_virtual_pr");
}

#[test]
fn cli_surface_exposes_command_request_changes() {
    assert_command_present("request-changes");
    assert_command_present("request_changes");
}

#[test]
fn cli_surface_exposes_command_check_virtual_pr_approval() {
    assert_command_present("check-virtual-pr-approval");
    assert_command_present("check_virtual_pr_approval");
}

#[test]
fn cli_surface_exposes_command_check_virtual_pr_coverage() {
    assert_command_present("check-virtual-pr-coverage");
    assert_command_present("check_virtual_pr_coverage");
}

#[test]
fn cli_surface_exposes_command_summarize_diffgr() {
    assert_command_present("summarize-diffgr");
    assert_command_present("summarize_diffgr");
}

#[test]
fn cli_surface_exposes_command_summarize_diffgr_state() {
    assert_command_present("summarize-diffgr-state");
    assert_command_present("summarize_diffgr_state");
}

#[test]
fn cli_surface_exposes_command_summarize_reviewability() {
    assert_command_present("summarize-reviewability");
    assert_command_present("summarize_reviewability");
}

#[test]
fn cli_surface_usage_lists_parity_audit_and_aliases() {
    let usage = usage_text();
    assert!(usage.contains("parity-audit"));
    assert!(usage.contains("Python-compatible aliases"));
    assert!(usage.contains("generate-diffgr"));
}

#[test]
fn cli_surface_all_manifest_options_are_unique() {
    let manifest = manifest();
    let mut seen = BTreeSet::new();
    for entry in manifest["entries"].as_array().unwrap() {
        for arg in entry["arguments"].as_array().unwrap() {
            for name in arg["names"].as_array().unwrap() {
                let Some(name) = name.as_str() else {
                    continue;
                };
                if name.starts_with("--") {
                    seen.insert(name.to_owned());
                }
            }
        }
    }
    assert_eq!(seen.len(), 80);
}

#[test]
fn cli_surface_match_arm_has_underscore_and_kebab_aliases() {
    let src = diffgrctl_source();
    for scenario in scenarios()["scenarios"].as_array().unwrap() {
        let stem = scenario["script"].as_str().unwrap();
        let native = scenario["nativeCommand"].as_str().unwrap();
        assert!(src.contains(stem), "missing underscore alias {stem}");
        assert!(src.contains(native), "missing kebab command {native}");
    }
}

#[test]
fn cli_surface_rebase_options_are_centralized() {
    let src = diffgrctl_source();
    assert!(src.contains("fn rebase_options"));
    assert!(src.contains("--keep-new-groups"));
    assert!(src.contains("--no-line-comments"));
    assert!(src.contains("--similarity-threshold"));
}

#[test]
fn cli_surface_html_options_require_impact_pairing() {
    let src = diffgrctl_source();
    assert!(src.contains("--impact-old and --impact-state must be provided together"));
    assert!(src.contains("--save-state-url"));
    assert!(src.contains("--save-state-label"));
}

#[test]
fn cli_surface_view_app_keeps_noninteractive_path() {
    let src = diffgrctl_source();
    assert!(src.contains("view-diffgr-app"));
    assert!(src.contains("--once"));
    assert!(src.contains("cmd_view_app"));
}

#[test]
fn cli_surface_run_agent_mentions_timeout_schema_prompt() {
    let src = diffgrctl_source();
    assert!(src.contains("--timeout"));
    assert!(src.contains("--schema"));
    assert!(src.contains("--prompt"));
    assert!(src.contains("run-agent-cli"));
}

#[test]
fn cli_surface_approval_commands_have_ci_friendly_names() {
    let src = diffgrctl_source();
    for name in [
        "approve-virtual-pr",
        "request-changes",
        "check-virtual-pr-approval",
        "check-virtual-pr-coverage",
    ] {
        assert!(src.contains(name));
    }
}

#[test]
fn cli_surface_bundle_commands_have_compat_names() {
    let src = diffgrctl_source();
    for name in [
        "export-review-bundle",
        "verify-review-bundle",
        "--bundle-out",
        "--state-out",
        "--manifest-out",
    ] {
        assert!(src.contains(name));
    }
}

#[test]
fn cli_surface_usage_has_no_python_required_claim() {
    let usage = usage_text().to_lowercase();
    assert!(usage.contains("rust/cargo"));
    assert!(!usage.contains("requires python"));
}
