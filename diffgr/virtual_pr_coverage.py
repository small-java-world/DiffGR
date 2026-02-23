from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CoverageIssue:
    unassigned: list[str]
    duplicated: dict[str, list[str]]
    unknown_groups: list[str]
    unknown_chunks: dict[str, list[str]]

    @property
    def ok(self) -> bool:
        return not (self.unassigned or self.duplicated or self.unknown_groups or self.unknown_chunks)


def _group_sort_key(group: dict[str, Any]) -> tuple:
    return (
        group.get("order") is None,
        group.get("order", 0),
        str(group.get("name", "")),
        str(group.get("id", "")),
    )


def _chunk_change_preview(chunk: dict[str, Any], *, max_lines: int = 6) -> str:
    lines: list[str] = []
    for ln in chunk.get("lines") or []:
        kind = ln.get("kind")
        if not kind or kind == "context":
            continue
        text = str(ln.get("text", ""))
        if kind in {"add", "delete"} and text.strip() == "":
            continue
        lines.append(f"{kind}: {text}")
        if len(lines) >= max_lines:
            break
    return " / ".join(lines) if lines else "(meta-only)"


def analyze_virtual_pr_coverage(doc: dict[str, Any]) -> CoverageIssue:
    groups = [group for group in doc.get("groups", []) if isinstance(group, dict)]
    chunks = [chunk for chunk in doc.get("chunks", []) if isinstance(chunk, dict)]
    assignments = doc.get("assignments", {})

    group_ids = {str(group.get("id")) for group in groups if str(group.get("id", ""))}
    chunk_ids = {str(chunk.get("id")) for chunk in chunks if str(chunk.get("id", ""))}

    unknown_groups: list[str] = []
    unknown_chunks: dict[str, list[str]] = {}
    assigned_by_chunk: dict[str, set[str]] = {}

    if isinstance(assignments, dict):
        for group_id_raw, assigned in assignments.items():
            group_id = str(group_id_raw)
            if group_id not in group_ids:
                unknown_groups.append(group_id)
            if not isinstance(assigned, list):
                continue
            for chunk_id_raw in assigned:
                chunk_id = str(chunk_id_raw)
                if chunk_id not in chunk_ids:
                    unknown_chunks.setdefault(chunk_id, []).append(group_id)
                    continue
                assigned_by_chunk.setdefault(chunk_id, set()).add(group_id)

    assigned_any = set(assigned_by_chunk.keys())
    unassigned = sorted(chunk_ids - assigned_any)
    duplicated = {chunk_id: sorted(list(group_ids)) for chunk_id, group_ids in assigned_by_chunk.items() if len(group_ids) > 1}
    unknown_groups_sorted = sorted(set(unknown_groups))
    unknown_chunks_sorted = {chunk_id: sorted(set(groups)) for chunk_id, groups in unknown_chunks.items()}
    return CoverageIssue(
        unassigned=unassigned,
        duplicated=dict(sorted(duplicated.items(), key=lambda item: item[0])),
        unknown_groups=unknown_groups_sorted,
        unknown_chunks=dict(sorted(unknown_chunks_sorted.items(), key=lambda item: item[0])),
    )


def build_ai_fix_coverage_prompt_markdown(
    doc: dict[str, Any],
    issue: CoverageIssue,
    *,
    max_chunks_per_group: int = 20,
    max_problem_chunks: int = 80,
) -> str:
    groups = [group for group in doc.get("groups", []) if isinstance(group, dict)]
    groups.sort(key=_group_sort_key)
    assignments = doc.get("assignments", {})
    chunk_map = {
        str(chunk.get("id")): chunk
        for chunk in doc.get("chunks", [])
        if isinstance(chunk, dict) and str(chunk.get("id", ""))
    }

    title = str((doc.get("meta") or {}).get("title", "DiffGR"))

    lines: list[str] = []
    lines.append("# DiffGR 仮想PR網羅チェック: 修正依頼")
    lines.append("")
    lines.append("目的: 仮想PR(グループ)の組み合わせで差分(chunks)を100%網羅する。")
    lines.append("必須条件:")
    lines.append("- 全 chunk を必ずどれか1つの group に割り当てる（unassigned を 0 にする）")
    lines.append("- 1 chunk は同時に複数 group に入れない（重複割当を 0 にする）")
    lines.append("- move 先 group は必ず既存の group id を使う（新規 group は作らない）")
    lines.append("")
    lines.append("出力フォーマット（必須）: 次の JSON だけを返してください。")
    lines.append("```json")
    lines.append('{ "rename": {}, "move": [ { "chunk": "chunk_id", "to": "g-id" } ] }')
    lines.append("```")
    lines.append("")
    lines.append(f"- title: {title}")
    lines.append("")

    lines.append("## 問題")
    if issue.ok:
        lines.append("")
        lines.append("- (none) 既に網羅されています。")
    else:
        if issue.unassigned:
            lines.append("")
            lines.append(f"### Unassigned chunks ({len(issue.unassigned)})")
            for chunk_id in issue.unassigned[:max_problem_chunks]:
                chunk = chunk_map.get(chunk_id) or {}
                lines.append(
                    f"- {chunk_id} | {chunk.get('filePath','')} | {chunk.get('header','')} | {_chunk_change_preview(chunk)}"
                )
            if len(issue.unassigned) > max_problem_chunks:
                lines.append(f"- ... ({len(issue.unassigned) - max_problem_chunks} more)")

        if issue.duplicated:
            lines.append("")
            lines.append(f"### Duplicated assignment ({len(issue.duplicated)})")
            duplicated_items = list(issue.duplicated.items())
            for chunk_id, group_ids in duplicated_items[:max_problem_chunks]:
                chunk = chunk_map.get(chunk_id) or {}
                lines.append(
                    f"- {chunk_id} | groups={','.join(group_ids)} | {chunk.get('filePath','')} | {chunk.get('header','')} | {_chunk_change_preview(chunk)}"
                )
            if len(duplicated_items) > max_problem_chunks:
                lines.append(f"- ... ({len(duplicated_items) - max_problem_chunks} more)")

        if issue.unknown_groups:
            lines.append("")
            lines.append(f"### Unknown group ids in assignments ({len(issue.unknown_groups)})")
            for group_id in issue.unknown_groups[:max_problem_chunks]:
                lines.append(f"- {group_id}")

        if issue.unknown_chunks:
            lines.append("")
            lines.append(f"### Unknown chunk ids in assignments ({len(issue.unknown_chunks)})")
            unknown_items = list(issue.unknown_chunks.items())
            for chunk_id, groups_for_chunk in unknown_items[:max_problem_chunks]:
                lines.append(f"- {chunk_id} | in groups={','.join(groups_for_chunk)}")

    lines.append("")
    lines.append("## 既存グループ一覧（move先の候補）")
    for group in groups:
        group_id = str(group.get("id", ""))
        group_name = str(group.get("name", ""))
        assigned = []
        if isinstance(assignments, dict):
            assigned = assignments.get(group_id, []) if isinstance(assignments.get(group_id, []), list) else []
        known_ids = [str(cid) for cid in assigned if str(cid) in chunk_map]
        lines.append("")
        lines.append(f"### {group_id} / {group_name} (chunks={len(known_ids)})")
        for chunk_id in known_ids[:max_chunks_per_group]:
            chunk = chunk_map.get(chunk_id) or {}
            lines.append(
                f"- {chunk_id} | {chunk.get('filePath','')} | {chunk.get('header','')} | {_chunk_change_preview(chunk)}"
            )
        if len(known_ids) > max_chunks_per_group:
            lines.append(f"- ... ({len(known_ids) - max_chunks_per_group} more)")

    lines.append("")
    return "\n".join(lines)


def coverage_issue_to_json(issue: CoverageIssue) -> str:
    return json.dumps(
        {
            "ok": issue.ok,
            "unassigned": issue.unassigned,
            "duplicated": issue.duplicated,
            "unknownGroups": issue.unknown_groups,
            "unknownChunks": issue.unknown_chunks,
        },
        ensure_ascii=False,
        indent=2,
    )
