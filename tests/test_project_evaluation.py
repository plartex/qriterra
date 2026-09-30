"""Contract tests for agent-driven project evaluation."""

import json
import asyncio
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

from agent_code_checker import EvaluationService, EvaluationTarget, load_code_smells_profile
from agent_code_checker.prompting import build_evaluation_prompt, build_session_batch_prompt
from agent_code_checker.providers.fake import FakeAgentProvider


def request_from_prompt(prompt: str) -> dict:
    return json.loads(prompt.split("REQUEST_DATA_JSON\n", 1)[1].split("\nEND_REQUEST_DATA_JSON", 1)[0])


class SessionFake(FakeAgentProvider):
    def __init__(self, handler):
        super().__init__(handler)
        self.opened = 0
        self.closed = 0

    @asynccontextmanager
    async def open_session(self, *, workspace=None, model=None, reasoning_effort=None):
        self.opened += 1
        self.session_id = "test-project-session"
        try:
            yield self
        finally:
            self.closed += 1


class ProjectPromptTests(unittest.TestCase):
    def test_project_prompt_allows_read_search_and_forbids_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            target = EvaluationTarget.project(folder)
            rules = load_code_smells_profile(rule_ids=["duplicate_code"]).rules
            prompt = build_evaluation_prompt("batch-0001", target, rules)
            next_prompt = build_session_batch_prompt("batch-0002", rules, target=target)

        self.assertIn("read and search", prompt)
        self.assertIn("Do not modify", prompt)
        self.assertNotIn("closed-book, tool-free", prompt)
        self.assertEqual(request_from_prompt(prompt)["target"]["kind"], "project")
        self.assertIn("same project", next_prompt)
        self.assertNotIn("Do not invoke tools", next_prompt)


class ProjectEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_budget_stops_later_batches_and_closes_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "app.py").write_text("x = 1\n", encoding="utf-8")
            profile = load_code_smells_profile(rule_ids=["long_method", "large_class"])

            async def handler(_prompt, *_args):
                await asyncio.Event().wait()
                return "not reached"

            provider = SessionFake(handler)
            report = await EvaluationService(provider).evaluate(
                EvaluationTarget.project(root), profile, max_project_seconds=0.01,
            )

        self.assertEqual((provider.opened, provider.closed), (1, 1))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(report.summary.inconclusive, 2)
        self.assertIsNone(report.summary.quality_score)

    async def test_rule_batches_share_one_project_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            profile = load_code_smells_profile(rule_ids=["long_method", "large_class"])

            def handler(prompt, workspace, _model):
                request = request_from_prompt(prompt)
                return json.dumps({
                    "schema_version": "2.0", "batch_id": request["batch_id"],
                    "results": [{
                        "rule_id": rule["id"], "status": "passed", "confidence": 0.8,
                        "coverage": {"status": "complete", "inspected_paths": ["app.py"], "limitations": []},
                        "findings": [],
                    } for rule in request["rules"]],
                })

            provider = SessionFake(handler)
            report = await EvaluationService(provider).evaluate(EvaluationTarget.project(root), profile)

        self.assertEqual((provider.opened, provider.closed), (1, 1))
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("Use read and search tools", provider.calls[0][0])
        self.assertIn("same project", provider.calls[1][0])
        self.assertEqual(report.summary.passed, 2)

    async def test_partial_coverage_cannot_be_reported_as_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.py").write_text("x = 1\n", encoding="utf-8")
            profile = load_code_smells_profile(rule_ids=["duplicate_code"])
            batch_id = None

            def handler(prompt, *_args):
                nonlocal batch_id
                if "REQUEST_DATA_JSON\n" in prompt:
                    batch_id = request_from_prompt(prompt)["batch_id"]
                return json.dumps({
                    "schema_version": "2.0", "batch_id": batch_id,
                    "results": [{
                        "rule_id": "duplicate_code", "status": "passed", "confidence": 0.8,
                        "coverage": {"status": "partial", "inspected_paths": ["one.py"],
                                     "limitations": ["Other modules not inspected"]},
                        "findings": [],
                    }],
                })

            report = await EvaluationService(SessionFake(handler)).evaluate(EvaluationTarget.project(root), profile)

        self.assertEqual(report.summary.errors, 1)
        self.assertEqual(report.summary.assessment_coverage, 0)
        self.assertIsNone(report.summary.quality_score)
        self.assertIn("cannot pass", report.results[0].reason)

    async def test_one_session_even_for_one_batch_and_grouped_duplicate_finding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.py").write_text("def a():\n    return calculate()\n", encoding="utf-8")
            (root / "two.py").write_text("def b():\n    return calculate()\n", encoding="utf-8")
            profile = load_code_smells_profile(rule_ids=["duplicate_code"])

            def handler(prompt, workspace, _model):
                request = request_from_prompt(prompt)
                self.assertEqual(workspace, root.resolve())
                return json.dumps({
                    "schema_version": "2.0", "batch_id": request["batch_id"],
                    "results": [{
                        "rule_id": "duplicate_code", "status": "failed", "confidence": 0.9,
                        "coverage": {"status": "complete", "inspected_paths": ["one.py", "two.py"], "limitations": []},
                        "findings": [{
                            "summary": "The same calculation is repeated",
                            "evidence": [
                                {"path": "one.py", "start_line": 2, "end_line": 2,
                                 "excerpt": "    return calculate()", "reason": "first occurrence"},
                                {"path": "two.py", "start_line": 2, "end_line": 2,
                                 "excerpt": "    return calculate()", "reason": "second occurrence"},
                            ],
                        }],
                    }],
                })

            provider = SessionFake(handler)
            report = await EvaluationService(provider).evaluate(EvaluationTarget.project(root), profile)

        self.assertEqual((provider.opened, provider.closed), (1, 1))
        self.assertEqual(report.summary.failed, 1)
        self.assertEqual(report.summary.findings, 1)
        self.assertEqual(len(report.results[0].findings[0].evidence), 2)
        self.assertEqual(report.to_dict()["schema_version"], "2.0")

    async def test_partial_coverage_cannot_pass_or_produce_quality_score(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.py").write_text("x = 1\n", encoding="utf-8")
            profile = load_code_smells_profile(rule_ids=["duplicate_code"])

            def handler(prompt, *_args):
                request = request_from_prompt(prompt)
                return json.dumps({
                    "schema_version": "2.0", "batch_id": request["batch_id"],
                    "results": [{
                        "rule_id": "duplicate_code", "status": "inconclusive", "confidence": 0.3,
                        "reason": "Only one module was inspected",
                        "coverage": {"status": "partial", "inspected_paths": ["one.py"],
                                     "limitations": ["Other modules not inspected"]},
                        "findings": [],
                    }],
                })

            report = await EvaluationService(SessionFake(handler)).evaluate(
                EvaluationTarget.project(root), profile,
            )

        self.assertEqual(report.summary.inconclusive, 1)
        self.assertIsNone(report.summary.quality_score)

    async def test_project_evidence_excerpt_must_match_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.py").write_text("x = 1\n", encoding="utf-8")
            profile = load_code_smells_profile(rule_ids=["long_method"])
            batch_id = None

            def handler(prompt, *_args):
                nonlocal batch_id
                if "REQUEST_DATA_JSON\n" in prompt:
                    batch_id = request_from_prompt(prompt)["batch_id"]
                return json.dumps({
                    "schema_version": "2.0", "batch_id": batch_id,
                    "results": [{
                        "rule_id": "long_method", "status": "failed", "confidence": 0.8,
                        "coverage": {"status": "complete", "inspected_paths": ["one.py"], "limitations": []},
                        "findings": [{"summary": "A long method", "evidence": [{
                            "path": "one.py", "start_line": 1, "end_line": 1,
                            "excerpt": "not present", "reason": "hallucinated",
                        }]}],
                    }],
                })

            report = await EvaluationService(SessionFake(handler)).evaluate(
                EvaluationTarget.project(root), profile,
            )

        self.assertEqual(report.summary.errors, 1)
        self.assertIn("excerpt", report.results[0].reason)
