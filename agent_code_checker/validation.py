"""Strict validation of LLM batch responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    CheckResult, EvaluationTarget, Evidence, ProjectCoverage, ProjectFinding,
    RuleDefinition, VALID_STATUSES,
)


class BatchProtocolError(ValueError):
    pass


def validate_batch_response(
    raw_response: str,
    *,
    batch_id: str,
    rules: tuple[RuleDefinition, ...],
    target: EvaluationTarget,
) -> tuple[CheckResult, ...]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise BatchProtocolError(f"response is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BatchProtocolError("response must be a JSON object")
    version = "2.0" if target.kind == "project" else "1.0"
    if payload.get("schema_version") != version:
        raise BatchProtocolError(f"schema_version must be {version}")
    if payload.get("batch_id") != batch_id:
        raise BatchProtocolError("batch_id does not match the request")
    items = payload.get("results")
    if not isinstance(items, list):
        raise BatchProtocolError("results must be an array")

    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise BatchProtocolError(f"results[{index}] must be an object")
        rule_id = item.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            raise BatchProtocolError(f"results[{index}].rule_id must be a nonempty string")
        if rule_id in by_id:
            raise BatchProtocolError(f"duplicate result for rule {rule_id}")
        by_id[rule_id] = item

    expected = {rule.id for rule in rules}
    actual = set(by_id)
    if expected != actual:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise BatchProtocolError(f"rule ids do not match; missing={missing}, extra={extra}")

    parser = _parse_project_result if target.kind == "project" else _parse_result
    return tuple(parser(by_id[rule.id], rule, target) for rule in rules)


def _parse_project_result(source: dict[str, Any], rule: RuleDefinition, target: EvaluationTarget) -> CheckResult:
    status = source.get("status")
    if status not in VALID_STATUSES:
        raise BatchProtocolError(f"Rule {rule.id} has invalid status: {status}")
    confidence = source.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise BatchProtocolError(f"Rule {rule.id} confidence must be between 0 and 1")
    coverage = _parse_project_coverage(source.get("coverage"), rule.id, target)
    raw_findings = source.get("findings")
    if not isinstance(raw_findings, list):
        raise BatchProtocolError(f"Rule {rule.id} findings must be an array")
    findings: list[ProjectFinding] = []
    for index, item in enumerate(raw_findings):
        if not isinstance(item, dict) or not isinstance(item.get("summary"), str) or not item["summary"].strip():
            raise BatchProtocolError(f"Rule {rule.id} finding[{index}] requires a summary")
        raw_evidence = item.get("evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise BatchProtocolError(f"Rule {rule.id} finding[{index}] requires evidence")
        evidence = tuple(
            _parse_evidence(entry, rule.id, target, evidence_index)
            for evidence_index, entry in enumerate(raw_evidence)
        )
        findings.append(ProjectFinding(item["summary"].strip(), evidence))
    reason = source.get("reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise BatchProtocolError(f"Rule {rule.id} reason must be a nonempty string")
    if status == "failed" and not findings:
        raise BatchProtocolError(f"Rule {rule.id} failed without findings")
    if status != "failed" and findings:
        raise BatchProtocolError(f"Rule {rule.id} may only include findings when failed")
    if status == "passed" and coverage.status != "complete":
        raise BatchProtocolError(f"Rule {rule.id} cannot pass with partial coverage")
    if status in {"skipped", "inconclusive", "error"} and reason is None:
        raise BatchProtocolError(f"Rule {rule.id} with status {status} requires reason")
    return CheckResult(
        rule_id=rule.id, status=status, severity=rule.severity,
        confidence=float(confidence), findings=tuple(findings), coverage=coverage,
        reason=reason.strip() if isinstance(reason, str) else None,
    )


def _parse_project_coverage(source: Any, rule_id: str, target: EvaluationTarget) -> ProjectCoverage:
    if not isinstance(source, dict) or source.get("status") not in {"complete", "partial"}:
        raise BatchProtocolError(f"Rule {rule_id} coverage.status must be complete or partial")
    paths = source.get("inspected_paths")
    limitations = source.get("limitations")
    if not isinstance(paths, list) or any(not isinstance(path, str) or not path.strip() for path in paths):
        raise BatchProtocolError(f"Rule {rule_id} coverage.inspected_paths must be an array of paths")
    if not isinstance(limitations, list) or any(
        not isinstance(item, str) or not item.strip() for item in limitations
    ):
        raise BatchProtocolError(f"Rule {rule_id} coverage.limitations must be an array of strings")
    if source["status"] == "partial" and not limitations:
        raise BatchProtocolError(f"Rule {rule_id} partial coverage requires limitations")
    if source["status"] == "complete" and (not paths or limitations):
        raise BatchProtocolError(f"Rule {rule_id} complete coverage requires inspected paths and no limitations")
    assert target.path is not None
    normalized = []
    for path in paths:
        candidate = (target.path / path).resolve(strict=False)
        try:
            relative = candidate.relative_to(target.path)
        except ValueError as exc:
            raise BatchProtocolError(f"Rule {rule_id} inspected path points outside the project") from exc
        if not candidate.exists():
            raise BatchProtocolError(f"Rule {rule_id} inspected path does not exist")
        normalized.append(relative.as_posix())
    return ProjectCoverage(source["status"], tuple(normalized), tuple(item.strip() for item in limitations))


def _parse_result(source: dict[str, Any], rule: RuleDefinition, target: EvaluationTarget) -> CheckResult:
    status = source.get("status")
    if status not in VALID_STATUSES:
        raise BatchProtocolError(f"Rule {rule.id} has invalid status: {status}")
    confidence = source.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise BatchProtocolError(f"Rule {rule.id} confidence must be a number")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise BatchProtocolError(f"Rule {rule.id} confidence must be between 0 and 1")

    raw_evidence = source.get("evidence")
    if not isinstance(raw_evidence, list):
        raise BatchProtocolError(f"Rule {rule.id} evidence must be an array")
    evidence = tuple(_parse_evidence(item, rule.id, target, index) for index, item in enumerate(raw_evidence))
    reason = source.get("reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise BatchProtocolError(f"Rule {rule.id} reason must be a nonempty string")
    if isinstance(reason, str):
        reason = reason.strip()

    if status == "failed" and not evidence:
        raise BatchProtocolError(f"Rule {rule.id} failed without evidence")
    if status != "failed" and evidence:
        raise BatchProtocolError(f"Rule {rule.id} may only include evidence when failed")
    if status in {"skipped", "inconclusive", "error"} and reason is None:
        raise BatchProtocolError(f"Rule {rule.id} with status {status} requires reason")

    return CheckResult(
        rule_id=rule.id,
        status=status,
        severity=rule.severity,
        confidence=confidence,
        evidence=evidence,
        reason=reason,
    )


def _parse_evidence(
    source: Any,
    rule_id: str,
    target: EvaluationTarget,
    index: int,
) -> Evidence:
    if not isinstance(source, dict):
        raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] must be an object")
    start = source.get("start_line")
    end = source.get("end_line")
    if isinstance(start, bool) or not isinstance(start, int) or start < 1:
        raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] has invalid start_line")
    if isinstance(end, bool) or not isinstance(end, int) or end < start:
        raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] has invalid end_line")
    excerpt = source.get("excerpt")
    reason = source.get("reason")
    if not isinstance(excerpt, str) or not excerpt.strip():
        raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] requires excerpt")
    if not isinstance(reason, str) or not reason.strip():
        raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] requires reason")
    normalized_path = _validate_evidence_path(source.get("path"), target, rule_id, index)
    _validate_line_range(target, normalized_path, start, end, rule_id, index)
    if target.kind == "project":
        assert target.path is not None and normalized_path is not None
        lines = (target.path / normalized_path).read_text(encoding="utf-8", errors="replace").splitlines()
        if excerpt.strip() not in "\n".join(lines[start - 1:end]):
            raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] excerpt does not match source lines")
    return Evidence(
        path=normalized_path,
        start_line=start,
        end_line=end,
        excerpt=excerpt.strip(),
        reason=reason.strip(),
    )


def _validate_evidence_path(value: Any, target: EvaluationTarget, rule_id: str, index: int) -> str | None:
    if target.kind == "snippet":
        if value is not None:
            raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] path must be null for snippet")
        return None
    if not isinstance(value, str) or not value.strip():
        raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] requires a path")
    supplied = Path(value)
    assert target.path is not None
    if target.kind == "file":
        candidate = supplied if supplied.is_absolute() else target.path.parent / supplied
        resolved = candidate.resolve(strict=False)
        if resolved != target.path:
            raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] points outside the file target")
        return str(target.path)

    candidate = supplied if supplied.is_absolute() else target.path / supplied
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(target.path)
    except ValueError as exc:
        raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] points outside the project target") from exc
    if not resolved.is_file():
        raise BatchProtocolError(f"Rule {rule_id} evidence[{index}] path is not an existing file")
    return relative.as_posix()


def _validate_line_range(
    target: EvaluationTarget,
    evidence_path: str | None,
    start: int,
    end: int,
    rule_id: str,
    index: int,
) -> None:
    try:
        if target.kind == "snippet":
            assert target.content is not None
            line_count = max(1, len(target.content.splitlines()))
        elif target.kind == "file":
            assert target.path is not None
            line_count = max(1, len(target.path.read_text(encoding="utf-8", errors="replace").splitlines()))
        else:
            assert target.path is not None and evidence_path is not None
            line_count = max(
                1,
                len((target.path / evidence_path).read_text(encoding="utf-8", errors="replace").splitlines()),
            )
    except OSError as exc:
        raise BatchProtocolError(f"Cannot validate evidence file for rule {rule_id}: {exc}") from exc
    if end > line_count:
        raise BatchProtocolError(
            f"Rule {rule_id} evidence[{index}] ends at line {end}, but target has {line_count} lines"
        )
