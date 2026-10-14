"""Offline privacy regressions. All markers below are synthetic."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_code_checker import EvaluationService, EvaluationTarget, load_code_smells_profile
from agent_code_checker.project_snapshot import capture_project, ProjectSnapshotError
from agent_code_checker.prompting import build_evaluation_prompt
from agent_code_checker.providers.fake import FakeAgentProvider
from agent_code_checker.providers.base import ProviderResponse, ProviderExecutionError
from tests.test_project_recovery import SessionFake


class InventoryPrivacyTests(unittest.TestCase):
    def test_filesystem_obeys_nested_ignores_and_negations(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sub").mkdir()
            for name in ("app.py", "private.json", "credentials.json", "sub/drop.py", "sub/keep.py"):
                (root / name).write_text("SYNTHETIC_SOURCE", encoding="utf-8")
            (root / ".gitignore").write_text("private.json\nsub/*.py\n", encoding="utf-8")
            (root / "private.json").write_text('{"api_key":"SYNTHETIC_PRIVATE_VALUE"}', encoding="utf-8")
            (root / "sub/.gitignore").write_text("!keep.py\n", encoding="utf-8")
            with patch("agent_code_checker.project_snapshot.subprocess.run", side_effect=OSError):
                snapshot = capture_project(root)
            self.assertEqual([file.path for file in snapshot.files], ["app.py", "sub/keep.py"])
            prompt = build_evaluation_prompt("b", EvaluationTarget.project(root),
                load_code_smells_profile(rule_ids=["long_method"]).rules, snapshot=snapshot)
            self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", prompt)
            self.assertEqual(snapshot.changes(root), [])

    def test_repository_never_falls_back_after_git_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".git").mkdir()
            with patch("agent_code_checker.project_snapshot.subprocess.run", side_effect=OSError):
                with self.assertRaises(ProjectSnapshotError):
                    capture_project(root)

    def test_sensitive_files_excluded_even_if_tracked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            names = ["credentials.json", "secrets.yaml", ".env.production", "codex.session.smoke.json", "app.py"]
            for name in names:
                (root / name).write_text("SYNTHETIC_SOURCE", encoding="utf-8")
            with patch("agent_code_checker.project_snapshot.subprocess.run",
                       return_value=SimpleNamespace(stdout=("\0".join(names) + "\0").encode())):
                self.assertEqual([file.path for file in capture_project(root).files], ["app.py"])

    def test_unreadable_ignore_stops_before_sending(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".gitignore").write_bytes(b"\xff")
            with self.assertRaises(ProjectSnapshotError):
                capture_project(root, discovery_mode="filesystem")


class ReportPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_exception_text_never_enters_report_or_callback(self):
        marker = "synthetic-arbitrary-private-output"
        def fail(*_):
            raise RuntimeError(marker)
        events = []
        for debug in (False, True):
            report = await EvaluationService(FakeAgentProvider(fail)).evaluate(
                EvaluationTarget.snippet("x = 1"), load_code_smells_profile(rule_ids=["long_method"]),
                debug=debug, on_debug_event=events.append,
            )
            self.assertEqual(report.summary.errors, 1)
            self.assertNotIn(marker, report.to_json())
        self.assertNotIn(marker, json.dumps(events))

    async def test_retried_provider_error_does_not_leak_in_report(self):
        marker = "synthetic-retry-private-output"
        def fail(*_):
            raise ProviderExecutionError(marker, retryable=True, details={"secret": marker})
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "app.py").write_text("x = 1")
            report = await EvaluationService(SessionFake(fail)).evaluate(
                EvaluationTarget.project(folder), load_code_smells_profile(rule_ids=["long_method"]), debug=True,
            )
            self.assertNotIn(marker, report.to_json())
            self.assertTrue(report.summary.errors)

    async def test_metadata_minimized_and_export_masks_paths(self):
        marker = "synthetic-provider-metadata"
        def answer(*_):
            return ProviderResponse(json.dumps({"schema_version": "1.0", "batch_id": "batch-0001",
                "results": [{"rule_id": "long_method", "status": "passed", "confidence": 1, "evidence": []}]}),
                usage={"total_tokens": 7}, details={"conversation_id": marker, "raw_output": marker})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "example.py"
            path.write_text("x = 1")
            report = await EvaluationService(FakeAgentProvider(answer)).evaluate(
                EvaluationTarget.file(path), load_code_smells_profile(rule_ids=["long_method"]), debug=True,
            )
            self.assertNotIn(marker, report.to_json())
            self.assertEqual(report.to_dict()["target"]["path"], str(path))
            exported = report.to_dict(shareable=True)
            self.assertNotIn("debug_trace", exported)
            self.assertNotIn("run_id", exported)
            self.assertNotIn(folder, json.dumps(exported))
            self.assertEqual(exported["target"]["path"], "<target>\\example.py" if "\\" in str(path) else "<target>/example.py")
