use serde_json::Value;
use std::fs;
use std::path::PathBuf;

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

#[test]
fn native_diffgrctl_mentions_every_python_script_option() {
    let root = project_root();
    let manifest: Value =
        serde_json::from_str(include_str!("../PYTHON_PARITY_MANIFEST.json")).unwrap();
    let rust_source = [
        include_str!("../src/bin/diffgrctl.rs"),
        include_str!("../src/ops.rs"),
        include_str!("../src/app.rs"),
    ]
    .join("\n");

    let entries = manifest["entries"].as_array().unwrap();
    assert_eq!(entries.len(), 31);

    let mut missing = Vec::new();
    for entry in entries {
        let stem = entry["stem"].as_str().unwrap();
        let hyphen = stem.replace('_', "-");
        assert!(
            rust_source.contains(&format!("\"{stem}\""))
                || rust_source.contains(&format!("\"{hyphen}\"")),
            "missing native command alias for {stem}"
        );
        for arg in entry["arguments"].as_array().unwrap() {
            for name in arg["names"].as_array().unwrap() {
                let Some(name) = name.as_str() else {
                    continue;
                };
                if !name.starts_with("--") {
                    continue;
                }
                if !rust_source.contains(&format!("\"{name}\"")) {
                    missing.push(format!("{stem}:{name}"));
                }
            }
        }
    }
    assert!(
        missing.is_empty(),
        "missing native option spellings: {missing:?}"
    );

    for guard in [
        "--keep-new-groups",
        "--no-line-comments",
        "--impact-grouping",
        "rebase_state_with_options",
        "rebase_reviews_document_with_options",
    ] {
        assert!(
            rust_source.contains(guard),
            "missing native rebase parity guard {guard}"
        );
    }

    for entry in entries {
        let stem = entry["stem"].as_str().unwrap();
        let ps1 = fs::read_to_string(root.join("scripts").join(format!("{stem}.ps1"))).unwrap();
        let sh = fs::read_to_string(root.join("scripts").join(format!("{stem}.sh"))).unwrap();
        assert!(
            ps1.contains("diffgrctl.ps1"),
            "{stem}.ps1 should default to Rust CLI"
        );
        assert!(
            ps1.contains("compat-python.ps1"),
            "{stem}.ps1 should keep compat fallback"
        );
        assert!(
            sh.contains("diffgrctl.sh"),
            "{stem}.sh should default to Rust CLI"
        );
        assert!(
            sh.contains("compat-python.sh"),
            "{stem}.sh should keep compat fallback"
        );
    }
}
