import os
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class CheckerMcpTest(unittest.IsolatedAsyncioTestCase):
    async def test_project_tool_starts_matching_read_only_harness(self):
        from agent_code_checker.mcp_server import evaluate

        launches = []

        @asynccontextmanager
        async def connect(launch):
            launches.append(launch)
            yield SimpleNamespace(url=launch.url)

        with tempfile.TemporaryDirectory() as folder, \
             patch("agent_code_checker.mcp_server.connect_harness", connect), \
             patch("agent_code_checker.mcp_server.agent_bridge_provider_from_name"), \
             patch("agent_code_checker.mcp_server.EvaluationService") as service:
            service.return_value.evaluate = AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {"ok": True}))
            result = await evaluate(
                "project", folder, provider="agent-bridge:codex", rules=["duplicate_code"],
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(launches[0].workspace, Path(folder).resolve())
        self.assertEqual(launches[0].tool_policy, "read_only")

    async def test_only_checker_tool_is_listed(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "agent_code_checker.mcp_server"],
            env={
                **os.environ,
                "BRIDGE_CODEX_URL": "http://127.0.0.1:8765",
                "BRIDGE_ANTIGRAVITY_URL": "http://127.0.0.1:8766",
            },
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
        self.assertEqual({tool.name for tool in tools}, {"evaluate"})
        props = tools[0].inputSchema["properties"]
        self.assertTrue({"target_type", "target", "batch_size", "model", "reasoning_effort",
                         "agent_url", "tool_policy", "debug"} <= props.keys())


if __name__ == "__main__":
    unittest.main()
