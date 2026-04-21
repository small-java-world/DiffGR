use diffgr_gui::app::StartupArgs;
use std::path::PathBuf;

#[test]
fn startup_args_accept_diffgr_then_state() {
    let args = StartupArgs::from_iter(["input.diffgr.json", "--state", "review.state.json"]);
    assert_eq!(args.path, Some(PathBuf::from("input.diffgr.json")));
    assert_eq!(args.state, Some(PathBuf::from("review.state.json")));
}

#[test]
fn startup_args_accept_state_then_diffgr() {
    let args = StartupArgs::from_iter(["--state", "review.state.json", "input.diffgr.json"]);
    assert_eq!(args.path, Some(PathBuf::from("input.diffgr.json")));
    assert_eq!(args.state, Some(PathBuf::from("review.state.json")));
}
