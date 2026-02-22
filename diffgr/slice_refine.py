from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GroupNameSuggestion:
    label: str
    name: str
    score: int


_LABELS_JA: dict[str, str] = {
    "compute": "計算ロジック",
    "normalize": "入力正規化",
    "format": "出力フォーマット",
    "stats": "タグ/統計",
    "readiness": "準備判定",
    "misc": "その他",
}

_LABEL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "compute": [
        re.compile(r"\bcompute\d*\b", re.IGNORECASE),
        re.compile(r"\bOFFSET\b", re.IGNORECASE),
        re.compile(r"\bbase\b", re.IGNORECASE),
        re.compile(r"\*\s*\d+"),
    ],
    "normalize": [
        re.compile(r"\bnormalize\d*\b", re.IGNORECASE),
        re.compile(r"\btrim\(\)", re.IGNORECASE),
        re.compile(r"\btoLowerCase\(\)", re.IGNORECASE),
        re.compile(r"\btoUpperCase\(\)", re.IGNORECASE),
    ],
    "format": [
        re.compile(r"\bformat\d*\b", re.IGNORECASE),
        re.compile(r"\btoFixed\(", re.IGNORECASE),
        re.compile(r"\bIntl\.", re.IGNORECASE),
    ],
    "stats": [
        re.compile(r"\bmakeStat\d*\b", re.IGNORECASE),
        re.compile(r"\btags\b", re.IGNORECASE),
        re.compile(r"\bmodule-\d+\b", re.IGNORECASE),
    ],
    "readiness": [
        re.compile(r"\bReady\b", re.IGNORECASE),
        re.compile(r"\bisModule\d+Ready\b", re.IGNORECASE),
        re.compile(r">=\s*0"),
    ],
}


def _chunk_text_for_scoring(chunk: dict[str, Any]) -> str:
    parts: list[str] = []
    parts.append(str(chunk.get("filePath", "")))
    if "header" in chunk:
        parts.append(str(chunk.get("header", "")))
    for line in chunk.get("lines") or []:
        kind = line.get("kind")
        if kind and kind != "context":
            text = str(line.get("text", ""))
            if kind in {"add", "delete"} and text.strip() == "":
                continue
            parts.append(text)
    return "\n".join(parts)


def suggest_group_name_ja(chunks: list[dict[str, Any]]) -> GroupNameSuggestion:
    if not chunks:
        return GroupNameSuggestion(label="misc", name=_LABELS_JA["misc"], score=0)

    text = "\n".join(_chunk_text_for_scoring(chunk) for chunk in chunks)
    scores: dict[str, int] = {}
    for label, patterns in _LABEL_PATTERNS.items():
        scores[label] = sum(len(pattern.findall(text)) for pattern in patterns)

    best_label = max(scores.items(), key=lambda kv: kv[1])[0]
    best_score = scores[best_label]
    if best_score <= 0:
        return GroupNameSuggestion(label="misc", name=_LABELS_JA["misc"], score=0)
    return GroupNameSuggestion(label=best_label, name=_LABELS_JA.get(best_label, best_label), score=best_score)


def refine_group_names_ja(doc: dict[str, Any]) -> dict[str, Any]:
    group_map = {group.get("id"): group for group in (doc.get("groups") or []) if isinstance(group, dict)}
    chunk_map = {chunk.get("id"): chunk for chunk in (doc.get("chunks") or []) if isinstance(chunk, dict)}
    assignments: dict[str, list[str]] = doc.get("assignments") or {}

    rename_map: dict[str, Any] = {}
    for group_id, group in group_map.items():
        chunk_ids = assignments.get(group_id) or []
        chunks = [chunk_map[cid] for cid in chunk_ids if cid in chunk_map]
        suggestion = suggest_group_name_ja(chunks)
        before = group.get("name", "")
        after = suggestion.name if suggestion.label != "misc" else before
        if after and after != before:
            group["name"] = after
        rename_map[group_id] = {
            "before": before,
            "after": group.get("name", before),
            "label": suggestion.label,
            "score": suggestion.score,
        }

    doc.setdefault("meta", {})
    doc["meta"]["x-sliceRefine"] = {"groupRename": rename_map, "lang": "ja", "method": "heuristic"}
    return doc


def build_ai_refine_prompt_markdown(doc: dict[str, Any], max_chunks_per_group: int = 30) -> str:
    groups = doc.get("groups") or []
    assignments = doc.get("assignments") or {}
    chunk_map = {chunk.get("id"): chunk for chunk in (doc.get("chunks") or []) if isinstance(chunk, dict)}

    lines: list[str] = []
    lines.append("# DiffGR 仮想PR分割のブラッシュアップ依頼")
    lines.append("")
    lines.append("目的: 1つの大きい差分を、仮想PR(グループ)に分割してレビューしやすくする。")
    lines.append("制約:")
    lines.append("- 全チャンクを必ずどれか1つのグループに割り当てる")
    lines.append("- グループ名は日本語（短く、目的が伝わる）")
    lines.append("- 各グループはレビュー可能な粒度（大きすぎたら分割、小さすぎたら統合）")
    lines.append("")
    lines.append("出力フォーマット（必須）: 次のJSONだけを返してください。")
    lines.append("```json")
    lines.append('{ "rename": { "g-id": "新しい名前" }, "move": [ { "chunk": "chunk_id", "to": "g-id" } ] }')
    lines.append("```")
    lines.append("")
    lines.append("## 現在のグループとチャンク概要")

    for group in groups:
        group_id = group.get("id")
        group_name = group.get("name", "")
        lines.append("")
        lines.append(f"### {group_id} / {group_name}")
        chunk_ids = assignments.get(group_id) or []
        for cid in chunk_ids[:max_chunks_per_group]:
            chunk = chunk_map.get(cid) or {}
            file_path = chunk.get("filePath", "")
            header = chunk.get("header", "")
            change_lines = []
            for ln in chunk.get("lines") or []:
                kind = ln.get("kind")
                if kind and kind != "context":
                    text = str(ln.get("text", ""))
                    if kind in {"add", "delete"} and text.strip() == "":
                        continue
                    change_lines.append(f"{kind}: {text}")
                if len(change_lines) >= 6:
                    break
            change_preview = " / ".join(change_lines) if change_lines else "(meta-only)"
            lines.append(f"- {cid} | {file_path} | {header} | {change_preview}")
        if len(chunk_ids) > max_chunks_per_group:
            lines.append(f"- ... ({len(chunk_ids) - max_chunks_per_group} more)")

    lines.append("")
    return "\n".join(lines)

