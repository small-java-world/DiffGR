#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.review_split import build_group_output_filename, split_document_by_group  # noqa: E402
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split one DiffGR file into per-group reviewer files.")
    parser.add_argument("--input", required=True, help="Input DiffGR JSON path.")
    parser.add_argument("--output-dir", required=True, help="Directory to write per-group DiffGR files.")
    parser.add_argument("--include-empty", action="store_true", help="Also emit files for empty groups.")
    parser.add_argument(
        "--manifest",
        default="manifest.json",
        help="Manifest file name under output-dir (default: manifest.json).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc = load_json(input_path)
        validate_document(doc)
        split_items = split_document_by_group(doc, include_empty=bool(args.include_empty))
        manifest_items: list[dict[str, object]] = []
        for index, (group, group_doc) in enumerate(split_items, start=1):
            group_id = str(group.get("id", ""))
            group_name = str(group.get("name", group_id))
            filename = build_group_output_filename(index, group_id, group_name)
            target = output_dir / filename
            target.write_text(json.dumps(group_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            manifest_items.append(
                {
                    "groupId": group_id,
                    "groupName": group_name,
                    "chunkCount": len(group_doc.get("chunks", [])),
                    "path": filename,
                }
            )
        manifest_path = output_dir / str(args.manifest)
        manifest_path.write_text(
            json.dumps(
                {
                    "source": str(input_path.resolve()),
                    "fileCount": len(manifest_items),
                    "files": manifest_items,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    print(f"Wrote: {output_dir}")
    print(f"Group files: {len(manifest_items)}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
