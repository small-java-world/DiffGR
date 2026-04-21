const APP_RS: &str = include_str!("../src/app.rs");
const RUN_WINDOWS_PS1: &str = include_str!("../windows/run-windows.ps1");
const RUN_PS1: &str = include_str!("../run.ps1");

fn assert_app_contains(needle: &str) {
    assert!(APP_RS.contains(needle), "missing app.rs marker: {needle}");
}

#[test]
fn render_responsiveness_has_background_document_loader() {
    assert_app_contains("struct PendingDocumentLoad");
    assert_app_contains("start_background_document_load");
    assert_app_contains("DiffgrDocument::load_from_path(&worker_path");
}

#[test]
fn render_responsiveness_has_background_state_autosave() {
    assert_app_contains("struct PendingStateSave");
    assert_app_contains("pending_state_save");
    assert_app_contains("write_json_value(&worker_path, &state)");
}

#[test]
fn render_responsiveness_polls_background_jobs_each_frame() {
    assert_app_contains("poll_background_jobs(ui.ctx())");
    assert_app_contains("TryRecvError::Empty");
    assert_app_contains("BACKGROUND_JOB_REPAINT_MS");
}

#[test]
fn render_responsiveness_keeps_autosave_dirty_when_newer_edits_exist() {
    assert_app_contains("pending.revision == self.state_revision");
    assert_app_contains("追加変更あり");
}

#[test]
fn render_responsiveness_visible_rows_are_on_demand() {
    assert_app_contains("rows: BTreeMap<usize, ChunkRow>");
    assert_app_contains("rows: BTreeMap::new()");
    assert_app_contains("fn build_chunk_row(&self, index: usize, chunk_id: &str)");
}

#[test]
fn render_responsiveness_visible_count_uses_ids_not_row_cache() {
    assert_app_contains("self.visible_cache.ids.len()");
}

#[test]
fn render_responsiveness_filter_input_is_debounced() {
    assert_app_contains("SEARCH_DEBOUNCE_MS");
    assert_app_contains("filter_apply_deadline");
    assert_app_contains("schedule_filter_apply(ui.ctx())");
}

#[test]
fn render_responsiveness_enter_applies_filter_immediately() {
    assert_app_contains("input.key_pressed(egui::Key::Enter)");
    assert_app_contains("apply_filter_inputs_now()");
}

#[test]
fn render_responsiveness_filter_buffers_are_separate_from_applied_filters() {
    assert_app_contains("file_filter_input: String");
    assert_app_contains("content_filter_input: String");
    assert_app_contains("self.file_filter_input = self.file_filter.clone()");
}

#[test]
fn render_responsiveness_state_json_uses_virtual_text() {
    assert_app_contains("fn draw_virtual_text(");
    assert_app_contains("build_line_starts(&text)");
    assert_app_contains("Some(&self.state_preview_cache.line_starts)");
}

#[test]
fn render_responsiveness_state_preview_avoids_per_frame_clone() {
    assert_app_contains("ensure_state_preview_cache");
    assert!(!APP_RS.contains("fn state_preview_text(&mut self) -> Option<String>"));
}

#[test]
fn render_responsiveness_state_diff_preview_uses_virtual_text() {
    assert_app_contains("State diff / merge preview");
    assert_app_contains("&self.state_merge_preview_text");
}

#[test]
fn render_responsiveness_long_diff_lines_are_clipped() {
    assert_app_contains("MAX_RENDERED_DIFF_CHARS");
    assert_app_contains("clip_for_display(&rendered, MAX_RENDERED_DIFF_CHARS)");
    assert_app_contains("chars omitted");
}

#[test]
fn render_responsiveness_smooth_scroll_repaint_setting_exists() {
    assert_app_contains("smooth_scroll_repaint");
    assert_app_contains("滑らかスクロール");
    assert_app_contains("ACTIVE_SCROLL_REPAINT_MS");
}

#[test]
fn render_responsiveness_repaints_only_on_active_scroll_or_drag() {
    assert_app_contains("maybe_request_active_scroll_repaint(ui.ctx())");
    assert_app_contains("input.pointer.any_down()");
    assert_app_contains("egui::Event::MouseWheel");
}

#[test]
fn render_responsiveness_reduce_motion_still_supported() {
    assert_app_contains("ちらつき抑制");
    assert_app_contains(
        "apply_runtime_style(ui.ctx(), self.config.theme, self.config.reduce_motion)",
    );
}

#[test]
fn render_responsiveness_background_io_can_be_disabled() {
    assert_app_contains("--no-background-io");
    assert_app_contains("DIFFGR_NO_BACKGROUND_IO");
    assert_app_contains("config.background_io = false");
}

#[test]
fn render_responsiveness_low_memory_disables_extra_repaint() {
    assert_app_contains("config.smooth_scroll_repaint = false");
    assert_app_contains("DIFFGR_LOW_MEMORY");
}

#[test]
fn render_responsiveness_smooth_scroll_cli_flag_exists() {
    assert_app_contains("--smooth-scroll");
    assert_app_contains("DIFFGR_SMOOTH_SCROLL");
}

#[test]
fn render_responsiveness_spinner_marks_background_work() {
    assert_app_contains("egui::Spinner::new()");
    assert_app_contains("バックグラウンド処理中");
}

#[test]
fn render_responsiveness_atomic_json_write_uses_temp_file() {
    assert_app_contains("fn write_json_value(path: &Path, value: &Value)");
    assert_app_contains("fs::rename(&tmp, path)");
}

#[test]
fn render_responsiveness_virtual_line_index_is_byte_based() {
    assert_app_contains("fn build_line_starts(text: &str) -> Vec<usize>");
    assert_app_contains("if byte == b'\\n'");
    assert_app_contains("fn line_at<'a>(text: &'a str, starts: &[usize], index: usize) -> &'a str");
}

#[test]
fn render_responsiveness_all_scroll_areas_keep_animation_toggle() {
    assert_app_contains(".animated(!self.config.reduce_motion)");
}

#[test]
fn render_responsiveness_filter_ui_explains_delayed_search() {
    assert_app_contains("入力停止後に反映します");
    assert_app_contains("Enterで即時反映");
}

#[test]
fn render_responsiveness_help_mentions_large_diff_settings() {
    assert_app_contains("大きいdiffでは");
    assert_app_contains("コンパクト行");
}

#[test]
fn render_responsiveness_window_title_update_stays_change_only() {
    assert_app_contains("if next_title != self.last_window_title");
}

#[test]
fn render_responsiveness_ui_memory_is_still_optional() {
    assert_app_contains("persist_egui_memory");
    assert_app_contains("UI状態を記憶");
}

#[test]
fn render_responsiveness_dropped_files_still_supported() {
    assert_app_contains("handle_dropped_files(ui)");
    assert_app_contains("raw.dropped_files");
}

#[test]
fn render_responsiveness_top_bar_background_io_setting_visible() {
    assert_app_contains("読込/自動保存を別スレッド");
}

#[test]
fn render_responsiveness_top_bar_clip_setting_visible() {
    assert_app_contains("超長行を省略描画");
}

#[test]
fn render_responsiveness_top_bar_deferred_filter_setting_visible() {
    assert_app_contains("検索を遅延適用");
}

#[test]
fn render_responsiveness_run_windows_has_smooth_switch() {
    assert!(
        RUN_WINDOWS_PS1.contains("Smooth"),
        "run-windows.ps1 should expose -Smooth"
    );
    assert!(
        RUN_WINDOWS_PS1.contains("DIFFGR_SMOOTH_SCROLL"),
        "run-windows.ps1 should set smooth env"
    );
}

#[test]
fn render_responsiveness_run_windows_can_disable_background_io() {
    assert!(
        RUN_WINDOWS_PS1.contains("NoBackgroundIO"),
        "run-windows.ps1 should expose -NoBackgroundIO"
    );
    assert!(
        RUN_WINDOWS_PS1.contains("DIFFGR_NO_BACKGROUND_IO"),
        "run-windows.ps1 should set no-background env"
    );
}

#[test]
fn render_responsiveness_root_run_ps1_passes_remaining_args() {
    assert!(RUN_PS1.contains("ValueFromRemainingArguments"));
    assert!(
        RUN_PS1.contains("windows\\run-windows.ps1")
            || RUN_PS1.contains("windows\\run-windows.ps1")
    );
}

#[test]
fn render_responsiveness_config_defaults_cover_new_features() {
    assert_app_contains("smooth_scroll_repaint: true");
    assert_app_contains("defer_filtering: true");
    assert_app_contains("background_io: true");
    assert_app_contains("clip_long_lines: true");
}

#[test]
fn render_responsiveness_background_load_preserves_recent_documents() {
    assert_app_contains("finish_loaded_document");
    assert_app_contains("remember_document(&path, self.state_path.as_deref(), Some(&title))");
}

#[test]
fn render_responsiveness_changed_line_indices_are_cached() {
    assert_app_contains("struct DiffLineIndexCache");
    assert_app_contains("fn changed_line_indices(&mut self, chunk: &Chunk) -> Arc<Vec<usize>>");
    assert_app_contains("self.diff_line_index_cache = Some(DiffLineIndexCache");
}

#[test]
fn render_responsiveness_show_only_changed_does_not_scan_every_frame() {
    assert_app_contains(
        "let changed_indices = self.show_only_changed.then(|| self.changed_line_indices(chunk));",
    );
    assert!(!APP_RS.contains("let changed_indices: Vec<usize> = if self.show_only_changed"));
}

#[test]
fn render_responsiveness_diff_line_index_cache_clears_with_volatile_caches() {
    assert_app_contains("self.diff_line_index_cache = None");
}
