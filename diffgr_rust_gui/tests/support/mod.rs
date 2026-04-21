use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::process;
use std::time::{SystemTime, UNIX_EPOCH};

pub fn rich_doc() -> Value {
    json!({
        "format": "diffgr",
        "version": 1,
        "meta": {
            "title": "UT rich fixture",
            "source": {
                "type": "git_compare",
                "base": "main",
                "head": "feature",
                "baseSha": "base-sha",
                "headSha": "head-sha",
                "mergeBaseSha": "merge-base"
            }
        },
        "groups": [
            {"id": "g-ui", "name": "UI", "order": 1, "tags": ["frontend"]},
            {"id": "g-api", "name": "API", "order": 2, "tags": ["backend"]},
            {"id": "g-empty", "name": "Empty", "order": 3, "tags": []}
        ],
        "chunks": [
            {
                "id": "c-ui-login",
                "filePath": "src/ui/login.rs",
                "header": "fn render_login",
                "old": {"start": 10, "count": 2},
                "new": {"start": 10, "count": 3},
                "lines": [
                    {"kind": "context", "text": "fn render_login() {", "oldLine": 10, "newLine": 10},
                    {"kind": "add", "text": "    show_spinner();", "oldLine": null, "newLine": 11},
                    {"kind": "context", "text": "}", "oldLine": 11, "newLine": 12}
                ],
                "fingerprints": {"stable": "stable-ui-login"}
            },
            {
                "id": "c-api-route",
                "filePath": "src/api/routes.rs",
                "header": "fn route_user",
                "old": {"start": 20, "count": 2},
                "new": {"start": 20, "count": 2},
                "lines": [
                    {"kind": "delete", "text": "    get(\"/user\");", "oldLine": 20, "newLine": null},
                    {"kind": "add", "text": "    get(\"/users\");", "oldLine": null, "newLine": 20},
                    {"kind": "context", "text": "}", "oldLine": 21, "newLine": 21}
                ],
                "fingerprints": {"stable": "stable-api-route"}
            },
            {
                "id": "c-docs",
                "filePath": "README.md",
                "header": "docs",
                "old": {"start": 1, "count": 1},
                "new": {"start": 1, "count": 2},
                "lines": [
                    {"kind": "context", "text": "# Project", "oldLine": 1, "newLine": 1},
                    {"kind": "add", "text": "Document login spinner.", "oldLine": null, "newLine": 2}
                ],
                "fingerprints": {"stable": "stable-docs"}
            }
        ],
        "assignments": {
            "g-ui": ["c-ui-login"],
            "g-api": ["c-api-route", "c-docs"],
            "g-empty": []
        },
        "reviews": {
            "c-ui-login": {
                "status": "reviewed",
                "comment": "looks good",
                "lineComments": [
                    {"lineType": "add", "oldLine": null, "newLine": 11, "comment": "spinner is expected"}
                ]
            },
            "c-api-route": {"status": "needsReReview", "comment": "confirm URL migration"}
        },
        "groupBriefs": {
            "g-ui": {"status": "ready", "summary": "Login spinner UI", "focusPoints": ["rendering"]},
            "g-api": {"status": "draft", "summary": "Route rename"}
        },
        "analysisState": {"currentGroupId": "g-ui", "selectedChunkId": "c-ui-login", "filterText": "src"},
        "threadState": {
            "c-ui-login": {"expanded": true},
            "__files": {"src/ui/login.rs": {"expanded": true}}
        },
        "patch": "diff --git a/src/ui/login.rs b/src/ui/login.rs\n"
    })
}

pub fn minimal_state() -> Value {
    json!({
        "reviews": {
            "c-ui-login": {"status": "reviewed", "comment": "state comment"},
            "c-docs": {"status": "ignored"}
        },
        "groupBriefs": {"g-ui": {"status": "acknowledged", "summary": "ack"}},
        "analysisState": {"currentGroupId": "g-ui"},
        "threadState": {"__files": {"README.md": {"expanded": true}}}
    })
}

pub fn rebase_old_doc() -> Value {
    json!({
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "old", "source": {"headSha": "old-head"}},
        "groups": [
            {"id": "g-old", "name": "Old Group", "order": 1},
            {"id": "g-legacy", "name": "Legacy", "order": 2}
        ],
        "chunks": [
            chunk("same-id", "src/a.rs", "same-fp", "fn same", "delete old same", "add new same"),
            chunk("old-stable", "src/b.rs", "stable-shared", "fn stable", "delete old stable", "add new stable"),
            chunk("old-similar", "src/c.rs", "old-similar-fp", "fn similar", "delete old login submit button", "add render login submit button"),
            chunk("old-gone", "src/gone.rs", "gone-fp", "fn gone", "delete gone", "add gone")
        ],
        "assignments": {"g-old": ["same-id", "old-stable", "old-similar"], "g-legacy": ["old-gone"]},
        "reviews": {
            "same-id": {"status": "reviewed", "lineComments": [{"lineType": "add", "oldLine": null, "newLine": 2, "comment": "carry me"}]},
            "old-stable": {"status": "reviewed", "lineComments": [{"lineType": "add", "oldLine": null, "newLine": 2, "comment": "stable line"}]},
            "old-similar": {"status": "reviewed", "lineComments": [{"lineType": "add", "oldLine": null, "newLine": 2, "comment": "should be dropped"}]},
            "old-gone": {"status": "ignored"}
        },
        "groupBriefs": {
            "g-old": {"status": "ready", "summary": "old ready", "approval": {"state": "approved", "approved": true}},
            "g-legacy": {"status": "draft", "summary": "legacy"}
        },
        "analysisState": {"selectedChunkId": "old-stable", "currentGroupId": "g-old"},
        "threadState": {"old-stable": {"notes": ["thread"]}, "selectedLineAnchor": {"lineType": "add", "newLine": 2}, "__files": {"src/b.rs": {"expanded": true}}}
    })
}

pub fn rebase_new_doc() -> Value {
    json!({
        "format": "diffgr",
        "version": 1,
        "meta": {"title": "new", "source": {"headSha": "new-head"}},
        "groups": [{"id": "g-new", "name": "New Group", "order": 1}],
        "chunks": [
            chunk("same-id", "src/a.rs", "same-fp", "fn same", "delete old same", "add new same"),
            chunk("new-stable", "src/moved/b.rs", "stable-shared", "fn stable", "delete old stable", "add new stable"),
            chunk("new-similar", "src/c.rs", "new-similar-fp", "fn similar", "delete old login submit button", "add render login submit button with spinner"),
            chunk("new-only", "src/new.rs", "new-only-fp", "fn new", "delete x", "add y")
        ],
        "assignments": {"g-new": ["same-id", "new-stable", "new-similar", "new-only"]},
        "reviews": {},
        "groupBriefs": {},
        "analysisState": {},
        "threadState": {}
    })
}

pub fn chunk(
    id: &str,
    file_path: &str,
    stable: &str,
    header: &str,
    delete_text: &str,
    add_text: &str,
) -> Value {
    json!({
        "id": id,
        "filePath": file_path,
        "header": header,
        "old": {"start": 1, "count": 1},
        "new": {"start": 1, "count": 1},
        "lines": [
            {"kind": "delete", "text": delete_text, "oldLine": 1, "newLine": null},
            {"kind": "add", "text": add_text, "oldLine": null, "newLine": 1}
        ],
        "fingerprints": {"stable": stable}
    })
}

pub fn temp_dir(label: &str) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time moves forward")
        .as_nanos();
    let dir = std::env::temp_dir().join(format!("diffgr_ut_{label}_{}_{}", process::id(), nanos));
    fs::create_dir_all(&dir).unwrap();
    dir
}

pub fn read_json(path: &std::path::Path) -> Value {
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}
