import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from agent_code_checker import EvaluationTarget, load_code_smells_profile, EvaluationService
from agent_code_checker.project_snapshot import capture_project
from agent_code_checker.prompting import build_evaluation_prompt
from tests.test_project_recovery import SessionFake, request_data, passed


class ProjectSnapshotTests(unittest.TestCase):
    def test_fallback_inventory_does_not_change_when_git_becomes_available(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "app.py").write_text("x = 1\n")
            (root / "bin").mkdir()
            (root / "bin/manifest.json").write_text('{"version":"1"}')
            with patch("agent_code_checker.project_snapshot.subprocess.run", side_effect=[
                OSError("git temporarily unavailable"), SimpleNamespace(stdout=b"app.py\0"),
            ]) as inventory:
                snapshot = capture_project(root)
                self.assertEqual(snapshot.changes(root), [])
                self.assertEqual(inventory.call_count, 1)

    def test_snapshot_includes_source_and_tests_but_excludes_generated_environments(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for relative in ("src/app.py", "tests/test_app.py", ".venv/ignored.py", ".runtime/old_report.py"):
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("x = 1\n", encoding="utf-8", newline="\n")
            snapshot = capture_project(root)
            self.assertEqual([file.path for file in snapshot.files], ["src/app.py", "tests/test_app.py"])
            self.assertTrue(all(file.content == "x = 1\n" for file in snapshot.files))
            rules = load_code_smells_profile(rule_ids=["large_class"]).rules
            prompt = build_evaluation_prompt("b", EvaluationTarget.project(root), rules, snapshot=snapshot)
            self.assertIn("All manifest files are embedded", prompt)
            self.assertIn("Do not call file tools", prompt)
            data = request_data(prompt)
            source = data["project_snapshot"]["files"][0]
            self.assertEqual(source["path"], "src/app.py")
            self.assertEqual(source["source_lines"], ["x = 1"])
            self.assertEqual(len(source["sha256"]), 64)

    def test_inline_limit_reports_missing_content_without_truncating_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
            snapshot = capture_project(root, inline_bytes=1)
            self.assertIsNone(snapshot.files[0].content)
            self.assertEqual(snapshot.files[0].size, 6)
            self.assertTrue(snapshot.limitations)


class ProjectMutationTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_git_inventory_is_reported_as_unverifiable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "app.py").write_text("x = 1\n")
            def handler(prompt, *_):
                data = request_data(prompt)
                return json.dumps({"schema_version":"2.0", "batch_id":data["batch_id"],
                                   "results":[passed(rule) for rule in data["rules"]]})
            with patch("agent_code_checker.project_snapshot.subprocess.run", side_effect=[
                SimpleNamespace(stdout=b"app.py\0"), OSError("git unavailable"),
            ]):
                report = await EvaluationService(SessionFake(handler)).evaluate(
                    EvaluationTarget.project(root), load_code_smells_profile(rule_ids=["long_method"]),
                )
            self.assertIsNone(report.source_snapshot["unchanged"])
            self.assertEqual(report.results[0].status, "inconclusive")
            self.assertIn("could not be verified", report.results[0].reason)

    async def test_missing_declared_files_prevents_a_complete_project_score(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("app.py", "uninspected.py"):
                (root / name).write_text("x = 1\n", encoding="utf-8")
            def handler(prompt, *_):
                data = request_data(prompt)
                return json.dumps({"schema_version": "2.0", "batch_id": data["batch_id"],
                                   "results": [passed(rule) for rule in data["rules"]]})
            report = await EvaluationService(SessionFake(handler)).evaluate(
                EvaluationTarget.project(root), load_code_smells_profile(rule_ids=["long_method"]),
            )
            self.assertIsNone(report.summary.quality_score)
            self.assertEqual(report.source_snapshot["undeclared_paths"], ["uninspected.py"])
            self.assertEqual(report.source_snapshot["declared_file_coverage"], .5)

    async def test_source_change_prevents_complete_success_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "app.py"
            source.write_text("x = 1\n", encoding="utf-8")

            def handler(prompt, *_):
                data = request_data(prompt)
                source.write_text("x = 2\n", encoding="utf-8")
                return json.dumps({"schema_version": "2.0", "batch_id": data["batch_id"],
                                   "results": [passed(r) for r in data["rules"]]})

            report = await EvaluationService(SessionFake(handler)).evaluate(
                EvaluationTarget.project(root), load_code_smells_profile(rule_ids=["long_method"]),
            )
            self.assertEqual(report.summary.passed, 0)
            self.assertEqual(report.results[0].status, "inconclusive")
            self.assertIsNone(report.summary.quality_score)
            self.assertIn("changed", report.results[0].reason)
            self.assertFalse(report.to_dict()["source_snapshot"]["unchanged"])
