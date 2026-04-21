use diffgr_gui::model::DiffgrDocument;
use diffgr_gui::{ops, vpr};
use serde_json::{json, Value};
use std::env;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

fn main() {
    if let Err(error) = run() {
        eprintln!("[error] {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let args = env::args().skip(1).collect::<Vec<_>>();
    if args.is_empty() || has(&args, "--help") || has(&args, "-h") {
        print_usage();
        return Ok(());
    }
    let command = &args[0];
    let rest = &args[1..];
    match command.as_str() {
        "generate" | "generate-diffgr" | "generate_diffgr" => cmd_generate(rest),
        "autoslice" | "autoslice-diffgr" | "autoslice_diffgr" => cmd_autoslice(rest),
        "refine" | "refine-slices" | "refine_slices" => cmd_refine(rest),
        "apply-slice-patch" | "apply_slice_patch" => cmd_apply_slice_patch(rest),
        "apply-layout" | "apply-diffgr-layout" | "apply_diffgr_layout" => cmd_apply_layout(rest),
        "prepare" | "prepare-review" | "prepare_review" => cmd_prepare(rest),
        "summarize" | "summarize-diffgr" | "summarize_diffgr" => cmd_summarize(rest),
        "summarize-state" | "summarize-diffgr-state" | "summarize_diffgr_state" => {
            cmd_summarize_state(rest)
        }
        "extract-state" | "extract-diffgr-state" | "extract_diffgr_state" => {
            cmd_extract_state(rest)
        }
        "apply-state" | "apply-diffgr-state" | "apply_diffgr_state" => cmd_apply_state(rest),
        "apply-state-diff" | "apply-diffgr-state-diff" | "apply_diffgr_state_diff" => {
            cmd_apply_state_diff(rest)
        }
        "diff-state" | "diff-diffgr-state" | "diff_diffgr_state" => cmd_diff_state(rest),
        "merge-state" | "merge-diffgr-state" | "merge_diffgr_state" => cmd_merge_state(rest),
        "state-apply-preview" => cmd_state_apply(rest, true),
        "state-apply" => cmd_state_apply(rest, false),
        "split-group-reviews" | "split_group_reviews" => cmd_split_group_reviews(rest),
        "merge-group-reviews" | "merge_group_reviews" => cmd_merge_group_reviews(rest),
        "impact-report" | "impact_report" => cmd_impact_report(rest),
        "preview-rebased-merge" | "preview_rebased_merge" => cmd_preview_rebased_merge(rest),
        "rebase-state" | "rebase-diffgr-state" | "rebase_diffgr_state" => cmd_rebase_state(rest),
        "rebase-reviews" | "rebase_reviews" => cmd_rebase_reviews(rest),
        "export-html" | "export-diffgr-html" | "export_diffgr_html" => cmd_export_html(rest),
        "serve-html" | "serve-diffgr-report" | "serve_diffgr_report" => cmd_serve_html(rest),
        "export-bundle" | "export-review-bundle" | "export_review_bundle" => {
            cmd_export_bundle(rest)
        }
        "verify-bundle" | "verify-review-bundle" | "verify_review_bundle" => {
            cmd_verify_bundle(rest)
        }
        "approve" | "approve-virtual-pr" | "approve_virtual_pr" => cmd_approve(rest),
        "request-changes" | "request_changes" => cmd_request_changes(rest),
        "check-approval" | "check-virtual-pr-approval" | "check_virtual_pr_approval" => {
            cmd_check_approval(rest)
        }
        "coverage" | "check-virtual-pr-coverage" | "check_virtual_pr_coverage" => {
            cmd_coverage(rest)
        }
        "reviewability" | "summarize-reviewability" | "summarize_reviewability" => {
            cmd_reviewability(rest)
        }
        "virtual-pr-review" | "vpr-review" | "review-gate" => cmd_virtual_pr_review(rest),
        "run-agent" | "run-agent-cli" | "run_agent_cli" => cmd_run_agent(rest),
        "view" | "view-diffgr" | "view_diffgr" => cmd_view(rest),
        "view-app" | "view-diffgr-app" | "view_diffgr_app" => cmd_view_app(rest),
        "quality-review" | "self-review" | "gui-quality" => cmd_quality_review(rest),
        "parity-audit" | "python-parity-audit" => cmd_parity_audit(rest),
        _ => Err(format!(
            "Unknown command: {command}\nRun `diffgrctl --help` for commands."
        )),
    }
}

fn print_usage() {
    println!(
        "{}",
        r#"diffgrctl - Rust/Cargo replacement for Python DiffGR scripts

Commands:
  generate                 Git base/feature -> .diffgr.json
  autoslice                Assign chunks to virtual PR groups by commit
  refine                   Heuristic group rename + optional AI prompt
  apply-slice-patch        Apply {rename, move} JSON patch
  apply-layout             Apply layout JSON groups/assignments/groupBriefs
  prepare                  generate -> autoslice -> refine
  summarize                Document summary
  summarize-state          Standalone review.state.json summary
  extract-state            Extract reviews/groupBriefs/analysisState/threadState
  apply-state              Apply review.state.json to a DiffGR document
  apply-state-diff         Apply selected state diff tokens, with optional impact plan
  diff-state               Diff two state JSON files and emit selection tokens
  merge-state              Merge state JSON files with precedence rules
  state-apply-preview      Preview selection-token state apply
  state-apply              Apply selection-token state apply
  split-group-reviews      Split one DiffGR into per-group review files
  merge-group-reviews      Merge per-group review files back into base
  impact-report            old/new DiffGR impact report
  preview-rebased-merge    Impact-aware state rebase + diff/tokens preview
  rebase-state             Rebase standalone state from old to new DiffGR
  rebase-reviews           Rebase embedded review state from old to new DiffGR
  export-html              Static HTML report
  serve-html               Local HTTP report with /api/state save endpoint
  export-bundle            bundle.diffgr.json + review.state.json + manifest
  verify-bundle            Verify immutable review bundle artifacts
  approve                  Approve groups
  request-changes          Record changes requested for groups
  check-approval           Approval report
  coverage                 Virtual PR coverage check + AI fix prompt
  reviewability            Per-group reviewability summary
  virtual-pr-review        Virtual PR readiness gate, risk queue, and reviewer prompt
  run-agent                Invoke external AI CLI and normalize slice patch JSON
  view                     Terminal text summary/viewer fallback
  view-app                 Launch native GUI, or map --once/--ui prompt to terminal view
  quality-review           Self-review Python parity, GUI quality, and UT assets
  parity-audit             List every Python scripts/*.py entry and its Rust replacement

Python-compatible aliases are built in. Examples:
  generate-diffgr, autoslice-diffgr, refine-slices, prepare-review
  apply-diffgr-layout, apply-diffgr-state, diff-diffgr-state, merge-diffgr-state
  export-diffgr-html, serve-diffgr-report, export-review-bundle, verify-review-bundle
  approve-virtual-pr, check-virtual-pr-coverage, view-diffgr, view-diffgr-app

Most commands use Python-compatible option names such as --input, --output, --state,
--base, --feature, --old, --new, --group, --all, --json. `run-agent` also accepts --schema and --timeout.
"#
    );
}

fn cmd_generate(args: &[String]) -> Result<(), String> {
    let repo = path_opt(args, "--repo").unwrap_or_else(|| PathBuf::from("."));
    let output = resolve_relative_to(
        &repo,
        path_opt(args, "--output").unwrap_or_else(|| PathBuf::from("out/sample-ts20.diffgr.json")),
    );
    let options = ops::GenerateOptions {
        repo: repo.clone(),
        base: opt(args, "--base").unwrap_or_else(|| "samples/ts20-base".to_owned()),
        feature: opt(args, "--feature").unwrap_or_else(|| "samples/ts20-feature-5pr".to_owned()),
        title: opt(args, "--title").unwrap_or_else(|| {
            "DiffGR sample from samples/ts20-base...samples/ts20-feature-5pr".to_owned()
        }),
        include_patch: !has(args, "--no-patch"),
    };
    let summary = ops::generate_to_file(&options, &output)?;
    println!("{}", summary.message);
    Ok(())
}

fn cmd_autoslice(args: &[String]) -> Result<(), String> {
    let options = autoslice_options(args);
    let input = resolve_relative_to(
        &options.repo,
        path_opt(args, "--input")
            .unwrap_or_else(|| PathBuf::from("samples/diffgr/ts20-5pr.diffgr.json")),
    );
    let output = resolve_relative_to(
        &options.repo,
        path_opt(args, "--output")
            .unwrap_or_else(|| PathBuf::from("samples/diffgr/ts20-5pr.autosliced.diffgr.json")),
    );
    let doc = ops::read_json_file(&input)?;
    let (out, warnings) = ops::autoslice_document_by_commits(&doc, &options)?;
    ops::write_json_file(&output, &out)?;
    let groups = out
        .get("groups")
        .and_then(Value::as_array)
        .map(|v| v.len())
        .unwrap_or(0);
    let unassigned = ops::coverage_report(&out)
        .ok()
        .and_then(|v| {
            v.get("unassigned")
                .and_then(Value::as_array)
                .map(|a| a.len())
        })
        .unwrap_or(0);
    println!("Wrote: {}", output.display());
    println!("Groups: {groups}");
    println!("Unassigned: {unassigned}");
    for warning in warnings {
        eprintln!("[warn] {warning}");
    }
    Ok(())
}

fn cmd_refine(args: &[String]) -> Result<(), String> {
    let root = PathBuf::from(".");
    let input = resolve_relative_to(
        &root,
        path_opt(args, "--input")
            .unwrap_or_else(|| PathBuf::from("samples/diffgr/ts20-5pr.autosliced.diffgr.json")),
    );
    let output = if has(args, "--stdout") || has(args, "--no-output") {
        None
    } else {
        Some(resolve_relative_to(
            &root,
            path_opt(args, "--output")
                .unwrap_or_else(|| PathBuf::from("samples/diffgr/ts20-5pr.refined.diffgr.json")),
        ))
    };
    let doc = ops::read_json_file(&input)?;
    let refined = ops::refine_group_names_ja(&doc);
    if !has(args, "--no-prompt") {
        let prompt_path = resolve_relative_to(
            &root,
            path_opt(args, "--write-prompt")
                .unwrap_or_else(|| PathBuf::from("samples/diffgr/ts20-5pr.refine-prompt.md")),
        );
        let max = opt_usize(args, "--max-chunks-per-group", 30);
        ops::write_text_file(
            &prompt_path,
            &ops::build_ai_refine_prompt_markdown(&refined, max),
        )?;
        println!("Wrote prompt: {}", prompt_path.display());
    }
    if let Some(output) = output {
        ops::write_json_file(&output, &refined)?;
        println!("Wrote: {}", output.display());
    } else {
        print_json(&refined)?;
    }
    Ok(())
}

fn cmd_apply_slice_patch(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let patch = path_required(args, "--patch")?;
    let output = path_required(args, "--output")?;
    let doc = ops::read_json_file(&input)?;
    let patch = ops::read_json_file(&patch)?;
    let out = ops::apply_slice_patch(&doc, &patch)?;
    ops::write_json_file(&output, &out)?;
    println!("Wrote: {}", output.display());
    Ok(())
}

fn cmd_apply_layout(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let layout = path_required(args, "--layout")?;
    let output = path_required(args, "--output")?;
    let doc = ops::read_json_file(&input)?;
    let layout = ops::read_json_file(&layout)?;
    let (out, warnings) = ops::apply_layout(&doc, &layout)?;
    ops::write_json_file(&output, &out)?;
    for warning in warnings {
        eprintln!("[warn] {warning}");
    }
    println!("Wrote: {}", output.display());
    Ok(())
}

fn cmd_prepare(args: &[String]) -> Result<(), String> {
    let output = path_required(args, "--output")?;
    let generate = ops::GenerateOptions {
        repo: path_opt(args, "--repo").unwrap_or_else(|| PathBuf::from(".")),
        base: opt(args, "--base").unwrap_or_else(|| "samples/ts20-base".to_owned()),
        feature: opt(args, "--feature").unwrap_or_else(|| "samples/ts20-feature-5pr".to_owned()),
        title: opt(args, "--title").unwrap_or_else(|| "DiffGR review bundle".to_owned()),
        include_patch: !has(args, "--no-patch"),
    };
    let auto = autoslice_options(args);
    let (doc, warnings) = ops::prepare_review(&generate, &auto)?;
    ops::write_json_file(&output, &doc)?;
    println!("Wrote: {}", output.display());
    for warning in warnings {
        eprintln!("[warn] {warning}");
    }
    Ok(())
}

fn cmd_summarize(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let doc = ops::read_json_file(&input)?;
    let summary = ops::summarize_document(&doc);
    if has(args, "--json") || path_opt(args, "--output").is_some() {
        write_or_print_json(args, &summary)
    } else {
        println!(
            "{}",
            serde_json::to_string_pretty(&summary).map_err(|e| e.to_string())?
        );
        Ok(())
    }
}

fn cmd_summarize_state(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let state = ops::read_json_file(&input)?;
    let summary = ops::summarize_state(&state)?;
    write_or_print_json(args, &summary)
}

fn cmd_extract_state(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let doc = ops::read_json_file(&input)?;
    let state = ops::extract_review_state(&doc);
    if let Some(output) = path_opt(args, "--output") {
        ops::write_json_file(&output, &state)?;
        println!("Wrote: {}", output.display());
    } else {
        print_json(&state)?;
    }
    Ok(())
}

fn cmd_apply_state(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let state = path_required(args, "--state")?;
    let output = path_required(args, "--output")?;
    let doc = ops::read_json_file(&input)?;
    let state = ops::read_json_file(&state)?;
    let out = ops::apply_review_state(&doc, &state)?;
    ops::write_json_file(&output, &out)?;
    println!("Wrote: {}", output.display());
    Ok(())
}

fn cmd_apply_state_diff(args: &[String]) -> Result<(), String> {
    let base_path = path_required(args, "--base")?;
    let base_state = ops::read_json_file(&base_path)?;
    let preview = has(args, "--preview");
    let output = path_opt(args, "--output");
    if !preview && output.is_none() {
        return Err("--output is required unless --preview is set".to_owned());
    }

    let (next_state, report, tokens, source_label) = if has(args, "--impact-old")
        || has(args, "--impact-new")
        || has(args, "--impact-plan")
    {
        if !repeated(args, "--select").is_empty()
            || !repeated(args, "--token").is_empty()
            || opt(args, "--tokens").is_some()
        {
            return Err("--select/--token/--tokens cannot be combined with --impact-old/--impact-new/--impact-plan".to_owned());
        }
        let old = ops::read_json_file(&path_required(args, "--impact-old")?)?;
        let new = ops::read_json_file(&path_required(args, "--impact-new")?)?;
        let plan = opt(args, "--impact-plan")
            .ok_or_else(|| "--impact-plan is required with --impact-old/--impact-new".to_owned())?;
        let (rebased, summary) = ops::rebase_state(&old, &new, &base_state)?;
        let current = ops::extract_review_state(&new);
        let diff = ops::diff_review_states(&current, &rebased)?;
        let mut tokens = ops::selection_tokens_from_diff(&diff);
        tokens.retain(|token| match plan.as_str() {
            "handoffs" => token.starts_with("groupBriefs:"),
            "reviews" => token.starts_with("reviews:"),
            "ui" => token.starts_with("analysisState:") || token.starts_with("threadState:"),
            "all" => true,
            _ => true,
        });
        let preview_report = ops::preview_review_state_selection(&current, &rebased, &tokens)?;
        let (next, _) = ops::apply_review_state_selection(&current, &rebased, &tokens)?;
        let report = json!({"preview": preview_report, "rebase": {"mappedReviews": summary.mapped_reviews, "unmappedReviews": summary.unmapped_reviews, "mappedThreadEntries": summary.mapped_thread_entries, "warnings": summary.warnings.clone()}});
        (next, report, tokens, format!("impact plan {plan}"))
    } else {
        let other_path = path_required_any(args, &["--other", "--incoming", "--state"])?;
        let other = ops::read_json_file(&other_path)?;
        let mut tokens = repeated(args, "--select");
        tokens.extend(repeated(args, "--token"));
        if let Some(value) = opt(args, "--tokens") {
            tokens.extend(
                value
                    .split(',')
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                    .map(str::to_owned),
            );
        }
        if tokens.is_empty() {
            return Err("At least one --select/--token/--tokens item is required".to_owned());
        }
        let report = ops::preview_review_state_selection(&base_state, &other, &tokens)?;
        let (next, _) = ops::apply_review_state_selection(&base_state, &other, &tokens)?;
        (next, report, tokens, other_path.display().to_string())
    };

    if let Some(output) = output.filter(|_| !preview) {
        ops::write_json_file(&output, &next_state)?;
        println!("Wrote: {}", output.display());
    } else {
        println!("Preview: {source_label}");
    }
    if has(args, "--json-summary") || preview {
        write_or_print_json(
            args,
            &json!({"source": source_label, "selection": tokens, "report": report}),
        )?;
    } else {
        println!("Selection: {}", tokens.join(" "));
    }
    Ok(())
}

fn cmd_diff_state(args: &[String]) -> Result<(), String> {
    let base_path = path_required_any(args, &["--base", "--input"])?;
    let incoming_path = path_required_any(args, &["--incoming", "--other", "--state"])?;
    let base = ops::read_json_file(&base_path)?;
    let incoming = ops::read_json_file(&incoming_path)?;
    let diff = ops::diff_review_states(&base, &incoming)?;
    if has(args, "--tokens-only") || has(args, "--tokens") {
        for token in ops::selection_tokens_from_diff(&diff) {
            println!("{token}");
        }
        return Ok(());
    }
    if has(args, "--json") || path_opt(args, "--output").is_some() {
        write_or_print_json(args, &diff)
    } else {
        println!("Base: {}", base_path.display());
        println!("Other: {}", incoming_path.display());
        print_state_diff_text(&diff);
        Ok(())
    }
}

fn cmd_merge_state(args: &[String]) -> Result<(), String> {
    let base_path = path_required(args, "--base")?;
    let output = path_opt(args, "--output");
    if !has(args, "--preview") && output.is_none() {
        return Err("--output is required unless --preview is used".to_owned());
    }
    let mut inputs = repeated_paths(args, "--input");
    for dir in repeated_paths(args, "--input-dir") {
        inputs.extend(read_diffgr_jsons_in_dir(&dir)?);
    }
    for pattern in repeated(args, "--input-glob") {
        inputs.extend(expand_simple_glob(&pattern)?);
    }
    if inputs.is_empty() {
        return Err("merge-state requires --input path, repeatable".to_owned());
    }
    let base = ops::read_json_file(&base_path)?;
    let mut states = Vec::new();
    for path in inputs {
        states.push((path.display().to_string(), ops::read_json_file(&path)?));
    }
    let (merged, warnings, applied) = ops::merge_review_states(&base, &states)?;
    if has(args, "--preview") || output.is_none() {
        print_json(&json!({"applied": applied, "warnings": warnings.clone(), "merged": merged}))?;
    } else if let Some(output) = output {
        ops::write_json_file(&output, &merged)?;
        println!("Wrote: {}", output.display());
        println!("Applied: {applied}");
        for warning in &warnings {
            eprintln!("[warn] {warning}");
        }
    }
    if has(args, "--json-summary") {
        print_json(&json!({"applied": applied, "warnings": warnings.clone()}))?;
    }
    Ok(())
}

fn cmd_state_apply(args: &[String], preview: bool) -> Result<(), String> {
    let base_path = path_required_any(args, &["--base", "--input"])?;
    let incoming_path = path_required_any(args, &["--incoming", "--other", "--state"])?;
    let tokens = tokens_arg(args)?;
    let base = ops::read_json_file(&base_path)?;
    let incoming = ops::read_json_file(&incoming_path)?;
    if preview {
        let report = ops::preview_review_state_selection(&base, &incoming, &tokens)?;
        write_or_print_json(args, &report)
    } else {
        let output = path_required(args, "--output")?;
        let (state, applied) = ops::apply_review_state_selection(&base, &incoming, &tokens)?;
        ops::write_json_file(&output, &state)?;
        println!("Wrote: {}", output.display());
        println!("Applied: {applied}");
        Ok(())
    }
}

fn cmd_split_group_reviews(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let output_dir = path_required(args, "--output-dir")?;
    let doc = ops::read_json_file(&input)?;
    let manifest_name = opt(args, "--manifest").unwrap_or_else(|| "manifest.json".to_owned());
    let summary = ops::split_document_by_group(&doc, &output_dir, has(args, "--include-empty"))?;
    if manifest_name != "manifest.json" {
        let default_manifest = output_dir.join("manifest.json");
        let custom_manifest = output_dir.join(&manifest_name);
        let manifest = ops::read_json_file(&default_manifest)?;
        ops::write_json_file(&custom_manifest, &manifest)?;
        let _ = std::fs::remove_file(&default_manifest);
    }
    println!("{}", summary.message);
    for path in summary.written {
        println!("Wrote: {}", path.display());
    }
    Ok(())
}

fn cmd_merge_group_reviews(args: &[String]) -> Result<(), String> {
    let base = path_required(args, "--base")?;
    let output = path_required(args, "--output")?;
    let mut inputs = repeated_paths(args, "--input");
    for dir in repeated_paths(args, "--input-dir") {
        inputs.extend(read_diffgr_jsons_in_dir(&dir)?);
    }
    for pattern in repeated(args, "--input-glob") {
        inputs.extend(expand_simple_glob(&pattern)?);
    }
    dedup_paths(&mut inputs);
    if inputs.is_empty() {
        return Err(
            "merge-group-reviews requires --input, --input-glob, or --input-dir".to_owned(),
        );
    }
    let base_doc = ops::read_json_file(&base)?;
    let mut review_docs = Vec::new();
    for path in inputs {
        review_docs.push((path.display().to_string(), ops::read_json_file(&path)?));
    }
    let (merged, warnings, applied) = ops::merge_group_review_documents(
        &base_doc,
        &review_docs,
        has(args, "--clear-base-reviews"),
        has(args, "--strict"),
    )?;
    ops::write_json_file(&output, &merged)?;
    println!("Wrote: {}", output.display());
    println!("Applied: {applied}");
    for warning in warnings {
        eprintln!("[warn] {warning}");
    }
    Ok(())
}

fn cmd_impact_report(args: &[String]) -> Result<(), String> {
    let old = ops::read_json_file(&path_required(args, "--old")?)?;
    let new = ops::read_json_file(&path_required(args, "--new")?)?;
    let state = path_opt(args, "--state")
        .or_else(|| path_opt(args, "--impact-state"))
        .map(|p| ops::read_json_file(&p))
        .transpose()?;
    let report = ops::impact_report_with_options(
        &old,
        &new,
        state.as_ref(),
        opt(args, "--grouping").as_deref().unwrap_or("old"),
        opt_f64(args, "--similarity-threshold", 0.86),
        opt_usize(args, "--max-items", 20),
    )?;
    if has(args, "--json") || has(args, "--json-summary") {
        write_or_print_json(args, &report)
    } else {
        let markdown =
            ops::format_impact_report_markdown(&report, opt_usize(args, "--max-items", 20));
        if let Some(output) = path_opt(args, "--output") {
            ops::write_text_file(&output, &markdown)?;
            println!("Wrote: {}", output.display());
        } else {
            print!("{markdown}");
        }
        Ok(())
    }
}

fn cmd_preview_rebased_merge(args: &[String]) -> Result<(), String> {
    let old = ops::read_json_file(&path_required(args, "--old")?)?;
    let new = ops::read_json_file(&path_required(args, "--new")?)?;
    let state = ops::read_json_file(&path_required(args, "--state")?)?;
    let (rebased, summary) = ops::rebase_state(&old, &new, &state)?;
    if let Some(plan) = opt(args, "--tokens-only") {
        let current = ops::extract_review_state(&new);
        let diff = ops::diff_review_states(&current, &rebased)?;
        let mut tokens = ops::selection_tokens_from_diff(&diff);
        tokens.retain(|token| match plan.as_str() {
            "handoffs" => token.starts_with("groupBriefs:"),
            "reviews" => token.starts_with("reviews:"),
            "ui" => token.starts_with("analysisState:") || token.starts_with("threadState:"),
            "all" => true,
            _ => true,
        });
        for token in tokens {
            println!("{token}");
        }
        return Ok(());
    }
    let report = json!({"summary": {"mappedReviews": summary.mapped_reviews, "unmappedReviews": summary.unmapped_reviews, "mappedThreadEntries": summary.mapped_thread_entries, "warnings": summary.warnings.clone()}, "rebasedState": rebased});
    write_or_print_json(args, &report)
}

fn rebase_options(args: &[String]) -> ops::RebaseOptions {
    ops::RebaseOptions {
        preserve_groups: !has(args, "--keep-new-groups"),
        carry_line_comments: !has(args, "--no-line-comments"),
        similarity_threshold: opt_f64(args, "--similarity-threshold", 0.86),
    }
}

fn cmd_rebase_state(args: &[String]) -> Result<(), String> {
    let old = ops::read_json_file(&path_required(args, "--old")?)?;
    let new = ops::read_json_file(&path_required(args, "--new")?)?;
    let state = ops::read_json_file(&path_required(args, "--state")?)?;
    let output = path_required(args, "--output")?;
    let options = rebase_options(args);
    let (rebased, summary) = ops::rebase_state_with_options(&old, &new, &state, &options)?;
    ops::write_json_file(&output, &rebased)?;
    if args.iter().any(|arg| arg == "--json-summary") {
        print_json(&ops::rebase_summary_json(&summary))?;
    } else {
        println!("Wrote: {}", output.display());
        println!("Matched (strong): {}", summary.matched_strong);
        println!("Matched (stable): {}", summary.matched_stable);
        println!("Matched (delta): {}", summary.matched_delta);
        println!("Matched (similar): {}", summary.matched_similar);
        println!(
            "Carried reviews: {} (reviewed={})",
            summary.carried_reviews, summary.carried_reviewed
        );
        println!(
            "Changed -> needsReReview: {}",
            summary.changed_to_needs_rereview
        );
        println!("Unmapped new chunks: {}", summary.unmapped_new_chunks);
        for warning in &summary.warnings {
            eprintln!("[warn] {warning}");
        }
    }
    Ok(())
}

fn cmd_rebase_reviews(args: &[String]) -> Result<(), String> {
    let old = ops::read_json_file(&path_required(args, "--old")?)?;
    let new = ops::read_json_file(&path_required(args, "--new")?)?;
    let output = path_required(args, "--output")?;
    let options = rebase_options(args);
    let impact_grouping = opt(args, "--impact-grouping").unwrap_or_else(|| "old".to_owned());
    if impact_grouping != "old" && impact_grouping != "new" {
        return Err("--impact-grouping must be old or new".to_owned());
    }
    let (mut rebased, summary) = ops::rebase_reviews_document_with_options(&old, &new, &options)?;
    if !has(args, "--no-history") {
        let impact_source = if impact_grouping == "new" {
            rebased.clone()
        } else {
            old.clone()
        };
        ops::append_rebase_history_metadata(
            &mut rebased,
            &impact_source,
            &new,
            &summary,
            opt(args, "--history-label").as_deref(),
            opt(args, "--history-actor").as_deref(),
            opt_usize(args, "--history-max-entries", 100),
            opt_usize(args, "--history-max-ids-per-group", 200),
        )?;
    }
    ops::write_json_file(&output, &rebased)?;
    if has(args, "--json-summary") {
        print_json(&ops::rebase_summary_json(&summary))?;
    } else {
        println!("Wrote: {}", output.display());
        println!("Matched (strong): {}", summary.matched_strong);
        println!("Matched (stable): {}", summary.matched_stable);
        println!("Matched (delta): {}", summary.matched_delta);
        println!("Matched (similar): {}", summary.matched_similar);
        println!(
            "Carried reviews: {} (reviewed={})",
            summary.carried_reviews, summary.carried_reviewed
        );
        println!(
            "Changed -> needsReReview: {}",
            summary.changed_to_needs_rereview
        );
        println!("Unmapped new chunks: {}", summary.unmapped_new_chunks);
        for warning in &summary.warnings {
            eprintln!("[warn] {warning}");
        }
    }
    Ok(())
}

fn cmd_export_html(args: &[String]) -> Result<(), String> {
    let input = ops::read_json_file(&path_required(args, "--input")?)?;
    let state_path = path_opt(args, "--state");
    let impact_old_path = path_opt(args, "--impact-old");
    let impact_state_path = path_opt(args, "--impact-state");
    if impact_old_path.is_some() ^ impact_state_path.is_some() {
        return Err("--impact-old and --impact-state must be provided together".to_owned());
    }
    if state_path.is_some() && impact_state_path.is_some() && state_path != impact_state_path {
        return Err(
            "--state and --impact-state must point to the same state file when both are provided"
                .to_owned(),
        );
    }
    let state = state_path
        .as_ref()
        .map(|p| ops::read_json_file(p))
        .transpose()?;
    let impact_old = impact_old_path
        .as_ref()
        .map(|p| ops::read_json_file(p))
        .transpose()?;
    let impact_state = impact_state_path
        .as_ref()
        .map(|p| ops::read_json_file(p))
        .transpose()?;
    let group = opt(args, "--group");
    let title = opt(args, "--title");
    let save_state_url = opt(args, "--save-state-url");
    let save_state_label = opt(args, "--save-state-label");
    let output = path_required(args, "--output")?;
    let html = ops::build_html_report_with_options(
        &input,
        state.as_ref(),
        impact_old.as_ref(),
        impact_state.as_ref(),
        group.as_deref(),
        title.as_deref(),
        save_state_url.as_deref(),
        save_state_label.as_deref(),
    )?;
    ops::write_text_file(&output, &html)?;
    println!("Wrote: {}", output.display());
    if has(args, "--open") {
        open_path(&output)?;
    }
    Ok(())
}

fn cmd_serve_html(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let state = path_opt(args, "--state");
    let impact_old = path_opt(args, "--impact-old");
    let impact_state = path_opt(args, "--impact-state");
    if impact_old.is_some() ^ impact_state.is_some() {
        return Err("--impact-old and --impact-state must be provided together".to_owned());
    }
    if state.is_some() && impact_state.is_some() && state != impact_state {
        return Err(
            "--state and --impact-state must point to the same state file when both are provided"
                .to_owned(),
        );
    }
    let group = opt(args, "--group");
    let title = opt(args, "--title");
    let host = opt(args, "--host").unwrap_or_else(|| "127.0.0.1".to_owned());
    let port = opt(args, "--port")
        .unwrap_or_else(|| "8765".to_owned())
        .parse::<u16>()
        .map_err(|_| "--port must be an integer".to_owned())?;
    ops::serve_report(
        &input,
        state.as_deref(),
        impact_old.as_deref(),
        impact_state.as_deref(),
        group.as_deref(),
        title.as_deref(),
        &host,
        port,
        has(args, "--open"),
    )
}

fn cmd_export_bundle(args: &[String]) -> Result<(), String> {
    let input = ops::read_json_file(&path_required(args, "--input")?)?;
    let summary = if path_opt(args, "--bundle-out").is_some()
        || path_opt(args, "--state-out").is_some()
        || path_opt(args, "--manifest-out").is_some()
    {
        let bundle_out = path_required(args, "--bundle-out")?;
        let state_out = path_required(args, "--state-out")?;
        let manifest_out = path_required(args, "--manifest-out")?;
        ops::export_review_bundle_to_paths(&input, &bundle_out, &state_out, &manifest_out)?
    } else {
        let output_dir = path_required(args, "--output-dir")?;
        ops::export_review_bundle(&input, &output_dir)?
    };
    println!("{}", summary.message);
    for path in summary.written {
        println!("Wrote: {}", path.display());
    }
    Ok(())
}

fn cmd_verify_bundle(args: &[String]) -> Result<(), String> {
    let bundle = ops::read_json_file(&path_required(args, "--bundle")?)?;
    let state = ops::read_json_file(&path_required(args, "--state")?)?;
    let manifest = ops::read_json_file(&path_required(args, "--manifest")?)?;
    let report = ops::verify_review_bundle(
        &bundle,
        &state,
        &manifest,
        opt(args, "--expected-head").as_deref(),
        has(args, "--require-approvals"),
    )?;
    let ok = report.ok;
    let json = json!({"ok": ok, "errors": report.errors, "warnings": report.warnings, "computedManifest": report.computed_manifest, "approvalReport": report.approval_report});
    write_or_print_json(args, &json)?;
    if ok {
        Ok(())
    } else {
        Err("bundle verification failed".to_owned())
    }
}

fn cmd_approve(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let output = path_opt(args, "--output").unwrap_or_else(|| input.clone());
    let doc = ops::read_json_file(&input)?;
    let groups = if has(args, "--all") {
        Vec::new()
    } else {
        repeated(args, "--group")
    };
    if !has(args, "--all") && groups.is_empty() {
        return Err("Specify --group GROUP_ID or --all.".to_owned());
    }
    let reviewer = opt(args, "--approved-by")
        .or_else(|| opt(args, "--reviewer"))
        .ok_or_else(|| "--approved-by is required".to_owned())?;
    let out = ops::approve_groups(&doc, &groups, &reviewer, has(args, "--force"))?;
    ops::write_json_file(&output, &out)?;
    println!("Wrote: {}", output.display());
    Ok(())
}

fn cmd_request_changes(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let output = path_opt(args, "--output").unwrap_or_else(|| input.clone());
    let doc = ops::read_json_file(&input)?;
    let groups = if has(args, "--all") {
        Vec::new()
    } else {
        repeated(args, "--group")
    };
    if !has(args, "--all") && groups.is_empty() {
        return Err("Specify --group GROUP_ID or --all.".to_owned());
    }
    let reviewer = opt(args, "--requested-by")
        .or_else(|| opt(args, "--reviewer"))
        .ok_or_else(|| "--requested-by is required".to_owned())?;
    let comment = opt(args, "--comment").unwrap_or_default();
    let out = ops::request_changes(&doc, &groups, &reviewer, &comment)?;
    ops::write_json_file(&output, &out)?;
    println!("Wrote: {}", output.display());
    Ok(())
}

fn cmd_check_approval(args: &[String]) -> Result<(), String> {
    let input_path = path_required(args, "--input")?;
    let input = ops::read_json_file(&input_path)?;
    let regen_flags = [
        path_opt(args, "--repo").is_some(),
        opt(args, "--base").is_some(),
        opt(args, "--feature").is_some(),
    ];
    if regen_flags.iter().any(|v| *v) && !regen_flags.iter().all(|v| *v) {
        return Err("--repo, --base, and --feature must all be specified together".to_owned());
    }
    let mut report = ops::approval_report(&input)?;
    if regen_flags.iter().all(|v| *v) {
        let options = ops::GenerateOptions {
            repo: path_opt(args, "--repo").unwrap(),
            base: opt(args, "--base").unwrap(),
            feature: opt(args, "--feature").unwrap(),
            title: "CI regeneration".to_owned(),
            include_patch: false,
        };
        match ops::build_diffgr_document(&options)
            .and_then(|new_doc| ops::impact_report(&input, &new_doc, None))
        {
            Ok(impact) => {
                let changed = json_count(&impact, "newOnlyChunks") > 0
                    || json_count(&impact, "oldOnlyChunks") > 0
                    || json_count(&impact, "changedChunks") > 0;
                if changed {
                    if let Some(root) = report.as_object_mut() {
                        root.insert("allApproved".to_owned(), Value::Bool(false));
                        let warnings = root
                            .entry("warnings".to_owned())
                            .or_insert_with(|| Value::Array(Vec::new()));
                        if let Some(items) = warnings.as_array_mut() {
                            items.push(Value::String("Regenerated DiffGR is not identical; approvals may be invalidated by code/layout change.".to_owned()));
                        }
                    }
                }
            }
            Err(err) if has(args, "--strict-full-check") => {
                return Err(format!(
                    "Regeneration failed and --strict-full-check is set: {err}"
                ))
            }
            Err(err) => eprintln!("[warn] Could not regenerate diffgr from git: {err}"),
        }
    }
    if has(args, "--json") || path_opt(args, "--output").is_some() {
        write_or_print_json(args, &report)?;
    } else {
        print_approval_report_text(&report);
    }
    if !report
        .get("allApproved")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        Err("not all groups are approved".to_owned())
    } else {
        Ok(())
    }
}

fn cmd_coverage(args: &[String]) -> Result<(), String> {
    let doc = ops::read_json_file(&path_required(args, "--input")?)?;
    let report = ops::coverage_report_with_limits(
        &doc,
        opt_usize(args, "--max-chunks-per-group", 20),
        opt_usize(args, "--max-problem-chunks", 80),
    )?;
    if let Some(prompt_path) = path_opt(args, "--write-prompt") {
        let prompt = report.get("prompt").and_then(Value::as_str).unwrap_or("");
        ops::write_text_file(&prompt_path, prompt)?;
        println!("Wrote prompt: {}", prompt_path.display());
    }
    if has(args, "--json") || path_opt(args, "--output").is_some() {
        write_or_print_json(args, &report)?;
    } else {
        println!(
            "Chunks: {}",
            doc.get("chunks")
                .and_then(Value::as_array)
                .map(|a| a.len())
                .unwrap_or(0)
        );
        println!(
            "Groups: {}",
            doc.get("groups")
                .and_then(Value::as_array)
                .map(|a| a.len())
                .unwrap_or(0)
        );
        println!(
            "Unassigned: {}",
            report
                .get("unassigned")
                .and_then(Value::as_array)
                .map(|a| a.len())
                .unwrap_or(0)
        );
        println!(
            "Duplicated: {}",
            report
                .get("duplicated")
                .and_then(Value::as_array)
                .map(|a| a.len())
                .unwrap_or(0)
        );
        println!(
            "Unknown groups in assignments: {}",
            report
                .get("unknownGroups")
                .and_then(Value::as_array)
                .map(|a| a.len())
                .unwrap_or(0)
        );
        println!(
            "Unknown chunks in assignments: {}",
            report
                .get("unknownChunks")
                .and_then(Value::as_array)
                .map(|a| a.len())
                .unwrap_or(0)
        );
    }
    if report.get("ok").and_then(Value::as_bool).unwrap_or(false) {
        Ok(())
    } else {
        Err("virtual PR coverage failed".to_owned())
    }
}

fn cmd_reviewability(args: &[String]) -> Result<(), String> {
    let doc = ops::read_json_file(&path_required(args, "--input")?)?;
    let report = ops::reviewability_report(&doc)?;
    write_or_print_json(args, &report)
}

fn cmd_virtual_pr_review(args: &[String]) -> Result<(), String> {
    let input = path_required(args, "--input")?;
    let state = path_opt(args, "--state");
    let doc = DiffgrDocument::load_from_path(&input, state.as_deref())?;
    let report = vpr::analyze_virtual_pr(&doc);
    let output = path_opt(args, "--output");
    let text_mode = has(args, "--markdown") || has(args, "--prompt") || !has(args, "--json");
    if has(args, "--prompt") {
        let prompt =
            vpr::virtual_pr_reviewer_prompt_markdown(&report, opt_usize(args, "--max-items", 12));
        if let Some(output) = output {
            ops::write_text_file(&output, &prompt)?;
            println!("Wrote: {}", output.display());
        } else {
            print!("{}", prompt);
        }
    } else if text_mode && !has(args, "--json") {
        let markdown = vpr::virtual_pr_report_markdown(&report);
        if let Some(output) = output {
            ops::write_text_file(&output, &markdown)?;
            println!("Wrote: {}", output.display());
        } else {
            print!("{}", markdown);
        }
    } else {
        let json = vpr::virtual_pr_report_json_value(&report);
        write_or_print_json(args, &json)?;
    }
    if has(args, "--fail-on-blockers") && !report.blockers.is_empty() {
        Err(format!(
            "virtual PR review gate failed: {} blocker(s)",
            report.blockers.len()
        ))
    } else {
        Ok(())
    }
}

fn cmd_run_agent(args: &[String]) -> Result<(), String> {
    let prompt_path = path_opt(args, "--prompt")
        .unwrap_or_else(|| PathBuf::from("samples/diffgr/ts20-5pr.refine-prompt.md"));
    let output = path_opt(args, "--output").unwrap_or_else(|| PathBuf::from("slice_patch.json"));
    let mut prompt = std::fs::read_to_string(&prompt_path)
        .map_err(|e| format!("{}: {e}", prompt_path.display()))?;
    let schema_path = path_opt(args, "--schema").unwrap_or_else(|| {
        let preferred = PathBuf::from("schemas/slice_patch.schema.json");
        if preferred.exists() {
            preferred
        } else {
            PathBuf::from("diffgr/slice_patch.schema.json")
        }
    });
    if schema_path.exists() {
        let schema = std::fs::read_to_string(&schema_path)
            .map_err(|e| format!("{}: {e}", schema_path.display()))?;
        prompt.push_str("\n\nReturn a JSON object matching this schema. Do not wrap it in markdown.\n\n```json\n");
        prompt.push_str(&schema);
        prompt.push_str("\n```\n");
    }
    if has(args, "--copy-prompt") && !has(args, "--no-copy-prompt") {
        copy_to_clipboard(&prompt).ok();
    }
    if has(args, "--interactive") {
        eprintln!("[info] --interactive uses the configured agent command and parses the JSON object from stdout.");
    }
    let command_line = opt(args, "--command")
        .or_else(|| read_agent_command(path_opt(args, "--config")))
        .unwrap_or_else(|| "codex exec".to_owned());
    let mut parts = split_command_line(&command_line);
    if parts.is_empty() {
        return Err("agent command is empty".to_owned());
    }
    let program = parts.remove(0);
    let mut child = Command::new(program)
        .args(parts)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|err| format!("failed to start agent CLI: {err}"))?;
    if let Some(mut stdin) = child.stdin.take() {
        use std::io::Write;
        stdin
            .write_all(prompt.as_bytes())
            .map_err(|err| err.to_string())?;
    }
    let timeout = Duration::from_secs(opt_usize(args, "--timeout", 180) as u64);
    let start = Instant::now();
    loop {
        if child.try_wait().map_err(|err| err.to_string())?.is_some() {
            break;
        }
        if start.elapsed() > timeout {
            let _ = child.kill();
            return Err(format!(
                "agent CLI timed out after {} seconds",
                timeout.as_secs()
            ));
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let output_data = child.wait_with_output().map_err(|err| err.to_string())?;
    if !output_data.status.success() {
        return Err(format!(
            "agent CLI exited with status {}",
            output_data.status
        ));
    }
    let text = String::from_utf8_lossy(&output_data.stdout).to_string();
    let patch = extract_first_json_object(&text)?;
    let patch = normalize_slice_patch(patch);
    ops::write_json_file(&output, &patch)?;
    println!("Wrote: {}", output.display());
    Ok(())
}

fn cmd_view(args: &[String]) -> Result<(), String> {
    let input = path_opt(args, "--input")
        .or_else(|| {
            positional_args(args)
                .first()
                .map(|value| PathBuf::from(value.as_str()))
        })
        .ok_or_else(|| "view requires --input or a path".to_owned())?;
    let mut doc = ops::read_json_file(&input)?;
    if let Some(state_path) = path_opt(args, "--state") {
        let state = ops::read_json_file(&state_path)?;
        doc = ops::apply_review_state(&doc, &state)?;
    }
    let group_filter = opt(args, "--group");
    let chunk_filter = opt(args, "--chunk");
    let status_filter = opt(args, "--status");
    let file_filter = opt(args, "--file").map(|s| s.to_lowercase());
    let filtered = filter_doc_chunks(
        &doc,
        group_filter.as_deref(),
        chunk_filter.as_deref(),
        status_filter.as_deref(),
        file_filter.as_deref(),
    );
    if filtered.is_empty() {
        return Err("No chunks matched filters.".to_owned());
    }
    if has(args, "--json") {
        let statuses: serde_json::Map<String, Value> = filtered
            .iter()
            .filter_map(|chunk| {
                chunk.get("id").and_then(Value::as_str).map(|id| {
                    (
                        id.to_owned(),
                        Value::String(status_for_chunk(&doc, id).to_owned()),
                    )
                })
            })
            .collect();
        return print_json(&json!({"warnings": [], "chunks": filtered, "statuses": statuses}));
    }
    let summary = ops::summarize_document(&doc);
    let title = doc
        .get("meta")
        .and_then(|m| m.get("title"))
        .and_then(Value::as_str)
        .unwrap_or("DiffGR");
    println!("# {title}");
    println!("input: {}", input.display());
    println!(
        "chunks: {}",
        summary
            .get("chunkCount")
            .and_then(Value::as_u64)
            .unwrap_or(0)
    );
    println!(
        "groups: {}",
        summary
            .get("groupCount")
            .and_then(Value::as_u64)
            .unwrap_or(0)
    );
    println!("matched: {}", filtered.len());
    if let Some(groups) = doc.get("groups").and_then(Value::as_array) {
        println!("\nGroups:");
        for group in groups {
            println!(
                "- {}: {}",
                group.get("id").and_then(Value::as_str).unwrap_or(""),
                group.get("name").and_then(Value::as_str).unwrap_or("")
            );
        }
    }
    println!("\nChunks:");
    let limit = opt_usize(args, "--limit", 40);
    for chunk in filtered.iter().take(limit) {
        let id = chunk.get("id").and_then(Value::as_str).unwrap_or("");
        println!(
            "- {} [{}] {} {}",
            id.chars().take(12).collect::<String>(),
            status_for_chunk(&doc, id),
            chunk.get("filePath").and_then(Value::as_str).unwrap_or(""),
            chunk.get("header").and_then(Value::as_str).unwrap_or("")
        );
    }
    if chunk_filter.is_some() {
        if let Some(chunk) = filtered.first() {
            print_chunk_detail(&doc, chunk, opt_usize(args, "--max-lines", 120));
        }
    }
    if has(args, "--show-patch") {
        if let Some(patch) = doc.get("patch").and_then(Value::as_str) {
            println!("\nPatch:\n{patch}");
        }
    }
    Ok(())
}

fn cmd_view_app(args: &[String]) -> Result<(), String> {
    if has(args, "--once") || opt(args, "--ui").as_deref() == Some("prompt") {
        return cmd_view(args);
    }
    let input = path_opt(args, "--input")
        .or_else(|| {
            positional_args(args)
                .first()
                .map(|value| PathBuf::from(value.as_str()))
        })
        .ok_or_else(|| "view-app requires a path".to_owned())?;
    let current = env::current_exe().map_err(|err| err.to_string())?;
    let exe = sibling_gui_exe(&current);
    if !exe.exists() {
        println!(
            "GUI executable was not found next to diffgrctl: {}",
            exe.display()
        );
        println!("Open with: diffgr_gui {}", input.display());
        return Ok(());
    }
    let mut command = Command::new(exe);
    command.arg(input);
    if let Some(state) = path_opt(args, "--state") {
        command.arg("--state").arg(state);
    }
    if has(args, "--low-memory") {
        command.arg("--low-memory");
    }
    command.spawn().map_err(|err| err.to_string())?;
    Ok(())
}

fn cmd_quality_review(args: &[String]) -> Result<(), String> {
    let root = path_opt(args, "--root")
        .unwrap_or_else(|| env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    let rows = python_script_parity_rows();
    let (wrapper_ps1, wrapper_sh) = count_python_wrappers_for_rows(&root, &rows);
    let (gui_markers_found, gui_markers_total, missing_gui_markers) = count_quality_markers(&root);
    let rust_tests = count_checked_in_rust_tests(&root);
    let compile_guard = visible_cache_key_compile_guard(&root);
    let functional_scenarios = json_file_array_len(
        &root.join("NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json"),
        "scenarios",
    );
    let compat_sources = json_number(
        &root.join("COMPLETE_PYTHON_SOURCE_AUDIT.json"),
        "sourceFileCount",
    );
    let python_options = json_number(
        &root.join("NATIVE_PYTHON_PARITY_AUDIT.json"),
        "uniquePythonOptionCount",
    );
    let checks = vec![
        json!({"name":"python script entries", "ok": rows.len() == 31, "actual": rows.len(), "expected": 31}),
        json!({"name":"PowerShell wrappers", "ok": wrapper_ps1 == 31, "actual": wrapper_ps1, "expected": 31}),
        json!({"name":"shell wrappers", "ok": wrapper_sh == 31, "actual": wrapper_sh, "expected": 31}),
        json!({"name":"native functional scenarios", "ok": functional_scenarios == 31, "actual": functional_scenarios, "expected": 31}),
        json!({"name":"python CLI options", "ok": python_options >= 80, "actual": python_options, "expected": 80}),
        json!({"name":"compat source files", "ok": compat_sources >= 163, "actual": compat_sources, "expected": 163}),
        json!({"name":"GUI quality markers", "ok": gui_markers_found == gui_markers_total, "actual": gui_markers_found, "expected": gui_markers_total, "missing": missing_gui_markers}),
        json!({"name":"Rust UT count", "ok": rust_tests >= 500, "actual": rust_tests, "expected": 500}),
        json!({"name":"static compile guard", "ok": compile_guard, "actual": compile_guard, "expected": true}),
    ];
    let ok = checks
        .iter()
        .all(|check| check.get("ok").and_then(Value::as_bool).unwrap_or(false));
    let value = json!({
        "format": "diffgr-gui-quality-self-review",
        "ok": ok,
        "root": root.display().to_string(),
        "summary": {
            "pythonScripts": rows.len(),
            "wrapperPs1": wrapper_ps1,
            "wrapperSh": wrapper_sh,
            "functionalScenarios": functional_scenarios,
            "pythonOptions": python_options,
            "compatSources": compat_sources,
            "guiMarkersFound": gui_markers_found,
            "guiMarkersTotal": gui_markers_total,
            "rustTests": rust_tests,
            "compileGuard": compile_guard
        },
        "checks": checks
    });
    if has(args, "--json") {
        write_or_print_json(args, &value)
    } else {
        println!("# DiffGR Rust GUI quality self-review");
        println!(
            "ok: {}",
            value.get("ok").and_then(Value::as_bool).unwrap_or(false)
        );
        for check in value
            .get("checks")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let mark = if check.get("ok").and_then(Value::as_bool).unwrap_or(false) {
                "ok"
            } else {
                "NG"
            };
            let name = check.get("name").and_then(Value::as_str).unwrap_or("check");
            let actual = check
                .get("actual")
                .map(|v| v.to_string())
                .unwrap_or_else(|| "-".to_owned());
            let expected = check
                .get("expected")
                .map(|v| v.to_string())
                .unwrap_or_else(|| "-".to_owned());
            println!("- [{mark}] {name}: {actual}/{expected}");
        }
        println!("\nRecommended gate:");
        println!("  .\\windows\\self-review-windows.ps1 -Json -Strict");
        println!("  .\\windows\\quality-review-windows.ps1 -Json -Deep");
        println!("  .\\test.ps1 -Fmt -Check");
        println!("  .\\build.ps1 -Test");
        Ok(())
    }
}

fn count_python_wrappers_for_rows(
    root: &Path,
    rows: &[(&'static str, &'static str, &'static str, &'static str)],
) -> (usize, usize) {
    let mut ps1 = 0;
    let mut sh = 0;
    for (script, _, _, _) in rows {
        let stem = script
            .trim_start_matches("scripts/")
            .trim_end_matches(".py");
        if root.join("scripts").join(format!("{stem}.ps1")).exists() {
            ps1 += 1;
        }
        if root.join("scripts").join(format!("{stem}.sh")).exists() {
            sh += 1;
        }
    }
    (ps1, sh)
}

const QUALITY_MARKERS: [&str; 18] = [
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
];

fn count_quality_markers(root: &Path) -> (usize, usize, Vec<&'static str>) {
    let app = std::fs::read_to_string(root.join("src/app.rs")).unwrap_or_default();
    let mut found = 0;
    let mut missing = Vec::new();
    for marker in QUALITY_MARKERS {
        if app.contains(marker) {
            found += 1;
        } else {
            missing.push(marker);
        }
    }
    (found, QUALITY_MARKERS.len(), missing)
}

fn count_checked_in_rust_tests(root: &Path) -> usize {
    let dir = root.join("tests");
    let Ok(entries) = std::fs::read_dir(dir) else {
        return 0;
    };
    entries
        .flatten()
        .map(|entry| {
            let path = entry.path();
            if path.extension().and_then(|v| v.to_str()) != Some("rs") {
                return 0;
            }
            std::fs::read_to_string(path)
                .map(|text| text.lines().filter(|line| line.trim() == "#[test]").count())
                .unwrap_or(0)
        })
        .sum()
}

fn visible_cache_key_compile_guard(root: &Path) -> bool {
    let app = std::fs::read_to_string(root.join("src/app.rs")).unwrap_or_default();
    app.contains("struct VisibleCacheKey")
        && app.contains("fn visible_cache_key")
        && !app.contains("file_filter_input: String,\n    content_filter_input: String,\n    filter_apply_deadline")
}

fn json_file_array_len(path: &Path, key: &str) -> usize {
    let Ok(text) = std::fs::read_to_string(path) else {
        return 0;
    };
    let Ok(value) = serde_json::from_str::<Value>(&text) else {
        return 0;
    };
    value
        .get(key)
        .and_then(Value::as_array)
        .map(Vec::len)
        .unwrap_or(0)
}

fn json_number(path: &Path, key: &str) -> usize {
    let Ok(text) = std::fs::read_to_string(path) else {
        return 0;
    };
    let Ok(value) = serde_json::from_str::<Value>(&text) else {
        return 0;
    };
    value.get(key).and_then(Value::as_u64).unwrap_or(0) as usize
}

fn cmd_parity_audit(args: &[String]) -> Result<(), String> {
    let scripts = python_script_parity_rows();
    let ok = scripts.iter().all(|row| row.3 == "covered");
    let value = json!({
        "ok": ok,
        "scriptCount": scripts.len(),
        "coveredCount": scripts.iter().filter(|row| row.3 == "covered").count(),
        "entries": scripts.iter().map(|(script, command, notes, status)| json!({
            "pythonScript": script,
            "rustEntry": command,
            "notes": notes,
            "status": status,
        })).collect::<Vec<_>>()
    });
    if has(args, "--json") {
        write_or_print_json(args, &value)
    } else {
        println!("# Python parity audit");
        println!(
            "covered: {}/{}",
            value["coveredCount"].as_u64().unwrap_or(0),
            value["scriptCount"].as_u64().unwrap_or(0)
        );
        for (script, command, notes, status) in scripts {
            println!("- [{status}] {script} -> {command} ({notes})");
        }
        Ok(())
    }
}

fn autoslice_options(args: &[String]) -> ops::AutosliceOptions {
    ops::AutosliceOptions {
        repo: path_opt(args, "--repo").unwrap_or_else(|| PathBuf::from(".")),
        base: opt(args, "--base").unwrap_or_else(|| "samples/ts20-base".to_owned()),
        feature: opt(args, "--feature").unwrap_or_else(|| "samples/ts20-feature-5pr".to_owned()),
        max_commits: opt_usize(args, "--max-commits", 50),
        name_style: opt(args, "--name-style").unwrap_or_else(|| "subject".to_owned()),
        split_chunks: !has(args, "--no-split"),
        context_lines: opt_usize(args, "--context-lines", 3),
        fail_on_truncate: has(args, "--fail-on-truncate"),
    }
}

fn resolve_relative_to(base: &Path, path: PathBuf) -> PathBuf {
    if path.is_absolute() {
        path
    } else {
        base.join(path)
    }
}

fn dedup_paths(paths: &mut Vec<PathBuf>) {
    paths.sort_by_key(|p| p.to_string_lossy().to_lowercase());
    paths.dedup_by(|a, b| a.to_string_lossy().to_lowercase() == b.to_string_lossy().to_lowercase());
}

fn positional_args(args: &[String]) -> Vec<String> {
    let value_options = [
        "--input",
        "--output",
        "--state",
        "--base",
        "--other",
        "--incoming",
        "--old",
        "--new",
        "--group",
        "--chunk",
        "--status",
        "--file",
        "--repo",
        "--feature",
        "--title",
        "--layout",
        "--patch",
        "--prompt",
        "--schema",
        "--config",
        "--bundle",
        "--manifest",
        "--bundle-out",
        "--state-out",
        "--manifest-out",
        "--output-dir",
        "--max-lines",
        "--limit",
        "--page-size",
        "--ui",
        "--host",
        "--port",
        "--approved-by",
        "--requested-by",
        "--reviewer",
        "--comment",
        "--token",
        "--tokens",
        "--select",
        "--input-dir",
        "--input-glob",
        "--write-prompt",
        "--impact-old",
        "--impact-new",
        "--impact-plan",
        "--impact-state",
        "--expected-head",
        "--timeout",
        "--command",
        "--max-items",
        "--max-chunks-per-group",
        "--max-problem-chunks",
        "--similarity-threshold",
        "--impact-grouping",
    ];
    let mut out = Vec::new();
    let mut index = 0;
    while index < args.len() {
        let arg = &args[index];
        if arg == "--" {
            out.extend(args[index + 1..].iter().cloned());
            break;
        }
        if arg.starts_with('-') {
            if value_options.contains(&arg.as_str()) {
                index += 2;
            } else {
                index += 1;
            }
        } else {
            out.push(arg.clone());
            index += 1;
        }
    }
    out
}

fn status_for_chunk<'a>(doc: &'a Value, chunk_id: &str) -> &'a str {
    doc.get("reviews")
        .and_then(Value::as_object)
        .and_then(|reviews| reviews.get(chunk_id))
        .and_then(|review| review.get("status"))
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .unwrap_or("unreviewed")
}

fn group_contains_chunk(doc: &Value, group_id: &str, chunk_id: &str) -> bool {
    doc.get("assignments")
        .and_then(Value::as_object)
        .and_then(|assignments| assignments.get(group_id))
        .and_then(Value::as_array)
        .map(|ids| ids.iter().any(|id| id.as_str() == Some(chunk_id)))
        .unwrap_or(false)
}

fn filter_doc_chunks(
    doc: &Value,
    group_id: Option<&str>,
    chunk_id: Option<&str>,
    status: Option<&str>,
    file_contains: Option<&str>,
) -> Vec<Value> {
    doc.get("chunks")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|chunk| {
            let id = chunk.get("id").and_then(Value::as_str).unwrap_or("");
            if let Some(target) = chunk_id {
                if id != target {
                    return false;
                }
            }
            if let Some(group) = group_id {
                if !group_contains_chunk(doc, group, id) {
                    return false;
                }
            }
            if let Some(target_status) = status {
                if status_for_chunk(doc, id) != target_status {
                    return false;
                }
            }
            if let Some(needle) = file_contains {
                let file = chunk
                    .get("filePath")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_lowercase();
                if !file.contains(needle) {
                    return false;
                }
            }
            true
        })
        .cloned()
        .collect()
}

fn print_chunk_detail(doc: &Value, chunk: &Value, max_lines: usize) {
    let id = chunk.get("id").and_then(Value::as_str).unwrap_or("");
    println!("\n## Chunk {id}");
    println!("status: {}", status_for_chunk(doc, id));
    println!(
        "file: {}",
        chunk.get("filePath").and_then(Value::as_str).unwrap_or("")
    );
    if let Some(header) = chunk
        .get("header")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
    {
        println!("header: {header}");
    }
    if let Some(comment) = doc
        .get("reviews")
        .and_then(|r| r.get(id))
        .and_then(|r| r.get("comment"))
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
    {
        println!("comment: {comment}");
    }
    println!("\nDiff:");
    for line in chunk
        .get("lines")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .take(max_lines)
    {
        let kind = line
            .get("kind")
            .and_then(Value::as_str)
            .unwrap_or("context");
        let prefix = match kind {
            "add" => "+",
            "delete" => "-",
            _ => " ",
        };
        let old = line
            .get("oldLine")
            .and_then(Value::as_i64)
            .map(|n| n.to_string())
            .unwrap_or_else(|| "-".to_owned());
        let new = line
            .get("newLine")
            .and_then(Value::as_i64)
            .map(|n| n.to_string())
            .unwrap_or_else(|| "-".to_owned());
        let text = line.get("text").and_then(Value::as_str).unwrap_or("");
        println!("{old:>5} {new:>5} {prefix}{text}");
    }
}

fn sibling_gui_exe(current: &Path) -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        current.with_file_name("diffgr_gui.exe")
    }
    #[cfg(not(target_os = "windows"))]
    {
        current.with_file_name("diffgr_gui")
    }
}

fn json_count(value: &Value, key: &str) -> u64 {
    match value.get(key) {
        Some(Value::Number(n)) => n.as_u64().unwrap_or(0),
        Some(Value::Array(a)) => a.len() as u64,
        _ => 0,
    }
}

fn print_approval_report_text(report: &Value) {
    if let Some(groups) = report.get("groups").and_then(Value::as_array) {
        for group in groups {
            let approved = group
                .get("approved")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let valid = group.get("valid").and_then(Value::as_bool).unwrap_or(false);
            let icon = if approved && valid { "[ok]" } else { "[fail]" };
            let id = group.get("groupId").and_then(Value::as_str).unwrap_or("");
            let name = group.get("groupName").and_then(Value::as_str).unwrap_or("");
            let reason = group.get("reason").and_then(Value::as_str).unwrap_or("");
            let reviewed = group
                .get("reviewedCount")
                .and_then(Value::as_u64)
                .unwrap_or(0);
            let total = group.get("totalCount").and_then(Value::as_u64).unwrap_or(0);
            println!("  {icon} {id} ({name}): {reason} [{reviewed}/{total}]");
        }
    }
    if let Some(warnings) = report.get("warnings").and_then(Value::as_array) {
        for warning in warnings {
            eprintln!("  [warning] {}", warning.as_str().unwrap_or(""));
        }
    }
    let status = if report
        .get("allApproved")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        "PASS"
    } else {
        "FAIL"
    };
    println!("\nResult: {status}");
}

fn print_state_diff_text(diff: &Value) {
    for key in ["reviews", "groupBriefs", "analysisState", "threadState"] {
        let section = diff.get(key).and_then(Value::as_object);
        println!(
            "{}: added={} removed={} changed={} unchanged={}",
            key,
            section
                .and_then(|s| s.get("addedCount"))
                .and_then(Value::as_u64)
                .unwrap_or(0),
            section
                .and_then(|s| s.get("removedCount"))
                .and_then(Value::as_u64)
                .unwrap_or(0),
            section
                .and_then(|s| s.get("changedCount"))
                .and_then(Value::as_u64)
                .unwrap_or(0),
            section
                .and_then(|s| s.get("unchangedCount"))
                .and_then(Value::as_u64)
                .unwrap_or(0),
        );
        for label in ["added", "removed", "changed"] {
            if let Some(rows) = section.and_then(|s| s.get(label)).and_then(Value::as_array) {
                if rows.is_empty() {
                    continue;
                }
                println!("  {label}:");
                for row in rows.iter().take(50) {
                    let key = row.get("key").and_then(Value::as_str).unwrap_or("");
                    let token = row
                        .get("selectionToken")
                        .and_then(Value::as_str)
                        .unwrap_or("");
                    let suffix = if token.is_empty() {
                        String::new()
                    } else {
                        format!(" [select: {token}]")
                    };
                    println!("    - {key}{suffix}");
                }
            }
        }
    }
}

fn python_script_parity_rows() -> Vec<(&'static str, &'static str, &'static str, &'static str)> {
    vec![
        (
            "scripts/generate_diffgr.py",
            "diffgrctl generate-diffgr",
            "defaults and --repo/--base/--feature/--output/--title/--no-patch",
            "covered",
        ),
        (
            "scripts/autoslice_diffgr.py",
            "diffgrctl autoslice-diffgr",
            "commit slicing, --no-split, context, truncate guard",
            "covered",
        ),
        (
            "scripts/refine_slices.py",
            "diffgrctl refine-slices",
            "rename heuristic plus default prompt emission",
            "covered",
        ),
        (
            "scripts/prepare_review.py",
            "diffgrctl prepare-review",
            "generate -> autoslice -> refine",
            "covered",
        ),
        (
            "scripts/run_agent_cli.py",
            "diffgrctl run-agent-cli",
            "external agent command, schema prompt, timeout, clipboard",
            "covered",
        ),
        (
            "scripts/apply_slice_patch.py",
            "diffgrctl apply-slice-patch",
            "rename/move patch",
            "covered",
        ),
        (
            "scripts/apply_diffgr_layout.py",
            "diffgrctl apply-diffgr-layout",
            "groups/assignments/groupBriefs layout",
            "covered",
        ),
        (
            "scripts/view_diffgr.py",
            "diffgrctl view-diffgr",
            "group/chunk/status/file filters, JSON output, patch/detail",
            "covered",
        ),
        (
            "scripts/view_diffgr_app.py",
            "diffgr_gui / diffgrctl view-diffgr-app",
            "native GUI replaces Textual, prompt --once maps to CLI view",
            "covered",
        ),
        (
            "scripts/export_diffgr_html.py",
            "diffgrctl export-diffgr-html",
            "state overlay, impact section, open",
            "covered",
        ),
        (
            "scripts/serve_diffgr_report.py",
            "diffgrctl serve-diffgr-report",
            "local server and /api/state",
            "covered",
        ),
        (
            "scripts/extract_diffgr_state.py",
            "diffgrctl extract-diffgr-state",
            "stdout or --output",
            "covered",
        ),
        (
            "scripts/apply_diffgr_state.py",
            "diffgrctl apply-diffgr-state",
            "apply external state",
            "covered",
        ),
        (
            "scripts/diff_diffgr_state.py",
            "diffgrctl diff-diffgr-state",
            "JSON diff and tokens",
            "covered",
        ),
        (
            "scripts/merge_diffgr_state.py",
            "diffgrctl merge-diffgr-state",
            "repeatable input/glob/preview",
            "covered",
        ),
        (
            "scripts/apply_diffgr_state_diff.py",
            "diffgrctl apply-diffgr-state-diff",
            "selection tokens and impact plans",
            "covered",
        ),
        (
            "scripts/split_group_reviews.py",
            "diffgrctl split-group-reviews",
            "per-group split",
            "covered",
        ),
        (
            "scripts/merge_group_reviews.py",
            "diffgrctl merge-group-reviews",
            "input, glob, strict, clear-base",
            "covered",
        ),
        (
            "scripts/impact_report.py",
            "diffgrctl impact-report",
            "markdown default, JSON optional",
            "covered",
        ),
        (
            "scripts/preview_rebased_merge.py",
            "diffgrctl preview-rebased-merge",
            "rebased state and plan tokens",
            "covered",
        ),
        (
            "scripts/rebase_diffgr_state.py",
            "diffgrctl rebase-diffgr-state",
            "standalone state rebase",
            "covered",
        ),
        (
            "scripts/rebase_reviews.py",
            "diffgrctl rebase-reviews",
            "embedded review rebase",
            "covered",
        ),
        (
            "scripts/export_review_bundle.py",
            "diffgrctl export-review-bundle",
            "output-dir or bundle/state/manifest paths",
            "covered",
        ),
        (
            "scripts/verify_review_bundle.py",
            "diffgrctl verify-review-bundle",
            "manifest/head/approval checks",
            "covered",
        ),
        (
            "scripts/approve_virtual_pr.py",
            "diffgrctl approve-virtual-pr",
            "group/all approval",
            "covered",
        ),
        (
            "scripts/request_changes.py",
            "diffgrctl request-changes",
            "group/all changes requested",
            "covered",
        ),
        (
            "scripts/check_virtual_pr_approval.py",
            "diffgrctl check-virtual-pr-approval",
            "approval gate",
            "covered",
        ),
        (
            "scripts/check_virtual_pr_coverage.py",
            "diffgrctl check-virtual-pr-coverage",
            "coverage JSON and fix prompt",
            "covered",
        ),
        (
            "scripts/summarize_diffgr.py",
            "diffgrctl summarize-diffgr",
            "document summary",
            "covered",
        ),
        (
            "scripts/summarize_diffgr_state.py",
            "diffgrctl summarize-diffgr-state",
            "state summary",
            "covered",
        ),
        (
            "scripts/summarize_reviewability.py",
            "diffgrctl summarize-reviewability",
            "group reviewability",
            "covered",
        ),
    ]
}

fn opt(args: &[String], name: &str) -> Option<String> {
    args.windows(2)
        .find_map(|w| (w[0] == name).then(|| w[1].clone()))
}

fn repeated(args: &[String], name: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut index = 0;
    while index < args.len() {
        if args[index] == name {
            if let Some(value) = args.get(index + 1) {
                out.push(value.clone());
            }
            index += 2;
        } else {
            index += 1;
        }
    }
    out
}

fn has(args: &[String], name: &str) -> bool {
    args.iter().any(|arg| arg == name)
}
fn opt_usize(args: &[String], name: &str, default: usize) -> usize {
    opt(args, name)
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}
fn opt_f64(args: &[String], name: &str, default: f64) -> f64 {
    opt(args, name)
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}
fn path_opt(args: &[String], name: &str) -> Option<PathBuf> {
    opt(args, name).map(PathBuf::from)
}
fn path_required(args: &[String], name: &str) -> Result<PathBuf, String> {
    path_opt(args, name).ok_or_else(|| format!("missing required option {name}"))
}
fn repeated_paths(args: &[String], name: &str) -> Vec<PathBuf> {
    repeated(args, name)
        .into_iter()
        .map(PathBuf::from)
        .collect()
}

fn path_required_any(args: &[String], names: &[&str]) -> Result<PathBuf, String> {
    for name in names {
        if let Some(path) = path_opt(args, name) {
            return Ok(path);
        }
    }
    Err(format!(
        "missing required option: one of {}",
        names.join(", ")
    ))
}

fn tokens_arg(args: &[String]) -> Result<Vec<String>, String> {
    let mut tokens = repeated(args, "--token");
    if let Some(value) = opt(args, "--tokens") {
        tokens.extend(
            value
                .split(',')
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(str::to_owned),
        );
    }
    if tokens.is_empty() {
        let mut after_dashdash = false;
        for arg in args {
            if after_dashdash {
                tokens.push(arg.clone());
            }
            if arg == "--" {
                after_dashdash = true;
            }
        }
    }
    if tokens.is_empty() {
        Err("selection tokens are required via --token, --tokens, or after --".to_owned())
    } else {
        Ok(tokens)
    }
}

fn write_or_print_json(args: &[String], value: &Value) -> Result<(), String> {
    if let Some(output) = path_opt(args, "--output") {
        ops::write_json_file(&output, value)?;
        println!("Wrote: {}", output.display());
    } else {
        print_json(value)?;
    }
    Ok(())
}

fn print_json(value: &Value) -> Result<(), String> {
    println!(
        "{}",
        serde_json::to_string_pretty(value).map_err(|e| e.to_string())?
    );
    Ok(())
}

fn read_diffgr_jsons_in_dir(dir: &Path) -> Result<Vec<PathBuf>, String> {
    let mut out = Vec::new();
    for entry in std::fs::read_dir(dir).map_err(|err| format!("{}: {err}", dir.display()))? {
        let path = entry.map_err(|err| err.to_string())?.path();
        let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
        if path.extension().and_then(|s| s.to_str()) == Some("json") && name != "manifest.json" {
            out.push(path);
        }
    }
    out.sort();
    Ok(out)
}

fn expand_simple_glob(pattern: &str) -> Result<Vec<PathBuf>, String> {
    if !pattern.contains('*') {
        return Ok(vec![PathBuf::from(pattern)]);
    }
    let path = PathBuf::from(pattern);
    let dir = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let file_pat = path.file_name().and_then(|v| v.to_str()).unwrap_or("*");
    let parts = file_pat.split('*').collect::<Vec<_>>();
    let mut out = Vec::new();
    for entry in std::fs::read_dir(dir).map_err(|err| format!("{}: {err}", dir.display()))? {
        let p = entry.map_err(|err| err.to_string())?.path();
        let Some(name) = p.file_name().and_then(|v| v.to_str()) else {
            continue;
        };
        let mut rest = name;
        let mut matched = true;
        for (index, part) in parts.iter().enumerate() {
            if part.is_empty() {
                continue;
            }
            if index == 0 && !file_pat.starts_with('*') {
                if let Some(next) = rest.strip_prefix(part) {
                    rest = next;
                } else {
                    matched = false;
                    break;
                }
            } else if let Some(pos) = rest.find(part) {
                rest = &rest[pos + part.len()..];
            } else {
                matched = false;
                break;
            }
        }
        if matched
            && (!file_pat.ends_with('*')
                && !parts.last().unwrap_or(&"").is_empty()
                && !rest.is_empty())
        {
            matched = false;
        }
        if matched {
            out.push(p);
        }
    }
    out.sort();
    Ok(out)
}

fn open_path(path: &Path) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        Command::new("cmd")
            .arg("/C")
            .arg("start")
            .arg("")
            .arg(path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg(path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new("xdg-open")
            .arg(path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn read_agent_command(config: Option<PathBuf>) -> Option<String> {
    let path = config.unwrap_or_else(|| PathBuf::from("agent_cli.toml"));
    let text = std::fs::read_to_string(path).ok()?;
    let provider = find_toml_string(&text, "provider").unwrap_or_else(|| "codex".to_owned());
    let section = if provider.trim().eq_ignore_ascii_case("claude") {
        "claude"
    } else {
        "codex"
    };
    let command =
        find_toml_section_string(&text, section, "command").unwrap_or_else(|| section.to_owned());
    let args = find_toml_section_array(&text, section, "args").unwrap_or_else(|| {
        if section == "codex" {
            vec!["exec".to_owned()]
        } else {
            vec![
                "-p".to_owned(),
                "--output-format".to_owned(),
                "text".to_owned(),
            ]
        }
    });
    Some(
        std::iter::once(command)
            .chain(args)
            .collect::<Vec<_>>()
            .join(" "),
    )
}

fn find_toml_string(text: &str, key: &str) -> Option<String> {
    for line in text.lines() {
        let line = line.split('#').next().unwrap_or("").trim();
        if let Some(rest) = line.strip_prefix(&format!("{key} =")) {
            return Some(rest.trim().trim_matches('"').to_owned());
        }
    }
    None
}

fn find_toml_section_string(text: &str, section: &str, key: &str) -> Option<String> {
    let mut in_section = false;
    for line in text.lines() {
        let line = line.split('#').next().unwrap_or("").trim();
        if line.starts_with('[') && line.ends_with(']') {
            in_section = &line[1..line.len() - 1] == section;
            continue;
        }
        if in_section {
            if let Some(rest) = line.strip_prefix(&format!("{key} =")) {
                return Some(rest.trim().trim_matches('"').to_owned());
            }
        }
    }
    None
}

fn find_toml_section_array(text: &str, section: &str, key: &str) -> Option<Vec<String>> {
    let mut in_section = false;
    for line in text.lines() {
        let line = line.split('#').next().unwrap_or("").trim();
        if line.starts_with('[') && line.ends_with(']') {
            in_section = &line[1..line.len() - 1] == section;
            continue;
        }
        if in_section {
            if let Some(rest) = line.strip_prefix(&format!("{key} =")) {
                let rest = rest.trim().trim_start_matches('[').trim_end_matches(']');
                return Some(
                    rest.split(',')
                        .map(|s| s.trim().trim_matches('"').to_owned())
                        .filter(|s| !s.is_empty())
                        .collect(),
                );
            }
        }
    }
    None
}

fn split_command_line(line: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut in_quote = false;
    for ch in line.chars() {
        if ch == '"' {
            in_quote = !in_quote;
            continue;
        }
        if ch.is_whitespace() && !in_quote {
            if !current.is_empty() {
                parts.push(std::mem::take(&mut current));
            }
        } else {
            current.push(ch);
        }
    }
    if !current.is_empty() {
        parts.push(current);
    }
    parts
}

fn extract_first_json_object(text: &str) -> Result<Value, String> {
    if let Ok(value) = serde_json::from_str::<Value>(text.trim()) {
        if value.is_object() {
            return Ok(value);
        }
    }
    let bytes = text.as_bytes();
    for start in 0..bytes.len() {
        if bytes[start] != b'{' {
            continue;
        }
        let mut depth = 0i32;
        let mut in_string = false;
        let mut escape = false;
        for end in start..bytes.len() {
            let ch = bytes[end] as char;
            if escape {
                escape = false;
                continue;
            }
            if ch == '\\' && in_string {
                escape = true;
                continue;
            }
            if ch == '"' {
                in_string = !in_string;
                continue;
            }
            if in_string {
                continue;
            }
            if ch == '{' {
                depth += 1;
            }
            if ch == '}' {
                depth -= 1;
                if depth == 0 {
                    let slice = &text[start..=end];
                    if let Ok(value) = serde_json::from_str::<Value>(slice) {
                        if value.is_object() {
                            return Ok(value);
                        }
                    }
                }
            }
        }
    }
    Err("Failed to parse JSON object from agent output.".to_owned())
}

fn normalize_slice_patch(mut value: Value) -> Value {
    if let Some(obj) = value.as_object_mut() {
        let rename = obj.remove("rename").unwrap_or_else(|| json!({}));
        let rename = match rename {
            Value::Array(items) => {
                let mut map = serde_json::Map::new();
                for item in items {
                    if let Some(id) = item.get("id").and_then(Value::as_str) {
                        if let Some(name) = item.get("name").and_then(Value::as_str) {
                            map.insert(id.to_owned(), Value::String(name.to_owned()));
                        }
                    }
                }
                Value::Object(map)
            }
            value @ Value::Object(_) => value,
            _ => json!({}),
        };
        obj.insert("rename".to_owned(), rename);
        if !obj.get("move").map(Value::is_array).unwrap_or(false) {
            obj.insert("move".to_owned(), json!([]));
        }
    }
    value
}

fn copy_to_clipboard(text: &str) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        let mut child = Command::new("powershell")
            .args(["-NoProfile", "-Command", "Set-Clipboard"])
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| e.to_string())?;
        if let Some(stdin) = child.stdin.as_mut() {
            use std::io::Write;
            stdin
                .write_all(text.as_bytes())
                .map_err(|e| e.to_string())?;
        }
        child.wait().map_err(|e| e.to_string())?;
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = text;
    }
    Ok(())
}
