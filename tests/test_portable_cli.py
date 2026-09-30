"""CLI addresses a profile without depending on neighboring repositories."""

import unittest
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_code_checker.cli import _project_harness, main


class PortableCliTests(unittest.TestCase):
    def test_project_harness_accepts_new_and_legacy_provider_prefix(self):
        expected = _project_harness("agent-bridge:codex")
        self.assertEqual(_project_harness("agent-shuttle:codex"), expected)

    def test_project_full_access_reaches_all_supported_harnesses(self):
        report = SimpleNamespace(to_json=lambda: '{"ok":true}', summary=SimpleNamespace(errors=0))

        @asynccontextmanager
        async def connect(launch):
            launches.append(launch)
            yield SimpleNamespace(url=launch.url)

        for harness in ("codex", "opencode", "claude_code"):
            with self.subTest(harness=harness), tempfile.TemporaryDirectory() as folder:
                launches = []
                with patch("sys.argv", [
                    "agent-code-checker", "evaluate", "project", folder,
                    "--provider", f"agent-bridge:{harness}", "--model", "test",
                    "--tool-policy", "full_access", "--rules", "duplicate_code", "--json",
                ]), patch("agent_code_checker.cli.connect_harness", connect), \
                     patch("agent_code_checker.cli.agent_bridge_provider_from_name") as provider, \
                     patch("agent_code_checker.cli.EvaluationService") as service, \
                     patch("builtins.print"):
                    service.return_value.evaluate = AsyncMock(return_value=report)
                    main()
                self.assertEqual(launches[0].tool_policy, "full_access")
                self.assertEqual(provider.call_args.kwargs["tool_policy"], "full_access")

    def test_project_antigravity_auto_starts_with_full_access(self):
        report = SimpleNamespace(to_json=lambda: '{"ok":true}', summary=SimpleNamespace(errors=0))
        launches = []

        @asynccontextmanager
        async def connect(launch):
            launches.append(launch)
            yield SimpleNamespace(url=launch.url)

        with tempfile.TemporaryDirectory() as folder, patch("sys.argv", [
            "agent-code-checker", "evaluate", "project", folder,
            "--provider", "agent-bridge:antigravity", "--rules", "duplicate_code", "--json",
        ]), patch("agent_code_checker.cli.connect_harness", connect), \
             patch("agent_code_checker.cli.agent_bridge_provider_from_name") as provider, \
             patch("agent_code_checker.cli.EvaluationService") as service, \
             patch("builtins.print"):
            service.return_value.evaluate = AsyncMock(return_value=report)
            main()

        self.assertEqual(launches[0].tool_policy, "full_access")
        self.assertFalse(launches[0].agy_dangerously_skip_permissions)
        self.assertEqual(provider.call_args.kwargs["tool_policy"], "full_access")

    def test_project_allows_explicit_workspace_write_policy(self):
        report = SimpleNamespace(to_json=lambda: '{"ok":true}', summary=SimpleNamespace(errors=0))
        with tempfile.TemporaryDirectory() as folder, patch("sys.argv", [
            "agent-code-checker", "evaluate", "project", folder,
            "--provider", "agent-bridge:codex", "--agent-url", "http://127.0.0.1:8765",
            "--tool-policy", "workspace_write", "--rules", "duplicate_code", "--json",
        ]), patch("agent_code_checker.cli.agent_bridge_provider_from_name") as provider, \
             patch("agent_code_checker.cli.EvaluationService") as service, \
             patch("builtins.print"):
            service.return_value.evaluate = AsyncMock(return_value=report)
            main()
        self.assertEqual(provider.call_args.kwargs["tool_policy"], "workspace_write")

    def test_project_custom_profile_uses_existing_server_without_autostart(self):
        report = SimpleNamespace(to_json=lambda: '{"ok":true}', summary=SimpleNamespace(errors=0))
        with tempfile.TemporaryDirectory() as folder, patch("sys.argv", [
            "agent-code-checker", "evaluate", "project", folder,
            "--provider", "agent-bridge:my-local-agent", "--agent-url", "http://127.0.0.1:8999",
            "--rules", "duplicate_code", "--json",
        ]), patch("agent_code_checker.cli.connect_harness") as connect, \
             patch("agent_code_checker.cli.agent_bridge_provider_from_name") as provider, \
             patch("agent_code_checker.cli.EvaluationService") as service, \
             patch("builtins.print"):
            service.return_value.evaluate = AsyncMock(return_value=report)
            main()

        connect.assert_not_called()
        provider.assert_called_once_with(
            "agent-bridge:my-local-agent", peer_url="http://127.0.0.1:8999",
            tool_policy="read_only",
        )

    def test_project_auto_starts_read_only_harness_in_target_workspace(self):
        report = SimpleNamespace(to_json=lambda: '{"ok":true}', summary=SimpleNamespace(errors=0))
        launches = []

        @asynccontextmanager
        async def connect(launch):
            launches.append(launch)
            yield SimpleNamespace(url=launch.url)

        with tempfile.TemporaryDirectory() as folder, patch("sys.argv", [
            "agent-code-checker", "evaluate", "project", folder,
            "--provider", "agent-bridge:codex", "--rules", "duplicate_code", "--json",
        ]), patch("agent_code_checker.cli.connect_harness", connect), \
             patch("agent_code_checker.cli.agent_bridge_provider_from_name") as provider, \
             patch("agent_code_checker.cli.EvaluationService") as service, \
             patch("builtins.print"):
            service.return_value.evaluate = AsyncMock(return_value=report)
            main()

        self.assertEqual(launches[0].workspace, Path(folder).resolve())
        self.assertEqual(launches[0].tool_policy, "read_only")
        self.assertEqual(service.return_value.evaluate.call_args.args[0].kind, "project")

    def test_custom_bridge_profile_uses_explicit_url_and_tool_policy(self):
        report = SimpleNamespace(to_json=lambda: '{"ok":true}', summary=SimpleNamespace(errors=0))
        with patch("sys.argv", [
            "agent-code-checker", "evaluate", "snippet", "def f(): return 1",
            "--provider", "agent-bridge:opencode-local",
            "--agent-url", "http://127.0.0.1:8767",
            "--tool-policy", "no_tools", "--model", "qwen3.5:9b", "--json",
        ]), patch("agent_code_checker.cli.agent_bridge_provider_from_name") as provider, \
             patch("agent_code_checker.cli.EvaluationService") as service, \
             patch("builtins.print") as output:
            service.return_value.evaluate = AsyncMock(return_value=report)
            main()
        provider.assert_called_once_with(
            "agent-bridge:opencode-local", peer_url="http://127.0.0.1:8767",
            tool_policy="no_tools",
        )
        self.assertEqual(service.return_value.evaluate.call_args.kwargs["model"], "qwen3.5:9b")
        output.assert_called_once_with('{"ok":true}')
