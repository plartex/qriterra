"""The PyCharm example must be runnable without script parameters."""

import unittest
from pathlib import Path

from examples import debug_harnesses as example


class DebugExampleTests(unittest.TestCase):
    def test_no_argument_run_has_target_and_both_parts(self):
        args = example.configured_args()
        self.assertEqual(args[args.index("--part") + 1], "all")
        self.assertEqual(Path(args[args.index("--target") + 1]), example.TARGET)
        self.assertIn("--rules", args)

    def test_extra_arguments_can_override_defaults(self):
        args = example.configured_args(["--target", "other.py", "--agents", "codex"])
        self.assertEqual(args[-4:], ["--target", "other.py", "--agents", "codex"])
