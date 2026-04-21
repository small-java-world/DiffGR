import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_agent_cli import (
    _as_fenced_markdown_block,
    _build_finalize_prompt,
    _build_interactive_initial_prompt,
    _extract_split_conflicts,
    _find_split_name_conflicts,
    main,
    _write_interactive_session_note,
)


class TestRunAgentCliScript(unittest.TestCase):
    def test_as_fenced_markdown_block_expands_fence_for_nested_backticks(self):
        markdown = "# title\n\n```json\n{\"k\": 1}\n```\n"
        block = _as_fenced_markdown_block(markdown)
        first_line = block.splitlines()[0]
        self.assertTrue(first_line.endswith("markdown"))
        fence = first_line[: -len("markdown")]
        self.assertGreaterEqual(len(fence), 4)
        self.assertEqual(set(fence), {"`"})
        self.assertIn("```json", block)
        self.assertTrue(block.rstrip().endswith(fence))

    def test_write_interactive_session_note_keeps_prompt_verbatim(self):
        markdown = "# prompt\n\n```json\n{\"rename\": {}, \"move\": []}\n```\n"
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            prompt_path = repo / "samples" / "prompt.md"
            schema_path = repo / "diffgr" / "slice_patch.schema.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            schema_path.parent.mkdir(parents=True, exist_ok=True)

            note_path = _write_interactive_session_note(
                repo=repo,
                prompt_path=prompt_path,
                schema_path=schema_path,
                prompt_markdown=markdown,
            )
            note = note_path.read_text(encoding="utf-8")

        self.assertIn("同一機能を前半/後半などに分割しない", note)
        section = note.split("## 入力Markdown全文\n", 1)[1]
        lines = section.splitlines()
        self.assertTrue(lines[0].endswith("markdown"))
        fence = lines[0][: -len("markdown")]
        self.assertGreaterEqual(len(fence), 4)
        self.assertEqual(lines[-1], fence)
        self.assertIn("```json", note)

    def test_interactive_prompts_require_function_cohesion(self):
        initial = _build_interactive_initial_prompt(repo=Path("."), note_path=Path("out/agent_cli/interactive_input_bundle.md"))
        finalize = _build_finalize_prompt()
        self.assertIn("同一機能を前半/後半", initial)
        self.assertIn("同一機能を前半/後半", finalize)
        self.assertIn("10-25chunksは目安", finalize)

    def test_find_split_name_conflicts_detects_half_split(self):
        rename = {
            "g-pr03": "準備判定追加(前半)",
            "g-pr05": "準備判定追加(後半)",
            "g-pr01": "計算結果倍化",
        }
        conflicts = _find_split_name_conflicts(rename)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("準備判定追加", conflicts[0])

    def test_extract_split_conflicts_ignores_normal_names(self):
        patch_obj = {
            "rename": {
                "g-pr01": "計算結果倍化",
                "g-pr02": "入力小文字化",
                "g-pr04": "出力タグ追加",
                "g-pr05": "準備判定追加",
            },
            "move": [],
        }
        self.assertEqual(_extract_split_conflicts(patch_obj), [])

    def test_main_noninteractive_retries_once_on_split_conflict(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            (repo / "diffgr").mkdir(parents=True, exist_ok=True)
            (repo / "out").mkdir(parents=True, exist_ok=True)
            config_path = repo / "agent_cli.toml"
            prompt_path = repo / "prompt.md"
            schema_path = repo / "diffgr" / "slice_patch.schema.json"
            output_path = repo / "out" / "slice_patch.json"
            config_path.write_text(
                (
                    'provider = "codex"\n'
                    "[codex]\n"
                    'command = "codex"\n'
                    'args = ["exec"]\n'
                ),
                encoding="utf-8",
            )
            prompt_path.write_text("# prompt", encoding="utf-8")
            schema_path.write_text(
                (
                    "{\n"
                    '  "type": "object",\n'
                    '  "required": ["rename", "move"],\n'
                    '  "properties": {"rename": {"type": "object"}, "move": {"type": "array"}}\n'
                    "}\n"
                ),
                encoding="utf-8",
            )

            bad_patch = {
                "rename": {"g-pr03": "準備判定追加(前半)", "g-pr05": "準備判定追加(後半)"},
                "move": [],
            }
            good_patch = {
                "rename": {"g-pr05": "準備判定追加"},
                "move": [],
            }

            with patch("scripts.run_agent_cli.ROOT", repo), patch(
                "scripts.run_agent_cli.shutil.which", return_value=r"C:\tools\codex.cmd"
            ), patch("scripts.run_agent_cli.run_agent_cli", side_effect=[bad_patch, good_patch]) as run_once:
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "--prompt",
                        str(prompt_path),
                        "--schema",
                        str(schema_path),
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(run_once.call_count, 2)
