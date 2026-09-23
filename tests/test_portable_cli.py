"""CLI addresses a profile without depending on neighboring repositories."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_code_checker.cli import main


class PortableCliTests(unittest.TestCase):
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
