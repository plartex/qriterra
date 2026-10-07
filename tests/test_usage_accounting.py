import json
import unittest
from agent_code_checker import EvaluationService, EvaluationTarget, load_code_smells_profile
from agent_code_checker.providers.fake import FakeAgentProvider
from agent_code_checker.providers.base import ProviderResponse


class UsageAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def test_combined_oneshot_usage_does_not_count_permission_probe_twice(self):
        class Provider(FakeAgentProvider):
            async def run(self, prompt, **kwargs):
                return ProviderResponse(json.dumps({"schema_version":"1.0", "batch_id":"batch-0001",
                    "results":[{"rule_id":"long_method", "status":"passed", "confidence":1,
                                "evidence":[]}]}), usage={"total_tokens":23},
                    details={"policy_probe_usage":{"total_tokens":10}, "usage_includes_policy_probe":True})
        report = await EvaluationService(Provider(lambda *_: "")).evaluate(
            EvaluationTarget.snippet("x = 1"), load_code_smells_profile(rule_ids=["long_method"]),
            use_session=False, debug=True,
        )
        finished = next(event for event in report.debug_trace if event['event']=='run_finished')
        self.assertEqual(finished['usage_totals'], {"total_tokens":23})
