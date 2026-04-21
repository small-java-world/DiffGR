mod support;

use diffgr_gui::model::normalize_state_payload;
use diffgr_gui::ops;
use serde_json::json;

#[test]
fn normalize_state_payload_accepts_wrapped_state_and_fills_missing_sections() {
    let normalized =
        normalize_state_payload(json!({"state": {"reviews": {"c1": {"status": "reviewed"}}}}))
            .unwrap();
    assert_eq!(normalized["reviews"]["c1"]["status"], json!("reviewed"));
    assert_eq!(normalized["groupBriefs"], json!({}));
    assert_eq!(normalized["analysisState"], json!({}));
    assert_eq!(normalized["threadState"], json!({}));
}

#[test]
fn normalize_state_payload_rejects_bad_shapes() {
    assert!(normalize_state_payload(json!(["not", "object"]))
        .unwrap_err()
        .contains("JSON object"));
    assert!(normalize_state_payload(json!({"reviews": []}))
        .unwrap_err()
        .contains("reviews"));
    assert!(normalize_state_payload(json!({"unrelated": {}}))
        .unwrap_err()
        .contains("reviews"));
}

#[test]
fn extract_and_apply_review_state_roundtrip_preserves_mutable_sections() {
    let doc = support::rich_doc();
    let state = ops::extract_review_state(&doc);
    assert_eq!(state["reviews"]["c-ui-login"]["status"], json!("reviewed"));
    assert_eq!(state["groupBriefs"]["g-ui"]["status"], json!("ready"));

    let stripped = json!({
        "format": doc["format"].clone(),
        "version": doc["version"].clone(),
        "meta": doc["meta"].clone(),
        "groups": doc["groups"].clone(),
        "chunks": doc["chunks"].clone(),
        "assignments": doc["assignments"].clone(),
        "reviews": {}
    });
    let applied = ops::apply_review_state(&stripped, &state).unwrap();
    assert_eq!(ops::extract_review_state(&applied), state);
}

#[test]
fn apply_review_state_removes_empty_optional_sections_but_keeps_reviews() {
    let doc = support::rich_doc();
    let state = json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let applied = ops::apply_review_state(&doc, &state).unwrap();
    assert!(applied.get("reviews").is_some());
    assert!(applied.get("groupBriefs").is_none());
    assert!(applied.get("analysisState").is_none());
    assert!(applied.get("threadState").is_none());
}

#[test]
fn merge_review_states_uses_status_precedence_and_conflict_warnings() {
    let base = json!({
        "reviews": {
            "c1": {"status": "reviewed", "comment": "base"},
            "c2": {"status": "ignored"}
        },
        "groupBriefs": {"g1": {"status": "ready", "summary": "base"}},
        "analysisState": {},
        "threadState": {}
    });
    let incoming = json!({
        "reviews": {
            "c1": {"status": "needsReReview", "comment": "incoming"},
            "c2": {"status": "reviewed"},
            "c3": {"status": "unreviewed", "comment": "new"}
        },
        "groupBriefs": {"g1": {"status": "draft", "summary": "incoming"}},
        "analysisState": {"selectedChunkId": "c3"},
        "threadState": {}
    });

    let (merged, warnings, applied) =
        ops::merge_review_states(&base, &[("incoming.state.json".to_owned(), incoming)]).unwrap();
    assert!(applied >= 5);
    assert_eq!(merged["reviews"]["c1"]["status"], json!("needsReReview"));
    assert_eq!(merged["reviews"]["c1"]["comment"], json!("incoming"));
    assert_eq!(merged["reviews"]["c2"]["status"], json!("ignored"));
    assert_eq!(merged["groupBriefs"]["g1"]["status"], json!("ready"));
    assert_eq!(merged["groupBriefs"]["g1"]["summary"], json!("incoming"));
    assert!(warnings.iter().any(|w| w.contains("conflict")));
}

#[test]
fn diff_review_states_emits_tokens_for_nested_thread_files() {
    let base = json!({
        "reviews": {"c1": {"status": "reviewed"}},
        "groupBriefs": {},
        "analysisState": {"selectedChunkId": "c1"},
        "threadState": {"__files": {"a.rs": {"expanded": true}}}
    });
    let incoming = json!({
        "reviews": {"c1": {"status": "needsReReview"}, "c2": {"comment": "new"}},
        "groupBriefs": {},
        "analysisState": {},
        "threadState": {"__files": {"b.rs": {"expanded": false}}}
    });

    let diff = ops::diff_review_states(&base, &incoming).unwrap();
    let tokens = ops::selection_tokens_from_diff(&diff);
    assert!(tokens.contains(&"reviews:c1".to_owned()));
    assert!(tokens.contains(&"reviews:c2".to_owned()));
    assert!(tokens.contains(&"analysisState:selectedChunkId".to_owned()));
    assert!(tokens.contains(&"threadState.__files:a.rs".to_owned()));
    assert!(tokens.contains(&"threadState.__files:b.rs".to_owned()));
}

#[test]
fn apply_review_state_selection_can_add_change_and_remove_entries() {
    let base = json!({
        "reviews": {"c1": {"status": "reviewed"}},
        "groupBriefs": {},
        "analysisState": {"selectedChunkId": "c1"},
        "threadState": {"__files": {"a.rs": {"expanded": true}}}
    });
    let incoming = json!({
        "reviews": {"c2": {"status": "ignored"}},
        "groupBriefs": {},
        "analysisState": {},
        "threadState": {"__files": {"b.rs": {"expanded": false}}}
    });
    let tokens = vec![
        "reviews:c1".to_owned(),
        "reviews:c2".to_owned(),
        "analysisState:selectedChunkId".to_owned(),
        "threadState.__files:a.rs".to_owned(),
        "threadState.__files:b.rs".to_owned(),
    ];
    let (next, applied) = ops::apply_review_state_selection(&base, &incoming, &tokens).unwrap();
    assert_eq!(applied, tokens.len());
    assert!(next["reviews"].get("c1").is_none());
    assert_eq!(next["reviews"]["c2"]["status"], json!("ignored"));
    assert!(next["analysisState"].get("selectedChunkId").is_none());
    assert!(next["threadState"]["__files"].get("a.rs").is_none());
    assert_eq!(
        next["threadState"]["__files"]["b.rs"]["expanded"],
        json!(false)
    );
}

#[test]
fn apply_review_state_selection_rejects_unknown_sections_and_bad_tokens() {
    let state = json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    assert!(
        ops::apply_review_state_selection(&state, &state, &["badtoken".to_owned()])
            .unwrap_err()
            .contains("Invalid")
    );
    assert!(
        ops::apply_review_state_selection(&state, &state, &["unknown:key".to_owned()])
            .unwrap_err()
            .contains("Unknown")
    );
}

#[test]
fn preview_review_state_selection_reports_applied_and_changed_tokens() {
    let base = json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let other = json!({"reviews": {"c1": {"status": "reviewed"}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let preview =
        ops::preview_review_state_selection(&base, &other, &["reviews:c1".to_owned()]).unwrap();
    assert_eq!(preview["appliedCount"], json!(1));
    assert!(preview["changedTokens"]
        .as_array()
        .unwrap()
        .contains(&json!("reviews:c1")));
}

#[test]
fn summarize_state_counts_sections_and_has_stable_fingerprint() {
    let a = json!({
        "reviews": {"c1": {"status": "reviewed"}},
        "groupBriefs": {"g1": {"status": "ready"}},
        "analysisState": {"filterText": "src"},
        "threadState": {}
    });
    let b = json!({
        "threadState": {},
        "analysisState": {"filterText": "src"},
        "groupBriefs": {"g1": {"status": "ready"}},
        "reviews": {"c1": {"status": "reviewed"}}
    });
    let summary_a = ops::summarize_state(&a).unwrap();
    let summary_b = ops::summarize_state(&b).unwrap();
    assert_eq!(summary_a["counts"]["reviews"], json!(1));
    assert_eq!(summary_a["counts"]["groupBriefs"], json!(1));
    assert_eq!(summary_a["fingerprint"], summary_b["fingerprint"]);
}
