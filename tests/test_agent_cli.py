import unittest
from pathlib import Path
from unittest.mock import patch

from diffgr.agent_cli import (
    AgentCliConfig,
    extract_first_json_object,
    run_codex_cli,
    run_agent_cli,
    run_agent_cli_from_last_session,
    start_interactive_session,
)


class TestAgentCli(unittest.TestCase):
    def test_extract_first_json_object_parses_plain_json(self):
        obj = extract_first_json_object('{"rename": {"g1": "計算"}, "move": []}')
        self.assertEqual(obj["rename"]["g1"], "計算")

    def test_extract_first_json_object_parses_embedded_json(self):
        obj = extract_first_json_object("note: ok\n{\"rename\": {}, \"move\": [{\"chunk\":\"c1\",\"to\":\"g1\"}]}\n")
        self.assertEqual(obj["move"][0]["chunk"], "c1")

    def test_run_agent_cli_builds_commands(self):
        repo = Path(".").resolve()
        prompt = "# prompt"
        schema_path = repo / "diffgr" / "slice_patch.schema.json"

        with patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"rename": {}, "move": []}'
            run.return_value.stderr = ""
            config = AgentCliConfig(provider="codex", codex_command="codex", codex_args=("exec",))
            patch_obj = run_agent_cli(repo=repo, config=config, prompt_markdown=prompt, schema_path=schema_path, timeout_s=3)
            self.assertEqual(patch_obj["move"], [])
            args, kwargs = run.call_args
            self.assertIn("--output-schema", args[0])
            self.assertIn("-", args[0])
            self.assertEqual(kwargs["input"], prompt)

    def test_interactive_then_resume_builds_commands(self):
        repo = Path(".").resolve()
        schema_path = repo / "diffgr" / "slice_patch.schema.json"
        config = AgentCliConfig(provider="codex", codex_command="codex", codex_args=("exec",), codex_interactive_args=("--sandbox", "read-only"))

        with patch("subprocess.run") as run:
            run.side_effect = [
                # interactive
                type("R", (), {"returncode": 0})(),
                # resume
                type("R", (), {"returncode": 0, "stdout": '{"rename": {}, "move": []}', "stderr": ""})(),
            ]
            code = start_interactive_session(repo=repo, config=config, initial_prompt="hi")
            self.assertEqual(code, 0)
            patch_obj = run_agent_cli_from_last_session(
                repo=repo,
                config=config,
                prompt_text="# prompt",
                schema_path=schema_path,
                timeout_s=3,
            )
            self.assertEqual(patch_obj["rename"], {})
            # second call should be codex exec resume --last
            resume_args, resume_kwargs = run.call_args
            self.assertIn("resume", resume_args[0])
            self.assertIn("--last", resume_args[0])
            self.assertIn("--output-schema", resume_args[0])
            self.assertEqual(resume_kwargs["input"], "# prompt")

    def test_run_agent_cli_uses_resolved_command_path(self):
        repo = Path(".").resolve()
        prompt = "# prompt"
        schema_path = repo / "diffgr" / "slice_patch.schema.json"
        resolved = r"C:\tools\codex.cmd"

        with patch("diffgr.agent_cli.shutil.which", return_value=resolved), patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"rename": {}, "move": []}'
            run.return_value.stderr = ""
            config = AgentCliConfig(provider="codex", codex_command="codex", codex_args=("exec",))
            run_agent_cli(repo=repo, config=config, prompt_markdown=prompt, schema_path=schema_path, timeout_s=3)
            args, _kwargs = run.call_args
            self.assertEqual(args[0][0], resolved)

    def test_run_codex_cli_moves_ask_for_approval_before_exec_and_uses_utf8(self):
        repo = Path(".").resolve()
        prompt = "# prompt"
        schema_path = repo / "diffgr" / "slice_patch.schema.json"

        with patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"rename": {}, "move": []}'
            run.return_value.stderr = ""
            run_codex_cli(
                repo=repo,
                prompt_markdown=prompt,
                schema_path=schema_path,
                command="codex",
                args=("exec", "--sandbox", "read-only", "--ask-for-approval", "never"),
                timeout_s=3,
            )
            args, kwargs = run.call_args
            self.assertIn("codex", str(args[0][0]).lower())
            self.assertEqual(args[0][1:4], ["--ask-for-approval", "never", "exec"])
            self.assertEqual(kwargs["encoding"], "utf-8")

    def test_run_codex_cli_non_windows_uses_given_schema_path(self):
        repo = Path(".").resolve()
        prompt = "# prompt"
        schema_path = repo / "diffgr" / "slice_patch.schema.json"

        with patch("diffgr.agent_cli._is_windows", return_value=False), patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"rename": {}, "move": []}'
            run.return_value.stderr = ""
            run_codex_cli(
                repo=repo,
                prompt_markdown=prompt,
                schema_path=schema_path,
                command="codex",
                args=("exec", "--sandbox", "read-only"),
                timeout_s=3,
            )
            args, _kwargs = run.call_args
            self.assertIn("--output-schema", args[0])
            self.assertIn(str(schema_path), args[0])
            self.assertNotIn("--output-last-message", args[0])

    def test_run_agent_cli_from_last_session_non_windows_uses_given_schema_path(self):
        repo = Path(".").resolve()
        schema_path = repo / "diffgr" / "slice_patch.schema.json"
        config = AgentCliConfig(provider="codex", codex_command="codex", codex_args=("exec",))

        with patch("diffgr.agent_cli._is_windows", return_value=False), patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"rename": {}, "move": []}'
            run.return_value.stderr = ""
            patch_obj = run_agent_cli_from_last_session(
                repo=repo,
                config=config,
                prompt_text="# prompt",
                schema_path=schema_path,
                timeout_s=3,
            )
            self.assertEqual(patch_obj["move"], [])
            args, _kwargs = run.call_args
            self.assertIn("--output-schema", args[0])
            self.assertIn(str(schema_path), args[0])
            self.assertIn("resume", args[0])
            self.assertIn("--last", args[0])
            self.assertNotIn("--output-last-message", args[0])

    def test_start_interactive_session_uses_resolved_command_path(self):
        repo = Path(".").resolve()
        resolved = r"C:\tools\codex.cmd"
        config = AgentCliConfig(provider="codex", codex_command="codex", codex_interactive_args=("--sandbox", "read-only"))

        with patch("diffgr.agent_cli.shutil.which", return_value=resolved), patch("subprocess.run") as run:
            run.return_value.returncode = 0
            code = start_interactive_session(repo=repo, config=config, initial_prompt="hi")
            self.assertEqual(code, 0)
            args, _kwargs = run.call_args
            self.assertEqual(args[0][0], resolved)
