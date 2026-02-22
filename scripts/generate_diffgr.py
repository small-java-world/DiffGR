#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.generator import (  # noqa: E402
    build_chunk,
    build_diffgr_document,
    canonical_json,
    iso_utc_now,
    normalize_diff_path,
    parse_generate_args,
    parse_unified_diff,
    run_git,
    sha256_hex,
    write_document,
)


def build_diffgr(repo: Path, base_ref: str, feature_ref: str, title: str, include_patch: bool) -> dict:
    return build_diffgr_document(repo, base_ref, feature_ref, title, include_patch)


def parse_args(argv: list[str]):
    return parse_generate_args(argv)


def main(argv: list[str]) -> int:
    args = parse_generate_args(argv)
    repo = Path(args.repo).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = repo / output
    try:
        document = build_diffgr_document(
            repo=repo,
            base_ref=args.base,
            feature_ref=args.feature,
            title=args.title,
            include_patch=not args.no_patch,
        )
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    write_document(document, output)
    print(f"Wrote: {output}")
    print(f"Chunks: {len(document['chunks'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
