from __future__ import annotations

import json
import subprocess
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
    cmd = [command, *args, "--output-schema", str(schema_path), "-"]
    result = subprocess.run(
        cmd,
        cwd=str(repo),
        input=prompt_markdown,
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    if result.returncode != 0:
        raise RuntimeError(f"codex cli failed (exit={result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return extract_first_json_object(result.stdout)


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
    cmd = [command, *args, "--json-schema", schema_text, "--append-system-prompt", query]
    result = subprocess.run(
        cmd,
        cwd=str(repo),
        input=prompt_markdown,
        text=True,
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
    if config.provider == "codex":
        cmd = [config.codex_command, *config.codex_interactive_args, initial_prompt]
    else:
        cmd = [config.claude_command, *config.claude_interactive_args, initial_prompt]
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
        cmd = [
            config.codex_command,
            *config.codex_args,
            "--output-schema",
            str(schema_path),
            "resume",
            "--last",
            "-",
        ]
        result = subprocess.run(
            cmd,
            cwd=str(repo),
            input=prompt_text,
            text=True,
            capture_output=True,
            timeout=timeout_s,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"codex cli resume failed (exit={result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
            )
        return extract_first_json_object(result.stdout)

    schema_text = schema_path.read_text(encoding="utf-8")
    cmd = [
        config.claude_command,
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
        capture_output=True,
        timeout=timeout_s,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude cli continue failed (exit={result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return extract_first_json_object(result.stdout)
