"""Common check-executor contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ..models import CheckResult, EvaluationTarget, RuleDefinition
from ..project_snapshot import ProjectSnapshot


@dataclass(frozen=True)
class BatchRequest:
    batch_id: str
    target: EvaluationTarget
    rules: tuple[RuleDefinition, ...]
    model: str | None = None
    reasoning_effort: str | None = None
    emit: Callable[[str, dict[str, Any]], None] | None = None
    on_result: Callable[[CheckResult], None] | None = None
    snapshot: ProjectSnapshot | None = None


class CheckExecutor(Protocol):
    id: str

    async def execute(self, request: BatchRequest) -> tuple[CheckResult, ...]: ...
