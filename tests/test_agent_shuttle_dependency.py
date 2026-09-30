"""Qriterra must install the separately packaged Agent Shuttle dependency."""

import tomllib
import unittest
from pathlib import Path


class AgentShuttleDependencyTests(unittest.TestCase):
    def test_distribution_depends_on_agent_shuttle(self):
        path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        dependencies = tomllib.loads(path.read_text(encoding="utf-8"))["project"]["dependencies"]
        self.assertTrue(any(item.startswith("agent-shuttle>=") for item in dependencies))
        self.assertFalse(any(item.startswith("codex-antigravity-a2a-bridge") for item in dependencies))


if __name__ == "__main__":
    unittest.main()
