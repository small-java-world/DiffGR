use std::fs;
use std::path::Path;

#[test]
fn python_parity_manifest_lists_all_vendored_scripts_and_wrappers() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let manifest_text = fs::read_to_string(root.join("PYTHON_PARITY_MANIFEST.json")).unwrap();
    let manifest: serde_json::Value = serde_json::from_str(&manifest_text).unwrap();
    let entries = manifest["entries"].as_array().unwrap();
    assert_eq!(entries.len(), 31);
    for entry in entries {
        let script = entry["script"].as_str().unwrap();
        let stem = entry["stem"].as_str().unwrap();
        assert!(
            root.join("compat/python").join(script).exists(),
            "missing compat script {script}"
        );
        assert!(
            root.join("scripts").join(format!("{stem}.ps1")).exists(),
            "missing ps1 wrapper {stem}"
        );
        assert!(
            root.join("scripts").join(format!("{stem}.sh")).exists(),
            "missing sh wrapper {stem}"
        );
        assert!(entry["nativeWrapperPs1"].as_bool().unwrap());
        assert!(entry["nativeWrapperSh"].as_bool().unwrap());
    }
}

#[test]
fn wrappers_expose_python_compat_switch() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    for entry in serde_json::from_str::<serde_json::Value>(
        &fs::read_to_string(root.join("PYTHON_PARITY_MANIFEST.json")).unwrap(),
    )
    .unwrap()["entries"]
        .as_array()
        .unwrap()
    {
        let stem = entry["stem"].as_str().unwrap();
        let ps1 = fs::read_to_string(root.join("scripts").join(format!("{stem}.ps1"))).unwrap();
        let sh = fs::read_to_string(root.join("scripts").join(format!("{stem}.sh"))).unwrap();
        assert!(ps1.contains("CompatPython"));
        assert!(sh.contains("--compat-python"));
    }
}
