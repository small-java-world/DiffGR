#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.slice_patch import apply_slice_patch  # noqa: E402
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply an AI slice patch (rename/move) to a DiffGR document.")
    parser.add_argument("--input", required=True, help="Input DiffGR JSON path.")
    parser.add_argument("--patch", required=True, help="Patch JSON path (rename/move).")
    parser.add_argument("--output", required=True, help="Output DiffGR JSON path.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo = ROOT
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = repo / input_path
    patch_path = Path(args.patch)
    if not patch_path.is_absolute():
        patch_path = repo / patch_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = repo / output_path

    try:
        doc = load_json(input_path)
        validate_document(doc)
        patch = json.loads(patch_path.read_text(encoding="utf-8"))
        new_doc = apply_slice_patch(doc, patch)
        validate_document(new_doc)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

