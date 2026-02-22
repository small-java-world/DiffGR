#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import replace
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


def _as_fenced_markdown_block(markdown_text: str) -> str:
    # Pick an outer fence longer than any fence already present in the text.
    matches = re.findall(r"`+", markdown_text)
    max_run = max((len(run) for run in matches), default=0)
    fence = "`" * max(3, max_run + 1)
    return f"{fence}markdown\n{markdown_text.strip()}\n{fence}\n"


def _has_split_marker_in_name(group_name: str) -> bool:
    text = group_name.lower()
    if re.search(r"(前半|後半|前編|後編)", group_name):
        return True
    if re.search(r"\bpart\s*\d+\b", text):
        return True
    return bool(re.search(r"第\s*[0-9一二三四五六七八九十]+\s*部", group_name))


def _normalize_group_name_for_split_guard(group_name: str) -> str:
    normalized = re.sub(r"[ 　]+", "", group_name)
    normalized = re.sub(
        r"[\(\（][^\)\）]*(前半|後半|前編|後編|part\s*\d+|第\s*[0-9一二三四五六七八九十]+\s*部)[^\)\）]*[\)\）]",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(前半|後半|前編|後編|part\s*\d+|第\s*[0-9一二三四五六七八九十]+\s*部)$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized


def _find_split_name_conflicts(rename: dict[str, str]) -> list[str]:
    by_base: dict[str, list[tuple[str, str]]] = {}
    for group_id, group_name in rename.items():
        if not isinstance(group_name, str):
            continue
        base = _normalize_group_name_for_split_guard(group_name)
        if not base:
            continue
        by_base.setdefault(base, []).append((group_id, group_name))

    problems: list[str] = []
    for base, entries in by_base.items():
        if len(entries) < 2:
            continue
        if not any(_has_split_marker_in_name(name) for _gid, name in entries):
            continue
        joined = ", ".join(f"{gid}:{name}" for gid, name in entries)
        problems.append(f"{base} -> {joined}")
    return problems


def _build_split_policy_retry_prompt(conflicts: list[str]) -> str:
    conflict_lines = "\n".join(f"- {line}" for line in conflicts)
    return (
        "直前のJSONは方針違反です。次を修正してJSONを再出力してください。\n"
        "違反内容:\n"
        f"{conflict_lines}\n"
        "修正ルール:\n"
        "- 同一機能を前半/後半などに分割しない\n"
        "- 必要最小のグループ数へ統合する\n"
        "- move先グループは必ず存在させる\n"
        "- 出力は最終的なJSONオブジェクトのみ"
    )


def _extract_split_conflicts(patch: dict[str, object]) -> list[str]:
    rename = patch.get("rename")
    if not isinstance(rename, dict):
        return []
    rename_map = {str(key): str(value) for key, value in rename.items() if isinstance(value, str)}
    return _find_split_name_conflicts(rename_map)


def _write_interactive_session_note(
    *, repo: Path, prompt_path: Path, schema_path: Path, prompt_markdown: str
) -> Path:
    note_path = repo / "out" / "agent_cli" / "interactive_input_bundle.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        display_prompt_path = str(prompt_path.relative_to(repo))
    except ValueError:
        display_prompt_path = str(prompt_path)
    try:
        display_schema_path = str(schema_path.relative_to(repo))
    except ValueError:
        display_schema_path = str(schema_path)

    note = (
        "# DiffGR 仮想PR分割: 入力バンドル\n\n"
        "このファイルだけで作業を完結させること。\n\n"
        "## 参照ファイル\n"
        f"- 入力Markdown: `{display_prompt_path}`\n"
        f"- 出力Schema: `{display_schema_path}`\n\n"
        "## 固定事項（議論しない）\n"
        "- 分割方針はレビュー意図起点で確定\n"
        "- グループ数（4/6など）は事前に固定しない\n"
        "- 空グループは最終成果物に残さない\n"
        "- 1グループの粒度目安は 10-25 chunks\n"
        "- 10-25 chunksは目安。機能塊維持のためなら下回ってよい\n"
        "- 同一機能を前半/後半などに分割しない（必要最小のグループ数を優先）\n"
        "- order は機能依存順を維持する\n"
        "- 上記方針の是非は議論しない\n\n"
        "## 方針\n"
        "- 分割軸は機能の塊を優先\n"
        "- 同じ機能に属する変更は1グループへ統合する\n"
        "- 空グループは残さない\n"
        "- rename/move のJSONに収束する\n"
        "- 最後に標準ファイル化/パッチ整合へ反映する前提で決める\n"
        "- 反映時の整合条件（move先グループ存在、空グループなし）を満たす\n"
        "- 追加情報要求は禁止（既存の入力Markdownだけで決める）\n"
        "- 入力Markdownに既にある情報の再掲要求は禁止\n"
        "- 追加入力を求める質問は禁止（承認確認1問のみ可）\n"
        "- リポジトリ探索コマンドは実行しない\n"
        "- 必ず最終的な rename/move JSON を返す\n"
        "- 先に暫定案を提示し、承認確認1問を行ってから最終JSONへ進む\n"
        "\n## 入力Markdown全文\n"
        f"{_as_fenced_markdown_block(prompt_markdown)}"
    )
    note_path.write_text(note, encoding="utf-8")
    return note_path


def _build_interactive_initial_prompt(*, repo: Path, note_path: Path) -> str:
    try:
        display_note_path = str(note_path.relative_to(repo))
    except ValueError:
        display_note_path = str(note_path)

    return (
        "DiffGRの仮想PR分割（グループ）を、この入力だけで完結させて決めます。\n"
        "まず次のファイルを開いて、内容を前提に作業してください。\n"
        f"- 入力バンドル: `{display_note_path}`\n"
        "固定事項: 分割方針はレビュー意図起点で確定。ここは議論しません。\n"
        "固定事項: グループ数（4/6など）は事前に固定しません。方針に従って結果として決めます。\n"
        "固定事項: 同一機能を前半/後半などに分割しません。機能塊を優先して必要最小のグループ数にします。\n"
        "必須: 最後の反映（標準ファイル化/パッチ整合）まで見据えて、適用可能な構成にしてください。\n"
        "禁止: 追加データ要求、既存情報の再掲要求、リポジトリ探索コマンド実行。\n"
        "必須: 最初に暫定案を提示し、承認確認を1問だけ行ってユーザー回答を待ってください。\n"
        "この入力バンドルだけで最終案まで出してください。\n"
        "読み込み後、固定事項を復唱してから分割案の改善に入ってください。"
    )


def _build_finalize_prompt() -> str:
    return (
        "これまでの会話内容に基づいて、最終的な slice patch JSON（rename/move）を出力してください。\n"
        "固定事項: 分割方針はレビュー意図起点で確定。ここは議論不要です。\n"
        "固定事項: グループ数（4/6など）は事前に固定しません。方針に従って最終構成を決めてください。\n"
        "固定事項: 同一機能を前半/後半に分割しないでください。機能塊優先で必要最小のグループ数に統合してください。\n"
        "分割は『機能の塊ベース』を優先し、空グループは残さない方針を維持してください。\n"
        "補足: 1グループ10-25chunksは目安であり厳密制約ではありません。機能塊維持を優先してください。\n"
        "必須: 最後に標準ファイル化/パッチ整合へ反映するので、適用可能で整合の取れた rename/move のみを返してください。\n"
        "整合条件: move先グループは必ず存在し、空グループを最終成果物に残さないこと。\n"
        "禁止: 追加データ要求、既存情報の再掲要求、リポジトリ探索コマンド実行、要件整理だけの返答。\n"
        "会話内でユーザー承認済みの案をJSON化してください。\n"
        "必ず最終JSONを返してください。\n"
        "出力はJSONオブジェクトのみで、説明文やMarkdownは不要です。"
    )


def _retry_noninteractive_prompt_for_split_policy(original_prompt: str, conflicts: list[str]) -> str:
    conflict_lines = "\n".join(f"- {line}" for line in conflicts)
    return (
        f"{original_prompt.rstrip()}\n\n"
        "## 追加固定事項（厳守）\n"
        "- 同一機能を前半/後半などに分割しない\n"
        "- 必要最小のグループ数に統合する\n"
        "- 10-25 chunksは目安であり厳密制約ではない\n"
        "\n"
        "## 直前案の違反内容\n"
        f"{conflict_lines}\n"
    )


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
        resolved_cli_command = shutil.which(cli_command)
        if resolved_cli_command is None:
            print(
                f"[error] CLI command not found in PATH: {cli_command}. "
                f"Edit `agent_cli.toml` to set a full path or install the CLI.",
                file=sys.stderr,
            )
            return 1
        if config.provider == "codex":
            config = replace(config, codex_command=resolved_cli_command)
        else:
            config = replace(config, claude_command=resolved_cli_command)
        prompt_markdown = prompt_path.read_text(encoding="utf-8")
        if args.interactive:
            if not (sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()):
                print(
                    "[error] --interactive requires a real terminal (TTY on stdin/stdout/stderr). "
                    "Run from an interactive terminal or omit --interactive.",
                    file=sys.stderr,
                )
                return 1
            do_copy = bool(args.copy_prompt) and not bool(args.no_copy_prompt)
            if do_copy and sys.platform.startswith("win"):
                import subprocess

                shell = shutil.which("powershell") or shutil.which("pwsh")
                if shell is None:
                    print("[warn] Clipboard copy skipped: neither powershell nor pwsh found in PATH.", file=sys.stderr)
                else:
                    subprocess.run(
                        [shell, "-NoProfile", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                        input=prompt_markdown,
                        text=True,
                        capture_output=True,
                    )
                    print(f"Copied prompt to clipboard: {prompt_path}")
            note_path = _write_interactive_session_note(
                repo=repo,
                prompt_path=prompt_path,
                schema_path=schema_path,
                prompt_markdown=prompt_markdown,
            )
            print(f"Wrote input bundle: {note_path}")
            print("Starting interactive session. Use the file paths in the initial message.")
            print("Have at least one approval exchange in chat (example: user replies 'OKで確定').")
            print("When done, exit the session; then this tool will resume the last session to output JSON patch.")

            initial_prompt = _build_interactive_initial_prompt(
                repo=repo,
                note_path=note_path,
            )
            code = start_interactive_session(repo=repo, config=config, initial_prompt=initial_prompt)
            # Many CLIs exit with 130 when the user presses Ctrl+C to leave the interactive session.
            # Treat that as a normal, user-driven exit so we can still resume and emit the final patch JSON.
            if code not in (0, 130):
                return code
            finalize_prompt = _build_finalize_prompt()
            patch = run_agent_cli_from_last_session(
                repo=repo,
                config=config,
                prompt_text=finalize_prompt,
                schema_path=schema_path,
                timeout_s=args.timeout,
            )
            split_conflicts = _extract_split_conflicts(patch)
            if split_conflicts:
                print(
                    "[warn] Detected split-name conflict in patch; retrying once with stricter consolidation rules.",
                    file=sys.stderr,
                )
                patch = run_agent_cli_from_last_session(
                    repo=repo,
                    config=config,
                    prompt_text=_build_split_policy_retry_prompt(split_conflicts),
                    schema_path=schema_path,
                    timeout_s=args.timeout,
                )
                split_conflicts = _extract_split_conflicts(patch)
                if split_conflicts:
                    raise RuntimeError(
                        "Patch policy violation: same function is still split across groups: "
                        + "; ".join(split_conflicts)
                    )
        else:
            patch = run_agent_cli(
                repo=repo,
                config=config,
                prompt_markdown=prompt_markdown,
                schema_path=schema_path,
                timeout_s=args.timeout,
            )
            split_conflicts = _extract_split_conflicts(patch)
            if split_conflicts:
                print(
                    "[warn] Detected split-name conflict in patch; retrying once with stricter consolidation rules.",
                    file=sys.stderr,
                )
                retry_prompt = _retry_noninteractive_prompt_for_split_policy(prompt_markdown, split_conflicts)
                patch = run_agent_cli(
                    repo=repo,
                    config=config,
                    prompt_markdown=retry_prompt,
                    schema_path=schema_path,
                    timeout_s=args.timeout,
                )
                split_conflicts = _extract_split_conflicts(patch)
                if split_conflicts:
                    raise RuntimeError(
                        "Patch policy violation: same function is still split across groups: "
                        + "; ".join(split_conflicts)
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
