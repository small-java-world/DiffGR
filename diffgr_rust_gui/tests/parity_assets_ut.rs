use serde_json::Value;
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;

fn manifest() -> Value {
    serde_json::from_str(include_str!("../PYTHON_PARITY_MANIFEST.json")).unwrap()
}

#[test]
fn every_python_script_has_ps1_sh_and_compat_copy() {
    let manifest = manifest();
    for entry in manifest["entries"].as_array().unwrap() {
        let stem = entry["stem"].as_str().unwrap();
        assert!(
            Path::new("scripts").join(format!("{stem}.ps1")).exists(),
            "missing ps1 for {stem}"
        );
        assert!(
            Path::new("scripts").join(format!("{stem}.sh")).exists(),
            "missing sh for {stem}"
        );
        assert!(
            Path::new("compat/python/scripts")
                .join(format!("{stem}.py"))
                .exists(),
            "missing compat py for {stem}"
        );
    }
}

#[test]
fn script_wrappers_default_to_native_and_only_use_python_when_requested() {
    let manifest = manifest();
    for entry in manifest["entries"].as_array().unwrap() {
        let stem = entry["stem"].as_str().unwrap();
        let ps1 = fs::read_to_string(Path::new("scripts").join(format!("{stem}.ps1"))).unwrap();
        let sh = fs::read_to_string(Path::new("scripts").join(format!("{stem}.sh"))).unwrap();
        assert!(
            ps1.contains("CompatPython"),
            "ps1 lacks CompatPython flag for {stem}"
        );
        assert!(
            ps1.contains("DIFFGR_COMPAT_PYTHON"),
            "ps1 lacks env switch for {stem}"
        );
        assert!(
            ps1.contains("diffgrctl-windows.ps1"),
            "ps1 does not call native wrapper for {stem}"
        );
        assert!(
            sh.contains("--compat-python"),
            "sh lacks compat flag for {stem}"
        );
        assert!(
            sh.contains("DIFFGR_COMPAT_PYTHON"),
            "sh lacks env switch for {stem}"
        );
        assert!(
            sh.contains("diffgrctl.sh"),
            "sh does not call native wrapper for {stem}"
        );
    }
}

#[test]
fn native_parity_audit_covers_all_manifest_scripts_and_options() {
    let audit: Value =
        serde_json::from_str(include_str!("../NATIVE_PYTHON_PARITY_AUDIT.json")).unwrap();
    assert_eq!(audit["ok"].as_bool(), Some(true));
    assert_eq!(audit["scriptCount"].as_u64().unwrap(), 31);
    assert!(audit["uniquePythonOptionCount"].as_u64().unwrap() >= 80);
    assert!(audit["missingNativeOptions"].as_array().unwrap().is_empty());
}

#[test]
fn functional_scenarios_are_unique_and_executable_by_native_command() {
    let scenarios: Value =
        serde_json::from_str(include_str!("../NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json")).unwrap();
    let mut seen = BTreeSet::new();
    for scenario in scenarios["scenarios"].as_array().unwrap() {
        let script = scenario["script"].as_str().unwrap();
        assert!(
            seen.insert(script.to_owned()),
            "duplicate scenario for {script}"
        );
        assert!(!scenario["nativeCommand"].as_str().unwrap().is_empty());
        assert!(!scenario["features"].as_array().unwrap().is_empty());
    }
    assert_eq!(seen.len(), 31);
}

#[test]
fn python_source_audit_records_all_non_cache_files_and_only_excludes_pyc() {
    let audit: Value =
        serde_json::from_str(include_str!("../COMPLETE_PYTHON_SOURCE_AUDIT.json")).unwrap();
    assert_eq!(audit["sourceFileCount"].as_u64().unwrap(), 163);
    assert_eq!(audit["excludedCacheFileCount"].as_u64().unwrap(), 99);
    assert_eq!(audit["entries"].as_array().unwrap().len(), 163);
    assert!(audit["entries"]
        .as_array()
        .unwrap()
        .iter()
        .all(|entry| !entry["sourcePath"].as_str().unwrap().ends_with(".pyc")));
}

#[test]
fn test_scripts_expose_fmt_check_and_targeted_test_entrypoints() {
    let ps1 = fs::read_to_string("windows/test-windows.ps1").unwrap();
    let sh = fs::read_to_string("scripts/test.sh").unwrap();
    assert!(ps1.contains("cargo") && ps1.contains("test") && ps1.contains("--all-targets"));
    assert!(ps1.contains("$TestName"));
    assert!(sh.contains("cargo test --all-targets") || sh.contains("test --all-targets"));
    assert!(sh.contains("test_name"));
}
