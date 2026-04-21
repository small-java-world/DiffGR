#!/usr/bin/env python3
"""Run functional parity smoke scenarios for native Rust diffgrctl vs bundled Python app.

This is intentionally separate from:
- tools/verify_python_parity.py: verifies bundled Python source byte-for-byte.
- tools/verify_native_parity.py: verifies native command/option/wrapper coverage.

The functional gate creates temporary fixtures, runs every historical Python
scripts/*.py entry once through the Python compat path and once through native
Rust diffgrctl, and checks that both executions complete and produce the expected
operation output. Pass --strict-shape to additionally compare native and compat summaries. It avoids byte-for-byte comparisons because the
implementations can legitimately differ in timestamps, ordering, wording, and
HTML formatting.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_FILE = ROOT / "NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json"
MANIFEST_FILE = ROOT / "PYTHON_PARITY_MANIFEST.json"

JSON_KEYS_TO_DROP = {
    "createdAt",
    "generatedAt",
    "updatedAt",
    "approvedAt",
    "requestedAt",
    "decisionAt",
    "revokedAt",
    "invalidatedAt",
    "timestamp",
    "created_at",
    "updated_at",
}


@dataclass
class CommandResult:
    code: int
    stdout: str
    stderr: str
    elapsed: float


@dataclass
class ScenarioResult:
    script: str
    native_command: str
    ok: bool
    native_code: int | None = None
    compat_code: int | None = None
    native_summary: Any = None
    compat_summary: Any = None
    error: str | None = None
    elapsed_native: float | None = None
    elapsed_compat: float | None = None


@dataclass
class Side:
    name: str
    root: Path
    fixture: Path
    out: Path
    git_repo: Path

    def p(self, rel: str) -> Path:
        return self.root / rel


@dataclass
class Scenario:
    script: str
    native_command: str
    native_args: Callable[[Side], list[str]]
    compat_args: Callable[[Side], list[str]]
    check: Callable[[Side, CommandResult], Any]
    depends_on: list[str] = field(default_factory=list)
    timeout: int = 40
    server: bool = False


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 40, env: dict[str, str] | None = None) -> CommandResult:
    started = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=env,
    )
    return CommandResult(proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)


def find_native_command(args: argparse.Namespace) -> list[str] | None:
    if args.native_cmd:
        return [args.native_cmd]
    env_cmd = os.environ.get("DIFFGRCTL")
    if env_cmd:
        return shlex.split(env_cmd)
    exe = "diffgrctl.exe" if platform.system().lower().startswith("win") else "diffgrctl"
    for rel in (Path("target/release") / exe, Path("target/debug") / exe):
        candidate = ROOT / rel
        if candidate.exists():
            return [str(candidate)]
    if shutil.which("cargo"):
        return ["cargo", "run", "--quiet", "--bin", "diffgrctl", "--"]
    return None


def python_exe(args: argparse.Namespace) -> str:
    return args.python or os.environ.get("PYTHON") or sys.executable


def compat_command(py: str, script: str, side: Side) -> list[str]:
    return [py, str(ROOT / "compat" / "python" / "scripts" / f"{script}.py")]


def git_available() -> bool:
    return shutil.which("git") is not None


def run_git(repo: Path, args: list[str]) -> None:
    proc = run(["git", "-C", str(repo), *args], timeout=20)
    if proc.code != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr or proc.stdout}")


def make_git_repo(repo: Path) -> tuple[str, str]:
    repo.mkdir(parents=True, exist_ok=True)
    run(["git", "init"], cwd=repo, timeout=20)
    run_git(repo, ["config", "user.email", "diffgr@example.invalid"])
    run_git(repo, ["config", "user.name", "DiffGR Smoke"])
    (repo / "src").mkdir()
    (repo / "src" / "app.rs").write_text("fn main() {\n    println!(\"base\");\n}\n", encoding="utf-8")
    run_git(repo, ["add", "."])
    run_git(repo, ["commit", "-m", "base"])
    run_git(repo, ["tag", "base"])
    run_git(repo, ["checkout", "-b", "feature"])
    (repo / "src" / "app.rs").write_text("fn main() {\n    println!(\"feature\");\n    println!(\"more\");\n}\n", encoding="utf-8")
    (repo / "src" / "lib.rs").write_text("pub fn answer() -> i32 { 42 }\n", encoding="utf-8")
    run_git(repo, ["add", "."])
    run_git(repo, ["commit", "-m", "feature: update app"])
    run_git(repo, ["checkout", "base"])
    return "base", "feature"


def make_state_payload() -> tuple[dict[str, Any], dict[str, Any]]:
    base = {
        "reviews": {
            "ui-0001": {"status": "reviewed", "comment": "looks good"},
            "win-0001": {"status": "needs-re-review", "comment": "check script"},
        },
        "groupBriefs": {
            "g-ui": {"summary": "UI review", "risk": "low"},
        },
        "analysisState": {"selectedGroup": "g-ui", "filter": "all"},
        "threadState": {"ui-0001": {"expanded": True}},
    }
    other = {
        "reviews": {
            "ui-0001": {"status": "needs-re-review", "comment": "changed after review"},
            "ui-0002": {"status": "reviewed", "comment": "newly reviewed"},
            "win-0001": {"status": "reviewed", "comment": "script ok"},
        },
        "groupBriefs": {
            "g-ui": {"summary": "Updated UI review", "risk": "medium"},
            "g-win": {"summary": "Windows wrapper review", "risk": "low"},
        },
        "analysisState": {"selectedGroup": "g-win", "filter": "reviewed"},
        "threadState": {"ui-0002": {"expanded": True}},
    }
    return base, other


def make_modified_doc(doc: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(doc))
    out.setdefault("meta", {})["title"] = "DiffGR smoke modified"
    if out.get("chunks"):
        out["chunks"][0]["lines"].append({"kind": "add", "text": "// parity smoke", "oldLine": None, "newLine": 999})
    extra = json.loads(json.dumps(out["chunks"][0]))
    extra["id"] = "new-0001"
    extra["filePath"] = "src/new_file.rs"
    out["chunks"].append(extra)
    out.setdefault("assignments", {}).setdefault("g-ui", []).append("new-0001")
    return out


def prepare_side(side: Side, py: str | None = None) -> None:
    side.out.mkdir(parents=True, exist_ok=True)
    source_doc = load_json(ROOT / "examples" / "multi_file.diffgr.json")
    minimal_doc = load_json(ROOT / "examples" / "minimal.diffgr.json")
    write_json(side.fixture / "doc.diffgr.json", source_doc)
    reviewed_doc = json.loads(json.dumps(source_doc))
    reviewed_doc["reviews"] = {
        str(chunk.get("id")): {"status": "reviewed", "comment": "functional parity reviewed"}
        for chunk in reviewed_doc.get("chunks", [])
        if isinstance(chunk, dict) and chunk.get("id")
    }
    write_json(side.fixture / "reviewed.diffgr.json", reviewed_doc)
    write_json(side.fixture / "old.diffgr.json", reviewed_doc)
    write_json(side.fixture / "new.diffgr.json", make_modified_doc(source_doc))
    write_json(side.fixture / "minimal.diffgr.json", minimal_doc)
    state_base, state_other = make_state_payload()
    write_json(side.fixture / "base.state.json", state_base)
    write_json(side.fixture / "other.state.json", state_other)
    write_json(
        side.fixture / "layout.json",
        {
            "groups": [
                {"id": "g-ui", "name": "UI polished", "order": 1, "tags": ["ui"]},
                {"id": "g-win", "name": "Windows polished", "order": 2, "tags": ["windows"]},
                {"id": "g-extra", "name": "Extra", "order": 3, "tags": []},
            ],
            "assignments": {"g-ui": ["ui-0001"], "g-win": ["win-0001"], "g-extra": ["ui-0002"]},
            "groupBriefs": {"g-extra": {"summary": "extra review bucket"}},
        },
    )
    write_json(side.fixture / "slice_patch.json", {"rename": {"g-ui": "UI smoke", "g-win": "Windows smoke"}, "move": [{"chunk": "ui-0002", "to": "g-win"}]})
    (side.fixture / "agent_prompt.md").write_text("Return a slice patch for the smoke fixture.\n", encoding="utf-8")
    fake_agent = side.fixture / "fake_agent.py"
    fake_agent.write_text(
        "import sys\n"
        "_ = sys.stdin.read()\n"
        "print('Here is JSON:')\n"
        "print('{\"rename\": {\"g-ui\": \"AI UI\"}, \"move\": [{\"chunk\": \"ui-0002\", \"to\": \"g-win\"}]}')\n",
        encoding="utf-8",
    )
    (side.fixture / "agent_cli.toml").write_text(
        'provider = "codex"\n\n[codex]\ncommand = "' + str(py or "python").replace('\\', '/').replace('"', '\\"') + '"\nargs = ["' + str(fake_agent).replace('\\', '/').replace('"', '\\"') + '"]\n',
        encoding="utf-8",
    )
    if git_available():
        make_git_repo(side.git_repo)


def json_signature(value: Any) -> Any:
    """Small, stable shape signature used for native-vs-compat smoke checks."""
    value = strip_volatile(value)
    if isinstance(value, dict):
        sig: dict[str, Any] = {}
        for key in ("format", "version", "ok", "allApproved", "chunkCount", "groupCount", "reviewCount"):
            if key in value:
                sig[key] = value[key]
        if "chunks" in value and isinstance(value["chunks"], list):
            sig["chunks"] = len(value["chunks"])
            sig["chunkIds"] = sorted(str(c.get("id")) for c in value["chunks"] if isinstance(c, dict) and c.get("id"))[:10]
        if "groups" in value and isinstance(value["groups"], list):
            sig["groups"] = len(value["groups"])
            sig["groupIds"] = sorted(str(g.get("id")) for g in value["groups"] if isinstance(g, dict) and g.get("id"))[:10]
        if "assignments" in value and isinstance(value["assignments"], dict):
            sig["assignments"] = {k: len(v) if isinstance(v, list) else 0 for k, v in sorted(value["assignments"].items())}
        if "reviews" in value and isinstance(value["reviews"], dict):
            sig["reviews"] = sorted(value["reviews"].keys())
        if "groupBriefs" in value and isinstance(value["groupBriefs"], dict):
            sig["groupBriefs"] = sorted(value["groupBriefs"].keys())
        if "errors" in value and isinstance(value["errors"], list):
            sig["errors"] = len(value["errors"])
        if "warnings" in value and isinstance(value["warnings"], list):
            sig["warnings"] = len(value["warnings"])
        return sig
    if isinstance(value, list):
        return {"listLength": len(value)}
    return {"type": type(value).__name__, "value": value}


def strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_volatile(v) for k, v in value.items() if k not in JSON_KEYS_TO_DROP}
    if isinstance(value, list):
        return [strip_volatile(v) for v in value]
    return value


def parse_stdout_json(result: CommandResult) -> Any:
    text = result.stdout.strip()
    if not text:
        raise AssertionError("stdout was empty; expected JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some commands may print a leading status line before JSON. Find the first JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def check_json_file(path: Path) -> Callable[[Side, CommandResult], Any]:
    def _check(side: Side, result: CommandResult) -> Any:
        if result.code != 0:
            raise AssertionError(f"exit {result.code}: {result.stderr or result.stdout}")
        actual = load_json(path if path.is_absolute() else side.root / path)
        return json_signature(actual)

    return _check


def check_stdout_json(side: Side, result: CommandResult) -> Any:
    if result.code != 0:
        raise AssertionError(f"exit {result.code}: {result.stderr or result.stdout}")
    return json_signature(parse_stdout_json(result))


def check_tokens(side: Side, result: CommandResult) -> Any:
    if result.code != 0:
        raise AssertionError(f"exit {result.code}: {result.stderr or result.stdout}")
    tokens = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not tokens:
        raise AssertionError("expected at least one state diff token")
    return {"tokenCount": len(tokens), "prefixes": sorted({token.split(":", 1)[0] for token in tokens})}


def check_text_contains(*needles: str) -> Callable[[Side, CommandResult], Any]:
    def _check(side: Side, result: CommandResult) -> Any:
        if result.code != 0:
            raise AssertionError(f"exit {result.code}: {result.stderr or result.stdout}")
        haystack = result.stdout + result.stderr
        missing = [needle for needle in needles if needle not in haystack]
        if missing:
            raise AssertionError(f"missing text {missing}; stdout={result.stdout!r}; stderr={result.stderr!r}")
        return {"contains": list(needles)}

    return _check


def check_html_file(path: Path) -> Callable[[Side, CommandResult], Any]:
    def _check(side: Side, result: CommandResult) -> Any:
        if result.code != 0:
            raise AssertionError(f"exit {result.code}: {result.stderr or result.stdout}")
        html_path = path if path.is_absolute() else side.root / path
        text = html_path.read_text(encoding="utf-8")
        if "<html" not in text.lower() and "<!doctype" not in text.lower():
            raise AssertionError("HTML output did not contain an html document")
        return {"html": True, "hasDiffgr": "DiffGR" in text or "diffgr" in text.lower()}

    return _check


def check_existing_files(*paths: str) -> Callable[[Side, CommandResult], Any]:
    def _check(side: Side, result: CommandResult) -> Any:
        if result.code != 0:
            raise AssertionError(f"exit {result.code}: {result.stderr or result.stdout}")
        found = []
        for rel in paths:
            p = side.root / rel
            if not p.exists():
                raise AssertionError(f"missing expected file {p}")
            found.append(str(p.relative_to(side.root)))
        return {"files": found}

    return _check


def check_agent_patch(side: Side, result: CommandResult) -> Any:
    if result.code != 0:
        raise AssertionError(f"exit {result.code}: {result.stderr or result.stdout}")
    value = load_json(side.out / "agent_patch.json")
    if not isinstance(value, dict) or "move" not in value:
        raise AssertionError("agent output was not normalized slice patch JSON")
    return json_signature(value)


def require_git_or_skip(args: argparse.Namespace) -> None:
    if not git_available() and not args.allow_skip_git:
        raise SystemExit("git is required for generate/autoslice/prepare parity scenarios; install git or pass --allow-skip-git")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_server(cmd: list[str], *, cwd: Path, port: int, timeout: int, env: dict[str, str] | None = None) -> CommandResult:
    started = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1.0) as response:
                    body = response.read().decode("utf-8", errors="replace")
                    if response.status == 200 and ("<html" in body.lower() or "<!doctype" in body.lower()):
                        return CommandResult(0, body[:500], "", time.monotonic() - started)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(0.2)
        return CommandResult(1, "", f"server did not answer on port {port}: {last_error}", time.monotonic() - started)
    finally:
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=3)
            if err and not err.strip().startswith("KeyboardInterrupt"):
                pass
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=3)


def scenario_defs(py: str) -> list[Scenario]:
    def dquote(value: str) -> str:
        return "\"" + str(value).replace("\"", "") + "\""

    return [
        Scenario(
            "generate_diffgr",
            "generate-diffgr",
            lambda s: ["--repo", str(s.git_repo), "--base", "base", "--feature", "feature", "--output", str(s.out / "generated.diffgr.json"), "--title", "Functional parity smoke"],
            lambda s: ["--repo", str(s.git_repo), "--base", "base", "--feature", "feature", "--output", str(s.out / "generated.diffgr.json"), "--title", "Functional parity smoke"],
            check_json_file(Path("out/generated.diffgr.json")),
        ),
        Scenario(
            "autoslice_diffgr",
            "autoslice-diffgr",
            lambda s: ["--repo", str(s.git_repo), "--base", "base", "--feature", "feature", "--input", str(s.out / "generated.diffgr.json"), "--output", str(s.out / "autosliced.diffgr.json"), "--name-style", "subject", "--no-split"],
            lambda s: ["--repo", str(s.git_repo), "--base", "base", "--feature", "feature", "--input", str(s.out / "generated.diffgr.json"), "--output", str(s.out / "autosliced.diffgr.json"), "--name-style", "subject", "--no-split"],
            check_json_file(Path("out/autosliced.diffgr.json")),
            depends_on=["generate_diffgr"],
        ),
        Scenario(
            "refine_slices",
            "refine-slices",
            lambda s: ["--input", str(s.out / "autosliced.diffgr.json"), "--output", str(s.out / "refined.diffgr.json"), "--write-prompt", str(s.out / "refine_prompt.md")],
            lambda s: ["--input", str(s.out / "autosliced.diffgr.json"), "--output", str(s.out / "refined.diffgr.json"), "--write-prompt", str(s.out / "refine_prompt.md")],
            check_existing_files("out/refined.diffgr.json", "out/refine_prompt.md"),
            depends_on=["autoslice_diffgr"],
        ),
        Scenario(
            "prepare_review",
            "prepare-review",
            lambda s: ["--repo", str(s.git_repo), "--base", "base", "--feature", "feature", "--output", str(s.out / "prepared.diffgr.json"), "--name-style", "pr"],
            lambda s: ["--repo", str(s.git_repo), "--base", "base", "--feature", "feature", "--output", str(s.out / "prepared.diffgr.json"), "--name-style", "pr"],
            check_json_file(Path("out/prepared.diffgr.json")),
        ),
        Scenario(
            "run_agent_cli",
            "run-agent-cli",
            lambda s: ["--config", str(s.fixture / "agent_cli.toml"), "--prompt", str(s.fixture / "agent_prompt.md"), "--schema", str(ROOT / "schemas" / "slice_patch.schema.json"), "--output", str(s.out / "agent_patch.json"), "--command", f"{dquote(py)} {dquote(str(s.fixture / 'fake_agent.py'))}", "--timeout", "10"],
            lambda s: ["--config", str(s.fixture / "agent_cli.toml"), "--prompt", str(s.fixture / "agent_prompt.md"), "--schema", str(ROOT / "schemas" / "slice_patch.schema.json"), "--output", str(s.out / "agent_patch.json"), "--timeout", "10"],
            check_agent_patch,
        ),
        Scenario("apply_slice_patch", "apply-slice-patch", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--patch", str(s.fixture / "slice_patch.json"), "--output", str(s.out / "slice_patched.diffgr.json")], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--patch", str(s.fixture / "slice_patch.json"), "--output", str(s.out / "slice_patched.diffgr.json")], check_json_file(Path("out/slice_patched.diffgr.json"))),
        Scenario("apply_diffgr_layout", "apply-diffgr-layout", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--layout", str(s.fixture / "layout.json"), "--output", str(s.out / "layout.diffgr.json")], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--layout", str(s.fixture / "layout.json"), "--output", str(s.out / "layout.diffgr.json")], check_json_file(Path("out/layout.diffgr.json"))),
        Scenario("view_diffgr", "view-diffgr", lambda s: [str(s.fixture / "doc.diffgr.json"), "--group", "g-ui", "--state", str(s.fixture / "other.state.json"), "--json"], lambda s: [str(s.fixture / "doc.diffgr.json"), "--group", "g-ui", "--state", str(s.fixture / "other.state.json"), "--json"], check_stdout_json),
        Scenario("view_diffgr_app", "view-diffgr-app", lambda s: [str(s.fixture / "doc.diffgr.json"), "--once", "--ui", "prompt", "--state", str(s.fixture / "other.state.json")], lambda s: [str(s.fixture / "doc.diffgr.json"), "--once", "--ui", "prompt", "--state", str(s.fixture / "other.state.json")], check_text_contains("DiffGR")),
        Scenario("export_diffgr_html", "export-diffgr-html", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--output", str(s.out / "report.html"), "--state", str(s.fixture / "other.state.json"), "--title", "Functional Smoke", "--save-state-url", "/api/state", "--save-state-label", "Save"], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--output", str(s.out / "report.html"), "--state", str(s.fixture / "other.state.json"), "--title", "Functional Smoke", "--save-state-url", "/api/state", "--save-state-label", "Save"], check_html_file(Path("out/report.html"))),
        Scenario("serve_diffgr_report", "serve-diffgr-report", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--state", str(s.fixture / "other.state.json"), "--host", "127.0.0.1", "--port", "{PORT}", "--title", "Functional Smoke"], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--state", str(s.fixture / "other.state.json"), "--host", "127.0.0.1", "--port", "{PORT}", "--title", "Functional Smoke"], lambda s, r: {"serverHtml": "html" in r.stdout.lower()}, timeout=8, server=True),
        Scenario("extract_diffgr_state", "extract-diffgr-state", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--output", str(s.out / "extracted.state.json")], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--output", str(s.out / "extracted.state.json")], check_json_file(Path("out/extracted.state.json"))),
        Scenario("apply_diffgr_state", "apply-diffgr-state", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--state", str(s.fixture / "other.state.json"), "--output", str(s.out / "state_applied.diffgr.json")], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--state", str(s.fixture / "other.state.json"), "--output", str(s.out / "state_applied.diffgr.json")], check_json_file(Path("out/state_applied.diffgr.json"))),
        Scenario("diff_diffgr_state", "diff-diffgr-state", lambda s: ["--base", str(s.fixture / "base.state.json"), "--other", str(s.fixture / "other.state.json"), "--tokens-only"], lambda s: ["--base", str(s.fixture / "base.state.json"), "--other", str(s.fixture / "other.state.json"), "--tokens-only"], check_tokens),
        Scenario("merge_diffgr_state", "merge-diffgr-state", lambda s: ["--base", str(s.fixture / "base.state.json"), "--input", str(s.fixture / "other.state.json"), "--output", str(s.out / "merged.state.json"), "--json-summary"], lambda s: ["--base", str(s.fixture / "base.state.json"), "--input", str(s.fixture / "other.state.json"), "--output", str(s.out / "merged.state.json"), "--json-summary"], check_json_file(Path("out/merged.state.json"))),
        Scenario("apply_diffgr_state_diff", "apply-diffgr-state-diff", lambda s: ["--base", str(s.fixture / "base.state.json"), "--other", str(s.fixture / "other.state.json"), "--select", "reviews:ui-0002", "--output", str(s.out / "selected.state.json"), "--json-summary"], lambda s: ["--base", str(s.fixture / "base.state.json"), "--other", str(s.fixture / "other.state.json"), "--select", "reviews:ui-0002", "--output", str(s.out / "selected.state.json"), "--json-summary"], check_json_file(Path("out/selected.state.json"))),
        Scenario("split_group_reviews", "split-group-reviews", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--output-dir", str(s.out / "split"), "--include-empty", "--manifest", "split_manifest.json"], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--output-dir", str(s.out / "split"), "--include-empty", "--manifest", "split_manifest.json"], check_existing_files("out/split/split_manifest.json")),
        Scenario("merge_group_reviews", "merge-group-reviews", lambda s: ["--base", str(s.fixture / "doc.diffgr.json"), "--input", str(s.out / "split" / "01-g-ui-UI.diffgr.json"), "--input", str(s.out / "split" / "02-g-win-Windows.diffgr.json"), "--output", str(s.out / "merged_reviews.diffgr.json")], lambda s: ["--base", str(s.fixture / "doc.diffgr.json"), "--input", str(s.out / "split" / "01-g-ui-UI.diffgr.json"), "--input", str(s.out / "split" / "02-g-win-Windows.diffgr.json"), "--output", str(s.out / "merged_reviews.diffgr.json")], check_json_file(Path("out/merged_reviews.diffgr.json")), depends_on=["split_group_reviews"]),
        Scenario("impact_report", "impact-report", lambda s: ["--old", str(s.fixture / "old.diffgr.json"), "--new", str(s.fixture / "new.diffgr.json"), "--json", "--grouping", "old", "--similarity-threshold", "0.5"], lambda s: ["--old", str(s.fixture / "old.diffgr.json"), "--new", str(s.fixture / "new.diffgr.json"), "--json", "--grouping", "old", "--similarity-threshold", "0.5"], check_stdout_json),
        Scenario("preview_rebased_merge", "preview-rebased-merge", lambda s: ["--old", str(s.fixture / "old.diffgr.json"), "--new", str(s.fixture / "new.diffgr.json"), "--state", str(s.fixture / "base.state.json"), "--json"], lambda s: ["--old", str(s.fixture / "old.diffgr.json"), "--new", str(s.fixture / "new.diffgr.json"), "--state", str(s.fixture / "base.state.json"), "--json"], check_stdout_json),
        Scenario("rebase_diffgr_state", "rebase-diffgr-state", lambda s: ["--old", str(s.fixture / "old.diffgr.json"), "--new", str(s.fixture / "new.diffgr.json"), "--state", str(s.fixture / "base.state.json"), "--output", str(s.out / "rebased.state.json"), "--json-summary", "--no-line-comments", "--similarity-threshold", "0.5"], lambda s: ["--old", str(s.fixture / "old.diffgr.json"), "--new", str(s.fixture / "new.diffgr.json"), "--state", str(s.fixture / "base.state.json"), "--output", str(s.out / "rebased.state.json"), "--json-summary", "--no-line-comments", "--similarity-threshold", "0.5"], check_json_file(Path("out/rebased.state.json"))),
        Scenario("rebase_reviews", "rebase-reviews", lambda s: ["--old", str(s.fixture / "old.diffgr.json"), "--new", str(s.fixture / "new.diffgr.json"), "--output", str(s.out / "rebased_reviews.diffgr.json"), "--json-summary", "--keep-new-groups", "--no-line-comments", "--impact-grouping", "old", "--similarity-threshold", "0.5", "--history-label", "smoke", "--history-actor", "tester"], lambda s: ["--old", str(s.fixture / "old.diffgr.json"), "--new", str(s.fixture / "new.diffgr.json"), "--output", str(s.out / "rebased_reviews.diffgr.json"), "--json-summary", "--keep-new-groups", "--no-line-comments", "--impact-grouping", "old", "--similarity-threshold", "0.5", "--history-label", "smoke", "--history-actor", "tester"], check_json_file(Path("out/rebased_reviews.diffgr.json"))),
        Scenario("export_review_bundle", "export-review-bundle", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--bundle-out", str(s.out / "bundle.diffgr.json"), "--state-out", str(s.out / "review.state.json"), "--manifest-out", str(s.out / "review.manifest.json")], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--bundle-out", str(s.out / "bundle.diffgr.json"), "--state-out", str(s.out / "review.state.json"), "--manifest-out", str(s.out / "review.manifest.json")], check_existing_files("out/bundle.diffgr.json", "out/review.state.json", "out/review.manifest.json")),
        Scenario("verify_review_bundle", "verify-review-bundle", lambda s: ["--bundle", str(s.out / "bundle.diffgr.json"), "--state", str(s.out / "review.state.json"), "--manifest", str(s.out / "review.manifest.json"), "--json"], lambda s: ["--bundle", str(s.out / "bundle.diffgr.json"), "--state", str(s.out / "review.state.json"), "--manifest", str(s.out / "review.manifest.json"), "--json"], check_stdout_json, depends_on=["export_review_bundle"]),
        Scenario("approve_virtual_pr", "approve-virtual-pr", lambda s: ["--input", str(s.fixture / "reviewed.diffgr.json"), "--output", str(s.out / "approved.diffgr.json"), "--all", "--approved-by", "tester"], lambda s: ["--input", str(s.fixture / "reviewed.diffgr.json"), "--output", str(s.out / "approved.diffgr.json"), "--all", "--approved-by", "tester"], check_json_file(Path("out/approved.diffgr.json"))),
        Scenario("request_changes", "request-changes", lambda s: ["--input", str(s.out / "approved.diffgr.json"), "--output", str(s.out / "changes.diffgr.json"), "--group", "g-ui", "--requested-by", "tester", "--comment", "please revisit"], lambda s: ["--input", str(s.out / "approved.diffgr.json"), "--output", str(s.out / "changes.diffgr.json"), "--group", "g-ui", "--requested-by", "tester", "--comment", "please revisit"], check_json_file(Path("out/changes.diffgr.json")), depends_on=["approve_virtual_pr"]),
        Scenario("check_virtual_pr_approval", "check-virtual-pr-approval", lambda s: ["--input", str(s.out / "approved.diffgr.json"), "--json"], lambda s: ["--input", str(s.out / "approved.diffgr.json"), "--json"], check_stdout_json, depends_on=["approve_virtual_pr"]),
        Scenario("check_virtual_pr_coverage", "check-virtual-pr-coverage", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--json", "--write-prompt", str(s.out / "coverage_prompt.md"), "--max-chunks-per-group", "3", "--max-problem-chunks", "10"], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--json", "--write-prompt", str(s.out / "coverage_prompt.md"), "--max-chunks-per-group", "3", "--max-problem-chunks", "10"], check_stdout_json),
        Scenario("summarize_diffgr", "summarize-diffgr", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--json"], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--json"], check_stdout_json),
        Scenario("summarize_diffgr_state", "summarize-diffgr-state", lambda s: ["--input", str(s.fixture / "other.state.json"), "--json"], lambda s: ["--input", str(s.fixture / "other.state.json"), "--json"], check_stdout_json),
        Scenario("summarize_reviewability", "summarize-reviewability", lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--json"], lambda s: ["--input", str(s.fixture / "doc.diffgr.json"), "--json"], check_stdout_json),
    ]


def verify_static_matrix() -> dict[str, Any]:
    manifest = load_json(MANIFEST_FILE)
    scenario_data = load_json(SCENARIO_FILE)
    manifest_stems = sorted(entry["stem"] for entry in manifest.get("entries", []))
    scenario_stems = sorted(item["script"] for item in scenario_data.get("scenarios", []))
    missing = sorted(set(manifest_stems) - set(scenario_stems))
    extra = sorted(set(scenario_stems) - set(manifest_stems))
    duplicate = sorted({x for x in scenario_stems if scenario_stems.count(x) > 1})
    return {
        "ok": not missing and not extra and not duplicate and len(scenario_stems) == 31,
        "manifestScriptCount": len(manifest_stems),
        "scenarioCount": len(scenario_stems),
        "missingScenarios": missing,
        "extraScenarios": extra,
        "duplicateScenarios": duplicate,
    }


def run_one(scenario: Scenario, side: Side, *, native_base: list[str] | None, py: str, is_native: bool) -> CommandResult:
    if is_native:
        assert native_base is not None
        cmd = [*native_base, scenario.native_command, *scenario.native_args(side)]
    else:
        cmd = [*compat_command(py, scenario.script, side), *scenario.compat_args(side)]
    if scenario.server:
        port = free_port()
        cmd = [str(port) if arg == "{PORT}" else arg for arg in cmd]
        return run_server(cmd, cwd=ROOT, port=port, timeout=scenario.timeout)
    return run(cmd, cwd=ROOT, timeout=scenario.timeout)


def run_scenarios(args: argparse.Namespace) -> dict[str, Any]:
    static = verify_static_matrix()
    if not static["ok"]:
        return {"ok": False, "static": static, "results": [], "error": "scenario manifest does not cover all Python scripts"}
    require_git_or_skip(args)
    native_base = find_native_command(args)
    if native_base is None and not args.skip_native_unavailable and not args.compat_only:
        return {"ok": False, "static": static, "results": [], "error": "native diffgrctl not found and cargo is unavailable"}
    py = python_exe(args)
    definitions = scenario_defs(py)
    if args.only:
        selected = set(args.only)
        definitions = [s for s in definitions if s.script in selected]
    scenario_names = {s.script for s in definitions}
    missing_defs = sorted(set(load_json(SCENARIO_FILE)["scenarios"][i]["script"] for i in range(31)) - {s.script for s in scenario_defs(py)})
    if missing_defs:
        return {"ok": False, "static": static, "results": [], "error": f"internal scenario_defs missing {missing_defs}"}

    with tempfile.TemporaryDirectory(prefix="diffgr-functional-parity-") as tmp:
        tmp_path = Path(tmp)
        native_side = Side("native", tmp_path / "native", tmp_path / "native" / "fixtures", tmp_path / "native" / "out", tmp_path / "native" / "repo")
        compat_side = Side("compat", tmp_path / "compat", tmp_path / "compat" / "fixtures", tmp_path / "compat" / "out", tmp_path / "compat" / "repo")
        prepare_side(native_side, py)
        prepare_side(compat_side, py)
        results: list[ScenarioResult] = []
        completed: set[str] = set()
        for scenario in definitions:
            if any(dep not in completed for dep in scenario.depends_on):
                missing_dep = [dep for dep in scenario.depends_on if dep not in completed]
                results.append(ScenarioResult(scenario.script, scenario.native_command, False, error=f"dependency did not complete: {missing_dep}"))
                continue
            if native_base is None and args.skip_native_unavailable and not args.compat_only:
                results.append(ScenarioResult(scenario.script, scenario.native_command, True, native_summary="skipped native unavailable", compat_summary="not run"))
                completed.add(scenario.script)
                continue
            try:
                compat_result = run_one(scenario, compat_side, native_base=native_base, py=py, is_native=False)
                compat_summary = scenario.check(compat_side, compat_result)
                native_result = None
                native_summary = "compat-only" if args.compat_only else None
                if not args.compat_only:
                    native_result = run_one(scenario, native_side, native_base=native_base, py=py, is_native=True)
                    native_summary = scenario.check(native_side, native_result)
                ok = True
                error = None
                if args.strict_shape and not args.compat_only and native_summary != compat_summary:
                    ok = False
                    error = "native/compat output shape differed"
                if args.keep_temp:
                    (tmp_path / "WORKDIR.txt").write_text(str(tmp_path), encoding="utf-8")
                results.append(
                    ScenarioResult(
                        scenario.script,
                        scenario.native_command,
                        ok,
                        native_code=None if native_result is None else native_result.code,
                        compat_code=compat_result.code,
                        native_summary=native_summary,
                        compat_summary=compat_summary,
                        error=error,
                        elapsed_native=None if native_result is None else round(native_result.elapsed, 3),
                        elapsed_compat=round(compat_result.elapsed, 3),
                    )
                )
                if ok:
                    completed.add(scenario.script)
            except Exception as exc:  # noqa: BLE001
                results.append(ScenarioResult(scenario.script, scenario.native_command, False, error=str(exc)))
        payload = {
            "format": "diffgr-native-functional-parity-result",
            "ok": all(item.ok for item in results),
            "static": static,
            "nativeCommand": native_base,
            "python": py,
            "scenarioCount": len(results),
            "passed": sum(1 for item in results if item.ok),
            "failed": [item.script for item in results if not item.ok],
            "results": [item.__dict__ for item in results],
        }
        if args.keep_temp:
            payload["tempDir"] = str(tmp_path)
            # Do not delete temp dir if requested.
            persistent = Path(tempfile.mkdtemp(prefix="diffgr-functional-parity-kept-"))
            shutil.copytree(tmp_path, persistent, dirs_exist_ok=True)
            payload["keptTempDir"] = str(persistent)
        return payload


def print_text(payload: dict[str, Any]) -> None:
    print("# Native functional parity smoke")
    print(f"ok: {payload.get('ok')}")
    if "error" in payload:
        print(f"error: {payload['error']}")
    print(f"scenarios: {payload.get('passed', 0)}/{payload.get('scenarioCount', payload.get('static', {}).get('scenarioCount', 0))}")
    for item in payload.get("results", []):
        status = "ok" if item.get("ok") else "fail"
        print(f"- [{status}] {item.get('script')} -> {item.get('native_command')}")
        if item.get("error"):
            print(f"    {item['error']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify native Rust functional parity against bundled Python DiffGR scripts.")
    parser.add_argument("--json", action="store_true", help="Print JSON result.")
    parser.add_argument("--list", action="store_true", help="Only verify/list the scenario matrix; do not execute commands.")
    parser.add_argument("--native-cmd", help="Path/command for diffgrctl. Defaults to DIFFGRCTL, target/*/diffgrctl, then cargo run.")
    parser.add_argument("--python", help="Python executable for compat scenarios. Defaults to PYTHON env or current interpreter.")
    parser.add_argument("--only", action="append", default=[], help="Run only one scenario by Python script stem. Repeatable.")
    parser.add_argument("--skip-native-unavailable", action="store_true", help="Return success for static coverage when native binary/cargo is unavailable.")
    parser.add_argument("--allow-skip-git", action="store_true", help="Allow environments without git. Git-dependent scenarios are not meaningful without git.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temp workdir copy for debugging failures.")
    parser.add_argument("--strict-shape", action="store_true", help="Require native and compat summaries to be exactly equal. Default only requires both checks to pass.")
    parser.add_argument("--compat-only", action="store_true", help="Run the functional scenario matrix only through bundled Python compatibility scripts.")
    args = parser.parse_args(argv)

    if args.list:
        payload = {"format": "diffgr-native-functional-parity-static", **verify_static_matrix(), "scenarios": load_json(SCENARIO_FILE).get("scenarios", [])}
    else:
        payload = run_scenarios(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text(payload)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
