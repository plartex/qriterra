"""The checker must keep analysis-only policy across one-shot and session calls."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

from agent_bridge import BridgeResult
from agent_code_checker.providers import AgentBridgeProvider


class BridgeToolPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_shot_forwards_no_tools_without_legacy_read_only(self):
        provider = AgentBridgeProvider("http://127.0.0.1:8767", "opencode-local", tool_policy="no_tools")
        provider.client.ask = AsyncMock(return_value=BridgeResult(
            provider.peer_url, None, None, "TASK_STATE_COMPLETED", "ok",
        ))

        await provider.run("analyze", workspace=None, model="qwen3.5:9b")

        self.assertTrue(provider.capabilities.read_only)
        self.assertEqual(provider.client.ask.call_args.kwargs["tool_policy"], "no_tools")
        self.assertFalse(provider.client.ask.call_args.kwargs["read_only"])

    async def test_session_forwards_no_tools_and_keeps_model(self):
        provider = AgentBridgeProvider("http://127.0.0.1:8768", "claude-local", tool_policy="no_tools")

        class Session:
            id = "11111111-1111-4111-8111-111111111111"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

            async def ask(self, _prompt):
                return BridgeResult(provider.peer_url, None, self.id, "TASK_STATE_COMPLETED", "ok")

        provider.client.session = unittest.mock.Mock(return_value=Session())
        async with provider.open_session(model="qwen3.5:9b") as session_provider:
            reply = await session_provider.run("analyze", workspace=None, model="qwen3.5:9b")

        self.assertEqual(reply.text, "ok")
        self.assertEqual(provider.client.session.call_args.kwargs["tool_policy"], "no_tools")
        self.assertFalse(provider.client.session.call_args.kwargs["read_only"])

    def test_invalid_policy_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "tool_policy"):
            AgentBridgeProvider("http://127.0.0.1:8767", "opencode-local", tool_policy="invalid")

    async def test_project_session_checks_workspace_and_read_only_tools_before_start(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            provider = AgentBridgeProvider("http://127.0.0.1:8767", "opencode-local", tool_policy="read_only")
            provider.client.identity = AsyncMock(return_value={"workspace": str(root)})

            class Session:
                id = "11111111-1111-4111-8111-111111111111"

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    pass

            provider.client.session = unittest.mock.Mock(return_value=Session())
            async with provider.open_session(workspace=root) as session:
                self.assertEqual(session.session_id, Session.id)

            self.assertEqual(provider.client.session.call_args.kwargs["tool_policy"], "read_only")

    async def test_project_session_rejects_wrong_workspace_without_model_call(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            provider = AgentBridgeProvider("http://127.0.0.1:8765", "codex")
            provider.client.identity = AsyncMock(return_value={"workspace": str(root.parent)})
            provider.client.session = unittest.mock.Mock()

            with self.assertRaisesRegex(ValueError, "workspace"):
                async with provider.open_session(workspace=root):
                    pass
            provider.client.session.assert_not_called()

    async def test_project_session_accepts_antigravity_full_access_without_read_only_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            provider = AgentBridgeProvider(
                "http://127.0.0.1:8766", "antigravity", tool_policy="full_access",
            )
            provider.client.identity = AsyncMock(return_value={
                "workspace": str(root), "backend": "agy_cli", "agy_permission_mode": "all",
            })

            class Session:
                id = "11111111-1111-4111-8111-111111111111"

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    pass

            provider.client.session = unittest.mock.Mock(return_value=Session())
            async with provider.open_session(workspace=root):
                pass
            self.assertEqual(provider.client.session.call_args.kwargs["tool_policy"], "full_access")

    async def test_project_full_access_rejects_old_antigravity_server_before_model_call(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            provider = AgentBridgeProvider("http://127.0.0.1:8766", "antigravity", tool_policy="full_access")
            provider.client.identity = AsyncMock(return_value={
                "workspace": str(root), "backend": "agy_cli", "agy_permission_mode": "settings",
            })
            provider.client.session = unittest.mock.Mock()
            with self.assertRaisesRegex(ValueError, "does not have full_access"):
                async with provider.open_session(workspace=root):
                    pass
            provider.client.session.assert_not_called()
