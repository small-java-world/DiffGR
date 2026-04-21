use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

const STATE_KEYS: [&str; 4] = ["reviews", "groupBriefs", "analysisState", "threadState"];

#[derive(Clone, Debug)]
pub struct Group {
    pub id: String,
    pub name: String,
    pub order: i64,
    pub tags: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct DiffLine {
    pub kind: String,
    pub text: String,
    pub old_line: Option<i64>,
    pub new_line: Option<i64>,
}

impl DiffLine {
    pub fn prefix(&self) -> &'static str {
        match self.kind.as_str() {
            "add" => "+",
            "delete" => "-",
            _ => " ",
        }
    }

    pub fn anchor(&self) -> LineAnchor {
        LineAnchor {
            line_type: self.kind.clone(),
            old_line: self.old_line,
            new_line: self.new_line,
        }
    }
}

#[derive(Clone, Debug)]
pub struct Chunk {
    pub id: String,
    pub file_path: String,
    pub old_start: Option<i64>,
    pub old_count: Option<i64>,
    pub new_start: Option<i64>,
    pub new_count: Option<i64>,
    pub lines: Arc<Vec<DiffLine>>,
    pub add_count: usize,
    pub delete_count: usize,
}

impl Chunk {
    pub fn short_id(&self) -> String {
        self.id.chars().take(8).collect()
    }

    pub fn old_range_label(&self) -> String {
        range_label(self.old_start, self.old_count)
    }

    pub fn new_range_label(&self) -> String {
        range_label(self.new_start, self.new_count)
    }

    pub fn change_counts(&self) -> (usize, usize) {
        (self.add_count, self.delete_count)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct LineAnchor {
    pub line_type: String,
    pub old_line: Option<i64>,
    pub new_line: Option<i64>,
}

impl LineAnchor {
    pub fn key(&self) -> String {
        format!(
            "{}:{}:{}",
            self.line_type,
            self.old_line.map(|n| n.to_string()).unwrap_or_default(),
            self.new_line.map(|n| n.to_string()).unwrap_or_default()
        )
    }

    pub fn label(&self) -> String {
        let old = self
            .old_line
            .map(|n| n.to_string())
            .unwrap_or_else(|| "-".to_owned());
        let new = self
            .new_line
            .map(|n| n.to_string())
            .unwrap_or_else(|| "-".to_owned());
        format!("{} old:{} new:{}", self.line_type, old, new)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReviewStatus {
    Unreviewed,
    Reviewed,
    Ignored,
    NeedsReReview,
}

impl ReviewStatus {
    pub const ALL: [ReviewStatus; 4] = [
        ReviewStatus::Unreviewed,
        ReviewStatus::Reviewed,
        ReviewStatus::NeedsReReview,
        ReviewStatus::Ignored,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            ReviewStatus::Unreviewed => "unreviewed",
            ReviewStatus::Reviewed => "reviewed",
            ReviewStatus::Ignored => "ignored",
            ReviewStatus::NeedsReReview => "needsReReview",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            ReviewStatus::Unreviewed => "未レビュー",
            ReviewStatus::Reviewed => "レビュー済み",
            ReviewStatus::Ignored => "無視",
            ReviewStatus::NeedsReReview => "再レビュー必要",
        }
    }

    pub fn from_str(value: &str) -> Self {
        match value {
            "reviewed" => ReviewStatus::Reviewed,
            "ignored" => ReviewStatus::Ignored,
            "needsReReview" => ReviewStatus::NeedsReReview,
            _ => ReviewStatus::Unreviewed,
        }
    }

    pub fn is_tracked(self) -> bool {
        self != ReviewStatus::Ignored
    }

    pub fn next_review_toggle(self) -> Self {
        match self {
            ReviewStatus::Reviewed => ReviewStatus::Unreviewed,
            _ => ReviewStatus::Reviewed,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Metrics {
    pub unassigned: usize,
    pub reviewed: usize,
    pub pending: usize,
    pub tracked: usize,
    pub coverage_rate: f32,
}

#[derive(Clone, Debug, Default)]
pub struct GroupMetrics {
    pub reviewed: usize,
    pub pending: usize,
    pub tracked: usize,
}

#[derive(Clone, Debug)]
pub struct GroupBriefDraft {
    pub status: String,
    pub summary: String,
    pub updated_at: String,
    pub source_head: String,
    pub focus_points: String,
    pub test_evidence: String,
    pub known_tradeoffs: String,
    pub questions_for_reviewer: String,
    pub mentions: String,
}

impl Default for GroupBriefDraft {
    fn default() -> Self {
        Self {
            status: "draft".to_owned(),
            summary: String::new(),
            updated_at: String::new(),
            source_head: String::new(),
            focus_points: String::new(),
            test_evidence: String::new(),
            known_tradeoffs: String::new(),
            questions_for_reviewer: String::new(),
            mentions: String::new(),
        }
    }
}

#[derive(Clone, Debug)]
pub struct DiffgrDocument {
    pub raw: Value,
    pub title: String,
    pub groups: Vec<Group>,
    pub chunks: Vec<Chunk>,
    pub assignments: BTreeMap<String, Vec<String>>,
    pub warnings: Vec<String>,
    chunk_index: BTreeMap<String, usize>,
}

impl DiffgrDocument {
    pub fn load_from_path(path: &Path, state_path: Option<&Path>) -> Result<Self, String> {
        let text =
            fs::read_to_string(path).map_err(|err| format!("{}: {}", path.display(), err))?;
        let value: Value = serde_json::from_str(&text)
            .map_err(|err| format!("{}: invalid JSON: {}", path.display(), err))?;
        let mut doc = Self::from_value(value)?;
        if let Some(state_path) = state_path {
            doc.apply_state_file(state_path)?;
        }
        Ok(doc)
    }

    pub fn from_value(raw: Value) -> Result<Self, String> {
        validate_document(&raw)?;
        let warnings = validate_references(&raw);
        let title = raw
            .get("meta")
            .and_then(|meta| meta.get("title"))
            .map(value_to_string)
            .filter(|text| !text.is_empty())
            .unwrap_or_else(|| "DiffGR".to_owned());
        let groups = parse_groups(&raw);
        let chunks = parse_chunks(&raw);
        let mut chunk_index = BTreeMap::new();
        for (index, chunk) in chunks.iter().enumerate() {
            chunk_index.insert(chunk.id.clone(), index);
        }
        let assignments = parse_assignments(&raw);
        Ok(Self {
            raw,
            title,
            groups,
            chunks,
            assignments,
            warnings,
            chunk_index,
        })
    }

    pub fn chunk_by_id(&self, chunk_id: &str) -> Option<&Chunk> {
        self.chunk_index
            .get(chunk_id)
            .and_then(|idx| self.chunks.get(*idx))
    }

    pub fn group_by_id(&self, group_id: &str) -> Option<&Group> {
        self.groups.iter().find(|group| group.id == group_id)
    }

    pub fn chunk_ids_for_group(&self, group_id: Option<&str>) -> Vec<String> {
        match group_id {
            Some(group_id) => self.assignments.get(group_id).cloned().unwrap_or_default(),
            None => self.chunks.iter().map(|chunk| chunk.id.clone()).collect(),
        }
    }

    pub fn status_for(&self, chunk_id: &str) -> ReviewStatus {
        let status = self
            .raw
            .get("reviews")
            .and_then(Value::as_object)
            .and_then(|reviews| reviews.get(chunk_id))
            .and_then(Value::as_object)
            .and_then(|record| record.get("status"))
            .and_then(Value::as_str)
            .unwrap_or("unreviewed");
        ReviewStatus::from_str(status)
    }

    pub fn set_status(&mut self, chunk_id: &str, status: ReviewStatus) {
        if status == ReviewStatus::Unreviewed {
            if let Some(record) = self.review_record_mut_if_present(chunk_id) {
                record.remove("status");
            }
            self.prune_chunk_review(chunk_id);
            return;
        }
        let record = self.ensure_review_record(chunk_id);
        record.insert(
            "status".to_owned(),
            Value::String(status.as_str().to_owned()),
        );
    }

    pub fn comment_for(&self, chunk_id: &str) -> String {
        self.raw
            .get("reviews")
            .and_then(Value::as_object)
            .and_then(|reviews| reviews.get(chunk_id))
            .and_then(Value::as_object)
            .and_then(|record| record.get("comment"))
            .map(value_to_string)
            .unwrap_or_default()
    }

    pub fn set_comment(&mut self, chunk_id: &str, comment: &str) {
        let normalized = comment.trim();
        if normalized.is_empty() {
            if let Some(record) = self.review_record_mut_if_present(chunk_id) {
                record.remove("comment");
            }
            self.prune_chunk_review(chunk_id);
            return;
        }
        let record = self.ensure_review_record(chunk_id);
        record.insert("comment".to_owned(), Value::String(normalized.to_owned()));
    }

    pub fn line_comment_for(&self, chunk_id: &str, anchor: &LineAnchor) -> String {
        self.raw
            .get("reviews")
            .and_then(Value::as_object)
            .and_then(|reviews| reviews.get(chunk_id))
            .and_then(Value::as_object)
            .and_then(|record| record.get("lineComments"))
            .and_then(Value::as_array)
            .and_then(|comments| {
                comments.iter().find(|item| {
                    item.as_object()
                        .map(|obj| line_comment_matches(obj, anchor))
                        .unwrap_or(false)
                })
            })
            .and_then(Value::as_object)
            .and_then(|obj| obj.get("comment"))
            .map(value_to_string)
            .unwrap_or_default()
    }

    pub fn line_comment_count_for(&self, chunk_id: &str) -> usize {
        self.raw
            .get("reviews")
            .and_then(Value::as_object)
            .and_then(|reviews| reviews.get(chunk_id))
            .and_then(Value::as_object)
            .and_then(|record| record.get("lineComments"))
            .and_then(Value::as_array)
            .map(|comments| {
                comments
                    .iter()
                    .filter(|item| {
                        item.as_object()
                            .and_then(|obj| obj.get("comment"))
                            .map(value_to_string)
                            .map(|text| !text.trim().is_empty())
                            .unwrap_or(false)
                    })
                    .count()
            })
            .unwrap_or(0)
    }

    pub fn set_line_comment(&mut self, chunk_id: &str, anchor: &LineAnchor, comment: &str) {
        let normalized = comment.trim().to_owned();
        {
            let record = self.ensure_review_record(chunk_id);
            let mut kept: Vec<Value> = Vec::new();
            let mut found = false;
            if let Some(existing) = record.get("lineComments").and_then(Value::as_array) {
                for item in existing {
                    let is_match = item
                        .as_object()
                        .map(|obj| line_comment_matches(obj, anchor))
                        .unwrap_or(false);
                    if is_match {
                        found = true;
                        if !normalized.is_empty() {
                            kept.push(line_comment_value(anchor, &normalized));
                        }
                    } else {
                        kept.push(item.clone());
                    }
                }
            }
            if !normalized.is_empty() && !found {
                kept.push(line_comment_value(anchor, &normalized));
            }
            if kept.is_empty() {
                record.remove("lineComments");
            } else {
                record.insert("lineComments".to_owned(), Value::Array(kept));
            }
        }

        if normalized.is_empty() {
            self.clear_selected_line_anchor_if_same(anchor);
        } else {
            self.set_selected_line_anchor_state(Some(anchor));
        }
        self.prune_chunk_review(chunk_id);
    }

    pub fn set_selected_line_anchor_state(&mut self, anchor: Option<&LineAnchor>) {
        let root = self.raw.as_object_mut().expect("validated object");
        let thread_state = ensure_object_field(root, "threadState");
        match anchor {
            Some(anchor) => {
                thread_state.insert(
                    "selectedLineAnchor".to_owned(),
                    json!({
                        "anchorKey": anchor.key(),
                        "oldLine": anchor.old_line,
                        "newLine": anchor.new_line,
                        "lineType": anchor.line_type,
                    }),
                );
            }
            None => {
                thread_state.remove("selectedLineAnchor");
                if thread_state.is_empty() {
                    root.remove("threadState");
                }
            }
        }
    }

    pub fn analysis_string(&self, key: &str) -> Option<String> {
        self.raw
            .get("analysisState")
            .and_then(Value::as_object)
            .and_then(|obj| obj.get(key))
            .map(value_to_string)
            .filter(|value| !value.is_empty())
    }

    pub fn set_analysis_string(&mut self, key: &str, value: Option<&str>) {
        let root = self.raw.as_object_mut().expect("validated object");
        let analysis_state = ensure_object_field(root, "analysisState");
        match value.map(str::trim).filter(|value| !value.is_empty()) {
            Some(value) => {
                analysis_state.insert(key.to_owned(), Value::String(value.to_owned()));
            }
            None => {
                analysis_state.remove(key);
            }
        }
        if analysis_state.is_empty() {
            root.remove("analysisState");
        }
    }

    pub fn selected_line_anchor_from_state(&self) -> Option<LineAnchor> {
        let obj = self
            .raw
            .get("threadState")
            .and_then(Value::as_object)
            .and_then(|thread| thread.get("selectedLineAnchor"))
            .and_then(Value::as_object)?;
        let line_type = obj
            .get("lineType")
            .map(value_to_string)
            .filter(|s| !s.is_empty())?;
        Some(LineAnchor {
            line_type,
            old_line: obj.get("oldLine").and_then(value_to_i64),
            new_line: obj.get("newLine").and_then(value_to_i64),
        })
    }

    pub fn group_brief_draft(&self, group_id: &str) -> GroupBriefDraft {
        let mut draft = GroupBriefDraft::default();
        let Some(record) = self
            .raw
            .get("groupBriefs")
            .and_then(Value::as_object)
            .and_then(|briefs| briefs.get(group_id))
            .and_then(Value::as_object)
        else {
            return draft;
        };
        draft.status = record
            .get("status")
            .map(value_to_string)
            .filter(|value| is_valid_group_brief_status(value))
            .unwrap_or_else(|| "draft".to_owned());
        draft.summary = record
            .get("summary")
            .map(value_to_string)
            .unwrap_or_default();
        draft.updated_at = record
            .get("updatedAt")
            .map(value_to_string)
            .unwrap_or_default();
        draft.source_head = record
            .get("sourceHead")
            .map(value_to_string)
            .unwrap_or_default();
        draft.focus_points = json_array_to_pipe(record.get("focusPoints"));
        draft.test_evidence = json_array_to_pipe(record.get("testEvidence"));
        draft.known_tradeoffs = json_array_to_pipe(record.get("knownTradeoffs"));
        draft.questions_for_reviewer = json_array_to_pipe(record.get("questionsForReviewer"));
        draft.mentions = json_array_to_pipe(record.get("mentions"));
        draft
    }

    pub fn set_group_brief_from_draft(&mut self, group_id: &str, draft: &GroupBriefDraft) {
        let mut record = Map::new();
        let status = draft.status.trim();
        if is_valid_group_brief_status(status) {
            record.insert("status".to_owned(), Value::String(status.to_owned()));
        }
        insert_non_empty_string(&mut record, "summary", &draft.summary);
        insert_non_empty_string(&mut record, "updatedAt", &draft.updated_at);
        insert_non_empty_string(&mut record, "sourceHead", &draft.source_head);
        insert_pipe_list(&mut record, "focusPoints", &draft.focus_points);
        insert_pipe_list(&mut record, "testEvidence", &draft.test_evidence);
        insert_pipe_list(&mut record, "knownTradeoffs", &draft.known_tradeoffs);
        insert_pipe_list(
            &mut record,
            "questionsForReviewer",
            &draft.questions_for_reviewer,
        );
        insert_pipe_list(&mut record, "mentions", &draft.mentions);

        let root = self.raw.as_object_mut().expect("validated object");
        if record.is_empty() {
            if let Some(group_briefs) = root.get_mut("groupBriefs").and_then(Value::as_object_mut) {
                group_briefs.remove(group_id);
                if group_briefs.is_empty() {
                    root.remove("groupBriefs");
                }
            }
            return;
        }
        let group_briefs = ensure_object_field(root, "groupBriefs");
        group_briefs.insert(group_id.to_owned(), Value::Object(record));
    }

    pub fn metrics(&self) -> Metrics {
        let chunk_ids: BTreeSet<String> =
            self.chunks.iter().map(|chunk| chunk.id.clone()).collect();
        let assigned: BTreeSet<String> = self
            .assignments
            .values()
            .flat_map(|items| items.iter().cloned())
            .collect();
        let ignored: BTreeSet<String> = chunk_ids
            .iter()
            .filter(|chunk_id| self.status_for(chunk_id) == ReviewStatus::Ignored)
            .cloned()
            .collect();
        let tracked: BTreeSet<String> = chunk_ids.difference(&ignored).cloned().collect();
        let reviewed = tracked
            .iter()
            .filter(|chunk_id| self.status_for(chunk_id) == ReviewStatus::Reviewed)
            .count();
        let pending = tracked
            .iter()
            .filter(|chunk_id| {
                matches!(
                    self.status_for(chunk_id),
                    ReviewStatus::Unreviewed | ReviewStatus::NeedsReReview
                )
            })
            .count();
        let tracked_count = tracked.len();
        let coverage_rate = if tracked_count == 0 {
            1.0
        } else {
            reviewed as f32 / tracked_count as f32
        };
        Metrics {
            unassigned: chunk_ids.difference(&assigned).count(),
            reviewed,
            pending,
            tracked: tracked_count,
            coverage_rate,
        }
    }

    pub fn group_metrics(&self, group_id: Option<&str>) -> GroupMetrics {
        let mut metrics = GroupMetrics::default();
        for chunk_id in self.chunk_ids_for_group(group_id) {
            let status = self.status_for(&chunk_id);
            if !status.is_tracked() {
                continue;
            }
            metrics.tracked += 1;
            if status == ReviewStatus::Reviewed {
                metrics.reviewed += 1;
            } else {
                metrics.pending += 1;
            }
        }
        metrics
    }

    pub fn extract_state(&self) -> Value {
        let mut state = Map::new();
        for key in STATE_KEYS {
            let value = self
                .raw
                .get(key)
                .and_then(Value::as_object)
                .map(|obj| Value::Object(obj.clone()))
                .unwrap_or_else(|| Value::Object(Map::new()));
            state.insert(key.to_owned(), value);
        }
        Value::Object(state)
    }

    pub fn apply_state_file(&mut self, state_path: &Path) -> Result<(), String> {
        let text = fs::read_to_string(state_path)
            .map_err(|err| format!("{}: {}", state_path.display(), err))?;
        let state: Value = serde_json::from_str(&text)
            .map_err(|err| format!("{}: invalid state JSON: {}", state_path.display(), err))?;
        self.apply_state_value(state)
    }

    pub fn apply_state_value(&mut self, state: Value) -> Result<(), String> {
        let normalized = normalize_state_payload(state)?;
        let root = self.raw.as_object_mut().expect("validated object");
        let state_obj = normalized.as_object().expect("normalized state object");
        for key in STATE_KEYS {
            let candidate = state_obj
                .get(key)
                .cloned()
                .unwrap_or_else(|| Value::Object(Map::new()));
            let keep = key == "reviews"
                || candidate
                    .as_object()
                    .map(|obj| !obj.is_empty())
                    .unwrap_or(false);
            if keep {
                root.insert(key.to_owned(), candidate);
            } else {
                root.remove(key);
            }
        }
        Ok(())
    }

    pub fn write_full_document(&self, path: &Path, make_backup: bool) -> Result<(), String> {
        if make_backup && path.exists() {
            let backup = path.with_extension(format!(
                "{}bak",
                path.extension()
                    .and_then(|value| value.to_str())
                    .map(|ext| format!("{}.", ext))
                    .unwrap_or_default()
            ));
            fs::copy(path, &backup)
                .map_err(|err| format!("backup {}: {}", backup.display(), err))?;
        }
        write_json(path, &self.raw)
    }

    pub fn write_state(&self, path: &Path) -> Result<(), String> {
        write_json(path, &self.extract_state())
    }

    fn ensure_review_record(&mut self, chunk_id: &str) -> &mut Map<String, Value> {
        let root = self.raw.as_object_mut().expect("validated object");
        let reviews = ensure_object_field(root, "reviews");
        ensure_object_field(reviews, chunk_id)
    }

    fn review_record_mut_if_present(&mut self, chunk_id: &str) -> Option<&mut Map<String, Value>> {
        self.raw
            .as_object_mut()
            .and_then(|root| root.get_mut("reviews"))
            .and_then(Value::as_object_mut)
            .and_then(|reviews| reviews.get_mut(chunk_id))
            .and_then(Value::as_object_mut)
    }

    fn prune_chunk_review(&mut self, chunk_id: &str) {
        let Some(root) = self.raw.as_object_mut() else {
            return;
        };
        let Some(reviews) = root.get_mut("reviews").and_then(Value::as_object_mut) else {
            return;
        };
        let keep = reviews
            .get(chunk_id)
            .and_then(Value::as_object)
            .map(|record| {
                let has_status = record
                    .get("status")
                    .map(value_to_string)
                    .map(|text| !text.trim().is_empty())
                    .unwrap_or(false);
                let has_comment = record
                    .get("comment")
                    .map(value_to_string)
                    .map(|text| !text.trim().is_empty())
                    .unwrap_or(false);
                let has_line_comments = record
                    .get("lineComments")
                    .and_then(Value::as_array)
                    .map(|items| !items.is_empty())
                    .unwrap_or(false);
                has_status || has_comment || has_line_comments
            })
            .unwrap_or(false);
        if !keep {
            reviews.remove(chunk_id);
        }
    }

    fn clear_selected_line_anchor_if_same(&mut self, anchor: &LineAnchor) {
        let Some(root) = self.raw.as_object_mut() else {
            return;
        };
        let Some(thread_state) = root.get_mut("threadState").and_then(Value::as_object_mut) else {
            return;
        };
        let is_same = thread_state
            .get("selectedLineAnchor")
            .and_then(Value::as_object)
            .map(|obj| {
                obj.get("lineType").map(value_to_string).unwrap_or_default() == anchor.line_type
                    && obj.get("oldLine").and_then(value_to_i64) == anchor.old_line
                    && obj.get("newLine").and_then(value_to_i64) == anchor.new_line
            })
            .unwrap_or(false);
        if is_same {
            thread_state.remove("selectedLineAnchor");
        }
    }
}

pub fn normalize_state_payload(payload: Value) -> Result<Value, String> {
    let payload = match payload {
        Value::Object(mut obj) => obj.remove("state").unwrap_or(Value::Object(obj)),
        _ => return Err("State payload must be a JSON object.".to_owned()),
    };
    let obj = payload
        .as_object()
        .ok_or_else(|| "`state` must be a JSON object.".to_owned())?;
    if !STATE_KEYS.iter().any(|key| obj.contains_key(*key)) {
        return Err("State payload must include one or more of: reviews, groupBriefs, analysisState, threadState.".to_owned());
    }
    let mut state = Map::new();
    for key in STATE_KEYS {
        let value = obj
            .get(key)
            .cloned()
            .unwrap_or_else(|| Value::Object(Map::new()));
        if !value.is_object() {
            return Err(format!("`{}` must be a JSON object.", key));
        }
        state.insert(key.to_owned(), value);
    }
    Ok(Value::Object(state))
}

fn parse_groups(raw: &Value) -> Vec<Group> {
    raw.get("groups")
        .and_then(Value::as_array)
        .map(|groups| {
            let mut parsed: Vec<Group> = groups
                .iter()
                .filter_map(|value| {
                    let obj = value.as_object()?;
                    let id = obj
                        .get("id")
                        .map(value_to_string)
                        .filter(|text| !text.is_empty())?;
                    let name = obj
                        .get("name")
                        .map(value_to_string)
                        .filter(|text| !text.is_empty())
                        .unwrap_or_else(|| id.clone());
                    let order = obj.get("order").and_then(value_to_i64).unwrap_or(0);
                    let tags = obj
                        .get("tags")
                        .and_then(Value::as_array)
                        .map(|items| {
                            items
                                .iter()
                                .map(value_to_string)
                                .filter(|s| !s.is_empty())
                                .collect()
                        })
                        .unwrap_or_default();
                    Some(Group {
                        id,
                        name,
                        order,
                        tags,
                    })
                })
                .collect();
            parsed.sort_by(|left, right| {
                left.order
                    .cmp(&right.order)
                    .then(left.name.cmp(&right.name))
            });
            parsed
        })
        .unwrap_or_default()
}

fn parse_chunks(raw: &Value) -> Vec<Chunk> {
    raw.get("chunks")
        .and_then(Value::as_array)
        .map(|chunks| chunks.iter().filter_map(parse_chunk).collect())
        .unwrap_or_default()
}

fn parse_chunk(value: &Value) -> Option<Chunk> {
    let obj = value.as_object()?;
    let id = obj
        .get("id")
        .map(value_to_string)
        .filter(|text| !text.is_empty())?;
    let file_path = obj.get("filePath").map(value_to_string).unwrap_or_default();
    let (old_start, old_count) = range_from_obj(obj.get("old"));
    let (new_start, new_count) = range_from_obj(obj.get("new"));
    let lines: Vec<DiffLine> = obj
        .get("lines")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(|line| {
                    let line_obj = line.as_object()?;
                    Some(DiffLine {
                        kind: line_obj
                            .get("kind")
                            .map(value_to_string)
                            .filter(|value| !value.is_empty())
                            .unwrap_or_else(|| "context".to_owned()),
                        text: line_obj
                            .get("text")
                            .map(value_to_string)
                            .unwrap_or_default(),
                        old_line: line_obj.get("oldLine").and_then(value_to_i64),
                        new_line: line_obj.get("newLine").and_then(value_to_i64),
                    })
                })
                .collect()
        })
        .unwrap_or_default();
    let add_count = lines.iter().filter(|line| line.kind == "add").count();
    let delete_count = lines.iter().filter(|line| line.kind == "delete").count();
    Some(Chunk {
        id,
        file_path,
        old_start,
        old_count,
        new_start,
        new_count,
        lines: Arc::new(lines),
        add_count,
        delete_count,
    })
}

fn parse_assignments(raw: &Value) -> BTreeMap<String, Vec<String>> {
    raw.get("assignments")
        .and_then(Value::as_object)
        .map(|items| {
            items
                .iter()
                .map(|(group_id, value)| {
                    let chunks = value
                        .as_array()
                        .map(|arr| {
                            arr.iter()
                                .map(value_to_string)
                                .filter(|s| !s.is_empty())
                                .collect()
                        })
                        .unwrap_or_default();
                    (group_id.clone(), chunks)
                })
                .collect()
        })
        .unwrap_or_default()
}

fn range_from_obj(value: Option<&Value>) -> (Option<i64>, Option<i64>) {
    let Some(obj) = value.and_then(Value::as_object) else {
        return (None, None);
    };
    (
        obj.get("start").and_then(value_to_i64),
        obj.get("count").and_then(value_to_i64),
    )
}

fn range_label(start: Option<i64>, count: Option<i64>) -> String {
    match (start, count) {
        (Some(start), Some(count)) if count > 1 => format!("{}+{}", start, count),
        (Some(start), _) => start.to_string(),
        _ => "-".to_owned(),
    }
}

fn validate_document(raw: &Value) -> Result<(), String> {
    let obj = raw
        .as_object()
        .ok_or_else(|| "DiffGR document must be a JSON object.".to_owned())?;
    for key in [
        "format",
        "version",
        "meta",
        "groups",
        "chunks",
        "assignments",
        "reviews",
    ] {
        if !obj.contains_key(key) {
            return Err(format!("Missing required key: {}", key));
        }
    }
    if raw.get("format").and_then(Value::as_str) != Some("diffgr") {
        return Err(format!(
            "Unsupported format: {}",
            raw.get("format").map(value_to_string).unwrap_or_default()
        ));
    }
    if raw.get("version").and_then(value_to_i64) != Some(1) {
        return Err(format!(
            "Unsupported version: {}",
            raw.get("version").map(value_to_string).unwrap_or_default()
        ));
    }
    if !raw.get("groups").map(Value::is_array).unwrap_or(false) {
        return Err("`groups` must be an array.".to_owned());
    }
    if !raw.get("chunks").map(Value::is_array).unwrap_or(false) {
        return Err("`chunks` must be an array.".to_owned());
    }
    if !raw
        .get("assignments")
        .map(Value::is_object)
        .unwrap_or(false)
    {
        return Err("`assignments` must be an object.".to_owned());
    }
    if !raw.get("reviews").map(Value::is_object).unwrap_or(false) {
        return Err("`reviews` must be an object.".to_owned());
    }
    Ok(())
}

fn validate_references(raw: &Value) -> Vec<String> {
    let mut warnings = Vec::new();
    let group_ids: Vec<String> = raw
        .get("groups")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|value| value.as_object())
        .filter_map(|obj| obj.get("id"))
        .map(value_to_string)
        .collect();
    let chunk_ids: Vec<String> = raw
        .get("chunks")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|value| value.as_object())
        .filter_map(|obj| obj.get("id"))
        .map(value_to_string)
        .collect();

    let group_set: BTreeSet<String> = group_ids.iter().cloned().collect();
    let chunk_set: BTreeSet<String> = chunk_ids.iter().cloned().collect();
    if group_ids.len() != group_set.len() {
        warnings.push("Duplicate group ids detected.".to_owned());
    }
    if chunk_ids.len() != chunk_set.len() {
        warnings.push("Duplicate chunk ids detected.".to_owned());
    }

    let assignments = raw
        .get("assignments")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    for group_id in &group_set {
        if !assignments.contains_key(group_id) {
            warnings.push(format!("Group missing assignments entry: {}", group_id));
        }
    }
    for (group_id, assigned) in assignments {
        if !group_set.contains(&group_id) {
            warnings.push(format!("Assignment key not in groups: {}", group_id));
        }
        let Some(items) = assigned.as_array() else {
            warnings.push(format!("Assignment value must be array: {}", group_id));
            continue;
        };
        for chunk_id in items.iter().map(value_to_string) {
            if !chunk_set.contains(&chunk_id) {
                warnings.push(format!("Assigned chunk id not found: {}", chunk_id));
            }
        }
    }
    if let Some(reviews) = raw.get("reviews").and_then(Value::as_object) {
        for chunk_id in reviews.keys() {
            if !chunk_set.contains(chunk_id) {
                warnings.push(format!("Review key chunk id not found: {}", chunk_id));
            }
        }
    }
    warnings
}

fn value_to_string(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(text) => text.clone(),
        Value::Number(number) => number.to_string(),
        Value::Bool(value) => value.to_string(),
        other => other.to_string(),
    }
}

fn value_to_i64(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number
            .as_i64()
            .or_else(|| number.as_u64().and_then(|n| i64::try_from(n).ok())),
        Value::String(text) => text.trim().parse::<i64>().ok(),
        _ => None,
    }
}

fn ensure_object_field<'a>(
    parent: &'a mut Map<String, Value>,
    key: &str,
) -> &'a mut Map<String, Value> {
    let needs_init = !parent.get(key).map(Value::is_object).unwrap_or(false);
    if needs_init {
        parent.insert(key.to_owned(), Value::Object(Map::new()));
    }
    parent
        .get_mut(key)
        .and_then(Value::as_object_mut)
        .expect("object inserted")
}

fn line_comment_matches(obj: &Map<String, Value>, anchor: &LineAnchor) -> bool {
    obj.get("lineType").map(value_to_string).unwrap_or_default() == anchor.line_type
        && obj.get("oldLine").and_then(value_to_i64) == anchor.old_line
        && obj.get("newLine").and_then(value_to_i64) == anchor.new_line
}

fn line_comment_value(anchor: &LineAnchor, comment: &str) -> Value {
    json!({
        "oldLine": anchor.old_line,
        "newLine": anchor.new_line,
        "lineType": anchor.line_type,
        "comment": comment,
    })
}

fn insert_non_empty_string(record: &mut Map<String, Value>, key: &str, value: &str) {
    let normalized = value.trim();
    if !normalized.is_empty() {
        record.insert(key.to_owned(), Value::String(normalized.to_owned()));
    }
}

fn insert_pipe_list(record: &mut Map<String, Value>, key: &str, value: &str) {
    let items: Vec<Value> = split_pipe_list(value)
        .into_iter()
        .map(Value::String)
        .collect();
    if !items.is_empty() {
        record.insert(key.to_owned(), Value::Array(items));
    }
}

fn split_pipe_list(value: &str) -> Vec<String> {
    value
        .split('|')
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

fn json_array_to_pipe(value: Option<&Value>) -> String {
    value
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .map(value_to_string)
                .map(|text| text.trim().to_owned())
                .filter(|text| !text.is_empty())
                .collect::<Vec<_>>()
                .join(" | ")
        })
        .unwrap_or_default()
}

fn is_valid_group_brief_status(value: &str) -> bool {
    matches!(value, "draft" | "ready" | "acknowledged" | "stale")
}

fn write_json(path: &Path, value: &Value) -> Result<(), String> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent).map_err(|err| format!("{}: {}", parent.display(), err))?;
    }
    let text = serde_json::to_string_pretty(value).map_err(|err| err.to_string())? + "\n";
    fs::write(path, text).map_err(|err| format!("{}: {}", path.display(), err))
}

#[allow(dead_code)]
fn canonicalize_for_display(path: &Path) -> PathBuf {
    path.canonicalize().unwrap_or_else(|_| path.to_path_buf())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn minimal_doc() -> Value {
        json!({
            "format": "diffgr",
            "version": 1,
            "meta": { "title": "UT" },
            "groups": [
                {"id": "g-app", "name": "App", "order": 2, "tags": ["rust"]},
                {"id": "g-core", "name": "Core", "order": 1, "tags": []}
            ],
            "chunks": [
                {
                    "id": "c1",
                    "filePath": "src/a.rs",
                    "old": {"start": 1, "count": 1},
                    "new": {"start": 1, "count": 2},
                    "lines": [
                        {"kind": "context", "text": "a", "oldLine": 1, "newLine": 1},
                        {"kind": "add", "text": "b", "oldLine": null, "newLine": 2}
                    ]
                },
                {
                    "id": "c2",
                    "filePath": "src/b.rs",
                    "old": {"start": 10, "count": 2},
                    "new": {"start": 10, "count": 1},
                    "lines": [
                        {"kind": "delete", "text": "old", "oldLine": 10, "newLine": null},
                        {"kind": "context", "text": "stay", "oldLine": 11, "newLine": 10}
                    ]
                },
                {
                    "id": "c3",
                    "filePath": "src/unassigned.rs",
                    "old": {"start": 20, "count": 1},
                    "new": {"start": 20, "count": 1},
                    "lines": [
                        {"kind": "context", "text": "same", "oldLine": 20, "newLine": 20}
                    ]
                }
            ],
            "assignments": {
                "g-app": ["c1", "c2"],
                "g-core": []
            },
            "reviews": {}
        })
    }

    fn unique_temp_dir(label: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time moves forward")
            .as_nanos();
        std::env::temp_dir().join(format!(
            "diffgr_gui_model_ut_{}_{}_{}",
            label,
            process::id(),
            nanos
        ))
    }

    #[test]
    fn parses_document_groups_chunks_and_change_counts() {
        let doc = DiffgrDocument::from_value(minimal_doc()).unwrap();
        assert_eq!(doc.title, "UT");
        assert_eq!(
            doc.groups.iter().map(|g| g.id.as_str()).collect::<Vec<_>>(),
            vec!["g-core", "g-app"]
        );
        assert_eq!(
            doc.chunk_ids_for_group(Some("g-app")),
            vec!["c1".to_owned(), "c2".to_owned()]
        );
        assert_eq!(doc.chunk_ids_for_group(None).len(), 3);

        let c1 = doc.chunk_by_id("c1").unwrap();
        assert_eq!(c1.short_id(), "c1");
        assert_eq!(c1.old_range_label(), "1");
        assert_eq!(c1.new_range_label(), "1+2");
        assert_eq!(c1.change_counts(), (1, 0));

        let c2 = doc.chunk_by_id("c2").unwrap();
        assert_eq!(c2.change_counts(), (0, 1));
        assert!(doc.warnings.is_empty());
    }

    #[test]
    fn edit_status_comment_and_state() {
        let mut doc = DiffgrDocument::from_value(minimal_doc()).unwrap();
        doc.set_status("c1", ReviewStatus::Reviewed);
        doc.set_comment("c1", "  looks good  ");
        let anchor = LineAnchor {
            line_type: "add".into(),
            old_line: None,
            new_line: Some(2),
        };
        doc.set_line_comment("c1", &anchor, " line note ");
        assert_eq!(doc.status_for("c1"), ReviewStatus::Reviewed);
        assert_eq!(doc.comment_for("c1"), "looks good");
        assert_eq!(doc.line_comment_for("c1", &anchor), "line note");
        assert_eq!(doc.line_comment_count_for("c1"), 1);
        assert_eq!(doc.selected_line_anchor_from_state(), Some(anchor.clone()));

        let state = doc.extract_state();
        assert_eq!(state["reviews"]["c1"]["status"], json!("reviewed"));
        assert_eq!(state["reviews"]["c1"]["comment"], json!("looks good"));
    }

    #[test]
    fn removing_empty_status_comments_prunes_review_record() {
        let mut doc = DiffgrDocument::from_value(minimal_doc()).unwrap();
        let anchor = LineAnchor {
            line_type: "add".into(),
            old_line: None,
            new_line: Some(2),
        };
        doc.set_status("c1", ReviewStatus::Reviewed);
        doc.set_comment("c1", "note");
        doc.set_line_comment("c1", &anchor, "line note");

        doc.set_status("c1", ReviewStatus::Unreviewed);
        doc.set_comment("c1", "   ");
        doc.set_line_comment("c1", &anchor, "");

        assert_eq!(doc.status_for("c1"), ReviewStatus::Unreviewed);
        assert_eq!(doc.comment_for("c1"), "");
        assert_eq!(doc.line_comment_count_for("c1"), 0);
        assert!(doc.selected_line_anchor_from_state().is_none());
        assert!(doc.raw["reviews"].as_object().unwrap().get("c1").is_none());
    }

    #[test]
    fn metrics_exclude_ignored_and_count_unassigned() {
        let mut doc = DiffgrDocument::from_value(minimal_doc()).unwrap();
        doc.set_status("c1", ReviewStatus::Reviewed);
        doc.set_status("c2", ReviewStatus::Ignored);
        let metrics = doc.metrics();
        assert_eq!(metrics.reviewed, 1);
        assert_eq!(metrics.pending, 1);
        assert_eq!(metrics.tracked, 2);
        assert_eq!(metrics.unassigned, 1);
        assert!((metrics.coverage_rate - 0.5).abs() < f32::EPSILON);

        let group_metrics = doc.group_metrics(Some("g-app"));
        assert_eq!(group_metrics.reviewed, 1);
        assert_eq!(group_metrics.pending, 0);
        assert_eq!(group_metrics.tracked, 1);
    }

    #[test]
    fn normalize_state_payload_accepts_wrapped_state_and_rejects_bad_shapes() {
        let normalized = normalize_state_payload(json!({
            "state": {
                "reviews": {"c1": {"status": "reviewed"}}
            }
        }))
        .unwrap();
        assert_eq!(normalized["reviews"]["c1"]["status"], json!("reviewed"));
        assert_eq!(normalized["groupBriefs"], json!({}));
        assert_eq!(normalized["analysisState"], json!({}));
        assert_eq!(normalized["threadState"], json!({}));

        assert!(normalize_state_payload(json!({"reviews": []})).is_err());
        assert!(normalize_state_payload(json!({"notState": {}})).is_err());
        assert!(normalize_state_payload(json!([])).is_err());
    }

    #[test]
    fn apply_state_value_replaces_reviews_and_restores_ui_state() {
        let mut doc = DiffgrDocument::from_value(minimal_doc()).unwrap();
        doc.set_status("c1", ReviewStatus::Reviewed);
        doc.apply_state_value(json!({
            "reviews": {"c2": {"status": "needsReReview", "comment": "check again"}},
            "analysisState": {"selectedChunkId": "c2", "filterText": "src/"},
            "threadState": {"selectedLineAnchor": {"lineType": "delete", "oldLine": 10, "newLine": null}}
        }))
        .unwrap();

        assert_eq!(doc.status_for("c1"), ReviewStatus::Unreviewed);
        assert_eq!(doc.status_for("c2"), ReviewStatus::NeedsReReview);
        assert_eq!(doc.comment_for("c2"), "check again");
        assert_eq!(
            doc.analysis_string("selectedChunkId"),
            Some("c2".to_owned())
        );
        assert_eq!(doc.analysis_string("filterText"), Some("src/".to_owned()));
        assert_eq!(
            doc.selected_line_anchor_from_state(),
            Some(LineAnchor {
                line_type: "delete".to_owned(),
                old_line: Some(10),
                new_line: None
            })
        );
    }

    #[test]
    fn group_brief_roundtrip_splits_pipe_lists_and_prunes_empty_record() {
        let mut doc = DiffgrDocument::from_value(minimal_doc()).unwrap();
        let draft = GroupBriefDraft {
            status: "ready".to_owned(),
            summary: " GUI review ".to_owned(),
            updated_at: "2026-04-19T00:00:00Z".to_owned(),
            source_head: "abc123".to_owned(),
            focus_points: "startup | state save |  ".to_owned(),
            test_evidence: "cargo test".to_owned(),
            known_tradeoffs: "large diff".to_owned(),
            questions_for_reviewer: "none".to_owned(),
            mentions: "@reviewer | @owner".to_owned(),
        };
        doc.set_group_brief_from_draft("g-app", &draft);
        assert_eq!(doc.raw["groupBriefs"]["g-app"]["status"], json!("ready"));
        assert_eq!(
            doc.raw["groupBriefs"]["g-app"]["focusPoints"],
            json!(["startup", "state save"])
        );

        let restored = doc.group_brief_draft("g-app");
        assert_eq!(restored.status, "ready");
        assert_eq!(restored.summary, "GUI review");
        assert_eq!(restored.focus_points, "startup | state save");
        assert_eq!(restored.mentions, "@reviewer | @owner");

        let empty = GroupBriefDraft {
            status: String::new(),
            ..GroupBriefDraft::default()
        };
        doc.set_group_brief_from_draft("g-app", &empty);
        assert!(doc.raw.get("groupBriefs").is_none());
    }

    #[test]
    fn validation_reports_bad_references_without_failing_load() {
        let mut raw = minimal_doc();
        raw["assignments"]["missing-group"] = json!(["missing-chunk"]);
        raw["reviews"]["missing-review"] = json!({"status": "reviewed"});
        let doc = DiffgrDocument::from_value(raw).unwrap();
        assert!(doc
            .warnings
            .iter()
            .any(|w| w.contains("Assignment key not in groups")));
        assert!(doc
            .warnings
            .iter()
            .any(|w| w.contains("Assigned chunk id not found")));
        assert!(doc
            .warnings
            .iter()
            .any(|w| w.contains("Review key chunk id not found")));
    }

    #[test]
    fn validation_rejects_invalid_root_shape() {
        assert!(DiffgrDocument::from_value(json!([])).is_err());
        assert!(DiffgrDocument::from_value(json!({
            "format": "other",
            "version": 1,
            "meta": {},
            "groups": [],
            "chunks": [],
            "assignments": {},
            "reviews": {}
        }))
        .is_err());
        assert!(DiffgrDocument::from_value(json!({
            "format": "diffgr",
            "version": 99,
            "meta": {},
            "groups": [],
            "chunks": [],
            "assignments": {},
            "reviews": {}
        }))
        .is_err());
    }

    #[test]
    fn write_state_and_full_document_create_parent_dirs_and_backup() {
        let root = unique_temp_dir("write");
        let doc_path = root.join("nested").join("sample.diffgr.json");
        let state_path = root.join("nested").join("state").join("review.state.json");
        let mut doc = DiffgrDocument::from_value(minimal_doc()).unwrap();
        doc.set_status("c1", ReviewStatus::Reviewed);

        doc.write_full_document(&doc_path, false).unwrap();
        assert!(doc_path.exists());
        doc.set_comment("c1", "after backup");
        doc.write_full_document(&doc_path, true).unwrap();
        assert!(doc_path.with_extension("json.bak").exists());

        doc.write_state(&state_path).unwrap();
        let state_text = fs::read_to_string(&state_path).unwrap();
        let state_json: Value = serde_json::from_str(&state_text).unwrap();
        assert_eq!(state_json["reviews"]["c1"]["status"], json!("reviewed"));

        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn review_status_and_anchor_helpers_are_stable() {
        assert_eq!(ReviewStatus::from_str("reviewed"), ReviewStatus::Reviewed);
        assert_eq!(ReviewStatus::from_str("ignored"), ReviewStatus::Ignored);
        assert_eq!(
            ReviewStatus::from_str("needsReReview"),
            ReviewStatus::NeedsReReview
        );
        assert_eq!(ReviewStatus::from_str("unknown"), ReviewStatus::Unreviewed);
        assert_eq!(
            ReviewStatus::Reviewed.next_review_toggle(),
            ReviewStatus::Unreviewed
        );
        assert_eq!(
            ReviewStatus::Unreviewed.next_review_toggle(),
            ReviewStatus::Reviewed
        );
        assert!(!ReviewStatus::Ignored.is_tracked());

        let anchor = LineAnchor {
            line_type: "add".to_owned(),
            old_line: None,
            new_line: Some(42),
        };
        assert_eq!(anchor.key(), "add::42");
        assert_eq!(anchor.label(), "add old:- new:42");
    }
}
