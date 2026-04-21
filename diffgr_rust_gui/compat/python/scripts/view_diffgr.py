#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.viewer_cli import parse_view_args, run_view  # noqa: E402
from diffgr.viewer_core import (  # noqa: E402
    VALID_STATUSES,
    build_indexes,
    compute_metrics,
    filter_chunks,
    load_json,
    validate_document,
)
from diffgr.viewer_render import (  # noqa: E402
    render_chunk_detail,
    render_chunks,
    render_groups,
    render_summary,
    status_style,
)


def parse_args(argv: list[str]):
    return parse_view_args(argv)


def main(argv: list[str]) -> int:
    return run_view(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
