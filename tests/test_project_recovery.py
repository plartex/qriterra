"""Regressions for failed batches from the real Antigravity review."""

import asyncio
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

from agent_code_checker import EvaluationService, EvaluationTarget, load_code_smells_profile
from agent_code_checker.providers.fake import FakeAgentProvider
from agent_code_checker.providers.base import ProviderExecutionError
from agent_code_checker.prompting import build_evaluation_prompt
from agent_code_checker.response_schema import project_output_schema
from jsonschema import Draft202012Validator


def request_data(prompt):
    return json.loads(prompt.split("REQUEST_DATA_JSON\n", 1)[1].split("\nEND_REQUEST_DATA_JSON", 1)[0])


def passed(rule):
    return {"rule_id": rule["id"], "status": "passed", "confidence": 0.9,
            "findings": [], "coverage": {"status": "complete",
            "inspected_paths": ["app.py"], "limitations": []}}


class SessionFake(FakeAgentProvider):
    opened = 0
    closed = 0

    @asynccontextmanager
    async def open_session(self, **kwargs):
        self.opened += 1
        self.session_id = "one-session"
        try:
            yield self
        finally:
            self.closed += 1


class ProjectRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_session_schema_allows_a_subset_of_the_profile_per_turn(self):
        ids = [r.id for r in load_code_smells_profile().rules]
        schema = project_output_schema(ids)
        value = {"schema_version": "2.0", "batch_id": "batch-0001",
                 "results": [passed({"id": ids[0]})]}
        Draft202012Validator(schema).validate(value)

    async def test_completed_provider_timeout_is_not_reported_as_still_waiting(self):
        def handler(prompt, *_):
            raise TimeoutError("native turn timed out")

        provider = SessionFake(handler)
        report = await EvaluationService(provider).evaluate(
            self.target, load_code_smells_profile(rule_ids=["long_method"]),
            max_project_seconds=.5, debug=True,
        )
        self.assertEqual(sum(row["event"] == "agent_waiting" for row in report.debug_trace), 0)
        self.assertEqual(report.summary.errors, 1)
        self.assertIn("native turn", report.results[0].reason)

    async def test_fatal_session_error_stops_later_model_calls(self):
        def handler(prompt, *_):
            raise ProviderExecutionError("native session was interrupted")

        provider = SessionFake(handler)
        report = await EvaluationService(provider).evaluate(self.target, load_code_smells_profile())
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(report.summary.errors, 80)
        self.assertEqual((provider.opened, provider.closed), (1, 1))

    async def test_read_denial_is_retried_with_corrected_scope_in_same_session(self):
        profile = load_code_smells_profile(rule_ids=["large_class"])
        calls = 0

        def handler(prompt, *_):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ProviderExecutionError("view_file outside_workspace", retryable=True,
                                             usage={"total_tokens": 10})
            data = request_data(prompt)
            self.assertIn("outside_workspace", prompt)
            self.assertEqual(data["target"]["path"], str(self.root.resolve()))
            return json.dumps({"schema_version": "2.0", "batch_id": data["batch_id"],
                               "results": [passed(r) for r in data["rules"]]})

        provider = SessionFake(handler)
        report = await EvaluationService(provider).evaluate(self.target, profile, debug=True)
        self.assertEqual(report.summary.errors, 0)
        self.assertEqual(report.debug_trace[-1]["usage_totals"]["total_tokens"], 10)
        self.assertEqual((provider.opened, provider.closed), (1, 1))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "app.py").write_text("x = 1\n", encoding="utf-8")
        self.target = EvaluationTarget.project(self.root)

    async def test_repairs_only_bad_rules_and_does_not_repeat_accepted_rules(self):
        profile = load_code_smells_profile(rule_ids=["long_method", "duplicate_code"])
        requests = []

        def handler(prompt, *_):
            data = request_data(prompt)
            requests.append([r["id"] for r in data["rules"]])
            rows = [passed(r) for r in data["rules"]]
            if len(requests) == 1:
                rows[-1]["confidence"] = None
            return json.dumps({"schema_version": "2.0", "batch_id": data["batch_id"], "results": rows})

        provider = SessionFake(handler)
        report = await EvaluationService(provider).evaluate(self.target, profile)
        self.assertEqual(report.summary.errors, 0)
        self.assertEqual(requests, [["long_method", "duplicate_code"], ["duplicate_code"]])
        self.assertEqual((provider.opened, provider.closed), (1, 1))

    async def test_all_80_rules_recover_from_malformed_large_batches_in_one_session(self):
        def handler(prompt, *_):
            data = request_data(prompt)
            if len(data["rules"]) > 2:
                return '{"schema_version": "2.0", "results": "wrong"}'
            return json.dumps({"schema_version": "2.0", "batch_id": data["batch_id"],
                               "results": [passed(r) for r in data["rules"]]})

        provider = SessionFake(handler)
        report = await EvaluationService(provider).evaluate(self.target, load_code_smells_profile())
        self.assertEqual(report.summary.errors, 0)
        self.assertEqual(report.summary.passed, 80)
        self.assertEqual(report.summary.assessment_coverage, 100)
        self.assertEqual((provider.opened, provider.closed), (1, 1))
        self.assertLess(len(provider.calls), 170)

    async def test_valid_sibling_survives_timeout_during_repair(self):
        profile = load_code_smells_profile(rule_ids=["long_method", "duplicate_code"])
        calls = 0

        async def handler(prompt, *_):
            nonlocal calls
            calls += 1
            if calls > 1:
                await asyncio.Event().wait()
            data = request_data(prompt)
            rows = [passed(r) for r in data["rules"]]
            rows[-1]["confidence"] = None
            return json.dumps({"schema_version": "2.0", "batch_id": data["batch_id"], "results": rows})

        report = await EvaluationService(SessionFake(handler)).evaluate(
            self.target, profile, max_project_seconds=0.1,
        )
        self.assertEqual(report.results[0].status, "passed")
        self.assertEqual(report.results[1].status, "inconclusive")

    async def test_each_project_prompt_carries_exact_json_schema_and_empty_result_template(self):
        profile = load_code_smells_profile(rule_ids=["large_class"])
        prompt = build_evaluation_prompt("batch-0001", self.target, profile.rules)
        data = request_data(prompt)
        self.assertEqual(data["response_schema"]["properties"]["schema_version"]["const"], "2.0")
        example = data["response_example"]["results"][0]
        self.assertEqual(example["rule_id"], "large_class")
        self.assertEqual(example["status"], "inconclusive")
        self.assertEqual(example["findings"], [])
        self.assertEqual(example["coverage"]["inspected_paths"], [])
