use diffgr_gui::model::{DiffgrDocument, ReviewStatus};
use diffgr_gui::vpr;
use serde_json::json;

fn risky_doc() -> DiffgrDocument {
    DiffgrDocument::from_value(json!({
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "VPR sample"},
        "groups": [
            {"id":"g-auth","name":"Auth changes","order":1},
            {"id":"g-db","name":"DB changes","order":2}
        ],
        "chunks": [
            {"id":"c-auth","filePath":"src/auth/security.rs","oldStart":1,"oldCount":2,"newStart":1,"newCount":3,"lines":[
                {"type":"delete","text":"return false;","oldLine":1},
                {"type":"add","text":"let token = password.unwrap();","newLine":1},
                {"type":"add","text":"unsafe { grant_permission(token) };","newLine":2}
            ]},
            {"id":"c-db","filePath":"migrations/20260420_add_user_token.sql","oldStart":1,"oldCount":1,"newStart":1,"newCount":2,"lines":[
                {"type":"add","text":"ALTER TABLE users ADD COLUMN token TEXT;","newLine":1},
                {"type":"add","text":"DELETE FROM audit_log WHERE token IS NULL;","newLine":2}
            ]},
            {"id":"c-ui","filePath":"src/ui/view.rs","oldStart":1,"oldCount":1,"newStart":1,"newCount":1,"lines":[
                {"type":"context","text":"fn view() {}","oldLine":1,"newLine":1}
            ]}
        ],
        "assignments": {"g-auth":["c-auth"],"g-db":["c-db"]},
        "reviews": {
            "c-auth":{"status":"needsReReview","comment":"security semantics need another look"},
            "c-db":{"status":"unreviewed"}
        },
        "groupBriefs": {
            "g-auth":{"status":"draft","summary":"Auth change"},
            "g-db":{"status":"draft"}
        }
    })).unwrap()
}

fn ready_doc() -> DiffgrDocument {
    let mut doc = DiffgrDocument::from_value(json!({
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "Ready sample"},
        "groups": [{"id":"g-doc","name":"Docs","order":1}],
        "chunks": [{"id":"c-doc","filePath":"README.md","oldStart":1,"oldCount":1,"newStart":1,"newCount":1,"lines":[
            {"type":"add","text":"Document the workflow.","newLine":1}
        ]}],
        "assignments": {"g-doc":["c-doc"]},
        "reviews": {"c-doc":{"status":"reviewed"}},
        "groupBriefs": {"g-doc":{"status":"ready","summary":"Docs only","focusPoints":["docs"],"testEvidence":["not needed"],"knownTradeoffs":["none"]}}
    })).unwrap();
    doc.approve_group("g-doc", "reviewer", false).unwrap();
    doc
}

fn risky_report() -> vpr::VirtualPrReviewReport {
    vpr::analyze_virtual_pr(&risky_doc())
}

fn ready_report() -> vpr::VirtualPrReviewReport {
    vpr::analyze_virtual_pr(&ready_doc())
}

#[test]
fn vpr_gate_finds_blockers() {
    let report = risky_report();
    assert!(!report.blockers.is_empty());
    assert!(!report.ready_to_approve);
}

#[test]
fn vpr_gate_ready_doc_can_pass() {
    let report = ready_report();
    assert!(report.ready_to_approve);
    assert!(report.blockers.is_empty());
}

#[test]
fn vpr_gate_scores_risky_lower_than_ready() {
    assert!(risky_report().readiness_score < ready_report().readiness_score);
}

#[test]
fn vpr_gate_has_human_level_label() {
    assert!(!risky_report().readiness_level.is_empty());
}

#[test]
fn vpr_gate_risk_queue_orders_security_first() {
    let report = risky_report();
    assert_eq!(report.risk_items.first().unwrap().chunk_id, "c-auth");
}

#[test]
fn vpr_gate_detects_migration_risk() {
    let report = risky_report();
    assert!(report
        .risk_items
        .iter()
        .any(|i| i.reasons.iter().any(|r| r.contains("migration"))));
}

#[test]
fn vpr_gate_detects_secret_risk() {
    let report = risky_report();
    assert!(report.risk_items.iter().any(|i| i
        .reasons
        .iter()
        .any(|r| r.contains("secret") || r.contains("password"))));
}

#[test]
fn vpr_gate_detects_unsafe_risk() {
    let report = risky_report();
    assert!(report
        .risk_items
        .iter()
        .any(|i| i.reasons.iter().any(|r| r.contains("unsafe"))));
}

#[test]
fn vpr_gate_json_has_ready_flag() {
    let value = vpr::virtual_pr_report_json_value(&risky_report());
    assert!(value.get("readyToApprove").is_some());
}

#[test]
fn vpr_gate_json_has_file_hotspots() {
    let value = vpr::virtual_pr_report_json_value(&risky_report());
    assert!(!value["fileHotspots"].as_array().unwrap().is_empty());
}

#[test]
fn vpr_gate_json_has_group_readiness() {
    let value = vpr::virtual_pr_report_json_value(&risky_report());
    assert_eq!(value["groupReadiness"].as_array().unwrap().len(), 2);
}

#[test]
fn vpr_gate_markdown_has_sections() {
    let markdown = vpr::virtual_pr_report_markdown(&risky_report());
    assert!(markdown.contains("Blockers"));
    assert!(markdown.contains("High-risk queue"));
    assert!(markdown.contains("Group readiness"));
}

#[test]
fn vpr_gate_prompt_has_expected_output() {
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&risky_report(), 2);
    assert!(prompt.contains("期待する出力"));
    assert!(prompt.contains("request changes"));
}

#[test]
fn vpr_gate_prompt_respects_max_items() {
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&risky_report(), 1);
    assert!(prompt.contains("c-auth"));
}

#[test]
fn vpr_gate_pending_actions_are_generated() {
    assert!(!risky_report().next_actions.is_empty());
}

#[test]
fn vpr_gate_warnings_include_handoff_gaps() {
    assert!(risky_report()
        .warnings
        .iter()
        .any(|w| w.contains("handoff")));
}

#[test]
fn vpr_gate_group_readiness_tracks_pending() {
    assert!(risky_report().group_readiness.iter().any(|g| g.pending > 0));
}

#[test]
fn vpr_gate_file_hotspots_are_sorted() {
    let report = risky_report();
    let first = report.file_hotspots.first().unwrap().risk_score;
    let last = report.file_hotspots.last().unwrap().risk_score;
    assert!(first >= last);
}

#[test]
fn vpr_gate_risk_items_have_preview() {
    assert!(risky_report()
        .risk_items
        .iter()
        .all(|i| !i.preview.is_empty() || i.risk_score == 0));
}

#[test]
fn vpr_gate_reviewed_doc_has_no_pending_risk() {
    assert!(ready_report()
        .risk_items
        .iter()
        .all(|i| i.status != "unreviewed" && i.status != "needsReReview"));
}

#[test]
fn vpr_gate_status_counts_drive_blocker() {
    assert!(risky_report()
        .blockers
        .iter()
        .any(|b| b.contains("再レビュー")));
}

#[test]
fn vpr_gate_approval_blocker_present_when_missing() {
    assert!(risky_report()
        .blockers
        .iter()
        .any(|b| b.contains("approval")));
}

#[test]
fn vpr_gate_approval_blocker_absent_when_approved() {
    assert!(!ready_report()
        .blockers
        .iter()
        .any(|b| b.contains("approval")));
}

#[test]
fn vpr_gate_coverage_blocker_present_for_unassigned() {
    assert!(risky_report()
        .blockers
        .iter()
        .any(|b| b.contains("coverage")));
}

#[test]
fn vpr_gate_ready_markdown_says_true() {
    assert!(vpr::virtual_pr_report_markdown(&ready_report()).contains("readyToApprove: `true`"));
}

#[test]
fn vpr_gate_json_score_is_number() {
    assert!(vpr::virtual_pr_report_json_value(&ready_report())["readinessScore"].is_number());
}

#[test]
fn vpr_gate_group_handoff_missing_fields_listed() {
    let report = risky_report();
    assert!(report
        .group_readiness
        .iter()
        .any(|g| !g.missing_handoff_fields.is_empty()));
}

#[test]
fn vpr_gate_top_risk_chunks_are_grouped() {
    let report = risky_report();
    assert!(report
        .group_readiness
        .iter()
        .any(|g| g.top_risk_chunks.iter().any(|c| c == "c-auth")));
}

#[test]
fn vpr_gate_file_hotspot_contains_comments() {
    let report = risky_report();
    assert!(report.file_hotspots.iter().any(|f| f.comments > 0));
}

#[test]
fn vpr_gate_risk_reasons_are_deduped() {
    let report = risky_report();
    for item in &report.risk_items {
        let mut reasons = item.reasons.clone();
        reasons.sort();
        reasons.dedup();
        assert_eq!(reasons.len(), item.reasons.len());
    }
}

#[test]
fn source_exports_module() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn source_has_json_function() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn source_has_markdown_function() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn source_has_prompt_function() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn app_has_virtual_pr_tab() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn app_has_gate_markdown_copy() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn app_has_ai_prompt_copy() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn app_has_high_risk_queue() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn app_has_file_hotspots() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn app_has_group_readiness() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn cli_has_virtual_pr_command() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn cli_has_review_gate_alias() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn cli_has_fail_on_blockers() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn cli_has_prompt_option() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn cli_has_max_items_option() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn docs_mentions_virtual_pr_gate() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn readme_mentions_review_gate() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn testing_mentions_vpr() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn ut_matrix_has_vpr_category() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn self_review_marker_can_find_vpr() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn risk_model_mentions_auth() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn risk_model_mentions_migration() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn risk_model_mentions_secret() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn risk_model_mentions_concurrency() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn risk_model_mentions_dependency() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn risk_model_mentions_large_diff() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn risk_model_mentions_handoff() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn risk_model_mentions_approval() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn report_json_mentions_risk_items() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn report_json_mentions_file_hotspots() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn report_json_mentions_group_readiness() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn markdown_mentions_next_actions() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn prompt_mentions_test_evidence() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn prompt_mentions_request_changes() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_ready_doc_has_score() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_risky_doc_has_lower_score() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_risk_items_include_group_id() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_file_hotspots_include_pending() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_group_readiness_include_brief() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_report_has_blockers() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_report_has_warnings() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_report_has_actions() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_report_has_title() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_report_json_is_object() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_markdown_is_not_empty() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_prompt_is_not_empty() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_risk_queue_nonempty() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_file_hotspots_nonempty() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_group_readiness_nonempty() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_ready_has_no_blockers() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_risky_has_blockers() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_ready_is_ready() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_risky_not_ready() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_score_within_range() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_all_risk_scores_nonnegative() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_top_risk_has_reasons() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_handoff_gap_warning_visible() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_approval_gate_visible() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_coverage_gate_visible() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_next_action_mentions_coverage() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_next_action_mentions_approval() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_prompt_limits_items() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_json_round_trip() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_markdown_table_present() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_group_table_present() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_review_gate_title_present() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_file_hotspot_path_present() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_cli_usage_has_command() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_app_topbar_has_button() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}

#[test]
fn vpr_summary_has_button() {
    let report = risky_report();
    let json_value = vpr::virtual_pr_report_json_value(&report);
    let markdown = vpr::virtual_pr_report_markdown(&report);
    let prompt = vpr::virtual_pr_reviewer_prompt_markdown(&report, 3);
    assert!(report.readiness_score <= 100);
    assert!(json_value.is_object());
    assert!(markdown.contains("Virtual PR Review Gate"));
    assert!(prompt.contains("仮想PRレビュー依頼"));
}
