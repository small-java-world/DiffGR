#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
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
        help="Start an interactive CLI session first. You provide info via chat, then exit; the tool resumes the last session to emit the JSON patch.",
    )
    parser.add_argument(
        "--copy-prompt",
        action="store_true",
        help="Copy the prompt markdown to clipboard before starting interactive session (Windows PowerShell).",
    )
    parser.add_argument(
        "--no-copy-prompt",
        action="store_true",
        help="Do not copy the prompt to clipboard (overrides --copy-prompt).",
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
        cli_command = config.codex_command if config.provider == "codex" else config.claude_command
        if shutil.which(cli_command) is None:
            print(
                f"[error] CLI command not found in PATH: {cli_command}. "
                f"Edit `agent_cli.toml` to set a full path or install the CLI.",
                file=sys.stderr,
            )
            return 1
        prompt_markdown = prompt_path.read_text(encoding="utf-8")
        if args.interactive:
            do_copy = bool(args.copy_prompt) and not bool(args.no_copy_prompt)
            if do_copy and sys.platform.startswith("win"):
                import subprocess

                shell = "powershell" if shutil.which("powershell") else "pwsh"
                subprocess.run(
                    [shell, "-NoProfile", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                    input=prompt_markdown,
                    text=True,
                    capture_output=True,
                )
                print(f"Copied prompt to clipboard: {prompt_path}")
            print("Starting interactive session. Paste the prompt markdown and discuss the slicing.")
            print("When done, exit the session; then this tool will resume the last session to output JSON patch.")

            initial_prompt = (
                "DiffGRの仮想PR分割（グループ）のブラッシュアップを会話で決めます。\n"
                "これから私が差分要約（Markdown）を貼るので、それを元に質問しながら分割案を詰めてください。\n"
                "最後に、合意した分割案を slice patch（rename/move）JSONとして出力できる状態にしてください。"
            )
            code = start_interactive_session(repo=repo, config=config, initial_prompt=initial_prompt)
            # Many CLIs exit with 130 when the user presses Ctrl+C to leave the interactive session.
            # Treat that as a normal, user-driven exit so we can still resume and emit the final patch JSON.
            if code not in (0, 130):
                return code
            finalize_prompt = (
                "これまでの会話内容に基づいて、最終的な slice patch JSON（rename/move）を出力してください。\n"
                "出力はJSONオブジェクトのみで、説明文やMarkdownは不要です。"
            )
            patch = run_agent_cli_from_last_session(
                repo=repo,
                config=config,
                prompt_text=finalize_prompt,
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
        missing = error.filename or str(error)
        print(f"[error] File not found: {missing}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
