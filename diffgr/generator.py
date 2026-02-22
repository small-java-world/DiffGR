from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<header>.*)$"
)


def run_git(repo: Path, args: list[str]) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return process.stdout


def iso_utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_diff_path(raw: str) -> str | None:
    value = raw.strip()
    if value == "/dev/null":
        return None
    if value.startswith("a/") or value.startswith("b/"):
        return value[2:]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: Any) -> str:
    payload = canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_unified_diff(diff_text: str) -> list[dict[str, Any]]:
    lines = diff_text.splitlines()
    files: list[dict[str, Any]] = []
    current_file: dict[str, Any] | None = None
    current_hunk: dict[str, Any] | None = None
    index = 0

    while index < len(lines):
        line = lines[index]

        if line.startswith("diff --git "):
            if current_file is not None:
                files.append(current_file)
            parts = line.split()
            a_path = normalize_diff_path(parts[2] if len(parts) > 2 else "")
            b_path = normalize_diff_path(parts[3] if len(parts) > 3 else "")
            current_file = {
                "a_path": a_path,
                "b_path": b_path,
                "meta": [line],
                "hunks": [],
            }
            current_hunk = None
            index += 1
            continue

        if current_file is None:
            index += 1
            continue

        if line.startswith("@@ "):
            match = HUNK_HEADER_RE.match(line)
            if not match:
                raise RuntimeError(f"Unsupported hunk header: {line}")
            old_start = int(match.group("old_start"))
            old_count = int(match.group("old_count") or "1")
            new_start = int(match.group("new_start"))
            new_count = int(match.group("new_count") or "1")
            header = match.group("header").strip()
            current_hunk = {
                "old": {"start": old_start, "count": old_count},
                "new": {"start": new_start, "count": new_count},
                "header": header,
                "lines": [],
                "old_cursor": old_start,
                "new_cursor": new_start,
            }
            current_file["hunks"].append(current_hunk)
            index += 1
            continue

        if current_hunk is not None:
            if line.startswith(" "):
                current_hunk["lines"].append(
                    {
                        "kind": "context",
                        "text": line[1:],
                        "oldLine": current_hunk["old_cursor"],
                        "newLine": current_hunk["new_cursor"],
                    }
                )
                current_hunk["old_cursor"] += 1
                current_hunk["new_cursor"] += 1
                index += 1
                continue
            if line.startswith("+") and not line.startswith("+++ "):
                current_hunk["lines"].append(
                    {
                        "kind": "add",
                        "text": line[1:],
                        "oldLine": None,
                        "newLine": current_hunk["new_cursor"],
                    }
                )
                current_hunk["new_cursor"] += 1
                index += 1
                continue
            if line.startswith("-") and not line.startswith("--- "):
                current_hunk["lines"].append(
                    {
                        "kind": "delete",
                        "text": line[1:],
                        "oldLine": current_hunk["old_cursor"],
                        "newLine": None,
                    }
                )
                current_hunk["old_cursor"] += 1
                index += 1
                continue
            if line.startswith("\\ "):
                current_hunk["lines"].append(
                    {
                        "kind": "meta",
                        "text": line[2:],
                        "oldLine": None,
                        "newLine": None,
                    }
                )
                index += 1
                continue
            current_hunk = None
            continue

        current_file["meta"].append(line)
        index += 1

    if current_file is not None:
        files.append(current_file)
    return files


def build_chunk(
    file_path: str,
    old_range: dict[str, int],
    new_range: dict[str, int],
    header: str | None,
    lines: list[dict[str, Any]],
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stable_input = {
        "filePath": file_path,
        "lines": [{"kind": line["kind"], "text": line["text"]} for line in lines],
    }
    strong_input = {
        "filePath": file_path,
        "old": old_range,
        "new": new_range,
        "header": header or "",
        "lines": [
            {
                "kind": line["kind"],
                "text": line["text"],
                "oldLine": line["oldLine"],
                "newLine": line["newLine"],
            }
            for line in lines
        ],
    }
    chunk_id = sha256_hex(strong_input)
    chunk: dict[str, Any] = {
        "id": chunk_id,
        "filePath": file_path,
        "old": old_range,
        "new": new_range,
        "lines": lines,
        "fingerprints": {
            "stable": sha256_hex(stable_input),
            "strong": sha256_hex(strong_input),
        },
    }
    if header:
        chunk["header"] = header
    if extra_meta:
        chunk["x-meta"] = extra_meta
    return chunk


def build_diffgr_document(
    repo: Path,
    base_ref: str,
    feature_ref: str,
    title: str,
    include_patch: bool,
) -> dict[str, Any]:
    run_git(repo, ["rev-parse", "--verify", base_ref])
    run_git(repo, ["rev-parse", "--verify", feature_ref])

    diff_text = run_git(
        repo,
        ["diff", "--no-color", "--find-renames=50%", f"{base_ref}...{feature_ref}"],
    )
    parsed_files = parse_unified_diff(diff_text)
    chunks: list[dict[str, Any]] = []

    for file_entry in parsed_files:
        file_path = file_entry["b_path"] or file_entry["a_path"] or "UNKNOWN"
        hunks = file_entry["hunks"]
        if hunks:
            for hunk in hunks:
                chunks.append(
                    build_chunk(
                        file_path=file_path,
                        old_range=hunk["old"],
                        new_range=hunk["new"],
                        header=hunk["header"] if hunk["header"] else None,
                        lines=hunk["lines"],
                    )
                )
            continue

        meta_lines = [value for value in file_entry["meta"] if not value.startswith("diff --git ")]
        chunks.append(
            build_chunk(
                file_path=file_path,
                old_range={"start": 0, "count": 0},
                new_range={"start": 0, "count": 0},
                header=None,
                lines=[],
                extra_meta={"diffHeaderLines": meta_lines},
            )
        )

    group_id = "g-all"
    document: dict[str, Any] = {
        "format": "diffgr",
        "version": 1,
        "meta": {
            "title": title,
            "createdAt": iso_utc_now(),
            "source": {
                "type": "git_compare",
                "base": base_ref,
                "head": feature_ref,
                "description": "Generated by scripts/generate_diffgr.py",
            },
        },
        "groups": [{"id": group_id, "name": "All Changes", "order": 1, "tags": ["all"]}],
        "chunks": chunks,
        "assignments": {group_id: [chunk["id"] for chunk in chunks]},
        "reviews": {},
    }
    if include_patch:
        document["patch"] = diff_text
    return document


def write_document(document: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_generate_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a DiffGR v1 JSON document from two git refs.")
    parser.add_argument("--repo", default=".", help="Path to git repository (default: current directory).")
    parser.add_argument("--base", default="sample/ts20-base", help="Base ref (default: sample/ts20-base).")
    parser.add_argument(
        "--feature",
        default="sample/ts20-feature-5pr-pure",
        help="Feature ref (default: sample/ts20-feature-5pr-pure).",
    )
    parser.add_argument(
        "--output",
        default="out/sample-ts20.diffgr.json",
        help="Output path (default: out/sample-ts20.diffgr.json).",
    )
    parser.add_argument(
        "--title",
        default="DiffGR sample from sample/ts20-base...sample/ts20-feature-5pr-pure",
        help="meta.title value.",
    )
    parser.add_argument("--no-patch", action="store_true", help="Do not include optional patch field.")
    return parser.parse_args(argv)
