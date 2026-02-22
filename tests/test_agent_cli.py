import unittest
from pathlib import Path
from unittest.mock import patch

from diffgr.agent_cli import (
    AgentCliConfig,
    extract_first_json_object,
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
                prompt_markdown="# prompt",
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
