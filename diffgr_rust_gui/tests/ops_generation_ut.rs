mod support;

use diffgr_gui::ops;
use serde_json::json;
use std::fs;

#[test]
fn build_diffgr_from_diff_text_handles_multiple_files_and_patch() {
    let diff = r#"diff --git a/src/lib.rs b/src/lib.rs
--- a/src/lib.rs
+++ b/src/lib.rs
@@ -1,2 +1,3 @@ fn main
 fn main() {
+    println!("hi");
 }
diff --git "a/path with spaces.txt" "b/path with spaces.txt"
--- "a/path with spaces.txt"
+++ "b/path with spaces.txt"
@@ -1,1 +1,1 @@
-old
+new
"#;

    let doc = ops::build_diffgr_from_diff_text(
        diff,
        "generated",
        "main",
        "feature",
        "base-sha",
        "head-sha",
        "merge-base",
        true,
    )
    .unwrap();

    assert_eq!(doc["meta"]["title"], json!("generated"));
    assert_eq!(doc["meta"]["source"]["base"], json!("main"));
    assert_eq!(doc["patch"], json!(diff));
    let chunks = doc["chunks"].as_array().unwrap();
    assert_eq!(chunks.len(), 2);
    assert_eq!(chunks[0]["filePath"], json!("src/lib.rs"));
    assert_eq!(chunks[1]["filePath"], json!("path with spaces.txt"));
    assert_eq!(doc["assignments"]["g-all"].as_array().unwrap().len(), 2);
}

#[test]
fn build_diffgr_from_diff_text_keeps_metadata_only_changes() {
    let diff = "diff --git a/assets/logo.bin b/assets/logo.bin\nnew file mode 100644\nindex 0000000..1111111\nBinary files /dev/null and b/assets/logo.bin differ\n";
    let doc = ops::build_diffgr_from_diff_text(diff, "binary", "a", "b", "a1", "b1", "m1", false)
        .unwrap();
    let chunks = doc["chunks"].as_array().unwrap();
    assert_eq!(chunks.len(), 1);
    assert_eq!(chunks[0]["filePath"], json!("assets/logo.bin"));
    assert!(chunks[0]["lines"].as_array().unwrap().is_empty());
    assert!(chunks[0]["x-meta"]["diffHeaderLines"]
        .as_array()
        .unwrap()
        .iter()
        .any(|line| line.as_str() == Some("new file mode 100644")));
    assert!(doc.get("patch").is_none());
}

#[test]
fn split_chunk_by_change_blocks_preserves_context_and_parent_metadata() {
    let chunk = json!({
        "id": "parent",
        "filePath": "src/lib.rs",
        "header": "fn demo",
        "old": {"start": 1, "count": 5},
        "new": {"start": 1, "count": 5},
        "lines": [
            {"kind": "context", "text": "a", "oldLine": 1, "newLine": 1},
            {"kind": "add", "text": "b", "oldLine": null, "newLine": 2},
            {"kind": "context", "text": "c", "oldLine": 2, "newLine": 3},
            {"kind": "delete", "text": "d", "oldLine": 3, "newLine": null},
            {"kind": "context", "text": "e", "oldLine": 4, "newLine": 4}
        ]
    });

    let pieces = ops::split_chunk_by_change_blocks(&chunk, 1);
    assert_eq!(pieces.len(), 2);
    assert_eq!(pieces[0]["x-meta"]["parentChunkId"], json!("parent"));
    assert_eq!(pieces[0]["x-meta"]["changeBlockIndex"], json!(1));
    assert_eq!(pieces[1]["x-meta"]["changeBlockIndex"], json!(2));
    assert_eq!(pieces[1]["x-meta"]["changeBlockCount"], json!(2));
    assert!(pieces[0]["lines"].as_array().unwrap().len() >= 2);
    assert!(pieces[1]["lines"].as_array().unwrap().len() >= 2);
}

#[test]
fn split_chunk_by_change_blocks_returns_original_for_single_change_block() {
    let chunk = json!({
        "id": "one",
        "filePath": "src/lib.rs",
        "old": {"start": 1, "count": 1},
        "new": {"start": 1, "count": 1},
        "lines": [
            {"kind": "delete", "text": "old", "oldLine": 1, "newLine": null},
            {"kind": "add", "text": "new", "oldLine": null, "newLine": 1}
        ]
    });
    assert_eq!(ops::split_chunk_by_change_blocks(&chunk, 3), vec![chunk]);
}

#[test]
fn change_fingerprint_ignores_line_numbers_but_not_file_or_header() {
    let left = json!({
        "id": "a",
        "filePath": "src/lib.rs",
        "header": "fn demo",
        "lines": [
            {"kind": "delete", "text": "old", "oldLine": 10, "newLine": null},
            {"kind": "add", "text": "new", "oldLine": null, "newLine": 10}
        ]
    });
    let mut right = left.clone();
    right["id"] = json!("b");
    right["lines"][0]["oldLine"] = json!(99);
    right["lines"][1]["newLine"] = json!(100);
    assert_eq!(
        ops::change_fingerprint_for_chunk(&left),
        ops::change_fingerprint_for_chunk(&right)
    );

    right["header"] = json!("fn other");
    assert_ne!(
        ops::change_fingerprint_for_chunk(&left),
        ops::change_fingerprint_for_chunk(&right)
    );
}

#[test]
fn canonical_json_sorted_is_stable_for_object_order() {
    let a = json!({"b": [2, 1], "a": {"y": true, "x": null}});
    let b = json!({"a": {"x": null, "y": true}, "b": [2, 1]});
    assert_eq!(
        ops::canonical_json_sorted(&a),
        ops::canonical_json_sorted(&b)
    );
    assert_eq!(ops::sha256_hex_value(&a), ops::sha256_hex_value(&b));
}

#[test]
fn write_helpers_create_parent_directories_and_replace_files() {
    let root = support::temp_dir("write_helpers");
    let text_path = root.join("nested").join("note.txt");
    let json_path = root.join("nested").join("state.json");

    ops::write_text_file(&text_path, "first").unwrap();
    ops::write_text_file(&text_path, "second").unwrap();
    ops::write_json_file(&json_path, &json!({"ok": true})).unwrap();

    assert_eq!(fs::read_to_string(&text_path).unwrap(), "second");
    assert_eq!(support::read_json(&json_path)["ok"], json!(true));
    let temp_leftovers = fs::read_dir(text_path.parent().unwrap())
        .unwrap()
        .filter_map(Result::ok)
        .filter(|entry| entry.file_name().to_string_lossy().contains(".tmp"))
        .count();
    assert_eq!(temp_leftovers, 0);

    fs::remove_dir_all(root).ok();
}

#[test]
fn apply_slice_patch_moves_chunks_and_rejects_unknowns() {
    let doc = support::rich_doc();
    let patched = ops::apply_slice_patch(
        &doc,
        &json!({
            "rename": {"g-ui": "User interface"},
            "move": [{"chunk": "c-docs", "to": "g-ui"}]
        }),
    )
    .unwrap();

    assert_eq!(patched["groups"][0]["name"], json!("User interface"));
    assert!(patched["assignments"]["g-ui"]
        .as_array()
        .unwrap()
        .iter()
        .any(|v| v.as_str() == Some("c-docs")));
    assert!(patched["groups"]
        .as_array()
        .unwrap()
        .iter()
        .all(|g| g["id"].as_str() != Some("g-empty")));
    assert_eq!(patched["meta"]["x-slicePatch"]["renameCount"], json!(1));

    let err = ops::apply_slice_patch(&doc, &json!({"move": [{"chunk": "missing", "to": "g-ui"}]}))
        .unwrap_err();
    assert!(err.contains("Unknown chunk id"));
}
