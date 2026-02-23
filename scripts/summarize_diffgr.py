#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.summary import summarize_document  # noqa: E402
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a DiffGR JSON (progress/coverage/source).")
    parser.add_argument("--input", required=True, help="Input DiffGR JSON path.")
    parser.add_argument("--json", action="store_true", help="Output JSON summary only.")
    return parser.parse_args(argv)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    try:
        doc = load_json(input_path.resolve())
        validate_document(doc)
        summary = summarize_document(doc)
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    source = summary.get("source", {}) if isinstance(summary.get("source"), dict) else {}
    base = source.get("base")
    head = source.get("head")
    base_sha = source.get("baseSha")
    head_sha = source.get("headSha")
    merge_base_sha = source.get("mergeBaseSha")

    cov = summary.get("coverage", {}) if isinstance(summary.get("coverage"), dict) else {}
    review = summary.get("review", {}) if isinstance(summary.get("review"), dict) else {}
    rate = float(review.get("CoverageRate", 0.0) or 0.0)

    print(f"File: {input_path.resolve()}")
    print(f"Title: {summary.get('title','')}")
    if summary.get("createdAt"):
        print(f"CreatedAt: {summary.get('createdAt')}")
    if base or head:
        print(f"Source: base={base} head={head}")
    if base_sha or head_sha or merge_base_sha:
        print(f"SHA: baseSha={base_sha} headSha={head_sha} mergeBaseSha={merge_base_sha}")
    print(f"Chunks: {summary.get('chunkCount',0)} Groups: {summary.get('groupCount',0)}")

    if cov:
        print(
            "Coverage:"
            f" ok={bool(cov.get('ok'))}"
            f" unassigned={len(cov.get('unassigned') or [])}"
            f" duplicated={len(cov.get('duplicated') or {})}"
            f" unknownGroups={len(cov.get('unknown_groups') or [])}"
            f" unknownChunks={len(cov.get('unknown_chunks') or {})}"
        )

    print(
        "Review:"
        f" tracked={review.get('Tracked',0)}"
        f" reviewed={review.get('Reviewed',0)}"
        f" pending={review.get('Pending',0)}"
        f" ignored={(summary.get('chunkCount',0) - review.get('Tracked',0)) if isinstance(summary.get('chunkCount',0), int) else '?'}"
        f" rate={_pct(rate)}"
    )

    print("")
    print("Groups:")
    for group in summary.get("groups", []) or []:
        if not isinstance(group, dict):
            continue
        gid = str(group.get("id", ""))
        name = str(group.get("name", ""))
        reviewed = int(group.get("reviewed", 0) or 0)
        tracked = int(group.get("tracked", 0) or 0)
        total = int(group.get("total", 0) or 0)
        rate_group = float(group.get("rate", 0.0) or 0.0)
        print(f"- {gid} {name}: reviewed={reviewed}/{tracked}({_pct(rate_group)}) total={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

