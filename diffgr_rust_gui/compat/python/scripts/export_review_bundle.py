#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_bundle import build_review_bundle_manifest, split_document_into_bundle  # noqa: E402
from diffgr.viewer_core import load_json, print_error, validate_document, write_json  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export immutable review bundle artifacts from a .diffgr.json document.")
    parser.add_argument("--input", required=True, help="Input .diffgr.json path.")
    parser.add_argument("--bundle-out", required=True, help="Output path for bundle.diffgr.json.")
    parser.add_argument("--state-out", required=True, help="Output path for review.state.json.")
    parser.add_argument("--manifest-out", required=True, help="Output path for review.manifest.json.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        doc = load_json(Path(args.input).resolve())
        validate_document(doc)
        bundle_doc, state = split_document_into_bundle(doc)
        manifest = build_review_bundle_manifest(bundle_doc, state)
        bundle_path = Path(args.bundle_out).resolve()
        state_path = Path(args.state_out).resolve()
        manifest_path = Path(args.manifest_out).resolve()
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(bundle_path, bundle_doc)
        write_json(state_path, state)
        write_json(manifest_path, manifest)
        return 0
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
