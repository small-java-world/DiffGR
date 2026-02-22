#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.viewer_app import parse_app_args, render_chunks_page, run_app  # noqa: E402


def parse_args(argv: list[str]):
    return parse_app_args(argv)


def run(argv: list[str]) -> int:
    return run_app(argv)


def main() -> int:
    return run_app(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
