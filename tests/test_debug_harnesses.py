"""The debug script uses the requested models and isolates per-harness results."""

import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_bridge import BridgeResult
from examples import debug_harnesses as debug


class DebugHarnessesTests(unittest.IsolatedAsyncioTestCase):
    def test_models_and_gemini_catalog_selection(self):
        args = debug.parse_args([])
        configured = {item.name: item for item in debug.harnesses(args)}
        self.assertEqual(configured["codex"].model, "gpt-6-sol")
        self.assertEqual(configured["opencode"].model, "qwen3.5:9b")
        self.assertEqual(configured["claude_code"].model, "qwen3.5:9b")
        self.assertEqual(configured["opencode"].tool_policy, "no_tools")
        self.assertEqual(debug.selected_model(
            configured["antigravity"], {"capabilities": {"models": [
                {"id": "gemini-3.8-pro-high"}, {"id": "gemini-3.7"},
            ]}},
        ), "gemini-3.8-pro-high")
        with self.assertRaisesRegex(ValueError, "absent"):
            debug.selected_model(configured["codex"], {"capabilities": {"models": ["other"]}})

    async def test_agents_part_queries_info_and_poem_for_each_selected_harness(self):
        with tempfile.TemporaryDirectory() as folder:
            args = debug.parse_args(["--part", "agents", "--agents", "codex,opencode",
                                     "--output-dir", folder])

            class FakeClient:
                def __init__(self):
                    self.calls = []

                async def info(self, url):
                    self.calls.append(("info", url))
                    return {"capabilities": {"models": ["gpt-6-sol", "ollama/qwen3.5:9b"]},
                            "usage": {"available": False}}

                async def ask(self, url, prompt, **kwargs):
                    self.calls.append(("ask", url, kwargs))
                    return BridgeResult(url, None, None, "TASK_STATE_COMPLETED", "Стих", {"input_tokens": 3})

            fake = FakeClient()
            with patch.object(debug, "BridgeClient", return_value=fake), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status = await debug.run(args)

            self.assertEqual(status, 0)
            self.assertEqual([call[0] for call in fake.calls], ["info", "ask", "info", "ask"])
            self.assertEqual(fake.calls[-1][2]["tool_policy"], "no_tools")
            summary = next(Path(folder).rglob("summary.json"))
            payload = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(set(payload["harnesses"]), {"codex", "opencode"})
            self.assertEqual(payload["harnesses"]["codex"]["model"], "gpt-6-sol")

    async def test_smells_part_writes_separate_report_and_flags_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "target.py"
            target.write_text("def example():\n    return 1\n", encoding="utf-8")
            args = debug.parse_args(["--part", "smells", "--agents", "opencode",
                                     "--target", str(target), "--rules", "long_method",
                                     "--output-dir", folder])
            report = SimpleNamespace(
                summary=SimpleNamespace(to_dict=lambda: {"passed": 1, "errors": 0}),
                to_json=lambda: '{"summary":{"passed":1}}',
            )

            class FakeService:
                def __init__(self, provider):
                    self.provider = provider

                async def evaluate(self, target, profile, **kwargs):
                    self_target = target
                    assert self_target.path == Path(args.target)
                    assert len(profile.rules) == 1
                    assert self.provider.tool_policy == "no_tools"
                    assert kwargs["model"] == "qwen3.5:9b"
                    return report

            with patch.object(debug, "BridgeClient") as client, \
                 patch.object(debug, "EvaluationService", FakeService), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                client.return_value.info = AsyncMock(return_value={
                    "capabilities": {"models": ["ollama/qwen3.5:9b"]},
                })
                status = await debug.run(args)
            self.assertEqual(status, 0)
            self.assertEqual(len(list(Path(folder).rglob("opencode.code-smells.json"))), 1)

    async def test_info_failure_is_recorded_even_if_poem_succeeds(self):
        with tempfile.TemporaryDirectory() as folder:
            args = debug.parse_args(["--part", "agents", "--agents", "codex",
                                     "--output-dir", folder])
            with patch.object(debug, "BridgeClient") as client, \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                client.return_value.info = AsyncMock(side_effect=RuntimeError("quota unavailable"))
                client.return_value.ask = AsyncMock(return_value=BridgeResult(
                    args.codex_url, None, None, "TASK_STATE_COMPLETED", "Стих",
                ))
                status = await debug.run(args)
            self.assertEqual(status, 1)
            summary = json.loads(next(Path(folder).rglob("summary.json")).read_text(encoding="utf-8"))
            self.assertIn("quota unavailable", summary["harnesses"]["codex"]["info_error"])
