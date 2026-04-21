use crate::model::{normalize_state_payload, DiffgrDocument};
use serde_json::{json, Map, Number, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

pub const STATE_KEYS: [&str; 4] = ["reviews", "groupBriefs", "analysisState", "threadState"];

#[derive(Clone, Debug, Default)]
pub struct GenerateOptions {
    pub repo: PathBuf,
    pub base: String,
    pub feature: String,
    pub title: String,
    pub include_patch: bool,
}

#[derive(Clone, Debug)]
pub struct AutosliceOptions {
    pub repo: PathBuf,
    pub base: String,
    pub feature: String,
    pub max_commits: usize,
    pub name_style: String,
    pub split_chunks: bool,
    pub context_lines: usize,
    pub fail_on_truncate: bool,
}

impl Default for AutosliceOptions {
    fn default() -> Self {
        Self {
            repo: PathBuf::from("."),
            base: String::new(),
            feature: String::new(),
            max_commits: 50,
            name_style: "subject".to_owned(),
            split_chunks: true,
            context_lines: 3,
            fail_on_truncate: false,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OperationSummary {
    pub written: Vec<PathBuf>,
    pub warnings: Vec<String>,
    pub message: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct RebaseOptions {
    pub preserve_groups: bool,
    pub carry_line_comments: bool,
    pub similarity_threshold: f64,
}

impl Default for RebaseOptions {
    fn default() -> Self {
        Self {
            preserve_groups: true,
            carry_line_comments: true,
            similarity_threshold: 0.86,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RebaseSummary {
    pub mapped_reviews: usize,
    pub unmapped_reviews: usize,
    pub mapped_thread_entries: usize,
    pub matched_strong: usize,
    pub matched_stable: usize,
    pub matched_delta: usize,
    pub matched_similar: usize,
    pub carried_reviews: usize,
    pub carried_reviewed: usize,
    pub changed_to_needs_rereview: usize,
    pub unmapped_new_chunks: usize,
    pub warnings: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BundleVerifyReport {
    pub ok: bool,
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
    pub computed_manifest: Value,
    pub approval_report: Option<Value>,
}

#[derive(Clone, Debug)]
struct ParsedFile {
    a_path: Option<String>,
    b_path: Option<String>,
    meta: Vec<String>,
    hunks: Vec<ParsedHunk>,
}

#[derive(Clone, Debug)]
struct ParsedHunk {
    old_start: i64,
    old_count: i64,
    new_start: i64,
    new_count: i64,
    header: String,
    lines: Vec<Value>,
}

#[derive(Clone, Debug)]
struct SliceCommit {
    sha: String,
    subject: String,
    parent: Option<String>,
}

pub fn read_json_file(path: &Path) -> Result<Value, String> {
    let text = fs::read_to_string(path).map_err(|err| format!("{}: {}", path.display(), err))?;
    serde_json::from_str(&text).map_err(|err| format!("{}: invalid JSON: {}", path.display(), err))
}

pub fn write_json_file(path: &Path, value: &Value) -> Result<(), String> {
    let text = serde_json::to_string_pretty(value).map_err(|err| err.to_string())?;
    write_text_file(path, &(text + "\n"))
}

pub fn write_text_file(path: &Path, text: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .map_err(|err| format!("mkdir {}: {}", parent.display(), err))?;
        }
    }
    let tmp = sibling_temp_path(path);
    {
        let mut file =
            fs::File::create(&tmp).map_err(|err| format!("{}: {}", tmp.display(), err))?;
        file.write_all(text.as_bytes())
            .map_err(|err| format!("{}: {}", tmp.display(), err))?;
        file.sync_all()
            .map_err(|err| format!("{}: {}", tmp.display(), err))?;
    }
    if path.exists() {
        fs::remove_file(path).map_err(|err| format!("replace {}: {}", path.display(), err))?;
    }
    fs::rename(&tmp, path)
        .map_err(|err| format!("rename {} -> {}: {}", tmp.display(), path.display(), err))
}

fn sibling_temp_path(path: &Path) -> PathBuf {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or(0);
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("diffgr-output");
    path.with_file_name(format!(".{file_name}.{stamp}.tmp"))
}

pub fn canonical_json_sorted(value: &Value) -> String {
    match value {
        Value::Null => "null".to_owned(),
        Value::Bool(v) => v.to_string(),
        Value::Number(v) => v.to_string(),
        Value::String(v) => serde_json::to_string(v).unwrap_or_else(|_| "\"\"".to_owned()),
        Value::Array(items) => {
            let inner = items
                .iter()
                .map(canonical_json_sorted)
                .collect::<Vec<_>>()
                .join(",");
            format!("[{inner}]")
        }
        Value::Object(obj) => {
            let mut keys = obj.keys().collect::<Vec<_>>();
            keys.sort();
            let mut parts = Vec::new();
            for key in keys {
                let value = obj.get(key).expect("key from map");
                let key_json = serde_json::to_string(key).unwrap_or_else(|_| "\"\"".to_owned());
                parts.push(format!("{}:{}", key_json, canonical_json_sorted(value)));
            }
            format!("{{{}}}", parts.join(","))
        }
    }
}

pub fn sha256_hex_value(value: &Value) -> String {
    let payload = canonical_json_sorted(value);
    let mut hasher = Sha256::new();
    hasher.update(payload.as_bytes());
    format!("{:x}", hasher.finalize())
}

pub fn run_git(repo: &Path, args: &[&str]) -> Result<String, String> {
    let output = Command::new("git")
        .arg("-C")
        .arg(repo)
        .args(args)
        .output()
        .map_err(|err| format!("git not available: {}", err))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
        let msg = if stderr.is_empty() { stdout } else { stderr };
        return Err(format!("git {} failed: {}", args.join(" "), msg));
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

fn now_stamp() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .unwrap_or(0);
    format!("unix:{secs}")
}

fn normalize_diff_path(raw: &str) -> Option<String> {
    let value = raw.trim().trim_matches('"');
    if value.is_empty() || value == "/dev/null" {
        return None;
    }
    Some(
        value
            .strip_prefix("a/")
            .or_else(|| value.strip_prefix("b/"))
            .unwrap_or(value)
            .to_owned(),
    )
}

fn parse_diff_git_paths(line: &str) -> (Option<String>, Option<String>) {
    let parts = split_shell_like(line);
    let a = parts.get(2).and_then(|value| normalize_diff_path(value));
    let b = parts.get(3).and_then(|value| normalize_diff_path(value));
    (a, b)
}

fn split_shell_like(line: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut in_quote = false;
    let mut escape = false;
    for ch in line.chars() {
        if escape {
            current.push(ch);
            escape = false;
            continue;
        }
        if ch == '\\' {
            escape = true;
            continue;
        }
        if ch == '"' {
            in_quote = !in_quote;
            continue;
        }
        if ch.is_whitespace() && !in_quote {
            if !current.is_empty() {
                parts.push(std::mem::take(&mut current));
            }
            continue;
        }
        current.push(ch);
    }
    if !current.is_empty() {
        parts.push(current);
    }
    parts
}

fn parse_hunk_header(line: &str) -> Result<(i64, i64, i64, i64, String), String> {
    if !line.starts_with("@@ -") {
        return Err(format!("Unsupported hunk header: {line}"));
    }
    let rest = &line[4..];
    let Some((old_spec, rest)) = rest.split_once(" +") else {
        return Err(format!("Unsupported hunk header: {line}"));
    };
    let Some((new_spec, header)) = rest.split_once(" @@") else {
        return Err(format!("Unsupported hunk header: {line}"));
    };
    let (old_start, old_count) = parse_range_spec(old_spec)?;
    let (new_start, new_count) = parse_range_spec(new_spec)?;
    Ok((
        old_start,
        old_count,
        new_start,
        new_count,
        header.trim().to_owned(),
    ))
}

fn parse_range_spec(spec: &str) -> Result<(i64, i64), String> {
    let (start, count) = match spec.split_once(',') {
        Some((start, count)) => (start, count),
        None => (spec, "1"),
    };
    Ok((
        start
            .parse::<i64>()
            .map_err(|_| format!("Invalid hunk range: {spec}"))?,
        count
            .parse::<i64>()
            .map_err(|_| format!("Invalid hunk range: {spec}"))?,
    ))
}

fn parse_unified_diff(diff_text: &str) -> Result<Vec<ParsedFile>, String> {
    let lines: Vec<&str> = diff_text.lines().collect();
    let mut files: Vec<ParsedFile> = Vec::new();
    let mut current_file: Option<ParsedFile> = None;
    let mut current_hunk: Option<ParsedHunk> = None;
    let mut old_cursor = 0i64;
    let mut new_cursor = 0i64;
    let mut index = 0usize;

    while index < lines.len() {
        let line = lines[index];
        if line.starts_with("diff --git ") {
            if let Some(hunk) = current_hunk.take() {
                if let Some(file) = current_file.as_mut() {
                    file.hunks.push(hunk);
                }
            }
            if let Some(file) = current_file.take() {
                files.push(file);
            }
            let (a_path, b_path) = parse_diff_git_paths(line);
            current_file = Some(ParsedFile {
                a_path,
                b_path,
                meta: vec![line.to_owned()],
                hunks: Vec::new(),
            });
            index += 1;
            continue;
        }

        let Some(file) = current_file.as_mut() else {
            index += 1;
            continue;
        };

        if line.starts_with("@@ ") {
            if let Some(hunk) = current_hunk.take() {
                file.hunks.push(hunk);
            }
            let (old_start, old_count, new_start, new_count, header) = parse_hunk_header(line)?;
            old_cursor = old_start;
            new_cursor = new_start;
            current_hunk = Some(ParsedHunk {
                old_start,
                old_count,
                new_start,
                new_count,
                header,
                lines: Vec::new(),
            });
            index += 1;
            continue;
        }

        if let Some(hunk) = current_hunk.as_mut() {
            if let Some(text) = line.strip_prefix(' ') {
                hunk.lines.push(json!({
                    "kind": "context",
                    "text": text,
                    "oldLine": old_cursor,
                    "newLine": new_cursor,
                }));
                old_cursor += 1;
                new_cursor += 1;
                index += 1;
                continue;
            }
            if line.starts_with('+') && !line.starts_with("+++ ") {
                hunk.lines.push(json!({
                    "kind": "add",
                    "text": &line[1..],
                    "oldLine": Value::Null,
                    "newLine": new_cursor,
                }));
                new_cursor += 1;
                index += 1;
                continue;
            }
            if line.starts_with('-') && !line.starts_with("--- ") {
                hunk.lines.push(json!({
                    "kind": "delete",
                    "text": &line[1..],
                    "oldLine": old_cursor,
                    "newLine": Value::Null,
                }));
                old_cursor += 1;
                index += 1;
                continue;
            }
            if let Some(text) = line.strip_prefix("\\ ") {
                hunk.lines.push(json!({
                    "kind": "meta",
                    "text": text,
                    "oldLine": Value::Null,
                    "newLine": Value::Null,
                }));
                index += 1;
                continue;
            }
            if let Some(hunk) = current_hunk.take() {
                file.hunks.push(hunk);
            }
            continue;
        }

        file.meta.push(line.to_owned());
        index += 1;
    }

    if let Some(hunk) = current_hunk.take() {
        if let Some(file) = current_file.as_mut() {
            file.hunks.push(hunk);
        }
    }
    if let Some(file) = current_file.take() {
        files.push(file);
    }
    Ok(files)
}

fn build_chunk_value(
    file_path: &str,
    old_start: i64,
    old_count: i64,
    new_start: i64,
    new_count: i64,
    header: Option<&str>,
    lines: Vec<Value>,
    extra_meta: Option<Value>,
) -> Value {
    let old_range = json!({"start": old_start, "count": old_count});
    let new_range = json!({"start": new_start, "count": new_count});
    let stable_lines = lines
        .iter()
        .map(|line| {
            json!({
                "kind": line.get("kind").and_then(Value::as_str).unwrap_or("context"),
                "text": line.get("text").and_then(Value::as_str).unwrap_or(""),
            })
        })
        .collect::<Vec<_>>();
    let strong_lines = lines
        .iter()
        .map(|line| {
            json!({
                "kind": line.get("kind").and_then(Value::as_str).unwrap_or("context"),
                "text": line.get("text").and_then(Value::as_str).unwrap_or(""),
                "oldLine": line.get("oldLine").cloned().unwrap_or(Value::Null),
                "newLine": line.get("newLine").cloned().unwrap_or(Value::Null),
            })
        })
        .collect::<Vec<_>>();
    let stable_input = json!({
        "filePath": file_path,
        "lines": stable_lines,
    });
    let strong_input = json!({
        "filePath": file_path,
        "old": old_range,
        "new": new_range,
        "header": header.unwrap_or(""),
        "lines": strong_lines,
    });
    let chunk_id = sha256_hex_value(&strong_input);
    let mut obj = Map::new();
    obj.insert("id".to_owned(), Value::String(chunk_id.clone()));
    obj.insert("filePath".to_owned(), Value::String(file_path.to_owned()));
    obj.insert(
        "old".to_owned(),
        json!({"start": old_start, "count": old_count}),
    );
    obj.insert(
        "new".to_owned(),
        json!({"start": new_start, "count": new_count}),
    );
    if let Some(header) = header.filter(|value| !value.trim().is_empty()) {
        obj.insert("header".to_owned(), Value::String(header.to_owned()));
    }
    obj.insert("lines".to_owned(), Value::Array(lines));
    obj.insert(
        "fingerprints".to_owned(),
        json!({
            "stable": sha256_hex_value(&stable_input),
            "strong": chunk_id,
        }),
    );
    if let Some(extra) = extra_meta {
        obj.insert("meta".to_owned(), extra.clone());
        obj.insert("x-meta".to_owned(), extra);
    }
    Value::Object(obj)
}

pub fn build_diffgr_from_diff_text(
    diff_text: &str,
    title: &str,
    base_ref: &str,
    feature_ref: &str,
    base_sha: &str,
    head_sha: &str,
    merge_base_sha: &str,
    include_patch: bool,
) -> Result<Value, String> {
    let parsed_files = parse_unified_diff(diff_text)?;
    let mut chunks = Vec::new();
    for file in parsed_files {
        let file_path = file
            .b_path
            .or(file.a_path)
            .unwrap_or_else(|| "UNKNOWN".to_owned());
        if file.hunks.is_empty() {
            let meta_lines = file
                .meta
                .into_iter()
                .filter(|line| !line.starts_with("diff --git "))
                .map(Value::String)
                .collect::<Vec<_>>();
            chunks.push(build_chunk_value(
                &file_path,
                0,
                0,
                0,
                0,
                None,
                Vec::new(),
                Some(json!({"diffHeaderLines": meta_lines})),
            ));
            continue;
        }
        for hunk in file.hunks {
            chunks.push(build_chunk_value(
                &file_path,
                hunk.old_start,
                hunk.old_count,
                hunk.new_start,
                hunk.new_count,
                if hunk.header.is_empty() {
                    None
                } else {
                    Some(&hunk.header)
                },
                hunk.lines,
                None,
            ));
        }
    }
    let chunk_ids = chunks
        .iter()
        .filter_map(|chunk| chunk.get("id").and_then(Value::as_str).map(str::to_owned))
        .collect::<Vec<_>>();
    let mut doc = json!({
        "format": "diffgr",
        "version": 1,
        "meta": {
            "title": title,
            "createdAt": now_stamp(),
            "source": {
                "type": "git_compare",
                "base": base_ref,
                "head": feature_ref,
                "baseSha": base_sha,
                "headSha": head_sha,
                "mergeBaseSha": merge_base_sha,
                "description": "Generated by Rust diffgrctl generate"
            }
        },
        "groups": [{"id": "g-all", "name": "All Changes", "order": 1, "tags": ["all"]}],
        "chunks": chunks,
        "assignments": {"g-all": chunk_ids},
        "reviews": {},
    });
    if include_patch {
        if let Some(obj) = doc.as_object_mut() {
            obj.insert("patch".to_owned(), Value::String(diff_text.to_owned()));
        }
    }
    Ok(doc)
}

pub fn build_diffgr_document(options: &GenerateOptions) -> Result<Value, String> {
    let repo = &options.repo;
    let base_sha = run_git(repo, &["rev-parse", "--verify", &options.base])?
        .trim()
        .to_owned();
    let head_sha = run_git(repo, &["rev-parse", "--verify", &options.feature])?
        .trim()
        .to_owned();
    let merge_base_sha = run_git(repo, &["merge-base", &options.base, &options.feature])?
        .trim()
        .to_owned();
    let compare = format!("{}...{}", options.base, options.feature);
    let diff_text = run_git(
        repo,
        &["diff", "--no-color", "--find-renames=50%", &compare],
    )?;
    build_diffgr_from_diff_text(
        &diff_text,
        &options.title,
        &options.base,
        &options.feature,
        &base_sha,
        &head_sha,
        &merge_base_sha,
        options.include_patch,
    )
}

pub fn generate_to_file(
    options: &GenerateOptions,
    output: &Path,
) -> Result<OperationSummary, String> {
    let doc = build_diffgr_document(options)?;
    write_json_file(output, &doc)?;
    Ok(OperationSummary {
        written: vec![output.to_path_buf()],
        warnings: Vec::new(),
        message: format!("Wrote {}", output.display()),
    })
}

fn line_kind(line: &Value) -> &str {
    line.get("kind")
        .and_then(Value::as_str)
        .unwrap_or("context")
}

fn line_text(line: &Value) -> &str {
    line.get("text").and_then(Value::as_str).unwrap_or("")
}

fn value_i64(value: Option<&Value>) -> Option<i64> {
    match value? {
        Value::Number(n) => n.as_i64(),
        Value::String(s) => s.parse::<i64>().ok(),
        _ => None,
    }
}

fn chunk_lines(chunk: &Value) -> Vec<Value> {
    chunk
        .get("lines")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

fn chunk_id(chunk: &Value) -> Option<String> {
    chunk.get("id").and_then(Value::as_str).map(str::to_owned)
}

fn chunk_file_path(chunk: &Value) -> String {
    chunk
        .get("filePath")
        .and_then(Value::as_str)
        .unwrap_or("UNKNOWN")
        .to_owned()
}

fn chunk_header(chunk: &Value) -> Option<String> {
    chunk
        .get("header")
        .and_then(Value::as_str)
        .map(str::to_owned)
}

fn change_blocks(lines: &[Value]) -> Vec<(usize, usize)> {
    let mut blocks = Vec::new();
    let mut start: Option<usize> = None;
    for (index, line) in lines.iter().enumerate() {
        let changed = matches!(line_kind(line), "add" | "delete" | "meta");
        if changed && start.is_none() {
            start = Some(index);
        }
        if !changed {
            if let Some(s) = start.take() {
                blocks.push((s, index));
            }
        }
    }
    if let Some(s) = start {
        blocks.push((s, lines.len()));
    }
    blocks
}

fn slice_segment(lines: &[Value], start: usize, end: usize, context_lines: usize) -> Vec<Value> {
    let s = start.saturating_sub(context_lines);
    let e = end.saturating_add(context_lines).min(lines.len());
    lines[s..e].to_vec()
}

fn first_line_number(lines: &[Value], key: &str) -> i64 {
    lines
        .iter()
        .filter_map(|line| value_i64(line.get(key)))
        .next()
        .unwrap_or(0)
}

fn count_old_new(lines: &[Value]) -> (i64, i64) {
    let mut old_count = 0i64;
    let mut new_count = 0i64;
    for line in lines {
        match line_kind(line) {
            "add" => new_count += 1,
            "delete" => old_count += 1,
            "meta" => {}
            _ => {
                old_count += 1;
                new_count += 1;
            }
        }
    }
    (old_count, new_count)
}

pub fn split_chunk_by_change_blocks(chunk: &Value, context_lines: usize) -> Vec<Value> {
    let lines = chunk_lines(chunk);
    let blocks = change_blocks(&lines);
    if blocks.len() <= 1 {
        return vec![chunk.clone()];
    }
    let file_path = chunk_file_path(chunk);
    let header = chunk_header(chunk);
    let parent = chunk_id(chunk);
    let mut pieces = Vec::new();
    for (block_index, (start, end)) in blocks.iter().copied().enumerate() {
        let segment = slice_segment(&lines, start, end, context_lines);
        let old_start = first_line_number(&segment, "oldLine");
        let new_start = first_line_number(&segment, "newLine");
        let (old_count, new_count) = count_old_new(&segment);
        let extra = json!({
            "parentChunkId": parent,
            "changeBlockIndex": block_index + 1,
            "changeBlockCount": blocks.len(),
        });
        pieces.push(build_chunk_value(
            &file_path,
            old_start,
            old_count,
            new_start,
            new_count,
            header.as_deref(),
            segment,
            Some(extra),
        ));
    }
    pieces
}

fn change_fingerprint_from_parts(
    file_path: &str,
    header: Option<&str>,
    change_lines: &[(String, String)],
) -> String {
    sha256_hex_value(&json!({
        "filePath": file_path,
        "header": header.unwrap_or(""),
        "changes": change_lines,
    }))
}

pub fn change_fingerprint_for_chunk(chunk: &Value) -> String {
    let file_path = chunk_file_path(chunk);
    let header = chunk_header(chunk);
    let lines = chunk_lines(chunk);
    let mut changes = Vec::new();
    for line in lines {
        let kind = line_kind(&line);
        if kind == "context" {
            continue;
        }
        changes.push((kind.to_owned(), line_text(&line).to_owned()));
    }
    change_fingerprint_from_parts(&file_path, header.as_deref(), &changes)
}

fn change_fingerprints_for_diff_text(
    diff_text: &str,
    context_lines: usize,
) -> Result<BTreeSet<String>, String> {
    let files = parse_unified_diff(diff_text)?;
    let mut fps = BTreeSet::new();
    for file in files {
        let file_path = file
            .b_path
            .or(file.a_path)
            .unwrap_or_else(|| "UNKNOWN".to_owned());
        if file.hunks.is_empty() {
            let changes = file
                .meta
                .into_iter()
                .filter(|line| !line.starts_with("diff --git "))
                .map(|line| ("meta".to_owned(), line))
                .collect::<Vec<_>>();
            fps.insert(change_fingerprint_from_parts(&file_path, None, &changes));
            continue;
        }
        for hunk in file.hunks {
            let blocks = change_blocks(&hunk.lines);
            for (start, end) in blocks {
                let segment = slice_segment(&hunk.lines, start, end, context_lines);
                let changes = segment
                    .iter()
                    .filter(|line| line_kind(line) != "context")
                    .map(|line| (line_kind(line).to_owned(), line_text(line).to_owned()))
                    .collect::<Vec<_>>();
                fps.insert(change_fingerprint_from_parts(
                    &file_path,
                    if hunk.header.is_empty() {
                        None
                    } else {
                        Some(hunk.header.as_str())
                    },
                    &changes,
                ));
            }
        }
    }
    Ok(fps)
}

fn list_linear_commits(
    options: &AutosliceOptions,
) -> Result<(Vec<SliceCommit>, Vec<String>), String> {
    let merge_base = run_git(
        &options.repo,
        &["merge-base", &options.base, &options.feature],
    )?
    .trim()
    .to_owned();
    let rev_range = format!("{}..{}", merge_base, options.feature);
    let revs = run_git(&options.repo, &["rev-list", "--reverse", &rev_range])?;
    let mut shas = revs
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(str::to_owned)
        .collect::<Vec<_>>();
    let mut warnings = Vec::new();
    if options.max_commits > 0 && shas.len() > options.max_commits {
        let message = format!(
            "Commit history truncated from {} to {}; autoslice assignments may be incomplete.",
            shas.len(),
            options.max_commits
        );
        if options.fail_on_truncate {
            return Err(message);
        }
        warnings.push(message);
        shas.truncate(options.max_commits);
    }
    let mut commits = Vec::new();
    for sha in shas {
        let subject = run_git(&options.repo, &["log", "-1", "--format=%s", &sha])?
            .trim()
            .to_owned();
        let parent_line = run_git(&options.repo, &["rev-list", "--parents", "-n", "1", &sha])?;
        let parts = parent_line.split_whitespace().collect::<Vec<_>>();
        commits.push(SliceCommit {
            sha,
            subject,
            parent: parts.get(1).map(|value| value.to_string()),
        });
    }
    Ok((commits, warnings))
}

pub fn autoslice_document_by_commits(
    doc: &Value,
    options: &AutosliceOptions,
) -> Result<(Value, Vec<String>), String> {
    if options.name_style != "subject" && options.name_style != "pr" {
        return Err("name_style must be 'subject' or 'pr'".to_owned());
    }
    let (commits, mut warnings) = list_linear_commits(options)?;
    if commits.is_empty() {
        return Err("No commits found between base and feature; cannot autoslice.".to_owned());
    }
    let mut fingerprint_to_commit_index: BTreeMap<String, usize> = BTreeMap::new();
    for (index, commit) in commits.iter().enumerate() {
        let Some(parent) = commit.parent.as_ref() else {
            warnings.push(format!("Commit has no parent (skipped): {}", commit.sha));
            continue;
        };
        let diff_text = run_git(&options.repo, &["diff", "--no-color", parent, &commit.sha])?;
        for fp in change_fingerprints_for_diff_text(&diff_text, options.context_lines)? {
            fingerprint_to_commit_index.entry(fp).or_insert(index + 1);
        }
    }

    let groups = commits
        .iter()
        .enumerate()
        .map(|(index, commit)| {
            let n = index + 1;
            let name = if options.name_style == "pr" {
                format!("PR{n}")
            } else if commit.subject.trim().is_empty() {
                format!("PR{n}")
            } else {
                commit.subject.clone()
            };
            json!({"id": format!("g-pr{n:02}"), "name": name, "order": n, "tags": ["autoslice", "commit"]})
        })
        .collect::<Vec<_>>();
    let mut assignments: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for index in 0..commits.len() {
        assignments.insert(format!("g-pr{:02}", index + 1), Vec::new());
    }
    let original_reviews = doc
        .get("reviews")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let mut new_reviews = Map::new();
    let mut new_chunks = Vec::new();
    let mut unassigned = Vec::new();

    for chunk in doc
        .get("chunks")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let original_id = chunk_id(chunk).unwrap_or_default();
        let review_record = original_reviews.get(&original_id).cloned();
        let pieces = if options.split_chunks {
            split_chunk_by_change_blocks(chunk, options.context_lines)
        } else {
            vec![chunk.clone()]
        };
        for piece in pieces {
            let piece_id = chunk_id(&piece).unwrap_or_default();
            if !piece_id.is_empty() {
                if let Some(record) = review_record.as_ref() {
                    new_reviews.insert(piece_id.clone(), record.clone());
                }
            }
            let fp = change_fingerprint_for_chunk(&piece);
            if let Some(idx) = fingerprint_to_commit_index.get(&fp).copied() {
                assignments
                    .entry(format!("g-pr{idx:02}"))
                    .or_default()
                    .push(Value::String(piece_id));
            } else {
                unassigned.push(piece_id);
            }
            new_chunks.push(piece);
        }
    }

    let assignments_obj = assignments
        .into_iter()
        .filter(|(_, ids)| !ids.is_empty())
        .map(|(group_id, ids)| (group_id, Value::Array(ids)))
        .collect::<Map<_, _>>();
    let mut new_doc = doc.clone();
    let root = new_doc
        .as_object_mut()
        .ok_or_else(|| "DiffGR document must be object.".to_owned())?;
    root.insert("groups".to_owned(), Value::Array(groups));
    root.insert("chunks".to_owned(), Value::Array(new_chunks));
    root.insert("assignments".to_owned(), Value::Object(assignments_obj));
    root.insert("reviews".to_owned(), Value::Object(new_reviews));
    let meta = root
        .entry("meta".to_owned())
        .or_insert_with(|| Value::Object(Map::new()));
    if !meta.is_object() {
        *meta = Value::Object(Map::new());
    }
    meta.as_object_mut().unwrap().insert(
        "x-autoslice".to_owned(),
        json!({
            "method": "commits",
            "base": options.base,
            "head": options.feature,
            "commits": commits.iter().map(|c| json!({"sha": c.sha, "subject": c.subject})).collect::<Vec<_>>(),
            "unassignedCount": unassigned.len(),
            "splitChunks": options.split_chunks,
            "contextLines": options.context_lines,
            "failOnTruncate": options.fail_on_truncate,
        }),
    );
    Ok((new_doc, warnings))
}

pub fn refine_group_names_ja(doc: &Value) -> Value {
    let mut out = doc.clone();
    let chunk_map = chunk_map(&out);
    let assignments = assignments_map(&out);
    let mut rename_map = Map::new();
    if let Some(groups) = out.get_mut("groups").and_then(Value::as_array_mut) {
        for group in groups {
            let Some(obj) = group.as_object_mut() else {
                continue;
            };
            let group_id = obj
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned();
            let before = obj
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned();
            let chunks = assignments
                .get(&group_id)
                .into_iter()
                .flatten()
                .filter_map(|id| chunk_map.get(id))
                .cloned()
                .collect::<Vec<_>>();
            let suggestion = suggest_group_name_ja(&chunks);
            let after = if suggestion.0 != "misc" {
                suggestion.1.clone()
            } else {
                before.clone()
            };
            if !after.is_empty() && after != before {
                obj.insert("name".to_owned(), Value::String(after.clone()));
            }
            rename_map.insert(
                group_id,
                json!({"before": before, "after": after, "label": suggestion.0, "score": suggestion.2}),
            );
        }
    }
    let root = out.as_object_mut().unwrap();
    let meta = root
        .entry("meta".to_owned())
        .or_insert_with(|| Value::Object(Map::new()));
    if !meta.is_object() {
        *meta = Value::Object(Map::new());
    }
    meta.as_object_mut().unwrap().insert(
        "x-sliceRefine".to_owned(),
        json!({"groupRename": rename_map, "lang": "ja", "method": "heuristic-rust"}),
    );
    out
}

fn suggest_group_name_ja(chunks: &[Value]) -> (String, String, usize) {
    let text = chunks
        .iter()
        .map(chunk_text_for_scoring)
        .collect::<Vec<_>>()
        .join("\n");
    let labels = [
        (
            "auth",
            "認証/権限",
            ["auth", "login", "token", "session", "permission", "role"].as_slice(),
        ),
        (
            "api",
            "API/サービス",
            [
                "route",
                "handler",
                "controller",
                "service",
                "endpoint",
                "api",
            ]
            .as_slice(),
        ),
        (
            "db",
            "DB/永続化",
            ["sql", "schema", "migration", "database", "db", "repository"].as_slice(),
        ),
        (
            "ui",
            "画面/UI",
            ["component", "tsx", "jsx", "page", "button", "modal", "css"].as_slice(),
        ),
        (
            "test",
            "テスト",
            ["test", "spec", "assert", "mock", "fixture"].as_slice(),
        ),
        (
            "config",
            "設定/ビルド",
            ["config", "toml", "json", "yaml", "webpack", "vite", "cargo"].as_slice(),
        ),
        (
            "compute",
            "計算ロジック",
            ["compute", "base", "offset", "*", "calculate"].as_slice(),
        ),
        (
            "normalize",
            "入力正規化",
            [
                "normalize",
                "trim",
                "tolowercase",
                "touppercase",
                "validate",
            ]
            .as_slice(),
        ),
        (
            "format",
            "出力フォーマット",
            ["format", "tofixed", "intl", "render"].as_slice(),
        ),
        (
            "docs",
            "ドキュメント",
            ["readme", "docs", "markdown", "adr"].as_slice(),
        ),
    ];
    let lower = text.to_lowercase();
    let mut best = ("misc", "その他", 0usize);
    for (label, name, patterns) in labels {
        let score = patterns
            .iter()
            .map(|pat| lower.matches(pat).count())
            .sum::<usize>();
        if score > best.2 {
            best = (label, name, score);
        }
    }
    (best.0.to_owned(), best.1.to_owned(), best.2)
}

fn chunk_text_for_scoring(chunk: &Value) -> String {
    let mut parts = Vec::new();
    parts.push(chunk_file_path(chunk));
    if let Some(header) = chunk.get("header").and_then(Value::as_str) {
        parts.push(header.to_owned());
    }
    for line in chunk_lines(chunk) {
        if line_kind(&line) != "context" {
            let text = line_text(&line);
            if !text.trim().is_empty() {
                parts.push(text.to_owned());
            }
        }
    }
    parts.join("\n")
}

pub fn build_ai_refine_prompt_markdown(doc: &Value, max_chunks_per_group: usize) -> String {
    let mut lines = Vec::new();
    let chunk_map = chunk_map(doc);
    let assignments = assignments_map(doc);
    lines.push("# DiffGR 仮想PR分割のブラッシュアップ依頼".to_owned());
    lines.push(String::new());
    lines.push(
        "目的: 1つの大きい差分を、仮想PR(グループ)に分割してレビューしやすくする。".to_owned(),
    );
    lines.push("制約:".to_owned());
    lines.push("- 全チャンクを必ずどれか1つのグループに割り当てる".to_owned());
    lines.push("- グループ名は日本語（短く、目的が伝わる）".to_owned());
    lines.push("- 各グループはレビュー可能な粒度（大きすぎたら分割、小さすぎたら統合）".to_owned());
    lines.push(String::new());
    lines.push("出力フォーマット（必須）: 次のJSONだけを返してください。".to_owned());
    lines.push("```json".to_owned());
    lines.push("{ \"rename\": { \"g-id\": \"新しい名前\" }, \"move\": [ { \"chunk\": \"chunk_id\", \"to\": \"g-id\" } ] }".to_owned());
    lines.push("```".to_owned());
    lines.push(String::new());
    lines.push("## 現在のグループとチャンク概要".to_owned());
    for group in doc
        .get("groups")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let group_id = group.get("id").and_then(Value::as_str).unwrap_or("");
        let group_name = group.get("name").and_then(Value::as_str).unwrap_or("");
        lines.push(String::new());
        lines.push(format!("### {group_id} / {group_name}"));
        let chunk_ids = assignments.get(group_id).cloned().unwrap_or_default();
        for cid in chunk_ids.iter().take(max_chunks_per_group) {
            let Some(chunk) = chunk_map.get(cid) else {
                continue;
            };
            let mut change_lines = Vec::new();
            for line in chunk_lines(chunk) {
                if line_kind(&line) != "context" {
                    let text = line_text(&line);
                    if !text.trim().is_empty() {
                        change_lines.push(format!("{}: {}", line_kind(&line), text));
                    }
                }
                if change_lines.len() >= 6 {
                    break;
                }
            }
            let preview = if change_lines.is_empty() {
                "(meta-only)".to_owned()
            } else {
                change_lines.join(" / ")
            };
            lines.push(format!(
                "- {} | {} | {} | {}",
                cid,
                chunk_file_path(chunk),
                chunk.get("header").and_then(Value::as_str).unwrap_or(""),
                preview
            ));
        }
        if chunk_ids.len() > max_chunks_per_group {
            lines.push(format!(
                "- ... ({} more)",
                chunk_ids.len() - max_chunks_per_group
            ));
        }
    }
    lines.push(String::new());
    lines.join("\n")
}

pub fn apply_slice_patch(doc: &Value, patch: &Value) -> Result<Value, String> {
    let mut out = doc.clone();
    let rename = patch
        .get("rename")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let moves = patch
        .get("move")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let group_ids = out
        .get("groups")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|group| group.get("id").and_then(Value::as_str).map(str::to_owned))
        .collect::<BTreeSet<_>>();
    let chunk_ids = out
        .get("chunks")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|chunk| chunk.get("id").and_then(Value::as_str).map(str::to_owned))
        .collect::<BTreeSet<_>>();

    if let Some(groups) = out.get_mut("groups").and_then(Value::as_array_mut) {
        for group in groups.iter_mut() {
            let Some(obj) = group.as_object_mut() else {
                continue;
            };
            let id = obj
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned();
            if let Some(new_name) = rename.get(&id).and_then(Value::as_str) {
                obj.insert("name".to_owned(), Value::String(new_name.to_owned()));
            }
        }
    }

    let root = out
        .as_object_mut()
        .ok_or_else(|| "DiffGR document must be object.".to_owned())?;
    let assignments = root
        .entry("assignments".to_owned())
        .or_insert_with(|| Value::Object(Map::new()));
    if !assignments.is_object() {
        *assignments = Value::Object(Map::new());
    }
    for move_item in moves {
        let chunk = move_item
            .get("chunk")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        let to = move_item
            .get("to")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        if chunk.is_empty() || to.is_empty() {
            continue;
        }
        if !group_ids.contains(&to) {
            return Err(format!("Unknown group id in move: {to}"));
        }
        if !chunk_ids.contains(&chunk) {
            return Err(format!("Unknown chunk id in move: {chunk}"));
        }
        let map = assignments.as_object_mut().unwrap();
        for ids in map.values_mut() {
            if let Some(arr) = ids.as_array_mut() {
                arr.retain(|value| value.as_str() != Some(chunk.as_str()));
            }
        }
        map.retain(|_, ids| ids.as_array().map(|arr| !arr.is_empty()).unwrap_or(false));
        let arr = map.entry(to).or_insert_with(|| Value::Array(Vec::new()));
        if !arr.is_array() {
            *arr = Value::Array(Vec::new());
        }
        let arr = arr.as_array_mut().unwrap();
        if !arr
            .iter()
            .any(|value| value.as_str() == Some(chunk.as_str()))
        {
            arr.push(Value::String(chunk));
        }
    }

    let assigned_group_ids = out
        .get("assignments")
        .and_then(Value::as_object)
        .into_iter()
        .flat_map(|m| m.iter())
        .filter(|(_, ids)| ids.as_array().map(|arr| !arr.is_empty()).unwrap_or(false))
        .map(|(group_id, _)| group_id.clone())
        .collect::<BTreeSet<_>>();
    if let Some(groups) = out.get_mut("groups").and_then(Value::as_array_mut) {
        groups.retain(|group| {
            group
                .get("id")
                .and_then(Value::as_str)
                .map(|id| assigned_group_ids.contains(id))
                .unwrap_or(false)
        });
    }
    let root = out.as_object_mut().unwrap();
    let meta = root
        .entry("meta".to_owned())
        .or_insert_with(|| Value::Object(Map::new()));
    if !meta.is_object() {
        *meta = Value::Object(Map::new());
    }
    meta.as_object_mut().unwrap().insert(
        "x-slicePatch".to_owned(),
        json!({"renameCount": rename.len(), "moveCount": patch.get("move").and_then(Value::as_array).map(|v| v.len()).unwrap_or(0)}),
    );
    Ok(out)
}

pub fn prepare_review(
    options: &GenerateOptions,
    autoslice: &AutosliceOptions,
) -> Result<(Value, Vec<String>), String> {
    let base = build_diffgr_document(options)?;
    let (autosliced, warnings) = autoslice_document_by_commits(&base, autoslice)?;
    Ok((refine_group_names_ja(&autosliced), warnings))
}

fn normalized_state(value: &Value) -> Result<Value, String> {
    normalize_state_payload(value.clone())
}

pub fn extract_review_state(doc: &Value) -> Value {
    let mut state = Map::new();
    for key in STATE_KEYS {
        let value = doc
            .get(key)
            .and_then(Value::as_object)
            .map(|obj| Value::Object(obj.clone()))
            .unwrap_or_else(|| Value::Object(Map::new()));
        state.insert(key.to_owned(), value);
    }
    Value::Object(state)
}

pub fn apply_review_state(doc: &Value, state: &Value) -> Result<Value, String> {
    let normalized = normalized_state(state)?;
    let mut out = doc.clone();
    let root = out
        .as_object_mut()
        .ok_or_else(|| "DiffGR document must be object.".to_owned())?;
    let obj = normalized.as_object().unwrap();
    for key in STATE_KEYS {
        let value = obj
            .get(key)
            .cloned()
            .unwrap_or_else(|| Value::Object(Map::new()));
        let keep = key == "reviews" || value.as_object().map(|o| !o.is_empty()).unwrap_or(false);
        if keep {
            root.insert(key.to_owned(), value);
        } else {
            root.remove(key);
        }
    }
    Ok(out)
}

pub fn merge_review_states(
    base: &Value,
    inputs: &[(String, Value)],
) -> Result<(Value, Vec<String>, usize), String> {
    let mut merged = normalized_state(base)?;
    let mut warnings = Vec::new();
    let mut applied = 0usize;
    for (source, input) in inputs {
        let incoming = normalized_state(input)?;
        for section in STATE_KEYS {
            let in_obj = incoming
                .get(section)
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            if section == "reviews" {
                for (key, value) in in_obj {
                    let record = merge_review_record(
                        merged
                            .get(section)
                            .and_then(Value::as_object)
                            .and_then(|m| m.get(&key)),
                        &value,
                        source,
                        &mut warnings,
                        &key,
                    );
                    ensure_state_section(&mut merged, section).insert(key, record);
                    applied += 1;
                }
            } else if section == "groupBriefs" {
                for (key, value) in in_obj {
                    let record = merge_group_brief_record(
                        merged
                            .get(section)
                            .and_then(Value::as_object)
                            .and_then(|m| m.get(&key)),
                        &value,
                        source,
                        &mut warnings,
                        &key,
                    );
                    ensure_state_section(&mut merged, section).insert(key, record);
                    applied += 1;
                }
            } else if section == "threadState" {
                for (key, value) in in_obj {
                    if key == "__files" {
                        let files = ensure_thread_files(&mut merged);
                        if let Some(in_files) = value.as_object() {
                            for (file_key, file_value) in in_files {
                                files.insert(file_key.clone(), file_value.clone());
                                applied += 1;
                            }
                        }
                    } else {
                        ensure_state_section(&mut merged, section).insert(key, value);
                        applied += 1;
                    }
                }
            } else {
                for (key, value) in in_obj {
                    ensure_state_section(&mut merged, section).insert(key, value);
                    applied += 1;
                }
            }
        }
    }
    Ok((merged, warnings, applied))
}

fn ensure_state_section<'a>(state: &'a mut Value, section: &str) -> &'a mut Map<String, Value> {
    let root = state.as_object_mut().expect("state object");
    let value = root
        .entry(section.to_owned())
        .or_insert_with(|| Value::Object(Map::new()));
    if !value.is_object() {
        *value = Value::Object(Map::new());
    }
    value.as_object_mut().unwrap()
}

fn ensure_thread_files(state: &mut Value) -> &mut Map<String, Value> {
    let thread = ensure_state_section(state, "threadState");
    let files = thread
        .entry("__files".to_owned())
        .or_insert_with(|| Value::Object(Map::new()));
    if !files.is_object() {
        *files = Value::Object(Map::new());
    }
    files.as_object_mut().unwrap()
}

fn merge_review_record(
    base: Option<&Value>,
    incoming: &Value,
    source: &str,
    warnings: &mut Vec<String>,
    chunk_id: &str,
) -> Value {
    let Some(in_obj) = incoming.as_object() else {
        warnings.push(format!(
            "{source}: review record must be object for chunk: {chunk_id}"
        ));
        return base.cloned().unwrap_or_else(|| Value::Object(Map::new()));
    };
    let mut out = base.and_then(Value::as_object).cloned().unwrap_or_default();
    if let Some(status) = in_obj.get("status").and_then(Value::as_str) {
        let old = out
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("unreviewed");
        if review_status_precedence(status) >= review_status_precedence(old) {
            out.insert("status".to_owned(), Value::String(status.to_owned()));
        }
    }
    for key in ["comment", "lineComments"] {
        if let Some(value) = in_obj.get(key) {
            if out.get(key).is_some() && out.get(key) != Some(value) {
                warnings.push(format!(
                    "{source}: chunk {key} conflict on chunk {chunk_id}; incoming wins."
                ));
            }
            out.insert(key.to_owned(), value.clone());
        }
    }
    Value::Object(out)
}

fn merge_group_brief_record(
    base: Option<&Value>,
    incoming: &Value,
    source: &str,
    warnings: &mut Vec<String>,
    group_id: &str,
) -> Value {
    let Some(in_obj) = incoming.as_object() else {
        warnings.push(format!(
            "{source}: group brief record must be object for group: {group_id}"
        ));
        return base.cloned().unwrap_or_else(|| Value::Object(Map::new()));
    };
    let mut out = base.and_then(Value::as_object).cloned().unwrap_or_default();
    for (key, value) in in_obj {
        if key == "status" {
            let old = out.get("status").and_then(Value::as_str).unwrap_or("draft");
            if group_brief_status_precedence(value.as_str().unwrap_or("draft"))
                < group_brief_status_precedence(old)
            {
                continue;
            }
        }
        if out.get(key).is_some() && out.get(key) != Some(value) {
            warnings.push(format!(
                "{source}: group brief conflict on {group_id}.{key}; incoming wins."
            ));
        }
        out.insert(key.clone(), value.clone());
    }
    Value::Object(out)
}

fn review_status_precedence(status: &str) -> i64 {
    match status {
        "ignored" => 4,
        "needsReReview" => 3,
        "reviewed" => 2,
        "unreviewed" => 1,
        _ => 0,
    }
}

fn group_brief_status_precedence(status: &str) -> i64 {
    match status {
        "acknowledged" => 4,
        "ready" => 3,
        "stale" => 2,
        "draft" => 1,
        _ => 0,
    }
}

pub fn diff_review_states(base: &Value, incoming: &Value) -> Result<Value, String> {
    let base = normalized_state(base)?;
    let incoming = normalized_state(incoming)?;
    let mut out = Map::new();
    for section in STATE_KEYS {
        let base_map = base
            .get(section)
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let incoming_map = incoming
            .get(section)
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        out.insert(
            section.to_owned(),
            diff_mapping(section, &base_map, &incoming_map),
        );
    }
    Ok(Value::Object(out))
}

fn diff_mapping(section: &str, base: &Map<String, Value>, incoming: &Map<String, Value>) -> Value {
    let mut added = Vec::new();
    let mut removed = Vec::new();
    let mut changed = Vec::new();
    let mut unchanged = Vec::new();
    let mut added_details = Vec::new();
    let mut removed_details = Vec::new();
    let mut changed_details = Vec::new();
    let mut keys = base
        .keys()
        .chain(incoming.keys())
        .cloned()
        .collect::<BTreeSet<_>>();
    if section == "threadState" {
        keys.remove("__files");
    }
    for key in keys {
        if !base.contains_key(&key) {
            added.push(Value::String(key.clone()));
            added_details.push(json!({"key": key, "preview": preview_value(incoming.get(&key)), "selectionToken": selection_token(section, &key)}));
        } else if !incoming.contains_key(&key) {
            removed.push(Value::String(key.clone()));
            removed_details.push(json!({"key": key, "preview": preview_value(base.get(&key)), "selectionToken": selection_token(section, &key)}));
        } else if canonical_json_sorted(base.get(&key).unwrap())
            != canonical_json_sorted(incoming.get(&key).unwrap())
        {
            changed.push(Value::String(key.clone()));
            changed_details.push(json!({"key": key, "beforePreview": preview_value(base.get(&key)), "afterPreview": preview_value(incoming.get(&key)), "selectionToken": selection_token(section, &key)}));
        } else {
            unchanged.push(Value::String(key));
        }
    }
    if section == "threadState" {
        let base_files = base
            .get("__files")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let incoming_files = incoming
            .get("__files")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        for key in base_files
            .keys()
            .chain(incoming_files.keys())
            .cloned()
            .collect::<BTreeSet<_>>()
        {
            let display = format!("__files:{key}");
            let token = selection_token("threadState.__files", &key);
            if !base_files.contains_key(&key) {
                added.push(Value::String(display.clone()));
                added_details.push(json!({"key": display, "preview": preview_value(incoming_files.get(&key)), "selectionToken": token}));
            } else if !incoming_files.contains_key(&key) {
                removed.push(Value::String(display.clone()));
                removed_details.push(json!({"key": display, "preview": preview_value(base_files.get(&key)), "selectionToken": token}));
            } else if canonical_json_sorted(base_files.get(&key).unwrap())
                != canonical_json_sorted(incoming_files.get(&key).unwrap())
            {
                changed.push(Value::String(display.clone()));
                changed_details.push(json!({"key": display, "beforePreview": preview_value(base_files.get(&key)), "afterPreview": preview_value(incoming_files.get(&key)), "selectionToken": token}));
            }
        }
    }
    json!({
        "addedCount": added.len(), "removedCount": removed.len(), "changedCount": changed.len(), "unchangedCount": unchanged.len(),
        "added": added, "removed": removed, "changed": changed, "unchanged": unchanged,
        "addedDetails": added_details, "removedDetails": removed_details, "changedDetails": changed_details,
    })
}

fn selection_token(section: &str, key: &str) -> String {
    format!("{section}:{key}")
}

fn preview_value(value: Option<&Value>) -> String {
    let Some(value) = value else {
        return String::new();
    };
    let rendered = match value {
        Value::String(s) => s.clone(),
        _ => canonical_json_sorted(value),
    };
    if rendered.chars().count() > 96 {
        rendered.chars().take(95).collect::<String>() + "…"
    } else {
        rendered
    }
}

pub fn selection_tokens_from_diff(diff: &Value) -> Vec<String> {
    let mut tokens = Vec::new();
    for section in STATE_KEYS {
        let Some(obj) = diff.get(section).and_then(Value::as_object) else {
            continue;
        };
        for key in ["addedDetails", "removedDetails", "changedDetails"] {
            for item in obj.get(key).and_then(Value::as_array).into_iter().flatten() {
                if let Some(token) = item.get("selectionToken").and_then(Value::as_str) {
                    if !tokens.iter().any(|existing| existing == token) {
                        tokens.push(token.to_owned());
                    }
                }
            }
        }
    }
    tokens
}

pub fn apply_review_state_selection(
    base: &Value,
    other: &Value,
    tokens: &[String],
) -> Result<(Value, usize), String> {
    let mut out = normalized_state(base)?;
    let other = normalized_state(other)?;
    let mut applied = 0usize;
    for token in tokens {
        let Some((section, key)) = token.split_once(':') else {
            return Err(format!("Invalid selection token: {token}"));
        };
        if section == "threadState.__files" {
            let other_files = other
                .get("threadState")
                .and_then(Value::as_object)
                .and_then(|m| m.get("__files"))
                .and_then(Value::as_object);
            let out_files = ensure_thread_files(&mut out);
            if let Some(value) = other_files.and_then(|m| m.get(key)) {
                out_files.insert(key.to_owned(), value.clone());
            } else {
                out_files.remove(key);
            }
            applied += 1;
            continue;
        }
        if !STATE_KEYS.contains(&section) {
            return Err(format!("Unknown selection section: {section}"));
        }
        let other_map = other.get(section).and_then(Value::as_object);
        let out_map = ensure_state_section(&mut out, section);
        if let Some(value) = other_map.and_then(|m| m.get(key)) {
            out_map.insert(key.to_owned(), value.clone());
        } else {
            out_map.remove(key);
        }
        applied += 1;
    }
    Ok((out, applied))
}

pub fn preview_review_state_selection(
    base: &Value,
    other: &Value,
    tokens: &[String],
) -> Result<Value, String> {
    let (next, applied) = apply_review_state_selection(base, other, tokens)?;
    let diff = diff_review_states(base, &next)?;
    Ok(json!({
        "selectedTokens": tokens,
        "appliedCount": applied,
        "resultDiff": diff,
        "changedTokens": selection_tokens_from_diff(&diff),
    }))
}

fn chunk_map(doc: &Value) -> BTreeMap<String, Value> {
    doc.get("chunks")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|chunk| Some((chunk.get("id")?.as_str()?.to_owned(), chunk.clone())))
        .collect()
}

fn assignments_map(doc: &Value) -> BTreeMap<String, Vec<String>> {
    doc.get("assignments")
        .and_then(Value::as_object)
        .into_iter()
        .flat_map(|map| map.iter())
        .map(|(group_id, ids)| {
            (
                group_id.clone(),
                ids.as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|id| id.as_str().map(str::to_owned))
                    .collect(),
            )
        })
        .collect()
}

pub fn split_document_by_group(
    doc: &Value,
    output_dir: &Path,
    include_empty: bool,
) -> Result<OperationSummary, String> {
    let parsed = DiffgrDocument::from_value(doc.clone())?;
    fs::create_dir_all(output_dir)
        .map_err(|err| format!("mkdir {}: {}", output_dir.display(), err))?;
    let mut manifest_groups = Vec::new();
    let mut written = Vec::new();
    for (index, group) in parsed.groups.iter().enumerate() {
        let assigned = parsed
            .assignments
            .get(&group.id)
            .cloned()
            .unwrap_or_default();
        if !include_empty && assigned.is_empty() {
            continue;
        }
        let file_name = build_group_output_filename(index + 1, &group.id, &group.name);
        let path = output_dir.join(&file_name);
        parsed.write_group_review_document(&group.id, &path)?;
        manifest_groups.push(json!({
            "groupId": group.id,
            "groupName": group.name,
            "file": file_name,
            "chunkCount": assigned.len(),
        }));
        written.push(path);
    }
    let manifest =
        json!({"format": "diffgr-review-split-manifest", "version": 1, "groups": manifest_groups});
    let manifest_path = output_dir.join("manifest.json");
    write_json_file(&manifest_path, &manifest)?;
    written.push(manifest_path);
    Ok(OperationSummary {
        message: format!(
            "Wrote {} group review file(s)",
            written.len().saturating_sub(1)
        ),
        written,
        warnings: Vec::new(),
    })
}

fn build_group_output_filename(index: usize, group_id: &str, group_name: &str) -> String {
    fn safe(value: &str, fallback: &str) -> String {
        let mut out = String::new();
        let mut last_dash = false;
        for ch in value.chars() {
            if ch.is_ascii_alphanumeric() || ch == '_' || ch == '-' {
                out.push(ch);
                last_dash = false;
            } else if !last_dash {
                out.push('-');
                last_dash = true;
            }
        }
        let out = out.trim_matches('-').to_owned();
        if out.is_empty() {
            fallback.to_owned()
        } else {
            out
        }
    }
    format!(
        "{index:02}-{}-{}.diffgr.json",
        safe(group_id, &format!("g{index:02}")),
        safe(group_name, "group")
    )
}

pub fn merge_group_review_documents(
    base_doc: &Value,
    review_docs: &[(String, Value)],
    clear_base_reviews: bool,
    strict: bool,
) -> Result<(Value, Vec<String>, usize), String> {
    let mut warnings = Vec::new();
    let mut filtered_inputs = Vec::new();
    let chunk_ids = chunk_map(base_doc).keys().cloned().collect::<BTreeSet<_>>();
    let group_ids = base_doc
        .get("groups")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|group| group.get("id").and_then(Value::as_str).map(str::to_owned))
        .collect::<BTreeSet<_>>();
    let file_keys = chunk_map(base_doc)
        .values()
        .map(|chunk| chunk_file_path(chunk).trim().to_lowercase())
        .filter(|value| !value.is_empty())
        .collect::<BTreeSet<_>>();

    for (source, review_doc) in review_docs {
        let mut state =
            json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
        let reviews = review_doc
            .get("reviews")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        for (chunk_id, record) in reviews {
            if !chunk_ids.contains(&chunk_id) {
                let msg = format!("{source}: unknown chunk id in reviews: {chunk_id}");
                if strict {
                    return Err(msg);
                }
                warnings.push(msg);
                continue;
            }
            ensure_state_section(&mut state, "reviews").insert(chunk_id, record);
        }
        let briefs = review_doc
            .get("groupBriefs")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        for (group_id, record) in briefs {
            if !group_ids.contains(&group_id) {
                let msg = format!("{source}: unknown group id in groupBriefs: {group_id}");
                if strict {
                    return Err(msg);
                }
                warnings.push(msg);
                continue;
            }
            ensure_state_section(&mut state, "groupBriefs").insert(group_id, record);
        }
        if let Some(analysis) = review_doc.get("analysisState").and_then(Value::as_object) {
            for (key, value) in analysis {
                if key == "currentGroupId"
                    && value
                        .as_str()
                        .map(|id| !group_ids.contains(id))
                        .unwrap_or(false)
                {
                    continue;
                }
                if key == "selectedChunkId"
                    && value
                        .as_str()
                        .map(|id| !chunk_ids.contains(id))
                        .unwrap_or(false)
                {
                    continue;
                }
                ensure_state_section(&mut state, "analysisState")
                    .insert(key.clone(), value.clone());
            }
        }
        if let Some(thread) = review_doc.get("threadState").and_then(Value::as_object) {
            for (key, value) in thread {
                if key == "__files" {
                    if let Some(files) = value.as_object() {
                        let out_files = ensure_thread_files(&mut state);
                        for (file_key, file_value) in files {
                            if file_keys.contains(&file_key.trim().to_lowercase()) {
                                out_files.insert(file_key.clone(), file_value.clone());
                            }
                        }
                    }
                } else if key == "selectedLineAnchor" || chunk_ids.contains(key) {
                    ensure_state_section(&mut state, "threadState")
                        .insert(key.clone(), value.clone());
                }
            }
        }
        filtered_inputs.push((source.clone(), state));
    }
    let mut base_state = extract_review_state(base_doc);
    if clear_base_reviews {
        ensure_state_section(&mut base_state, "reviews").clear();
    }
    let (merged_state, merge_warnings, applied) =
        merge_review_states(&base_state, &filtered_inputs)?;
    warnings.extend(merge_warnings);
    let merged_doc = apply_review_state(base_doc, &merged_state)?;
    Ok((merged_doc, warnings, applied))
}

pub fn summarize_document(doc: &Value) -> Value {
    let Ok(parsed) = DiffgrDocument::from_value(doc.clone()) else {
        return json!({"ok": false, "error": "invalid DiffGR document"});
    };
    let counts = parsed.status_counts();
    let metrics = parsed.metrics();
    json!({
        "title": parsed.title,
        "groups": parsed.groups.len(),
        "chunks": parsed.chunks.len(),
        "status": {
            "unreviewed": counts.unreviewed,
            "reviewed": counts.reviewed,
            "needsReReview": counts.needs_re_review,
            "ignored": counts.ignored,
        },
        "metrics": {
            "reviewed": metrics.reviewed,
            "pending": metrics.pending,
            "tracked": metrics.tracked,
            "unassigned": metrics.unassigned,
            "coverageRate": metrics.coverage_rate,
        },
        "files": parsed.file_summaries().into_iter().map(|file| json!({
            "filePath": file.file_path,
            "chunks": file.chunks,
            "reviewed": file.reviewed,
            "pending": file.pending,
            "ignored": file.ignored,
            "adds": file.adds,
            "deletes": file.deletes,
            "comments": file.comments,
        })).collect::<Vec<_>>(),
        "warnings": parsed.warnings,
    })
}

pub fn summarize_state(state: &Value) -> Result<Value, String> {
    let state = normalized_state(state)?;
    let mut counts = Map::new();
    for key in STATE_KEYS {
        counts.insert(
            key.to_owned(),
            Value::Number(Number::from(
                state
                    .get(key)
                    .and_then(Value::as_object)
                    .map(|m| m.len())
                    .unwrap_or(0) as u64,
            )),
        );
    }
    Ok(json!({"counts": counts, "fingerprint": sha256_hex_value(&state)}))
}

pub fn reviewability_report(doc: &Value) -> Result<Value, String> {
    let parsed = DiffgrDocument::from_value(doc.clone())?;
    let mut rows = Vec::new();
    for group in &parsed.groups {
        let ids = parsed
            .assignments
            .get(&group.id)
            .cloned()
            .unwrap_or_default();
        let mut adds = 0usize;
        let mut deletes = 0usize;
        let mut files = BTreeSet::new();
        let mut hotspots = Vec::new();
        for chunk_id in &ids {
            if let Some(chunk) = parsed.chunk_by_id(chunk_id) {
                adds += chunk.add_count;
                deletes += chunk.delete_count;
                files.insert(chunk.file_path.clone());
                if chunk.add_count + chunk.delete_count >= 80 {
                    hotspots.push(json!({"chunkId": chunk.id, "filePath": chunk.file_path, "changes": chunk.add_count + chunk.delete_count}));
                }
            }
        }
        let score = ids.len() + files.len() * 2 + (adds + deletes) / 40 + hotspots.len() * 3;
        let level = if score >= 40 {
            "hard"
        } else if score >= 20 {
            "medium"
        } else {
            "easy"
        };
        rows.push(json!({
            "groupId": group.id,
            "groupName": group.name,
            "chunkCount": ids.len(),
            "fileCount": files.len(),
            "adds": adds,
            "deletes": deletes,
            "hotspots": hotspots,
            "reviewabilityScore": score,
            "level": level,
        }));
    }
    Ok(json!({
        "groupCount": rows.len(),
        "groups": rows,
    }))
}

pub fn coverage_report(doc: &Value) -> Result<Value, String> {
    coverage_report_with_limits(doc, 20, 80)
}

pub fn coverage_report_with_limits(
    doc: &Value,
    max_chunks_per_group: usize,
    max_problem_chunks: usize,
) -> Result<Value, String> {
    let parsed = DiffgrDocument::from_value(doc.clone())?;
    let issue = parsed.analyze_coverage();
    Ok(json!({
        "ok": issue.ok(),
        "unassigned": issue.unassigned,
        "duplicated": issue.duplicated.into_iter().map(|(chunk, groups)| json!({"chunkId": chunk, "groups": groups})).collect::<Vec<_>>(),
        "unknownGroups": issue.unknown_groups,
        "unknownChunks": issue.unknown_chunks,
        "prompt": parsed.coverage_fix_prompt_markdown_limited(max_chunks_per_group, max_problem_chunks),
    }))
}

pub fn build_html_report(
    doc: &Value,
    state: Option<&Value>,
    impact_old: Option<&Value>,
) -> Result<String, String> {
    build_html_report_with_options(doc, state, impact_old, None, None, None, None, None)
}

pub fn build_html_report_with_options(
    doc: &Value,
    state: Option<&Value>,
    impact_old: Option<&Value>,
    impact_state: Option<&Value>,
    group_selector: Option<&str>,
    report_title: Option<&str>,
    save_state_url: Option<&str>,
    save_state_label: Option<&str>,
) -> Result<String, String> {
    if impact_state.is_some() && impact_old.is_none() {
        return Err("--impact-state requires --impact-old".to_owned());
    }
    let composed = if let Some(state) = state {
        apply_review_state(doc, state)?
    } else {
        doc.clone()
    };
    let composed = html_report_doc_with_options(&composed, group_selector, report_title)?;
    let parsed = DiffgrDocument::from_value(composed.clone())?;
    let mut html = parsed.review_html_report();
    if let Some(title) = report_title
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        html = html.replace(
            "<title>DiffGR Review</title>",
            &format!("<title>{}</title>", html_escape(title)),
        );
    }
    if let (Some(old), Some(state_for_impact)) = (impact_old, impact_state) {
        let report = impact_report(old, &composed, Some(state_for_impact))?;
        html.push_str("\n<section><h2>Impact Preview</h2><pre>");
        html.push_str(&html_escape(&format_impact_report_markdown(&report, 50)));
        html.push_str("</pre></section>\n");
    } else if let Some(old) = impact_old {
        let report = impact_report(old, &composed, None)?;
        html.push_str("\n<section><h2>Impact Preview</h2><pre>");
        html.push_str(&html_escape(&format_impact_report_markdown(&report, 50)));
        html.push_str("</pre></section>\n");
    }
    if let Some(url) = save_state_url
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        let label = save_state_label.unwrap_or("Save State");
        let state_json = serde_json::to_string_pretty(&extract_review_state(&composed))
            .map_err(|err| err.to_string())?;
        inject_save_state_widget(&mut html, url, label, &state_json);
    }
    Ok(html)
}

fn html_report_doc_with_options(
    doc: &Value,
    group_selector: Option<&str>,
    report_title: Option<&str>,
) -> Result<Value, String> {
    let mut out = doc.clone();
    if let Some(title) = report_title
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        let root = out
            .as_object_mut()
            .ok_or_else(|| "DiffGR document must be a JSON object".to_owned())?;
        let meta = root
            .entry("meta".to_owned())
            .or_insert_with(|| Value::Object(Map::new()));
        let meta_obj = meta
            .as_object_mut()
            .ok_or_else(|| "meta must be an object".to_owned())?;
        meta_obj.insert("title".to_owned(), Value::String(title.to_owned()));
    }
    let Some(selector) = group_selector
        .map(str::trim)
        .filter(|value| !value.is_empty() && *value != "all")
    else {
        return Ok(out);
    };
    let groups = out
        .get("groups")
        .and_then(Value::as_array)
        .ok_or_else(|| "groups must be an array".to_owned())?;
    let group = groups
        .iter()
        .find(|group| {
            group.get("id").and_then(Value::as_str) == Some(selector)
                || group.get("name").and_then(Value::as_str) == Some(selector)
        })
        .cloned()
        .ok_or_else(|| format!("Group not found: {selector}"))?;
    let group_id = group
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "selected group has no id".to_owned())?
        .to_owned();
    let assigned = out
        .get("assignments")
        .and_then(Value::as_object)
        .and_then(|assignments| assignments.get(&group_id))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let assigned_ids = assigned
        .iter()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect::<BTreeSet<_>>();
    if let Some(root) = out.as_object_mut() {
        let mut assignments = Map::new();
        assignments.insert(group_id.clone(), Value::Array(assigned));
        root.insert("groups".to_owned(), Value::Array(vec![group]));
        root.insert("assignments".to_owned(), Value::Object(assignments));
        if let Some(chunks) = root.get_mut("chunks").and_then(Value::as_array_mut) {
            chunks.retain(|chunk| {
                chunk
                    .get("id")
                    .and_then(Value::as_str)
                    .map(|id| assigned_ids.contains(id))
                    .unwrap_or(false)
            });
        }
    }
    Ok(out)
}

fn inject_save_state_widget(html: &mut String, url: &str, label: &str, state_json: &str) {
    let url_json = serde_json::to_string(url).unwrap_or_else(|_| "\"/api/state\"".to_owned());
    let snippet = format!(
        "\n<script>\nwindow.diffgrState = {};\nasync function diffgrSaveState(){{\n  const r = await fetch({}, {{method:'POST', headers:{{'content-type':'application/json'}}, body: JSON.stringify(window.diffgrState)}});\n  alert(await r.text());\n}}\n</script>\n<div style=\"position:fixed;right:16px;bottom:16px;background:#111;color:#fff;padding:12px;border-radius:8px;z-index:9999\">\n  <button onclick=\"diffgrSaveState()\">{}</button>\n</div>\n",
        state_json,
        url_json,
        html_escape(label),
    );
    if let Some(index) = html.rfind("</body>") {
        html.insert_str(index, &snippet);
    } else {
        html.push_str(&snippet);
    }
}

fn html_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

pub fn export_review_bundle(doc: &Value, output_dir: &Path) -> Result<OperationSummary, String> {
    fs::create_dir_all(output_dir)
        .map_err(|err| format!("mkdir {}: {}", output_dir.display(), err))?;
    let bundle = bundle_doc_without_mutable_state(doc);
    let state = extract_review_state(doc);
    let manifest = build_review_bundle_manifest(&bundle, &state);
    let bundle_path = output_dir.join("bundle.diffgr.json");
    let state_path = output_dir.join("review.state.json");
    let manifest_path = output_dir.join("review.manifest.json");
    write_json_file(&bundle_path, &bundle)?;
    write_json_file(&state_path, &state)?;
    write_json_file(&manifest_path, &manifest)?;
    Ok(OperationSummary {
        written: vec![bundle_path, state_path, manifest_path],
        warnings: Vec::new(),
        message: "Wrote review bundle artifacts".to_owned(),
    })
}

pub fn export_review_bundle_to_paths(
    doc: &Value,
    bundle_path: &Path,
    state_path: &Path,
    manifest_path: &Path,
) -> Result<OperationSummary, String> {
    let bundle = bundle_doc_without_mutable_state(doc);
    let state = extract_review_state(doc);
    let manifest = build_review_bundle_manifest(&bundle, &state);
    write_json_file(bundle_path, &bundle)?;
    write_json_file(state_path, &state)?;
    write_json_file(manifest_path, &manifest)?;
    Ok(OperationSummary {
        written: vec![
            bundle_path.to_path_buf(),
            state_path.to_path_buf(),
            manifest_path.to_path_buf(),
        ],
        warnings: Vec::new(),
        message: "Wrote review bundle artifacts".to_owned(),
    })
}

fn bundle_doc_without_mutable_state(doc: &Value) -> Value {
    let mut out = doc.clone();
    if let Some(root) = out.as_object_mut() {
        root.insert("reviews".to_owned(), Value::Object(Map::new()));
        for key in ["groupBriefs", "analysisState", "threadState"] {
            root.remove(key);
        }
    }
    out
}

pub fn build_review_bundle_manifest(bundle_doc: &Value, state: &Value) -> Value {
    let normalized_state =
        normalized_state(state).unwrap_or_else(|_| extract_review_state(&json!({"reviews": {}})));
    let source_head = bundle_doc
        .get("meta")
        .and_then(|m| m.get("source"))
        .and_then(Value::as_object)
        .and_then(|source| source.get("headSha").or_else(|| source.get("head")))
        .and_then(Value::as_str)
        .unwrap_or("");
    let document_digest = sha256_hex_value(bundle_doc);
    let state_digest = sha256_hex_value(&normalized_state);
    let bundle_digest =
        sha256_hex_value(&json!({"documentDigest": document_digest, "stateDigest": state_digest}));
    json!({
        "format": "diffgr-review-bundle",
        "version": 1,
        "sourceHead": source_head,
        "documentDigest": document_digest,
        "stateDigest": state_digest,
        "bundleDigest": bundle_digest,
        "groupCount": bundle_doc.get("groups").and_then(Value::as_array).map(|v| v.len()).unwrap_or(0),
        "chunkCount": bundle_doc.get("chunks").and_then(Value::as_array).map(|v| v.len()).unwrap_or(0),
        "stateKeys": STATE_KEYS,
    })
}

pub fn verify_review_bundle(
    bundle_doc: &Value,
    state: &Value,
    manifest: &Value,
    expected_head: Option<&str>,
    require_approvals: bool,
) -> Result<BundleVerifyReport, String> {
    let normalized_state = normalized_state(state)?;
    let computed = build_review_bundle_manifest(bundle_doc, &normalized_state);
    let mut errors = Vec::new();
    let mut warnings = validate_state_topology(bundle_doc, &normalized_state);
    if manifest.get("format").and_then(Value::as_str) != Some("diffgr-review-bundle") {
        errors.push(format!(
            "Unsupported manifest format: {:?}",
            manifest.get("format")
        ));
    }
    if manifest.get("version").and_then(Value::as_i64) != Some(1) {
        errors.push(format!(
            "Unsupported manifest version: {:?}",
            manifest.get("version")
        ));
    }
    for key in [
        "sourceHead",
        "documentDigest",
        "stateDigest",
        "bundleDigest",
        "groupCount",
        "chunkCount",
    ] {
        if manifest.get(key).map(canonical_json_sorted)
            != computed.get(key).map(canonical_json_sorted)
        {
            errors.push(format!("Manifest mismatch for {key}."));
        }
    }
    if let Some(expected) = expected_head
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        let actual = computed
            .get("sourceHead")
            .and_then(Value::as_str)
            .unwrap_or("");
        if !actual.is_empty() && actual != expected {
            errors.push(format!(
                "Expected head {expected} but bundle targets {actual}."
            ));
        }
    }
    let mut approval_report = None;
    if require_approvals {
        let composed = apply_review_state(bundle_doc, &normalized_state)?;
        let parsed = DiffgrDocument::from_value(composed)?;
        let report = parsed.approval_report_json_value();
        if !report
            .get("allApproved")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            errors.push("Not all groups are approved.".to_owned());
        }
        approval_report = Some(report);
    }
    if bundle_doc
        .get("reviews")
        .and_then(Value::as_object)
        .map(|m| !m.is_empty())
        .unwrap_or(true)
    {
        errors.push("Bundle document must contain an empty reviews object.".to_owned());
    }
    for key in ["groupBriefs", "analysisState", "threadState"] {
        if bundle_doc.get(key).is_some() {
            errors.push(format!(
                "Bundle document must not contain mutable state key: {key}."
            ));
        }
    }
    warnings.sort();
    warnings.dedup();
    Ok(BundleVerifyReport {
        ok: errors.is_empty(),
        errors,
        warnings,
        computed_manifest: computed,
        approval_report,
    })
}

fn validate_state_topology(bundle_doc: &Value, state: &Value) -> Vec<String> {
    let group_ids = bundle_doc
        .get("groups")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|group| group.get("id").and_then(Value::as_str).map(str::to_owned))
        .collect::<BTreeSet<_>>();
    let chunk_ids = chunk_map(bundle_doc)
        .keys()
        .cloned()
        .collect::<BTreeSet<_>>();
    let file_keys = chunk_map(bundle_doc)
        .values()
        .map(|chunk| chunk_file_path(chunk).trim().to_lowercase())
        .filter(|value| !value.is_empty())
        .collect::<BTreeSet<_>>();
    let mut warnings = Vec::new();
    for chunk_id in state
        .get("reviews")
        .and_then(Value::as_object)
        .into_iter()
        .flat_map(|m| m.keys())
    {
        if !chunk_ids.contains(chunk_id) {
            warnings.push(format!(
                "State review key not found in bundle chunks: {chunk_id}"
            ));
        }
    }
    for group_id in state
        .get("groupBriefs")
        .and_then(Value::as_object)
        .into_iter()
        .flat_map(|m| m.keys())
    {
        if !group_ids.contains(group_id) {
            warnings.push(format!(
                "State groupBrief key not found in bundle groups: {group_id}"
            ));
        }
    }
    if let Some(analysis) = state.get("analysisState").and_then(Value::as_object) {
        if let Some(group_id) = analysis
            .get("currentGroupId")
            .and_then(Value::as_str)
            .filter(|id| !group_ids.contains(*id))
        {
            warnings.push(format!(
                "analysisState.currentGroupId is not present in bundle groups: {group_id}"
            ));
        }
        if let Some(chunk_id) = analysis
            .get("selectedChunkId")
            .and_then(Value::as_str)
            .filter(|id| !chunk_ids.contains(*id))
        {
            warnings.push(format!(
                "analysisState.selectedChunkId is not present in bundle chunks: {chunk_id}"
            ));
        }
    }
    if let Some(thread) = state.get("threadState").and_then(Value::as_object) {
        for (key, value) in thread {
            if key == "__files" {
                for file_key in value.as_object().into_iter().flat_map(|m| m.keys()) {
                    if !file_keys.contains(&file_key.trim().to_lowercase()) {
                        warnings.push(format!(
                            "threadState.__files entry is not present in bundle files: {file_key}"
                        ));
                    }
                }
            } else if key != "selectedLineAnchor" && !chunk_ids.contains(key) {
                warnings.push(format!(
                    "threadState chunk entry is not present in bundle chunks: {key}"
                ));
            }
        }
    }
    warnings
}

#[derive(Clone, Debug, PartialEq)]
struct ChunkMatchInfo {
    old_id: String,
    new_id: String,
    kind: &'static str,
    score: f64,
}

fn stable_fingerprint_for_chunk(chunk: &Value) -> String {
    if let Some(value) = chunk
        .get("fingerprints")
        .and_then(|f| f.get("stable"))
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
    {
        return value.to_owned();
    }
    let lines = chunk_lines(chunk)
        .into_iter()
        .map(|line| {
            json!({
                "kind": line_kind(&line),
                "text": line_text(&line),
            })
        })
        .collect::<Vec<_>>();
    sha256_hex_value(&json!({
        "filePath": chunk_file_path(chunk),
        "lines": lines,
    }))
}

fn content_stable_fingerprint_for_chunk(chunk: &Value) -> String {
    let lines = chunk_lines(chunk)
        .into_iter()
        .map(|line| {
            json!({
                "kind": line_kind(&line),
                "text": line_text(&line),
            })
        })
        .collect::<Vec<_>>();
    sha256_hex_value(&json!({
        "header": chunk_header(chunk).unwrap_or_default(),
        "lines": lines,
    }))
}

fn delta_fingerprint_for_chunk(chunk: &Value) -> String {
    let lines = chunk_lines(chunk)
        .into_iter()
        .filter(|line| matches!(line_kind(line), "add" | "delete"))
        .map(|line| {
            json!({
                "kind": line_kind(&line),
                "text": line_text(&line),
            })
        })
        .collect::<Vec<_>>();
    sha256_hex_value(&json!({
        "filePath": chunk_file_path(chunk),
        "lines": lines,
    }))
}

fn chunk_signature_text(chunk: &Value, include_path: bool) -> String {
    let mut parts = Vec::new();
    if include_path {
        parts.push(chunk_file_path(chunk));
    }
    if let Some(header) = chunk_header(chunk).filter(|value| !value.is_empty()) {
        parts.push(header);
    }
    for line in chunk_lines(chunk) {
        let kind = line_kind(&line);
        if kind.is_empty() || kind == "context" {
            continue;
        }
        parts.push(format!("{}:{}", kind, line_text(&line)));
    }
    parts.join("\n")
}

fn token_set_for_similarity(text: &str) -> BTreeSet<String> {
    let mut set = BTreeSet::new();
    let mut saw_token = false;
    for token in text.split(|ch: char| !ch.is_alphanumeric() && ch != '_' && ch != '-') {
        let token = token.trim().to_lowercase();
        if token.is_empty() {
            continue;
        }
        saw_token = true;
        if !matches!(token.as_str(), "add" | "delete" | "fn") {
            set.insert(token);
        }
    }
    if set.is_empty() && !saw_token && !text.trim().is_empty() {
        set.insert(text.trim().to_lowercase());
    }
    set
}

fn simple_similarity(a: &str, b: &str) -> f64 {
    if a.is_empty() && b.is_empty() {
        return 1.0;
    }
    let a_set = token_set_for_similarity(a);
    let b_set = token_set_for_similarity(b);
    if a_set.is_empty() || b_set.is_empty() {
        return 0.0;
    }
    let shared = a_set.intersection(&b_set).count() as f64;
    (2.0 * shared) / ((a_set.len() + b_set.len()) as f64)
}

fn chunk_range_start(chunk: &Value, side: &str) -> i64 {
    chunk
        .get(side)
        .and_then(|range| range.get("start"))
        .and_then(|value| value_i64(Some(value)))
        .unwrap_or(0)
}

fn pair_by_range_closeness(
    old_ids: &[String],
    new_ids: &[String],
    old_chunks: &BTreeMap<String, Value>,
    new_chunks: &BTreeMap<String, Value>,
) -> Vec<(String, String)> {
    let mut remaining_new = new_ids.iter().cloned().collect::<BTreeSet<_>>();
    let mut pairs = Vec::new();
    for old_id in old_ids {
        let Some(old_chunk) = old_chunks.get(old_id) else {
            continue;
        };
        let mut candidates = remaining_new
            .iter()
            .filter_map(|new_id| {
                let new_chunk = new_chunks.get(new_id)?;
                Some((
                    (chunk_range_start(old_chunk, "new") - chunk_range_start(new_chunk, "new"))
                        .abs(),
                    (chunk_range_start(old_chunk, "old") - chunk_range_start(new_chunk, "old"))
                        .abs(),
                    new_id.clone(),
                ))
            })
            .collect::<Vec<_>>();
        candidates.sort();
        if let Some((_, _, chosen)) = candidates.into_iter().next() {
            remaining_new.remove(&chosen);
            pairs.push((old_id.clone(), chosen));
        }
    }
    pairs
}

fn index_chunks_by<F>(
    chunks: &BTreeMap<String, Value>,
    skip_ids: &BTreeSet<String>,
    f: F,
) -> BTreeMap<String, Vec<String>>
where
    F: Fn(&Value) -> String,
{
    let mut out: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for (id, chunk) in chunks {
        if skip_ids.contains(id) {
            continue;
        }
        out.entry(f(chunk)).or_default().push(id.clone());
    }
    out
}

fn add_fingerprint_matches(
    kind: &'static str,
    old_index: BTreeMap<String, Vec<String>>,
    new_index: BTreeMap<String, Vec<String>>,
    old_chunks: &BTreeMap<String, Value>,
    new_chunks: &BTreeMap<String, Value>,
    used_old: &mut BTreeSet<String>,
    used_new: &mut BTreeSet<String>,
    matches: &mut Vec<ChunkMatchInfo>,
    warnings: &mut Vec<String>,
) {
    for (fingerprint, new_ids) in new_index {
        let old_ids = old_index.get(&fingerprint).cloned().unwrap_or_default();
        let new_ids_unmatched = new_ids
            .into_iter()
            .filter(|id| !used_new.contains(id))
            .collect::<Vec<_>>();
        let old_ids_unmatched = old_ids
            .into_iter()
            .filter(|id| !used_old.contains(id))
            .collect::<Vec<_>>();
        if new_ids_unmatched.is_empty() || old_ids_unmatched.is_empty() {
            continue;
        }
        let pairs = if new_ids_unmatched.len() == 1 && old_ids_unmatched.len() == 1 {
            vec![(old_ids_unmatched[0].clone(), new_ids_unmatched[0].clone())]
        } else if new_ids_unmatched.len() == old_ids_unmatched.len() {
            pair_by_range_closeness(
                &old_ids_unmatched,
                &new_ids_unmatched,
                old_chunks,
                new_chunks,
            )
        } else {
            warnings.push(format!(
                "Ambiguous {kind} match skipped (fp={}..., old={}, new={})",
                fingerprint.chars().take(12).collect::<String>(),
                old_ids_unmatched.len(),
                new_ids_unmatched.len(),
            ));
            Vec::new()
        };
        for (old_id, new_id) in pairs {
            if used_old.contains(&old_id) || used_new.contains(&new_id) {
                continue;
            }
            matches.push(ChunkMatchInfo {
                old_id: old_id.clone(),
                new_id: new_id.clone(),
                kind,
                score: 1.0,
            });
            used_old.insert(old_id);
            used_new.insert(new_id);
        }
    }
}

fn match_chunks_for_rebase(
    old_doc: &Value,
    new_doc: &Value,
    similarity_threshold: f64,
) -> (Vec<ChunkMatchInfo>, Vec<String>) {
    let old_chunks = chunk_map(old_doc);
    let new_chunks = chunk_map(new_doc);
    let mut warnings = Vec::new();
    let mut matches = Vec::new();
    let mut used_old = BTreeSet::new();
    let mut used_new = BTreeSet::new();

    for new_id in new_chunks.keys() {
        if old_chunks.contains_key(new_id) {
            matches.push(ChunkMatchInfo {
                old_id: new_id.clone(),
                new_id: new_id.clone(),
                kind: "strong",
                score: 1.0,
            });
            used_old.insert(new_id.clone());
            used_new.insert(new_id.clone());
        }
    }

    add_fingerprint_matches(
        "stable",
        index_chunks_by(&old_chunks, &used_old, stable_fingerprint_for_chunk),
        index_chunks_by(&new_chunks, &used_new, stable_fingerprint_for_chunk),
        &old_chunks,
        &new_chunks,
        &mut used_old,
        &mut used_new,
        &mut matches,
        &mut warnings,
    );

    add_fingerprint_matches(
        "delta",
        index_chunks_by(&old_chunks, &used_old, delta_fingerprint_for_chunk),
        index_chunks_by(&new_chunks, &used_new, delta_fingerprint_for_chunk),
        &old_chunks,
        &new_chunks,
        &mut used_old,
        &mut used_new,
        &mut matches,
        &mut warnings,
    );

    add_fingerprint_matches(
        "stable",
        index_chunks_by(&old_chunks, &used_old, content_stable_fingerprint_for_chunk),
        index_chunks_by(&new_chunks, &used_new, content_stable_fingerprint_for_chunk),
        &old_chunks,
        &new_chunks,
        &mut used_old,
        &mut used_new,
        &mut matches,
        &mut warnings,
    );

    let threshold = similarity_threshold.clamp(0.0, 0.99);
    if threshold > 0.0 {
        let old_remaining = old_chunks
            .keys()
            .filter(|id| !used_old.contains(*id))
            .cloned()
            .collect::<Vec<_>>();
        let new_remaining = new_chunks
            .keys()
            .filter(|id| !used_new.contains(*id))
            .cloned()
            .collect::<Vec<_>>();
        let mut candidates = Vec::new();
        for new_id in &new_remaining {
            let Some(new_chunk) = new_chunks.get(new_id) else {
                continue;
            };
            let new_text = chunk_signature_text(new_chunk, false);
            let mut best: Option<(f64, String)> = None;
            for old_id in &old_remaining {
                let Some(old_chunk) = old_chunks.get(old_id) else {
                    continue;
                };
                let mut score =
                    simple_similarity(&chunk_signature_text(old_chunk, false), &new_text);
                if chunk_file_path(old_chunk) == chunk_file_path(new_chunk) {
                    score = (score + 0.05).min(1.0);
                }
                if best
                    .as_ref()
                    .map(|(best_score, _)| score > *best_score)
                    .unwrap_or(true)
                {
                    best = Some((score, old_id.clone()));
                }
            }
            if let Some((score, old_id)) = best.filter(|(score, _)| *score >= threshold) {
                candidates.push((ordered_float_key(score), old_id, new_id.clone(), score));
            }
        }
        candidates.sort_by(|a, b| {
            b.0.cmp(&a.0)
                .then_with(|| a.1.cmp(&b.1))
                .then_with(|| a.2.cmp(&b.2))
        });
        for (_, old_id, new_id, score) in candidates {
            if used_old.contains(&old_id) || used_new.contains(&new_id) {
                continue;
            }
            matches.push(ChunkMatchInfo {
                old_id: old_id.clone(),
                new_id: new_id.clone(),
                kind: "similar",
                score,
            });
            used_old.insert(old_id);
            used_new.insert(new_id);
        }
    }

    (matches, warnings)
}

fn ordered_float_key(value: f64) -> i64 {
    (value * 1_000_000.0).round() as i64
}

fn source_head(doc: &Value) -> String {
    doc.get("meta")
        .and_then(Value::as_object)
        .and_then(|meta| meta.get("source"))
        .and_then(Value::as_object)
        .and_then(|source| source.get("headSha").or_else(|| source.get("head")))
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_owned()
}

fn review_status_string(record: &Value) -> String {
    match record.get("status").and_then(Value::as_str).unwrap_or("") {
        "reviewed" => "reviewed".to_owned(),
        "ignored" => "ignored".to_owned(),
        "needsReReview" => "needsReReview".to_owned(),
        _ => "unreviewed".to_owned(),
    }
}

fn state_json_from_rebase_summary(summary: &RebaseSummary) -> Value {
    json!({
        "mappedReviews": summary.mapped_reviews,
        "unmappedReviews": summary.unmapped_reviews,
        "mappedThreadEntries": summary.mapped_thread_entries,
        "matchedStrong": summary.matched_strong,
        "matchedStable": summary.matched_stable,
        "matchedDelta": summary.matched_delta,
        "matchedSimilar": summary.matched_similar,
        "carriedReviews": summary.carried_reviews,
        "carriedReviewed": summary.carried_reviewed,
        "changedToNeedsReReview": summary.changed_to_needs_rereview,
        "unmappedNewChunks": summary.unmapped_new_chunks,
        "warnings": summary.warnings.clone(),
    })
}

pub fn rebase_summary_json(summary: &RebaseSummary) -> Value {
    state_json_from_rebase_summary(summary)
}

pub fn rebase_state(
    old_doc: &Value,
    new_doc: &Value,
    state: &Value,
) -> Result<(Value, RebaseSummary), String> {
    rebase_state_with_options(old_doc, new_doc, state, &RebaseOptions::default())
}

pub fn rebase_state_with_options(
    old_doc: &Value,
    new_doc: &Value,
    state: &Value,
    options: &RebaseOptions,
) -> Result<(Value, RebaseSummary), String> {
    let state = normalized_state(state)?;
    let old_chunks = chunk_map(old_doc);
    let new_chunks = chunk_map(new_doc);
    let (matches, mut warnings) =
        match_chunks_for_rebase(old_doc, new_doc, options.similarity_threshold);
    let id_map = matches
        .iter()
        .map(|m| (m.old_id.clone(), m.new_id.clone()))
        .collect::<BTreeMap<_, _>>();
    let match_by_old = matches
        .iter()
        .map(|m| (m.old_id.clone(), m.clone()))
        .collect::<BTreeMap<_, _>>();

    let mut out = json!({"reviews": {}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
    let mut summary = RebaseSummary::default();
    summary.matched_strong = matches.iter().filter(|m| m.kind == "strong").count();
    summary.matched_stable = matches.iter().filter(|m| m.kind == "stable").count();
    summary.matched_delta = matches.iter().filter(|m| m.kind == "delta").count();
    summary.matched_similar = matches.iter().filter(|m| m.kind == "similar").count();
    summary.unmapped_new_chunks = new_chunks.len().saturating_sub(matches.len());

    if let Some(reviews) = state.get("reviews").and_then(Value::as_object) {
        for (old_id, record) in reviews {
            if let Some(new_id) = id_map.get(old_id) {
                let mut record = record.clone();
                let match_kind = match_by_old.get(old_id).map(|m| m.kind).unwrap_or("strong");
                let status_old = review_status_string(&record);
                if let Some(obj) = record.as_object_mut() {
                    obj.insert("status".to_owned(), Value::String(status_old.clone()));
                    if match_kind == "similar" && status_old == "reviewed" {
                        obj.insert(
                            "status".to_owned(),
                            Value::String("needsReReview".to_owned()),
                        );
                        summary.changed_to_needs_rereview += 1;
                    }
                    if !options.carry_line_comments || !matches!(match_kind, "strong" | "stable") {
                        obj.remove("lineComments");
                    }
                }
                ensure_state_section(&mut out, "reviews").insert(new_id.clone(), record);
                summary.mapped_reviews += 1;
                summary.carried_reviews += 1;
                if status_old == "reviewed" && match_kind != "similar" {
                    summary.carried_reviewed += 1;
                }
            } else {
                summary.unmapped_reviews += 1;
                warnings.push(format!("Review could not be mapped to new chunk: {old_id}"));
            }
        }
    }

    let target_group_ids = if options.preserve_groups {
        old_doc
            .get("groups")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|group| group.get("id").and_then(Value::as_str).map(str::to_owned))
            .collect::<BTreeSet<_>>()
    } else {
        new_doc
            .get("groups")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|group| group.get("id").and_then(Value::as_str).map(str::to_owned))
            .collect::<BTreeSet<_>>()
    };
    let head_changed = {
        let old_head = source_head(old_doc);
        let new_head = source_head(new_doc);
        !old_head.is_empty() && !new_head.is_empty() && old_head != new_head
    };
    if let Some(briefs) = state.get("groupBriefs").and_then(Value::as_object) {
        for (group_id, record) in briefs {
            if target_group_ids.contains(group_id) {
                let mut record = record.clone();
                if head_changed {
                    if let Some(obj) = record.as_object_mut() {
                        obj.insert("status".to_owned(), Value::String("stale".to_owned()));
                        if let Some(approval) =
                            obj.get_mut("approval").and_then(Value::as_object_mut)
                        {
                            approval.insert(
                                "state".to_owned(),
                                Value::String("invalidated".to_owned()),
                            );
                            approval.insert("approved".to_owned(), Value::Bool(false));
                            approval.insert("invalidatedAt".to_owned(), Value::String(now_stamp()));
                            approval.insert("decisionAt".to_owned(), Value::String(now_stamp()));
                            approval.insert(
                                "invalidationReason".to_owned(),
                                Value::String("head_changed".to_owned()),
                            );
                        }
                    }
                }
                ensure_state_section(&mut out, "groupBriefs").insert(group_id.clone(), record);
            } else {
                warnings.push(format!(
                    "Group brief could not be mapped to target group set: {group_id}"
                ));
            }
        }
    }

    if let Some(analysis) = state.get("analysisState").and_then(Value::as_object) {
        for (key, value) in analysis {
            if key == "selectedChunkId" {
                if let Some(new_id) = value.as_str().and_then(|old_id| id_map.get(old_id)) {
                    ensure_state_section(&mut out, "analysisState")
                        .insert(key.clone(), Value::String(new_id.clone()));
                }
                continue;
            }
            if key == "currentGroupId" {
                if value
                    .as_str()
                    .map(|group_id| target_group_ids.contains(group_id))
                    .unwrap_or(false)
                {
                    ensure_state_section(&mut out, "analysisState")
                        .insert(key.clone(), value.clone());
                }
                continue;
            }
            ensure_state_section(&mut out, "analysisState").insert(key.clone(), value.clone());
        }
    }

    let new_file_keys = new_chunks
        .values()
        .map(|chunk| chunk_file_path(chunk).trim().to_lowercase())
        .filter(|value| !value.is_empty())
        .collect::<BTreeSet<_>>();
    if let Some(thread) = state.get("threadState").and_then(Value::as_object) {
        for (key, value) in thread {
            if key == "__files" {
                if let Some(files) = value.as_object() {
                    let filtered = files
                        .iter()
                        .filter(|(file_key, _)| {
                            new_file_keys.contains(&file_key.trim().to_lowercase())
                        })
                        .map(|(file_key, value)| (file_key.clone(), value.clone()))
                        .collect::<Map<_, _>>();
                    if !filtered.is_empty() {
                        ensure_state_section(&mut out, "threadState")
                            .insert(key.clone(), Value::Object(filtered));
                    }
                }
            } else if key == "selectedLineAnchor" {
                if options.carry_line_comments {
                    ensure_state_section(&mut out, "threadState")
                        .insert(key.clone(), value.clone());
                }
            } else if let Some(new_id) = id_map.get(key) {
                ensure_state_section(&mut out, "threadState").insert(new_id.clone(), value.clone());
                summary.mapped_thread_entries += 1;
            }
        }
    }

    // Keep the old summary field names for existing callers, while also exposing Python-compatible counters.
    summary.warnings = warnings;
    Ok((out, summary))
}

pub fn rebase_reviews_document(
    old_doc: &Value,
    new_doc: &Value,
) -> Result<(Value, RebaseSummary), String> {
    rebase_reviews_document_with_options(old_doc, new_doc, &RebaseOptions::default())
}

pub fn rebase_reviews_document_with_options(
    old_doc: &Value,
    new_doc: &Value,
    options: &RebaseOptions,
) -> Result<(Value, RebaseSummary), String> {
    let state = extract_review_state(old_doc);
    let (rebased_state, summary) = rebase_state_with_options(old_doc, new_doc, &state, options)?;
    let mut out = apply_review_state(new_doc, &rebased_state)?;
    if options.preserve_groups {
        let matches = match_chunks_for_rebase(old_doc, new_doc, options.similarity_threshold).0;
        let id_map = matches
            .iter()
            .map(|m| (m.old_id.clone(), m.new_id.clone()))
            .collect::<BTreeMap<_, _>>();
        let mut assignments = Map::new();
        let old_groups = old_doc
            .get("groups")
            .cloned()
            .unwrap_or_else(|| Value::Array(Vec::new()));
        if let Some(groups) = old_groups.as_array() {
            for group in groups {
                if let Some(group_id) = group.get("id").and_then(Value::as_str) {
                    assignments.insert(group_id.to_owned(), Value::Array(Vec::new()));
                }
            }
        }
        for (group_id, old_ids) in assignments_map(old_doc) {
            let Some(items) = assignments.get_mut(&group_id).and_then(Value::as_array_mut) else {
                continue;
            };
            for old_id in old_ids {
                if let Some(new_id) = id_map.get(&old_id) {
                    if !items.iter().any(|value| value.as_str() == Some(new_id)) {
                        items.push(Value::String(new_id.clone()));
                    }
                }
            }
        }
        if let Some(root) = out.as_object_mut() {
            root.insert("groups".to_owned(), old_groups);
            root.insert("assignments".to_owned(), Value::Object(assignments));
        }
    }
    if let Some(meta) = out
        .as_object_mut()
        .and_then(|root| root.get_mut("meta"))
        .and_then(Value::as_object_mut)
    {
        meta.insert(
            "x-reviewRebase".to_owned(),
            state_json_from_rebase_summary(&summary),
        );
    } else if let Some(root) = out.as_object_mut() {
        let mut meta = Map::new();
        meta.insert(
            "x-reviewRebase".to_owned(),
            state_json_from_rebase_summary(&summary),
        );
        root.insert("meta".to_owned(), Value::Object(meta));
    }
    Ok((out, summary))
}

pub fn append_rebase_history_metadata(
    doc: &mut Value,
    old_doc: &Value,
    new_doc: &Value,
    summary: &RebaseSummary,
    label: Option<&str>,
    actor: Option<&str>,
    max_entries: usize,
    max_ids_per_group: usize,
) -> Result<(), String> {
    let impact = impact_report(old_doc, new_doc, None)?;
    let entry = json!({
        "type": "rebase",
        "at": now_stamp(),
        "label": label.unwrap_or("rebase"),
        "actor": actor.unwrap_or("diffgrctl"),
        "summary": {
            "mappedReviews": summary.mapped_reviews,
            "unmappedReviews": summary.unmapped_reviews,
            "mappedThreadEntries": summary.mapped_thread_entries,
            "warnings": summary.warnings.clone(),
        },
    });
    let root = doc
        .as_object_mut()
        .ok_or_else(|| "DiffGR document must be an object".to_owned())?;
    let meta = root
        .entry("meta".to_owned())
        .or_insert_with(|| Value::Object(Map::new()));
    let meta_obj = meta
        .as_object_mut()
        .ok_or_else(|| "meta must be an object".to_owned())?;
    let history = meta_obj
        .entry("x-reviewHistory".to_owned())
        .or_insert_with(|| Value::Array(Vec::new()));
    let history = history
        .as_array_mut()
        .ok_or_else(|| "meta.x-reviewHistory must be an array".to_owned())?;
    history.push(entry);
    if history.len() > max_entries {
        let drop_count = history.len() - max_entries;
        history.drain(0..drop_count);
    }
    let impact_scope = trim_impact_scope(&impact, max_ids_per_group);
    meta_obj.insert("x-impactScope".to_owned(), impact_scope);
    Ok(())
}

fn trim_impact_scope(impact: &Value, max_ids_per_group: usize) -> Value {
    let mut out = impact.clone();
    if let Some(groups) = out.get_mut("groups").and_then(Value::as_array_mut) {
        for group in groups {
            if let Some(obj) = group.as_object_mut() {
                for key in ["chunkIds", "newChunkIds", "changedChunkIds", "oldChunkIds"] {
                    if let Some(values) = obj.get_mut(key).and_then(Value::as_array_mut) {
                        values.truncate(max_ids_per_group);
                    }
                }
            }
        }
    }
    out
}

pub fn approve_groups(
    doc: &Value,
    groups: &[String],
    reviewer: &str,
    force: bool,
) -> Result<Value, String> {
    let mut parsed = DiffgrDocument::from_value(doc.clone())?;
    let target_groups = if groups.is_empty() {
        parsed
            .groups
            .iter()
            .map(|g| g.id.clone())
            .collect::<Vec<_>>()
    } else {
        groups.to_vec()
    };
    for group_id in target_groups {
        parsed.approve_group(&group_id, reviewer, force)?;
    }
    Ok(parsed.raw)
}

pub fn request_changes(
    doc: &Value,
    groups: &[String],
    reviewer: &str,
    comment: &str,
) -> Result<Value, String> {
    let mut parsed = DiffgrDocument::from_value(doc.clone())?;
    let target_groups = if groups.is_empty() {
        parsed
            .groups
            .iter()
            .map(|g| g.id.clone())
            .collect::<Vec<_>>()
    } else {
        groups.to_vec()
    };
    for group_id in target_groups {
        parsed.request_changes_on_group(&group_id, reviewer, comment)?;
    }
    Ok(parsed.raw)
}

pub fn approval_report(doc: &Value) -> Result<Value, String> {
    let parsed = DiffgrDocument::from_value(doc.clone())?;
    Ok(parsed.approval_report_json_value())
}

pub fn impact_report(
    old_doc: &Value,
    new_doc: &Value,
    state: Option<&Value>,
) -> Result<Value, String> {
    let old = DiffgrDocument::from_value(old_doc.clone())?;
    let mut new_value = new_doc.clone();
    if let Some(state) = state {
        new_value = apply_review_state(&new_value, state)?;
    }
    let new = DiffgrDocument::from_value(new_value)?;
    let report = new.impact_against(&old);
    Ok(json!({
        "oldChunkCount": report.old_chunk_count,
        "newChunkCount": report.new_chunk_count,
        "unchangedChunks": report.unchanged,
        "newOnlyChunks": report.new_only,
        "oldOnlyChunks": report.old_only,
        "changedChunks": report.changed,
        "warnings": report.warnings.clone(),
        "groups": report.groups.iter().map(|g| json!({
            "groupId": g.id.clone(),
            "groupName": g.name.clone(),
            "action": g.action.clone(),
            "totalNew": g.total_new,
            "unchanged": g.unchanged,
            "newChunks": g.new_chunks,
            "changed": g.changed,
        })).collect::<Vec<_>>(),
    }))
}

pub fn impact_report_with_options(
    old_doc: &Value,
    new_doc: &Value,
    state: Option<&Value>,
    grouping: &str,
    similarity_threshold: f64,
    max_items_per_group: usize,
) -> Result<Value, String> {
    let mut report = impact_report(old_doc, new_doc, state)?;
    if let Some(obj) = report.as_object_mut() {
        obj.insert("grouping".to_owned(), Value::String(grouping.to_owned()));
        obj.insert("match".to_owned(), json!({
            "similarityThreshold": similarity_threshold,
            "maxItemsPerGroup": max_items_per_group,
            "note": "Native Rust impact report uses stable chunk fingerprints; use --compat-python for byte-compatible Python matching details."
        }));
    }
    Ok(report)
}

pub fn format_impact_report_markdown(report: &Value, max_items: usize) -> String {
    let count = |key: &str| report.get(key).and_then(Value::as_u64).unwrap_or(0);
    let mut out = String::new();
    out.push_str("# DiffGR Impact Report\n\n");
    out.push_str(&format!(
        "- old chunks: {}\n- new chunks: {}\n- unchanged: {}\n- new only: {}\n- old only: {}\n- changed: {}\n\n",
        count("oldChunkCount"),
        count("newChunkCount"),
        count("unchangedChunks"),
        count("newOnlyChunks"),
        count("oldOnlyChunks"),
        count("changedChunks"),
    ));
    if let Some(warnings) = report
        .get("warnings")
        .and_then(Value::as_array)
        .filter(|v| !v.is_empty())
    {
        out.push_str("## Warnings\n\n");
        for warning in warnings.iter().take(max_items) {
            out.push_str(&format!("- {}\n", warning.as_str().unwrap_or("")));
        }
        out.push('\n');
    }
    out.push_str("## Groups\n\n");
    if let Some(groups) = report.get("groups").and_then(Value::as_array) {
        for group in groups.iter().take(max_items) {
            let id = group.get("groupId").and_then(Value::as_str).unwrap_or("");
            let name = group.get("groupName").and_then(Value::as_str).unwrap_or("");
            let action = group.get("action").and_then(Value::as_str).unwrap_or("");
            out.push_str(&format!("### {id} {name}\n\n"));
            out.push_str(&format!("- action: {action}\n"));
            out.push_str(&format!(
                "- total new: {}\n",
                group.get("totalNew").and_then(Value::as_u64).unwrap_or(0)
            ));
            out.push_str(&format!(
                "- unchanged: {}\n",
                group.get("unchanged").and_then(Value::as_u64).unwrap_or(0)
            ));
            out.push_str(&format!(
                "- new chunks: {}\n",
                group.get("newChunks").and_then(Value::as_u64).unwrap_or(0)
            ));
            out.push_str(&format!(
                "- changed chunks: {}\n\n",
                group.get("changed").and_then(Value::as_u64).unwrap_or(0)
            ));
        }
    }
    out
}

pub fn serve_report(
    input: &Path,
    state_path: Option<&Path>,
    impact_old_path: Option<&Path>,
    impact_state_path: Option<&Path>,
    group_selector: Option<&str>,
    report_title: Option<&str>,
    host: &str,
    port: u16,
    open_browser: bool,
) -> Result<(), String> {
    let doc = read_json_file(input)?;
    let state = match state_path {
        Some(path) if path.exists() => Some(read_json_file(path)?),
        _ => None,
    };
    let impact_old = match impact_old_path {
        Some(path) if path.exists() => Some(read_json_file(path)?),
        Some(path) => return Err(format!("{}: impact-old file not found", path.display())),
        None => None,
    };
    let impact_state = match impact_state_path {
        Some(path) if path.exists() => Some(read_json_file(path)?),
        Some(path) => return Err(format!("{}: impact-state file not found", path.display())),
        None => None,
    };
    let html = build_interactive_server_html(
        &doc,
        state.as_ref(),
        impact_old.as_ref(),
        impact_state.as_ref(),
        group_selector,
        report_title,
    )?;
    let listener =
        TcpListener::bind((host, port)).map_err(|err| format!("bind {host}:{port}: {err}"))?;
    let url = format!("http://{host}:{port}/");
    if open_browser {
        let _ = open_path(&url);
    }
    eprintln!("Serving DiffGR report at {url}");
    for stream in listener.incoming() {
        let mut stream = stream.map_err(|err| err.to_string())?;
        handle_http_request(&mut stream, &html, state_path)?;
    }
    Ok(())
}

fn build_interactive_server_html(
    doc: &Value,
    state: Option<&Value>,
    impact_old: Option<&Value>,
    impact_state: Option<&Value>,
    group_selector: Option<&str>,
    report_title: Option<&str>,
) -> Result<String, String> {
    build_html_report_with_options(
        doc,
        state,
        impact_old,
        impact_state,
        group_selector,
        report_title,
        Some("/api/state"),
        Some("Save State"),
    )
}

fn handle_http_request(
    stream: &mut TcpStream,
    html: &str,
    state_path: Option<&Path>,
) -> Result<(), String> {
    let mut buffer = [0u8; 65536];
    let n = stream.read(&mut buffer).map_err(|err| err.to_string())?;
    let request = String::from_utf8_lossy(&buffer[..n]);
    let mut lines = request.lines();
    let first = lines.next().unwrap_or("");
    let mut parts = first.split_whitespace();
    let method = parts.next().unwrap_or("");
    let path = parts.next().unwrap_or("/");
    if method == "GET" && path == "/" {
        respond(
            stream,
            "200 OK",
            "text/html; charset=utf-8",
            html.as_bytes(),
        )?;
    } else if method == "GET" && path == "/api/state" {
        let state = state_path
            .and_then(|path| read_json_file(path).ok())
            .unwrap_or_else(|| json!({}));
        let body = serde_json::to_vec_pretty(&state).map_err(|err| err.to_string())?;
        respond(stream, "200 OK", "application/json; charset=utf-8", &body)?;
    } else if method == "POST" && path == "/api/state" {
        let Some(path) = state_path else {
            respond(
                stream,
                "400 Bad Request",
                "text/plain; charset=utf-8",
                b"No --state path was provided.",
            )?;
            return Ok(());
        };
        let body = request.split("\r\n\r\n").nth(1).unwrap_or("");
        let value: Value = serde_json::from_str(body).map_err(|err| err.to_string())?;
        let state = normalized_state(&value)?;
        write_json_file(path, &state)?;
        respond(
            stream,
            "200 OK",
            "text/plain; charset=utf-8",
            b"Saved state.",
        )?;
    } else {
        respond(
            stream,
            "404 Not Found",
            "text/plain; charset=utf-8",
            b"Not found",
        )?;
    }
    Ok(())
}

fn respond(
    stream: &mut TcpStream,
    status: &str,
    content_type: &str,
    body: &[u8],
) -> Result<(), String> {
    let header = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream
        .write_all(header.as_bytes())
        .map_err(|err| err.to_string())?;
    stream.write_all(body).map_err(|err| err.to_string())?;
    Ok(())
}

fn open_path(value: &str) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        Command::new("cmd")
            .args(["/C", "start", "", value])
            .spawn()
            .map_err(|err| err.to_string())?;
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg(value)
            .spawn()
            .map_err(|err| err.to_string())?;
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new("xdg-open")
            .arg(value)
            .spawn()
            .map_err(|err| err.to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tiny_doc() -> Value {
        build_diffgr_from_diff_text(
            "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1,1 +1,1 @@\n-old\n+new\n",
            "Tiny",
            "base",
            "head",
            "baseSha",
            "headSha",
            "mergeBase",
            true,
        )
        .unwrap()
    }

    #[test]
    fn parse_diff_builds_chunk() {
        let doc = tiny_doc();
        assert_eq!(
            doc.get("chunks").and_then(Value::as_array).unwrap().len(),
            1
        );
        assert!(doc.get("patch").is_some());
    }

    #[test]
    fn state_selection_applies_tokens() {
        let base = json!({"reviews": {"c1": {"status": "reviewed"}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
        let other = json!({"reviews": {"c1": {"status": "needsReReview"}, "c2": {"comment": "x"}}, "groupBriefs": {}, "analysisState": {}, "threadState": {}});
        let (next, applied) =
            apply_review_state_selection(&base, &other, &["reviews:c2".to_owned()]).unwrap();
        assert_eq!(applied, 1);
        assert!(next.get("reviews").and_then(|v| v.get("c2")).is_some());
    }

    #[test]
    fn bundle_manifest_verifies() {
        let doc = tiny_doc();
        let bundle = bundle_doc_without_mutable_state(&doc);
        let state = extract_review_state(&doc);
        let manifest = build_review_bundle_manifest(&bundle, &state);
        let report = verify_review_bundle(&bundle, &state, &manifest, None, false).unwrap();
        assert!(report.ok);
    }
}

pub fn apply_layout(doc: &Value, layout: &Value) -> Result<(Value, Vec<String>), String> {
    let mut out = doc.clone();
    let layout = layout
        .as_object()
        .ok_or_else(|| "Layout JSON must be an object.".to_owned())?;
    let mut warnings = Vec::new();
    let known_chunk_ids = chunk_map(&out).keys().cloned().collect::<BTreeSet<_>>();

    if let Some(raw_groups) = layout.get("groups") {
        let groups = raw_groups
            .as_array()
            .ok_or_else(|| "'groups' must be a JSON array.".to_owned())?;
        let mut normalized = Vec::new();
        let mut seen = BTreeSet::new();
        for (index, raw) in groups.iter().enumerate() {
            let obj = raw
                .as_object()
                .ok_or_else(|| "Each group must be an object.".to_owned())?;
            let id = obj.get("id").and_then(Value::as_str).unwrap_or("").trim();
            let name = obj.get("name").and_then(Value::as_str).unwrap_or("").trim();
            if id.is_empty() {
                return Err(format!("Group missing 'id': {raw}"));
            }
            if name.is_empty() {
                return Err(format!("Group '{id}' missing 'name'"));
            }
            if !seen.insert(id.to_owned()) {
                return Err(format!("Duplicate group id: {id}"));
            }
            let tags = obj
                .get("tags")
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(Value::as_str)
                        .map(|s| Value::String(s.to_owned()))
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default();
            normalized.push(json!({
                "id": id,
                "name": name,
                "order": obj.get("order").and_then(Value::as_i64).unwrap_or((index + 1) as i64),
                "tags": tags,
            }));
        }
        let valid_group_ids = normalized
            .iter()
            .filter_map(|g| g.get("id").and_then(Value::as_str).map(str::to_owned))
            .collect::<BTreeSet<_>>();
        let root = out
            .as_object_mut()
            .ok_or_else(|| "DiffGR document must be object.".to_owned())?;
        root.insert("groups".to_owned(), Value::Array(normalized));
        if let Some(assignments) = root.get_mut("assignments").and_then(Value::as_object_mut) {
            assignments.retain(|gid, value| valid_group_ids.contains(gid) && value.is_array());
        }
        if let Some(briefs) = root.get_mut("groupBriefs").and_then(Value::as_object_mut) {
            briefs.retain(|gid, _| valid_group_ids.contains(gid));
        }
    }

    if let Some(raw_assignments) = layout.get("assignments") {
        let raw_assignments = raw_assignments
            .as_object()
            .ok_or_else(|| "'assignments' must be a JSON object.".to_owned())?;
        let group_ids = out
            .get("groups")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|g| g.get("id").and_then(Value::as_str).map(str::to_owned))
            .collect::<BTreeSet<_>>();
        let mut new_assignments = Map::new();
        let mut assigned = BTreeSet::new();
        for (gid, raw_ids) in raw_assignments {
            let Some(ids) = raw_ids.as_array() else {
                return Err(format!("assignments['{gid}'] must be a list."));
            };
            if !group_ids.contains(gid) {
                warnings.push(format!(
                    "assignments references unknown group '{gid}' — skipped"
                ));
                continue;
            }
            let mut valid = Vec::new();
            for cid in ids {
                let cid = cid.as_str().unwrap_or("").to_owned();
                if !known_chunk_ids.contains(&cid) {
                    warnings.push(format!(
                        "assignments['{gid}'] references unknown chunk '{}' — skipped",
                        short_token(&cid)
                    ));
                    continue;
                }
                if !assigned.insert(cid.clone()) {
                    warnings.push(format!(
                        "Chunk '{}' assigned to multiple groups — keeping first",
                        short_token(&cid)
                    ));
                    continue;
                }
                valid.push(Value::String(cid));
            }
            if !valid.is_empty() {
                new_assignments.insert(gid.clone(), Value::Array(valid));
            }
        }
        let unassigned = known_chunk_ids.difference(&assigned).count();
        if unassigned > 0 {
            warnings.push(format!("{unassigned} chunk(s) not assigned to any group"));
        }
        out.as_object_mut()
            .unwrap()
            .insert("assignments".to_owned(), Value::Object(new_assignments));
    }

    if let Some(raw_briefs) = layout.get("groupBriefs") {
        let raw_briefs = raw_briefs
            .as_object()
            .ok_or_else(|| "'groupBriefs' must be a JSON object.".to_owned())?;
        let root = out.as_object_mut().unwrap();
        let briefs = root
            .entry("groupBriefs".to_owned())
            .or_insert_with(|| Value::Object(Map::new()));
        if !briefs.is_object() {
            *briefs = Value::Object(Map::new());
        }
        let briefs = briefs.as_object_mut().unwrap();
        for (gid, raw) in raw_briefs {
            let raw = raw
                .as_object()
                .ok_or_else(|| format!("groupBriefs['{gid}'] must be a JSON object."))?;
            let entry = briefs
                .entry(gid.clone())
                .or_insert_with(|| Value::Object(Map::new()));
            if !entry.is_object() {
                *entry = Value::Object(Map::new());
            }
            let entry = entry.as_object_mut().unwrap();
            for (key, value) in raw {
                entry.insert(key.clone(), value.clone());
            }
        }
    }
    Ok((out, warnings))
}

fn short_token(value: &str) -> String {
    let prefix = value.chars().take(16).collect::<String>();
    if value.chars().count() > 16 {
        prefix + "…"
    } else {
        prefix
    }
}
