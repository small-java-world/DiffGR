use std::collections::BTreeSet;

#[test]
fn native_functional_scenarios_cover_every_python_script() {
    let manifest: serde_json::Value =
        serde_json::from_str(include_str!("../PYTHON_PARITY_MANIFEST.json")).unwrap();
    let scenarios: serde_json::Value =
        serde_json::from_str(include_str!("../NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json")).unwrap();

    let manifest_stems: BTreeSet<String> = manifest["entries"]
        .as_array()
        .unwrap()
        .iter()
        .map(|entry| entry["stem"].as_str().unwrap().to_owned())
        .collect();
    let scenario_stems: BTreeSet<String> = scenarios["scenarios"]
        .as_array()
        .unwrap()
        .iter()
        .map(|entry| entry["script"].as_str().unwrap().to_owned())
        .collect();

    assert_eq!(manifest_stems.len(), 31);
    assert_eq!(scenario_stems.len(), 31);
    assert_eq!(manifest_stems, scenario_stems);
}

#[test]
fn native_functional_scenarios_name_native_commands_and_features() {
    let scenarios: serde_json::Value =
        serde_json::from_str(include_str!("../NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json")).unwrap();
    for entry in scenarios["scenarios"].as_array().unwrap() {
        assert!(entry["nativeCommand"].as_str().unwrap().contains('-'));
        assert!(!entry["features"].as_array().unwrap().is_empty());
    }
}
