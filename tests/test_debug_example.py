"""The PyCharm example must be runnable without script parameters."""

import unittest
from pathlib import Path

from examples import debug_harnesses as example


class DebugExampleTests(unittest.TestCase):
    def test_no_argument_run_has_target_and_both_parts(self):
        args = example.parse_args([])
        self.assertEqual(args.part, "all")
        self.assertEqual(args.target, example.TARGET)
        self.assertIsNone(args.rules)  # Preserve the user's full-catalog setting.

    def test_extra_arguments_can_override_defaults(self):
        args = example.parse_args(["--target", "other.py", "--agents", "codex",
                                   "--rules", "long_method"])
        self.assertEqual(args.target, Path("other.py"))
        self.assertEqual(args.agents, "codex")
        self.assertEqual(args.rules, "long_method")
