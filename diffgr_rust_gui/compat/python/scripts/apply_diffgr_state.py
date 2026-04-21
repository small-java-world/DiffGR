#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_state import apply_review_state, load_diffgr_document, load_review_state  # noqa: E402
from diffgr.viewer_core import print_error, write_json  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply review state JSON to a DiffGR JSON.")
    parser.add_argument("--input", required=True, help="Input DiffGR JSON path.")
    parser.add_argument("--state", required=True, help="State JSON path.")
    parser.add_argument("--output", required=True, help="Output DiffGR JSON path.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    state_path = Path(args.state)
    if not state_path.is_absolute():
        state_path = ROOT / state_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    try:
        doc = load_diffgr_document(input_path.resolve())
        state = load_review_state(state_path.resolve())
        out = apply_review_state(doc, state)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(output_path, out)
        print(f"Wrote: {output_path}")
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
