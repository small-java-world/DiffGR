#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.agent_cli import (  # noqa: E402
    load_agent_cli_config,
    run_agent_cli,
    run_agent_cli_from_last_session,
    start_interactive_session,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex CLI or Claude Code CLI to produce a slice patch JSON.")
    parser.add_argument(
        "--config",
        default="agent_cli.toml",
        help="Config TOML path (default: agent_cli.toml).",
    )
    parser.add_argument(
        "--prompt",
        default="samples/diffgr/ts20-5pr.refine-prompt.md",
        help="Prompt markdown path (default: samples/diffgr/ts20-5pr.refine-prompt.md).",
    )
    parser.add_argument(
        "--schema",
        default="diffgr/slice_patch.schema.json",
        help="JSON schema path for the output patch (default: diffgr/slice_patch.schema.json).",
    )
    parser.add_argument(
        "--output",
        default="slice_patch.json",
        help="Output patch JSON path (default: slice_patch.json).",
    )
    parser.add_argument("--timeout", type=int, default=180, help="Timeout seconds (default: 180).")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Start an interactive CLI session first, then continue the last session in print mode to emit the JSON patch.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo = ROOT

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo / config_path
    prompt_path = Path(args.prompt)
    if not prompt_path.is_absolute():
        prompt_path = repo / prompt_path
    schema_path = Path(args.schema)
    if not schema_path.is_absolute():
        schema_path = repo / schema_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = repo / output_path

    try:
        config = load_agent_cli_config(config_path)
        prompt_markdown = prompt_path.read_text(encoding="utf-8")
        if args.interactive:
            initial_prompt = (
                "DiffGRの仮想PR分割（グループ）のブラッシュアップを会話で決めます。\n"
                f"まず `{prompt_path}` を読み、rename/move の方針を相談してください。\n"
                "会話が終わったらセッションを終了してください。終了後に、このツールが直近セッションを継続して\n"
                "JSONスキーマに合う slice patch（rename/move）を生成して `slice_patch.json` に保存します。"
            )
            code = start_interactive_session(repo=repo, config=config, initial_prompt=initial_prompt)
            if code != 0:
                return code
            patch = run_agent_cli_from_last_session(
                repo=repo,
                config=config,
                prompt_markdown=prompt_markdown,
                schema_path=schema_path,
                timeout_s=args.timeout,
            )
        else:
            patch = run_agent_cli(
                repo=repo,
                config=config,
                prompt_markdown=prompt_markdown,
                schema_path=schema_path,
                timeout_s=args.timeout,
            )
        output_path.write_text(json.dumps(patch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except FileNotFoundError as error:
        print(f"[error] File not found: {error.filename}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
