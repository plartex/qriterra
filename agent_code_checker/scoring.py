"""Deterministic evaluation aggregation and scoring."""

from __future__ import annotations

from collections import Counter

from .models import CheckResult, EvaluationSummary


SEVERITY_WEIGHTS = {"low": 1, "medium": 2, "high": 3, "critical": 5}


def summarize(results: tuple[CheckResult, ...], *, project: bool = False) -> EvaluationSummary:
    counts = Counter(result.status for result in results)
    passed_weight = sum(SEVERITY_WEIGHTS[result.severity] for result in results if result.status == "passed")
    failed_weight = sum(SEVERITY_WEIGHTS[result.severity] for result in results if result.status == "failed")
    assessed_weight = passed_weight + failed_weight
    # A score based on only successful batches looks authoritative even when
    # transport/tool failures left part of the profile unassessed.
    quality = (
        100.0 * passed_weight / assessed_weight
        if assessed_weight and not counts["error"]
        and (not project or all(result.status in {"passed", "failed"} for result in results))
        and all(result.coverage is None or result.coverage.status == "complete" for result in results)
        else None
    )
    assessed_count = (
        sum(result.status in {"passed", "failed"} and result.coverage is not None
            and result.coverage.status == "complete" for result in results)
        if project else counts["passed"] + counts["failed"]
    )
    coverage = 100.0 * assessed_count / len(results) if results else 0.0
    return EvaluationSummary(
        total=len(results),
        passed=counts["passed"],
        failed=counts["failed"],
        skipped=counts["skipped"],
        inconclusive=counts["inconclusive"],
        errors=counts["error"],
        findings=sum(
            len(result.findings) if result.coverage is not None else len(result.evidence)
            for result in results if result.status == "failed"
        ),
        quality_score=quality,
        assessment_coverage=coverage,
    )
