import json
import tempfile
import unittest
from pathlib import Path

from agent_code_checker import EvaluationTarget, load_code_smells_profile
from agent_code_checker.validation import BatchProtocolError, validate_batch_response


class ProjectEvidenceIntegrityTests(unittest.TestCase):
    def test_coverage_requires_files_and_findings_require_inspected_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.py").write_text("x = 1\n", encoding="utf-8")
            (root / "two.py").write_text("x = 1\n", encoding="utf-8")
            target = EvaluationTarget.project(root)
            rules = load_code_smells_profile(rule_ids=["duplicate_code"]).rules
            for paths, findings, message in (
                (["."], [], "must be a file"),
                (["one.py"], [{"summary": "duplicate", "evidence": [{
                    "path": "two.py", "start_line": 1, "end_line": 1,
                    "excerpt": "x = 1", "reason": "copy",
                }]}], "not declared as inspected"),
            ):
                payload = {"schema_version": "2.0", "batch_id": "b", "results": [{
                    "rule_id": "duplicate_code", "status": "failed" if findings else "passed",
                    "confidence": .9, "findings": findings,
                    "coverage": {"status": "complete", "inspected_paths": paths, "limitations": []},
                }]}
                with self.subTest(paths=paths), self.assertRaisesRegex(BatchProtocolError, message):
                    validate_batch_response(json.dumps(payload), batch_id="b", rules=rules, target=target)
