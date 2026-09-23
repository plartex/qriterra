import os
import sys
import unittest

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class CheckerMcpTest(unittest.IsolatedAsyncioTestCase):
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
