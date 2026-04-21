use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::Write;
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
        self.id.chars().take(7).collect()
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

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StatusCounts {
    pub unreviewed: usize,
    pub reviewed: usize,
    pub needs_re_review: usize,
    pub ignored: usize,
}

impl StatusCounts {
    pub fn total(&self) -> usize {
        self.unreviewed + self.reviewed + self.needs_re_review + self.ignored
    }

    pub fn pending(&self) -> usize {
        self.unreviewed + self.needs_re_review
    }

    pub fn tracked(&self) -> usize {
        self.unreviewed + self.reviewed + self.needs_re_review
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FileSummary {
    pub file_path: String,
    pub chunks: usize,
    pub reviewed: usize,
    pub pending: usize,
    pub ignored: usize,
    pub adds: usize,
    pub deletes: usize,
    pub comments: usize,
}

impl FileSummary {
    pub fn tracked(&self) -> usize {
        self.chunks.saturating_sub(self.ignored)
    }

    pub fn coverage_rate(&self) -> f32 {
        let tracked = self.tracked();
        if tracked == 0 {
            1.0
        } else {
            self.reviewed as f32 / tracked as f32
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CoverageIssue {
    pub unassigned: Vec<String>,
    pub duplicated: BTreeMap<String, Vec<String>>,
    pub unknown_groups: Vec<String>,
    pub unknown_chunks: BTreeMap<String, Vec<String>>,
}

impl CoverageIssue {
    pub fn ok(&self) -> bool {
        self.unassigned.is_empty()
            && self.duplicated.is_empty()
            && self.unknown_groups.is_empty()
            && self.unknown_chunks.is_empty()
    }

    pub fn problem_count(&self) -> usize {
        self.unassigned.len()
            + self.duplicated.len()
            + self.unknown_groups.len()
            + self.unknown_chunks.len()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateSectionDiff {
    pub section: String,
    pub added: Vec<String>,
    pub removed: Vec<String>,
    pub changed: Vec<String>,
    pub unchanged: usize,
}

impl StateSectionDiff {
    pub fn changed_total(&self) -> usize {
        self.added.len() + self.removed.len() + self.changed.len()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateDiffReport {
    pub sections: Vec<StateSectionDiff>,
}

impl StateDiffReport {
    pub fn changed_total(&self) -> usize {
        self.sections
            .iter()
            .map(StateSectionDiff::changed_total)
            .sum()
    }

    pub fn section(&self, section: &str) -> Option<&StateSectionDiff> {
        self.sections.iter().find(|item| item.section == section)
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StateMergePreview {
    pub merged_state: Value,
    pub diff: StateDiffReport,
    pub warnings: Vec<String>,
    pub applied_reviews: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ImpactGroupReport {
    pub id: String,
    pub name: String,
    pub total_new: usize,
    pub unchanged: usize,
    pub changed: usize,
    pub new_chunks: usize,
    pub action: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ImpactReport {
    pub old_title: String,
    pub new_title: String,
    pub old_chunk_count: usize,
    pub new_chunk_count: usize,
    pub unchanged: usize,
    pub changed: usize,
    pub new_only: usize,
    pub old_only: usize,
    pub groups: Vec<ImpactGroupReport>,
    pub warnings: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ApprovalGroupStatus {
    pub group_id: String,
    pub group_name: String,
    pub approved: bool,
    pub valid: bool,
    pub reason: String,
    pub reviewed_count: usize,
    pub total_count: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ApprovalReport {
    pub all_approved: bool,
    pub groups: Vec<ApprovalGroupStatus>,
    pub warnings: Vec<String>,
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

    pub fn refresh_layout_metadata(&mut self) {
        self.groups = parse_groups(&self.raw);
        self.assignments = parse_assignments(&self.raw);
        self.warnings = validate_references(&self.raw);
        self.chunk_index.clear();
        for (index, chunk) in self.chunks.iter().enumerate() {
            self.chunk_index.insert(chunk.id.clone(), index);
        }
    }

    pub fn unassigned_chunk_ids(&self) -> Vec<String> {
        let assigned: BTreeSet<String> = self
            .assignments
            .values()
            .flat_map(|items| items.iter().cloned())
            .collect();
        self.chunks
            .iter()
            .filter(|chunk| !assigned.contains(&chunk.id))
            .map(|chunk| chunk.id.clone())
            .collect()
    }

    pub fn group_ids_for_chunk(&self, chunk_id: &str) -> Vec<String> {
        self.assignments
            .iter()
            .filter_map(|(group_id, chunk_ids)| {
                chunk_ids
                    .iter()
                    .any(|candidate| candidate == chunk_id)
                    .then(|| group_id.clone())
            })
            .collect()
    }

    pub fn primary_group_for_chunk(&self, chunk_id: &str) -> Option<String> {
        self.group_ids_for_chunk(chunk_id).into_iter().next()
    }

    pub fn create_group(
        &mut self,
        group_id: &str,
        name: &str,
        tags: &[String],
    ) -> Result<(), String> {
        let group_id = group_id.trim();
        if group_id.is_empty() {
            return Err("Group id is required.".to_owned());
        }
        if self.group_by_id(group_id).is_some() {
            return Err(format!("Group already exists: {group_id}"));
        }
        let name = name.trim();
        let order = self
            .groups
            .iter()
            .map(|group| group.order)
            .max()
            .unwrap_or(0)
            + 1;
        let tag_values: Vec<Value> = tags
            .iter()
            .map(|tag| tag.trim())
            .filter(|tag| !tag.is_empty())
            .map(|tag| Value::String(tag.to_owned()))
            .collect();

        let mut group = Map::new();
        group.insert("id".to_owned(), Value::String(group_id.to_owned()));
        group.insert(
            "name".to_owned(),
            Value::String(if name.is_empty() { group_id } else { name }.to_owned()),
        );
        group.insert("order".to_owned(), Value::Number(order.into()));
        if !tag_values.is_empty() {
            group.insert("tags".to_owned(), Value::Array(tag_values));
        }

        let root = self.raw.as_object_mut().expect("validated object");
        if let Some(groups) = root.get_mut("groups").and_then(Value::as_array_mut) {
            groups.push(Value::Object(group));
        } else {
            root.insert(
                "groups".to_owned(),
                Value::Array(vec![Value::Object(group)]),
            );
        }
        let assignments = ensure_object_field(root, "assignments");
        assignments.insert(group_id.to_owned(), Value::Array(Vec::new()));
        self.refresh_layout_metadata();
        Ok(())
    }

    pub fn rename_group(
        &mut self,
        group_id: &str,
        name: &str,
        tags: &[String],
    ) -> Result<(), String> {
        let group_id = group_id.trim();
        let mut found = false;
        let tag_values: Vec<Value> = tags
            .iter()
            .map(|tag| tag.trim())
            .filter(|tag| !tag.is_empty())
            .map(|tag| Value::String(tag.to_owned()))
            .collect();
        if let Some(groups) = self.raw.get_mut("groups").and_then(Value::as_array_mut) {
            for group in groups {
                let Some(obj) = group.as_object_mut() else {
                    continue;
                };
                if !obj
                    .get("id")
                    .map(|id| value_to_string(id) == group_id)
                    .unwrap_or(false)
                {
                    continue;
                }
                found = true;
                let normalized_name = name.trim();
                if !normalized_name.is_empty() {
                    obj.insert("name".to_owned(), Value::String(normalized_name.to_owned()));
                }
                if tag_values.is_empty() {
                    obj.remove("tags");
                } else {
                    obj.insert("tags".to_owned(), Value::Array(tag_values.clone()));
                }
                break;
            }
        }
        if !found {
            return Err(format!("Group not found: {group_id}"));
        }
        self.refresh_layout_metadata();
        Ok(())
    }

    pub fn delete_group_keep_chunks_unassigned(&mut self, group_id: &str) -> Result<(), String> {
        let group_id = group_id.trim();
        if self.group_by_id(group_id).is_none() {
            return Err(format!("Group not found: {group_id}"));
        }
        if let Some(groups) = self.raw.get_mut("groups").and_then(Value::as_array_mut) {
            groups.retain(|group| {
                group
                    .as_object()
                    .and_then(|obj| obj.get("id"))
                    .map(value_to_string)
                    .map(|id| id != group_id)
                    .unwrap_or(true)
            });
        }
        if let Some(assignments) = self
            .raw
            .get_mut("assignments")
            .and_then(Value::as_object_mut)
        {
            assignments.remove(group_id);
        }
        if let Some(group_briefs) = self
            .raw
            .get_mut("groupBriefs")
            .and_then(Value::as_object_mut)
        {
            group_briefs.remove(group_id);
            if group_briefs.is_empty() {
                if let Some(root) = self.raw.as_object_mut() {
                    root.remove("groupBriefs");
                }
            }
        }
        self.refresh_layout_metadata();
        Ok(())
    }

    pub fn assign_chunk_to_group(&mut self, chunk_id: &str, group_id: &str) -> Result<(), String> {
        let chunk_id = chunk_id.trim();
        let group_id = group_id.trim();
        if self.chunk_by_id(chunk_id).is_none() {
            return Err(format!("Chunk not found: {chunk_id}"));
        }
        if self.group_by_id(group_id).is_none() {
            return Err(format!("Group not found: {group_id}"));
        }
        let root = self.raw.as_object_mut().expect("validated object");
        let assignments = ensure_object_field(root, "assignments");
        for value in assignments.values_mut() {
            if let Some(items) = value.as_array_mut() {
                items.retain(|candidate| value_to_string(candidate) != chunk_id);
            }
        }
        let target = assignments
            .entry(group_id.to_owned())
            .or_insert_with(|| Value::Array(Vec::new()));
        if !target.is_array() {
            *target = Value::Array(Vec::new());
        }
        let items = target.as_array_mut().expect("target assignment array");
        if !items
            .iter()
            .any(|candidate| value_to_string(candidate) == chunk_id)
        {
            items.push(Value::String(chunk_id.to_owned()));
        }
        self.refresh_layout_metadata();
        Ok(())
    }

    pub fn unassign_chunk(&mut self, chunk_id: &str) -> Result<(), String> {
        let chunk_id = chunk_id.trim();
        if self.chunk_by_id(chunk_id).is_none() {
            return Err(format!("Chunk not found: {chunk_id}"));
        }
        if let Some(assignments) = self
            .raw
            .get_mut("assignments")
            .and_then(Value::as_object_mut)
        {
            for value in assignments.values_mut() {
                if let Some(items) = value.as_array_mut() {
                    items.retain(|candidate| value_to_string(candidate) != chunk_id);
                }
            }
        }
        self.refresh_layout_metadata();
        Ok(())
    }

    pub fn apply_layout_patch_value(&mut self, patch: &Value) -> Result<usize, String> {
        let obj = patch
            .as_object()
            .ok_or_else(|| "Layout patch must be a JSON object.".to_owned())?;
        let mut applied = 0usize;
        if let Some(rename) = obj.get("rename").and_then(Value::as_object) {
            for (group_id, value) in rename {
                let new_name = value_to_string(value);
                let tags = self
                    .group_by_id(group_id)
                    .map(|group| group.tags.clone())
                    .unwrap_or_default();
                self.rename_group(group_id, &new_name, &tags)?;
                applied += 1;
            }
        }
        if let Some(moves) = obj.get("move").and_then(Value::as_array) {
            for item in moves {
                let Some(move_obj) = item.as_object() else {
                    continue;
                };
                let chunk = move_obj
                    .get("chunk")
                    .map(value_to_string)
                    .unwrap_or_default();
                let to = move_obj.get("to").map(value_to_string).unwrap_or_default();
                if chunk.trim().is_empty() || to.trim().is_empty() {
                    continue;
                }
                self.assign_chunk_to_group(&chunk, &to)?;
                applied += 1;
            }
        }
        Ok(applied)
    }

    pub fn analyze_coverage(&self) -> CoverageIssue {
        let group_ids: BTreeSet<String> =
            self.groups.iter().map(|group| group.id.clone()).collect();
        let chunk_ids: BTreeSet<String> =
            self.chunks.iter().map(|chunk| chunk.id.clone()).collect();
        let mut unknown_groups = Vec::new();
        let mut unknown_chunks: BTreeMap<String, Vec<String>> = BTreeMap::new();
        let mut assigned_by_chunk: BTreeMap<String, Vec<String>> = BTreeMap::new();

        for (group_id, assigned) in &self.assignments {
            if !group_ids.contains(group_id) {
                unknown_groups.push(group_id.clone());
            }
            for chunk_id in assigned {
                if !chunk_ids.contains(chunk_id) {
                    unknown_chunks
                        .entry(chunk_id.clone())
                        .or_default()
                        .push(group_id.clone());
                    continue;
                }
                assigned_by_chunk
                    .entry(chunk_id.clone())
                    .or_default()
                    .push(group_id.clone());
            }
        }

        unknown_groups.sort();
        unknown_groups.dedup();
        for groups in unknown_chunks.values_mut() {
            groups.sort();
            groups.dedup();
        }

        let assigned_known: BTreeSet<String> = assigned_by_chunk.keys().cloned().collect();
        let unassigned = chunk_ids.difference(&assigned_known).cloned().collect();

        let duplicated = assigned_by_chunk
            .into_iter()
            .filter_map(|(chunk_id, mut groups)| {
                groups.sort();
                groups.dedup();
                (groups.len() > 1).then_some((chunk_id, groups))
            })
            .collect();

        CoverageIssue {
            unassigned,
            duplicated,
            unknown_groups,
            unknown_chunks,
        }
    }

    pub fn coverage_fix_prompt_markdown(&self) -> String {
        self.coverage_fix_prompt_markdown_limited(20, 80)
    }

    pub fn coverage_fix_prompt_markdown_limited(
        &self,
        max_chunks_per_group: usize,
        max_problem_chunks: usize,
    ) -> String {
        let issue = self.analyze_coverage();
        let mut out = String::new();
        out.push_str("# DiffGR 仮想PR網羅チェック: 修正依頼\n\n");
        out.push_str("目的: 全 chunk を既存 group のどれか1つにだけ割り当ててください。\n\n");
        out.push_str("出力フォーマットは JSON のみです。\n\n```json\n{ \"rename\": {}, \"move\": [ { \"chunk\": \"chunk_id\", \"to\": \"group_id\" } ] }\n```\n\n");
        out.push_str(&format!("- title: {}\n", self.title));
        out.push_str(&format!("- chunks: {}\n", self.chunks.len()));
        out.push_str(&format!("- groups: {}\n\n", self.groups.len()));
        out.push_str("## 問題\n\n");
        if issue.ok() {
            out.push_str("- (none) 既に網羅されています。\n\n");
        } else {
            if !issue.unassigned.is_empty() {
                out.push_str(&format!(
                    "### Unassigned chunks ({})\n\n",
                    issue.unassigned.len()
                ));
                for chunk_id in issue.unassigned.iter().take(max_problem_chunks) {
                    if let Some(chunk) = self.chunk_by_id(chunk_id) {
                        out.push_str(&format!(
                            "- {} | {} | {}\n",
                            chunk.id,
                            chunk.file_path,
                            chunk_change_preview(chunk, 6, true)
                        ));
                    }
                }
                out.push('\n');
            }
            if !issue.duplicated.is_empty() {
                out.push_str(&format!(
                    "### Duplicated assignments ({})\n\n",
                    issue.duplicated.len()
                ));
                for (chunk_id, groups) in issue.duplicated.iter().take(max_problem_chunks) {
                    if let Some(chunk) = self.chunk_by_id(chunk_id) {
                        out.push_str(&format!(
                            "- {} | groups={} | {} | {}\n",
                            chunk.id,
                            groups.join(","),
                            chunk.file_path,
                            chunk_change_preview(chunk, 6, true)
                        ));
                    }
                }
                out.push('\n');
            }
            if !issue.unknown_groups.is_empty() {
                out.push_str(&format!(
                    "### Unknown group ids ({})\n\n",
                    issue.unknown_groups.len()
                ));
                for group_id in issue.unknown_groups.iter().take(max_problem_chunks) {
                    out.push_str(&format!("- {}\n", group_id));
                }
                out.push('\n');
            }
            if !issue.unknown_chunks.is_empty() {
                out.push_str(&format!(
                    "### Unknown chunk ids ({})\n\n",
                    issue.unknown_chunks.len()
                ));
                for (chunk_id, groups) in issue.unknown_chunks.iter().take(max_problem_chunks) {
                    out.push_str(&format!(
                        "- {} | in groups={}\n",
                        chunk_id,
                        groups.join(",")
                    ));
                }
                out.push('\n');
            }
        }
        out.push_str("## 既存グループ一覧\n\n");
        for group in &self.groups {
            let assigned = self.assignments.get(&group.id).cloned().unwrap_or_default();
            out.push_str(&format!(
                "### {} / {} (chunks={})\n\n",
                group.id,
                group.name,
                assigned.len()
            ));
            for chunk_id in assigned.iter().take(max_chunks_per_group) {
                if let Some(chunk) = self.chunk_by_id(chunk_id) {
                    out.push_str(&format!(
                        "- {} | {} | {}\n",
                        chunk.id,
                        chunk.file_path,
                        chunk_change_preview(chunk, 6, true)
                    ));
                }
            }
            if assigned.len() > max_chunks_per_group {
                out.push_str(&format!(
                    "- ... ({} more)\n",
                    assigned.len() - max_chunks_per_group
                ));
            }
            out.push('\n');
        }
        out
    }

    pub fn state_diff_against_value(&self, other_state: Value) -> Result<StateDiffReport, String> {
        diff_state_values(&self.extract_state(), &other_state)
    }

    pub fn merge_state_value(
        &self,
        incoming_state: Value,
        source_name: &str,
    ) -> Result<StateMergePreview, String> {
        merge_state_values(&self.extract_state(), incoming_state, source_name)
    }

    pub fn apply_merged_state_preview(&mut self, preview: StateMergePreview) -> Result<(), String> {
        self.apply_state_value(preview.merged_state)
    }

    pub fn split_group_review_document(&self, group_id: &str) -> Result<Value, String> {
        let group = self
            .group_by_id(group_id)
            .ok_or_else(|| format!("Group not found: {group_id}"))?;
        let assigned = self.assignments.get(group_id).cloned().unwrap_or_default();
        let chunks: Vec<Value> = assigned
            .iter()
            .filter_map(|chunk_id| raw_chunk_by_id(&self.raw, chunk_id).cloned())
            .collect();

        let mut reviews = Map::new();
        for chunk_id in &assigned {
            if let Some(record) = self
                .raw
                .get("reviews")
                .and_then(Value::as_object)
                .and_then(|reviews| reviews.get(chunk_id))
                .cloned()
            {
                reviews.insert(chunk_id.clone(), record);
            }
        }

        let mut group_briefs = Map::new();
        if let Some(brief) = self
            .raw
            .get("groupBriefs")
            .and_then(Value::as_object)
            .and_then(|briefs| briefs.get(group_id))
            .cloned()
        {
            group_briefs.insert(group_id.to_owned(), brief);
        }

        let mut meta = self
            .raw
            .get("meta")
            .cloned()
            .unwrap_or_else(|| Value::Object(Map::new()));
        if let Some(meta_obj) = meta.as_object_mut() {
            let source_title = meta_obj
                .get("title")
                .map(value_to_string)
                .unwrap_or_else(|| "DiffGR".to_owned());
            meta_obj.insert(
                "title".to_owned(),
                Value::String(format!("{} [{}]", source_title, group.name)),
            );
            meta_obj.insert(
                "x-reviewSplit".to_owned(),
                json!({
                    "groupId": group.id.clone(),
                    "groupName": group.name.clone(),
                    "chunkCount": chunks.len(),
                }),
            );
        }

        let group_value = raw_group_by_id(&self.raw, group_id)
            .cloned()
            .unwrap_or_else(|| {
                json!({
                    "id": group.id.clone(),
                    "name": group.name.clone(),
                    "order": group.order,
                })
            });
        let mut assignments = Map::new();
        assignments.insert(group_id.to_owned(), json!(assigned));
        let mut analysis_state = Map::new();
        analysis_state.insert(
            "currentGroupId".to_owned(),
            Value::String(group_id.to_owned()),
        );

        Ok(json!({
            "format": "diffgr",
            "version": 1,
            "meta": meta,
            "groups": [group_value],
            "chunks": chunks,
            "assignments": assignments,
            "reviews": reviews,
            "groupBriefs": group_briefs,
            "analysisState": analysis_state,
            "threadState": {},
        }))
    }

    pub fn write_group_review_document(&self, group_id: &str, path: &Path) -> Result<(), String> {
        write_json(path, &self.split_group_review_document(group_id)?)
    }

    pub fn impact_against(&self, older: &DiffgrDocument) -> ImpactReport {
        build_impact_report(older, self)
    }

    pub fn review_html_report(&self) -> String {
        build_html_report(self)
    }

    pub fn write_html_report(&self, path: &Path) -> Result<(), String> {
        write_text(path, &self.review_html_report())
    }

    fn reviewed_count_for_group(&self, group_id: &str) -> (usize, usize) {
        let chunk_ids = self.assignments.get(group_id).cloned().unwrap_or_default();
        let total = chunk_ids.len();
        let reviewed = chunk_ids
            .iter()
            .filter(|chunk_id| {
                matches!(
                    self.status_for(chunk_id),
                    ReviewStatus::Reviewed | ReviewStatus::Ignored
                )
            })
            .count();
        (reviewed, total)
    }

    pub fn compute_group_approval_fingerprint(&self, group_id: &str) -> String {
        compute_group_approval_fingerprint(&self.raw, group_id)
    }

    pub fn approve_group(
        &mut self,
        group_id: &str,
        approved_by: &str,
        force: bool,
    ) -> Result<(), String> {
        let chunk_ids = self
            .assignments
            .get(group_id)
            .cloned()
            .ok_or_else(|| format!("Group not found or has no assignments: {group_id}"))?;
        if !force {
            if chunk_ids.is_empty() {
                return Err(format!("Group {group_id} has no assigned chunks."));
            }
            let unreviewed: Vec<String> = chunk_ids
                .iter()
                .filter(|chunk_id| {
                    !matches!(
                        self.status_for(chunk_id),
                        ReviewStatus::Reviewed | ReviewStatus::Ignored
                    )
                })
                .cloned()
                .collect();
            if !unreviewed.is_empty() {
                return Err(format!(
                    "Group {group_id} has {} unreviewed chunk(s): {}",
                    unreviewed.len(),
                    unreviewed
                        .iter()
                        .take(5)
                        .cloned()
                        .collect::<Vec<_>>()
                        .join(", ")
                ));
            }
        }

        let (reviewed_count, total_count) = self.reviewed_count_for_group(group_id);
        let fingerprint = self.compute_group_approval_fingerprint(group_id);
        let source_head = current_head_sha(&self.raw);
        let now = decision_timestamp();
        let approved_by = approved_by.trim();
        let approved_by = if approved_by.is_empty() {
            "reviewer"
        } else {
            approved_by
        };

        let brief = group_brief_object_mut(&mut self.raw, group_id)?;
        brief.insert(
            "approval".to_owned(),
            json!({
                "state": "approved",
                "approved": true,
                "approvedAt": now,
                "approvedBy": approved_by,
                "approvalFingerprint": fingerprint,
                "sourceHead": source_head,
                "decisionAt": now,
                "reviewedCount": reviewed_count,
                "totalCount": total_count,
            }),
        );
        Ok(())
    }

    pub fn request_changes_on_group(
        &mut self,
        group_id: &str,
        requested_by: &str,
        comment: &str,
    ) -> Result<(), String> {
        let now = decision_timestamp();
        let requested_by = requested_by.trim();
        let requested_by = if requested_by.is_empty() {
            "reviewer"
        } else {
            requested_by
        };
        let brief = group_brief_object_mut(&mut self.raw, group_id)?;
        let mut record = brief
            .get("approval")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        record.insert(
            "state".to_owned(),
            Value::String("changesRequested".to_owned()),
        );
        record.insert("approved".to_owned(), Value::Bool(false));
        record.insert("changesRequestedAt".to_owned(), Value::String(now.clone()));
        record.insert(
            "changesRequestedBy".to_owned(),
            Value::String(requested_by.to_owned()),
        );
        record.insert("decisionAt".to_owned(), Value::String(now));
        let comment = comment.trim();
        if comment.is_empty() {
            record.remove("comment");
        } else {
            record.insert("comment".to_owned(), Value::String(comment.to_owned()));
        }
        brief.insert("approval".to_owned(), Value::Object(record));
        Ok(())
    }

    pub fn revoke_group_approval(
        &mut self,
        group_id: &str,
        revoked_by: &str,
        reason: &str,
    ) -> Result<(), String> {
        let now = decision_timestamp();
        let revoked_by = revoked_by.trim();
        let revoked_by = if revoked_by.is_empty() {
            "reviewer"
        } else {
            revoked_by
        };
        let reason = reason.trim();
        let reason = if reason.is_empty() { "revoked" } else { reason };
        let brief = group_brief_object_mut(&mut self.raw, group_id)?;
        let mut record = brief
            .get("approval")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        record.insert("state".to_owned(), Value::String("revoked".to_owned()));
        record.insert("approved".to_owned(), Value::Bool(false));
        record.insert("revokedAt".to_owned(), Value::String(now.clone()));
        record.insert("revokedBy".to_owned(), Value::String(revoked_by.to_owned()));
        record.insert("decisionAt".to_owned(), Value::String(now));
        record.insert(
            "invalidationReason".to_owned(),
            Value::String(reason.to_owned()),
        );
        brief.insert("approval".to_owned(), Value::Object(record));
        Ok(())
    }

    pub fn check_group_approval(&self, group_id: &str) -> ApprovalGroupStatus {
        check_group_approval(self, group_id)
    }

    pub fn check_all_approvals(&self) -> ApprovalReport {
        let mut groups = Vec::new();
        for group in &self.groups {
            if group.id.trim().is_empty() {
                continue;
            }
            groups.push(self.check_group_approval(&group.id));
        }
        let all_approved =
            !groups.is_empty() && groups.iter().all(|status| status.approved && status.valid);
        ApprovalReport {
            all_approved,
            groups,
            warnings: Vec::new(),
        }
    }

    pub fn approval_report_json_value(&self) -> Value {
        let report = self.check_all_approvals();
        json!({
            "allApproved": report.all_approved,
            "groups": report.groups.iter().map(|status| json!({
                "groupId": status.group_id.clone(),
                "groupName": status.group_name.clone(),
                "approved": status.approved,
                "valid": status.valid,
                "reason": status.reason.clone(),
                "reviewedCount": status.reviewed_count,
                "totalCount": status.total_count,
            })).collect::<Vec<_>>(),
            "warnings": report.warnings,
        })
    }

    pub fn approval_report_markdown(&self) -> String {
        let report = self.check_all_approvals();
        let mut out = String::new();
        out.push_str("# DiffGR Approval Report\n\n");
        out.push_str(&format!("- all approved: {}\n", report.all_approved));
        out.push_str(&format!("- groups: {}\n\n", report.groups.len()));
        out.push_str("| Group | Approved | Valid | Reason | Reviewed |\n");
        out.push_str("|---|---:|---:|---|---:|\n");
        for status in report.groups {
            out.push_str(&format!(
                "| {} ({}) | {} | {} | {} | {}/{} |\n",
                status.group_name,
                status.group_id,
                status.approved,
                status.valid,
                status.reason,
                status.reviewed_count,
                status.total_count
            ));
        }
        out
    }

    pub fn write_approval_report_json(&self, path: &Path) -> Result<(), String> {
        write_json(path, &self.approval_report_json_value())
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

    pub fn status_counts(&self) -> StatusCounts {
        let mut counts = StatusCounts::default();
        for chunk in &self.chunks {
            match self.status_for(&chunk.id) {
                ReviewStatus::Unreviewed => counts.unreviewed += 1,
                ReviewStatus::Reviewed => counts.reviewed += 1,
                ReviewStatus::NeedsReReview => counts.needs_re_review += 1,
                ReviewStatus::Ignored => counts.ignored += 1,
            }
        }
        counts
    }

    pub fn file_summaries(&self) -> Vec<FileSummary> {
        let mut by_file: BTreeMap<String, FileSummary> = BTreeMap::new();
        for chunk in &self.chunks {
            let entry = by_file
                .entry(chunk.file_path.clone())
                .or_insert_with(|| FileSummary {
                    file_path: chunk.file_path.clone(),
                    ..FileSummary::default()
                });
            entry.chunks += 1;
            entry.adds += chunk.add_count;
            entry.deletes += chunk.delete_count;
            entry.comments += usize::from(!self.comment_for(&chunk.id).trim().is_empty());
            entry.comments += self.line_comment_count_for(&chunk.id);
            match self.status_for(&chunk.id) {
                ReviewStatus::Unreviewed | ReviewStatus::NeedsReReview => entry.pending += 1,
                ReviewStatus::Reviewed => entry.reviewed += 1,
                ReviewStatus::Ignored => entry.ignored += 1,
            }
        }
        let mut rows: Vec<FileSummary> = by_file.into_values().collect();
        rows.sort_by(|left, right| {
            right
                .pending
                .cmp(&left.pending)
                .then_with(|| (right.adds + right.deletes).cmp(&(left.adds + left.deletes)))
                .then_with(|| left.file_path.cmp(&right.file_path))
        });
        rows
    }

    pub fn set_status_for_chunks(&mut self, chunk_ids: &[String], status: ReviewStatus) -> usize {
        let known: BTreeSet<String> = self.chunks.iter().map(|chunk| chunk.id.clone()).collect();
        let mut changed = 0;
        for chunk_id in chunk_ids {
            if !known.contains(chunk_id) || self.status_for(chunk_id) == status {
                continue;
            }
            self.set_status(chunk_id, status);
            changed += 1;
        }
        changed
    }

    pub fn review_markdown_report(&self) -> String {
        let counts = self.status_counts();
        let metrics = self.metrics();
        let mut out = String::new();
        out.push_str(&format!("# DiffGR Review Summary: {}\n\n", self.title));
        out.push_str("## Status\n\n");
        out.push_str(&format!("- Total chunks: {}\n", counts.total()));
        out.push_str(&format!("- Reviewed: {}\n", counts.reviewed));
        out.push_str(&format!("- Unreviewed: {}\n", counts.unreviewed));
        out.push_str(&format!("- Needs re-review: {}\n", counts.needs_re_review));
        out.push_str(&format!("- Ignored: {}\n", counts.ignored));
        out.push_str(&format!(
            "- Coverage: {:.1}% ({}/{})\n\n",
            metrics.coverage_rate * 100.0,
            metrics.reviewed,
            metrics.tracked
        ));

        if !self.warnings.is_empty() {
            out.push_str("## Warnings\n\n");
            for warning in &self.warnings {
                out.push_str(&format!("- {}\n", escape_markdown_line(warning)));
            }
            out.push('\n');
        }

        out.push_str("## Files\n\n");
        out.push_str("| File | Chunks | Reviewed | Pending | Ignored | +/- | Comments |\n");
        out.push_str("|---|---:|---:|---:|---:|---:|---:|\n");
        for file in self.file_summaries() {
            out.push_str(&format!(
                "| {} | {} | {} | {} | {} | +{} / -{} | {} |\n",
                escape_markdown_cell(&file.file_path),
                file.chunks,
                file.reviewed,
                file.pending,
                file.ignored,
                file.adds,
                file.deletes,
                file.comments
            ));
        }
        out.push('\n');

        let mut noted = 0usize;
        for chunk in &self.chunks {
            let chunk_comment = self.comment_for(&chunk.id);
            let line_comments = self.line_comments_for_report(&chunk.id);
            if chunk_comment.trim().is_empty() && line_comments.is_empty() {
                continue;
            }
            if noted == 0 {
                out.push_str("## Comments\n\n");
            }
            noted += 1;
            out.push_str(&format!(
                "### {} ({})\n\n",
                escape_markdown_line(&chunk.file_path),
                chunk.short_id()
            ));
            out.push_str(&format!(
                "Status: `{}`\n\n",
                self.status_for(&chunk.id).as_str()
            ));
            if !chunk_comment.trim().is_empty() {
                out.push_str(&format!(
                    "- Chunk: {}\n",
                    escape_markdown_line(&chunk_comment)
                ));
            }
            for (anchor, comment) in line_comments {
                out.push_str(&format!(
                    "- Line {}: {}\n",
                    escape_markdown_line(&anchor.label()),
                    escape_markdown_line(&comment)
                ));
            }
            out.push('\n');
        }
        if noted == 0 {
            out.push_str("## Comments\n\nNo comments yet.\n");
        }
        out
    }

    pub fn write_review_report(&self, path: &Path) -> Result<(), String> {
        write_text(path, &self.review_markdown_report())
    }

    fn line_comments_for_report(&self, chunk_id: &str) -> Vec<(LineAnchor, String)> {
        self.raw
            .get("reviews")
            .and_then(Value::as_object)
            .and_then(|reviews| reviews.get(chunk_id))
            .and_then(Value::as_object)
            .and_then(|record| record.get("lineComments"))
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|item| {
                let obj = item.as_object()?;
                let comment = obj.get("comment").map(value_to_string).unwrap_or_default();
                if comment.trim().is_empty() {
                    return None;
                }
                Some((
                    LineAnchor {
                        line_type: obj
                            .get("lineType")
                            .map(value_to_string)
                            .filter(|value| !value.is_empty())
                            .unwrap_or_else(|| "context".to_owned()),
                        old_line: obj.get("oldLine").and_then(value_to_i64),
                        new_line: obj.get("newLine").and_then(value_to_i64),
                    },
                    comment.trim().to_owned(),
                ))
            })
            .collect()
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
                            .or_else(|| line_obj.get("type"))
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

fn group_brief_object_mut<'a>(
    raw: &'a mut Value,
    group_id: &str,
) -> Result<&'a mut Map<String, Value>, String> {
    if group_id.trim().is_empty() {
        return Err("group_id is empty".to_owned());
    }
    let root = raw
        .as_object_mut()
        .ok_or_else(|| "DiffGR document root must be an object".to_owned())?;
    let group_briefs = root
        .entry("groupBriefs".to_owned())
        .or_insert_with(|| Value::Object(Map::new()));
    if !group_briefs.is_object() {
        *group_briefs = Value::Object(Map::new());
    }
    let group_briefs = group_briefs
        .as_object_mut()
        .ok_or_else(|| "groupBriefs must be an object".to_owned())?;
    let brief = group_briefs
        .entry(group_id.to_owned())
        .or_insert_with(|| Value::Object(Map::new()));
    if !brief.is_object() {
        *brief = Value::Object(Map::new());
    }
    brief
        .as_object_mut()
        .ok_or_else(|| "group brief must be an object".to_owned())
}

fn current_head_sha(raw: &Value) -> String {
    raw.get("meta")
        .and_then(|meta| meta.get("source"))
        .and_then(Value::as_object)
        .and_then(|source| source.get("headSha").or_else(|| source.get("head")))
        .map(value_to_string)
        .unwrap_or_default()
}

fn decision_timestamp() -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_secs())
        .unwrap_or(0);
    format!("unix:{seconds}")
}

fn check_group_approval(doc: &DiffgrDocument, group_id: &str) -> ApprovalGroupStatus {
    let group_name = doc
        .group_by_id(group_id)
        .map(|group| group.name.clone())
        .unwrap_or_else(|| group_id.to_owned());
    let (reviewed_count, total_count) = doc.reviewed_count_for_group(group_id);
    let approval = doc
        .raw
        .get("groupBriefs")
        .and_then(Value::as_object)
        .and_then(|briefs| briefs.get(group_id))
        .and_then(Value::as_object)
        .and_then(|brief| brief.get("approval"))
        .and_then(Value::as_object);

    let Some(approval) = approval else {
        return ApprovalGroupStatus {
            group_id: group_id.to_owned(),
            group_name,
            approved: false,
            valid: false,
            reason: "not_approved".to_owned(),
            reviewed_count,
            total_count,
        };
    };

    let approved = approval
        .get("approved")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if !approved {
        return ApprovalGroupStatus {
            group_id: group_id.to_owned(),
            group_name,
            approved: false,
            valid: false,
            reason: invalidation_reason_from_approval(approval),
            reviewed_count,
            total_count,
        };
    }

    let saved_head = approval
        .get("sourceHead")
        .map(value_to_string)
        .unwrap_or_default();
    let current_head = current_head_sha(&doc.raw);
    if !saved_head.is_empty() && !current_head.is_empty() && saved_head != current_head {
        return ApprovalGroupStatus {
            group_id: group_id.to_owned(),
            group_name,
            approved: true,
            valid: false,
            reason: "invalidated_head".to_owned(),
            reviewed_count,
            total_count,
        };
    }

    let chunk_ids = doc.assignments.get(group_id).cloned().unwrap_or_default();
    if !chunk_ids.is_empty()
        && chunk_ids.iter().any(|chunk_id| {
            !matches!(
                doc.status_for(chunk_id),
                ReviewStatus::Reviewed | ReviewStatus::Ignored
            )
        })
    {
        return ApprovalGroupStatus {
            group_id: group_id.to_owned(),
            group_name,
            approved: true,
            valid: false,
            reason: "invalidated_review_state".to_owned(),
            reviewed_count,
            total_count,
        };
    }

    let saved_fp = approval
        .get("approvalFingerprint")
        .map(value_to_string)
        .unwrap_or_default();
    let current_fp = doc.compute_group_approval_fingerprint(group_id);
    if saved_fp != current_fp {
        return ApprovalGroupStatus {
            group_id: group_id.to_owned(),
            group_name,
            approved: true,
            valid: false,
            reason: "invalidated_fingerprint".to_owned(),
            reviewed_count,
            total_count,
        };
    }

    ApprovalGroupStatus {
        group_id: group_id.to_owned(),
        group_name,
        approved: true,
        valid: true,
        reason: "approved".to_owned(),
        reviewed_count,
        total_count,
    }
}

fn invalidation_reason_from_approval(approval: &Map<String, Value>) -> String {
    let state = approval
        .get("state")
        .map(value_to_string)
        .unwrap_or_default();
    match state.as_str() {
        "revoked" => "revoked".to_owned(),
        "changesRequested" => "changes_requested".to_owned(),
        "invalidated" => {
            let raw = approval
                .get("invalidationReason")
                .map(value_to_string)
                .unwrap_or_default();
            match raw.as_str() {
                "head_changed" => "invalidated_head".to_owned(),
                "review_state_changed" => "invalidated_review_state".to_owned(),
                "code_changed" => "invalidated_code_change".to_owned(),
                "fingerprint_changed" => "invalidated_fingerprint".to_owned(),
                value if !value.is_empty() => value.to_owned(),
                _ => "invalidated_record".to_owned(),
            }
        }
        _ => {
            let raw = approval
                .get("invalidationReason")
                .map(value_to_string)
                .unwrap_or_default();
            if raw.is_empty() {
                "not_approved".to_owned()
            } else {
                raw
            }
        }
    }
}

fn compute_group_approval_fingerprint(raw: &Value, group_id: &str) -> String {
    let chunk_by_id: BTreeMap<String, Value> = raw
        .get("chunks")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|chunk| {
            let id = chunk.get("id").map(value_to_string)?;
            if id.is_empty() {
                None
            } else {
                Some((id, chunk.clone()))
            }
        })
        .collect();
    let mut stable_fingerprints: Vec<String> = raw
        .get("assignments")
        .and_then(Value::as_object)
        .and_then(|assignments| assignments.get(group_id))
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|chunk_id| chunk_by_id.get(&value_to_string(chunk_id)))
        .map(stable_fingerprint_for_chunk)
        .collect();
    stable_fingerprints.sort();
    sha256_hex_value(&json!(stable_fingerprints))
}

fn stable_fingerprint_for_chunk(chunk: &Value) -> String {
    let lines = chunk
        .get("lines")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .map(|line| {
            json!({
                "kind": line.get("kind").cloned().unwrap_or(Value::Null),
                "text": line.get("text").cloned().unwrap_or(Value::Null),
            })
        })
        .collect::<Vec<_>>();
    sha256_hex_value(&json!({
        "filePath": chunk.get("filePath").map(value_to_string).unwrap_or_default(),
        "lines": lines,
    }))
}

fn sha256_hex_value(value: &Value) -> String {
    let payload = canonical_json_sorted(value);
    let mut hasher = Sha256::new();
    hasher.update(payload.as_bytes());
    let digest = hasher.finalize();
    digest.iter().map(|byte| format!("{:02x}", *byte)).collect()
}

fn canonical_json_sorted(value: &Value) -> String {
    match value {
        Value::Null => "null".to_owned(),
        Value::Bool(value) => {
            if *value {
                "true".to_owned()
            } else {
                "false".to_owned()
            }
        }
        Value::Number(value) => value.to_string(),
        Value::String(value) => serde_json::to_string(value).unwrap_or_else(|_| "\"\"".to_owned()),
        Value::Array(values) => {
            let inner = values
                .iter()
                .map(canonical_json_sorted)
                .collect::<Vec<_>>()
                .join(",");
            format!("[{inner}]")
        }
        Value::Object(map) => {
            let mut keys = map.keys().collect::<Vec<_>>();
            keys.sort();
            let inner = keys
                .into_iter()
                .map(|key| {
                    let encoded_key =
                        serde_json::to_string(key).unwrap_or_else(|_| "\"\"".to_owned());
                    let encoded_value = map
                        .get(key)
                        .map(canonical_json_sorted)
                        .unwrap_or_else(|| "null".to_owned());
                    format!("{encoded_key}:{encoded_value}")
                })
                .collect::<Vec<_>>()
                .join(",");
            format!("{{{inner}}}")
        }
    }
}

fn raw_group_by_id<'a>(raw: &'a Value, group_id: &str) -> Option<&'a Value> {
    raw.get("groups")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .find(|group| {
            group
                .as_object()
                .and_then(|obj| obj.get("id"))
                .map(|id| value_to_string(id) == group_id)
                .unwrap_or(false)
        })
}

fn raw_chunk_by_id<'a>(raw: &'a Value, chunk_id: &str) -> Option<&'a Value> {
    raw.get("chunks")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .find(|chunk| {
            chunk
                .as_object()
                .and_then(|obj| obj.get("id"))
                .map(|id| value_to_string(id) == chunk_id)
                .unwrap_or(false)
        })
}

fn chunk_change_preview(chunk: &Chunk, max_lines: usize, include_meta: bool) -> String {
    let mut lines = Vec::new();
    for line in chunk.lines.iter() {
        if include_meta {
            if line.kind.is_empty() || line.kind == "context" {
                continue;
            }
        } else if !matches!(line.kind.as_str(), "add" | "delete") {
            continue;
        }
        if matches!(line.kind.as_str(), "add" | "delete") && line.text.trim().is_empty() {
            continue;
        }
        lines.push(format!("{}: {}", line.kind, line.text));
        if lines.len() >= max_lines {
            break;
        }
    }
    if lines.is_empty() {
        if include_meta {
            "(meta-only)"
        } else {
            "(no add/delete lines)"
        }
        .to_owned()
    } else {
        lines.join(" / ")
    }
}

fn diff_state_values(base_state: &Value, other_state: &Value) -> Result<StateDiffReport, String> {
    let base = normalize_state_payload(base_state.clone())?;
    let other = normalize_state_payload(other_state.clone())?;
    let mut sections = Vec::new();
    for section in STATE_KEYS {
        let base_obj = base
            .get(section)
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let other_obj = other
            .get(section)
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let keys: BTreeSet<String> = base_obj.keys().chain(other_obj.keys()).cloned().collect();
        let mut diff = StateSectionDiff {
            section: section.to_owned(),
            ..StateSectionDiff::default()
        };
        for key in keys {
            match (base_obj.get(&key), other_obj.get(&key)) {
                (None, Some(_)) => diff.added.push(key),
                (Some(_), None) => diff.removed.push(key),
                (Some(left), Some(right)) if canonical_json(left) != canonical_json(right) => {
                    diff.changed.push(key)
                }
                (Some(_), Some(_)) => diff.unchanged += 1,
                (None, None) => {}
            }
        }
        sections.push(diff);
    }
    Ok(StateDiffReport { sections })
}

fn merge_state_values(
    base_state: &Value,
    incoming_state: Value,
    source_name: &str,
) -> Result<StateMergePreview, String> {
    let base = normalize_state_payload(base_state.clone())?;
    let incoming = normalize_state_payload(incoming_state)?;
    let mut merged = base.clone();
    let mut warnings = Vec::new();
    let mut applied_reviews = 0usize;

    merge_object_section(
        &mut merged,
        &incoming,
        "reviews",
        |key, base_record, incoming_record, warnings| {
            applied_reviews += 1;
            merge_review_record(base_record, incoming_record, source_name, key, warnings)
        },
        &mut warnings,
    );
    merge_object_section(
        &mut merged,
        &incoming,
        "groupBriefs",
        |key, base_record, incoming_record, warnings| {
            merge_group_brief_record(base_record, incoming_record, source_name, key, warnings)
        },
        &mut warnings,
    );
    merge_plain_object_section(&mut merged, &incoming, "analysisState");
    merge_thread_state_section(&mut merged, &incoming);

    let diff = diff_state_values(&base, &merged)?;
    Ok(StateMergePreview {
        merged_state: merged,
        diff,
        warnings,
        applied_reviews,
    })
}

fn merge_object_section<F>(
    merged: &mut Value,
    incoming: &Value,
    section: &str,
    mut merge_record: F,
    warnings: &mut Vec<String>,
) where
    F: FnMut(&str, &Map<String, Value>, &Map<String, Value>, &mut Vec<String>) -> Value,
{
    let Some(incoming_obj) = incoming.get(section).and_then(Value::as_object) else {
        return;
    };
    let root = merged.as_object_mut().expect("normalized state object");
    let target = ensure_object_field(root, section);
    for (key, incoming_record) in incoming_obj {
        let Some(incoming_record_obj) = incoming_record.as_object() else {
            warnings.push(format!("{} record must be object: {}", section, key));
            continue;
        };
        let base_empty = Map::new();
        let base_record = target
            .get(key)
            .and_then(Value::as_object)
            .unwrap_or(&base_empty);
        let merged_record = merge_record(key, base_record, incoming_record_obj, warnings);
        target.insert(key.clone(), merged_record);
    }
}

fn merge_plain_object_section(merged: &mut Value, incoming: &Value, section: &str) {
    let Some(incoming_obj) = incoming.get(section).and_then(Value::as_object) else {
        return;
    };
    let root = merged.as_object_mut().expect("normalized state object");
    let target = ensure_object_field(root, section);
    for (key, value) in incoming_obj {
        target.insert(key.clone(), value.clone());
    }
}

fn merge_thread_state_section(merged: &mut Value, incoming: &Value) {
    let Some(incoming_obj) = incoming.get("threadState").and_then(Value::as_object) else {
        return;
    };
    let root = merged.as_object_mut().expect("normalized state object");
    let target = ensure_object_field(root, "threadState");
    for (key, value) in incoming_obj {
        if key == "__files" {
            if let Some(incoming_files) = value.as_object() {
                let target_files = target
                    .entry("__files".to_owned())
                    .or_insert_with(|| Value::Object(Map::new()));
                if !target_files.is_object() {
                    *target_files = Value::Object(Map::new());
                }
                let files = target_files.as_object_mut().expect("files object");
                for (file_key, file_value) in incoming_files {
                    files.insert(file_key.clone(), file_value.clone());
                }
            }
        } else {
            target.insert(key.clone(), value.clone());
        }
    }
}

fn review_status_precedence(status: &str) -> i64 {
    match status {
        "ignored" => 1,
        "reviewed" => 2,
        "unreviewed" => 3,
        "needsReReview" => 4,
        _ => 0,
    }
}

fn group_brief_status_precedence(status: &str) -> i64 {
    match status {
        "draft" => 1,
        "acknowledged" => 2,
        "ready" => 3,
        "stale" => 4,
        _ => 0,
    }
}

fn merge_review_record(
    base_record: &Map<String, Value>,
    incoming_record: &Map<String, Value>,
    source_name: &str,
    chunk_id: &str,
    warnings: &mut Vec<String>,
) -> Value {
    let mut merged = base_record.clone();
    let base_status = base_record.get("status").map(value_to_string);
    let incoming_status = incoming_record.get("status").map(value_to_string);
    if let Some(incoming_status) =
        incoming_status.filter(|status| review_status_precedence(status) > 0)
    {
        let should_take = base_status
            .as_deref()
            .map(|status| {
                review_status_precedence(&incoming_status) >= review_status_precedence(status)
            })
            .unwrap_or(true);
        if should_take {
            merged.insert("status".to_owned(), Value::String(incoming_status.clone()));
        } else if base_status.as_deref() != Some(incoming_status.as_str()) {
            warnings.push(format!(
                "{}: status conflict on chunk {}; kept {}, ignored {}",
                source_name,
                chunk_id,
                base_status.unwrap_or_else(|| "-".to_owned()),
                incoming_status
            ));
        }
    }

    let base_comment = base_record
        .get("comment")
        .map(value_to_string)
        .unwrap_or_default()
        .trim()
        .to_owned();
    let incoming_comment = incoming_record
        .get("comment")
        .map(value_to_string)
        .unwrap_or_default()
        .trim()
        .to_owned();
    if !incoming_comment.is_empty() {
        if !base_comment.is_empty() && base_comment != incoming_comment {
            warnings.push(format!(
                "{}: chunk comment conflict on chunk {}; used incoming comment.",
                source_name, chunk_id
            ));
        }
        merged.insert("comment".to_owned(), Value::String(incoming_comment));
    } else if !base_comment.is_empty() {
        merged.insert("comment".to_owned(), Value::String(base_comment));
    } else {
        merged.remove("comment");
    }

    let mut combined = Vec::new();
    let mut seen = BTreeSet::new();
    for record in [base_record, incoming_record] {
        if let Some(items) = record.get("lineComments").and_then(Value::as_array) {
            for item in items {
                let Some(obj) = item.as_object() else {
                    continue;
                };
                let comment = obj
                    .get("comment")
                    .map(value_to_string)
                    .unwrap_or_default()
                    .trim()
                    .to_owned();
                if comment.is_empty() {
                    continue;
                }
                let mut normalized = obj.clone();
                normalized.insert("comment".to_owned(), Value::String(comment));
                let key = canonical_json(&Value::Object(normalized.clone()));
                if seen.insert(key) {
                    combined.push(Value::Object(normalized));
                }
            }
        }
    }
    if combined.is_empty() {
        merged.remove("lineComments");
    } else {
        merged.insert("lineComments".to_owned(), Value::Array(combined));
    }

    for (key, value) in incoming_record {
        if matches!(key.as_str(), "status" | "comment" | "lineComments") {
            continue;
        }
        merged.insert(key.clone(), value.clone());
    }
    Value::Object(merged)
}

fn merge_group_brief_record(
    base_record: &Map<String, Value>,
    incoming_record: &Map<String, Value>,
    source_name: &str,
    group_id: &str,
    warnings: &mut Vec<String>,
) -> Value {
    let mut merged = base_record.clone();
    if let Some(incoming_status) = incoming_record
        .get("status")
        .map(value_to_string)
        .filter(|status| group_brief_status_precedence(status) > 0)
    {
        let base_status = base_record.get("status").map(value_to_string);
        let should_take = base_status
            .as_deref()
            .map(|status| {
                group_brief_status_precedence(&incoming_status)
                    >= group_brief_status_precedence(status)
            })
            .unwrap_or(true);
        if should_take {
            merged.insert("status".to_owned(), Value::String(incoming_status));
        }
    }
    for key in ["summary", "updatedAt", "sourceHead"] {
        let base_value = base_record
            .get(key)
            .map(value_to_string)
            .unwrap_or_default()
            .trim()
            .to_owned();
        let incoming_value = incoming_record
            .get(key)
            .map(value_to_string)
            .unwrap_or_default()
            .trim()
            .to_owned();
        if !incoming_value.is_empty() {
            if key == "summary" && !base_value.is_empty() && base_value != incoming_value {
                warnings.push(format!(
                    "{}: group brief conflict on {}; used incoming {}.",
                    source_name, group_id, key
                ));
            }
            merged.insert(key.to_owned(), Value::String(incoming_value));
        } else if !base_value.is_empty() {
            merged.insert(key.to_owned(), Value::String(base_value));
        } else {
            merged.remove(key);
        }
    }
    for key in [
        "focusPoints",
        "testEvidence",
        "knownTradeoffs",
        "questionsForReviewer",
        "mentions",
    ] {
        let mut combined = Vec::new();
        let mut seen = BTreeSet::new();
        for record in [base_record, incoming_record] {
            if let Some(items) = record.get(key).and_then(Value::as_array) {
                for item in items {
                    let text = value_to_string(item).trim().to_owned();
                    if text.is_empty() || !seen.insert(text.clone()) {
                        continue;
                    }
                    combined.push(Value::String(text));
                }
            }
        }
        if combined.is_empty() {
            merged.remove(key);
        } else {
            merged.insert(key.to_owned(), Value::Array(combined));
        }
    }
    if let Some(approval) =
        merge_approval_record_values(base_record.get("approval"), incoming_record.get("approval"))
    {
        merged.insert("approval".to_owned(), approval);
    }

    for (key, value) in incoming_record {
        if matches!(
            key.as_str(),
            "status"
                | "summary"
                | "updatedAt"
                | "sourceHead"
                | "focusPoints"
                | "testEvidence"
                | "knownTradeoffs"
                | "questionsForReviewer"
                | "mentions"
                | "approval"
        ) {
            continue;
        }
        merged.insert(key.clone(), value.clone());
    }
    Value::Object(merged)
}

fn merge_approval_record_values(base: Option<&Value>, incoming: Option<&Value>) -> Option<Value> {
    let incoming = normalize_approval_record(incoming?)?;
    let Some(base) = base.and_then(normalize_approval_record) else {
        return Some(Value::Object(incoming));
    };

    let incoming_time = approval_decision_time(&incoming);
    let base_time = approval_decision_time(&base);
    if incoming_time > base_time {
        return Some(Value::Object(incoming));
    }
    if incoming_time < base_time {
        return None;
    }

    let incoming_state = approval_state(&incoming);
    let base_state = approval_state(&base);
    let incoming_precedence = approval_state_precedence(&incoming_state);
    let base_precedence = approval_state_precedence(&base_state);
    if incoming_precedence > base_precedence {
        return Some(Value::Object(incoming));
    }
    if incoming_precedence < base_precedence {
        return None;
    }

    let incoming_json = canonical_json(&Value::Object(incoming.clone()));
    let base_json = canonical_json(&Value::Object(base));
    (incoming_json >= base_json).then_some(Value::Object(incoming))
}

fn normalize_approval_record(value: &Value) -> Option<Map<String, Value>> {
    let mut record = value.as_object()?.clone();
    let state = approval_state(&record);
    record.insert("state".to_owned(), Value::String(state.clone()));
    record.insert("approved".to_owned(), Value::Bool(state == "approved"));
    let decision_at = approval_decision_time(&record);
    if !decision_at.is_empty() {
        record.insert("decisionAt".to_owned(), Value::String(decision_at));
    }
    Some(record)
}

fn approval_state(record: &Map<String, Value>) -> String {
    let state = record.get("state").map(value_to_string).unwrap_or_default();
    if matches!(
        state.as_str(),
        "approved" | "revoked" | "invalidated" | "changesRequested"
    ) {
        return state;
    }
    if record
        .get("approved")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return "approved".to_owned();
    }
    let reason = record
        .get("invalidationReason")
        .map(value_to_string)
        .unwrap_or_default();
    if reason == "revoked" || record.get("revokedAt").is_some() {
        "revoked".to_owned()
    } else {
        "invalidated".to_owned()
    }
}

fn approval_decision_time(record: &Map<String, Value>) -> String {
    for key in [
        "decisionAt",
        "revokedAt",
        "changesRequestedAt",
        "invalidatedAt",
        "approvedAt",
    ] {
        let value = record
            .get(key)
            .map(value_to_string)
            .unwrap_or_default()
            .trim()
            .to_owned();
        if !value.is_empty() {
            return value;
        }
    }
    String::new()
}

fn approval_state_precedence(state: &str) -> u8 {
    match state {
        "approved" => 1,
        "invalidated" | "changesRequested" => 2,
        "revoked" => 3,
        _ => 0,
    }
}

fn build_impact_report(old_doc: &DiffgrDocument, new_doc: &DiffgrDocument) -> ImpactReport {
    let mut warnings = Vec::new();
    let old_by_id: BTreeMap<String, String> = old_doc
        .chunks
        .iter()
        .map(|chunk| (chunk.id.clone(), stable_chunk_signature(chunk)))
        .collect();
    let new_by_id: BTreeMap<String, String> = new_doc
        .chunks
        .iter()
        .map(|chunk| (chunk.id.clone(), stable_chunk_signature(chunk)))
        .collect();
    let old_signatures: BTreeMap<String, Vec<String>> = signature_index(old_doc);

    let mut unchanged = 0usize;
    let mut changed = 0usize;
    let mut new_only = 0usize;
    for chunk in &new_doc.chunks {
        if let Some(old_sig) = old_by_id.get(&chunk.id) {
            if *old_sig == stable_chunk_signature(chunk) {
                unchanged += 1;
            } else {
                changed += 1;
            }
        } else {
            let signature = stable_chunk_signature(chunk);
            if old_signatures
                .get(&signature)
                .map(|ids| !ids.is_empty())
                .unwrap_or(false)
            {
                unchanged += 1;
            } else {
                new_only += 1;
            }
        }
    }
    let old_only = old_doc
        .chunks
        .iter()
        .filter(|chunk| !new_by_id.contains_key(&chunk.id))
        .count();

    if old_doc.title == new_doc.title && old_doc.chunks.len() != new_doc.chunks.len() {
        warnings.push(
            "Same title but chunk count differs; review impact may need attention.".to_owned(),
        );
    }

    let mut groups = Vec::new();
    for group in &new_doc.groups {
        let mut group_report = ImpactGroupReport {
            id: group.id.clone(),
            name: group.name.clone(),
            ..ImpactGroupReport::default()
        };
        let assigned = new_doc
            .assignments
            .get(&group.id)
            .cloned()
            .unwrap_or_default();
        group_report.total_new = assigned.len();
        for chunk_id in assigned {
            let Some(chunk) = new_doc.chunk_by_id(&chunk_id) else {
                continue;
            };
            if let Some(old_sig) = old_by_id.get(&chunk.id) {
                if *old_sig == stable_chunk_signature(chunk) {
                    group_report.unchanged += 1;
                } else {
                    group_report.changed += 1;
                }
            } else {
                let signature = stable_chunk_signature(chunk);
                if old_signatures
                    .get(&signature)
                    .map(|ids| !ids.is_empty())
                    .unwrap_or(false)
                {
                    group_report.unchanged += 1;
                } else {
                    group_report.new_chunks += 1;
                }
            }
        }
        group_report.action = if group_report.changed == 0 && group_report.new_chunks == 0 {
            "skip".to_owned()
        } else {
            "review".to_owned()
        };
        groups.push(group_report);
    }

    ImpactReport {
        old_title: old_doc.title.clone(),
        new_title: new_doc.title.clone(),
        old_chunk_count: old_doc.chunks.len(),
        new_chunk_count: new_doc.chunks.len(),
        unchanged,
        changed,
        new_only,
        old_only,
        groups,
        warnings,
    }
}

fn signature_index(doc: &DiffgrDocument) -> BTreeMap<String, Vec<String>> {
    let mut out: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for chunk in &doc.chunks {
        out.entry(stable_chunk_signature(chunk))
            .or_default()
            .push(chunk.id.clone());
    }
    out
}

fn stable_chunk_signature(chunk: &Chunk) -> String {
    let mut text = String::new();
    text.push_str(&chunk.file_path);
    text.push('\n');
    for line in chunk.lines.iter() {
        text.push_str(&line.kind);
        text.push('\t');
        text.push_str(&line.text);
        text.push('\n');
    }
    text
}

fn build_html_report(doc: &DiffgrDocument) -> String {
    let counts = doc.status_counts();
    let metrics = doc.metrics();
    let mut out = String::new();
    out.push_str("<!doctype html><html><head><meta charset=\"utf-8\">\n");
    out.push_str("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n");
    out.push_str("<title>DiffGR Review</title>\n");
    out.push_str("<style>body{font-family:system-ui,sans-serif;margin:24px;line-height:1.5}.chunk{border:1px solid #ccc;border-radius:8px;padding:12px;margin:12px 0}.add{color:#0a7f34}.delete{color:#b00020}.meta{color:#666}.badge{padding:2px 8px;border-radius:999px;background:#eee}.reviewed{background:#d9f7d9}.needsReReview{background:#fff3bf}.ignored{background:#eee}.unreviewed{background:#ffd6d6}pre{white-space:pre-wrap}</style>\n");
    out.push_str("</head><body>\n");
    out.push_str(&format!("<h1>{}</h1>\n", html_escape(&doc.title)));
    out.push_str(&format!(
        "<p>Coverage {:.1}% ({}/{}) / reviewed {} / pending {} / ignored {}</p>\n",
        metrics.coverage_rate * 100.0,
        metrics.reviewed,
        metrics.tracked,
        counts.reviewed,
        counts.pending(),
        counts.ignored
    ));
    out.push_str("<h2>Groups</h2><ul>\n");
    for group in &doc.groups {
        let group_metrics = doc.group_metrics(Some(&group.id));
        out.push_str(&format!(
            "<li><a href=\"#group-{}\">{}</a> — {}/{} reviewed</li>\n",
            html_id(&group.id),
            html_escape(&group.name),
            group_metrics.reviewed,
            group_metrics.tracked
        ));
    }
    out.push_str("</ul>\n");
    for group in &doc.groups {
        out.push_str(&format!(
            "<h2 id=\"group-{}\">{}</h2>\n",
            html_id(&group.id),
            html_escape(&group.name)
        ));
        for chunk_id in doc.assignments.get(&group.id).into_iter().flatten() {
            if let Some(chunk) = doc.chunk_by_id(chunk_id) {
                push_chunk_html(doc, chunk, &mut out);
            }
        }
    }
    let unassigned = doc.unassigned_chunk_ids();
    if !unassigned.is_empty() {
        out.push_str("<h2 id=\"unassigned\">Unassigned</h2>\n");
        for chunk_id in unassigned {
            if let Some(chunk) = doc.chunk_by_id(&chunk_id) {
                push_chunk_html(doc, chunk, &mut out);
            }
        }
    }
    out.push_str("</body></html>\n");
    out
}

fn push_chunk_html(doc: &DiffgrDocument, chunk: &Chunk, out: &mut String) {
    let status = doc.status_for(&chunk.id);
    out.push_str(&format!(
        "<section class=\"chunk\" id=\"chunk-{}\"><h3>{}</h3><p><span class=\"badge {}\">{}</span> <code>{}</code> +{} -{}</p>\n",
        html_id(&chunk.id),
        html_escape(&chunk.file_path),
        status.as_str(),
        html_escape(status.label()),
        html_escape(&chunk.id),
        chunk.add_count,
        chunk.delete_count
    ));
    let comment = doc.comment_for(&chunk.id);
    if !comment.trim().is_empty() {
        out.push_str(&format!(
            "<p><strong>Comment:</strong> {}</p>\n",
            html_escape(comment.trim())
        ));
    }
    out.push_str("<pre>\n");
    for line in chunk.lines.iter() {
        let class = match line.kind.as_str() {
            "add" => "add",
            "delete" => "delete",
            "meta" => "meta",
            _ => "context",
        };
        out.push_str(&format!(
            "<span class=\"{}\">{}{}</span>\n",
            class,
            html_escape(line.prefix()),
            html_escape(&line.text)
        ));
    }
    out.push_str("</pre></section>\n");
}

fn html_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&#39;")
}

fn html_id(value: &str) -> String {
    let mut out = String::new();
    for ch in value.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
        } else if ch == '-' || ch == '_' {
            out.push(ch);
        } else if !out.ends_with('-') {
            out.push('-');
        }
    }
    let trimmed = out.trim_matches('-').to_owned();
    if trimmed.is_empty() {
        "item".to_owned()
    } else {
        trimmed
    }
}

fn canonical_json(value: &Value) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| String::new())
}

fn write_json(path: &Path, value: &Value) -> Result<(), String> {
    let text = serde_json::to_string_pretty(value).map_err(|err| err.to_string())? + "\n";
    write_text(path, &text)
}

fn write_text(path: &Path, text: &str) -> Result<(), String> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent).map_err(|err| format!("{}: {}", parent.display(), err))?;
    }

    let temp_path = sibling_temp_path(path);
    let write_result = (|| -> Result<(), String> {
        let mut file = fs::File::create(&temp_path)
            .map_err(|err| format!("{}: {}", temp_path.display(), err))?;
        file.write_all(text.as_bytes())
            .map_err(|err| format!("{}: {}", temp_path.display(), err))?;
        file.sync_all()
            .map_err(|err| format!("{}: {}", temp_path.display(), err))?;
        Ok(())
    })();
    if let Err(err) = write_result {
        let _ = fs::remove_file(&temp_path);
        return Err(err);
    }

    match fs::rename(&temp_path, path) {
        Ok(()) => Ok(()),
        Err(rename_err) => {
            // Windows cannot rename over an existing file. Keep the write safe by only
            // replacing the destination after the complete temp file is on disk, and keep
            // a short-lived restore copy in case the final rename fails.
            let restore_path = sibling_restore_path(path);
            let had_existing = path.exists();
            if had_existing {
                fs::copy(path, &restore_path)
                    .map_err(|copy_err| format!("{}: {}", restore_path.display(), copy_err))?;
                fs::remove_file(path)
                    .map_err(|remove_err| format!("{}: {}", path.display(), remove_err))?;
            }
            match fs::rename(&temp_path, path) {
                Ok(()) => {
                    if had_existing {
                        let _ = fs::remove_file(&restore_path);
                    }
                    Ok(())
                }
                Err(err) => {
                    if had_existing {
                        let _ = fs::copy(&restore_path, path);
                        let _ = fs::remove_file(&restore_path);
                    }
                    let _ = fs::remove_file(&temp_path);
                    Err(format!(
                        "{}: {} (initial rename error: {})",
                        path.display(),
                        err,
                        rename_err
                    ))
                }
            }
        }
    }
}

fn sibling_temp_path(path: &Path) -> PathBuf {
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("diffgr.tmp");
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or(0);
    let unique = format!(".{}.{}.{}.tmp", file_name, std::process::id(), stamp);
    path.with_file_name(unique)
}

fn sibling_restore_path(path: &Path) -> PathBuf {
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("diffgr.restore");
    path.with_file_name(format!(".{}.restore", file_name))
}

fn escape_markdown_cell(value: &str) -> String {
    escape_markdown_line(value).replace('|', "\\|")
}

fn escape_markdown_line(value: &str) -> String {
    value
        .replace('\r', " ")
        .replace('\n', " ")
        .trim()
        .to_owned()
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
