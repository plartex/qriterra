import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

from agent_bridge import BridgeResult

from agent_code_checker import (
    EvaluationService,
    EvaluationTarget,
    format_text_report,
    load_code_smells_profile,
)
from agent_code_checker.batching import plan_batches
from agent_code_checker.prompting import MAX_INLINE_FILE_BYTES, build_evaluation_prompt
from agent_code_checker.providers import FakeAgentProvider
from agent_code_checker.providers.agent_bridge import AgentBridgeProvider
from agent_code_checker.providers.base import ProviderResponse
from agent_code_checker.models import CheckResult
from agent_code_checker.scoring import summarize


def request_from_prompt(prompt: str) -> dict:
    payload = prompt.split("REQUEST_DATA_JSON\n", 1)[1].split("\nEND_REQUEST_DATA_JSON", 1)[0]
    return json.loads(payload)


def response_for(prompt: str, result_factory) -> str:
    request = request_from_prompt(prompt)
    return json.dumps(
        {
            "schema_version": "1.0",
            "batch_id": request["batch_id"],
            "results": [result_factory(rule) for rule in request["rules"]],
        },
        ensure_ascii=False,
    )


class CatalogAndBatchingTest(unittest.TestCase):
    def test_partial_transport_failure_has_no_quality_score(self):
        summary = summarize((
            CheckResult(rule_id="ok", status="passed", severity="medium"),
            CheckResult(rule_id="error", status="error", severity="high", reason="denied"),
        ))
        self.assertIsNone(summary.quality_score)
        self.assertEqual(summary.assessment_coverage, 50.0)

    def test_bundled_catalog_contains_all_rules(self):
        profile = load_code_smells_profile()
        self.assertEqual(len(profile.rules), 80)
        self.assertEqual(len({rule.id for rule in profile.rules}), 80)
        self.assertEqual(profile.rules[0].id, "long_method")
        self.assertEqual(profile.rules[-1].id, "duplicated_derived_state")
        self.assertEqual(profile.prompt_language, "en")
        self.assertTrue(all(rule.definition for rule in profile.rules))

    def test_english_prompt_preserves_russian_detection_details(self):
        english = load_code_smells_profile(rule_ids=["long_method"])
        russian = load_code_smells_profile(
            rule_ids=["long_method"], prompt_language="ru",
        )
        english_rule = english.rules[0].prompt_dict()
        russian_rule = russian.rules[0].prompt_dict()
        self.assertEqual(english_rule["title"], "Long Method")
        self.assertIn("definition", english_rule)
        self.assertIn("symptoms", english_rule)
        self.assertIn("detection_hints", english_rule)
        self.assertIn("definition", russian_rule)
        self.assertEqual(english.rules[0].title, russian.rules[0].title)
        self.assertIn("30", english_rule["detection_hints"]["lines_of_code_loc"])
        self.assertNotEqual(english_rule["definition"], russian_rule["definition"])

    def test_explicit_compact_criterion_remains_supported(self):
        russian = load_code_smells_profile(
            rule_ids=["long_method"], prompt_language="ru",
        ).rules[0]
        compact = replace(russian, criterion_en="More than 30 lines")
        self.assertEqual(compact.prompt_dict()["criterion"], "More than 30 lines")
        self.assertNotIn("definition", compact.prompt_dict())

    def test_english_translation_retains_source_metrics_and_examples(self):
        from agent_code_checker.catalog import (
            DEFAULT_CODE_SMELLS_CATALOG,
            DEFAULT_ENGLISH_PROFILE,
            DEFAULT_ENGLISH_SOURCE_HASH,
        )

        russian = json.loads(DEFAULT_CODE_SMELLS_CATALOG.read_text(encoding="utf-8"))
        english = json.loads(DEFAULT_ENGLISH_PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(russian.keys(), english.keys())
        self.assertEqual(len(russian["categories"]), len(english["categories"]))
        self.assertEqual(len(russian["smells"]), len(english["smells"]))
        self.assertEqual(
            [rule["id"] for rule in russian["smells"]],
            [rule["id"] for rule in english["smells"]],
        )
        self.assertEqual(len(DEFAULT_ENGLISH_SOURCE_HASH.read_text(encoding="ascii").strip()), 64)
        for original, translated in zip(russian["smells"], english["smells"], strict=True):
            self.assertEqual(original.keys(), translated.keys())
            self.assertEqual(translated["name"], original["name_en"])
            self.assertEqual(original["bad_example"]["code"], translated["bad_example"]["code"])
            self.assertEqual(original["good_example"]["code"], translated["good_example"]["code"])
        duplicate = load_code_smells_profile(rule_ids=["duplicate_code"]).rules[0]
        self.assertIn("85%", duplicate.detection_hints["token_similarity"])
        self.assertIn("6", duplicate.detection_hints["token_similarity"])

    def test_english_mirror_rejects_missing_fields_code_changes_and_russian(self):
        from agent_code_checker.catalog import CatalogError, _validate_translation_shape

        source = {"id": "rule", "definition": "Русское правило", "example": {"code": "print('ok')"}}
        translated = {"id": "rule", "definition": "English rule", "example": {"code": "print('ok')"}}
        _validate_translation_shape(source, translated)
        with self.assertRaises(CatalogError):
            _validate_translation_shape(source, {**translated, "extra": "lost parity"})
        with self.assertRaises(CatalogError):
            _validate_translation_shape(source, {**translated, "definition": "Русское правило"})
        with self.assertRaises(CatalogError):
            _validate_translation_shape(
                source, {**translated, "example": {"code": "print('changed')"}},
            )

    def test_custom_catalog_uses_russian_unless_english_is_requested(self):
        from agent_code_checker.catalog import DEFAULT_CODE_SMELLS_CATALOG

        with tempfile.TemporaryDirectory() as folder:
            copied = Path(folder) / "custom.json"
            copied.write_bytes(DEFAULT_CODE_SMELLS_CATALOG.read_bytes())
            profile = load_code_smells_profile(copied, rule_ids=["long_method"])
            self.assertEqual(profile.prompt_language, "ru")
            with self.assertRaisesRegex(ValueError, "only available for the bundled"):
                load_code_smells_profile(copied, prompt_language="en")

    def test_batches_are_bounded_and_complete(self):
        rules = load_code_smells_profile().rules
        batches = plan_batches(rules, batch_size=7)
        self.assertTrue(batches)
        self.assertTrue(all(1 <= len(batch) <= 7 for batch in batches))
        flattened = [rule.id for batch in batches for rule in batch]
        self.assertCountEqual(flattened, [rule.id for rule in rules])

    def test_unknown_rule_is_rejected_before_agent_run(self):
        with self.assertRaisesRegex(ValueError, "Unknown rule ids"):
            load_code_smells_profile(rule_ids=["does_not_exist"])

    def test_file_target_is_inlined_for_fixed_workspace_agents(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "service.py"
            path.write_text("def answer():\n    return 42\n", encoding="utf-8")
            target = EvaluationTarget.file(path)
            rule = load_code_smells_profile(rule_ids=["long_method"]).rules
            payload = request_from_prompt(build_evaluation_prompt("batch-0001", target, rule))

        self.assertEqual(payload["target"]["kind"], "file")
        self.assertEqual(payload["target"]["path"], str(path.resolve()))
        self.assertEqual(payload["target"]["language"], "py")
        self.assertEqual(payload["target"]["content"], "def answer():\n    return 42\n")

    def test_evaluation_prompt_forbids_tools_and_external_file_context(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "service.py"
            path.write_text("value = 42\n", encoding="utf-8")
            target = EvaluationTarget.file(path)
            rule = load_code_smells_profile(rule_ids=["cyclic_dependency"]).rules
            prompt = build_evaluation_prompt("batch-0001", target, rule)

        self.assertIn("closed-book, tool-free evaluation", prompt)
        self.assertIn("Never invoke tools", prompt)
        self.assertIn("analyze only target.content", prompt)

    def test_oversized_file_fails_before_agent_run(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.py"
            path.write_bytes(b"x" * (MAX_INLINE_FILE_BYTES + 1))
            target = EvaluationTarget.file(path)
            rule = load_code_smells_profile(rule_ids=["long_method"]).rules
            with self.assertRaisesRegex(ValueError, "inline limit"):
                build_evaluation_prompt("batch-0001", target, rule)


class EvaluationServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_session_reuses_target_and_reports_per_turn_usage(self):
        profile = load_code_smells_profile(rule_ids=["long_method", "large_class"])
        provider = AgentBridgeProvider("http://127.0.0.1:8766", "antigravity")
        prompts = []
        settings = []

        class RecordingSession:
            id = "11111111-1111-4111-8111-111111111111"
            closed = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                self.closed = True

            async def ask(self, prompt):
                prompts.append(prompt)
                return BridgeResult(
                    "http://127.0.0.1:8766", None, self.id,
                    "TASK_STATE_COMPLETED",
                    response_for(prompt, lambda rule: {
                        "rule_id": rule["id"], "status": "passed",
                        "confidence": 1.0, "evidence": [],
                    }),
                    {"input_tokens": 100 + len(prompts), "cache_read_tokens": 10},
                )

        session = RecordingSession()

        def open_session(url, *, model, reasoning_effort, read_only):
            settings.append((url, model, reasoning_effort, read_only))
            return session

        provider.client.session = open_session
        report = await EvaluationService(provider).evaluate(
            EvaluationTarget.snippet("unique_source_marker = 42"), profile,
            model="chosen-model", reasoning_effort="medium", debug=True,
        )

        self.assertEqual(report.summary.passed, 2)
        self.assertEqual(len(prompts), 2)
        self.assertIn("unique_source_marker", prompts[0])
        self.assertNotIn("unique_source_marker", prompts[1])
        self.assertEqual(request_from_prompt(prompts[1])["batch_id"], "batch-0002")
        self.assertEqual(settings, [("http://127.0.0.1:8766", "chosen-model", "medium", False)])
        self.assertTrue(session.closed)
        events = [event["event"] for event in report.debug_trace]
        self.assertIn("session_opened", events)
        self.assertIn("session_closed", events)
        self.assertEqual(report.debug_trace[-1]["usage_totals"]["input_tokens"], 203)
        self.assertEqual(report.debug_trace[-1]["usage_totals"]["cache_read_tokens"], 20)

    async def test_bridge_no_session_sends_full_target_for_each_batch(self):
        profile = load_code_smells_profile(rule_ids=["long_method", "large_class"])
        provider = AgentBridgeProvider("http://127.0.0.1:8766", "antigravity")
        prompts = []

        async def ask(url, prompt, **kwargs):
            prompts.append(prompt)
            return BridgeResult(
                url, None, None, "TASK_STATE_COMPLETED",
                response_for(prompt, lambda rule: {
                    "rule_id": rule["id"], "status": "passed",
                    "confidence": 1.0, "evidence": [],
                }),
            )

        provider.client.ask = AsyncMock(side_effect=ask)
        report = await EvaluationService(provider).evaluate(
            EvaluationTarget.snippet("unique_source_marker = 42"), profile,
            use_session=False,
        )
        self.assertEqual(report.summary.passed, 2)
        self.assertEqual(len(prompts), 2)
        self.assertTrue(all("unique_source_marker" in prompt for prompt in prompts))

    async def test_session_repair_does_not_resend_target(self):
        profile = load_code_smells_profile(rule_ids=["long_method", "large_class"])
        provider = AgentBridgeProvider("http://127.0.0.1:8766", "antigravity")
        prompts = []

        class RepairSession:
            id = "33333333-3333-4333-8333-333333333333"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                pass

            async def ask(self, prompt):
                prompts.append(prompt)
                if len(prompts) == 1:
                    answer = "not json"
                else:
                    batch_prompt = prompts[0] if len(prompts) == 2 else prompt
                    answer = response_for(batch_prompt, lambda rule: {
                        "rule_id": rule["id"], "status": "passed",
                        "confidence": 1.0, "evidence": [],
                    })
                return BridgeResult(
                    "http://127.0.0.1:8766", None, self.id,
                    "TASK_STATE_COMPLETED", answer,
                )

        provider.client.session = lambda *args, **kwargs: RepairSession()
        report = await EvaluationService(provider).evaluate(
            EvaluationTarget.snippet("unique_source_marker = 42"), profile,
        )
        self.assertEqual(report.summary.passed, 2)
        self.assertEqual(len(prompts), 3)
        self.assertIn("unique_source_marker", prompts[0])
        self.assertNotIn("unique_source_marker", prompts[1])
        self.assertNotIn("unique_source_marker", prompts[2])
        self.assertIn("REPAIR_DATA_JSON", prompts[1])

    async def test_failed_first_session_turn_resends_target_on_next_batch(self):
        profile = load_code_smells_profile(rule_ids=["long_method", "large_class"])
        provider = AgentBridgeProvider("http://127.0.0.1:8766", "antigravity")
        prompts = []

        class FlakySession:
            id = "22222222-2222-4222-8222-222222222222"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                pass

            async def ask(self, prompt):
                prompts.append(prompt)
                if len(prompts) == 1:
                    raise RuntimeError("transport failed")
                return BridgeResult(
                    "http://127.0.0.1:8766", None, self.id,
                    "TASK_STATE_COMPLETED",
                    response_for(prompt, lambda rule: {
                        "rule_id": rule["id"], "status": "passed",
                        "confidence": 1.0, "evidence": [],
                    }),
                )

        provider.client.session = lambda *args, **kwargs: FlakySession()
        report = await EvaluationService(provider).evaluate(
            EvaluationTarget.snippet("unique_source_marker = 42"), profile,
        )
        self.assertEqual(report.summary.errors, 1)
        self.assertEqual(report.summary.passed, 1)
        self.assertEqual(len(prompts), 2)
        self.assertTrue(all("unique_source_marker" in prompt for prompt in prompts))

    async def test_project_target_rejected_without_agent_tools_before_model_call(self):
        with tempfile.TemporaryDirectory() as folder:
            provider = AgentBridgeProvider("http://127.0.0.1:1", "antigravity", tool_policy="no_tools")
            with self.assertRaisesRegex(ValueError, "No model calls were made"):
                await EvaluationService(provider).evaluate(
                    EvaluationTarget.project(folder),
                    load_code_smells_profile(rule_ids=["long_method"]),
                )

    async def test_debug_trace_includes_batch_progress_and_actual_usage(self):
        profile = load_code_smells_profile(rule_ids=["long_method"])
        emitted = []

        def handler(prompt, workspace, model):
            return ProviderResponse(
                response_for(prompt, lambda rule: {
                    "rule_id": rule["id"], "status": "passed", "confidence": 1.0, "evidence": [],
                }),
                {"input_tokens": 1234, "output_tokens": 56, "total_tokens": 1290},
            )

        report = await EvaluationService(FakeAgentProvider(handler)).evaluate(
            EvaluationTarget.snippet("def small(): return 1"),
            profile,
            debug=True,
            on_debug_event=emitted.append,
        )
        events = [entry["event"] for entry in emitted]
        self.assertEqual(events, [
            "run_started", "batch_started", "agent_request", "agent_response",
            "validated", "batch_finished", "run_finished",
        ])
        self.assertEqual(emitted[-1]["usage_totals"]["input_tokens"], 1234)
        self.assertEqual(report.to_dict()["debug_trace"], emitted)

    async def test_model_and_reasoning_effort_reach_provider_and_report(self):
        profile = load_code_smells_profile(rule_ids=["long_method"])

        def handler(prompt, workspace, model):
            return response_for(
                prompt,
                lambda rule: {
                    "rule_id": rule["id"],
                    "status": "passed",
                    "confidence": 1.0,
                    "evidence": [],
                },
            )

        provider = FakeAgentProvider(handler)
        report = await EvaluationService(provider).evaluate(
            EvaluationTarget.snippet("def small(): return 1", language="python"),
            profile,
            model="chosen-model",
            reasoning_effort="high",
        )

        self.assertEqual(provider.calls[0][2:], ("chosen-model", "high"))
        self.assertEqual(report.provider.model, "chosen-model")
        self.assertEqual(report.provider.reasoning_effort, "high")

    async def test_failed_and_passed_rules_produce_weighted_score(self):
        profile = load_code_smells_profile(rule_ids=["long_method", "large_class"])

        def handler(prompt, workspace, model):
            def result(rule):
                if rule["id"] == "long_method":
                    return {
                        "rule_id": rule["id"],
                        "status": "failed",
                        "confidence": 0.96,
                        "evidence": [
                            {
                                "path": None,
                                "start_line": 1,
                                "end_line": 3,
                                "excerpt": "def process_order():",
                                "reason": "The function combines several unrelated responsibilities.",
                            }
                        ],
                    }
                return {
                    "rule_id": rule["id"],
                    "status": "passed",
                    "confidence": 0.91,
                    "evidence": [],
                }

            return response_for(prompt, result)

        provider = FakeAgentProvider(handler)
        target = EvaluationTarget.snippet(
            "def process_order():\n    validate()\n    charge()\n    notify()\n",
            language="python",
        )
        report = await EvaluationService(provider).evaluate(target, profile, batch_size=10)

        self.assertEqual(report.summary.total, 2)
        self.assertEqual(report.summary.passed, 1)
        self.assertEqual(report.summary.failed, 1)
        self.assertEqual(report.summary.findings, 1)
        self.assertEqual(report.summary.quality_score, 60.0)  # high passed / (high + medium)
        self.assertEqual(report.summary.assessment_coverage, 100.0)
        self.assertEqual([result.rule_id for result in report.results], ["long_method", "large_class"])
        self.assertFalse(report.warnings)
        self.assertEqual(len(provider.calls), 2)  # method and class scopes are separate batches
        text = format_text_report(report)
        self.assertIn("1/2 PASSED", text)
        self.assertIn("Code quality: 60.0%", text)
        self.assertIn("long_method", text)

    async def test_invalid_json_is_repaired_once(self):
        profile = load_code_smells_profile(rule_ids=["long_method"])
        attempts = 0

        def handler(prompt, workspace, model):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return "```json\nnot valid\n```"
            return response_for(
                prompt,
                lambda rule: {
                    "rule_id": rule["id"],
                    "status": "passed",
                    "confidence": 0.8,
                    "evidence": [],
                },
            )

        provider = FakeAgentProvider(handler)
        report = await EvaluationService(provider).evaluate(
            EvaluationTarget.snippet("def small():\n    return 1\n", language="python"),
            profile,
        )
        self.assertEqual(attempts, 2)
        self.assertEqual(report.summary.passed, 1)
        self.assertEqual(report.summary.errors, 0)

    async def test_evidence_outside_project_turns_batch_into_error(self):
        profile = load_code_smells_profile(rule_ids=["long_method"])
        batch_id = None

        def handler(prompt, workspace, model):
            nonlocal batch_id
            if "REQUEST_DATA_JSON\n" in prompt:
                batch_id = request_from_prompt(prompt)["batch_id"]
            return json.dumps({
                "schema_version": "2.0", "batch_id": batch_id,
                "results": [{
                    "rule_id": "long_method", "status": "failed", "confidence": 0.9,
                    "coverage": {"status": "complete", "inspected_paths": ["inside.py"], "limitations": []},
                    "findings": [{"summary": "Invalid location", "evidence": [{
                        "path": "../outside.py", "start_line": 1, "end_line": 1,
                        "excerpt": "outside", "reason": "Invalid out-of-scope evidence.",
                    }]}],
                }],
            })

        class SessionFake(FakeAgentProvider):
            session_id = "test-session"

            @asynccontextmanager
            async def open_session(self, *, workspace=None, model=None, reasoning_effort=None):
                yield self

        provider = SessionFake(handler)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "inside.py").write_text("print('inside')\n", encoding="utf-8")
            report = await EvaluationService(provider).evaluate(EvaluationTarget.project(root), profile)

        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(report.summary.errors, 1)
        self.assertEqual(report.summary.assessment_coverage, 0.0)
        self.assertIsNone(report.summary.quality_score)
        self.assertIn("outside the project target", report.results[0].reason)

    async def test_skipped_requires_reason(self):
        profile = load_code_smells_profile(rule_ids=["cyclic_dependency"])

        def handler(prompt, workspace, model):
            return response_for(
                prompt,
                lambda rule: {
                    "rule_id": rule["id"],
                    "status": "skipped",
                    "confidence": 1.0,
                    "evidence": [],
                    "reason": "A standalone snippet has no module dependency graph.",
                },
            )

        report = await EvaluationService(FakeAgentProvider(handler)).evaluate(
            EvaluationTarget.snippet("x = 1", language="python"),
            profile,
        )
        self.assertEqual(report.summary.skipped, 1)
        self.assertEqual(report.summary.assessment_coverage, 0.0)


if __name__ == "__main__":
    unittest.main()
