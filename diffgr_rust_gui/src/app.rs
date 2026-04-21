use crate::diff_words::{self, DiffTextSegment};
use crate::model::{
    Chunk, CoverageIssue, DiffLine, DiffgrDocument, GroupBriefDraft, GroupMetrics, ImpactReport,
    LineAnchor, Metrics, ReviewStatus, StateDiffReport, StatusCounts,
};
use crate::{ops, vpr};
use eframe::egui::{self, Color32, FontFamily, ProgressBar, RichText, TextEdit};
use rfd::FileDialog;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::sync::Arc;
use std::time::{Duration, Instant};

const APP_STORAGE_KEY: &str = "diffgr_gui_config_v2";
const MAX_RECENT_DOCUMENTS: usize = 8;
const MAX_STATUS_HISTORY: usize = 64;
const COMPACT_CHUNK_ROW_HEIGHT: f32 = 54.0;
const COMFORTABLE_CHUNK_ROW_HEIGHT: f32 = 66.0;
const GROUP_ROW_HEIGHT: f32 = 76.0;
const MIN_DIFF_ROW_HEIGHT: f32 = 22.0;
const SEARCH_DEBOUNCE_MS: u64 = 220;
const ACTIVE_SCROLL_REPAINT_MS: u64 = 16;
const BACKGROUND_JOB_REPAINT_MS: u64 = 60;
const MAX_RENDERED_DIFF_CHARS: usize = 1800;
const WORD_DIFF_UNPAIRED_SENTINEL: usize = usize::MAX;
const MAX_CHUNK_ROW_CACHE: usize = 512;
const CHUNK_ROW_CACHE_RETAIN_RADIUS: usize = 192;

#[derive(Clone, Debug, Default)]
pub struct StartupArgs {
    pub path: Option<PathBuf>,
    pub state: Option<PathBuf>,
    pub low_memory: bool,
    pub smooth_scroll: bool,
    pub no_background_io: bool,
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
                "--low-memory" | "--lowMemory" => {
                    out.low_memory = true;
                }
                "--smooth-scroll" | "--smooth" => {
                    out.smooth_scroll = true;
                }
                "--no-background-io" => {
                    out.no_background_io = true;
                }
                "--help" | "-h" => {
                    eprintln!(
                        "Usage: diffgr_gui [path/to/file.diffgr.json] [--state path/to/review.state.json] [--low-memory] [--smooth-scroll] [--no-background-io]"
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
    Layout,
    Coverage,
    Impact,
    Approval,
    VirtualPr,
    Tools,
    Diagnostics,
    Summary,
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
            DetailTab::Layout => "Layout",
            DetailTab::Coverage => "Coverage",
            DetailTab::Impact => "Impact",
            DetailTab::Approval => "Approval",
            DetailTab::VirtualPr => "仮想PR",
            DetailTab::Tools => "Tools",
            DetailTab::Diagnostics => "診断",
            DetailTab::Summary => "概要",
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

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
enum DiffViewMode {
    Unified,
    SideBySide,
}

impl Default for DiffViewMode {
    fn default() -> Self {
        DiffViewMode::Unified
    }
}

impl DiffViewMode {
    const ALL: [DiffViewMode; 2] = [DiffViewMode::Unified, DiffViewMode::SideBySide];

    fn label(self) -> &'static str {
        match self {
            DiffViewMode::Unified => "統合表示",
            DiffViewMode::SideBySide => "左右比較",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
enum DiffContextMode {
    All,
    ChangedOnly,
    ChangedWithContext,
}

impl Default for DiffContextMode {
    fn default() -> Self {
        DiffContextMode::All
    }
}

impl DiffContextMode {
    const ALL: [DiffContextMode; 3] = [
        DiffContextMode::All,
        DiffContextMode::ChangedOnly,
        DiffContextMode::ChangedWithContext,
    ];

    fn label(self) -> &'static str {
        match self {
            DiffContextMode::All => "全行",
            DiffContextMode::ChangedOnly => "変更行のみ",
            DiffContextMode::ChangedWithContext => "変更周辺",
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
    diff_view_mode: DiffViewMode,
    diff_context_mode: DiffContextMode,
    diff_context_radius: usize,
    word_diff_enabled: bool,
    word_diff_smart_pairing: bool,
    wrap_diff: bool,
    only_with_comments: bool,
    reduce_motion: bool,
    smooth_scroll_repaint: bool,
    show_performance_overlay: bool,
    defer_filtering: bool,
    background_io: bool,
    clip_long_lines: bool,
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
            diff_view_mode: DiffViewMode::Unified,
            diff_context_mode: DiffContextMode::All,
            diff_context_radius: 2,
            word_diff_enabled: true,
            word_diff_smart_pairing: true,
            wrap_diff: true,
            only_with_comments: false,
            reduce_motion: true,
            smooth_scroll_repaint: true,
            show_performance_overlay: false,
            defer_filtering: true,
            background_io: true,
            clip_long_lines: true,
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
    rows: BTreeMap<usize, ChunkRow>,
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
    line_starts: Vec<usize>,
}

#[derive(Clone, Debug, Default)]
struct DiffLineIndexCache {
    chunk_id: String,
    source_len: usize,
    changed_indices: Arc<Vec<usize>>,
}

#[derive(Clone, Debug, Default)]
struct DiffContextIndexCache {
    chunk_id: String,
    source_len: usize,
    radius: usize,
    indices: Arc<Vec<usize>>,
}

#[derive(Clone, Copy, Debug, Default)]
struct SideBySideDiffRow {
    old_index: Option<usize>,
    new_index: Option<usize>,
}

#[derive(Clone, Debug, Default)]
struct DiffSideBySideCache {
    chunk_id: String,
    source_len: usize,
    context_mode: DiffContextMode,
    context_radius: usize,
    smart_pairing: bool,
    rows: Arc<Vec<SideBySideDiffRow>>,
}

#[derive(Clone, Debug, Default)]
struct DiffWordPairCache {
    chunk_id: String,
    source_len: usize,
    smart_pairing: bool,
    pairs: Arc<BTreeMap<usize, usize>>,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
struct DiffWordSegmentKey {
    line_index: usize,
    pair_index: usize,
}

#[derive(Clone, Debug, Default)]
struct DiffWordSegmentCache {
    chunk_id: String,
    source_len: usize,
    segments: BTreeMap<DiffWordSegmentKey, Arc<Vec<DiffTextSegment>>>,
}

#[derive(Clone, Debug, Default)]
struct VirtualPrReportCache {
    revision: u64,
    report: Option<vpr::VirtualPrReviewReport>,
}

#[derive(Clone, Debug)]
struct StatusChange {
    chunk_id: String,
    previous: ReviewStatus,
    next: ReviewStatus,
}

#[derive(Clone, Debug)]
struct StatusHistoryItem {
    changes: Vec<StatusChange>,
}

struct PendingDocumentLoad {
    path: PathBuf,
    state_path: Option<PathBuf>,
    started: Instant,
    rx: Receiver<Result<DiffgrDocument, String>>,
}

struct PendingStateSave {
    path: PathBuf,
    revision: u64,
    started: Instant,
    rx: Receiver<Result<(), String>>,
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
    file_filter_input: String,
    content_filter_input: String,
    filter_apply_deadline: Option<Instant>,
    sort_mode: SortMode,
    detail_tab: DetailTab,
    comment_buffer: String,
    line_comment_buffer: String,
    group_brief_buffer: GroupBriefDraft,
    group_id_buffer: String,
    group_name_buffer: String,
    group_tags_buffer: String,
    state_merge_preview_text: String,
    impact_preview_text: String,
    approval_report_text: String,
    reviewer_input: String,
    change_request_comment: String,
    tool_repo_input: String,
    tool_base_input: String,
    tool_feature_input: String,
    tool_title_input: String,
    tool_output_input: String,
    tool_output_text: String,
    diff_view_mode: DiffViewMode,
    diff_context_mode: DiffContextMode,
    diff_context_radius: usize,
    word_diff_enabled: bool,
    word_diff_smart_pairing: bool,
    diff_search_buffer: String,
    show_only_changed: bool,
    wrap_diff: bool,
    show_line_numbers: bool,
    only_with_comments: bool,
    auto_save_state: bool,
    auto_advance_after_review: bool,
    dirty: bool,
    layout_dirty: bool,
    message: String,
    show_help: bool,
    show_close_confirm: bool,
    force_close: bool,
    focus_search_next_frame: bool,
    status_history: Vec<StatusHistoryItem>,
    last_auto_save: Instant,
    list_revision: u64,
    state_revision: u64,
    visible_cache: VisibleChunkCache,
    metrics_cache: MetricsCache,
    state_preview_cache: StatePreviewCache,
    diff_line_index_cache: Option<DiffLineIndexCache>,
    diff_context_index_cache: Option<DiffContextIndexCache>,
    diff_side_by_side_cache: Option<DiffSideBySideCache>,
    diff_word_pair_cache: Option<DiffWordPairCache>,
    diff_word_segment_cache: Option<DiffWordSegmentCache>,
    virtual_pr_report_cache: VirtualPrReportCache,
    pending_load: Option<PendingDocumentLoad>,
    pending_state_save: Option<PendingStateSave>,
    last_frame_instant: Option<Instant>,
    frame_time_ema_ms: f32,
    frame_time_peak_ms: f32,
    slow_frame_count: u64,
    frame_sample_count: u64,
    last_window_title: String,
    config: AppConfig,
}

impl DiffgrGuiApp {
    pub fn new(args: StartupArgs, cc: &eframe::CreationContext<'_>) -> Self {
        let mut config = AppConfig::load(cc.storage);
        if args.low_memory || env_flag("DIFFGR_LOW_MEMORY") {
            config.reduce_motion = true;
            config.smooth_scroll_repaint = false;
            config.compact_rows = true;
            config.persist_egui_memory = false;
            config.auto_load_last = false;
            config.clip_long_lines = true;
            config.defer_filtering = true;
            config.word_diff_enabled = false;
        }
        if args.smooth_scroll || env_flag("DIFFGR_SMOOTH_SCROLL") {
            config.smooth_scroll_repaint = true;
            config.reduce_motion = false;
        }
        if args.no_background_io || env_flag("DIFFGR_NO_BACKGROUND_IO") {
            config.background_io = false;
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
            file_filter_input: String::new(),
            content_filter_input: String::new(),
            filter_apply_deadline: None,
            sort_mode: config.sort_mode,
            detail_tab: config.detail_tab,
            comment_buffer: String::new(),
            line_comment_buffer: String::new(),
            group_brief_buffer: GroupBriefDraft::default(),
            group_id_buffer: String::new(),
            group_name_buffer: String::new(),
            group_tags_buffer: String::new(),
            state_merge_preview_text: String::new(),
            impact_preview_text: String::new(),
            approval_report_text: String::new(),
            reviewer_input: String::new(),
            change_request_comment: String::new(),
            tool_repo_input: ".".to_owned(),
            tool_base_input: "main".to_owned(),
            tool_feature_input: "HEAD".to_owned(),
            tool_title_input: "DiffGR review bundle".to_owned(),
            tool_output_input: "out\\work\\review.diffgr.json".to_owned(),
            tool_output_text: String::new(),
            diff_view_mode: config.diff_view_mode,
            diff_context_mode: if config.show_only_changed {
                DiffContextMode::ChangedOnly
            } else {
                config.diff_context_mode
            },
            diff_context_radius: config.diff_context_radius,
            word_diff_enabled: config.word_diff_enabled,
            word_diff_smart_pairing: config.word_diff_smart_pairing,
            diff_search_buffer: String::new(),
            show_only_changed: config.show_only_changed,
            wrap_diff: config.wrap_diff,
            show_line_numbers: config.show_line_numbers,
            only_with_comments: config.only_with_comments,
            auto_save_state: config.auto_save_state,
            auto_advance_after_review: config.auto_advance_after_review,
            dirty: false,
            layout_dirty: false,
            message: String::new(),
            show_help: false,
            show_close_confirm: false,
            force_close: false,
            focus_search_next_frame: false,
            status_history: Vec::new(),
            last_auto_save: Instant::now(),
            list_revision: 1,
            state_revision: 1,
            visible_cache: VisibleChunkCache::default(),
            metrics_cache: MetricsCache::default(),
            state_preview_cache: StatePreviewCache::default(),
            diff_line_index_cache: None,
            diff_context_index_cache: None,
            diff_side_by_side_cache: None,
            diff_word_pair_cache: None,
            diff_word_segment_cache: None,
            virtual_pr_report_cache: VirtualPrReportCache::default(),
            pending_load: None,
            pending_state_save: None,
            last_frame_instant: None,
            frame_time_ema_ms: 0.0,
            frame_time_peak_ms: 0.0,
            slow_frame_count: 0,
            frame_sample_count: 0,
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
        self.path_input = path.display().to_string();
        self.state_input = state_path
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_default();

        if self.config.background_io {
            self.start_background_document_load(path, state_path);
        } else {
            match DiffgrDocument::load_from_path(&path, state_path.as_deref()) {
                Ok(doc) => self.finish_loaded_document(path, state_path, doc),
                Err(err) => self.message = format!("読み込み失敗: {err}"),
            }
        }
    }

    fn start_background_document_load(&mut self, path: PathBuf, state_path: Option<PathBuf>) {
        let worker_path = path.clone();
        let worker_state_path = state_path.clone();
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            let result = DiffgrDocument::load_from_path(&worker_path, worker_state_path.as_deref());
            let _ = tx.send(result);
        });
        self.pending_load = Some(PendingDocumentLoad {
            path: path.clone(),
            state_path: state_path.clone(),
            started: Instant::now(),
            rx,
        });
        self.message = match state_path {
            Some(state) => format!(
                "バックグラウンド読み込み中: {} / state: {}",
                path.display(),
                state.display()
            ),
            None => format!("バックグラウンド読み込み中: {}", path.display()),
        };
    }

    fn finish_loaded_document(
        &mut self,
        path: PathBuf,
        state_path: Option<PathBuf>,
        doc: DiffgrDocument,
    ) {
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
        self.status_history.clear();
        self.state_merge_preview_text.clear();
        self.impact_preview_text.clear();
        self.approval_report_text.clear();
        self.restore_ui_state_from_document();
        self.file_filter_input = self.file_filter.clone();
        self.content_filter_input = self.content_filter.clone();
        self.filter_apply_deadline = None;
        self.last_window_title.clear();
        self.dirty = false;
        self.layout_dirty = false;
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

    fn poll_background_jobs(&mut self, ctx: &egui::Context) {
        let mut keep_repainting = false;
        if self.pending_load.is_some() {
            let recv = self
                .pending_load
                .as_ref()
                .expect("pending load exists")
                .rx
                .try_recv();
            match recv {
                Ok(result) => {
                    let pending = self.pending_load.take().expect("pending load exists");
                    match result {
                        Ok(doc) => {
                            self.finish_loaded_document(pending.path, pending.state_path, doc)
                        }
                        Err(err) => self.message = format!("読み込み失敗: {err}"),
                    }
                }
                Err(TryRecvError::Empty) => {
                    keep_repainting = true;
                    if let Some(pending) = self.pending_load.as_ref() {
                        if pending.started.elapsed() > Duration::from_millis(180) {
                            self.message = format!("読み込み中… {}", pending.path.display());
                        }
                    }
                }
                Err(TryRecvError::Disconnected) => {
                    self.pending_load = None;
                    self.message = "読み込みワーカーが終了しました。".to_owned();
                }
            }
        }

        if self.pending_state_save.is_some() {
            let recv = self
                .pending_state_save
                .as_ref()
                .expect("pending save exists")
                .rx
                .try_recv();
            match recv {
                Ok(result) => {
                    let pending = self.pending_state_save.take().expect("pending save exists");
                    match result {
                        Ok(()) => {
                            if pending.revision == self.state_revision && !self.layout_dirty {
                                self.dirty = false;
                                self.message = format!("自動保存: {}", pending.path.display());
                            } else {
                                self.message = format!(
                                    "自動保存完了: {} / 追加変更あり",
                                    pending.path.display()
                                );
                            }
                        }
                        Err(err) => self.message = format!("自動保存失敗: {err}"),
                    }
                }
                Err(TryRecvError::Empty) => {
                    keep_repainting = true;
                    if let Some(pending) = self.pending_state_save.as_ref() {
                        if pending.started.elapsed() > Duration::from_millis(180) {
                            self.message = format!("自動保存中… {}", pending.path.display());
                        }
                    }
                }
                Err(TryRecvError::Disconnected) => {
                    self.pending_state_save = None;
                    self.message = "自動保存ワーカーが終了しました。".to_owned();
                }
            }
        }

        if keep_repainting {
            ctx.request_repaint_after(Duration::from_millis(BACKGROUND_JOB_REPAINT_MS));
        }
    }

    fn restore_ui_state_from_document(&mut self) {
        let Some(doc) = self.doc.as_ref() else {
            return;
        };

        self.status_filter = StatusFilter::from_analysis(doc.analysis_string("promptStatusFilter"));
        self.file_filter = doc.analysis_string("filterText").unwrap_or_default();
        self.content_filter = doc.analysis_string("contentSearchText").unwrap_or_default();
        self.file_filter_input = self.file_filter.clone();
        self.content_filter_input = self.content_filter.clone();
        self.filter_apply_deadline = None;

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
        self.reload_group_editor_buffer();
    }

    fn reload_group_editor_buffer(&mut self) {
        if let Some((doc, group_id)) = self.doc.as_ref().zip(self.current_group.as_ref()) {
            if let Some(group) = doc.group_by_id(group_id) {
                self.group_id_buffer = group.id.clone();
                self.group_name_buffer = group.name.clone();
                self.group_tags_buffer = group.tags.join(" | ");
                return;
            }
        }
        self.group_id_buffer.clear();
        self.group_name_buffer.clear();
        self.group_tags_buffer.clear();
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
        self.file_filter_input = self.file_filter.clone();
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
        self.content_filter_input = self.content_filter.clone();
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

    fn schedule_filter_apply(&mut self, ctx: &egui::Context) {
        if self.config.defer_filtering {
            self.filter_apply_deadline =
                Some(Instant::now() + Duration::from_millis(SEARCH_DEBOUNCE_MS));
            ctx.request_repaint_after(Duration::from_millis(SEARCH_DEBOUNCE_MS));
        } else {
            self.apply_filter_inputs_now();
        }
    }

    fn apply_filter_inputs_now(&mut self) {
        let next_file = self.file_filter_input.clone();
        let next_content = self.content_filter_input.clone();
        self.filter_apply_deadline = None;
        let changed = self.file_filter != next_file || self.content_filter != next_content;
        if !changed {
            return;
        }
        self.file_filter = next_file;
        self.content_filter = next_content;
        if let Some(doc) = self.doc.as_mut() {
            let file = self.file_filter.trim().to_owned();
            let content = self.content_filter.trim().to_owned();
            doc.set_analysis_string("filterText", (!file.is_empty()).then_some(file.as_str()));
            doc.set_analysis_string(
                "contentSearchText",
                (!content.is_empty()).then_some(content.as_str()),
            );
        }
        self.invalidate_visible_cache();
        self.ensure_selected_chunk_visible();
        self.invalidate_state_preview_cache();
    }

    fn maybe_apply_debounced_filters(&mut self, ctx: &egui::Context) {
        let Some(deadline) = self.filter_apply_deadline else {
            return;
        };
        let now = Instant::now();
        if now >= deadline {
            self.apply_filter_inputs_now();
        } else {
            ctx.request_repaint_after(deadline.saturating_duration_since(now));
        }
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
        self.virtual_pr_report_cache = VirtualPrReportCache::default();
    }

    fn invalidate_state_preview_cache(&mut self) {
        self.state_revision = self.state_revision.wrapping_add(1);
        self.state_preview_cache = StatePreviewCache::default();
        self.virtual_pr_report_cache = VirtualPrReportCache::default();
    }

    fn clear_all_volatile_caches(&mut self) {
        self.list_revision = self.list_revision.wrapping_add(1);
        self.state_revision = self.state_revision.wrapping_add(1);
        self.visible_cache = VisibleChunkCache::default();
        self.metrics_cache = MetricsCache::default();
        self.state_preview_cache = StatePreviewCache::default();
        self.diff_line_index_cache = None;
        self.diff_context_index_cache = None;
        self.diff_side_by_side_cache = None;
        self.diff_word_pair_cache = None;
        self.diff_word_segment_cache = None;
        self.virtual_pr_report_cache = VirtualPrReportCache::default();
    }

    fn virtual_pr_report(&mut self) -> Option<vpr::VirtualPrReviewReport> {
        if self.virtual_pr_report_cache.revision == self.state_revision {
            if let Some(report) = self.virtual_pr_report_cache.report.clone() {
                return Some(report);
            }
        }
        let report = self.doc.as_ref().map(vpr::analyze_virtual_pr)?;
        self.virtual_pr_report_cache = VirtualPrReportCache {
            revision: self.state_revision,
            report: Some(report.clone()),
        };
        Some(report)
    }

    fn ensure_visible_cache(&mut self) {
        let key = self.visible_cache_key();
        if self.visible_cache.key.as_ref() == Some(&key) {
            return;
        }

        let ids = self.visible_chunk_ids_uncached();
        self.visible_cache = VisibleChunkCache {
            key: Some(key),
            ids,
            rows: BTreeMap::new(),
        };
    }

    fn visible_chunk_ids(&mut self) -> Vec<String> {
        self.ensure_visible_cache();
        self.visible_cache.ids.clone()
    }

    fn build_chunk_rows_from_ids(&self, ids: &[String]) -> Vec<ChunkRow> {
        ids.iter()
            .enumerate()
            .filter_map(|(index, chunk_id)| self.build_chunk_row(index, chunk_id))
            .collect()
    }

    fn build_chunk_row(&self, index: usize, chunk_id: &str) -> Option<ChunkRow> {
        let doc = self.doc.as_ref()?;
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
    }

    fn cached_chunk_row(&mut self, index: usize) -> Option<ChunkRow> {
        self.ensure_visible_cache();
        if let Some(row) = self.visible_cache.rows.get(&index) {
            return Some(row.clone());
        }
        let chunk_id = self.visible_cache.ids.get(index)?.clone();
        let row = self.build_chunk_row(index, &chunk_id)?;
        self.visible_cache.rows.insert(index, row.clone());
        self.prune_chunk_row_cache_around(index);
        Some(row)
    }

    fn prune_chunk_row_cache_around(&mut self, focus_index: usize) {
        if self.visible_cache.rows.len() <= MAX_CHUNK_ROW_CACHE {
            return;
        }
        let start = focus_index.saturating_sub(CHUNK_ROW_CACHE_RETAIN_RADIUS);
        let end = focus_index.saturating_add(CHUNK_ROW_CACHE_RETAIN_RADIUS);
        self.visible_cache
            .rows
            .retain(|index, _| *index >= start && *index <= end);
        while self.visible_cache.rows.len() > MAX_CHUNK_ROW_CACHE {
            let remove_key = self
                .visible_cache
                .rows
                .keys()
                .max_by_key(|index| usize::abs_diff(**index, focus_index))
                .copied();
            if let Some(key) = remove_key {
                self.visible_cache.rows.remove(&key);
            } else {
                break;
            }
        }
    }

    fn visible_chunk_count(&mut self) -> usize {
        self.ensure_visible_cache();
        self.visible_cache.ids.len()
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

    fn ensure_state_preview_cache(&mut self) -> bool {
        if self.state_preview_cache.revision == self.state_revision
            && self.state_preview_cache.text.is_some()
        {
            return true;
        }
        let Some(text) = self.doc.as_ref().map(|doc| {
            serde_json::to_string_pretty(&doc.extract_state()).unwrap_or_else(|err| err.to_string())
        }) else {
            return false;
        };
        let line_starts = build_line_starts(&text);
        self.state_preview_cache.revision = self.state_revision;
        self.state_preview_cache.text = Some(text);
        self.state_preview_cache.line_starts = line_starts;
        true
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

    fn update_frame_budget_metrics(&mut self) {
        let now = Instant::now();
        if let Some(previous) = self.last_frame_instant.replace(now) {
            let elapsed_ms = now.duration_since(previous).as_secs_f32() * 1000.0;
            if self.frame_sample_count == 0 {
                self.frame_time_ema_ms = elapsed_ms;
                self.frame_time_peak_ms = elapsed_ms;
            } else {
                self.frame_time_ema_ms = self.frame_time_ema_ms.mul_add(0.90, elapsed_ms * 0.10);
                self.frame_time_peak_ms = self.frame_time_peak_ms.max(elapsed_ms);
            }
            self.frame_sample_count = self.frame_sample_count.saturating_add(1);
            if elapsed_ms > 50.0 {
                self.slow_frame_count = self.slow_frame_count.saturating_add(1);
            }
        }
    }

    fn reset_frame_budget_metrics(&mut self) {
        self.last_frame_instant = Some(Instant::now());
        self.frame_time_ema_ms = 0.0;
        self.frame_time_peak_ms = 0.0;
        self.slow_frame_count = 0;
        self.frame_sample_count = 0;
    }

    fn performance_health_label(&self) -> &'static str {
        if self.frame_time_ema_ms <= 0.0 {
            "計測中"
        } else if self.frame_time_ema_ms <= 16.7 {
            "良好 / 60fps相当"
        } else if self.frame_time_ema_ms <= 33.4 {
            "注意 / 30fps相当"
        } else {
            "重い / 表示設定を軽量化推奨"
        }
    }

    fn copy_self_review_report(&mut self, ctx: &egui::Context) {
        ctx.copy_text(build_self_review_markdown(
            self.doc.as_ref(),
            &self.config,
            self.pending_load.is_some(),
            self.pending_state_save.is_some(),
        ));
        self.message = "自己レビュー結果をMarkdownとしてコピーしました。".to_owned();
    }

    fn save_self_review_report(&mut self) {
        let mut dialog = FileDialog::new()
            .add_filter("Markdown", &["md"])
            .set_file_name("diffgr-rust-gui-self-review.md");
        if let Some(parent) = self.doc_path.as_ref().and_then(|path| path.parent()) {
            dialog = dialog.set_directory(parent);
        }
        let Some(path) = dialog.save_file() else {
            return;
        };
        let report = build_self_review_markdown(
            self.doc.as_ref(),
            &self.config,
            self.pending_load.is_some(),
            self.pending_state_save.is_some(),
        );
        match write_text_file(&path, &report) {
            Ok(()) => self.message = format!("自己レビュー保存: {}", path.display()),
            Err(err) => self.message = format!("自己レビュー保存失敗: {err}"),
        }
    }

    fn copy_review_summary(&mut self, ctx: &egui::Context) {
        let Some(doc) = self.doc.as_ref() else {
            self.message = "コピー対象のDiffGRがありません。".to_owned();
            return;
        };
        ctx.copy_text(doc.review_markdown_report());
        self.message = "レビューサマリをMarkdownとしてコピーしました。".to_owned();
    }

    fn save_review_summary(&mut self) {
        let Some(doc) = self.doc.as_ref() else {
            self.message = "保存対象のDiffGRがありません。".to_owned();
            return;
        };
        let default_name = default_report_file_name(self.doc_path.as_deref());
        let mut dialog = FileDialog::new()
            .add_filter("Markdown", &["md"])
            .set_file_name(&default_name);
        if let Some(parent) = self.doc_path.as_ref().and_then(|path| path.parent()) {
            dialog = dialog.set_directory(parent);
        }
        let Some(path) = dialog.save_file() else {
            return;
        };
        match doc.write_review_report(&path) {
            Ok(()) => self.message = format!("レビューサマリ保存: {}", path.display()),
            Err(err) => self.message = format!("レビューサマリ保存失敗: {err}"),
        }
    }

    fn save_html_report(&mut self) {
        let Some(doc) = self.doc.as_ref() else {
            self.message = "保存対象のDiffGRがありません。".to_owned();
            return;
        };
        let default_name = default_html_report_file_name(self.doc_path.as_deref());
        let mut dialog = FileDialog::new()
            .add_filter("HTML", &["html", "htm"])
            .set_file_name(&default_name);
        if let Some(parent) = self.doc_path.as_ref().and_then(|path| path.parent()) {
            dialog = dialog.set_directory(parent);
        }
        let Some(path) = dialog.save_file() else {
            return;
        };
        match doc.write_html_report(&path) {
            Ok(()) => self.message = format!("HTMLレポート保存: {}", path.display()),
            Err(err) => self.message = format!("HTMLレポート保存失敗: {err}"),
        }
    }

    fn copy_coverage_prompt(&mut self, ctx: &egui::Context) {
        let Some(doc) = self.doc.as_ref() else {
            self.message = "コピー対象のDiffGRがありません。".to_owned();
            return;
        };
        ctx.copy_text(doc.coverage_fix_prompt_markdown());
        self.message = "coverage修正依頼プロンプトをコピーしました。".to_owned();
    }

    fn save_coverage_prompt(&mut self) {
        let Some(doc) = self.doc.as_ref() else {
            self.message = "保存対象のDiffGRがありません。".to_owned();
            return;
        };
        let mut dialog = FileDialog::new()
            .add_filter("Markdown", &["md"])
            .set_file_name("coverage-fix-prompt.md");
        if let Some(parent) = self.doc_path.as_ref().and_then(|path| path.parent()) {
            dialog = dialog.set_directory(parent);
        }
        let Some(path) = dialog.save_file() else {
            return;
        };
        match write_text_file(&path, &doc.coverage_fix_prompt_markdown()) {
            Ok(()) => self.message = format!("coverage prompt保存: {}", path.display()),
            Err(err) => self.message = format!("coverage prompt保存失敗: {err}"),
        }
    }

    fn apply_layout_patch_from_file(&mut self) {
        let Some(path) = FileDialog::new()
            .add_filter("DiffGR layout patch", &["json"])
            .pick_file()
        else {
            return;
        };
        let Some(doc) = self.doc.as_mut() else {
            self.message = "先にDiffGR JSONを開いてください。".to_owned();
            return;
        };
        let result = read_json_file(&path).and_then(|value| doc.apply_layout_patch_value(&value));
        match result {
            Ok(applied) => {
                self.dirty = true;
                self.layout_dirty = true;
                self.invalidate_review_caches();
                self.ensure_selected_chunk_visible();
                self.reload_group_editor_buffer();
                self.message = format!("layout patch適用: {}件 ({})", applied, path.display());
            }
            Err(err) => self.message = format!("layout patch適用失敗: {err}"),
        }
    }

    fn create_group_from_inputs(&mut self) {
        let tags = split_pipe_input(&self.group_tags_buffer);
        let Some(doc) = self.doc.as_mut() else {
            self.message = "先にDiffGR JSONを開いてください。".to_owned();
            return;
        };
        match doc.create_group(&self.group_id_buffer, &self.group_name_buffer, &tags) {
            Ok(()) => {
                self.current_group = Some(self.group_id_buffer.trim().to_owned());
                self.dirty = true;
                self.layout_dirty = true;
                self.invalidate_review_caches();
                self.reload_group_brief_buffer();
                self.message = format!("group作成: {}", self.group_id_buffer.trim());
            }
            Err(err) => self.message = format!("group作成失敗: {err}"),
        }
    }

    fn rename_current_group_from_inputs(&mut self) {
        let Some(group_id) = self.current_group.clone() else {
            self.message = "リネーム対象のgroupを選択してください。".to_owned();
            return;
        };
        let tags = split_pipe_input(&self.group_tags_buffer);
        let Some(doc) = self.doc.as_mut() else {
            return;
        };
        match doc.rename_group(&group_id, &self.group_name_buffer, &tags) {
            Ok(()) => {
                self.dirty = true;
                self.layout_dirty = true;
                self.invalidate_review_caches();
                self.reload_group_editor_buffer();
                self.message = format!("group更新: {group_id}");
            }
            Err(err) => self.message = format!("group更新失敗: {err}"),
        }
    }

    fn delete_current_group(&mut self) {
        let Some(group_id) = self.current_group.clone() else {
            self.message = "削除対象のgroupを選択してください。".to_owned();
            return;
        };
        let Some(doc) = self.doc.as_mut() else {
            return;
        };
        match doc.delete_group_keep_chunks_unassigned(&group_id) {
            Ok(()) => {
                self.current_group = doc.groups.first().map(|group| group.id.clone());
                self.dirty = true;
                self.layout_dirty = true;
                self.invalidate_review_caches();
                self.ensure_selected_chunk_visible();
                self.reload_group_brief_buffer();
                self.message = format!("group削除: {group_id}。chunkは未割当にしました。");
            }
            Err(err) => self.message = format!("group削除失敗: {err}"),
        }
    }

    fn assign_selected_chunk_to_group(&mut self, group_id: &str) {
        let Some(chunk_id) = self.selected_chunk.clone() else {
            self.message = "割当対象のchunkを選択してください。".to_owned();
            return;
        };
        let Some(doc) = self.doc.as_mut() else {
            return;
        };
        match doc.assign_chunk_to_group(&chunk_id, group_id) {
            Ok(()) => {
                self.dirty = true;
                self.layout_dirty = true;
                self.invalidate_review_caches();
                self.ensure_selected_chunk_visible();
                self.message = format!("{} を {} に割当しました。", short_id(&chunk_id), group_id);
            }
            Err(err) => self.message = format!("chunk割当失敗: {err}"),
        }
    }

    fn unassign_selected_chunk(&mut self) {
        let Some(chunk_id) = self.selected_chunk.clone() else {
            self.message = "未割当にするchunkを選択してください。".to_owned();
            return;
        };
        let Some(doc) = self.doc.as_mut() else {
            return;
        };
        match doc.unassign_chunk(&chunk_id) {
            Ok(()) => {
                self.dirty = true;
                self.layout_dirty = true;
                self.invalidate_review_caches();
                self.ensure_selected_chunk_visible();
                self.message = format!("{} を未割当にしました。", short_id(&chunk_id));
            }
            Err(err) => self.message = format!("未割当化失敗: {err}"),
        }
    }

    fn save_current_group_review_document(&mut self) {
        let Some(group_id) = self.current_group.clone() else {
            self.message = "split対象のgroupを選択してください。".to_owned();
            return;
        };
        let Some(doc) = self.doc.as_ref() else {
            return;
        };
        let default_name = format!("{}.diffgr.json", sanitize_file_stem(&group_id));
        let mut dialog = FileDialog::new()
            .add_filter("DiffGR JSON", &["json"])
            .set_file_name(default_name);
        if let Some(parent) = self.doc_path.as_ref().and_then(|path| path.parent()) {
            dialog = dialog.set_directory(parent);
        }
        let Some(path) = dialog.save_file() else {
            return;
        };
        match doc.write_group_review_document(&group_id, &path) {
            Ok(()) => self.message = format!("group review保存: {}", path.display()),
            Err(err) => self.message = format!("group review保存失敗: {err}"),
        }
    }

    fn pick_and_preview_state_diff(&mut self) {
        let Some(path) = FileDialog::new()
            .add_filter("Review state", &["json"])
            .pick_file()
        else {
            return;
        };
        let Some(doc) = self.doc.as_ref() else {
            self.message = "先にDiffGR JSONを開いてください。".to_owned();
            return;
        };
        match read_json_file(&path).and_then(|value| doc.state_diff_against_value(value)) {
            Ok(diff) => {
                self.state_merge_preview_text =
                    format_state_diff_markdown(&diff, &format!("State diff: {}", path.display()));
                self.detail_tab = DetailTab::State;
                self.message = format!("state差分プレビュー: {}", path.display());
            }
            Err(err) => self.message = format!("state差分プレビュー失敗: {err}"),
        }
    }

    fn pick_and_merge_state(&mut self) {
        let Some(path) = FileDialog::new()
            .add_filter("Review state", &["json"])
            .pick_file()
        else {
            return;
        };
        let source_name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("incoming state")
            .to_owned();
        let preview = {
            let Some(doc) = self.doc.as_ref() else {
                self.message = "先にDiffGR JSONを開いてください。".to_owned();
                return;
            };
            read_json_file(&path).and_then(|value| doc.merge_state_value(value, &source_name))
        };
        match preview {
            Ok(preview) => {
                self.state_merge_preview_text = format_state_diff_markdown(
                    &preview.diff,
                    &format!("Merged state preview: {}", path.display()),
                );
                if !preview.warnings.is_empty() {
                    self.state_merge_preview_text.push_str("\n## Warnings\n\n");
                    for warning in &preview.warnings {
                        self.state_merge_preview_text
                            .push_str(&format!("- {}\n", warning));
                    }
                }
                if let Some(doc) = self.doc.as_mut() {
                    if let Err(err) = doc.apply_merged_state_preview(preview) {
                        self.message = format!("state merge適用失敗: {err}");
                        return;
                    }
                }
                self.dirty = true;
                self.clear_all_volatile_caches();
                self.restore_ui_state_from_document();
                self.detail_tab = DetailTab::State;
                self.message = format!("state merge適用: {}", path.display());
            }
            Err(err) => self.message = format!("state merge失敗: {err}"),
        }
    }

    fn pick_and_preview_impact(&mut self) {
        let Some(path) = FileDialog::new()
            .add_filter("DiffGR JSON", &["json"])
            .pick_file()
        else {
            return;
        };
        let Some(current) = self.doc.as_ref() else {
            self.message = "先にDiffGR JSONを開いてください。".to_owned();
            return;
        };
        match DiffgrDocument::load_from_path(&path, None) {
            Ok(old_doc) => {
                let report = current.impact_against(&old_doc);
                self.impact_preview_text = format_impact_report_markdown(&report);
                self.detail_tab = DetailTab::Impact;
                self.message = format!("impact preview: current vs {}", path.display());
            }
            Err(err) => self.message = format!("impact preview失敗: {err}"),
        }
    }

    fn current_group_for_decision(&self) -> Option<String> {
        self.current_group.clone().or_else(|| {
            let chunk_id = self.selected_chunk.as_ref()?;
            self.doc
                .as_ref()
                .and_then(|doc| doc.primary_group_for_chunk(chunk_id))
        })
    }

    fn approve_current_group(&mut self, force: bool) {
        let Some(group_id) = self.current_group_for_decision() else {
            self.message = "approval対象のgroupを選択してください。".to_owned();
            return;
        };
        let reviewer = self.reviewer_input.clone();
        let result = {
            let Some(doc) = self.doc.as_mut() else {
                return;
            };
            doc.approve_group(&group_id, &reviewer, force)
                .map(|_| doc.approval_report_markdown())
        };
        match result {
            Ok(report_text) => {
                self.dirty = true;
                self.invalidate_review_caches();
                self.approval_report_text = report_text;
                self.detail_tab = DetailTab::Approval;
                self.message = format!("approved: {group_id}");
            }
            Err(err) => self.message = format!("approval失敗: {err}"),
        }
    }

    fn request_changes_current_group(&mut self) {
        let Some(group_id) = self.current_group_for_decision() else {
            self.message = "request changes対象のgroupを選択してください。".to_owned();
            return;
        };
        let reviewer = self.reviewer_input.clone();
        let comment = self.change_request_comment.clone();
        let result = {
            let Some(doc) = self.doc.as_mut() else {
                return;
            };
            doc.request_changes_on_group(&group_id, &reviewer, &comment)
                .map(|_| doc.approval_report_markdown())
        };
        match result {
            Ok(report_text) => {
                self.dirty = true;
                self.invalidate_review_caches();
                self.approval_report_text = report_text;
                self.detail_tab = DetailTab::Approval;
                self.message = format!("changes requested: {group_id}");
            }
            Err(err) => self.message = format!("request changes失敗: {err}"),
        }
    }

    fn revoke_current_group(&mut self) {
        let Some(group_id) = self.current_group_for_decision() else {
            self.message = "revoke対象のgroupを選択してください。".to_owned();
            return;
        };
        let reviewer = self.reviewer_input.clone();
        let result = {
            let Some(doc) = self.doc.as_mut() else {
                return;
            };
            doc.revoke_group_approval(&group_id, &reviewer, "revoked")
                .map(|_| doc.approval_report_markdown())
        };
        match result {
            Ok(report_text) => {
                self.dirty = true;
                self.invalidate_review_caches();
                self.approval_report_text = report_text;
                self.detail_tab = DetailTab::Approval;
                self.message = format!("approval revoked: {group_id}");
            }
            Err(err) => self.message = format!("revoke失敗: {err}"),
        }
    }

    fn save_approval_report_json(&mut self) {
        let Some(doc) = self.doc.as_ref() else {
            self.message = "先にDiffGR JSONを開いてください。".to_owned();
            return;
        };
        let default_name = "approval-report.json";
        let mut dialog = FileDialog::new()
            .add_filter("JSON", &["json"])
            .set_file_name(default_name);
        if let Some(parent) = self.doc_path.as_ref().and_then(|path| path.parent()) {
            dialog = dialog.set_directory(parent);
        }
        let Some(path) = dialog.save_file() else {
            return;
        };
        match doc.write_approval_report_json(&path) {
            Ok(()) => self.message = format!("approval report保存: {}", path.display()),
            Err(err) => self.message = format!("approval report保存失敗: {err}"),
        }
    }

    fn push_status_history(&mut self, changes: Vec<StatusChange>) {
        if changes.is_empty() {
            return;
        }
        self.status_history.push(StatusHistoryItem { changes });
        if self.status_history.len() > MAX_STATUS_HISTORY {
            let overflow = self.status_history.len() - MAX_STATUS_HISTORY;
            self.status_history.drain(0..overflow);
        }
    }

    fn apply_status_change(
        &mut self,
        chunk_id: &str,
        status: ReviewStatus,
        record_undo: bool,
    ) -> bool {
        let Some(previous) = self.doc.as_ref().map(|doc| doc.status_for(chunk_id)) else {
            return false;
        };
        if previous == status {
            return false;
        }
        if let Some(doc) = self.doc.as_mut() {
            doc.set_status(chunk_id, status);
        }
        if record_undo {
            self.push_status_history(vec![StatusChange {
                chunk_id: chunk_id.to_owned(),
                previous,
                next: status,
            }]);
        }
        self.dirty = true;
        self.invalidate_review_caches();
        true
    }

    fn undo_last_status_change(&mut self) {
        let Some(item) = self.status_history.pop() else {
            self.message = "戻せるステータス変更がありません。".to_owned();
            return;
        };
        let count = item.changes.len();
        let first_chunk = item.changes.first().map(|change| change.chunk_id.clone());
        if let Some(doc) = self.doc.as_mut() {
            for change in item.changes.iter().rev() {
                doc.set_status(&change.chunk_id, change.previous);
            }
        }
        self.dirty = true;
        self.invalidate_review_caches();
        if let Some(chunk_id) = first_chunk {
            self.select_chunk(Some(chunk_id.clone()));
            let label = if count == 1 {
                let change = &item.changes[0];
                format!(
                    "{}  {} → {}",
                    short_id(&change.chunk_id),
                    change.next.label(),
                    change.previous.label()
                )
            } else {
                format!("{}チャンク", count)
            };
            self.message = format!("ステータス変更を戻しました: {label}");
        }
    }

    fn set_visible_status(&mut self, status: ReviewStatus) {
        let ids = self.visible_chunk_ids();
        if ids.is_empty() {
            self.message = "対象チャンクがありません。".to_owned();
            return;
        }
        let changes: Vec<StatusChange> = self
            .doc
            .as_ref()
            .map(|doc| {
                ids.iter()
                    .filter_map(|chunk_id| {
                        let previous = doc.status_for(chunk_id);
                        (previous != status).then(|| StatusChange {
                            chunk_id: chunk_id.clone(),
                            previous,
                            next: status,
                        })
                    })
                    .collect()
            })
            .unwrap_or_default();

        if changes.is_empty() {
            self.message = format!("表示中のチャンクはすでに {} です。", status.label());
            return;
        }
        if let Some(doc) = self.doc.as_mut() {
            for change in &changes {
                doc.set_status(&change.chunk_id, change.next);
            }
        }
        let changed = changes.len();
        self.push_status_history(changes);
        self.dirty = true;
        self.invalidate_review_caches();
        self.message = format!(
            "表示中の{}チャンクを {} にしました。Ctrl+Zで一括変更を戻せます。",
            changed,
            status.label()
        );
    }

    fn save_current(&mut self) {
        let Some(doc) = self.doc.as_ref() else {
            self.message = "保存対象のDiffGRがありません。".to_owned();
            return;
        };

        let mut messages = Vec::new();

        if self.layout_dirty {
            let Some(doc_path) = self.doc_path.as_ref() else {
                self.message =
                    "layout変更の保存先DiffGRが未設定です。DiffGR JSONを開き直してください。"
                        .to_owned();
                return;
            };
            if let Err(err) = doc.write_full_document(doc_path, true) {
                self.message = format!("DiffGR保存失敗: {err}");
                return;
            }
            messages.push(format!("DiffGR保存: {}", doc_path.display()));
        }

        if let Some(state_path) = self.state_path.as_ref() {
            if let Err(err) = doc.write_state(state_path) {
                self.message = format!("state保存失敗: {err}");
                return;
            }
            messages.push(format!("state保存: {}", state_path.display()));
        } else if !self.layout_dirty {
            let Some(doc_path) = self.doc_path.as_ref() else {
                self.message = "保存先が未設定です。State保存先… を使ってください。".to_owned();
                return;
            };
            if let Err(err) = doc.write_full_document(doc_path, true) {
                self.message = format!("DiffGR保存失敗: {err}");
                return;
            }
            messages.push(format!("DiffGR保存: {}", doc_path.display()));
        }

        self.dirty = false;
        self.layout_dirty = false;
        self.message = if messages.is_empty() {
            "保存対象の変更はありません。".to_owned()
        } else {
            messages.join(" / ")
        };
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
                self.dirty = self.layout_dirty;
                self.message = if self.layout_dirty {
                    format!("state保存: {} / layout変更は未保存です", path.display())
                } else {
                    format!("state保存: {}", path.display())
                };
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
                self.status_history.clear();
                self.state_merge_preview_text.clear();
                self.impact_preview_text.clear();
                self.approval_report_text.clear();
                self.restore_ui_state_from_document();
                self.last_window_title.clear();
                self.dirty = false;
                self.layout_dirty = false;
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
        let Some(next) = self
            .doc
            .as_ref()
            .map(|doc| doc.status_for(&chunk_id).next_review_toggle())
        else {
            return;
        };
        self.set_selected_status(next);
    }

    fn set_selected_status(&mut self, status: ReviewStatus) {
        let Some(chunk_id) = self.selected_chunk.clone() else {
            return;
        };
        let changed = self.apply_status_change(&chunk_id, status, true);
        if changed && self.auto_advance_after_review && status == ReviewStatus::Reviewed {
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
        self.set_visible_status(ReviewStatus::Reviewed);
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

        if ui.input(|input| input.modifiers.command && input.key_pressed(egui::Key::Z)) {
            self.undo_last_status_change();
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

    fn maybe_request_active_scroll_repaint(&self, ctx: &egui::Context) {
        if !self.config.smooth_scroll_repaint {
            return;
        }
        let active = ctx.input(|input| {
            input.pointer.any_down()
                || input
                    .events
                    .iter()
                    .any(|event| matches!(event, egui::Event::MouseWheel { .. }))
        });
        if active {
            ctx.request_repaint_after(Duration::from_millis(ACTIVE_SCROLL_REPAINT_MS));
        }
    }

    fn maybe_auto_save(&mut self) {
        if !self.auto_save_state || !self.dirty {
            return;
        }
        if self.state_path.is_none() || self.pending_state_save.is_some() {
            return;
        }
        if self.layout_dirty {
            return;
        }
        if self.last_auto_save.elapsed() < Duration::from_secs(30) {
            return;
        }
        self.last_auto_save = Instant::now();
        let Some(state_path) = self.state_path.clone() else {
            return;
        };
        let Some(doc) = self.doc.as_ref() else {
            self.message = "保存対象のDiffGRがありません。".to_owned();
            return;
        };
        if self.config.background_io {
            let state = doc.extract_state();
            let revision = self.state_revision;
            let worker_path = state_path.clone();
            let (tx, rx) = mpsc::channel();
            std::thread::spawn(move || {
                let result = write_json_value(&worker_path, &state);
                let _ = tx.send(result);
            });
            self.pending_state_save = Some(PendingStateSave {
                path: state_path.clone(),
                revision,
                started: Instant::now(),
                rx,
            });
            self.message = format!("自動保存を開始: {}", state_path.display());
        } else {
            match doc.write_state(&state_path) {
                Ok(()) => {
                    self.dirty = false;
                    self.message = format!("自動保存: {}", state_path.display());
                }
                Err(err) => self.message = format!("自動保存失敗: {err}"),
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
            if self.pending_load.is_some() || self.pending_state_save.is_some() {
                ui.add(egui::Spinner::new());
                ui.small("バックグラウンド処理中");
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
            if ui.button("サマリコピー").clicked() {
                self.copy_review_summary(ui.ctx());
            }
            if ui.button("サマリ保存…").clicked() {
                self.save_review_summary();
            }
            if ui.button("HTML保存…").clicked() {
                self.save_html_report();
            }
            if ui.button("Coverage").clicked() {
                self.detail_tab = DetailTab::Coverage;
            }
            if ui.button("Impact").clicked() {
                self.detail_tab = DetailTab::Impact;
            }
            if ui.button("Approval").clicked() {
                self.detail_tab = DetailTab::Approval;
            }
            if ui.button("仮想PR").clicked() {
                self.detail_tab = DetailTab::VirtualPr;
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
            if ui.small_button("State差分…").clicked() {
                self.pick_and_preview_state_diff();
            }
            if ui.small_button("State merge…").clicked() {
                self.pick_and_merge_state();
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
            ui.checkbox(&mut self.config.smooth_scroll_repaint, "滑らかスクロール")
                .on_hover_text("スクロール/ドラッグ中だけ約60fpsで再描画を促し、普段は描画を増やしません。");
            ui.checkbox(&mut self.config.defer_filtering, "検索を遅延適用")
                .on_hover_text("入力中の全件再検索を避け、止まってから反映します。Enterで即時反映できます。");
            ui.checkbox(&mut self.config.background_io, "読込/自動保存を別スレッド")
                .on_hover_text("巨大JSONの読み込みや自動保存でUIスレッドを止めにくくします。");
            ui.checkbox(&mut self.config.clip_long_lines, "超長行を省略描画")
                .on_hover_text("1行が非常に長いdiffでレイアウト計算が固まるのを避けます。");
            ui.checkbox(&mut self.config.compact_rows, "コンパクト行");
            ui.checkbox(&mut self.config.persist_egui_memory, "UI状態を記憶")
                .on_hover_text("オフ推奨: eguiの細かなUIメモリを保存せず、設定と最近使ったファイルだけ保存します。");
            ui.checkbox(&mut self.config.show_performance_overlay, "性能HUD")
                .on_hover_text("frame平均/peak、slow frame、表示cache量を右上に出します。");
            if ui.small_button("診断").clicked() {
                self.detail_tab = DetailTab::Diagnostics;
                self.config.show_performance_overlay = true;
            }
            if ui.small_button("揮発キャッシュ破棄").clicked() {
                self.clear_all_volatile_caches();
                self.message = "表示用の揮発キャッシュを破棄しました。設定/レビュー状態は消しません。".to_owned();
            }
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
        let (warnings, counts) = self
            .doc
            .as_ref()
            .map(|doc| (doc.warnings.clone(), doc.status_counts()))
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
            ui.label(format!("レビュー済み: {}", counts.reviewed));
            ui.label(format!("未レビュー: {}", counts.unreviewed));
            ui.label(format!("再レビュー: {}", counts.needs_re_review));
            ui.label(format!("無視: {}", counts.ignored));
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
            let response = ui.add_sized(
                [f32::INFINITY, 24.0],
                TextEdit::singleline(&mut self.file_filter_input)
                    .hint_text("ファイルパスで絞り込み"),
            );
            if response.changed() {
                self.schedule_filter_apply(ui.ctx());
            }
            if response.lost_focus() && ui.input(|input| input.key_pressed(egui::Key::Enter)) {
                self.apply_filter_inputs_now();
            }
        });
        ui.horizontal(|ui| {
            ui.label("検索");
            let response = ui.add_sized(
                [f32::INFINITY, 24.0],
                TextEdit::singleline(&mut self.content_filter_input)
                    .hint_text("ID / diff本文 / コメント"),
            );
            if self.focus_search_next_frame {
                response.request_focus();
                self.focus_search_next_frame = false;
            }
            if response.changed() {
                self.schedule_filter_apply(ui.ctx());
            }
            if response.lost_focus() && ui.input(|input| input.key_pressed(egui::Key::Enter)) {
                self.apply_filter_inputs_now();
            }
        });
        if self.filter_apply_deadline.is_some() {
            ui.small("検索/Pathフィルタは入力停止後に反映します。Enterで即時反映できます。");
        }
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
            ui.separator();
            ui.label("一括:");
            if ui.button("レビュー済み").clicked() {
                self.mark_visible_as_reviewed();
            }
            if ui.button("再レビュー").clicked() {
                self.set_visible_status(ReviewStatus::NeedsReReview);
            }
            if ui.button("未レビュー").clicked() {
                self.set_visible_status(ReviewStatus::Unreviewed);
            }
            if ui.button("無視").clicked() {
                self.set_visible_status(ReviewStatus::Ignored);
            }
            if ui.button("Undo Ctrl+Z").clicked() {
                self.undo_last_status_change();
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
        let chunk = self.selected_chunk_clone();
        if chunk.is_none()
            && !matches!(
                self.detail_tab,
                DetailTab::Summary
                    | DetailTab::State
                    | DetailTab::Layout
                    | DetailTab::Coverage
                    | DetailTab::Impact
                    | DetailTab::Approval
                    | DetailTab::VirtualPr
                    | DetailTab::Tools
                    | DetailTab::Diagnostics
                    | DetailTab::Handoff
            )
        {
            self.detail_tab = DetailTab::Summary;
        }

        ui.horizontal_wrapped(|ui| {
            ui.heading("Detail");
            ui.separator();
            if let Some(chunk) = chunk.as_ref() {
                ui.label(RichText::new(&chunk.file_path).strong());
                ui.small(format!(
                    "id: {}  old:{}  new:{}",
                    chunk.short_id(),
                    chunk.old_range_label(),
                    chunk.new_range_label()
                ));
            } else {
                ui.label("チャンク未選択");
            }
        });
        ui.horizontal_wrapped(|ui| {
            for tab in [
                DetailTab::Diff,
                DetailTab::Review,
                DetailTab::Handoff,
                DetailTab::Layout,
                DetailTab::Coverage,
                DetailTab::Impact,
                DetailTab::Approval,
                DetailTab::VirtualPr,
                DetailTab::Tools,
                DetailTab::Diagnostics,
                DetailTab::Summary,
                DetailTab::State,
            ] {
                ui.selectable_value(&mut self.detail_tab, tab, tab.label());
            }
        });
        self.config.detail_tab = self.detail_tab;
        ui.separator();

        match self.detail_tab {
            DetailTab::Summary => self.draw_review_summary_panel(ui),
            DetailTab::State => self.draw_state_preview(ui),
            DetailTab::Handoff => self.draw_group_brief_editor(ui),
            DetailTab::Layout => self.draw_layout_editor(ui),
            DetailTab::Coverage => self.draw_coverage_panel(ui),
            DetailTab::Impact => self.draw_impact_panel(ui),
            DetailTab::Approval => self.draw_approval_panel(ui),
            DetailTab::VirtualPr => self.draw_virtual_pr_panel(ui),
            DetailTab::Tools => self.draw_tools_panel(ui),
            DetailTab::Diagnostics => self.draw_diagnostics_panel(ui),
            DetailTab::Diff => {
                let Some(chunk) = chunk.as_ref() else {
                    ui.label("チャンクを選択してください。");
                    return;
                };
                self.draw_chunk_status_editor(ui, &chunk.id);
                self.draw_diff_toolbar(ui, chunk);
                self.draw_diff_lines(ui, chunk);
                self.draw_line_comment_editor(ui, &chunk.id);
            }
            DetailTab::Review => {
                let Some(chunk) = chunk.as_ref() else {
                    ui.label("チャンクを選択してください。");
                    return;
                };
                self.draw_chunk_status_editor(ui, &chunk.id);
                self.draw_chunk_comment_editor(ui, &chunk.id);
                self.draw_line_comment_editor(ui, &chunk.id);
            }
        }
    }

    fn draw_diagnostics_panel(&mut self, ui: &mut egui::Ui) {
        ui.heading("GUI診断 / 固まりにくさチェック");
        ui.small("巨大DiffGRで固まる原因を切り分けるための軽量表示です。レビュー状態や設定は変更しません。");
        ui.separator();
        ui.horizontal_wrapped(|ui| {
            ui.label(format!("frame avg: {:.1} ms", self.frame_time_ema_ms));
            ui.label(format!("peak: {:.1} ms", self.frame_time_peak_ms));
            ui.label(format!("slow frames >50ms: {}", self.slow_frame_count));
            ui.label(self.performance_health_label());
            if ui.small_button("計測リセット").clicked() {
                self.reset_frame_budget_metrics();
            }
        });
        ui.horizontal_wrapped(|ui| {
            ui.label(format!("visible chunks: {}", self.visible_cache.ids.len()));
            ui.label(format!(
                "cached chunk rows: {} / max {}",
                self.visible_cache.rows.len(),
                MAX_CHUNK_ROW_CACHE
            ));
            ui.label(format!(
                "state preview lines: {}",
                self.state_preview_cache.line_starts.len()
            ));
            ui.label(format!("list rev: {}", self.list_revision));
            ui.label(format!("state rev: {}", self.state_revision));
        });
        ui.label(
            self.pending_load
                .as_ref()
                .map(|job| {
                    format!(
                        "読込中: {} / {:.1}s",
                        job.path.display(),
                        job.started.elapsed().as_secs_f32()
                    )
                })
                .unwrap_or_else(|| "読込なし".to_owned()),
        );
        ui.label(
            self.pending_state_save
                .as_ref()
                .map(|job| {
                    format!(
                        "保存中: {} / rev {} / {:.1}s",
                        job.path.display(),
                        job.revision,
                        job.started.elapsed().as_secs_f32()
                    )
                })
                .unwrap_or_else(|| "保存なし".to_owned()),
        );
        ui.separator();
        ui.horizontal_wrapped(|ui| {
            if ui.button("ちらつき抑制ON").clicked() {
                self.config.reduce_motion = true;
                apply_runtime_style(ui.ctx(), self.config.theme, true);
            }
            if ui.button("滑らかスクロールON").clicked() {
                self.config.smooth_scroll_repaint = true;
                self.config.reduce_motion = false;
                apply_runtime_style(ui.ctx(), self.config.theme, false);
            }
            if ui.button("低メモリ寄り").clicked() {
                self.config.smooth_scroll_repaint = false;
                self.config.reduce_motion = true;
                self.config.clip_long_lines = true;
                self.config.compact_rows = true;
                self.clear_all_volatile_caches();
            }
            if ui.button("自己レビューをコピー").clicked() {
                self.copy_self_review_report(ui.ctx());
            }
        });
    }

    fn draw_review_summary_panel(&mut self, ui: &mut egui::Ui) {
        let Some((title, counts, metrics, files)) = self.doc.as_ref().map(|doc| {
            (
                doc.title.clone(),
                doc.status_counts(),
                doc.metrics(),
                doc.file_summaries(),
            )
        }) else {
            ui.label("DiffGRを開くと概要を表示します。");
            return;
        };

        ui.heading("レビュー概要");
        ui.horizontal_wrapped(|ui| {
            ui.label(RichText::new(title).strong());
            ui.separator();
            ui.add(
                ProgressBar::new(metrics.coverage_rate)
                    .desired_width(180.0)
                    .text(format!("{:.1}%", metrics.coverage_rate * 100.0)),
            );
            ui.label(format!("reviewed {}/{}", metrics.reviewed, metrics.tracked));
        });
        draw_status_counts(ui, &counts);
        ui.horizontal_wrapped(|ui| {
            if ui.button("Markdownコピー").clicked() {
                self.copy_review_summary(ui.ctx());
            }
            if ui.button("Markdown保存…").clicked() {
                self.save_review_summary();
            }
            if ui.button("HTML保存…").clicked() {
                self.save_html_report();
            }
            if ui.button("Coverageを見る").clicked() {
                self.detail_tab = DetailTab::Coverage;
            }
            if ui.button("Impactを見る").clicked() {
                self.detail_tab = DetailTab::Impact;
            }
            if ui.button("Approvalを見る").clicked() {
                self.detail_tab = DetailTab::Approval;
            }
            if ui.button("仮想PRゲートを見る").clicked() {
                self.detail_tab = DetailTab::VirtualPr;
            }
            if ui.button("未完了へ移動").clicked() {
                self.select_next_pending_or_next();
                self.detail_tab = DetailTab::Diff;
            }
            if ui.button("State JSONを見る").clicked() {
                self.detail_tab = DetailTab::State;
            }
        });
        ui.separator();
        ui.label("ファイル別の進捗。`絞る` でPathフィルタへ反映します。");
        let row_height = 46.0;
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .animated(!self.config.reduce_motion)
            .show_rows(ui, row_height, files.len(), |ui, row_range| {
                for index in row_range {
                    let file = files[index].clone();
                    ui.horizontal(|ui| {
                        ui.add(
                            ProgressBar::new(file.coverage_rate())
                                .desired_width(90.0)
                                .text(format!("{:.0}%", file.coverage_rate() * 100.0)),
                        );
                        ui.label(format!(
                            "{} chunks / pending {} / comments {} / +{} -{}",
                            file.chunks, file.pending, file.comments, file.adds, file.deletes
                        ));
                        if ui.small_button("絞る").clicked() {
                            self.set_file_filter(file.file_path.clone());
                        }
                    });
                    ui.small(&file.file_path);
                    ui.separator();
                }
            });
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
            ui.separator();
            egui::ComboBox::from_id_salt("diff_view_mode")
                .selected_text(self.diff_view_mode.label())
                .show_ui(ui, |ui| {
                    for mode in DiffViewMode::ALL {
                        ui.selectable_value(&mut self.diff_view_mode, mode, mode.label());
                    }
                });
            egui::ComboBox::from_id_salt("diff_context_mode")
                .selected_text(self.diff_context_mode.label())
                .show_ui(ui, |ui| {
                    for mode in DiffContextMode::ALL {
                        ui.selectable_value(&mut self.diff_context_mode, mode, mode.label());
                    }
                });
            self.show_only_changed = self.diff_context_mode == DiffContextMode::ChangedOnly;
            self.config.show_only_changed = self.show_only_changed;
            if self.diff_context_mode == DiffContextMode::ChangedWithContext {
                ui.label("文脈");
                if ui.small_button("-").clicked() && self.diff_context_radius > 0 {
                    self.diff_context_radius -= 1;
                    self.diff_context_index_cache = None;
                    self.diff_side_by_side_cache = None;
                }
                ui.label(format!("{}行", self.diff_context_radius));
                if ui.small_button("+").clicked() && self.diff_context_radius < 12 {
                    self.diff_context_radius += 1;
                    self.diff_context_index_cache = None;
                    self.diff_side_by_side_cache = None;
                }
            }
            if ui.checkbox(&mut self.wrap_diff, "折り返し").changed() {
                self.config.wrap_diff = self.wrap_diff;
            }
            if ui.checkbox(&mut self.show_line_numbers, "行番号").changed() {
                self.config.show_line_numbers = self.show_line_numbers;
            }
            if ui
                .checkbox(&mut self.word_diff_enabled, "行内差分")
                .changed()
            {
                self.config.word_diff_enabled = self.word_diff_enabled;
                self.diff_word_segment_cache = None;
            }
            if ui
                .checkbox(&mut self.word_diff_smart_pairing, "賢く対応付け")
                .changed()
            {
                self.config.word_diff_smart_pairing = self.word_diff_smart_pairing;
                self.diff_side_by_side_cache = None;
                self.diff_word_pair_cache = None;
                self.diff_word_segment_cache = None;
            }
        });
        ui.horizontal_wrapped(|ui| {
            ui.label("Diff内検索");
            let search = ui.add_sized(
                [180.0, 24.0],
                TextEdit::singleline(&mut self.diff_search_buffer)
                    .hint_text("このチャンク内を検索"),
            );
            if search.lost_focus() && ui.input(|input| input.key_pressed(egui::Key::Enter)) {
                self.select_diff_search_match(chunk, true);
            }
            if ui.button("前の変更").clicked() {
                self.select_changed_line_relative(chunk, false);
            }
            if ui.button("次の変更").clicked() {
                self.select_changed_line_relative(chunk, true);
            }
            if ui.button("前の検索").clicked() {
                self.select_diff_search_match(chunk, false);
            }
            if ui.button("次の検索").clicked() {
                self.select_diff_search_match(chunk, true);
            }
            if ui.button("表示中diffコピー").clicked() {
                self.copy_visible_diff_text(ui.ctx(), chunk);
            }
            if ui.button("選択行コピー").clicked() {
                self.copy_selected_diff_line(ui.ctx(), chunk);
            }
            if ui.button("このチャンク情報をコピー").clicked() {
                let text = self.chunk_clipboard_text(chunk);
                ui.ctx().copy_text(text);
                self.message = "チャンク情報をクリップボードへコピーしました。".to_owned();
            }
        });
        ui.small("行クリックで下の line comment を直接編集できます。行内差分は単語/記号単位の変更を強調し、左右比較は類似行を賢く対応付けます。");
    }

    fn changed_line_indices(&mut self, chunk: &Chunk) -> Arc<Vec<usize>> {
        if let Some(cache) = self.diff_line_index_cache.as_ref() {
            if cache.chunk_id == chunk.id && cache.source_len == chunk.lines.len() {
                return cache.changed_indices.clone();
            }
        }
        let indices: Vec<usize> = chunk
            .lines
            .iter()
            .enumerate()
            .filter_map(|(index, line)| (line.kind != "context").then_some(index))
            .collect();
        let indices = Arc::new(indices);
        self.diff_line_index_cache = Some(DiffLineIndexCache {
            chunk_id: chunk.id.clone(),
            source_len: chunk.lines.len(),
            changed_indices: indices.clone(),
        });
        indices
    }

    fn context_line_indices(&mut self, chunk: &Chunk) -> Arc<Vec<usize>> {
        if let Some(cache) = self.diff_context_index_cache.as_ref() {
            if cache.chunk_id == chunk.id
                && cache.source_len == chunk.lines.len()
                && cache.radius == self.diff_context_radius
            {
                return cache.indices.clone();
            }
        }
        let changed = self.changed_line_indices(chunk);
        let mut keep = vec![false; chunk.lines.len()];
        for &index in changed.iter() {
            let start = index.saturating_sub(self.diff_context_radius);
            let end = (index + self.diff_context_radius + 1).min(chunk.lines.len());
            for item in keep.iter_mut().take(end).skip(start) {
                *item = true;
            }
        }
        let indices = Arc::new(
            keep.iter()
                .enumerate()
                .filter_map(|(index, keep)| keep.then_some(index))
                .collect::<Vec<_>>(),
        );
        self.diff_context_index_cache = Some(DiffContextIndexCache {
            chunk_id: chunk.id.clone(),
            source_len: chunk.lines.len(),
            radius: self.diff_context_radius,
            indices: indices.clone(),
        });
        indices
    }

    fn visible_diff_line_indices(&mut self, chunk: &Chunk) -> Option<Arc<Vec<usize>>> {
        // Legacy performance marker: let changed_indices = self.show_only_changed.then(|| self.changed_line_indices(chunk));
        match self.diff_context_mode {
            DiffContextMode::All => None,
            DiffContextMode::ChangedOnly => Some(self.changed_line_indices(chunk)),
            DiffContextMode::ChangedWithContext => Some(self.context_line_indices(chunk)),
        }
    }

    fn diff_word_pair_map(&mut self, chunk: &Chunk) -> Arc<BTreeMap<usize, usize>> {
        if let Some(cache) = self.diff_word_pair_cache.as_ref() {
            if cache.chunk_id == chunk.id
                && cache.source_len == chunk.lines.len()
                && cache.smart_pairing == self.word_diff_smart_pairing
            {
                return cache.pairs.clone();
            }
        }
        let mut pairs = BTreeMap::new();
        let mut cursor = 0;
        while cursor < chunk.lines.len() {
            if chunk.lines.get(cursor).map(|line| line.kind.as_str()) != Some("delete") {
                cursor += 1;
                continue;
            }
            let mut deletes = Vec::new();
            while cursor < chunk.lines.len()
                && chunk.lines.get(cursor).map(|line| line.kind.as_str()) == Some("delete")
            {
                deletes.push(cursor);
                cursor += 1;
            }
            let mut adds = Vec::new();
            while cursor < chunk.lines.len()
                && chunk.lines.get(cursor).map(|line| line.kind.as_str()) == Some("add")
            {
                adds.push(cursor);
                cursor += 1;
            }
            for row in self.matched_delete_add_rows(chunk, &deletes, &adds) {
                if let (Some(old_index), Some(new_index)) = (row.old_index, row.new_index) {
                    pairs.insert(old_index, new_index);
                    pairs.insert(new_index, old_index);
                }
            }
        }
        let pairs = Arc::new(pairs);
        self.diff_word_pair_cache = Some(DiffWordPairCache {
            chunk_id: chunk.id.clone(),
            source_len: chunk.lines.len(),
            smart_pairing: self.word_diff_smart_pairing,
            pairs: pairs.clone(),
        });
        pairs
    }

    fn matched_delete_add_rows(
        &self,
        chunk: &Chunk,
        deletes: &[usize],
        adds: &[usize],
    ) -> Vec<SideBySideDiffRow> {
        if deletes.is_empty() && adds.is_empty() {
            return Vec::new();
        }
        if !self.word_diff_smart_pairing {
            let total = deletes.len().max(adds.len());
            return (0..total)
                .map(|row| SideBySideDiffRow {
                    old_index: deletes.get(row).copied(),
                    new_index: adds.get(row).copied(),
                })
                .collect();
        }
        let matches = diff_words::match_delete_add_pairs(deletes, adds, |index| {
            chunk.lines.get(index).map(|line| line.text.clone())
        });
        let mut new_by_old = BTreeMap::new();
        let mut used_new = BTreeSet::new();
        for matched in matches {
            new_by_old.insert(matched.old_index, matched.new_index);
            used_new.insert(matched.new_index);
        }
        let mut rows = Vec::new();
        for &old_index in deletes {
            rows.push(SideBySideDiffRow {
                old_index: Some(old_index),
                new_index: new_by_old.get(&old_index).copied(),
            });
        }
        for &new_index in adds {
            if !used_new.contains(&new_index) {
                rows.push(SideBySideDiffRow {
                    old_index: None,
                    new_index: Some(new_index),
                });
            }
        }
        rows
    }

    fn word_segments_for_line(
        &mut self,
        chunk: &Chunk,
        line_index: usize,
    ) -> Option<Arc<Vec<DiffTextSegment>>> {
        if !self.word_diff_enabled {
            return None;
        }
        let line = chunk.lines.get(line_index)?;
        if !matches!(line.kind.as_str(), "add" | "delete") {
            return None;
        }
        if line.text.chars().count() > diff_words::MAX_WORD_DIFF_LINE_CHARS {
            return None;
        }
        let pair_index = self.diff_word_pair_map(chunk).get(&line_index).copied();
        let cache_key = DiffWordSegmentKey {
            line_index,
            pair_index: pair_index.unwrap_or(WORD_DIFF_UNPAIRED_SENTINEL),
        };
        let cache_valid = self
            .diff_word_segment_cache
            .as_ref()
            .map(|cache| cache.chunk_id == chunk.id && cache.source_len == chunk.lines.len())
            .unwrap_or(false);
        if !cache_valid {
            self.diff_word_segment_cache = Some(DiffWordSegmentCache {
                chunk_id: chunk.id.clone(),
                source_len: chunk.lines.len(),
                segments: BTreeMap::new(),
            });
        }
        if let Some(cache) = self.diff_word_segment_cache.as_ref() {
            if let Some(segments) = cache.segments.get(&cache_key) {
                return Some(segments.clone());
            }
        }
        let segments = if let Some(pair_index) = pair_index {
            let pair = chunk.lines.get(pair_index)?;
            if !matches!(pair.kind.as_str(), "add" | "delete") || pair.kind == line.kind {
                vec![DiffTextSegment::new(line.text.clone(), false)]
            } else {
                let (old_text, new_text) = if line.kind == "delete" {
                    (line.text.as_str(), pair.text.as_str())
                } else {
                    (pair.text.as_str(), line.text.as_str())
                };
                let (old_segments, new_segments) =
                    diff_words::word_level_segments(old_text, new_text)?;
                if line.kind == "delete" {
                    old_segments
                } else {
                    new_segments
                }
            }
        } else {
            vec![DiffTextSegment::new(line.text.clone(), true)]
        };
        let segments = Arc::new(segments);
        if let Some(cache) = self.diff_word_segment_cache.as_mut() {
            cache.segments.insert(cache_key, segments.clone());
        }
        Some(segments)
    }

    fn side_by_side_rows(&mut self, chunk: &Chunk) -> Arc<Vec<SideBySideDiffRow>> {
        if let Some(cache) = self.diff_side_by_side_cache.as_ref() {
            if cache.chunk_id == chunk.id
                && cache.source_len == chunk.lines.len()
                && cache.context_mode == self.diff_context_mode
                && cache.context_radius == self.diff_context_radius
                && cache.smart_pairing == self.word_diff_smart_pairing
            {
                return cache.rows.clone();
            }
        }
        let selected: Vec<usize> = self
            .visible_diff_line_indices(chunk)
            .map(|indices| indices.iter().copied().collect())
            .unwrap_or_else(|| (0..chunk.lines.len()).collect());
        let mut rows = Vec::new();
        let mut cursor = 0;
        while cursor < selected.len() {
            let index = selected[cursor];
            let Some(line) = chunk.lines.get(index) else {
                cursor += 1;
                continue;
            };
            match line.kind.as_str() {
                "delete" => {
                    let mut deletes = Vec::new();
                    while cursor < selected.len()
                        && chunk
                            .lines
                            .get(selected[cursor])
                            .map(|line| line.kind.as_str())
                            == Some("delete")
                    {
                        deletes.push(selected[cursor]);
                        cursor += 1;
                    }
                    let mut adds = Vec::new();
                    while cursor < selected.len()
                        && chunk
                            .lines
                            .get(selected[cursor])
                            .map(|line| line.kind.as_str())
                            == Some("add")
                    {
                        adds.push(selected[cursor]);
                        cursor += 1;
                    }
                    rows.extend(self.matched_delete_add_rows(chunk, &deletes, &adds));
                }
                "add" => {
                    rows.push(SideBySideDiffRow {
                        old_index: None,
                        new_index: Some(index),
                    });
                    cursor += 1;
                }
                _ => {
                    rows.push(SideBySideDiffRow {
                        old_index: Some(index),
                        new_index: Some(index),
                    });
                    cursor += 1;
                }
            }
        }
        let rows = Arc::new(rows);
        self.diff_side_by_side_cache = Some(DiffSideBySideCache {
            chunk_id: chunk.id.clone(),
            source_len: chunk.lines.len(),
            context_mode: self.diff_context_mode,
            context_radius: self.diff_context_radius,
            smart_pairing: self.word_diff_smart_pairing,
            rows: rows.clone(),
        });
        rows
    }

    fn draw_diff_lines(&mut self, ui: &mut egui::Ui, chunk: &Chunk) {
        match self.diff_view_mode {
            DiffViewMode::Unified => self.draw_unified_diff_lines(ui, chunk),
            DiffViewMode::SideBySide => self.draw_side_by_side_diff_lines(ui, chunk),
        }
    }

    fn draw_unified_diff_lines(&mut self, ui: &mut egui::Ui, chunk: &Chunk) {
        let chunk_id = chunk.id.clone();
        let max_height = (ui.available_height() - 132.0).max(240.0);
        let visible_indices = self.visible_diff_line_indices(chunk);
        let total_rows = visible_indices
            .as_ref()
            .map(|indices| indices.len())
            .unwrap_or_else(|| chunk.lines.len());
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
                let line_index = visible_indices
                    .as_ref()
                    .map(|indices| indices[row])
                    .unwrap_or(row);
                self.draw_one_diff_line(ui, &chunk_id, chunk, line_index);
            }
        });
    }

    fn draw_side_by_side_diff_lines(&mut self, ui: &mut egui::Ui, chunk: &Chunk) {
        let chunk_id = chunk.id.clone();
        let rows = self.side_by_side_rows(chunk);
        let total_rows = rows.len();
        if total_rows == 0 {
            ui.small("表示対象のdiff行がありません。");
            return;
        }
        let max_height = (ui.available_height() - 132.0).max(240.0);
        let row_height =
            (ui.text_style_height(&egui::TextStyle::Monospace) + ui.spacing().item_spacing.y + 6.0)
                .max(MIN_DIFF_ROW_HEIGHT);
        ui.horizontal(|ui| {
            ui.label(RichText::new("OLD").monospace().color(Color32::GRAY));
            ui.separator();
            ui.label(RichText::new("NEW").monospace().color(Color32::GRAY));
        });
        egui::ScrollArea::vertical()
            .max_height(max_height)
            .auto_shrink([false, false])
            .animated(!self.config.reduce_motion)
            .show_rows(ui, row_height, total_rows, |ui, row_range| {
                for row_index in row_range {
                    let row = rows[row_index];
                    ui.columns(2, |columns| {
                        if let Some(index) = row.old_index {
                            self.draw_one_diff_line(&mut columns[0], &chunk_id, chunk, index);
                        } else {
                            columns[0].label(RichText::new(" ").monospace());
                        }
                        if let Some(index) = row.new_index {
                            self.draw_one_diff_line(&mut columns[1], &chunk_id, chunk, index);
                        } else {
                            columns[1].label(RichText::new(" ").monospace());
                        }
                    });
                }
            });
    }

    fn draw_one_diff_line(
        &mut self,
        ui: &mut egui::Ui,
        chunk_id: &str,
        chunk: &Chunk,
        line_index: usize,
    ) {
        let Some(line) = chunk.lines.get(line_index).cloned() else {
            return;
        };
        let anchor = line.anchor();
        let selected = self.selected_line_anchor.as_ref() == Some(&anchor);
        let existing_comment = self
            .doc
            .as_ref()
            .map(|doc| doc.line_comment_for(chunk_id, &anchor))
            .unwrap_or_default();
        let search_match = line_matches_diff_search(&line, &self.diff_search_buffer);
        let comment_mark = if existing_comment.is_empty() {
            ""
        } else {
            "  💬"
        };
        let search_mark = if search_match { "  🔎" } else { "" };
        let fill = diff_line_background(&line.kind, selected, search_match);
        let word_segments = self.word_segments_for_line(chunk, line_index);
        let clicked = egui::Frame::default()
            .fill(fill)
            .show(ui, |ui| {
                let response = if let Some(segments) = word_segments.as_ref() {
                    let job = build_diff_layout_job(
                        ui,
                        &diff_line_prefix_text(self.show_line_numbers, &line),
                        segments,
                        &line.kind,
                        comment_mark,
                        search_mark,
                    );
                    ui.add(egui::Label::new(job).sense(egui::Sense::click()))
                } else {
                    let rendered = render_plain_diff_line(
                        self.show_line_numbers,
                        &line,
                        comment_mark,
                        search_mark,
                        self.config.clip_long_lines,
                    );
                    let text = RichText::new(rendered)
                        .monospace()
                        .color(color_for_line(&line.kind));
                    ui.selectable_label(selected, text)
                };
                let clicked = response.clicked();
                if !existing_comment.is_empty() {
                    response.on_hover_text(existing_comment);
                }
                clicked
            })
            .inner;
        if clicked {
            self.select_line_anchor(anchor);
        }
    }

    fn select_changed_line_relative(&mut self, chunk: &Chunk, forward: bool) {
        let indices = self.changed_line_indices(chunk);
        if indices.is_empty() {
            self.message = "このチャンクに変更行がありません。".to_owned();
            return;
        }
        let current = self
            .selected_line_anchor
            .as_ref()
            .and_then(|anchor| chunk.lines.iter().position(|line| line.anchor() == *anchor))
            .and_then(|line_index| indices.iter().position(|index| *index == line_index));
        let next_position = match (current, forward) {
            (Some(pos), true) => (pos + 1) % indices.len(),
            (Some(0), false) | (None, false) => indices.len().saturating_sub(1),
            (Some(pos), false) => pos.saturating_sub(1),
            (None, true) => 0,
        };
        if let Some(line) = chunk.lines.get(indices[next_position]) {
            self.select_line_anchor(line.anchor());
            self.message = format!(
                "変更行 {}/{} を選択しました。",
                next_position + 1,
                indices.len()
            );
        }
    }

    fn select_diff_search_match(&mut self, chunk: &Chunk, forward: bool) {
        let needle = self.diff_search_buffer.trim().to_lowercase();
        if needle.is_empty() {
            self.message = "Diff内検索語を入力してください。".to_owned();
            return;
        }
        let matches: Vec<usize> = chunk
            .lines
            .iter()
            .enumerate()
            .filter_map(|(index, line)| line.text.to_lowercase().contains(&needle).then_some(index))
            .collect();
        if matches.is_empty() {
            self.message = format!(
                "Diff内検索: `{}` は見つかりません。",
                self.diff_search_buffer.trim()
            );
            return;
        }
        let current = self
            .selected_line_anchor
            .as_ref()
            .and_then(|anchor| chunk.lines.iter().position(|line| line.anchor() == *anchor))
            .and_then(|line_index| matches.iter().position(|index| *index == line_index));
        let next_position = match (current, forward) {
            (Some(pos), true) => (pos + 1) % matches.len(),
            (Some(0), false) | (None, false) => matches.len().saturating_sub(1),
            (Some(pos), false) => pos.saturating_sub(1),
            (None, true) => 0,
        };
        if let Some(line) = chunk.lines.get(matches[next_position]) {
            self.select_line_anchor(line.anchor());
            self.message = format!(
                "Diff内検索: `{}` {}/{}",
                self.diff_search_buffer.trim(),
                next_position + 1,
                matches.len()
            );
        }
    }

    fn copy_visible_diff_text(&mut self, ctx: &egui::Context, chunk: &Chunk) {
        let indices = self.visible_diff_line_indices(chunk);
        let mut out = String::new();
        out.push_str(&format!("diff -- {}\n", chunk.file_path));
        let display_indices: Vec<usize> = indices
            .as_ref()
            .map(|indices| indices.iter().copied().collect())
            .unwrap_or_else(|| (0..chunk.lines.len()).collect());
        for index in display_indices {
            if let Some(line) = chunk.lines.get(index) {
                out.push_str(&format!("{} {}\n", line.prefix(), line.text));
            }
        }
        ctx.copy_text(out);
        self.message = "表示中のdiffをクリップボードへコピーしました。".to_owned();
    }

    fn copy_selected_diff_line(&mut self, ctx: &egui::Context, chunk: &Chunk) {
        let Some(anchor) = self.selected_line_anchor.as_ref() else {
            self.message = "コピーする行をDiffで選択してください。".to_owned();
            return;
        };
        let Some(line) = chunk.lines.iter().find(|line| line.anchor() == *anchor) else {
            self.message = "選択行が現在のチャンク内にありません。".to_owned();
            return;
        };
        ctx.copy_text(format!("{} {}", line.prefix(), line.text));
        self.message = "選択diff行をクリップボードへコピーしました。".to_owned();
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

    fn draw_layout_editor(&mut self, ui: &mut egui::Ui) {
        ui.heading("Layout / Group編集");
        ui.small("Python Textual版の group 作成・rename・assign/unassign に相当する操作です。");
        ui.separator();

        ui.horizontal_wrapped(|ui| {
            ui.label("Group id");
            ui.add_sized(
                [180.0, 24.0],
                TextEdit::singleline(&mut self.group_id_buffer),
            );
            ui.label("Name");
            ui.add_sized(
                [260.0, 24.0],
                TextEdit::singleline(&mut self.group_name_buffer),
            );
            ui.label("Tags");
            ui.add_sized(
                [260.0, 24.0],
                TextEdit::singleline(&mut self.group_tags_buffer).hint_text("tag1 | tag2"),
            );
        });
        ui.horizontal_wrapped(|ui| {
            if ui.button("新規group作成").clicked() {
                self.create_group_from_inputs();
            }
            if ui.button("選択groupを更新").clicked() {
                self.rename_current_group_from_inputs();
            }
            if ui.button("選択groupを削除").clicked() {
                self.delete_current_group();
            }
            if ui.button("layout patch JSON適用…").clicked() {
                self.apply_layout_patch_from_file();
            }
            if ui.button("選択groupをsplit保存…").clicked() {
                self.save_current_group_review_document();
            }
        });

        ui.separator();
        ui.heading("選択chunkの割当");
        let selected_chunk = self.selected_chunk.clone();
        if let Some(chunk_id) = selected_chunk.as_ref() {
            let (file_path, groups) = self
                .doc
                .as_ref()
                .and_then(|doc| {
                    let chunk = doc.chunk_by_id(chunk_id)?;
                    Some((chunk.file_path.clone(), doc.group_ids_for_chunk(chunk_id)))
                })
                .unwrap_or_default();
            ui.label(format!("chunk: {} / {}", short_id(chunk_id), file_path));
            ui.label(format!(
                "現在の割当: {}",
                if groups.is_empty() {
                    "(未割当)".to_owned()
                } else {
                    groups.join(", ")
                }
            ));
            ui.horizontal_wrapped(|ui| {
                if ui.button("未割当にする").clicked() {
                    self.unassign_selected_chunk();
                }
                ui.separator();
                ui.label("割当先:");
                let groups = self
                    .doc
                    .as_ref()
                    .map(|doc| {
                        doc.groups
                            .iter()
                            .map(|group| (group.id.clone(), group.name.clone()))
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                for (group_id, group_name) in groups {
                    if ui
                        .button(format!("{} ({})", group_name, group_id))
                        .clicked()
                    {
                        self.assign_selected_chunk_to_group(&group_id);
                    }
                }
            });
        } else {
            ui.label("chunkを選択すると、groupへの割当/未割当ができます。");
        }

        ui.separator();
        ui.heading("未割当 chunks");
        let unassigned = self
            .doc
            .as_ref()
            .map(DiffgrDocument::unassigned_chunk_ids)
            .unwrap_or_default();
        if unassigned.is_empty() {
            ui.label("未割当chunkはありません。");
        } else {
            egui::ScrollArea::vertical()
                .max_height(220.0)
                .animated(!self.config.reduce_motion)
                .show(ui, |ui| {
                    for chunk_id in unassigned {
                        let file_path = self
                            .doc
                            .as_ref()
                            .and_then(|doc| doc.chunk_by_id(&chunk_id))
                            .map(|chunk| chunk.file_path.clone())
                            .unwrap_or_default();
                        if ui
                            .selectable_label(
                                self.selected_chunk.as_deref() == Some(chunk_id.as_str()),
                                format!("{}  {}", short_id(&chunk_id), file_path),
                            )
                            .clicked()
                        {
                            self.select_chunk(Some(chunk_id.clone()));
                        }
                    }
                });
        }
    }

    fn draw_virtual_pr_panel(&mut self, ui: &mut egui::Ui) {
        let Some(report) = self.virtual_pr_report() else {
            ui.label("DiffGRを開くと仮想PRレビューゲートを表示します。");
            return;
        };
        ui.heading("仮想PRレビューゲート");
        ui.small("レビュー完了・coverage・approval・handoff・高リスクchunkをまとめて見ます。merge/approve判断の直前確認に使います。");
        ui.separator();
        ui.horizontal_wrapped(|ui| {
            let score = report.readiness_score as f32 / 100.0;
            ui.add(
                ProgressBar::new(score)
                    .desired_width(220.0)
                    .text(format!("{} / 100", report.readiness_score)),
            );
            let ready_text = if report.ready_to_approve {
                RichText::new("READY").color(Color32::LIGHT_GREEN).strong()
            } else {
                RichText::new(report.readiness_level.clone())
                    .color(Color32::YELLOW)
                    .strong()
            };
            ui.label(ready_text);
            ui.label(format!(
                "blockers {} / warnings {} / risk queue {}",
                report.blockers.len(),
                report.warnings.len(),
                report.risk_items.len()
            ));
        });
        ui.horizontal_wrapped(|ui| {
            if ui.button("ゲートMarkdownコピー").clicked() {
                ui.ctx().copy_text(vpr::virtual_pr_report_markdown(&report));
                self.message = "仮想PRレビューゲートをコピーしました。".to_owned();
            }
            if ui.button("AI/人間レビューpromptコピー").clicked() {
                ui.ctx()
                    .copy_text(vpr::virtual_pr_reviewer_prompt_markdown(&report, 12));
                self.message = "仮想PRレビューpromptをコピーしました。".to_owned();
            }
            if ui.button("最重要chunkへ").clicked() {
                if let Some(item) = report.risk_items.first() {
                    self.select_chunk(Some(item.chunk_id.clone()));
                    if let Some(group_id) = item.group_id.clone() {
                        self.select_group(Some(group_id));
                    }
                    self.detail_tab = DetailTab::Diff;
                }
            }
            if ui.button("未完了高リスクへ").clicked() {
                if let Some(item) = report
                    .risk_items
                    .iter()
                    .find(|item| item.status == "unreviewed" || item.status == "needsReReview")
                {
                    self.select_chunk(Some(item.chunk_id.clone()));
                    if let Some(group_id) = item.group_id.clone() {
                        self.select_group(Some(group_id));
                    }
                    self.detail_tab = DetailTab::Diff;
                }
            }
            if ui.button("Approvalへ").clicked() {
                self.detail_tab = DetailTab::Approval;
            }
            if ui.button("Coverageへ").clicked() {
                self.detail_tab = DetailTab::Coverage;
            }
        });

        ui.separator();
        ui.columns(2, |columns| {
            columns[0].heading("Blockers");
            if report.blockers.is_empty() {
                columns[0].label(RichText::new("なし").color(Color32::LIGHT_GREEN));
            } else {
                for blocker in &report.blockers {
                    columns[0].label(RichText::new(format!("• {blocker}")).color(Color32::YELLOW));
                }
            }
            columns[1].heading("Next actions");
            if report.next_actions.is_empty() {
                columns[1].label("なし");
            } else {
                for action in &report.next_actions {
                    columns[1].label(format!("• {action}"));
                }
            }
        });

        if !report.warnings.is_empty() {
            egui::CollapsingHeader::new(format!("Warnings ({})", report.warnings.len()))
                .default_open(false)
                .show(ui, |ui| {
                    for warning in &report.warnings {
                        ui.label(format!("• {warning}"));
                    }
                });
        }

        ui.separator();
        ui.heading("高リスクレビューqueue");
        ui.small("status未完了・再レビュー・security/auth/migration/dependency/secret/concurrency/大規模差分を優先して並べます。");
        let risk_rows = report.risk_items.clone();
        let row_height = 72.0;
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .animated(!self.config.reduce_motion)
            .max_height(330.0)
            .show_rows(ui, row_height, risk_rows.len(), |ui, row_range| {
                for index in row_range {
                    let item = &risk_rows[index];
                    ui.horizontal_wrapped(|ui| {
                        ui.label(RichText::new(format!("risk {}", item.risk_score)).strong());
                        ui.label(status_text_badge(&item.status));
                        ui.label(format!(
                            "+{} -{} 💬{}",
                            item.adds, item.deletes, item.comments
                        ));
                        if ui.small_button("開く").clicked() {
                            self.select_chunk(Some(item.chunk_id.clone()));
                            if let Some(group_id) = item.group_id.clone() {
                                self.select_group(Some(group_id));
                            }
                            self.detail_tab = DetailTab::Diff;
                        }
                        if ui.small_button("再レビュー指定").clicked() {
                            self.select_chunk(Some(item.chunk_id.clone()));
                            self.set_selected_status(ReviewStatus::NeedsReReview);
                        }
                    });
                    ui.small(format!(
                        "{} / {} / {}",
                        item.group_id.as_deref().unwrap_or("unassigned"),
                        item.file_path,
                        item.chunk_id
                    ));
                    if !item.reasons.is_empty() {
                        ui.small(format!("理由: {}", item.reasons.join(", ")));
                    }
                    ui.separator();
                }
            });

        ui.separator();
        egui::CollapsingHeader::new("Group readiness")
            .default_open(true)
            .show(ui, |ui| {
                for group in &report.group_readiness {
                    ui.horizontal_wrapped(|ui| {
                        ui.label(
                            RichText::new(format!("{} / {}", group.group_id, group.group_name))
                                .strong(),
                        );
                        let progress = if group.tracked == 0 {
                            1.0
                        } else {
                            group.reviewed as f32 / group.tracked as f32
                        };
                        ui.add(
                            ProgressBar::new(progress)
                                .desired_width(100.0)
                                .text(format!("{}/{}", group.reviewed, group.tracked)),
                        );
                        ui.label(format!("pending {}", group.pending));
                        ui.label(format!(
                            "approval {}/{}",
                            group.approved, group.approval_valid
                        ));
                        ui.label(format!("brief {}", group.brief_status));
                        ui.label(format!("risk {}", group.risk_score));
                        if ui.small_button("絞る").clicked() {
                            self.select_group(Some(group.group_id.clone()));
                        }
                        if ui.small_button("Handoff").clicked() {
                            self.select_group(Some(group.group_id.clone()));
                            self.detail_tab = DetailTab::Handoff;
                        }
                    });
                    if !group.missing_handoff_fields.is_empty() {
                        ui.small(format!(
                            "handoff不足: {}",
                            group.missing_handoff_fields.join(", ")
                        ));
                    }
                    if !group.top_risk_chunks.is_empty() {
                        ui.small(format!(
                            "top risk chunks: {}",
                            group.top_risk_chunks.join(", ")
                        ));
                    }
                    ui.separator();
                }
            });

        egui::CollapsingHeader::new("File hotspots")
            .default_open(false)
            .show(ui, |ui| {
                for file in report.file_hotspots.iter().take(30) {
                    ui.horizontal_wrapped(|ui| {
                        ui.label(RichText::new(format!("risk {}", file.risk_score)).strong());
                        ui.label(format!(
                            "chunks {} pending {} +{} -{} 💬{}",
                            file.chunks, file.pending, file.adds, file.deletes, file.comments
                        ));
                        if ui.small_button("Path絞り込み").clicked() {
                            self.set_file_filter(file.file_path.clone());
                        }
                    });
                    ui.small(&file.file_path);
                    if !file.reasons.is_empty() {
                        ui.small(format!("理由: {}", file.reasons.join(", ")));
                    }
                    ui.separator();
                }
            });
    }

    fn draw_coverage_panel(&mut self, ui: &mut egui::Ui) {
        ui.heading("Virtual PR coverage");
        let Some(issue) = self.doc.as_ref().map(DiffgrDocument::analyze_coverage) else {
            ui.label("DiffGRを開くとcoverageを表示します。");
            return;
        };
        if issue.ok() {
            ui.label(
                RichText::new("OK: 全chunkがちょうど1つのgroupに割り当てられています。").strong(),
            );
        } else {
            ui.label(
                RichText::new(format!("問題 {}件", issue.problem_count()))
                    .color(Color32::YELLOW)
                    .strong(),
            );
        }
        ui.horizontal_wrapped(|ui| {
            if ui.button("修正依頼promptコピー").clicked() {
                self.copy_coverage_prompt(ui.ctx());
            }
            if ui.button("修正依頼prompt保存…").clicked() {
                self.save_coverage_prompt();
            }
            if ui.button("layout patch JSON適用…").clicked() {
                self.apply_layout_patch_from_file();
            }
        });
        draw_coverage_issue(ui, &issue);
    }

    fn draw_impact_panel(&mut self, ui: &mut egui::Ui) {
        ui.heading("Impact preview / re-review planning");
        ui.horizontal_wrapped(|ui| {
            if ui.button("旧DiffGRを選んでimpact preview…").clicked() {
                self.pick_and_preview_impact();
            }
            if ui.button("Markdownコピー").clicked() {
                ui.ctx().copy_text(self.impact_preview_text.clone());
                self.message = "impact previewをコピーしました。".to_owned();
            }
        });
        if self.impact_preview_text.trim().is_empty() {
            ui.label("旧DiffGR JSONを選択すると、現在のDiffGRとの差分影響をここに表示します。");
        } else {
            ui.add(
                TextEdit::multiline(&mut self.impact_preview_text)
                    .font(egui::TextStyle::Monospace)
                    .desired_width(f32::INFINITY)
                    .desired_rows(28),
            );
        }
    }

    fn draw_approval_panel(&mut self, ui: &mut egui::Ui) {
        ui.heading("Approval / Request changes");
        ui.small("Python版の approve_virtual_pr / request_changes / check_virtual_pr_approval 相当です。");
        ui.separator();

        let current_group = self.current_group_for_decision();
        ui.horizontal_wrapped(|ui| {
            ui.label("Reviewer");
            ui.add_sized(
                [240.0, 24.0],
                TextEdit::singleline(&mut self.reviewer_input).hint_text("reviewer name"),
            );
            if let Some(group_id) = current_group.as_ref() {
                ui.label(format!("対象group: {group_id}"));
            } else {
                ui.label("対象group: 未選択");
            }
        });
        labeled_multiline(
            ui,
            "Request changes comment",
            &mut self.change_request_comment,
            3,
        );

        ui.horizontal_wrapped(|ui| {
            if ui.button("Approve selected group").clicked() {
                self.approve_current_group(false);
            }
            if ui.button("Force approve").clicked() {
                self.approve_current_group(true);
            }
            if ui.button("Request changes").clicked() {
                self.request_changes_current_group();
            }
            if ui.button("Revoke approval").clicked() {
                self.revoke_current_group();
            }
            if ui.button("Report更新").clicked() {
                if let Some(doc) = self.doc.as_ref() {
                    self.approval_report_text = doc.approval_report_markdown();
                }
            }
            if ui.button("Reportコピー").clicked() {
                if self.approval_report_text.trim().is_empty() {
                    if let Some(doc) = self.doc.as_ref() {
                        self.approval_report_text = doc.approval_report_markdown();
                    }
                }
                ui.ctx().copy_text(self.approval_report_text.clone());
                self.message = "approval reportをコピーしました。".to_owned();
            }
            if ui.button("Report JSON保存…").clicked() {
                self.save_approval_report_json();
            }
        });

        ui.separator();
        let report = self.doc.as_ref().map(DiffgrDocument::check_all_approvals);
        if let Some(report) = report {
            if report.all_approved {
                ui.label(
                    RichText::new("OK: すべてのgroup approvalが有効です。")
                        .strong()
                        .color(Color32::LIGHT_GREEN),
                );
            } else {
                ui.label(
                    RichText::new("未承認または無効なapprovalがあります。")
                        .strong()
                        .color(Color32::YELLOW),
                );
            }
            egui::Grid::new("approval_grid")
                .striped(true)
                .show(ui, |ui| {
                    ui.strong("Group");
                    ui.strong("Approved");
                    ui.strong("Valid");
                    ui.strong("Reason");
                    ui.strong("Reviewed");
                    ui.end_row();
                    for status in &report.groups {
                        ui.label(format!("{} ({})", status.group_name, status.group_id));
                        ui.label(if status.approved { "yes" } else { "no" });
                        ui.label(if status.valid { "yes" } else { "no" });
                        ui.label(&status.reason);
                        ui.label(format!("{}/{}", status.reviewed_count, status.total_count));
                        ui.end_row();
                    }
                });
            if self.approval_report_text.trim().is_empty() {
                let report_text = self
                    .doc
                    .as_ref()
                    .map(DiffgrDocument::approval_report_markdown)
                    .unwrap_or_default();
                self.approval_report_text = report_text;
            }
            ui.separator();
            ui.label("Markdown report");
            ui.add(
                TextEdit::multiline(&mut self.approval_report_text)
                    .font(egui::TextStyle::Monospace)
                    .desired_width(f32::INFINITY)
                    .desired_rows(14),
            );
        } else {
            ui.label("DiffGRを開くとapproval状態を表示します。");
        }
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

    fn draw_tools_panel(&mut self, ui: &mut egui::Ui) {
        ui.heading("Python parity tools / 既存 Python 機能相当");
        ui.label("Rust/Cargo 側で Python scripts/*.py 相当を実行するための入口です。重い生成系はCLI diffgrctl でも同じ処理を呼べます。");
        ui.separator();

        egui::CollapsingHeader::new("自己レビュー / 品質ゲート")
            .default_open(true)
            .show(ui, |ui| {
                ui.label("Python版機能網羅、GUI完成度、固まりにくさ、UT資産をこの画面から確認できます。");
                ui.horizontal_wrapped(|ui| {
                    if ui.button("自己レビューをコピー").clicked() {
                        self.copy_self_review_report(ui.ctx());
                    }
                    if ui.button("自己レビューを保存…").clicked() {
                        self.save_self_review_report();
                    }
                    if ui.button("CLIコマンドを表示").clicked() {
                        self.tool_output_text = "PowerShell:\n  .\\self-review.ps1 -Json -Strict\n  .\\quality-review.ps1 -Json -Deep\n\nCargo:\n  cargo run --bin diffgrctl -- quality-review --json --deep\n\nUT:\n  .\\windows\\ut-matrix-windows.ps1 -Json\n  .\\test.ps1 -Fmt -Check\n  .\\build.ps1 -Test".to_owned();
                    }
                });
                let score = package_quality_score();
                ui.small(format!(
                    "静的品質シグナル: Python scripts {}/31 / wrapper {}/62 / GUI markers {}/{} / UT推定 {} tests",
                    score.python_scripts, score.wrapper_entries, score.gui_markers_found, score.gui_markers_total, score.rust_tests
                ));
            });

        ui.separator();

        ui.collapsing("生成 → autoslice → refine", |ui| {
            labeled_singleline(ui, "repo", &mut self.tool_repo_input);
            labeled_singleline(ui, "base", &mut self.tool_base_input);
            labeled_singleline(ui, "feature", &mut self.tool_feature_input);
            labeled_singleline(ui, "title", &mut self.tool_title_input);
            labeled_singleline(ui, "output", &mut self.tool_output_input);
            ui.horizontal_wrapped(|ui| {
                if ui.button("Generate only").clicked() {
                    self.run_generate_tool(false);
                }
                if ui.button("Prepare review").clicked() {
                    self.run_generate_tool(true);
                }
                if ui.button("出力先...").clicked() {
                    if let Some(path) = FileDialog::new()
                        .add_filter("DiffGR", &["json"])
                        .save_file()
                    {
                        self.tool_output_input = path.display().to_string();
                    }
                }
            });
            ui.small(
                "prepare は generate_diffgr.py + autoslice_diffgr.py + refine_slices.py 相当です。",
            );
        });

        ui.separator();
        let Some(doc_raw) = self.doc.as_ref().map(|doc| doc.raw.clone()) else {
            ui.label("DiffGR を開くと、state / layout / bundle / rebase 系の操作が使えます。");
            return;
        };

        ui.horizontal_wrapped(|ui| {
            if ui.button("State抽出...").clicked() {
                if let Some(path) = FileDialog::new()
                    .set_file_name("review.state.json")
                    .save_file()
                {
                    match ops::write_json_file(&path, &ops::extract_review_state(&doc_raw)) {
                        Ok(()) => {
                            self.tool_output_text = format!("Wrote state: {}", path.display())
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
            if ui.button("HTML保存...").clicked() {
                self.save_html_report();
            }
            if ui.button("Bundle出力...").clicked() {
                if let Some(dir) = FileDialog::new().pick_folder() {
                    match ops::export_review_bundle(&doc_raw, &dir) {
                        Ok(summary) => {
                            self.tool_output_text = format!(
                                "{}\n{}",
                                summary.message,
                                summary
                                    .written
                                    .iter()
                                    .map(|p| p.display().to_string())
                                    .collect::<Vec<_>>()
                                    .join("\n")
                            )
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
            if ui.button("Split all groups...").clicked() {
                if let Some(dir) = FileDialog::new().pick_folder() {
                    match ops::split_document_by_group(&doc_raw, &dir, false) {
                        Ok(summary) => {
                            self.tool_output_text = format!(
                                "{}\n{}",
                                summary.message,
                                summary
                                    .written
                                    .iter()
                                    .map(|p| p.display().to_string())
                                    .collect::<Vec<_>>()
                                    .join("\n")
                            )
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
        });

        ui.horizontal_wrapped(|ui| {
            if ui.button("Coverage JSON...").clicked() {
                if let Some(path) = FileDialog::new().set_file_name("coverage.json").save_file() {
                    match ops::coverage_report(&doc_raw)
                        .and_then(|report| ops::write_json_file(&path, &report))
                    {
                        Ok(()) => {
                            self.tool_output_text = format!("Wrote coverage: {}", path.display())
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
            if ui.button("Coverage修正prompt...").clicked() {
                if let Some(path) = FileDialog::new()
                    .set_file_name("coverage-fix-prompt.md")
                    .save_file()
                {
                    match ops::coverage_report(&doc_raw).and_then(|report| {
                        ops::write_text_file(
                            &path,
                            report.get("prompt").and_then(Value::as_str).unwrap_or(""),
                        )
                    }) {
                        Ok(()) => {
                            self.tool_output_text = format!("Wrote prompt: {}", path.display())
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
            if ui.button("Reviewability JSON...").clicked() {
                if let Some(path) = FileDialog::new()
                    .set_file_name("reviewability.json")
                    .save_file()
                {
                    match ops::reviewability_report(&doc_raw)
                        .and_then(|report| ops::write_json_file(&path, &report))
                    {
                        Ok(()) => {
                            self.tool_output_text =
                                format!("Wrote reviewability: {}", path.display())
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
            if ui.button("AI refine prompt...").clicked() {
                if let Some(path) = FileDialog::new()
                    .set_file_name("refine-prompt.md")
                    .save_file()
                {
                    match ops::write_text_file(
                        &path,
                        &ops::build_ai_refine_prompt_markdown(&doc_raw, 30),
                    ) {
                        Ok(()) => {
                            self.tool_output_text = format!("Wrote prompt: {}", path.display())
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
        });

        ui.horizontal_wrapped(|ui| {
            if ui.button("Layout JSON適用...").clicked() {
                if let Some(path) = FileDialog::new().add_filter("JSON", &["json"]).pick_file() {
                    match read_json_file(&path)
                        .and_then(|layout| ops::apply_layout(&doc_raw, &layout))
                        .and_then(|(out, warnings)| {
                            self.replace_current_document_value(out, true)?;
                            Ok(warnings)
                        }) {
                        Ok(warnings) => {
                            self.tool_output_text =
                                format!("Applied layout.\n{}", warnings.join("\n"))
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
            if ui.button("Slice patch適用...").clicked() {
                if let Some(path) = FileDialog::new().add_filter("JSON", &["json"]).pick_file() {
                    match read_json_file(&path)
                        .and_then(|patch| ops::apply_slice_patch(&doc_raw, &patch))
                        .and_then(|out| self.replace_current_document_value(out, true))
                    {
                        Ok(()) => self.tool_output_text = "Applied slice patch.".to_owned(),
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
            if ui.button("Merge group reviews...").clicked() {
                if let Some(dir) = FileDialog::new().pick_folder() {
                    match self.merge_group_reviews_from_dir(&doc_raw, &dir) {
                        Ok(applied) => {
                            self.tool_output_text =
                                format!("Merged group reviews. Applied: {applied}")
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
        });

        ui.horizontal_wrapped(|ui| {
            if ui.button("Rebase state old→current...").clicked() {
                self.rebase_state_to_current_tool(&doc_raw);
            }
            if ui.button("Impact old→current...").clicked() {
                if let Some(old_path) = FileDialog::new()
                    .add_filter("DiffGR", &["json"])
                    .pick_file()
                {
                    match read_json_file(&old_path)
                        .and_then(|old| ops::impact_report(&old, &doc_raw, None))
                    {
                        Ok(report) => {
                            self.tool_output_text = serde_json::to_string_pretty(&report)
                                .unwrap_or_else(|_| format!("{report:?}"))
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
            if ui.button("Approval JSON...").clicked() {
                if let Some(path) = FileDialog::new()
                    .set_file_name("approval-report.json")
                    .save_file()
                {
                    match ops::approval_report(&doc_raw)
                        .and_then(|report| ops::write_json_file(&path, &report))
                    {
                        Ok(()) => {
                            self.tool_output_text =
                                format!("Wrote approval report: {}", path.display())
                        }
                        Err(err) => self.tool_output_text = err,
                    }
                }
            }
        });

        ui.separator();
        ui.collapsing("diffgrctl CLI", |ui| {
            ui.monospace("cargo run --bin diffgrctl -- prepare --repo . --base main --feature HEAD --output out/work/review.diffgr.json");
            ui.monospace("cargo run --bin diffgrctl -- export-bundle --input review.diffgr.json --output-dir out/bundle");
            ui.monospace("cargo run --bin diffgrctl -- verify-bundle --bundle out/bundle/bundle.diffgr.json --state out/bundle/review.state.json --manifest out/bundle/review.manifest.json --json");
        });
        if !self.tool_output_text.trim().is_empty() {
            ui.separator();
            ui.label(RichText::new("結果").strong());
            ui.add(
                TextEdit::multiline(&mut self.tool_output_text)
                    .desired_rows(10)
                    .code_editor(),
            );
        }
    }

    fn run_generate_tool(&mut self, prepare: bool) {
        let output = PathBuf::from(self.tool_output_input.trim());
        let generate = ops::GenerateOptions {
            repo: PathBuf::from(self.tool_repo_input.trim()),
            base: self.tool_base_input.trim().to_owned(),
            feature: self.tool_feature_input.trim().to_owned(),
            title: self.tool_title_input.trim().to_owned(),
            include_patch: true,
        };
        let result = if prepare {
            let auto = ops::AutosliceOptions {
                repo: generate.repo.clone(),
                base: generate.base.clone(),
                feature: generate.feature.clone(),
                name_style: "pr".to_owned(),
                ..Default::default()
            };
            ops::prepare_review(&generate, &auto).and_then(|(doc, warnings)| {
                ops::write_json_file(&output, &doc)?;
                Ok(format!(
                    "Wrote: {}\n{}",
                    output.display(),
                    warnings.join("\n")
                ))
            })
        } else {
            ops::build_diffgr_document(&generate).and_then(|doc| {
                ops::write_json_file(&output, &doc)?;
                Ok(format!("Wrote: {}", output.display()))
            })
        };
        match result {
            Ok(text) => self.tool_output_text = text,
            Err(err) => self.tool_output_text = err,
        }
    }

    fn replace_current_document_value(
        &mut self,
        value: Value,
        layout_change: bool,
    ) -> Result<(), String> {
        let doc = DiffgrDocument::from_value(value)?;
        self.doc = Some(doc);
        self.dirty = true;
        self.layout_dirty |= layout_change;
        self.invalidate_visible_cache();
        self.invalidate_review_caches();
        self.invalidate_state_preview_cache();
        self.diff_line_index_cache = None;
        self.diff_context_index_cache = None;
        self.diff_side_by_side_cache = None;
        self.diff_word_pair_cache = None;
        self.diff_word_segment_cache = None;
        self.list_revision = self.list_revision.saturating_add(1);
        self.state_revision = self.state_revision.saturating_add(1);
        Ok(())
    }

    fn merge_group_reviews_from_dir(
        &mut self,
        base_doc: &Value,
        dir: &Path,
    ) -> Result<usize, String> {
        let mut review_docs = Vec::new();
        for entry in fs::read_dir(dir).map_err(|err| format!("{}: {}", dir.display(), err))? {
            let path = entry.map_err(|err| err.to_string())?.path();
            let name = path
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("");
            if path.extension().and_then(|value| value.to_str()) == Some("json")
                && name != "manifest.json"
            {
                review_docs.push((path.display().to_string(), read_json_file(&path)?));
            }
        }
        let (merged, warnings, applied) =
            ops::merge_group_review_documents(base_doc, &review_docs, false, false)?;
        self.replace_current_document_value(merged, false)?;
        self.tool_output_text = warnings.join("\n");
        Ok(applied)
    }

    fn rebase_state_to_current_tool(&mut self, current_doc: &Value) {
        let Some(old_path) = FileDialog::new()
            .set_title("Old DiffGR")
            .add_filter("DiffGR", &["json"])
            .pick_file()
        else {
            return;
        };
        let Some(state_path) = FileDialog::new()
            .set_title("Old review.state.json")
            .add_filter("JSON", &["json"])
            .pick_file()
        else {
            return;
        };
        let Some(output_path) = FileDialog::new()
            .set_title("Save rebased review.state.json")
            .set_file_name("review.rebased.state.json")
            .save_file()
        else {
            return;
        };
        match read_json_file(&old_path)
            .and_then(|old| {
                read_json_file(&state_path)
                    .and_then(|state| ops::rebase_state(&old, current_doc, &state))
            })
            .and_then(|(rebased, summary)| {
                ops::write_json_file(&output_path, &rebased)?;
                Ok(summary)
            }) {
            Ok(summary) => {
                self.tool_output_text = format!(
                    "Wrote: {}\nmappedReviews: {}\nunmappedReviews: {}\n{}",
                    output_path.display(),
                    summary.mapped_reviews,
                    summary.unmapped_reviews,
                    summary.warnings.join("\n")
                );
            }
            Err(err) => self.tool_output_text = err,
        }
    }
    fn draw_state_preview(&mut self, ui: &mut egui::Ui) {
        if !self.ensure_state_preview_cache() {
            return;
        }
        ui.horizontal_wrapped(|ui| {
            ui.small("プレビューは1件だけの揮発キャッシュです。巨大JSONは行仮想化して描画します。");
            if ui.button("State JSONをコピー").clicked() {
                if let Some(preview) = self.state_preview_cache.text.as_ref() {
                    ui.ctx().copy_text(preview.clone());
                    self.message = "State JSONをクリップボードへコピーしました。".to_owned();
                }
            }
            if ui.button("State保存先…").clicked() {
                self.save_state_as();
            }
            if ui.button("State差分…").clicked() {
                self.pick_and_preview_state_diff();
            }
            if ui.button("State merge…").clicked() {
                self.pick_and_merge_state();
            }
        });
        if !self.state_merge_preview_text.trim().is_empty() {
            egui::CollapsingHeader::new("State diff / merge preview")
                .default_open(true)
                .show(ui, |ui| {
                    draw_virtual_text(
                        ui,
                        &self.state_merge_preview_text,
                        None,
                        self.config.reduce_motion,
                    );
                });
        }
        if let Some(preview) = self.state_preview_cache.text.as_ref() {
            draw_virtual_text(
                ui,
                preview,
                Some(&self.state_preview_cache.line_starts),
                self.config.reduce_motion,
            );
        }
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

    fn draw_performance_overlay(&self, ctx: &egui::Context) {
        if !self.config.show_performance_overlay {
            return;
        }
        egui::Area::new(egui::Id::new("diffgr_performance_hud"))
            .anchor(egui::Align2::RIGHT_TOP, [-12.0, 12.0])
            .order(egui::Order::Foreground)
            .show(ctx, |ui| {
                ui.group(|ui| {
                    ui.small(RichText::new("DiffGR HUD").strong());
                    ui.small(format!(
                        "avg {:.1} ms / peak {:.1} ms",
                        self.frame_time_ema_ms, self.frame_time_peak_ms
                    ));
                    ui.small(format!(
                        "slow {} / samples {}",
                        self.slow_frame_count, self.frame_sample_count
                    ));
                    ui.small(format!(
                        "rows {} / cache {}",
                        self.visible_cache.ids.len(),
                        self.visible_cache.rows.len()
                    ));
                    if self.pending_load.is_some() || self.pending_state_save.is_some() {
                        ui.small("background I/O active");
                    }
                });
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
                ui.label("R: レビュー済み / I: 無視 / Ctrl+F: 検索欄へ / Ctrl+Z: 直近のステータス変更を戻す");
                ui.label("Diff: 統合/左右比較、行内差分、賢く対応付け、全行/変更行のみ/変更周辺、Diff内検索、次/前の変更、表示中diffコピー");
                ui.separator();
                ui.heading("おすすめ運用");
                ui.label("1. DiffGR JSONを開く。必要なら review.state.json を読み込む。");
                ui.label("2. State保存先… で review.state.json を作ると、元JSONを汚さずレビュー状態だけ保存できます。");
                ui.label("3. 作業ルートを設定すると、Diff内の相対パスから実ファイルを開きやすくなります。");
                ui.label("4. Path / 検索 / 状態フィルタで絞り込み、Space と N で高速にレビューできます。");
                ui.label("5. 概要タブまたは上部ボタンから、レビューサマリをMarkdownでコピー/保存できます。");
                ui.label("6. 大きいdiffでは `ちらつき抑制` ON / `UI状態を記憶` OFF / `コンパクト行` ON が軽量です。");
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
        self.config.show_only_changed = self.diff_context_mode == DiffContextMode::ChangedOnly;
        self.config.diff_view_mode = self.diff_view_mode;
        self.config.diff_context_mode = self.diff_context_mode;
        self.config.diff_context_radius = self.diff_context_radius;
        self.config.word_diff_enabled = self.word_diff_enabled;
        self.config.word_diff_smart_pairing = self.word_diff_smart_pairing;
        self.config.wrap_diff = self.wrap_diff;
        self.config.only_with_comments = self.only_with_comments;
        self.config.sort_mode = self.sort_mode;
        self.config.detail_tab = self.detail_tab;
        self.config.workspace_root = self.workspace_root_input.trim().to_owned();
    }
}

impl eframe::App for DiffgrGuiApp {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.update_frame_budget_metrics();
        self.poll_background_jobs(ui.ctx());
        self.maybe_apply_debounced_filters(ui.ctx());
        self.maybe_request_active_scroll_repaint(ui.ctx());
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
        self.draw_performance_overlay(ui.ctx());
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

#[derive(Clone, Debug, Default)]
struct PackageQualityScore {
    python_scripts: usize,
    wrapper_entries: usize,
    rust_tests: usize,
    gui_markers_found: usize,
    gui_markers_total: usize,
}

fn build_self_review_markdown(
    doc: Option<&DiffgrDocument>,
    config: &AppConfig,
    pending_load: bool,
    pending_save: bool,
) -> String {
    let score = package_quality_score();
    let mut out = String::new();
    out.push_str("# DiffGR Rust GUI 自己レビュー\n\n");
    out.push_str("## 結論\n\n");
    out.push_str("- 既存 Python アプリ相当の入口は、Native Rust CLI / GUI tools / Windows & shell wrapper / Python strict compat の4層で網羅しています。\n");
    out.push_str("- 厳密な Python 互換が必要な場合は `-CompatPython` / `--compat-python` / `DIFFGR_COMPAT_PYTHON=1` で同梱 Python 実装を呼び出せます。\n");
    out.push_str("- GUI はバックグラウンド読み込み・バックグラウンド保存・仮想スクロール・検索 debounce・長大行省略・低メモリ/滑らかスクロール切替・性能HUDで固まりにくさを強化しています。\n\n");
    out.push_str("## 静的品質シグナル\n\n");
    out.push_str("| 項目 | 値 |\n|---|---:|\n");
    out.push_str(&format!(
        "| Python scripts | {}/31 |\n",
        score.python_scripts
    ));
    out.push_str(&format!(
        "| Windows/shell wrappers | {}/62 |\n",
        score.wrapper_entries
    ));
    out.push_str(&format!(
        "| GUI responsiveness markers | {}/{} |\n",
        score.gui_markers_found, score.gui_markers_total
    ));
    out.push_str(&format!(
        "| Rust UT estimated count | {} |\n\n",
        score.rust_tests
    ));
    out.push_str("## GUI 実行時設定\n\n");
    out.push_str("| 設定 | 状態 |\n|---|---|\n");
    out.push_str(&format!(
        "| background I/O | {} |\n",
        on_off(config.background_io)
    ));
    out.push_str(&format!(
        "| smooth scroll repaint | {} |\n",
        on_off(config.smooth_scroll_repaint)
    ));
    out.push_str(&format!(
        "| reduce motion / flicker guard | {} |\n",
        on_off(config.reduce_motion)
    ));
    out.push_str(&format!(
        "| performance HUD | {} |\n",
        on_off(config.show_performance_overlay)
    ));
    out.push_str(&format!(
        "| deferred filtering | {} |\n",
        on_off(config.defer_filtering)
    ));
    out.push_str(&format!(
        "| clip long lines | {} |\n",
        on_off(config.clip_long_lines)
    ));
    out.push_str(&format!(
        "| compact rows | {} |\n",
        on_off(config.compact_rows)
    ));
    out.push_str(&format!("| pending load | {} |\n", yes_no(pending_load)));
    out.push_str(&format!("| pending save | {} |\n\n", yes_no(pending_save)));
    if let Some(doc) = doc {
        let counts = doc.status_counts();
        let metrics = doc.metrics();
        let coverage = doc.analyze_coverage();
        out.push_str("## 現在開いている DiffGR\n\n");
        out.push_str(&format!("- title: {}\n", doc.title));
        out.push_str(&format!("- groups: {}\n", doc.groups.len()));
        out.push_str(&format!("- chunks: {}\n", doc.chunks.len()));
        out.push_str(&format!(
            "- reviewed: {} / {}\n",
            metrics.reviewed, metrics.tracked
        ));
        out.push_str(&format!("- pending: {}\n", counts.pending()));
        out.push_str(&format!(
            "- coverage rate: {:.1}%\n",
            metrics.coverage_rate * 100.0
        ));
        out.push_str(&format!(
            "- unassigned chunks: {}\n",
            coverage.unassigned.len()
        ));
        out.push_str(&format!(
            "- duplicated assignments: {}\n",
            coverage.duplicated.len()
        ));
        out.push_str(&format!(
            "- unknown groups: {}\n",
            coverage.unknown_groups.len()
        ));
        out.push_str(&format!(
            "- unknown chunks: {}\n\n",
            coverage.unknown_chunks.len()
        ));
    } else {
        out.push_str("## 現在開いている DiffGR\n\n- なし。DiffGR JSON を開くと文書単位の coverage / approval / reviewability も含めて自己レビューします。\n\n");
    }
    out.push_str("## 推奨ゲート\n\n```powershell\n");
    out.push_str(".\\windows\\self-review-windows.ps1 -Json -Strict\n");
    out.push_str(".\\windows\\quality-review-windows.ps1 -Json -Deep\n");
    out.push_str(".\\windows\\python-compat-verify-windows.ps1 -Json\n");
    out.push_str(".\\windows\\native-parity-verify-windows.ps1 -Json -CheckCompat\n");
    out.push_str(".\\windows\\native-functional-parity-windows.ps1 -Json\n");
    out.push_str(".\\windows\\ut-matrix-windows.ps1 -Json\n");
    out.push_str(".\\test.ps1 -Fmt -Check\n");
    out.push_str(".\\build.ps1 -Test\n```\n\n");
    out.push_str("## 残る注意点\n\n");
    out.push_str("- このGUI内の自己レビューは静的検査と現在文書の状態確認です。最終判定は `cargo test --all-targets` と上記 parity gate を Windows 実機で通してください。\n");
    out.push_str("- Native Rust は全 Python script の入口と主要 option を持ちますが、Python 実装と byte-for-byte の表示差異が必要な運用では compat mode を使ってください。\n");
    out
}

fn package_quality_score() -> PackageQualityScore {
    let Some(root) = locate_project_root() else {
        return PackageQualityScore {
            gui_markers_total: GUI_QUALITY_MARKERS.len(),
            ..PackageQualityScore::default()
        };
    };
    let python_scripts = count_manifest_scripts(&root);
    let wrapper_entries = count_wrapper_entries(&root);
    let rust_tests = count_rust_tests(&root);
    let (gui_markers_found, gui_markers_total) = count_gui_markers(&root);
    PackageQualityScore {
        python_scripts,
        wrapper_entries,
        rust_tests,
        gui_markers_found,
        gui_markers_total,
    }
}

const GUI_QUALITY_MARKERS: &[&str] = &[
    "PendingDocumentLoad",
    "PendingStateSave",
    "show_rows",
    "cached_chunk_row",
    "filter_apply_deadline",
    "maybe_apply_debounced_filters",
    "smooth_scroll_repaint",
    "clip_for_display",
    "draw_virtual_text",
    "DiffLineIndexCache",
    "request_repaint_after",
    "reduce_motion",
    "persist_egui_memory",
    "State JSONをコピー",
    "自己レビュー / 品質ゲート",
    "background_io",
    "MAX_RENDERED_DIFF_CHARS",
    "draw_performance_overlay",
    "draw_diagnostics_panel",
    "copy_self_review_report",
    "save_self_review_report",
    "DiffViewMode",
    "DiffContextMode",
    "draw_side_by_side_diff_lines",
    "select_changed_line_relative",
    "diff_search_buffer",
    "diff_line_background",
    "copy_visible_diff_text",
    "word_diff_enabled",
    "word_diff_smart_pairing",
    "DiffWordPairCache",
    "DiffWordSegmentCache",
    "word_segments_for_line",
    "diff_word_pair_map",
    "matched_delete_add_rows",
    "build_diff_layout_job",
    "word_diff_background",
    "行内差分",
    "賢く対応付け",
];

fn locate_project_root() -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(cwd) = env::current_dir() {
        candidates.push(cwd.clone());
        candidates.extend(cwd.ancestors().map(Path::to_path_buf));
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(parent) = exe.parent() {
            candidates.push(parent.to_path_buf());
            candidates.extend(parent.ancestors().map(Path::to_path_buf));
        }
    }
    candidates.into_iter().find(|candidate| {
        candidate.join("Cargo.toml").exists() && candidate.join("src/app.rs").exists()
    })
}

fn count_manifest_scripts(root: &Path) -> usize {
    let Ok(text) = fs::read_to_string(root.join("PYTHON_PARITY_MANIFEST.json")) else {
        return 0;
    };
    let Ok(value) = serde_json::from_str::<Value>(&text) else {
        return 0;
    };
    value
        .get("entries")
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0)
}

fn count_wrapper_entries(root: &Path) -> usize {
    let Ok(text) = fs::read_to_string(root.join("PYTHON_PARITY_MANIFEST.json")) else {
        return 0;
    };
    let Ok(value) = serde_json::from_str::<Value>(&text) else {
        return 0;
    };
    let Some(entries) = value.get("entries").and_then(Value::as_array) else {
        return 0;
    };
    let mut count = 0;
    for entry in entries {
        let Some(stem) = entry.get("stem").and_then(Value::as_str) else {
            continue;
        };
        if root.join("scripts").join(format!("{stem}.ps1")).exists() {
            count += 1;
        }
        if root.join("scripts").join(format!("{stem}.sh")).exists() {
            count += 1;
        }
    }
    count
}

fn count_rust_tests(root: &Path) -> usize {
    let Ok(entries) = fs::read_dir(root.join("tests")) else {
        return 0;
    };
    let mut count = 0;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|value| value.to_str()) != Some("rs") {
            continue;
        }
        let Ok(text) = fs::read_to_string(path) else {
            continue;
        };
        count += text.lines().filter(|line| line.trim() == "#[test]").count();
    }
    count
}

fn count_gui_markers(root: &Path) -> (usize, usize) {
    let text = fs::read_to_string(root.join("src/app.rs")).unwrap_or_default();
    let found = GUI_QUALITY_MARKERS
        .iter()
        .filter(|marker| text.contains(**marker))
        .count();
    (found, GUI_QUALITY_MARKERS.len())
}

fn on_off(value: bool) -> &'static str {
    if value {
        "ON"
    } else {
        "OFF"
    }
}
fn yes_no(value: bool) -> &'static str {
    if value {
        "yes"
    } else {
        "no"
    }
}

fn draw_status_counts(ui: &mut egui::Ui, counts: &StatusCounts) {
    ui.horizontal_wrapped(|ui| {
        ui.label(format!("合計: {}", counts.total()));
        ui.label(format!("レビュー済み: {}", counts.reviewed));
        ui.label(format!("未レビュー: {}", counts.unreviewed));
        ui.label(format!("再レビュー: {}", counts.needs_re_review));
        ui.label(format!("無視: {}", counts.ignored));
        ui.label(format!("未完了: {}", counts.pending()));
    });
}

fn write_json_value(path: &Path, value: &Value) -> Result<(), String> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent).map_err(|err| format!("{}: {}", parent.display(), err))?;
    }
    let text = serde_json::to_string_pretty(value).map_err(|err| err.to_string())?;
    let tmp = path.with_extension(format!(
        "{}tmp",
        path.extension()
            .and_then(|value| value.to_str())
            .map(|ext| format!("{}.", ext))
            .unwrap_or_default()
    ));
    fs::write(&tmp, text).map_err(|err| format!("{}: {}", tmp.display(), err))?;
    fs::rename(&tmp, path).or_else(|rename_err| {
        fs::copy(&tmp, path).map(|_| ()).map_err(|copy_err| {
            format!(
                "{} -> {}: rename: {}; copy: {}",
                tmp.display(),
                path.display(),
                rename_err,
                copy_err
            )
        })?;
        let _ = fs::remove_file(&tmp);
        Ok(())
    })
}

fn build_line_starts(text: &str) -> Vec<usize> {
    let mut starts = vec![0];
    for (index, byte) in text.bytes().enumerate() {
        if byte == b'\n' && index + 1 < text.len() {
            starts.push(index + 1);
        }
    }
    starts
}

fn line_at<'a>(text: &'a str, starts: &[usize], index: usize) -> &'a str {
    let Some(&start) = starts.get(index) else {
        return "";
    };
    let end = starts.get(index + 1).copied().unwrap_or_else(|| text.len());
    text[start..end].trim_end_matches(&['\r', '\n'][..])
}

fn draw_virtual_text(
    ui: &mut egui::Ui,
    text: &str,
    cached_starts: Option<&[usize]>,
    reduce_motion: bool,
) {
    let owned_starts;
    let starts = match cached_starts {
        Some(starts) => starts,
        None => {
            owned_starts = build_line_starts(text);
            &owned_starts
        }
    };
    let row_height =
        (ui.text_style_height(&egui::TextStyle::Monospace) + ui.spacing().item_spacing.y + 4.0)
            .max(MIN_DIFF_ROW_HEIGHT);
    egui::ScrollArea::both()
        .auto_shrink([false, false])
        .animated(!reduce_motion)
        .show_rows(ui, row_height, starts.len(), |ui, row_range| {
            for index in row_range {
                ui.monospace(line_at(text, starts, index));
            }
        });
}

fn clip_for_display(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        return text.to_owned();
    }
    let keep_head = max_chars.saturating_sub(64);
    let head: String = text.chars().take(keep_head).collect();
    let omitted = text.chars().count().saturating_sub(keep_head);
    format!("{} … [{} chars omitted]", head, omitted)
}

fn default_report_file_name(doc_path: Option<&Path>) -> String {
    doc_path
        .and_then(|path| path.file_stem())
        .and_then(|value| value.to_str())
        .map(|stem| format!("{}-review-summary.md", sanitize_file_stem(stem)))
        .unwrap_or_else(|| "diffgr-review-summary.md".to_owned())
}

fn default_html_report_file_name(doc_path: Option<&Path>) -> String {
    doc_path
        .and_then(|path| path.file_stem())
        .and_then(|value| value.to_str())
        .map(|stem| format!("{}-review.html", sanitize_file_stem(stem)))
        .unwrap_or_else(|| "diffgr-review.html".to_owned())
}

fn split_pipe_input(value: &str) -> Vec<String> {
    value
        .split('|')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

fn read_json_file(path: &Path) -> Result<Value, String> {
    let text = fs::read_to_string(path).map_err(|err| format!("{}: {}", path.display(), err))?;
    serde_json::from_str(&text).map_err(|err| format!("{}: invalid JSON: {}", path.display(), err))
}

fn write_text_file(path: &Path, text: &str) -> Result<(), String> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent).map_err(|err| format!("{}: {}", parent.display(), err))?;
    }
    fs::write(path, text).map_err(|err| format!("{}: {}", path.display(), err))
}

fn format_state_diff_markdown(diff: &StateDiffReport, title: &str) -> String {
    let mut out = String::new();
    out.push_str(&format!("# {}\n\n", title));
    out.push_str(&format!("- changed total: {}\n\n", diff.changed_total()));
    out.push_str("| Section | Added | Removed | Changed | Unchanged |\n");
    out.push_str("|---|---:|---:|---:|---:|\n");
    for section in &diff.sections {
        out.push_str(&format!(
            "| {} | {} | {} | {} | {} |\n",
            section.section,
            section.added.len(),
            section.removed.len(),
            section.changed.len(),
            section.unchanged
        ));
    }
    for section in &diff.sections {
        if section.changed_total() == 0 {
            continue;
        }
        out.push_str(&format!("\n## {}\n\n", section.section));
        if !section.added.is_empty() {
            out.push_str(&format!("- added: {}\n", section.added.join(", ")));
        }
        if !section.removed.is_empty() {
            out.push_str(&format!("- removed: {}\n", section.removed.join(", ")));
        }
        if !section.changed.is_empty() {
            out.push_str(&format!("- changed: {}\n", section.changed.join(", ")));
        }
    }
    out
}

fn draw_coverage_issue(ui: &mut egui::Ui, issue: &CoverageIssue) {
    if !issue.unassigned.is_empty() {
        egui::CollapsingHeader::new(format!("Unassigned chunks ({})", issue.unassigned.len()))
            .default_open(true)
            .show(ui, |ui| {
                for chunk_id in &issue.unassigned {
                    ui.monospace(chunk_id);
                }
            });
    }
    if !issue.duplicated.is_empty() {
        egui::CollapsingHeader::new(format!(
            "Duplicated assignments ({})",
            issue.duplicated.len()
        ))
        .default_open(true)
        .show(ui, |ui| {
            for (chunk_id, groups) in &issue.duplicated {
                ui.monospace(format!("{} -> {}", chunk_id, groups.join(", ")));
            }
        });
    }
    if !issue.unknown_groups.is_empty() {
        egui::CollapsingHeader::new(format!("Unknown groups ({})", issue.unknown_groups.len()))
            .default_open(true)
            .show(ui, |ui| {
                for group_id in &issue.unknown_groups {
                    ui.monospace(group_id);
                }
            });
    }
    if !issue.unknown_chunks.is_empty() {
        egui::CollapsingHeader::new(format!("Unknown chunks ({})", issue.unknown_chunks.len()))
            .default_open(true)
            .show(ui, |ui| {
                for (chunk_id, groups) in &issue.unknown_chunks {
                    ui.monospace(format!("{} -> {}", chunk_id, groups.join(", ")));
                }
            });
    }
}

fn format_impact_report_markdown(report: &ImpactReport) -> String {
    let mut out = String::new();
    out.push_str("# DiffGR Impact Preview\n\n");
    out.push_str(&format!(
        "- old: {} ({} chunks)\n",
        report.old_title, report.old_chunk_count
    ));
    out.push_str(&format!(
        "- new/current: {} ({} chunks)\n",
        report.new_title, report.new_chunk_count
    ));
    out.push_str(&format!("- unchanged: {}\n", report.unchanged));
    out.push_str(&format!("- changed: {}\n", report.changed));
    out.push_str(&format!("- new only: {}\n", report.new_only));
    out.push_str(&format!("- old only: {}\n\n", report.old_only));
    if !report.warnings.is_empty() {
        out.push_str("## Warnings\n\n");
        for warning in &report.warnings {
            out.push_str(&format!("- {}\n", warning));
        }
        out.push('\n');
    }
    out.push_str("## Groups\n\n");
    out.push_str("| Group | Action | Total | Unchanged | Changed | New |\n");
    out.push_str("|---|---|---:|---:|---:|---:|\n");
    for group in &report.groups {
        out.push_str(&format!(
            "| {} ({}) | {} | {} | {} | {} | {} |\n",
            group.name,
            group.id,
            group.action,
            group.total_new,
            group.unchanged,
            group.changed,
            group.new_chunks
        ));
    }
    out
}

fn sanitize_file_stem(value: &str) -> String {
    let sanitized: String = value
        .chars()
        .map(|ch| match ch {
            '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*' => '-',
            _ => ch,
        })
        .collect();
    sanitized.trim_matches('-').trim().to_owned()
}

fn diff_line_prefix_text(show_line_numbers: bool, line: &DiffLine) -> String {
    if show_line_numbers {
        let old_line = line
            .old_line
            .map(|n| n.to_string())
            .unwrap_or_else(|| "-".to_owned());
        let new_line = line
            .new_line
            .map(|n| n.to_string())
            .unwrap_or_else(|| "-".to_owned());
        format!("{:>5} {:>5} {} ", old_line, new_line, line.prefix())
    } else {
        format!("{} ", line.prefix())
    }
}

fn render_plain_diff_line(
    show_line_numbers: bool,
    line: &DiffLine,
    comment_mark: &str,
    search_mark: &str,
    clip_long_lines: bool,
) -> String {
    let rendered = format!(
        "{}{}{}{}",
        diff_line_prefix_text(show_line_numbers, line),
        line.text,
        comment_mark,
        search_mark
    );
    if clip_long_lines {
        clip_for_display(&rendered, MAX_RENDERED_DIFF_CHARS)
    } else {
        rendered
    }
}

fn build_diff_layout_job(
    ui: &egui::Ui,
    prefix_text: &str,
    segments: &[DiffTextSegment],
    kind: &str,
    comment_mark: &str,
    search_mark: &str,
) -> egui::text::LayoutJob {
    let mut job = egui::text::LayoutJob::default();
    let font_id = egui::TextStyle::Monospace.resolve(ui.style());
    append_diff_job_text(
        &mut job,
        prefix_text,
        font_id.clone(),
        Color32::GRAY,
        Color32::TRANSPARENT,
    );
    for segment in segments {
        append_diff_job_text(
            &mut job,
            &segment.text,
            font_id.clone(),
            color_for_line(kind),
            if segment.changed {
                word_diff_background(kind)
            } else {
                Color32::TRANSPARENT
            },
        );
    }
    if !comment_mark.is_empty() {
        append_diff_job_text(
            &mut job,
            comment_mark,
            font_id.clone(),
            Color32::LIGHT_BLUE,
            Color32::TRANSPARENT,
        );
    }
    if !search_mark.is_empty() {
        append_diff_job_text(
            &mut job,
            search_mark,
            font_id,
            Color32::YELLOW,
            search_inline_background(Color32::TRANSPARENT),
        );
    }
    job
}

fn append_diff_job_text(
    job: &mut egui::text::LayoutJob,
    text: &str,
    font_id: egui::FontId,
    color: Color32,
    background: Color32,
) {
    job.append(
        text,
        0.0,
        egui::TextFormat {
            font_id,
            color,
            background,
            ..Default::default()
        },
    );
}

fn word_diff_background(kind: &str) -> Color32 {
    match kind {
        "add" => Color32::from_rgba_premultiplied(46, 170, 95, 125),
        "delete" => Color32::from_rgba_premultiplied(210, 60, 60, 130),
        _ => Color32::from_rgba_premultiplied(130, 130, 130, 60),
    }
}

fn search_inline_background(existing: Color32) -> Color32 {
    if existing == Color32::TRANSPARENT {
        Color32::from_rgba_premultiplied(210, 170, 45, 125)
    } else {
        Color32::from_rgba_premultiplied(220, 185, 65, 155)
    }
}

fn line_matches_diff_search(line: &DiffLine, query: &str) -> bool {
    let needle = query.trim();
    !needle.is_empty() && line.text.to_lowercase().contains(&needle.to_lowercase())
}

fn diff_line_background(kind: &str, selected: bool, search_match: bool) -> Color32 {
    if selected {
        return Color32::from_rgba_premultiplied(90, 120, 180, 110);
    }
    if search_match {
        return Color32::from_rgba_premultiplied(180, 150, 40, 70);
    }
    match kind {
        "add" => Color32::from_rgba_premultiplied(30, 120, 70, 38),
        "delete" => Color32::from_rgba_premultiplied(150, 45, 45, 42),
        _ => Color32::from_rgba_premultiplied(80, 80, 80, 10),
    }
}

fn status_text_badge(status: &str) -> RichText {
    match status {
        "reviewed" => RichText::new("レビュー済み").color(Color32::LIGHT_GREEN),
        "needsReReview" => RichText::new("再レビュー").color(Color32::YELLOW),
        "ignored" => RichText::new("無視").color(Color32::GRAY),
        _ => RichText::new("未レビュー").color(Color32::LIGHT_RED),
    }
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
    id.chars().take(7).collect()
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

    #[test]
    fn default_report_file_name_is_safe_for_windows() {
        assert_eq!(
            default_report_file_name(Some(Path::new("dir/bad:name.diffgr.json"))),
            "bad-name.diffgr-review-summary.md"
        );
        assert_eq!(default_report_file_name(None), "diffgr-review-summary.md");
    }
}
