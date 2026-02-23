#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.impact import build_impact_report  # noqa: E402
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show which virtual PRs/groups are impacted between two DiffGR snapshots.")
    parser.add_argument("--old", required=True, help="Old DiffGR JSON path (usually merged.diffgr.json).")
    parser.add_argument("--new", required=True, help="New DiffGR JSON path (bundle/rebased snapshot).")
    parser.add_argument(
        "--grouping",
        choices=["old", "new"],
        default="old",
        help="Group impact by old groups (default) or new groups.",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.86,
        help="Similarity threshold (0-1) for best-effort matching.",
    )
    parser.add_argument("--max-items", type=int, default=20, help="Max items to list per group/section.")
    parser.add_argument("--output", help="Write Markdown report to this path (UTF-8). If omitted, print to stdout.")
    parser.add_argument("--json", action="store_true", help="Output JSON report only.")
    return parser.parse_args(argv)


def _fmt_sha(source: dict) -> str:
    base_sha = source.get("baseSha")
    head_sha = source.get("headSha")
    merge_base_sha = source.get("mergeBaseSha")
    parts: list[str] = []
    if base_sha:
        parts.append(f"baseSha={base_sha}")
    if head_sha:
        parts.append(f"headSha={head_sha}")
    if merge_base_sha:
        parts.append(f"mergeBaseSha={merge_base_sha}")
    return " ".join(parts)


def _md_chunk_line(item: dict) -> str:
    cid = item.get("id")
    file_path = item.get("filePath") or ""
    header = item.get("header") or ""
    preview = item.get("preview") or ""
    extra: list[str] = []
    if item.get("matchKind"):
        extra.append(f"match={item.get('matchKind')}({item.get('matchScore')}) from={item.get('fromOldId')}")
    extra_text = f" | {'; '.join(extra)}" if extra else ""
    return f"- {cid} | {file_path} | {header} | {preview}{extra_text}"


def render_markdown(report: dict) -> str:
    old = report.get("old", {}) if isinstance(report.get("old"), dict) else {}
    new = report.get("new", {}) if isinstance(report.get("new"), dict) else {}
    match = report.get("match", {}) if isinstance(report.get("match"), dict) else {}
    counts = match.get("counts", {}) if isinstance(match.get("counts"), dict) else {}
    cov = report.get("coverageNew", {}) if isinstance(report.get("coverageNew"), dict) else {}

    lines: list[str] = []
    lines.append("# DiffGR Impact Report")
    lines.append("")
    lines.append("Note: this report shows *diff impact* between snapshots (what changed / what didn't).")
    lines.append("For review progress (reviewed/pending), use `scripts/summarize_diffgr.py` on the current DiffGR JSON.")
    lines.append("")
    lines.append(f"- grouping: `{report.get('grouping','')}`")
    lines.append("")
    lines.append("## Snapshots")
    lines.append(f"- old title: {old.get('title','')}")
    if old.get("createdAt"):
        lines.append(f"- old createdAt: {old.get('createdAt')}")
    if isinstance(old.get("source"), dict):
        source = old["source"]
        lines.append(f"- old source: base={source.get('base')} head={source.get('head')}")
        sha = _fmt_sha(source)
        if sha:
            lines.append(f"- old {sha}")
    lines.append(f"- old chunks: {old.get('chunkCount',0)}")
    lines.append("")
    lines.append(f"- new title: {new.get('title','')}")
    if new.get("createdAt"):
        lines.append(f"- new createdAt: {new.get('createdAt')}")
    if isinstance(new.get("source"), dict):
        source = new["source"]
        lines.append(f"- new source: base={source.get('base')} head={source.get('head')}")
        sha = _fmt_sha(source)
        if sha:
            lines.append(f"- new {sha}")
    lines.append(f"- new chunks: {new.get('chunkCount',0)}")
    lines.append("")

    lines.append("## Match Summary")
    lines.append(
        f"- matched: strong={counts.get('strong',0)} stable={counts.get('stable',0)} delta={counts.get('delta',0)} similar={counts.get('similar',0)}"
    )
    lines.append(f"- oldOnly: {match.get('oldOnly',0)} newOnly: {match.get('newOnly',0)}")
    lines.append(f"- similarityThreshold: {match.get('similarityThreshold')}")
    warnings = match.get("warnings") or []
    lines.append(f"- warnings: {len(warnings)}")
    lines.append("")

    lines.append("## Coverage (New Assignments)")
    lines.append(
        f"- ok={bool(cov.get('ok'))} unassigned={len(cov.get('unassigned') or [])} duplicated={len(cov.get('duplicated') or {})} unknownGroups={len(cov.get('unknown_groups') or [])} unknownChunks={len(cov.get('unknown_chunks') or {})}"
    )
    lines.append("")

    groups = report.get("groups", []) or []
    no_impact: list[str] = []
    impacted: list[str] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id", ""))
        name = str(g.get("name", ""))
        changed = int(g.get("changed", 0) or 0)
        new_count = int(g.get("new", 0) or 0)
        action = str(g.get("action", ""))
        if action == "skip" and changed == 0 and new_count == 0:
            no_impact.append(f"{gid} {name}")
        else:
            impacted.append(f"{gid} {name}")

    lines.append("## Action List")
    lines.append(f"- no impact groups: {len(no_impact)}")
    for item in no_impact:
        lines.append(f"- {item}")
    lines.append("")
    lines.append(f"- impacted groups: {len(impacted)}")
    for item in impacted:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Groups")
    for g in groups:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id", ""))
        name = str(g.get("name", ""))
        action = str(g.get("action", ""))
        lines.append("")
        lines.append(f"### {gid} / {name}")
        lines.append(f"- action: `{action}`")
        if "totalOld" in g:
            lines.append(
                f"- old chunks: total={g.get('totalOld',0)} unchanged={g.get('unchanged',0)} changed={g.get('changed',0)} removed={g.get('removed',0)}"
            )
        else:
            lines.append(
                f"- new chunks: total={g.get('totalNew',0)} unchanged={g.get('unchanged',0)} changed={g.get('changed',0)} new={g.get('new',0)}"
            )

        changed_chunks = g.get("changedChunks") or []
        if changed_chunks:
            lines.append("- changed chunks:")
            for item in changed_chunks:
                if isinstance(item, dict):
                    lines.append(_md_chunk_line(item))

        new_chunks = g.get("newChunks") or []
        if new_chunks:
            lines.append("- new chunks:")
            for item in new_chunks:
                if isinstance(item, dict):
                    lines.append(_md_chunk_line(item))

        removed_chunks = g.get("removedChunks") or []
        if removed_chunks:
            lines.append("- removed chunks:")
            for item in removed_chunks:
                if isinstance(item, dict):
                    lines.append(_md_chunk_line(item))

    lines.append("")
    new_only_chunks = report.get("newOnlyChunks") or []
    lines.append(f"## Unmatched New Chunks (newOnly={len(new_only_chunks)})")
    if new_only_chunks:
        for item in new_only_chunks:
            if isinstance(item, dict):
                lines.append(_md_chunk_line(item))
    else:
        lines.append("- (none)")

    if warnings:
        lines.append("")
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")

    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    old_path = Path(args.old)
    if not old_path.is_absolute():
        old_path = ROOT / old_path
    new_path = Path(args.new)
    if not new_path.is_absolute():
        new_path = ROOT / new_path

    try:
        old_doc = load_json(old_path.resolve())
        validate_document(old_doc)
        new_doc = load_json(new_path.resolve())
        validate_document(new_doc)
        report = build_impact_report(
            old_doc=old_doc,
            new_doc=new_doc,
            grouping=str(args.grouping),
            similarity_threshold=float(args.similarity_threshold),
            max_items_per_group=int(args.max_items),
        )
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    markdown = render_markdown(report)
    if args.output:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown + "\n", encoding="utf-8")
        print(f"Wrote: {out_path}")
        return 0

    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
