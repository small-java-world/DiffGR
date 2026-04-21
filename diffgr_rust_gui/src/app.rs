use crate::model::{
    Chunk, DiffLine, DiffgrDocument, GroupBriefDraft, GroupMetrics, LineAnchor, Metrics,
    ReviewStatus,
};
use eframe::egui::{self, Color32, FontFamily, ProgressBar, RichText, TextEdit};
use rfd::FileDialog;
use serde::{Deserialize, Serialize};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;
use std::time::{Duration, Instant};

const APP_STORAGE_KEY: &str = "diffgr_gui_config_v2";
const MAX_RECENT_DOCUMENTS: usize = 8;
const COMPACT_CHUNK_ROW_HEIGHT: f32 = 54.0;
const COMFORTABLE_CHUNK_ROW_HEIGHT: f32 = 66.0;
const GROUP_ROW_HEIGHT: f32 = 76.0;
const MIN_DIFF_ROW_HEIGHT: f32 = 22.0;

#[derive(Clone, Debug, Default)]
pub struct StartupArgs {
    pub path: Option<PathBuf>,
    pub state: Option<PathBuf>,
}

impl StartupArgs {
    pub fn from_env() -> Self {
        Self::from_iter(env::args().skip(1))
    }

    pub fn from_iter<I, S>(args: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let mut args = args.into_iter().map(Into::into);
        let mut out = StartupArgs::default();
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--state" => {
                    if let Some(value) = args.next() {
                        out.state = Some(PathBuf::from(value));
                    }
                }
                "--help" | "-h" => {
                    eprintln!(
                        "Usage: diffgr_gui [path/to/file.diffgr.json] [--state path/to/review.state.json]"
                    );
                }
                value if value.starts_with('-') => {
                    eprintln!("Ignoring unknown option: {value}");
                }
                value => {
                    if out.path.is_none() {
                        out.path = Some(PathBuf::from(value));
                    }
                }
            }
        }
        out
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
enum StatusFilter {
    All,
    Unreviewed,
    Reviewed,
    NeedsReReview,
    Ignored,
}

impl Default for StatusFilter {
    fn default() -> Self {
        StatusFilter::All
    }
}

impl StatusFilter {
    const ALL: [StatusFilter; 5] = [
        StatusFilter::All,
        StatusFilter::Unreviewed,
        StatusFilter::Reviewed,
        StatusFilter::NeedsReReview,
        StatusFilter::Ignored,
    ];

    fn label(self) -> &'static str {
        match self {
            StatusFilter::All => "すべて",
            StatusFilter::Unreviewed => "未レビュー",
            StatusFilter::Reviewed => "レビュー済み",
            StatusFilter::NeedsReReview => "再レビュー必要",
            StatusFilter::Ignored => "無視",
        }
    }

    fn as_review_status(self) -> Option<ReviewStatus> {
        match self {
            StatusFilter::All => None,
            StatusFilter::Unreviewed => Some(ReviewStatus::Unreviewed),
            StatusFilter::Reviewed => Some(ReviewStatus::Reviewed),
            StatusFilter::NeedsReReview => Some(ReviewStatus::NeedsReReview),
            StatusFilter::Ignored => Some(ReviewStatus::Ignored),
        }
    }

    fn from_analysis(value: Option<String>) -> Self {
        match value.as_deref() {
            Some("unreviewed") => StatusFilter::Unreviewed,
            Some("reviewed") => StatusFilter::Reviewed,
            Some("needsReReview") => StatusFilter::NeedsReReview,
            Some("ignored") => StatusFilter::Ignored,
            _ => StatusFilter::All,
        }
    }

    fn analysis_value(self) -> Option<&'static str> {
        self.as_review_status().map(ReviewStatus::as_str)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
enum SortMode {
    Natural,
    FilePath,
    Status,
    ChangeSize,
}

impl Default for SortMode {
    fn default() -> Self {
        SortMode::Natural
    }
}

impl SortMode {
    const ALL: [SortMode; 4] = [
        SortMode::Natural,
        SortMode::FilePath,
        SortMode::Status,
        SortMode::ChangeSize,
    ];

    fn label(self) -> &'static str {
        match self {
            SortMode::Natural => "元の順序",
            SortMode::FilePath => "ファイル名",
            SortMode::Status => "状態優先",
            SortMode::ChangeSize => "変更量が多い順",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
enum DetailTab {
    Diff,
    Review,
    Handoff,
    State,
}

impl Default for DetailTab {
    fn default() -> Self {
        DetailTab::Diff
    }
}

impl DetailTab {
    fn label(self) -> &'static str {
        match self {
            DetailTab::Diff => "Diff",
            DetailTab::Review => "レビュー",
            DetailTab::Handoff => "Handoff",
            DetailTab::State => "State JSON",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
enum ThemeMode {
    System,
    Dark,
    Light,
}

impl Default for ThemeMode {
    fn default() -> Self {
        ThemeMode::System
    }
}

impl ThemeMode {
    const ALL: [ThemeMode; 3] = [ThemeMode::System, ThemeMode::Dark, ThemeMode::Light];

    fn label(self) -> &'static str {
        match self {
            ThemeMode::System => "OS設定",
            ThemeMode::Dark => "ダーク",
            ThemeMode::Light => "ライト",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct RecentDocument {
    path: String,
    state_path: Option<String>,
    title: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
struct AppConfig {
    recent_documents: Vec<RecentDocument>,
    auto_load_last: bool,
    auto_pick_nearby_state: bool,
    auto_save_state: bool,
    auto_advance_after_review: bool,
    show_line_numbers: bool,
    show_only_changed: bool,
    wrap_diff: bool,
    only_with_comments: bool,
    reduce_motion: bool,
    compact_rows: bool,
    persist_egui_memory: bool,
    theme: ThemeMode,
    sort_mode: SortMode,
    detail_tab: DetailTab,
    workspace_root: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            recent_documents: Vec::new(),
            auto_load_last: false,
            auto_pick_nearby_state: true,
            auto_save_state: true,
            auto_advance_after_review: true,
            show_line_numbers: true,
            show_only_changed: false,
            wrap_diff: true,
            only_with_comments: false,
            reduce_motion: true,
            compact_rows: true,
            persist_egui_memory: false,
            theme: ThemeMode::System,
            sort_mode: SortMode::Natural,
            detail_tab: DetailTab::Diff,
            workspace_root: String::new(),
        }
    }
}

impl AppConfig {
    fn load(storage: Option<&dyn eframe::Storage>) -> Self {
        storage
            .and_then(|storage| storage.get_string(APP_STORAGE_KEY))
            .and_then(|json| serde_json::from_str(&json).ok())
            .unwrap_or_default()
    }

    fn save(&self, storage: &mut dyn eframe::Storage) {
        if let Ok(json) = serde_json::to_string(self) {
            storage.set_string(APP_STORAGE_KEY, json);
        }
    }

    fn remember_document(&mut self, path: &Path, state_path: Option<&Path>, title: Option<&str>) {
        let key = path.display().to_string();
        self.recent_documents.retain(|item| item.path != key);
        self.recent_documents.insert(
            0,
            RecentDocument {
                path: key,
                state_path: state_path.map(|path| path.display().to_string()),
                title: title.map(ToOwned::to_owned),
            },
        );
        self.recent_documents.truncate(MAX_RECENT_DOCUMENTS);
    }
}

#[derive(Clone, Debug)]
struct GroupRow {
    group_id: Option<String>,
    title: String,
    tags: String,
    metrics: GroupMetrics,
}

#[derive(Clone, Debug)]
struct ChunkRow {
    id: String,
    index: usize,
    file_path: String,
    old_range: String,
    new_range: String,
    adds: usize,
    deletes: usize,
    line_comments: usize,
    status: ReviewStatus,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct VisibleCacheKey {
    revision: u64,
    current_group: Option<String>,
    status_filter: StatusFilter,
    file_filter: String,
    content_filter: String,
    sort_mode: SortMode,
    only_with_comments: bool,
}

#[derive(Clone, Debug, Default)]
struct VisibleChunkCache {
    key: Option<VisibleCacheKey>,
    ids: Vec<String>,
    rows: Vec<ChunkRow>,
}

#[derive(Clone, Debug, Default)]
struct MetricsCache {
    revision: u64,
    metrics: Option<Metrics>,
    group_rows: Option<Vec<GroupRow>>,
}

#[derive(Clone, Debug, Default)]
struct StatePreviewCache {
    revision: u64,
    text: Option<String>,
}

pub struct DiffgrGuiApp {
    doc: Option<DiffgrDocument>,
    doc_path: Option<PathBuf>,
    state_path: Option<PathBuf>,
    path_input: String,
    state_input: String,
    workspace_root_input: String,
    current_group: Option<String>,
    selected_chunk: Option<String>,
    selected_line_anchor: Option<LineAnchor>,
    status_filter: StatusFilter,
    file_filter: String,
    content_filter: String,
    sort_mode: SortMode,
    detail_tab: DetailTab,
    comment_buffer: String,
    line_comment_buffer: String,
    group_brief_buffer: GroupBriefDraft,
    show_only_changed: bool,
    wrap_diff: bool,
    show_line_numbers: bool,
    only_with_comments: bool,
    auto_save_state: bool,
    auto_advance_after_review: bool,
    dirty: bool,
    message: String,
    show_help: bool,
    show_close_confirm: bool,
    force_close: bool,
    focus_search_next_frame: bool,
    last_auto_save: Instant,
    list_revision: u64,
    state_revision: u64,
    visible_cache: VisibleChunkCache,
    metrics_cache: MetricsCache,
    state_preview_cache: StatePreviewCache,
    last_window_title: String,
    config: AppConfig,
}

impl DiffgrGuiApp {
    pub fn new(args: StartupArgs, cc: &eframe::CreationContext<'_>) -> Self {
        let mut config = AppConfig::load(cc.storage);
        if env_flag("DIFFGR_LOW_MEMORY") {
            config.reduce_motion = true;
            config.compact_rows = true;
            config.persist_egui_memory = false;
            config.auto_load_last = false;
        }
        apply_runtime_style(&cc.egui_ctx, config.theme, config.reduce_motion);

        let startup_path = args.path.clone().or_else(|| {
            if config.auto_load_last {
                config
                    .recent_documents
                    .first()
                    .map(|recent| PathBuf::from(&recent.path))
            } else {
                None
            }
        });
        let startup_state = args.state.clone().or_else(|| {
            if args.path.is_none() && config.auto_load_last {
                config
                    .recent_documents
                    .first()
                    .and_then(|recent| recent.state_path.as_ref())
                    .map(|value| PathBuf::from(value.as_str()))
            } else {
                None
            }
        });

        let path_input = startup_path
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_default();
        let state_input = startup_state
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_default();

        let mut app = Self {
            doc: None,
            doc_path: startup_path.clone(),
            state_path: startup_state.clone(),
            path_input,
            state_input,
            workspace_root_input: config.workspace_root.clone(),
            current_group: None,
            selected_chunk: None,
            selected_line_anchor: None,
            status_filter: StatusFilter::All,
            file_filter: String::new(),
            content_filter: String::new(),
            sort_mode: config.sort_mode,
            detail_tab: config.detail_tab,
            comment_buffer: String::new(),
            line_comment_buffer: String::new(),
            group_brief_buffer: GroupBriefDraft::default(),
            show_only_changed: config.show_only_changed,
            wrap_diff: config.wrap_diff,
            show_line_numbers: config.show_line_numbers,
            only_with_comments: config.only_with_comments,
            auto_save_state: config.auto_save_state,
            auto_advance_after_review: config.auto_advance_after_review,
            dirty: false,
            message: String::new(),
            show_help: false,
            show_close_confirm: false,
            force_close: false,
            focus_search_next_frame: false,
            last_auto_save: Instant::now(),
            list_revision: 1,
            state_revision: 1,
            visible_cache: VisibleChunkCache::default(),
            metrics_cache: MetricsCache::default(),
            state_preview_cache: StatePreviewCache::default(),
            last_window_title: String::new(),
            config,
        };

        if let Some(path) = startup_path {
            app.open_document(path, startup_state);
        }
        app
    }

    fn open_document(&mut self, path: PathBuf, requested_state_path: Option<PathBuf>) {
        let state_path = requested_state_path.or_else(|| {
            if self.config.auto_pick_nearby_state {
                find_nearby_state_file(&path)
            } else {
                None
            }
        });

        match DiffgrDocument::load_from_path(&path, state_path.as_deref()) {
            Ok(doc) => {
                let title = doc.title.clone();
                self.doc = Some(doc);
                self.doc_path = Some(path.clone());
                self.state_path = state_path.clone();
                self.path_input = path.display().to_string();
                self.state_input = state_path
                    .as_ref()
                    .map(|path| path.display().to_string())
                    .unwrap_or_default();
                self.clear_all_volatile_caches();
                self.restore_ui_state_from_document();
                self.last_window_title.clear();
                self.dirty = false;
                self.config
                    .remember_document(&path, self.state_path.as_deref(), Some(&title));
                self.message = match state_path {
                    Some(state) => format!(
                        "読み込み完了: {} / state: {}",
                        path.display(),
                        state.display()
                    ),
                    None => format!("読み込み完了: {}", path.display()),
                };
            }
            Err(err) => {
                self.message = format!("読み込み失敗: {err}");
            }
        }
    }

    fn restore_ui_state_from_document(&mut self) {
        let Some(doc) = self.doc.as_ref() else {
            return;
        };

        self.status_filter = StatusFilter::from_analysis(doc.analysis_string("promptStatusFilter"));
        self.file_filter = doc.analysis_string("filterText").unwrap_or_default();
        self.content_filter = doc.analysis_string("contentSearchText").unwrap_or_default();

        let restored_group = doc
            .analysis_string("currentGroupId")
            .filter(|group_id| doc.group_by_id(group_id).is_some());
        self.current_group =
            restored_group.or_else(|| doc.groups.first().map(|group| group.id.clone()));

        let selected = doc
            .analysis_string("selectedChunkId")
            .filter(|chunk_id| doc.chunk_by_id(chunk_id).is_some())
            .or_else(|| self.first_visible_chunk_id());
        self.selected_chunk = selected;
        self.selected_line_anchor = doc.selected_line_anchor_from_state();
        self.reload_comment_buffer();
        self.reload_line_comment_buffer();
        self.reload_group_brief_buffer();
    }

    fn first_visible_chunk_id(&self) -> Option<String> {
        self.visible_chunk_ids_uncached().into_iter().next()
    }

    fn select_group(&mut self, group_id: Option<String>) {
        self.current_group = group_id.clone();
        if let Some(doc) = self.doc.as_mut() {
            doc.set_analysis_string("currentGroupId", group_id.as_deref());
        }
        self.invalidate_visible_cache();
        self.ensure_selected_chunk_visible();
        self.reload_group_brief_buffer();
        self.invalidate_state_preview_cache();
    }

    fn select_chunk(&mut self, chunk_id: Option<String>) {
        self.selected_chunk = chunk_id.clone();
        self.selected_line_anchor = None;
        self.line_comment_buffer.clear();
        if let Some(doc) = self.doc.as_mut() {
            doc.set_analysis_string("selectedChunkId", chunk_id.as_deref());
            doc.set_selected_line_anchor_state(None);
        }
        self.reload_comment_buffer();
        self.invalidate_state_preview_cache();
    }

    fn select_line_anchor(&mut self, anchor: LineAnchor) {
        self.selected_line_anchor = Some(anchor.clone());
        self.reload_line_comment_buffer();
        if let Some(doc) = self.doc.as_mut() {
            doc.set_selected_line_anchor_state(Some(&anchor));
        }
        self.invalidate_state_preview_cache();
    }

    fn ensure_selected_chunk_visible(&mut self) {
        let visible = self.visible_chunk_ids();
        let selected_still_visible = self
            .selected_chunk
            .as_ref()
            .map(|chunk_id| visible.contains(chunk_id))
            .unwrap_or(false);
        if !selected_still_visible {
            self.select_chunk(visible.into_iter().next());
        }
    }

    fn reload_comment_buffer(&mut self) {
        self.comment_buffer = self
            .doc
            .as_ref()
            .zip(self.selected_chunk.as_ref())
            .map(|(doc, chunk_id)| doc.comment_for(chunk_id))
            .unwrap_or_default();
    }

    fn reload_line_comment_buffer(&mut self) {
        self.line_comment_buffer = self
            .doc
            .as_ref()
            .zip(self.selected_chunk.as_ref())
            .zip(self.selected_line_anchor.as_ref())
            .map(|((doc, chunk_id), anchor)| doc.line_comment_for(chunk_id, anchor))
            .unwrap_or_default();
    }

    fn reload_group_brief_buffer(&mut self) {
        self.group_brief_buffer = self
            .doc
            .as_ref()
            .zip(self.current_group.as_ref())
            .map(|(doc, group_id)| doc.group_brief_draft(group_id))
            .unwrap_or_default();
    }

    fn set_status_filter(&mut self, filter: StatusFilter) {
        if self.status_filter == filter {
            return;
        }
        self.status_filter = filter;
        if let Some(doc) = self.doc.as_mut() {
            doc.set_analysis_string("promptStatusFilter", filter.analysis_value());
        }
        self.invalidate_visible_cache();
        self.ensure_selected_chunk_visible();
        self.invalidate_state_preview_cache();
    }

    fn set_file_filter(&mut self, filter: String) {
        if self.file_filter == filter {
            return;
        }
        self.file_filter = filter;
        let normalized = self.file_filter.trim().to_owned();
        if let Some(doc) = self.doc.as_mut() {
            doc.set_analysis_string(
                "filterText",
                (!normalized.is_empty()).then_some(normalized.as_str()),
            );
        }
        self.invalidate_visible_cache();
        self.ensure_selected_chunk_visible();
        self.invalidate_state_preview_cache();
    }

    fn set_content_filter(&mut self, filter: String) {
        if self.content_filter == filter {
            return;
        }
        self.content_filter = filter;
        let normalized = self.content_filter.trim().to_owned();
        if let Some(doc) = self.doc.as_mut() {
            doc.set_analysis_string(
                "contentSearchText",
                (!normalized.is_empty()).then_some(normalized.as_str()),
            );
        }
        self.invalidate_visible_cache();
        self.ensure_selected_chunk_visible();
        self.invalidate_state_preview_cache();
    }

    fn filtered_chunk_ids_unsorted(&self) -> Vec<String> {
        let Some(doc) = self.doc.as_ref() else {
            return Vec::new();
        };
        let status_filter = self.status_filter.as_review_status();
        let file_filter = self.file_filter.trim().to_lowercase();
        let content_filter = self.content_filter.trim().to_lowercase();
        doc.chunk_ids_for_group(self.current_group.as_deref())
            .into_iter()
            .filter(|chunk_id| {
                let Some(chunk) = doc.chunk_by_id(chunk_id) else {
                    return false;
                };
                if let Some(status) = status_filter {
                    if doc.status_for(chunk_id) != status {
                        return false;
                    }
                }
                if !file_filter.is_empty() && !chunk.file_path.to_lowercase().contains(&file_filter)
                {
                    return false;
                }
                if self.only_with_comments
                    && doc.comment_for(chunk_id).trim().is_empty()
                    && doc.line_comment_count_for(chunk_id) == 0
                {
                    return false;
                }
                if !content_filter.is_empty() && !chunk_matches_text(doc, chunk, &content_filter) {
                    return false;
                }
                true
            })
            .collect()
    }

    fn visible_chunk_ids_uncached(&self) -> Vec<String> {
        let mut ids = self.filtered_chunk_ids_unsorted();
        self.sort_chunk_ids(&mut ids);
        ids
    }

    fn visible_cache_key(&self) -> VisibleCacheKey {
        VisibleCacheKey {
            revision: self.list_revision,
            current_group: self.current_group.clone(),
            status_filter: self.status_filter,
            file_filter: self.file_filter.trim().to_lowercase(),
            content_filter: self.content_filter.trim().to_lowercase(),
            sort_mode: self.sort_mode,
            only_with_comments: self.only_with_comments,
        }
    }

    fn invalidate_visible_cache(&mut self) {
        self.list_revision = self.list_revision.wrapping_add(1);
        self.visible_cache = VisibleChunkCache::default();
    }

    fn invalidate_review_caches(&mut self) {
        self.list_revision = self.list_revision.wrapping_add(1);
        self.state_revision = self.state_revision.wrapping_add(1);
        self.visible_cache = VisibleChunkCache::default();
        self.metrics_cache = MetricsCache::default();
        self.state_preview_cache = StatePreviewCache::default();
    }

    fn invalidate_state_preview_cache(&mut self) {
        self.state_revision = self.state_revision.wrapping_add(1);
        self.state_preview_cache = StatePreviewCache::default();
    }

    fn clear_all_volatile_caches(&mut self) {
        self.list_revision = self.list_revision.wrapping_add(1);
        self.state_revision = self.state_revision.wrapping_add(1);
        self.visible_cache = VisibleChunkCache::default();
        self.metrics_cache = MetricsCache::default();
        self.state_preview_cache = StatePreviewCache::default();
    }

    fn ensure_visible_cache(&mut self) {
        let key = self.visible_cache_key();
        if self.visible_cache.key.as_ref() == Some(&key) {
            return;
        }

        let ids = self.visible_chunk_ids_uncached();
        let rows = self.build_chunk_rows_from_ids(&ids);
        self.visible_cache = VisibleChunkCache {
            key: Some(key),
            ids,
            rows,
        };
    }

    fn visible_chunk_ids(&mut self) -> Vec<String> {
        self.ensure_visible_cache();
        self.visible_cache.ids.clone()
    }

    fn build_chunk_rows_from_ids(&self, ids: &[String]) -> Vec<ChunkRow> {
        let Some(doc) = self.doc.as_ref() else {
            return Vec::new();
        };
        ids.iter()
            .enumerate()
            .filter_map(|(index, chunk_id)| {
                let chunk = doc.chunk_by_id(chunk_id)?;
                let (adds, deletes) = chunk.change_counts();
                Some(ChunkRow {
                    id: chunk.id.clone(),
                    index,
                    file_path: chunk.file_path.clone(),
                    old_range: chunk.old_range_label(),
                    new_range: chunk.new_range_label(),
                    adds,
                    deletes,
                    line_comments: doc.line_comment_count_for(&chunk.id),
                    status: doc.status_for(&chunk.id),
                })
            })
            .collect()
    }

    fn cached_chunk_row(&mut self, index: usize) -> Option<ChunkRow> {
        self.ensure_visible_cache();
        self.visible_cache.rows.get(index).cloned()
    }

    fn visible_chunk_count(&mut self) -> usize {
        self.ensure_visible_cache();
        self.visible_cache.rows.len()
    }

    fn sort_chunk_ids(&self, ids: &mut [String]) {
        let Some(doc) = self.doc.as_ref() else {
            return;
        };
        match self.sort_mode {
            SortMode::Natural => {}
            SortMode::FilePath => ids.sort_by(|left, right| {
                let left_chunk = doc.chunk_by_id(left);
                let right_chunk = doc.chunk_by_id(right);
                left_chunk
                    .map(|chunk| chunk.file_path.as_str())
                    .cmp(&right_chunk.map(|chunk| chunk.file_path.as_str()))
                    .then(left.cmp(right))
            }),
            SortMode::Status => ids.sort_by(|left, right| {
                status_sort_key(doc.status_for(left))
                    .cmp(&status_sort_key(doc.status_for(right)))
                    .then(left.cmp(right))
            }),
            SortMode::ChangeSize => ids.sort_by(|left, right| {
                let left_score = doc
                    .chunk_by_id(left)
                    .map(|chunk| {
                        let (adds, deletes) = chunk.change_counts();
                        adds + deletes
                    })
                    .unwrap_or(0);
                let right_score = doc
                    .chunk_by_id(right)
                    .map(|chunk| {
                        let (adds, deletes) = chunk.change_counts();
                        adds + deletes
                    })
                    .unwrap_or(0);
                right_score.cmp(&left_score).then(left.cmp(right))
            }),
        }
    }

    fn group_rows(&mut self) -> Vec<GroupRow> {
        if self.metrics_cache.revision != self.list_revision {
            self.metrics_cache.revision = self.list_revision;
            self.metrics_cache.metrics = None;
            self.metrics_cache.group_rows = None;
        }
        if let Some(rows) = self.metrics_cache.group_rows.as_ref() {
            return rows.clone();
        }

        let Some(doc) = self.doc.as_ref() else {
            return Vec::new();
        };
        let mut rows = Vec::new();
        rows.push(GroupRow {
            group_id: None,
            title: "すべてのグループ".to_owned(),
            tags: String::new(),
            metrics: doc.group_metrics(None),
        });
        rows.extend(doc.groups.iter().map(|group| GroupRow {
            group_id: Some(group.id.clone()),
            title: format!("{}  ({})", group.name, group.id),
            tags: group.tags.join(", "),
            metrics: doc.group_metrics(Some(&group.id)),
        }));
        self.metrics_cache.revision = self.list_revision;
        self.metrics_cache.group_rows = Some(rows.clone());
        rows
    }

    fn metrics(&mut self) -> Option<Metrics> {
        if self.metrics_cache.revision != self.list_revision {
            self.metrics_cache.revision = self.list_revision;
            self.metrics_cache.metrics = None;
            self.metrics_cache.group_rows = None;
        }
        if let Some(metrics) = self.metrics_cache.metrics.as_ref() {
            return Some(metrics.clone());
        }
        let metrics = self.doc.as_ref().map(DiffgrDocument::metrics)?;
        self.metrics_cache.revision = self.list_revision;
        self.metrics_cache.metrics = Some(metrics.clone());
        Some(metrics)
    }

    fn state_preview_text(&mut self) -> Option<String> {
        if self.state_preview_cache.revision == self.state_revision {
            if let Some(text) = self.state_preview_cache.text.as_ref() {
                return Some(text.clone());
            }
        }
        let text = self.doc.as_ref().map(|doc| {
            serde_json::to_string_pretty(&doc.extract_state()).unwrap_or_else(|err| err.to_string())
        })?;
        self.state_preview_cache.revision = self.state_revision;
        self.state_preview_cache.text = Some(text.clone());
        Some(text)
    }

    fn selected_chunk_clone(&self) -> Option<Chunk> {
        self.doc
            .as_ref()
            .zip(self.selected_chunk.as_ref())
            .and_then(|(doc, chunk_id)| doc.chunk_by_id(chunk_id))
            .cloned()
    }

    fn selected_visible_index(&mut self) -> Option<(usize, usize)> {
        let visible = self.visible_chunk_ids();
        let total = visible.len();
        let selected = self.selected_chunk.as_ref()?;
        visible
            .iter()
            .position(|chunk_id| chunk_id == selected)
            .map(|index| (index, total))
    }

    fn save_current(&mut self) {
        let Some(doc) = self.doc.as_ref() else {
            self.message = "保存対象のDiffGRがありません。".to_owned();
            return;
        };
        let result = if let Some(state_path) = self.state_path.as_ref() {
            doc.write_state(state_path)
                .map(|_| format!("state保存: {}", state_path.display()))
        } else if let Some(doc_path) = self.doc_path.as_ref() {
            doc.write_full_document(doc_path, true)
                .map(|_| format!("DiffGR保存: {}", doc_path.display()))
        } else {
            Err("保存先が未設定です。State保存先… を使ってください。".to_owned())
        };
        match result {
            Ok(message) => {
                self.dirty = false;
                self.message = message;
            }
            Err(err) => {
                self.message = format!("保存失敗: {err}");
            }
        }
    }

    fn save_state_as(&mut self) {
        let default_path = self
            .doc_path
            .as_ref()
            .and_then(|path| path.parent().map(|parent| parent.join("review.state.json")));
        let mut dialog = FileDialog::new()
            .add_filter("DiffGR review state", &["json"])
            .set_file_name("review.state.json");
        if let Some(default_path) = default_path.as_ref().and_then(|path| path.parent()) {
            dialog = dialog.set_directory(default_path);
        }
        let Some(path) = dialog.save_file() else {
            return;
        };
        self.write_state_to(path);
    }

    fn write_state_to(&mut self, path: PathBuf) {
        let result = self
            .doc
            .as_ref()
            .map(|doc| doc.write_state(&path))
            .unwrap_or_else(|| Err("保存対象のDiffGRがありません。".to_owned()));
        match result {
            Ok(()) => {
                self.state_path = Some(path.clone());
                self.state_input = path.display().to_string();
                if let (Some(doc_path), Some(doc)) = (self.doc_path.as_ref(), self.doc.as_ref()) {
                    self.config.remember_document(
                        doc_path,
                        self.state_path.as_deref(),
                        Some(&doc.title),
                    );
                }
                self.dirty = false;
                self.message = format!("state保存: {}", path.display());
            }
            Err(err) => self.message = format!("state保存失敗: {err}"),
        }
    }

    fn create_state_next_to_diff(&mut self) {
        let Some(doc_path) = self.doc_path.as_ref() else {
            self.message = "先にDiffGR JSONを開いてください。".to_owned();
            return;
        };
        let path = doc_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join("review.state.json");
        self.write_state_to(path);
    }

    fn load_state_into_current_document(&mut self, path: PathBuf) {
        let Some(doc) = self.doc.as_mut() else {
            self.message = "先にDiffGR JSONを開いてください。".to_owned();
            return;
        };
        match doc.apply_state_file(&path) {
            Ok(()) => {
                self.state_path = Some(path.clone());
                self.state_input = path.display().to_string();
                self.clear_all_volatile_caches();
                self.restore_ui_state_from_document();
                self.last_window_title.clear();
                self.dirty = false;
                if let (Some(doc_path), Some(doc)) = (self.doc_path.as_ref(), self.doc.as_ref()) {
                    self.config.remember_document(
                        doc_path,
                        self.state_path.as_deref(),
                        Some(&doc.title),
                    );
                }
                self.message = format!("state読み込み: {}", path.display());
            }
            Err(err) => self.message = format!("state読み込み失敗: {err}"),
        }
    }

    fn toggle_selected_reviewed(&mut self) {
        let Some(chunk_id) = self.selected_chunk.clone() else {
            return;
        };
        let Some(doc) = self.doc.as_mut() else {
            return;
        };
        let next = doc.status_for(&chunk_id).next_review_toggle();
        doc.set_status(&chunk_id, next);
        self.dirty = true;
        self.invalidate_review_caches();
        if self.auto_advance_after_review && next == ReviewStatus::Reviewed {
            self.select_next_pending_or_next();
        }
    }

    fn set_selected_status(&mut self, status: ReviewStatus) {
        let Some(chunk_id) = self.selected_chunk.clone() else {
            return;
        };
        let Some(doc) = self.doc.as_mut() else {
            return;
        };
        doc.set_status(&chunk_id, status);
        self.dirty = true;
        self.invalidate_review_caches();
        if self.auto_advance_after_review && status == ReviewStatus::Reviewed {
            self.select_next_pending_or_next();
        }
    }

    fn select_next_chunk(&mut self) {
        self.select_relative_chunk(1);
    }

    fn select_previous_chunk(&mut self) {
        self.select_relative_chunk(-1);
    }

    fn select_relative_chunk(&mut self, delta: isize) {
        let ids = self.visible_chunk_ids();
        if ids.is_empty() {
            self.select_chunk(None);
            return;
        }
        let current = self
            .selected_chunk
            .as_ref()
            .and_then(|selected| ids.iter().position(|chunk_id| chunk_id == selected))
            .unwrap_or(0);
        let len = ids.len() as isize;
        let next = ((current as isize + delta).rem_euclid(len)) as usize;
        self.select_chunk(Some(ids[next].clone()));
    }

    fn select_next_pending_or_next(&mut self) {
        if self
            .select_next_matching_status(&[ReviewStatus::Unreviewed, ReviewStatus::NeedsReReview])
        {
            return;
        }
        self.select_next_chunk();
    }

    fn select_next_matching_status(&mut self, statuses: &[ReviewStatus]) -> bool {
        let ids = self.visible_chunk_ids();
        if ids.is_empty() {
            return false;
        }
        let start = self
            .selected_chunk
            .as_ref()
            .and_then(|selected| ids.iter().position(|chunk_id| chunk_id == selected))
            .unwrap_or(0);
        for offset in 1..=ids.len() {
            let index = (start + offset) % ids.len();
            let matches = self
                .doc
                .as_ref()
                .map(|doc| statuses.contains(&doc.status_for(&ids[index])))
                .unwrap_or(false);
            if matches {
                let next = ids[index].clone();
                self.select_chunk(Some(next));
                return true;
            }
        }
        false
    }

    fn mark_visible_as_reviewed(&mut self) {
        let ids = self.visible_chunk_ids();
        if ids.is_empty() {
            self.message = "対象チャンクがありません。".to_owned();
            return;
        }
        if let Some(doc) = self.doc.as_mut() {
            for chunk_id in &ids {
                doc.set_status(chunk_id, ReviewStatus::Reviewed);
            }
            self.dirty = true;
            self.invalidate_review_caches();
            self.message = format!("表示中の{}チャンクをレビュー済みにしました。", ids.len());
        }
    }

    fn handle_shortcuts(&mut self, ui: &mut egui::Ui) {
        let ctx = ui.ctx();
        let save_as_pressed = ui.input(|input| {
            input.modifiers.command && input.modifiers.shift && input.key_pressed(egui::Key::S)
        });
        if save_as_pressed {
            self.save_state_as();
            return;
        }
        let save_pressed =
            ui.input(|input| input.modifiers.command && input.key_pressed(egui::Key::S));
        if save_pressed {
            self.save_current();
        }
        let open_pressed =
            ui.input(|input| input.modifiers.command && input.key_pressed(egui::Key::O));
        if open_pressed {
            self.pick_and_open_document();
        }
        let find_pressed =
            ui.input(|input| input.modifiers.command && input.key_pressed(egui::Key::F));
        if find_pressed {
            self.focus_search_next_frame = true;
        }
        let help_pressed = ui.input(|input| input.key_pressed(egui::Key::F1));
        if help_pressed {
            self.show_help = !self.show_help;
        }

        if ctx.wants_keyboard_input() {
            return;
        }

        if ui.input(|input| input.key_pressed(egui::Key::Space)) {
            self.toggle_selected_reviewed();
        }
        if ui.input(|input| {
            input.key_pressed(egui::Key::J) || input.key_pressed(egui::Key::ArrowDown)
        }) {
            self.select_next_chunk();
        }
        if ui
            .input(|input| input.key_pressed(egui::Key::K) || input.key_pressed(egui::Key::ArrowUp))
        {
            self.select_previous_chunk();
        }
        if ui.input(|input| input.key_pressed(egui::Key::N)) {
            self.select_next_pending_or_next();
        }
        if ui.input(|input| input.key_pressed(egui::Key::R)) {
            self.set_selected_status(ReviewStatus::Reviewed);
        }
        if ui.input(|input| input.key_pressed(egui::Key::I)) {
            self.set_selected_status(ReviewStatus::Ignored);
        }
    }

    fn handle_dropped_files(&mut self, ui: &mut egui::Ui) {
        let dropped_files = ui.input(|input| input.raw.dropped_files.clone());
        for file in dropped_files {
            if let Some(path) = file.path {
                let lower = path.display().to_string().to_lowercase();
                if lower.contains("state") && self.doc.is_some() {
                    self.load_state_into_current_document(path);
                } else {
                    self.open_document(path, None);
                }
            }
        }
    }

    fn maybe_auto_save(&mut self) {
        if !self.auto_save_state || !self.dirty {
            return;
        }
        if self.state_path.is_none() {
            return;
        }
        if self.last_auto_save.elapsed() < Duration::from_secs(30) {
            return;
        }
        self.last_auto_save = Instant::now();
        let Some(state_path) = self.state_path.clone() else {
            return;
        };
        let result = self
            .doc
            .as_ref()
            .map(|doc| doc.write_state(&state_path))
            .unwrap_or_else(|| Err("保存対象のDiffGRがありません。".to_owned()));
        match result {
            Ok(()) => {
                self.dirty = false;
                self.message = format!("自動保存: {}", state_path.display());
            }
            Err(err) => {
                self.message = format!("自動保存失敗: {err}");
            }
        }
    }

    fn pick_and_open_document(&mut self) {
        if let Some(path) = FileDialog::new()
            .add_filter("DiffGR JSON", &["json"])
            .pick_file()
        {
            self.open_document(path, None);
        }
    }

    fn pick_and_load_state(&mut self) {
        if let Some(path) = FileDialog::new()
            .add_filter("Review state", &["json"])
            .pick_file()
        {
            self.load_state_into_current_document(path);
        }
    }

    fn pick_workspace_root(&mut self) {
        if let Some(path) = FileDialog::new().pick_folder() {
            self.workspace_root_input = path.display().to_string();
            self.config.workspace_root = self.workspace_root_input.clone();
        }
    }

    fn draw_top_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            ui.heading("DiffGR Review");
            if self.dirty {
                ui.label(RichText::new("● 未保存").color(Color32::YELLOW));
            } else {
                ui.label(RichText::new("● 保存済み").color(Color32::LIGHT_GREEN));
            }
            if let Some((index, total)) = self.selected_visible_index() {
                ui.separator();
                ui.label(format!("{}/{}", index + 1, total));
            }
            ui.separator();
            if ui.button("開く Ctrl+O").clicked() {
                self.pick_and_open_document();
            }
            if ui.button("保存 Ctrl+S").clicked() {
                self.save_current();
            }
            if ui.button("State保存先…").clicked() {
                self.save_state_as();
            }
            if ui.button("ヘルプ F1").clicked() {
                self.show_help = !self.show_help;
            }
        });

        ui.horizontal_wrapped(|ui| {
            ui.label("DiffGR");
            ui.add_sized([420.0, 24.0], TextEdit::singleline(&mut self.path_input));
            if ui.button("読込").clicked() {
                let path = PathBuf::from(self.path_input.trim());
                let state = parse_optional_path(&self.state_input);
                self.open_document(path, state);
            }
            if ui.small_button("フォルダ").clicked() {
                if let Some(path) = self.doc_path.clone() {
                    self.reveal_path(&path);
                }
            }
            ui.separator();
            ui.label("State");
            ui.add_sized([360.0, 24.0], TextEdit::singleline(&mut self.state_input));
            if ui.button("State読込").clicked() {
                if let Some(path) = parse_optional_path(&self.state_input) {
                    self.load_state_into_current_document(path);
                } else {
                    self.pick_and_load_state();
                }
            }
            if ui.small_button("新規State").clicked() {
                self.create_state_next_to_diff();
            }
            if ui.small_button("解除").clicked() {
                self.state_path = None;
                self.state_input.clear();
                self.message =
                    "state保存先を解除しました。保存は元のDiffGR JSONへ行われます。".to_owned();
            }
        });

        ui.horizontal_wrapped(|ui| {
            ui.label("作業ルート");
            ui.add_sized([360.0, 24.0], TextEdit::singleline(&mut self.workspace_root_input));
            if ui.small_button("選択…").clicked() {
                self.pick_workspace_root();
            }
            if ui.small_button("適用").clicked() {
                self.config.workspace_root = self.workspace_root_input.trim().to_owned();
            }
            ui.separator();
            ui.checkbox(&mut self.auto_save_state, "state自動保存");
            ui.checkbox(&mut self.auto_advance_after_review, "レビュー済みで次へ");
            ui.separator();
            if ui.checkbox(&mut self.config.reduce_motion, "ちらつき抑制").changed() {
                apply_runtime_style(ui.ctx(), self.config.theme, self.config.reduce_motion);
            }
            ui.checkbox(&mut self.config.compact_rows, "コンパクト行");
            ui.checkbox(&mut self.config.persist_egui_memory, "UI状態を記憶")
                .on_hover_text("オフ推奨: eguiの細かなUIメモリを保存せず、設定と最近使ったファイルだけ保存します。");
            ui.separator();
            let mut theme = self.config.theme;
            egui::ComboBox::from_id_salt("theme_mode")
                .selected_text(theme.label())
                .show_ui(ui, |ui| {
                    for mode in ThemeMode::ALL {
                        ui.selectable_value(&mut theme, mode, mode.label());
                    }
                });
            if theme != self.config.theme {
                self.config.theme = theme;
                apply_runtime_style(ui.ctx(), theme, self.config.reduce_motion);
            }
        });
    }

    fn draw_metrics(&mut self, ui: &mut egui::Ui) {
        let Some(title) = self.doc.as_ref().map(|doc| doc.title.clone()) else {
            return;
        };
        let warnings = self
            .doc
            .as_ref()
            .map(|doc| doc.warnings.clone())
            .unwrap_or_default();
        let Some(metrics) = self.metrics() else {
            return;
        };
        ui.horizontal_wrapped(|ui| {
            ui.label(RichText::new(title).strong());
            ui.separator();
            ui.add(
                ProgressBar::new(metrics.coverage_rate)
                    .desired_width(180.0)
                    .text(format!("{:.1}%", metrics.coverage_rate * 100.0)),
            );
            ui.label(format!("レビュー済み: {}", metrics.reviewed));
            ui.label(format!("未完了: {}", metrics.pending));
            ui.label(format!("追跡対象: {}", metrics.tracked));
            ui.label(format!("未割当: {}", metrics.unassigned));
        });
        if !warnings.is_empty() {
            egui::CollapsingHeader::new(format!("警告 {}件", warnings.len()))
                .default_open(false)
                .show(ui, |ui| {
                    for warning in &warnings {
                        ui.label(RichText::new(warning).color(Color32::YELLOW));
                    }
                });
        }
    }

    fn draw_filters(&mut self, ui: &mut egui::Ui) {
        let mut next_status = self.status_filter;
        let mut next_sort = self.sort_mode;
        ui.horizontal_wrapped(|ui| {
            ui.label("状態");
            egui::ComboBox::from_id_salt("status_filter")
                .selected_text(next_status.label())
                .show_ui(ui, |ui| {
                    for filter in StatusFilter::ALL {
                        ui.selectable_value(&mut next_status, filter, filter.label());
                    }
                });
            ui.label("並び");
            egui::ComboBox::from_id_salt("sort_mode")
                .selected_text(next_sort.label())
                .show_ui(ui, |ui| {
                    for sort in SortMode::ALL {
                        ui.selectable_value(&mut next_sort, sort, sort.label());
                    }
                });
        });
        if next_status != self.status_filter {
            self.set_status_filter(next_status);
        }
        if next_sort != self.sort_mode {
            self.sort_mode = next_sort;
            self.config.sort_mode = next_sort;
            self.invalidate_visible_cache();
            self.ensure_selected_chunk_visible();
        }

        ui.horizontal(|ui| {
            ui.label("Path");
            let mut next_file_filter = self.file_filter.clone();
            let response = ui.add_sized(
                [f32::INFINITY, 24.0],
                TextEdit::singleline(&mut next_file_filter).hint_text("ファイルパスで絞り込み"),
            );
            if response.changed() {
                self.set_file_filter(next_file_filter);
            }
        });
        ui.horizontal(|ui| {
            ui.label("検索");
            let mut next_content_filter = self.content_filter.clone();
            let response = ui.add_sized(
                [f32::INFINITY, 24.0],
                TextEdit::singleline(&mut next_content_filter)
                    .hint_text("ID / diff本文 / コメント"),
            );
            if self.focus_search_next_frame {
                response.request_focus();
                self.focus_search_next_frame = false;
            }
            if response.changed() {
                self.set_content_filter(next_content_filter);
            }
        });
        ui.horizontal_wrapped(|ui| {
            if ui
                .checkbox(&mut self.only_with_comments, "コメント付きのみ")
                .changed()
            {
                self.config.only_with_comments = self.only_with_comments;
                self.invalidate_visible_cache();
                self.ensure_selected_chunk_visible();
            }
            if ui.button("フィルタ解除").clicked() {
                self.set_status_filter(StatusFilter::All);
                self.set_file_filter(String::new());
                self.set_content_filter(String::new());
                self.only_with_comments = false;
                self.config.only_with_comments = false;
                self.invalidate_visible_cache();
                self.ensure_selected_chunk_visible();
            }
        });
    }

    fn draw_groups(&mut self, ui: &mut egui::Ui) {
        ui.heading("Groups");
        ui.small("グループごとの進捗。クリックで絞り込み。");
        ui.separator();
        let rows = self.group_rows();
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .animated(!self.config.reduce_motion)
            .show_rows(ui, GROUP_ROW_HEIGHT, rows.len(), |ui, row_range| {
                for index in row_range {
                    let row = rows[index].clone();
                    let selected = self.current_group == row.group_id;
                    let coverage = if row.metrics.tracked == 0 {
                        1.0
                    } else {
                        row.metrics.reviewed as f32 / row.metrics.tracked as f32
                    };
                    if ui
                        .selectable_label(selected, RichText::new(row.title.clone()).strong())
                        .clicked()
                    {
                        self.select_group(row.group_id.clone());
                    }
                    ui.add(
                        ProgressBar::new(coverage)
                            .desired_width(f32::INFINITY)
                            .text(format!(
                                "{}/{} reviewed",
                                row.metrics.reviewed, row.metrics.tracked
                            )),
                    );
                    if !row.tags.is_empty() {
                        ui.small(format!("tags: {}", row.tags));
                    }
                    ui.separator();
                }
            });
    }

    fn draw_chunks(&mut self, ui: &mut egui::Ui) {
        ui.heading("Chunks");
        self.draw_filters(ui);
        ui.separator();
        let total_rows = self.visible_chunk_count();
        ui.horizontal_wrapped(|ui| {
            ui.label(format!("表示中: {} chunks", total_rows));
            if ui.button("次の未完了 N").clicked() {
                self.select_next_pending_or_next();
            }
            if ui.button("表示中をレビュー済み").clicked() {
                self.mark_visible_as_reviewed();
            }
        });

        let row_height = if self.config.compact_rows {
            COMPACT_CHUNK_ROW_HEIGHT
        } else {
            COMFORTABLE_CHUNK_ROW_HEIGHT
        };
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .animated(!self.config.reduce_motion)
            .show_rows(ui, row_height, total_rows, |ui, row_range| {
                for index in row_range {
                    let Some(row) = self.cached_chunk_row(index) else {
                        continue;
                    };
                    let selected = self.selected_chunk.as_deref() == Some(row.id.as_str());
                    ui.horizontal(|ui| {
                        ui.label(status_badge(row.status));
                        let comment_mark = if row.line_comments > 0 {
                            format!(" 💬{}", row.line_comments)
                        } else {
                            String::new()
                        };
                        let title = format!(
                            "#{} {}  +{} -{}  old:{} new:{}{}",
                            row.index + 1,
                            short_id(&row.id),
                            row.adds,
                            row.deletes,
                            row.old_range,
                            row.new_range,
                            comment_mark,
                        );
                        if ui.selectable_label(selected, title).clicked() {
                            self.select_chunk(Some(row.id.clone()));
                        }
                    });
                    ui.small(&row.file_path);
                    ui.separator();
                }
            });
    }

    fn draw_detail(&mut self, ui: &mut egui::Ui) {
        let Some(chunk) = self.selected_chunk_clone() else {
            ui.heading("Detail");
            ui.label("チャンクを選択してください。");
            return;
        };
        let chunk_id = chunk.id.clone();
        ui.horizontal_wrapped(|ui| {
            ui.heading("Detail");
            ui.separator();
            ui.label(RichText::new(&chunk.file_path).strong());
            ui.small(format!(
                "id: {}  old:{}  new:{}",
                chunk.short_id(),
                chunk.old_range_label(),
                chunk.new_range_label()
            ));
        });
        ui.horizontal_wrapped(|ui| {
            for tab in [
                DetailTab::Diff,
                DetailTab::Review,
                DetailTab::Handoff,
                DetailTab::State,
            ] {
                ui.selectable_value(&mut self.detail_tab, tab, tab.label());
            }
        });
        self.config.detail_tab = self.detail_tab;
        ui.separator();

        match self.detail_tab {
            DetailTab::Diff => {
                self.draw_chunk_status_editor(ui, &chunk_id);
                self.draw_diff_toolbar(ui, &chunk);
                self.draw_diff_lines(ui, &chunk);
            }
            DetailTab::Review => {
                self.draw_chunk_status_editor(ui, &chunk_id);
                self.draw_chunk_comment_editor(ui, &chunk_id);
                self.draw_line_comment_editor(ui, &chunk_id);
            }
            DetailTab::Handoff => {
                self.draw_group_brief_editor(ui);
            }
            DetailTab::State => {
                self.draw_state_preview(ui);
            }
        }
    }

    fn draw_chunk_status_editor(&mut self, ui: &mut egui::Ui, chunk_id: &str) {
        let current_status = self
            .doc
            .as_ref()
            .map(|doc| doc.status_for(chunk_id))
            .unwrap_or(ReviewStatus::Unreviewed);
        let mut next_status = current_status;
        ui.horizontal_wrapped(|ui| {
            ui.label("Status:");
            egui::ComboBox::from_id_salt("chunk_status")
                .selected_text(current_status.label())
                .show_ui(ui, |ui| {
                    for status in ReviewStatus::ALL {
                        ui.selectable_value(&mut next_status, status, status.label());
                    }
                });
            if ui.button("レビュー済み Space").clicked() {
                next_status = ReviewStatus::Reviewed;
            }
            if ui.button("再レビュー").clicked() {
                next_status = ReviewStatus::NeedsReReview;
            }
            if ui.button("無視 I").clicked() {
                next_status = ReviewStatus::Ignored;
            }
            if ui.button("未レビュー").clicked() {
                next_status = ReviewStatus::Unreviewed;
            }
            if ui.button("実ファイルを開く").clicked() {
                if let Some(chunk) = self.selected_chunk_clone() {
                    self.open_source_file(&chunk.file_path);
                }
            }
            if ui.button("場所を表示").clicked() {
                if let Some(chunk) = self.selected_chunk_clone() {
                    let path = self.resolve_source_path(&chunk.file_path);
                    self.reveal_path(&path);
                }
            }
        });
        if next_status != current_status {
            self.set_selected_status(next_status);
        }
    }

    fn draw_chunk_comment_editor(&mut self, ui: &mut egui::Ui, chunk_id: &str) {
        ui.label("Chunk comment:");
        let response = ui.add(
            TextEdit::multiline(&mut self.comment_buffer)
                .hint_text("チャンク全体のレビューコメント")
                .desired_rows(5)
                .desired_width(f32::INFINITY),
        );
        if response.changed() {
            if let Some(doc) = self.doc.as_mut() {
                doc.set_comment(chunk_id, &self.comment_buffer);
                self.dirty = true;
                self.invalidate_review_caches();
            }
        }
    }

    fn draw_diff_toolbar(&mut self, ui: &mut egui::Ui, chunk: &Chunk) {
        let (adds, deletes) = chunk.change_counts();
        ui.horizontal_wrapped(|ui| {
            ui.label(format!(
                "Diff lines: {}  +{} -{}",
                chunk.lines.len(),
                adds,
                deletes
            ));
            if ui
                .checkbox(&mut self.show_only_changed, "変更行のみ")
                .changed()
            {
                self.config.show_only_changed = self.show_only_changed;
            }
            if ui.checkbox(&mut self.wrap_diff, "折り返し").changed() {
                self.config.wrap_diff = self.wrap_diff;
            }
            if ui.checkbox(&mut self.show_line_numbers, "行番号").changed() {
                self.config.show_line_numbers = self.show_line_numbers;
            }
            if ui.button("このチャンク情報をコピー").clicked() {
                let text = self.chunk_clipboard_text(chunk);
                ui.ctx().copy_text(text);
                self.message = "チャンク情報をクリップボードへコピーしました。".to_owned();
            }
        });
    }

    fn draw_diff_lines(&mut self, ui: &mut egui::Ui, chunk: &Chunk) {
        let chunk_id = chunk.id.clone();
        let max_height = (ui.available_height() - 12.0).max(280.0);
        let changed_indices: Vec<usize> = if self.show_only_changed {
            chunk
                .lines
                .iter()
                .enumerate()
                .filter_map(|(index, line)| (line.kind != "context").then_some(index))
                .collect()
        } else {
            Vec::new()
        };
        let total_rows = if self.show_only_changed {
            changed_indices.len()
        } else {
            chunk.lines.len()
        };
        if total_rows == 0 {
            ui.small("表示対象のdiff行がありません。");
            return;
        }

        let row_height =
            (ui.text_style_height(&egui::TextStyle::Monospace) + ui.spacing().item_spacing.y + 4.0)
                .max(MIN_DIFF_ROW_HEIGHT);
        let mut scroll = if self.wrap_diff {
            egui::ScrollArea::vertical().max_height(max_height)
        } else {
            egui::ScrollArea::both().max_height(max_height)
        };
        scroll = scroll
            .auto_shrink([false, false])
            .animated(!self.config.reduce_motion);
        scroll.show_rows(ui, row_height, total_rows, |ui, row_range| {
            for row in row_range {
                let line_index = if self.show_only_changed {
                    changed_indices[row]
                } else {
                    row
                };
                let Some(line) = chunk.lines.get(line_index) else {
                    continue;
                };
                self.draw_one_diff_line(ui, &chunk_id, line);
            }
        });
    }

    fn draw_one_diff_line(&mut self, ui: &mut egui::Ui, chunk_id: &str, line: &DiffLine) {
        let anchor = line.anchor();
        let selected = self.selected_line_anchor.as_ref() == Some(&anchor);
        let existing_comment = self
            .doc
            .as_ref()
            .map(|doc| doc.line_comment_for(chunk_id, &anchor))
            .unwrap_or_default();
        let comment_mark = if existing_comment.is_empty() {
            ""
        } else {
            "  💬"
        };
        let rendered = if self.show_line_numbers {
            let old_line = line
                .old_line
                .map(|n| n.to_string())
                .unwrap_or_else(|| "-".to_owned());
            let new_line = line
                .new_line
                .map(|n| n.to_string())
                .unwrap_or_else(|| "-".to_owned());
            format!(
                "{:>5} {:>5} {} {}{}",
                old_line,
                new_line,
                line.prefix(),
                line.text,
                comment_mark
            )
        } else {
            format!("{} {}{}", line.prefix(), line.text, comment_mark)
        };
        let text = RichText::new(rendered)
            .monospace()
            .color(color_for_line(&line.kind));
        let response = ui.selectable_label(selected, text);
        let clicked = response.clicked();
        if !existing_comment.is_empty() {
            response.on_hover_text(existing_comment);
        }
        if clicked {
            self.select_line_anchor(anchor);
        }
    }

    fn draw_line_comment_editor(&mut self, ui: &mut egui::Ui, chunk_id: &str) {
        ui.separator();
        let Some(anchor) = self.selected_line_anchor.clone() else {
            ui.small("Diffタブで行をクリックすると line comment を編集できます。");
            return;
        };
        ui.label(format!("Line comment: {}", anchor.label()));
        let response = ui.add(
            TextEdit::multiline(&mut self.line_comment_buffer)
                .hint_text("選択行へのコメント")
                .desired_rows(4)
                .desired_width(f32::INFINITY),
        );
        if response.changed() {
            if let Some(doc) = self.doc.as_mut() {
                doc.set_line_comment(chunk_id, &anchor, &self.line_comment_buffer);
                self.dirty = true;
                self.invalidate_review_caches();
            }
        }
        ui.horizontal(|ui| {
            if ui.button("コメント削除").clicked() {
                self.line_comment_buffer.clear();
                if let Some(doc) = self.doc.as_mut() {
                    doc.set_line_comment(chunk_id, &anchor, "");
                    self.dirty = true;
                    self.invalidate_review_caches();
                }
            }
            if ui.button("Diffタブへ").clicked() {
                self.detail_tab = DetailTab::Diff;
            }
        });
    }

    fn draw_group_brief_editor(&mut self, ui: &mut egui::Ui) {
        let Some(group_id) = self.current_group.clone() else {
            ui.label("左のGroupsからグループを選ぶとHandoffを編集できます。");
            return;
        };
        let title = self
            .doc
            .as_ref()
            .and_then(|doc| doc.group_by_id(&group_id))
            .map(|group| format!("Review Handoff: {}", group.name))
            .unwrap_or_else(|| "Review Handoff".to_owned());
        ui.heading(title);
        ui.horizontal(|ui| {
            ui.label("Status:");
            egui::ComboBox::from_id_salt("brief_status")
                .selected_text(&self.group_brief_buffer.status)
                .show_ui(ui, |ui| {
                    for status in ["draft", "ready", "acknowledged", "stale"] {
                        ui.selectable_value(
                            &mut self.group_brief_buffer.status,
                            status.to_owned(),
                            status,
                        );
                    }
                });
            if ui.button("Handoff適用").clicked() {
                if let Some(doc) = self.doc.as_mut() {
                    doc.set_group_brief_from_draft(&group_id, &self.group_brief_buffer);
                    self.dirty = true;
                    self.invalidate_state_preview_cache();
                    self.message = format!("Handoff更新: {}", group_id);
                }
            }
            if ui.button("再読み込み").clicked() {
                self.reload_group_brief_buffer();
            }
        });
        egui::ScrollArea::vertical().show(ui, |ui| {
            labeled_multiline(ui, "Summary", &mut self.group_brief_buffer.summary, 4);
            labeled_singleline(ui, "updatedAt", &mut self.group_brief_buffer.updated_at);
            labeled_singleline(ui, "sourceHead", &mut self.group_brief_buffer.source_head);
            ui.small("リスト項目は ` | ` 区切りで入力します。");
            labeled_singleline(
                ui,
                "Focus points",
                &mut self.group_brief_buffer.focus_points,
            );
            labeled_singleline(
                ui,
                "Test evidence",
                &mut self.group_brief_buffer.test_evidence,
            );
            labeled_singleline(
                ui,
                "Known tradeoffs",
                &mut self.group_brief_buffer.known_tradeoffs,
            );
            labeled_singleline(
                ui,
                "Questions",
                &mut self.group_brief_buffer.questions_for_reviewer,
            );
            labeled_singleline(ui, "Mentions", &mut self.group_brief_buffer.mentions);
        });
    }

    fn draw_state_preview(&mut self, ui: &mut egui::Ui) {
        let Some(preview) = self.state_preview_text() else {
            return;
        };
        ui.horizontal_wrapped(|ui| {
            ui.small("プレビューは1件だけの揮発キャッシュです。編集時に破棄され、ファイルには保存されません。");
            if ui.button("State JSONをコピー").clicked() {
                ui.ctx().copy_text(preview.clone());
                self.message = "State JSONをクリップボードへコピーしました。".to_owned();
            }
            if ui.button("State保存先…").clicked() {
                self.save_state_as();
            }
        });
        egui::ScrollArea::both()
            .auto_shrink([false, false])
            .animated(!self.config.reduce_motion)
            .show(ui, |ui| {
                ui.monospace(preview);
            });
    }

    fn draw_empty(&mut self, ui: &mut egui::Ui) {
        ui.vertical_centered(|ui| {
            ui.add_space(60.0);
            ui.heading("DiffGR JSONを開いてください");
            ui.label("ファイルをドラッグ&ドロップ、または Ctrl+O / 開く ボタンから選択できます。");
            ui.add_space(12.0);
            if ui.button("DiffGR JSONを開く…").clicked() {
                self.pick_and_open_document();
            }
            ui.add_space(18.0);
            if !self.config.recent_documents.is_empty() {
                ui.heading("最近使ったDiffGR");
                let recent = self.config.recent_documents.clone();
                for item in recent {
                    let label = item
                        .title
                        .as_ref()
                        .map(|title| format!("{}\n{}", title, item.path))
                        .unwrap_or_else(|| item.path.clone());
                    if ui.button(label).clicked() {
                        self.open_document(
                            PathBuf::from(&item.path),
                            item.state_path
                                .as_ref()
                                .map(|value| PathBuf::from(value.as_str())),
                        );
                    }
                }
            }
        });
    }

    fn draw_main(&mut self, ui: &mut egui::Ui) {
        egui::Panel::left("groups_panel")
            .default_size(280.0)
            .resizable(true)
            .show_inside(ui, |ui| {
                self.draw_groups(ui);
            });
        egui::Panel::left("chunks_panel")
            .default_size(440.0)
            .resizable(true)
            .show_inside(ui, |ui| {
                self.draw_chunks(ui);
            });
        egui::CentralPanel::default().show_inside(ui, |ui| {
            self.draw_detail(ui);
        });
    }

    fn draw_status_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            if !self.message.is_empty() {
                ui.label(&self.message);
            } else {
                ui.label("準備完了");
            }
            ui.separator();
            ui.small("Space: reviewed / J,K: 移動 / N: 次の未完了 / Ctrl+S: 保存 / F1: ヘルプ");
        });
    }

    fn draw_help_window(&mut self, ui: &mut egui::Ui) {
        if !self.show_help {
            return;
        }
        let mut open = self.show_help;
        egui::Window::new("DiffGR Review ヘルプ")
            .open(&mut open)
            .resizable(true)
            .default_size([640.0, 520.0])
            .show(ui.ctx(), |ui| {
                ui.heading("ショートカット");
                ui.label("Ctrl+O: DiffGRを開く / Ctrl+S: 保存 / Ctrl+Shift+S: State保存先を選ぶ");
                ui.label("Space: 選択チャンクをレビュー済みにする / J,K または ↑↓: チャンク移動 / N: 次の未完了へ");
                ui.label("R: レビュー済み / I: 無視 / Ctrl+F: 検索欄へ");
                ui.separator();
                ui.heading("おすすめ運用");
                ui.label("1. DiffGR JSONを開く。必要なら review.state.json を読み込む。");
                ui.label("2. State保存先… で review.state.json を作ると、元JSONを汚さずレビュー状態だけ保存できます。");
                ui.label("3. 作業ルートを設定すると、Diff内の相対パスから実ファイルを開きやすくなります。");
                ui.label("4. Path / 検索 / 状態フィルタで絞り込み、Space と N で高速にレビューできます。");
                ui.label("5. 大きいdiffでは `ちらつき抑制` ON / `UI状態を記憶` OFF / `コンパクト行` ON が軽量です。");
                ui.separator();
                ui.heading("Windows向け");
                ui.label("run-windows.ps1 は開発起動、build-windows.ps1 はreleaseビルド、package-windows.ps1 は配布用zip作成です。");
                ui.label("重い場合は `run-windows.ps1 -LowMemory`、古いUI状態を消す場合は `clear-cache-windows.ps1 -Force` を使います。");
            });
        self.show_help = open;
    }

    fn draw_close_confirm(&mut self, ui: &mut egui::Ui) {
        if !self.show_close_confirm {
            return;
        }
        let mut open = self.show_close_confirm;
        egui::Window::new("未保存の変更があります")
            .open(&mut open)
            .collapsible(false)
            .resizable(false)
            .show(ui.ctx(), |ui| {
                ui.label(
                    "保存せずに終了すると、レビュー状態やコメントが失われる可能性があります。",
                );
                ui.horizontal(|ui| {
                    if ui.button("保存して終了").clicked() {
                        self.save_current();
                        if !self.dirty {
                            self.force_close = true;
                            ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
                        }
                    }
                    if ui.button("保存せず終了").clicked() {
                        self.force_close = true;
                        ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
                    }
                    if ui.button("キャンセル").clicked() {
                        self.show_close_confirm = false;
                    }
                });
            });
        self.show_close_confirm = open;
    }

    fn draw_drag_overlay(&mut self, ui: &mut egui::Ui) {
        let hovered = ui.input(|input| !input.raw.hovered_files.is_empty());
        if hovered {
            egui::Area::new(egui::Id::new("diffgr_drop_overlay"))
                .order(egui::Order::Foreground)
                .anchor(egui::Align2::CENTER_CENTER, egui::vec2(0.0, 0.0))
                .show(ui.ctx(), |ui| {
                    ui.group(|ui| {
                        ui.label(RichText::new("ファイルをドロップ").strong());
                        ui.label("DiffGR JSONなら開きます。state JSONなら現在のDiffGRへ重ねます。");
                    });
                });
        }
    }

    fn open_source_file(&mut self, file_path: &str) {
        let path = self.resolve_source_path(file_path);
        if !path.exists() {
            self.message = format!("ファイルが見つかりません: {}", path.display());
            return;
        }
        let result = open_path_with_system(&path);
        self.message = match result {
            Ok(()) => format!("ファイルを開きました: {}", path.display()),
            Err(err) => format!("ファイルを開けませんでした: {}: {}", path.display(), err),
        };
    }

    fn reveal_path(&mut self, path: &Path) {
        let result = reveal_path_with_system(path);
        self.message = match result {
            Ok(()) => format!("場所を表示: {}", path.display()),
            Err(err) => format!("場所を表示できませんでした: {}: {}", path.display(), err),
        };
    }

    fn resolve_source_path(&self, file_path: &str) -> PathBuf {
        let raw = PathBuf::from(file_path);
        if raw.is_absolute() {
            return raw;
        }
        let mut candidates = Vec::new();
        if let Some(root) = parse_optional_path(&self.workspace_root_input) {
            candidates.push(root.join(&raw));
        }
        if let Ok(cwd) = env::current_dir() {
            candidates.push(cwd.join(&raw));
        }
        if let Some(doc_path) = self.doc_path.as_ref() {
            let mut current = doc_path.parent().map(Path::to_path_buf);
            for _ in 0..6 {
                if let Some(base) = current.clone() {
                    candidates.push(base.join(&raw));
                    current = base.parent().map(Path::to_path_buf);
                }
            }
        }
        candidates
            .iter()
            .find(|candidate| candidate.exists())
            .cloned()
            .unwrap_or_else(|| candidates.into_iter().next().unwrap_or(raw))
    }

    fn chunk_clipboard_text(&self, chunk: &Chunk) -> String {
        let status = self
            .doc
            .as_ref()
            .map(|doc| doc.status_for(&chunk.id).label())
            .unwrap_or("未レビュー");
        format!(
            "{}\nchunk: {}\nstatus: {}\nold: {} new: {}\n",
            chunk.file_path,
            chunk.id,
            status,
            chunk.old_range_label(),
            chunk.new_range_label()
        )
    }

    fn window_title(&self) -> String {
        let dirty_mark = if self.dirty { " *" } else { "" };
        let doc_title = self
            .doc
            .as_ref()
            .map(|doc| doc.title.as_str())
            .unwrap_or("DiffGR");
        format!("{}{} - DiffGR Review", doc_title, dirty_mark)
    }

    fn sync_config_snapshot(&mut self) {
        self.config.auto_save_state = self.auto_save_state;
        self.config.auto_advance_after_review = self.auto_advance_after_review;
        self.config.show_line_numbers = self.show_line_numbers;
        self.config.show_only_changed = self.show_only_changed;
        self.config.wrap_diff = self.wrap_diff;
        self.config.only_with_comments = self.only_with_comments;
        self.config.sort_mode = self.sort_mode;
        self.config.detail_tab = self.detail_tab;
        self.config.workspace_root = self.workspace_root_input.trim().to_owned();
    }
}

impl eframe::App for DiffgrGuiApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.handle_shortcuts(ui);
        self.handle_dropped_files(ui);
        self.maybe_auto_save();
        let next_title = self.window_title();
        if next_title != self.last_window_title {
            ui.ctx()
                .send_viewport_cmd(egui::ViewportCommand::Title(next_title.clone()));
            self.last_window_title = next_title;
        }

        let close_requested = ui.input(|input| input.viewport().close_requested());
        if close_requested && self.dirty && !self.force_close {
            ui.ctx()
                .send_viewport_cmd(egui::ViewportCommand::CancelClose);
            self.show_close_confirm = true;
        }

        egui::Panel::top("top_bar").show_inside(ui, |ui| {
            self.draw_top_bar(ui);
        });
        egui::Panel::bottom("status_bar").show_inside(ui, |ui| {
            self.draw_status_bar(ui);
        });

        if self.doc.is_some() {
            egui::Panel::top("metrics_bar").show_inside(ui, |ui| {
                self.draw_metrics(ui);
            });
            self.draw_main(ui);
        } else {
            egui::CentralPanel::default().show_inside(ui, |ui| {
                self.draw_empty(ui);
            });
        }

        self.draw_help_window(ui);
        self.draw_close_confirm(ui);
        self.draw_drag_overlay(ui);
        self.sync_config_snapshot();
    }

    fn save(&mut self, storage: &mut dyn eframe::Storage) {
        self.sync_config_snapshot();
        self.config.save(storage);
    }

    fn auto_save_interval(&self) -> Duration {
        Duration::from_secs(20)
    }

    fn persist_egui_memory(&self) -> bool {
        self.config.persist_egui_memory
    }
}

pub fn install_japanese_font_fallbacks(ctx: &egui::Context) {
    let candidates = [
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\YuGothM.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    ];

    for path in candidates {
        let Ok(bytes) = fs::read(path) else {
            continue;
        };
        let mut fonts = egui::FontDefinitions::default();
        let name = "system_japanese".to_owned();
        fonts
            .font_data
            .insert(name.clone(), Arc::new(egui::FontData::from_owned(bytes)));
        fonts
            .families
            .get_mut(&FontFamily::Proportional)
            .expect("default proportional font family")
            .insert(0, name.clone());
        fonts
            .families
            .get_mut(&FontFamily::Monospace)
            .expect("default monospace font family")
            .insert(0, name);
        ctx.set_fonts(fonts);
        return;
    }
}

fn apply_runtime_style(ctx: &egui::Context, mode: ThemeMode, reduce_motion: bool) {
    match mode {
        ThemeMode::System => {}
        ThemeMode::Dark => ctx.set_visuals(egui::Visuals::dark()),
        ThemeMode::Light => ctx.set_visuals(egui::Visuals::light()),
    }
    ctx.global_style_mut(|style| {
        style.animation_time = if reduce_motion { 0.0 } else { 0.083 };
    });
}

fn status_badge(status: ReviewStatus) -> RichText {
    RichText::new(status.label()).color(match status {
        ReviewStatus::Reviewed => Color32::LIGHT_GREEN,
        ReviewStatus::NeedsReReview => Color32::YELLOW,
        ReviewStatus::Ignored => Color32::GRAY,
        ReviewStatus::Unreviewed => Color32::LIGHT_RED,
    })
}

fn color_for_line(kind: &str) -> Color32 {
    match kind {
        "add" => Color32::LIGHT_GREEN,
        "delete" => Color32::LIGHT_RED,
        _ => Color32::LIGHT_GRAY,
    }
}

fn status_sort_key(status: ReviewStatus) -> u8 {
    match status {
        ReviewStatus::NeedsReReview => 0,
        ReviewStatus::Unreviewed => 1,
        ReviewStatus::Reviewed => 2,
        ReviewStatus::Ignored => 3,
    }
}

fn short_id(id: &str) -> String {
    id.chars().take(8).collect()
}

fn labeled_singleline(ui: &mut egui::Ui, label: &str, value: &mut String) {
    ui.label(label);
    ui.add_sized([f32::INFINITY, 24.0], TextEdit::singleline(value));
}

fn labeled_multiline(ui: &mut egui::Ui, label: &str, value: &mut String, rows: usize) {
    ui.label(label);
    ui.add(
        TextEdit::multiline(value)
            .desired_rows(rows)
            .desired_width(f32::INFINITY),
    );
}

fn env_flag(name: &str) -> bool {
    env::var(name)
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false)
}

fn parse_optional_path(input: &str) -> Option<PathBuf> {
    let trimmed = input.trim().trim_matches('"');
    (!trimmed.is_empty()).then(|| PathBuf::from(trimmed))
}

fn chunk_matches_text(doc: &DiffgrDocument, chunk: &Chunk, needle: &str) -> bool {
    if chunk.id.to_lowercase().contains(needle) || chunk.file_path.to_lowercase().contains(needle) {
        return true;
    }
    if doc.comment_for(&chunk.id).to_lowercase().contains(needle) {
        return true;
    }
    chunk
        .lines
        .iter()
        .any(|line| line.text.to_lowercase().contains(needle))
}

fn find_nearby_state_file(doc_path: &Path) -> Option<PathBuf> {
    let dir = doc_path.parent()?;
    let candidates = [
        dir.join("review.state.json"),
        dir.join("diffgr.review.state.json"),
        doc_path.with_extension("state.json"),
    ];
    candidates.into_iter().find(|path| path.exists())
}

fn open_path_with_system(path: &Path) -> std::io::Result<()> {
    #[cfg(target_os = "windows")]
    {
        Command::new("cmd")
            .args(["/C", "start", ""])
            .arg(path)
            .spawn()?;
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open").arg(path).spawn()?;
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new("xdg-open").arg(path).spawn()?;
    }
    Ok(())
}

fn reveal_path_with_system(path: &Path) -> std::io::Result<()> {
    #[cfg(target_os = "windows")]
    {
        if path.is_file() {
            Command::new("explorer")
                .arg(format!("/select,{}", path.display()))
                .spawn()?;
        } else {
            Command::new("explorer").arg(path).spawn()?;
        }
    }
    #[cfg(target_os = "macos")]
    {
        if path.exists() {
            Command::new("open").arg("-R").arg(path).spawn()?;
        } else if let Some(parent) = path.parent() {
            Command::new("open").arg(parent).spawn()?;
        }
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let target = if path.is_dir() {
            path.to_path_buf()
        } else {
            path.parent()
                .unwrap_or_else(|| Path::new("."))
                .to_path_buf()
        };
        Command::new("xdg-open").arg(target).spawn()?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::process;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn sample_doc() -> DiffgrDocument {
        DiffgrDocument::from_value(json!({
            "format": "diffgr",
            "version": 1,
            "meta": {"title": "App UT"},
            "groups": [{"id": "g", "name": "Group", "order": 1}],
            "chunks": [
                {
                    "id": "c1",
                    "filePath": "src/main.rs",
                    "old": {"start": 1, "count": 1},
                    "new": {"start": 1, "count": 2},
                    "lines": [
                        {"kind": "context", "text": "fn main()", "oldLine": 1, "newLine": 1},
                        {"kind": "add", "text": "println!(\"hello\");", "oldLine": null, "newLine": 2}
                    ]
                }
            ],
            "assignments": {"g": ["c1"]},
            "reviews": {}
        }))
        .unwrap()
    }

    fn unique_temp_dir(label: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time moves forward")
            .as_nanos();
        std::env::temp_dir().join(format!(
            "diffgr_gui_app_ut_{}_{}_{}",
            label,
            process::id(),
            nanos
        ))
    }

    #[test]
    fn startup_args_parse_path_and_state() {
        let args = StartupArgs::from_iter([
            "--state",
            "review.state.json",
            "input.diffgr.json",
            "ignored-second-path.diffgr.json",
        ]);
        assert_eq!(args.path, Some(PathBuf::from("input.diffgr.json")));
        assert_eq!(args.state, Some(PathBuf::from("review.state.json")));
    }

    #[test]
    fn startup_args_ignore_unknown_options() {
        let args = StartupArgs::from_iter(["--unknown", "input.diffgr.json"]);
        assert_eq!(args.path, Some(PathBuf::from("input.diffgr.json")));
        assert_eq!(args.state, None);
    }

    #[test]
    fn parse_optional_path_trims_quotes_and_empty_values() {
        assert_eq!(parse_optional_path(""), None);
        assert_eq!(
            parse_optional_path("   \"C:/work/a.diffgr.json\"  "),
            Some(PathBuf::from("C:/work/a.diffgr.json"))
        );
    }

    #[test]
    fn chunk_text_search_checks_path_comment_and_diff_lines() {
        let mut doc = sample_doc();
        let chunk = doc.chunk_by_id("c1").unwrap().clone();
        assert!(chunk_matches_text(&doc, &chunk, "main.rs"));
        assert!(chunk_matches_text(&doc, &chunk, "println"));
        assert!(!chunk_matches_text(&doc, &chunk, "missing-text"));

        doc.set_comment("c1", "review note from tester");
        let chunk = doc.chunk_by_id("c1").unwrap().clone();
        assert!(chunk_matches_text(&doc, &chunk, "tester"));
    }

    #[test]
    fn nearby_state_file_prefers_review_state_json() {
        let root = unique_temp_dir("nearby_state");
        fs::create_dir_all(&root).unwrap();
        let doc_path = root.join("sample.diffgr.json");
        let preferred = root.join("review.state.json");
        let fallback = root.join("diffgr.review.state.json");
        fs::write(&fallback, "{}").unwrap();
        fs::write(&preferred, "{}").unwrap();

        assert_eq!(find_nearby_state_file(&doc_path), Some(preferred));
        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn status_sort_key_keeps_attention_items_first() {
        let ordered = [
            ReviewStatus::NeedsReReview,
            ReviewStatus::Unreviewed,
            ReviewStatus::Reviewed,
            ReviewStatus::Ignored,
        ];
        let keys: Vec<u8> = ordered.into_iter().map(status_sort_key).collect();
        assert_eq!(keys, vec![0, 1, 2, 3]);
    }
}
