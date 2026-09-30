"""Evaluation orchestration."""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable

from .batching import plan_batches
from .executors import BatchRequest, CheckExecutor, LlmCheckExecutor
from .models import CheckResult, EvaluationProfile, EvaluationReport, EvaluationTarget, ProjectCoverage
from .providers.base import AgentProvider
from .scoring import summarize


class EvaluationService:
    def __init__(self, provider: AgentProvider):
        self.provider = provider
        self.executors: dict[str, CheckExecutor] = {"llm": LlmCheckExecutor(provider)}

    async def evaluate(
        self,
        target: EvaluationTarget,
        profile: EvaluationProfile,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
        batch_size: int = 10,
        max_project_seconds: float = 1800,
        use_session: bool = True,
        debug: bool = False,
        on_debug_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> EvaluationReport:
        if target.kind == "project" and max_project_seconds <= 0:
            raise ValueError("max_project_seconds must be positive")
        batches = plan_batches(profile.rules, batch_size=batch_size)
        started = monotonic()
        deadline = started + max_project_seconds if target.kind == "project" else None
        trace: list[dict[str, Any]] = []

        def emit(event: str, details: dict[str, Any]) -> None:
            if not debug:
                return
            entry = {
                "time": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(monotonic() - started, 3),
                "event": event,
                **details,
            }
            trace.append(entry)
            if on_debug_event:
                on_debug_event(entry)

        collected: dict[str, CheckResult] = {}
        warnings: list[str] = []
        if target.kind == "project":
            warnings.append("Project coverage is agent-reported, not independently proven exhaustive.")
        if not self.provider.capabilities.read_only:
            warnings.append("The selected provider cannot guarantee a read-only agent sandbox.")
        if target.kind != "snippet" and not self.provider.capabilities.file_targets:
            raise ValueError("The selected provider does not support file or project targets")
        if target.kind == "project" and not self.provider.capabilities.project_tools:
            raise ValueError(
                "Project evaluation requires agent tools; this provider does not "
                "offer them. No model calls were made."
            )
        if target.kind == "project" and not use_session:
            raise ValueError("Project evaluation requires one persistent agent session. No model calls were made.")

        emit("run_started", {
            "target_kind": target.kind,
            "provider": self.provider.descriptor(model, reasoning_effort).to_dict(),
            "rules": len(profile.rules),
            "batches": len(batches),
            "batch_size": batch_size,
            "max_project_seconds": max_project_seconds if target.kind == "project" else None,
        })

        async def run_batches(executors: dict[str, CheckExecutor]) -> None:
            budget_exhausted = False
            for number, rules in enumerate(batches, start=1):
                executor_ids = {rule.executor for rule in rules}
                if len(executor_ids) != 1:
                    raise ValueError("A batch cannot mix check executors")
                executor_id = next(iter(executor_ids))
                executor = executors.get(executor_id)
                if executor is None:
                    raise ValueError(f"Unknown check executor: {executor_id}")
                batch_id = f"batch-{number:04d}"
                batch_started = monotonic()
                emit("batch_started", {
                    "batch_id": batch_id,
                    "scope": rules[0].scope,
                    "rule_ids": [rule.id for rule in rules],
                })
                try:
                    request = BatchRequest(
                        batch_id=batch_id,
                        target=target,
                        rules=rules,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        emit=emit if debug else None,
                    )
                    if deadline is not None:
                        if budget_exhausted:
                            raise asyncio.TimeoutError
                        remaining = deadline - monotonic()
                        if remaining <= 0:
                            raise asyncio.TimeoutError
                        batch_results = await asyncio.wait_for(executor.execute(request), timeout=remaining)
                    else:
                        batch_results = await executor.execute(request)
                except asyncio.TimeoutError:
                    budget_exhausted = True
                    reason = f"Project time budget of {max_project_seconds:g}s exhausted"
                    warnings.append(reason)
                    emit("batch_budget_exhausted", {"batch_id": batch_id, "reason": reason})
                    batch_results = tuple(
                        CheckResult(
                            rule_id=rule.id, status="inconclusive", severity=rule.severity,
                            reason=reason, coverage=ProjectCoverage("partial", (), (reason,)),
                        ) for rule in rules
                    )
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                    emit("batch_error", {
                        "batch_id": batch_id,
                        "error_type": type(exc).__name__,
                        "message": str(exc).splitlines()[0][:300],
                    })
                    warnings.append(f"{batch_id} failed: {reason}")
                    batch_results = tuple(
                        CheckResult(
                            rule_id=rule.id,
                            status="error",
                            severity=rule.severity,
                            reason=reason,
                            coverage=(
                                ProjectCoverage("partial", (), (reason,))
                                if target.kind == "project" else None
                            ),
                        )
                        for rule in rules
                    )
                for result in batch_results:
                    if result.rule_id in collected:
                        raise RuntimeError(f"Duplicate aggregated result: {result.rule_id}")
                    collected[result.rule_id] = result
                emit("batch_finished", {
                    "batch_id": batch_id,
                    "duration_seconds": round(monotonic() - batch_started, 3),
                    "statuses": dict(Counter(item.status for item in batch_results)),
                })

        open_session = getattr(self.provider, "open_session", None)
        if target.kind == "project" and not callable(open_session):
            raise ValueError("Project provider must support sessions. No model calls were made.")
        if use_session and callable(open_session) and (target.kind == "project" or len(batches) > 1):
            session_options = {"model": model, "reasoning_effort": reasoning_effort}
            if target.kind == "project":
                session_options["workspace"] = target.path
            async with open_session(**session_options) as session_provider:
                emit("session_opened", {"session_id": session_provider.session_id})
                executors = dict(self.executors)
                executors["llm"] = LlmCheckExecutor(session_provider, session_mode=True)
                await run_batches(executors)
            emit("session_closed", {"session_id": session_provider.session_id})
        else:
            await run_batches(self.executors)

        ordered = tuple(collected[rule.id] for rule in profile.rules)
        usage_totals: Counter[str] = Counter()
        for entry in trace:
            if entry["event"] == "agent_response" and isinstance(entry.get("usage"), dict):
                usage_totals.update(entry["usage"])
        agent_requests = sum(entry["event"] == "agent_request" for entry in trace)
        usage_reported_calls = sum(
            entry["event"] == "agent_response" and bool(entry.get("usage"))
            for entry in trace
        )
        emit("run_finished", {
            "duration_seconds": round(monotonic() - started, 3),
            "statuses": dict(Counter(item.status for item in ordered)),
            "usage_totals": dict(usage_totals) if usage_totals else None,
            "agent_requests": agent_requests,
            "usage_reported_calls": usage_reported_calls,
        })
        return EvaluationReport(
            run_id=str(uuid.uuid4()),
            profile=profile,
            target=target,
            provider=self.provider.descriptor(model, reasoning_effort),
            summary=summarize(ordered, project=target.kind == "project"),
            results=ordered,
            warnings=tuple(warnings),
            debug_trace=tuple(trace),
        )
