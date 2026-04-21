#!/usr/bin/env python3
"""Verify the GUI completion portion of the consolidated self-review gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_self_review import run  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify DiffGR GUI completion self-review gates.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check-subgates", action="store_true")
    parser.add_argument("--write-audit", default="GUI_COMPLETION_AUDIT.json")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = run(root, strict=args.check_subgates)
    result["format"] = "diffgr-gui-completion-verify-result"
    (root / args.write_audit).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"GUI completion verify: {'ok' if result['ok'] else 'failed'}")
        for check in result["checks"]:
            print(f"- {'ok' if check['ok'] else 'NG'}: {check['name']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
