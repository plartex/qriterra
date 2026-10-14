"""Qriterra must install the separately packaged Agent Shuttle dependency."""

import tomllib
import unittest
from pathlib import Path


class AgentShuttleDependencyTests(unittest.TestCase):
    def test_distribution_depends_on_agent_shuttle(self):
        path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        dependencies = tomllib.loads(path.read_text(encoding="utf-8"))["project"]["dependencies"]
        self.assertIn("agent-shuttle>=0.8.0,<1", dependencies)


if __name__ == "__main__":
    unittest.main()
