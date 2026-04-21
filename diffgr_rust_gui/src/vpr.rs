use crate::model::{DiffgrDocument, ReviewStatus};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VirtualPrRiskItem {
    pub chunk_id: String,
    pub file_path: String,
    pub group_id: Option<String>,
    pub status: String,
    pub risk_score: u32,
    pub adds: usize,
    pub deletes: usize,
    pub comments: usize,
    pub reasons: Vec<String>,
    pub preview: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VirtualPrFileHotspot {
    pub file_path: String,
    pub chunks: usize,
    pub pending: usize,
    pub risk_score: u32,
    pub adds: usize,
    pub deletes: usize,
    pub comments: usize,
    pub reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VirtualPrGroupReadiness {
    pub group_id: String,
    pub group_name: String,
    pub reviewed: usize,
    pub tracked: usize,
    pub pending: usize,
    pub approved: bool,
    pub approval_valid: bool,
    pub brief_status: String,
    pub missing_handoff_fields: Vec<String>,
    pub risk_score: u32,
    pub top_risk_chunks: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VirtualPrReviewReport {
    pub title: String,
    pub readiness_score: u8,
    pub readiness_level: String,
    pub ready_to_approve: bool,
    pub blockers: Vec<String>,
    pub warnings: Vec<String>,
    pub next_actions: Vec<String>,
    pub risk_items: Vec<VirtualPrRiskItem>,
    pub file_hotspots: Vec<VirtualPrFileHotspot>,
    pub group_readiness: Vec<VirtualPrGroupReadiness>,
}

pub fn analyze_virtual_pr(doc: &DiffgrDocument) -> VirtualPrReviewReport {
    let coverage = doc.analyze_coverage();
    let counts = doc.status_counts();
    let metrics = doc.metrics();
    let approval = doc.check_all_approvals();
    let mut blockers = Vec::new();
    let mut warnings = Vec::new();
    let mut next_actions = Vec::new();

    if !coverage.ok() {
        blockers.push(format!(
            "coverageに問題があります: unassigned={}, duplicated={}, unknownGroups={}, unknownChunks={}",
            coverage.unassigned.len(),
            coverage.duplicated.len(),
            coverage.unknown_groups.len(),
            coverage.unknown_chunks.len()
        ));
        next_actions.push("Coverageタブで未割当/重複割当を直す".to_owned());
    }
    if counts.needs_re_review > 0 {
        blockers.push(format!(
            "再レビュー必要なchunkが{}件あります",
            counts.needs_re_review
        ));
        next_actions.push("status=再レビュー必要のchunkから確認する".to_owned());
    }
    if metrics.pending > 0 {
        blockers.push(format!(
            "未完了レビューが{}件あります ({}/{})",
            metrics.pending, metrics.reviewed, metrics.tracked
        ));
        next_actions.push("次の未完了chunkへ進み、レビュー済みにするか差戻し理由を書く".to_owned());
    }
    if !approval.all_approved {
        blockers.push("全groupのapprovalが有効ではありません".to_owned());
        next_actions.push("Approvalタブでgroup単位のapprove/request changesを確認する".to_owned());
    }
    if !doc.warnings.is_empty() {
        warnings.extend(
            doc.warnings
                .iter()
                .map(|w| format!("document warning: {w}")),
        );
    }

    let mut risk_items = build_risk_items(doc);
    risk_items.sort_by(|left, right| {
        right
            .risk_score
            .cmp(&left.risk_score)
            .then_with(|| status_rank(&left.status).cmp(&status_rank(&right.status)))
            .then_with(|| left.file_path.cmp(&right.file_path))
            .then_with(|| left.chunk_id.cmp(&right.chunk_id))
    });

    let critical_pending = risk_items
        .iter()
        .filter(|item| {
            item.risk_score >= 45 && item.status != "reviewed" && item.status != "ignored"
        })
        .count();
    if critical_pending > 0 {
        blockers.push(format!(
            "高リスクかつ未完了のchunkが{}件あります",
            critical_pending
        ));
        next_actions.push("仮想PRタブの高リスクqueue上位から確認する".to_owned());
    }

    let huge_files = doc
        .file_summaries()
        .into_iter()
        .filter(|file| file.adds + file.deletes >= 500)
        .count();
    if huge_files > 0 {
        warnings.push(format!(
            "変更量が大きいファイルが{}件あります。分割または重点レビューを検討してください",
            huge_files
        ));
    }

    let file_hotspots = build_file_hotspots(&risk_items);
    let group_readiness = build_group_readiness(doc, &risk_items);
    for group in &group_readiness {
        if group.pending > 0 {
            next_actions.push(format!(
                "group {} のpending {}件を確認する",
                group.group_id, group.pending
            ));
        }
        if !group.missing_handoff_fields.is_empty() {
            warnings.push(format!(
                "group {} のhandoff不足: {}",
                group.group_id,
                group.missing_handoff_fields.join(", ")
            ));
        }
    }

    dedup_keep_order(&mut blockers);
    dedup_keep_order(&mut warnings);
    dedup_keep_order(&mut next_actions);
    next_actions.truncate(12);

    let mut penalty = 0i32;
    penalty += (blockers.len() as i32) * 14;
    penalty += (warnings.len() as i32) * 4;
    penalty += ((counts.needs_re_review as i32) * 4).min(20);
    penalty += ((metrics.pending as i32) * 2).min(20);
    penalty += risk_items
        .iter()
        .take(5)
        .map(|item| (item.risk_score as i32 / 10).min(8))
        .sum::<i32>();
    let readiness_score = (100 - penalty).clamp(0, 100) as u8;
    let readiness_level = readiness_level(readiness_score, blockers.len()).to_owned();
    let ready_to_approve = blockers.is_empty() && readiness_score >= 85;

    VirtualPrReviewReport {
        title: doc.title.clone(),
        readiness_score,
        readiness_level,
        ready_to_approve,
        blockers,
        warnings,
        next_actions,
        risk_items,
        file_hotspots,
        group_readiness,
    }
}

pub fn virtual_pr_report_json_value(report: &VirtualPrReviewReport) -> Value {
    json!({
        "title": &report.title,
        "readinessScore": report.readiness_score,
        "readinessLevel": &report.readiness_level,
        "readyToApprove": report.ready_to_approve,
        "blockers": &report.blockers,
        "warnings": &report.warnings,
        "nextActions": &report.next_actions,
        "riskItems": report.risk_items.iter().map(|item| json!({
            "chunkId": &item.chunk_id,
            "filePath": &item.file_path,
            "groupId": &item.group_id,
            "status": &item.status,
            "riskScore": item.risk_score,
            "adds": item.adds,
            "deletes": item.deletes,
            "comments": item.comments,
            "reasons": &item.reasons,
            "preview": &item.preview,
        })).collect::<Vec<_>>(),
        "fileHotspots": report.file_hotspots.iter().map(|file| json!({
            "filePath": &file.file_path,
            "chunks": file.chunks,
            "pending": file.pending,
            "riskScore": file.risk_score,
            "adds": file.adds,
            "deletes": file.deletes,
            "comments": file.comments,
            "reasons": &file.reasons,
        })).collect::<Vec<_>>(),
        "groupReadiness": report.group_readiness.iter().map(|group| json!({
            "groupId": &group.group_id,
            "groupName": &group.group_name,
            "reviewed": group.reviewed,
            "tracked": group.tracked,
            "pending": group.pending,
            "approved": group.approved,
            "approvalValid": group.approval_valid,
            "briefStatus": &group.brief_status,
            "missingHandoffFields": &group.missing_handoff_fields,
            "riskScore": group.risk_score,
            "topRiskChunks": &group.top_risk_chunks,
        })).collect::<Vec<_>>(),
    })
}

pub fn virtual_pr_report_markdown(report: &VirtualPrReviewReport) -> String {
    let mut out = String::new();
    out.push_str(&format!("# Virtual PR Review Gate: {}\n\n", report.title));
    out.push_str(&format!(
        "- readiness: **{} / 100** ({})\n",
        report.readiness_score, report.readiness_level
    ));
    out.push_str(&format!(
        "- readyToApprove: `{}`\n\n",
        report.ready_to_approve
    ));

    out.push_str("## Blockers\n\n");
    if report.blockers.is_empty() {
        out.push_str("- none\n\n");
    } else {
        for item in &report.blockers {
            out.push_str(&format!("- {}\n", escape_md(item)));
        }
        out.push('\n');
    }

    out.push_str("## Warnings\n\n");
    if report.warnings.is_empty() {
        out.push_str("- none\n\n");
    } else {
        for item in &report.warnings {
            out.push_str(&format!("- {}\n", escape_md(item)));
        }
        out.push('\n');
    }

    out.push_str("## Next actions\n\n");
    if report.next_actions.is_empty() {
        out.push_str("- none\n\n");
    } else {
        for item in &report.next_actions {
            out.push_str(&format!("- {}\n", escape_md(item)));
        }
        out.push('\n');
    }

    out.push_str("## High-risk queue\n\n");
    out.push_str("| Risk | Status | Chunk | Group | File | Reasons |\n");
    out.push_str("|---:|---|---|---|---|---|\n");
    for item in report.risk_items.iter().take(20) {
        out.push_str(&format!(
            "| {} | `{}` | `{}` | {} | {} | {} |\n",
            item.risk_score,
            item.status,
            short(&item.chunk_id),
            item.group_id.as_deref().unwrap_or("-"),
            escape_table(&item.file_path),
            escape_table(&item.reasons.join(", "))
        ));
    }
    out.push('\n');

    out.push_str("## Group readiness\n\n");
    out.push_str("| Group | Reviewed | Approval | Brief | Risk | Missing handoff |\n");
    out.push_str("|---|---:|---|---|---:|---|\n");
    for group in &report.group_readiness {
        out.push_str(&format!(
            "| {} ({}) | {}/{} | {}/{} | {} | {} | {} |\n",
            escape_table(&group.group_name),
            escape_table(&group.group_id),
            group.reviewed,
            group.tracked,
            group.approved,
            group.approval_valid,
            escape_table(&group.brief_status),
            group.risk_score,
            escape_table(&group.missing_handoff_fields.join(", "))
        ));
    }
    out
}

pub fn virtual_pr_reviewer_prompt_markdown(
    report: &VirtualPrReviewReport,
    max_items: usize,
) -> String {
    let mut out = String::new();
    out.push_str("# 仮想PRレビュー依頼\n\n");
    out.push_str("あなたはこの仮想PRをレビューします。blockerを先に潰し、高リスクchunkから確認してください。\n\n");
    out.push_str(&format!(
        "- title: {}\n- readiness: {} / 100 ({})\n- readyToApprove: {}\n\n",
        report.title, report.readiness_score, report.readiness_level, report.ready_to_approve
    ));
    out.push_str("## Blockers\n\n");
    for blocker in &report.blockers {
        out.push_str(&format!("- {}\n", blocker));
    }
    if report.blockers.is_empty() {
        out.push_str("- none\n");
    }
    out.push_str("\n## 見る順番\n\n");
    for item in report.risk_items.iter().take(max_items) {
        out.push_str(&format!(
            "### {} risk={} status={}\n\n- file: {}\n- group: {}\n- reasons: {}\n- preview: {}\n\n",
            item.chunk_id,
            item.risk_score,
            item.status,
            item.file_path,
            item.group_id.as_deref().unwrap_or("-"),
            item.reasons.join(", "),
            item.preview
        ));
    }
    out.push_str("## 期待する出力\n\n- approve可能か\n- request changesすべき具体的理由\n- 追加で必要なtest evidence\n- group handoffに追記すべき事項\n");
    out
}

fn build_risk_items(doc: &DiffgrDocument) -> Vec<VirtualPrRiskItem> {
    let assigned: BTreeSet<String> = doc
        .assignments
        .values()
        .flat_map(|ids| ids.iter().cloned())
        .collect();
    doc.chunks
        .iter()
        .map(|chunk| {
            let status = doc.status_for(&chunk.id);
            let comments = usize::from(!doc.comment_for(&chunk.id).trim().is_empty())
                + doc.line_comment_count_for(&chunk.id);
            let mut score = 0u32;
            let mut reasons = Vec::new();
            match status {
                ReviewStatus::NeedsReReview => {
                    score += 42;
                    reasons.push("needs re-review".to_owned());
                }
                ReviewStatus::Unreviewed => {
                    score += 24;
                    reasons.push("unreviewed".to_owned());
                }
                ReviewStatus::Reviewed => {}
                ReviewStatus::Ignored => {
                    reasons.push("ignored".to_owned());
                }
            }
            let size = chunk.add_count + chunk.delete_count;
            if size >= 500 {
                score += 28;
                reasons.push(format!("large diff {size} lines"));
            } else if size >= 200 {
                score += 18;
                reasons.push(format!("medium-large diff {size} lines"));
            } else if size >= 60 {
                score += 8;
                reasons.push(format!("non-trivial diff {size} lines"));
            }
            if chunk.delete_count >= 50 && chunk.delete_count > chunk.add_count * 2 {
                score += 10;
                reasons.push("large deletion ratio".to_owned());
            }
            if !assigned.contains(&chunk.id) {
                score += 25;
                reasons.push("unassigned to virtual PR group".to_owned());
            }
            if comments > 0 {
                score += 6 + (comments as u32).min(6);
                reasons.push(format!("{} review comment(s)", comments));
            }
            let path_reasons = path_risk_reasons(&chunk.file_path);
            for (reason, points) in path_reasons {
                score += points;
                reasons.push(reason);
            }
            let text = chunk_text_for_scan(chunk);
            let text_reasons = text_risk_reasons(&text);
            for (reason, points) in text_reasons {
                score += points;
                reasons.push(reason);
            }
            if text.lines().any(|line| line.len() > 800) {
                score += 8;
                reasons.push("very long/minified line".to_owned());
            }
            dedup_keep_order(&mut reasons);
            let preview = compact_preview(&text, 180);
            VirtualPrRiskItem {
                chunk_id: chunk.id.clone(),
                file_path: chunk.file_path.clone(),
                group_id: doc.primary_group_for_chunk(&chunk.id),
                status: status.as_str().to_owned(),
                risk_score: score,
                adds: chunk.add_count,
                deletes: chunk.delete_count,
                comments,
                reasons,
                preview,
            }
        })
        .filter(|item| item.risk_score > 0 || item.status != "reviewed")
        .collect()
}

fn build_file_hotspots(items: &[VirtualPrRiskItem]) -> Vec<VirtualPrFileHotspot> {
    let mut by_file: BTreeMap<String, VirtualPrFileHotspot> = BTreeMap::new();
    for item in items {
        let entry = by_file
            .entry(item.file_path.clone())
            .or_insert_with(|| VirtualPrFileHotspot {
                file_path: item.file_path.clone(),
                ..VirtualPrFileHotspot::default()
            });
        entry.chunks += 1;
        entry.adds += item.adds;
        entry.deletes += item.deletes;
        entry.comments += item.comments;
        entry.risk_score += item.risk_score;
        if item.status == "unreviewed" || item.status == "needsReReview" {
            entry.pending += 1;
        }
        for reason in &item.reasons {
            if entry.reasons.len() < 8 && !entry.reasons.contains(reason) {
                entry.reasons.push(reason.clone());
            }
        }
    }
    let mut out: Vec<_> = by_file.into_values().collect();
    out.sort_by(|left, right| {
        right
            .risk_score
            .cmp(&left.risk_score)
            .then_with(|| right.pending.cmp(&left.pending))
            .then_with(|| left.file_path.cmp(&right.file_path))
    });
    out
}

fn build_group_readiness(
    doc: &DiffgrDocument,
    risk_items: &[VirtualPrRiskItem],
) -> Vec<VirtualPrGroupReadiness> {
    let approval = doc.check_all_approvals();
    let approval_by_group: BTreeMap<String, _> = approval
        .groups
        .into_iter()
        .map(|status| (status.group_id.clone(), status))
        .collect();
    let mut risk_by_group: BTreeMap<String, Vec<&VirtualPrRiskItem>> = BTreeMap::new();
    for item in risk_items {
        if let Some(group_id) = item.group_id.as_ref() {
            risk_by_group
                .entry(group_id.clone())
                .or_default()
                .push(item);
        }
    }
    let mut rows = Vec::new();
    for group in &doc.groups {
        let metrics = doc.group_metrics(Some(&group.id));
        let brief = doc.group_brief_draft(&group.id);
        let mut missing = Vec::new();
        if brief.summary.trim().is_empty() {
            missing.push("summary".to_owned());
        }
        if brief.focus_points.trim().is_empty() {
            missing.push("focusPoints".to_owned());
        }
        if brief.test_evidence.trim().is_empty() {
            missing.push("testEvidence".to_owned());
        }
        if brief.known_tradeoffs.trim().is_empty() {
            missing.push("knownTradeoffs".to_owned());
        }
        if brief.questions_for_reviewer.trim().is_empty() && metrics.pending > 0 {
            missing.push("questionsForReviewer".to_owned());
        }
        let risks = risk_by_group.get(&group.id).cloned().unwrap_or_default();
        let risk_score = risks.iter().map(|item| item.risk_score).sum();
        let mut top_risk_chunks = risks
            .iter()
            .take(5)
            .map(|item| item.chunk_id.clone())
            .collect::<Vec<_>>();
        top_risk_chunks.sort();
        top_risk_chunks.dedup();
        let approval_status = approval_by_group.get(&group.id);
        rows.push(VirtualPrGroupReadiness {
            group_id: group.id.clone(),
            group_name: group.name.clone(),
            reviewed: metrics.reviewed,
            tracked: metrics.tracked,
            pending: metrics.pending,
            approved: approval_status.map(|s| s.approved).unwrap_or(false),
            approval_valid: approval_status.map(|s| s.valid).unwrap_or(false),
            brief_status: brief.status,
            missing_handoff_fields: missing,
            risk_score,
            top_risk_chunks,
        });
    }
    rows.sort_by(|left, right| {
        right
            .pending
            .cmp(&left.pending)
            .then_with(|| right.risk_score.cmp(&left.risk_score))
            .then_with(|| left.group_id.cmp(&right.group_id))
    });
    rows
}

fn path_risk_reasons(path: &str) -> Vec<(String, u32)> {
    let lower = path.to_lowercase();
    let mut out = Vec::new();
    let rules = [
        ("migration", 18, "migration/schema change"),
        ("schema", 14, "schema/contract change"),
        ("auth", 16, "auth/security path"),
        ("security", 16, "security path"),
        ("permission", 14, "permission path"),
        ("policy", 10, "policy path"),
        ("payment", 14, "payment path"),
        ("billing", 14, "billing path"),
        ("crypto", 16, "crypto path"),
        ("config", 8, "config path"),
        ("Cargo.toml", 12, "dependency manifest"),
        ("package.json", 12, "dependency manifest"),
        ("lock", 6, "lockfile/dependency churn"),
        ("test", 4, "test file"),
    ];
    for (needle, points, reason) in rules {
        if lower.contains(&needle.to_lowercase()) {
            out.push((reason.to_owned(), points));
        }
    }
    out
}

fn text_risk_reasons(text: &str) -> Vec<(String, u32)> {
    let lower = text.to_lowercase();
    let rules = [
        ("unsafe", 18, "unsafe usage"),
        ("unwrap(", 8, "unwrap usage"),
        ("expect(", 6, "expect usage"),
        ("panic!", 14, "panic path"),
        ("todo!", 10, "todo left in code"),
        ("fixme", 8, "FIXME marker"),
        ("password", 16, "secret/password reference"),
        ("token", 10, "token/credential reference"),
        ("secret", 16, "secret reference"),
        ("sql", 8, "SQL/data access"),
        ("select ", 8, "SQL/data access"),
        ("insert ", 8, "SQL/data access"),
        ("delete ", 8, "SQL/data access"),
        ("cache", 6, "cache behavior"),
        ("thread", 8, "concurrency/threading"),
        ("mutex", 8, "concurrency/locking"),
        ("async", 5, "async behavior"),
        ("timeout", 5, "timeout behavior"),
    ];
    let mut out = Vec::new();
    for (needle, points, reason) in rules {
        if lower.contains(needle) {
            out.push((reason.to_owned(), points));
        }
    }
    out
}

fn chunk_text_for_scan(chunk: &crate::model::Chunk) -> String {
    let changed = chunk
        .lines
        .iter()
        .filter(|line| line.kind != "context")
        .map(|line| format!("{}{}", line.prefix(), line.text))
        .collect::<Vec<_>>()
        .join("\n");
    if !changed.trim().is_empty() {
        return changed;
    }
    chunk
        .lines
        .iter()
        .map(|line| format!("{}{}", line.prefix(), line.text))
        .collect::<Vec<_>>()
        .join("\n")
}

fn compact_preview(text: &str, max_chars: usize) -> String {
    let normalized = text
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .take(6)
        .collect::<Vec<_>>()
        .join(" / ");
    if normalized.chars().count() <= max_chars {
        normalized
    } else {
        let mut out: String = normalized
            .chars()
            .take(max_chars.saturating_sub(1))
            .collect();
        out.push('…');
        out
    }
}

fn readiness_level(score: u8, blocker_count: usize) -> &'static str {
    if blocker_count > 0 && score < 60 {
        "blocked"
    } else if blocker_count > 0 {
        "needs-review"
    } else if score >= 90 {
        "ready"
    } else if score >= 75 {
        "nearly-ready"
    } else {
        "needs-review"
    }
}

fn status_rank(status: &str) -> u8 {
    match status {
        "needsReReview" => 0,
        "unreviewed" => 1,
        "reviewed" => 2,
        "ignored" => 3,
        _ => 4,
    }
}

fn dedup_keep_order(items: &mut Vec<String>) {
    let mut seen = BTreeSet::new();
    items.retain(|item| seen.insert(item.clone()));
}

fn short(value: &str) -> String {
    value.chars().take(10).collect()
}

fn escape_md(value: &str) -> String {
    value.replace('\n', " ")
}

fn escape_table(value: &str) -> String {
    escape_md(value).replace('|', "\\|")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample_doc() -> DiffgrDocument {
        DiffgrDocument::from_value(json!({
            "format": "diffgr",
            "version": 1,
            "meta": {"title": "sample"},
            "groups": [{"id":"g-auth","name":"Auth","order":1}],
            "chunks": [{
                "id":"c-auth",
                "filePath":"src/auth/security.rs",
                "oldStart":1,"oldCount":1,"newStart":1,"newCount":2,
                "lines":[
                    {"type":"delete","text":"return false;","oldLine":1},
                    {"type":"add","text":"let token = password.unwrap();","newLine":1}
                ]
            }],
            "assignments": {"g-auth":["c-auth"]},
            "reviews": {"c-auth":{"status":"needsReReview","comment":"check this"}},
            "groupBriefs": {"g-auth":{"status":"draft"}}
        }))
        .unwrap()
    }

    #[test]
    fn virtual_pr_detects_blockers_and_risk() {
        let report = analyze_virtual_pr(&sample_doc());
        assert!(!report.ready_to_approve);
        assert!(report.readiness_score < 85);
        assert!(!report.blockers.is_empty());
        assert!(report.risk_items[0].risk_score >= 40);
        assert!(report.risk_items[0]
            .reasons
            .iter()
            .any(|r| r.contains("security")));
    }

    #[test]
    fn virtual_pr_json_contains_queues() {
        let report = analyze_virtual_pr(&sample_doc());
        let value = virtual_pr_report_json_value(&report);
        assert_eq!(value["title"], "sample");
        assert!(value["riskItems"].as_array().unwrap().len() == 1);
        assert!(value["groupReadiness"].as_array().unwrap().len() == 1);
    }

    #[test]
    fn virtual_pr_markdown_has_review_gate_sections() {
        let report = analyze_virtual_pr(&sample_doc());
        let md = virtual_pr_report_markdown(&report);
        assert!(md.contains("Virtual PR Review Gate"));
        assert!(md.contains("High-risk queue"));
        assert!(md.contains("Group readiness"));
    }

    #[test]
    fn virtual_pr_prompt_is_reviewer_oriented() {
        let report = analyze_virtual_pr(&sample_doc());
        let prompt = virtual_pr_reviewer_prompt_markdown(&report, 5);
        assert!(prompt.contains("仮想PRレビュー依頼"));
        assert!(prompt.contains("request changes"));
        assert!(prompt.contains("c-auth"));
    }
}
