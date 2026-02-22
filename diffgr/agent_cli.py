from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentCliConfig:
    provider: str
    codex_command: str = "codex"
    codex_args: tuple[str, ...] = ("exec",)
    codex_interactive_args: tuple[str, ...] = ()
    claude_command: str = "claude"
    claude_args: tuple[str, ...] = ("-p", "--output-format", "text")
    claude_interactive_args: tuple[str, ...] = ()
    claude_query: str = "Use the markdown from stdin and return ONLY the JSON object."


@dataclass(frozen=True)
class CodexRuntimeProfile:
    schema_path: Path
    cleanup_schema_path: Path | None
    normalize_patch_output: bool
    use_output_last_message: bool


def load_agent_cli_config(path: Path) -> AgentCliConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    provider = str(data.get("provider") or "").strip().lower()
    if provider not in {"codex", "claude"}:
        raise RuntimeError("agent cli config must set provider = 'codex' or 'claude'")

    codex = data.get("codex") or {}
    claude = data.get("claude") or {}

    codex_command = str(codex.get("command") or "codex")
    codex_args = tuple(str(value) for value in (codex.get("args") or ["exec"]))
    codex_interactive_args = tuple(str(value) for value in (codex.get("interactive_args") or []))

    claude_command = str(claude.get("command") or "claude")
    claude_args = tuple(str(value) for value in (claude.get("args") or ["-p", "--output-format", "text"]))
    claude_interactive_args = tuple(str(value) for value in (claude.get("interactive_args") or []))
    claude_query = str(claude.get("query") or "Use the markdown from stdin and return ONLY the JSON object.")

    return AgentCliConfig(
        provider=provider,
        codex_command=codex_command,
        codex_args=codex_args,
        codex_interactive_args=codex_interactive_args,
        claude_command=claude_command,
        claude_args=claude_args,
        claude_interactive_args=claude_interactive_args,
        claude_query=claude_query,
    )


def extract_first_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise RuntimeError("Empty agent output; expected JSON.")

    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise RuntimeError("Failed to parse JSON object from agent output.")


def _resolve_command_for_subprocess(command: str) -> str:
    resolved = shutil.which(command)
    if resolved:
        return resolved

    if os.name == "nt":
        command_path = Path(command)
        if not command_path.suffix:
            for ext in (".cmd", ".bat", ".exe", ".com"):
                resolved_with_ext = shutil.which(f"{command}{ext}")
                if resolved_with_ext:
                    return resolved_with_ext

    return command


def _normalize_codex_exec_args(args: tuple[str, ...]) -> tuple[str, ...]:
    # Backward compatibility:
    # Older configs may place codex-global flags (e.g. --ask-for-approval) after "exec".
    # Current codex CLI expects those flags before the subcommand.
    values = list(args)
    if "exec" not in values:
        return args

    exec_index = values.index("exec")
    head = values[:exec_index]
    tail = values[exec_index + 1 :]

    def has_ask_approval_option(tokens: list[str]) -> bool:
        for token in tokens:
            if token in {"--ask-for-approval", "-a"}:
                return True
            if token.startswith("--ask-for-approval=") or token.startswith("-a="):
                return True
        return False

    if has_ask_approval_option(head):
        return args

    moved: list[str] = []
    kept: list[str] = []
    index = 0
    while index < len(tail):
        token = tail[index]
        if token in {"--ask-for-approval", "-a"}:
            if index + 1 < len(tail):
                moved.extend([token, tail[index + 1]])
                index += 2
                continue
            kept.append(token)
            index += 1
            continue
        if token.startswith("--ask-for-approval=") or token.startswith("-a="):
            moved.append(token)
            index += 1
            continue
        kept.append(token)
        index += 1

    return tuple([*head, *moved, "exec", *kept])


def _is_windows() -> bool:
    return os.name == "nt"


def _build_codex_slice_patch_schema() -> dict[str, Any]:
    # Codex response_format requires strict object schemas and does not handle
    # dynamic-key maps like {"rename": {"g-id": "name"}} reliably.
    # Use an array form for rename, then normalize back to map.
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["rename", "move"],
        "properties": {
            "rename": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "name": {"type": "string", "minLength": 1},
                    },
                },
            },
            "move": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["chunk", "to"],
                    "properties": {
                        "chunk": {"type": "string", "minLength": 1},
                        "to": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
    }


def _normalize_slice_patch_for_output(patch: dict[str, Any]) -> dict[str, Any]:
    rename = patch.get("rename")
    if isinstance(rename, list):
        rename_map: dict[str, str] = {}
        for item in rename:
            if not isinstance(item, dict):
                continue
            group_id = item.get("id")
            group_name = item.get("name")
            if isinstance(group_id, str) and group_id and isinstance(group_name, str) and group_name:
                rename_map[group_id] = group_name
        patch["rename"] = rename_map
    elif not isinstance(rename, dict):
        patch["rename"] = {}

    move = patch.get("move")
    if not isinstance(move, list):
        patch["move"] = []

    return patch


def _build_codex_runtime_profile(schema_path: Path) -> CodexRuntimeProfile:
    if not _is_windows():
        return CodexRuntimeProfile(
            schema_path=schema_path,
            cleanup_schema_path=None,
            normalize_patch_output=False,
            use_output_last_message=False,
        )

    schema_fd, schema_path_raw = tempfile.mkstemp(prefix="codex-schema-", suffix=".json")
    os.close(schema_fd)
    codex_schema_path = Path(schema_path_raw)
    codex_schema_path.write_text(json.dumps(_build_codex_slice_patch_schema(), ensure_ascii=False), encoding="utf-8")
    return CodexRuntimeProfile(
        schema_path=codex_schema_path,
        cleanup_schema_path=codex_schema_path,
        normalize_patch_output=True,
        use_output_last_message=True,
    )


def _cleanup_codex_runtime_profile(profile: CodexRuntimeProfile) -> None:
    if profile.cleanup_schema_path is None:
        return
    try:
        profile.cleanup_schema_path.unlink(missing_ok=True)
    except OSError:
        pass


def _run_codex_with_profile(
    *,
    repo: Path,
    prompt_text: str,
    resolved_command: str,
    normalized_args: tuple[str, ...],
    profile: CodexRuntimeProfile,
    timeout_s: int,
    resume_last_session: bool,
) -> dict[str, Any]:
    output_path: Path | None = None
    cmd = [resolved_command, *normalized_args, "--output-schema", str(profile.schema_path)]

    if profile.use_output_last_message:
        out_fd, output_path_raw = tempfile.mkstemp(prefix="codex-last-message-", suffix=".txt")
        os.close(out_fd)
        output_path = Path(output_path_raw)
        cmd.extend(["--output-last-message", str(output_path)])

    if resume_last_session:
        cmd.extend(["resume", "--last", "-"])
    else:
        cmd.append("-")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo),
            input=prompt_text,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout_s,
        )
        if result.returncode != 0:
            label = "codex cli resume failed" if resume_last_session else "codex cli failed"
            raise RuntimeError(f"{label} (exit={result.returncode}): {result.stderr.strip() or result.stdout.strip()}")

        raw = result.stdout
        if output_path is not None and output_path.exists():
            last_message = output_path.read_text(encoding="utf-8")
            if last_message.strip():
                raw = last_message

        patch = extract_first_json_object(raw)
        return _normalize_slice_patch_for_output(patch) if profile.normalize_patch_output else patch
    finally:
        if output_path is not None:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass


def run_codex_cli(
    *,
    repo: Path,
    prompt_markdown: str,
    schema_path: Path,
    command: str,
    args: tuple[str, ...],
    timeout_s: int,
) -> dict[str, Any]:
    # Use "-" to force stdin prompt mode (avoids any ambiguity about prompt sources).
    resolved_command = _resolve_command_for_subprocess(command)
    normalized_args = _normalize_codex_exec_args(args)
    profile = _build_codex_runtime_profile(schema_path)
    try:
        return _run_codex_with_profile(
            repo=repo,
            prompt_text=prompt_markdown,
            resolved_command=resolved_command,
            normalized_args=normalized_args,
            profile=profile,
            timeout_s=timeout_s,
            resume_last_session=False,
        )
    finally:
        _cleanup_codex_runtime_profile(profile)


def run_claude_cli(
    *,
    repo: Path,
    prompt_markdown: str,
    schema_text: str,
    command: str,
    args: tuple[str, ...],
    query: str,
    timeout_s: int,
) -> dict[str, Any]:
    # Feed the main prompt via stdin; use an appended system prompt for the "return JSON only" contract.
    resolved_command = _resolve_command_for_subprocess(command)
    cmd = [resolved_command, *args, "--json-schema", schema_text, "--append-system-prompt", query]
    result = subprocess.run(
        cmd,
        cwd=str(repo),
        input=prompt_markdown,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout_s,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude cli failed (exit={result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return extract_first_json_object(result.stdout)


def run_agent_cli(
    *,
    repo: Path,
    config: AgentCliConfig,
    prompt_markdown: str,
    schema_path: Path,
    timeout_s: int = 120,
) -> dict[str, Any]:
    if config.provider == "codex":
        return run_codex_cli(
            repo=repo,
            prompt_markdown=prompt_markdown,
            schema_path=schema_path,
            command=config.codex_command,
            args=config.codex_args,
            timeout_s=timeout_s,
        )
    schema_text = schema_path.read_text(encoding="utf-8")
    return run_claude_cli(
        repo=repo,
        prompt_markdown=prompt_markdown,
        schema_text=schema_text,
        command=config.claude_command,
        args=config.claude_args,
        query=config.claude_query,
        timeout_s=timeout_s,
    )


def start_interactive_session(*, repo: Path, config: AgentCliConfig, initial_prompt: str) -> int:
    resolved_command = _resolve_command_for_subprocess(
        config.codex_command if config.provider == "codex" else config.claude_command
    )
    if config.provider == "codex":
        cmd = [resolved_command, *config.codex_interactive_args, initial_prompt]
    else:
        cmd = [resolved_command, *config.claude_interactive_args, initial_prompt]
    result = subprocess.run(cmd, cwd=str(repo))
    return int(result.returncode)


def run_agent_cli_from_last_session(
    *,
    repo: Path,
    config: AgentCliConfig,
    prompt_text: str,
    schema_path: Path,
    timeout_s: int = 180,
) -> dict[str, Any]:
    if config.provider == "codex":
        resolved_command = _resolve_command_for_subprocess(config.codex_command)
        normalized_args = _normalize_codex_exec_args(config.codex_args)
        profile = _build_codex_runtime_profile(schema_path)
        try:
            return _run_codex_with_profile(
                repo=repo,
                prompt_text=prompt_text,
                resolved_command=resolved_command,
                normalized_args=normalized_args,
                profile=profile,
                timeout_s=timeout_s,
                resume_last_session=True,
            )
        finally:
            _cleanup_codex_runtime_profile(profile)

    schema_text = schema_path.read_text(encoding="utf-8")
    resolved_command = _resolve_command_for_subprocess(config.claude_command)
    cmd = [
        resolved_command,
        "--continue",
        *config.claude_args,
        "--json-schema",
        schema_text,
        "--append-system-prompt",
        config.claude_query,
    ]
    result = subprocess.run(
        cmd,
        cwd=str(repo),
        input=prompt_text,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout_s,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude cli continue failed (exit={result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return extract_first_json_object(result.stdout)
