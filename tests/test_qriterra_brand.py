"""Public naming and backwards-compatibility contract for Qriterra."""

import contextlib
import io
import sys
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class QriterraBrandTests(unittest.TestCase):
    def test_new_imports_reexport_existing_api(self):
        import agent_code_checker
        import qriterra
        from agent_code_checker.providers import AgentBridgeProvider as LegacyProvider
        from qriterra.providers import AgentBridgeProvider

        self.assertIs(qriterra.EvaluationService, agent_code_checker.EvaluationService)
        self.assertIs(qriterra.EvaluationTarget, agent_code_checker.EvaluationTarget)
        self.assertIs(AgentBridgeProvider, LegacyProvider)

    def test_distribution_exposes_new_and_legacy_commands(self):
        with (ROOT / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]

        self.assertEqual(project["name"], "qriterra")
        self.assertEqual(project["scripts"]["qriterra"], "qriterra.cli:main")
        self.assertEqual(project["scripts"]["qriterra-mcp"], "qriterra.mcp_server:main")
        self.assertIn("agent-code-checker", project["scripts"])
        self.assertIn("agent-code-checker-mcp", project["scripts"])

    def test_new_cli_uses_product_name(self):
        from qriterra.cli import main

        output = io.StringIO()
        with patch.object(sys, "argv", ["qriterra", "--help"]):
            with contextlib.redirect_stdout(output):
                with self.assertRaises(SystemExit) as exit_result:
                    main()
        self.assertEqual(exit_result.exception.code, 0)
        self.assertIn("usage: qriterra ", output.getvalue())

    def test_mcp_server_uses_product_name(self):
        from qriterra.mcp_server import mcp

        self.assertEqual(mcp.name, "Qriterra")

    def test_readmes_have_same_brand(self):
        for name in ("README.md", "README.ru.md"):
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).read_text(encoding="utf-8").startswith("# Qriterra\n"))


if __name__ == "__main__":
    unittest.main()
