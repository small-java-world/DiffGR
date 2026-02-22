from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .generator import build_chunk, parse_unified_diff, run_git, sha256_hex


@dataclass(frozen=True)
class SliceCommit:
    sha: str
    subject: str
    parent: str | None


def _change_fingerprint_from_parts(
    file_path: str,
    header: str | None,
    change_lines: list[tuple[str, str]],
) -> str:
    payload = {
        "filePath": file_path,
        "changes": [{"kind": kind, "text": text} for kind, text in change_lines],
    }
    return sha256_hex(payload)


def change_fingerprint_for_chunk(chunk: dict[str, Any]) -> str:
    file_path = chunk.get("filePath", "UNKNOWN")
    header = chunk.get("header")
    change_lines: list[tuple[str, str]] = []

    for line in chunk.get("lines", []) or []:
        kind = line.get("kind")
        text = line.get("text", "")
        if kind and kind != "context":
            if kind in {"add", "delete"} and str(text).strip() == "":
                continue
            change_lines.append((kind, text))

    if not change_lines:
        extra = chunk.get("x-meta") or {}
        for meta_line in extra.get("diffHeaderLines", []) or []:
            change_lines.append(("meta", str(meta_line)))

    return _change_fingerprint_from_parts(str(file_path), str(header) if header is not None else None, change_lines)


def _change_blocks(lines: list[dict[str, Any]]) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    index = 0
    while index < len(lines):
        kind = lines[index].get("kind")
        if kind and kind != "context":
            end = index
            while end + 1 < len(lines) and (lines[end + 1].get("kind") not in (None, "context")):
                end += 1
            blocks.append((index, end))
            index = end + 1
            continue
        index += 1
    return blocks


def _slice_segment(lines: list[dict[str, Any]], start: int, end: int, context_lines: int) -> list[dict[str, Any]]:
    blocks = _change_blocks(lines)
    # Find nearest neighbor blocks for overlap avoidance.
    prev_end = -1
    next_start = len(lines)
    for b_start, b_end in blocks:
        if b_end < start:
            prev_end = max(prev_end, b_end)
        if b_start > end:
            next_start = min(next_start, b_start)
    seg_start = max(start - context_lines, prev_end + 1, 0)
    seg_end = min(end + context_lines, next_start - 1, len(lines) - 1)
    return lines[seg_start : seg_end + 1]


def split_chunk_by_change_blocks(chunk: dict[str, Any], context_lines: int = 3) -> list[dict[str, Any]]:
    lines = chunk.get("lines") or []
    if not lines:
        return [chunk]

    blocks = _change_blocks(lines)
    if len(blocks) <= 1:
        return [chunk]

    file_path = chunk.get("filePath", "UNKNOWN")
    header = chunk.get("header")

    result: list[dict[str, Any]] = []
    for start, end in blocks:
        segment_lines = _slice_segment(lines, start, end, context_lines=context_lines)
        old_start = next((ln["oldLine"] for ln in segment_lines if ln.get("oldLine") is not None), 0)
        new_start = next((ln["newLine"] for ln in segment_lines if ln.get("newLine") is not None), 0)
        old_count = sum(1 for ln in segment_lines if ln.get("kind") in {"context", "delete"})
        new_count = sum(1 for ln in segment_lines if ln.get("kind") in {"context", "add"})
        result.append(
            build_chunk(
                file_path=str(file_path),
                old_range={"start": int(old_start), "count": int(old_count)},
                new_range={"start": int(new_start), "count": int(new_count)},
                header=str(header) if header is not None else None,
                lines=segment_lines,
            )
        )
    return result


def change_fingerprints_for_diff_text(diff_text: str, context_lines: int = 3) -> set[str]:
    parsed_files = parse_unified_diff(diff_text)
    fingerprints: set[str] = set()
    for file_entry in parsed_files:
        file_path = file_entry.get("b_path") or file_entry.get("a_path") or "UNKNOWN"
        hunks = file_entry.get("hunks") or []
        if hunks:
            for hunk in hunks:
                hunk_lines = hunk.get("lines") or []
                blocks = _change_blocks(hunk_lines)
                if not blocks:
                    continue
                for start, end in blocks:
                    segment_lines = _slice_segment(hunk_lines, start, end, context_lines=context_lines)
                    change_lines: list[tuple[str, str]] = []
                    for line in segment_lines:
                        kind = line.get("kind")
                        text = line.get("text", "")
                        if kind and kind != "context":
                            if kind in {"add", "delete"} and str(text).strip() == "":
                                continue
                            change_lines.append((kind, text))
                    fingerprints.add(
                        _change_fingerprint_from_parts(
                            file_path=str(file_path),
                            header=hunk.get("header"),
                            change_lines=change_lines,
                        )
                    )
            continue

        meta_lines = [value for value in (file_entry.get("meta") or []) if not str(value).startswith("diff --git ")]
        change_lines = [("meta", str(value)) for value in meta_lines]
        fingerprints.add(_change_fingerprint_from_parts(file_path=str(file_path), header=None, change_lines=change_lines))
    return fingerprints


def list_linear_commits(repo: Path, base_ref: str, feature_ref: str, max_commits: int = 50) -> list[SliceCommit]:
    merge_base = run_git(repo, ["merge-base", base_ref, feature_ref]).strip()
    commit_shas = [
        line.strip()
        for line in run_git(repo, ["rev-list", "--reverse", f"{merge_base}..{feature_ref}"]).splitlines()
        if line.strip()
    ]
    if max_commits and len(commit_shas) > max_commits:
        commit_shas = commit_shas[:max_commits]

    commits: list[SliceCommit] = []
    for sha in commit_shas:
        subject = run_git(repo, ["log", "-1", "--format=%s", sha]).strip()
        parent_line = run_git(repo, ["rev-list", "--parents", "-n", "1", sha]).strip()
        parts = parent_line.split()
        parent = parts[1] if len(parts) >= 2 else None
        commits.append(SliceCommit(sha=sha, subject=subject, parent=parent))
    return commits


def autoslice_document_by_commits(
    *,
    repo: Path,
    doc: dict[str, Any],
    base_ref: str,
    feature_ref: str,
    max_commits: int = 50,
    name_style: str = "subject",
    split_chunks: bool = True,
    context_lines: int = 3,
) -> tuple[dict[str, Any], list[str]]:
    if name_style not in {"subject", "pr"}:
        raise ValueError("name_style must be 'subject' or 'pr'")

    commits = list_linear_commits(repo, base_ref, feature_ref, max_commits=max_commits)
    if not commits:
        raise RuntimeError("No commits found between base and feature; cannot autoslice.")

    # Map change fingerprint -> first commit index that introduced it.
    fingerprint_to_commit_index: dict[str, int] = {}
    warnings: list[str] = []

    for index, commit in enumerate(commits, start=1):
        if not commit.parent:
            warnings.append(f"Commit has no parent (skipped): {commit.sha}")
            continue
        diff_text = run_git(repo, ["diff", "--no-color", f"{commit.parent}", f"{commit.sha}"])
        for fp in change_fingerprints_for_diff_text(diff_text, context_lines=context_lines):
            fingerprint_to_commit_index.setdefault(fp, index)

    groups: list[dict[str, Any]] = []
    assignments: dict[str, list[str]] = {}

    for index, commit in enumerate(commits, start=1):
        group_id = f"g-pr{index:02d}"
        if name_style == "pr":
            name = f"PR{index}"
        else:
            name = commit.subject or f"PR{index}"
        groups.append({"id": group_id, "name": name, "order": index, "tags": ["autoslice", "commit"]})
        assignments[group_id] = []

    original_reviews = doc.get("reviews") or {}
    new_reviews: dict[str, Any] = {}
    new_chunks: list[dict[str, Any]] = []

    unassigned: list[str] = []
    for chunk in doc.get("chunks") or []:
        chunk_id = chunk.get("id")
        review_record = original_reviews.get(chunk_id, {}) if chunk_id else {}

        pieces = split_chunk_by_change_blocks(chunk, context_lines=context_lines) if split_chunks else [chunk]
        for piece in pieces:
            new_chunks.append(piece)
            pid = piece.get("id")
            if pid and review_record:
                new_reviews[pid] = review_record
            if not pid:
                continue
            fp = change_fingerprint_for_chunk(piece)
            idx = fingerprint_to_commit_index.get(fp)
            if idx is None:
                unassigned.append(pid)
                continue
            group_id = f"g-pr{idx:02d}"
            assignments[group_id].append(pid)

    # Drop empty groups from assignments to keep the file small, but keep them in groups list.
    assignments = {group_id: ids for group_id, ids in assignments.items() if ids}

    new_doc = dict(doc)
    new_doc["groups"] = groups
    new_doc["chunks"] = new_chunks
    new_doc["assignments"] = assignments
    new_doc["reviews"] = new_reviews
    new_doc.setdefault("meta", {}).setdefault("x-autoslice", {})
    new_doc["meta"]["x-autoslice"] = {
        "method": "commits",
        "base": base_ref,
        "head": feature_ref,
        "commits": [{"sha": c.sha, "subject": c.subject} for c in commits],
        "unassignedCount": len(unassigned),
        "splitChunks": bool(split_chunks),
        "contextLines": int(context_lines),
    }
    return new_doc, warnings
