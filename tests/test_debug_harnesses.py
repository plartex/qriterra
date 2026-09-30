"""The standalone example composes public library calls in the right order."""

import io
import json
import tempfile
import unittest
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_bridge import BridgeConnection, BridgeResult
from examples import debug_harnesses as debug


@asynccontextmanager
async def connected(launch, *, client=None):
    yield BridgeConnection(launch.url, started=False)


class DebugHarnessesTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_runs_info_poem_then_checker_in_script(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "target.py"
            target.write_text("def f():\n    return 1\n", encoding="utf-8")
            args = debug.parse_args(["--part", "all", "--agents", "codex",
                                     "--codex-model", "gpt-6-sol",
                                     "--target", str(target), "--rules", "long_method",
                                     "--output-dir", folder])
            events = []

            class FakeClient:
                async def info(self, url):
                    events.append("info")
                    return {"capabilities": {"models": ["gpt-6-sol"]}}

                async def ask(self, url, prompt, **kwargs):
                    events.append("poem")
                    return BridgeResult(url, None, None, "TASK_STATE_COMPLETED", "Стих")

            class FakeService:
                def __init__(self, provider):
                    pass

                async def evaluate(self, target, profile, **kwargs):
                    events.append("evaluate")
                    return SimpleNamespace(
                        summary=SimpleNamespace(to_dict=lambda: {"passed": 1, "errors": 0}),
                        to_json=lambda: '{"summary":{"passed":1}}',
                    )

            with patch.object(debug, "BridgeClient", return_value=FakeClient()), \
                 patch.object(debug, "connect_harness", connected), \
                 patch.object(debug, "EvaluationService", FakeService), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(await debug.run(args), 0)
            self.assertEqual(events, ["info", "poem", "evaluate"])

    def test_models_and_gemini_catalog_selection(self):
        args = debug.parse_args(["--agents", "antigravity,codex,opencode,claude_code"])
        configured = {item.name: item for item in debug.harnesses(args)}
        self.assertEqual(configured["codex"].model, debug.MODELS["codex"])
        self.assertEqual(configured["opencode"].model, debug.MODELS["opencode"])
        self.assertEqual(configured["claude_code"].model, debug.MODELS["claude_code"])
        self.assertEqual(configured["opencode"].tool_policy, "no_tools")
        self.assertEqual(debug.selected_model(
            configured["antigravity"], {"capabilities": {"models": [
                {"id": "gemini-3.8-pro-high"}, {"id": "gemini-3.7"},
            ]}},
        ), "gemini-3.8-pro-high")
        with self.assertRaisesRegex(ValueError, "absent"):
            debug.selected_model(configured["codex"], {"capabilities": {"models": ["other"]}})

    async def test_auto_selection_includes_discovered_antigravity(self):
        with tempfile.TemporaryDirectory() as folder:
            args = debug.parse_args(["--part", "agents", "--agents", "auto", "--output-dir", folder])

            class FakeClient:
                async def capabilities(self, url):
                    if not url.endswith(":8766"):
                        raise OSError("not running")
                    return {"backend": "agy_cli"}

                async def info(self, url):
                    return {"backend": "agy_cli", "capabilities": {
                        "models": ["gemini-3.8-flash-medium"]}}

                async def ask(self, url, prompt, **kwargs):
                    return BridgeResult(url, None, None, "TASK_STATE_COMPLETED", "Стих")

            with patch.object(debug, "discover_harnesses", return_value={
                "antigravity": "C:/tools/agy.exe"}), \
                 patch.object(debug, "BridgeClient", return_value=FakeClient()), \
                 patch.object(debug, "connect_harness", connected), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status = await debug.run(args)
            self.assertEqual(status, 0)
            payload = json.loads(next(Path(folder).rglob("summary.json")).read_text(encoding="utf-8"))
            self.assertEqual(set(payload["harnesses"]), {"antigravity"})

    async def test_agents_part_calls_info_then_poem_for_each_harness(self):
        with tempfile.TemporaryDirectory() as folder:
            args = debug.parse_args(["--part", "agents", "--agents", "codex,opencode",
                                     "--codex-model", "gpt-6-sol",
                                     "--output-dir", folder])

            class FakeClient:
                def __init__(self):
                    self.calls = []

                async def info(self, url):
                    self.calls.append(("info", url))
                    return {"capabilities": {"models": ["gpt-6-sol", "ollama/qwen3.5:9b"]}}

                async def ask(self, url, prompt, **kwargs):
                    self.calls.append(("ask", url, kwargs))
                    return BridgeResult(url, None, None, "TASK_STATE_COMPLETED", "Стих")

            fake = FakeClient()
            with patch.object(debug, "BridgeClient", return_value=fake), \
                 patch.object(debug, "connect_harness", connected), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status = await debug.run(args)
            self.assertEqual(status, 0)
            self.assertEqual([call[0] for call in fake.calls], ["info", "ask", "info", "ask"])
            self.assertEqual(fake.calls[-1][2]["tool_policy"], "no_tools")

    async def test_smells_part_uses_checker_service_and_saves_report(self):
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
                    assert self_target.path.samefile(args.target)
                    assert len(profile.rules) == 1
                    assert self.provider.tool_policy == "no_tools"
                    assert kwargs["model"] == "qwen3.5:9b"
                    return report

            with patch.object(debug, "BridgeClient") as client, \
                 patch.object(debug, "connect_harness", connected), \
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
                 patch.object(debug, "connect_harness", connected), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                client.return_value.info = AsyncMock(side_effect=RuntimeError("quota unavailable"))
                client.return_value.ask = AsyncMock(return_value=BridgeResult(
                    args.codex_url, None, None, "TASK_STATE_COMPLETED", "Стих",
                ))
                status = await debug.run(args)
            self.assertEqual(status, 1)
            summary = json.loads(next(Path(folder).rglob("summary.json")).read_text(encoding="utf-8"))
            self.assertIn("quota unavailable", summary["harnesses"]["codex"]["info_error"])

    async def test_explicit_url_disables_auto_start(self):
        with tempfile.TemporaryDirectory() as folder:
            args = debug.parse_args(["--part", "agents", "--agents", "codex",
                                     "--codex-url", "http://127.0.0.1:9999",
                                     "--output-dir", folder])
            launches = []

            @asynccontextmanager
            async def capture(launch, *, client=None):
                launches.append(launch)
                yield BridgeConnection(launch.url, started=False)

            with patch.object(debug, "BridgeClient") as client, \
                 patch.object(debug, "connect_harness", capture), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                client.return_value.info = AsyncMock(return_value={})
                client.return_value.ask = AsyncMock(return_value=BridgeResult(
                    args.codex_url, None, None, "TASK_STATE_COMPLETED", "Стих"))
                self.assertEqual(await debug.run(args), 0)
            self.assertFalse(launches[0].start_if_missing)
