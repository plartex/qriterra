"""Evaluation orchestration."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections import Counter
from datetime import datetime, timezone
from time import monotonic
from dataclasses import replace
from typing import Any, Callable

from .batching import plan_batches
from .executors import BatchRequest, CheckExecutor, LlmCheckExecutor
from .models import CheckResult, EvaluationProfile, EvaluationReport, EvaluationTarget, ProjectCoverage
from .providers.base import AgentProvider, ProviderExecutionError
from .response_schema import project_output_schema
from .project_snapshot import capture_project, ProjectSnapshotError
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
        snapshot = None
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
        if target.kind == "project":
            snapshot = capture_project(target.path)

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
            fatal_session_error = None
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
                progress: dict[str, CheckResult] = {}
                emit("batch_started", {
                    "batch_id": batch_id,
                    "scope": rules[0].scope,
                    "rule_ids": [rule.id for rule in rules],
                })
                try:
                    if fatal_session_error is not None:
                        raise ProviderExecutionError(fatal_session_error)
                    request = BatchRequest(
                        batch_id=batch_id,
                        target=target,
                        rules=rules,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        emit=emit if debug else None,
                        on_result=lambda item: progress.setdefault(item.rule_id, item),
                        snapshot=snapshot,
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
                        progress.get(rule.id) or CheckResult(
                            rule_id=rule.id, status="inconclusive", severity=rule.severity,
                            reason=reason, coverage=ProjectCoverage("partial", (), (reason,)),
                        ) for rule in rules
                    )
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                    if isinstance(exc, ProviderExecutionError) and not exc.retryable:
                        if fatal_session_error is None:
                            emit("run_aborted", {"reason": reason, "completed_rule_ids": list(collected)})
                            fatal_session_error = reason
                    emit("batch_error", {
                        "batch_id": batch_id,
                        "error_type": type(exc).__name__,
                        "message": str(exc).splitlines()[0][:300],
                    })
                    warnings.append(f"{batch_id} failed: {reason}")
                    batch_results = tuple(
                        progress.get(rule.id) or CheckResult(
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
                if (self.provider.capabilities.structured_output
                        and "output_schema" in inspect.signature(open_session).parameters):
                    session_options["output_schema"] = project_output_schema([rule.id for rule in profile.rules])
            async with open_session(**session_options) as session_provider:
                emit("session_opened", {"session_id": session_provider.session_id})
                executors = dict(self.executors)
                executors["llm"] = LlmCheckExecutor(session_provider, session_mode=True)
                await run_batches(executors)
            emit("session_closed", {"session_id": session_provider.session_id})
        else:
            await run_batches(self.executors)

        ordered = tuple(collected[rule.id] for rule in profile.rules)
        snapshot_report = None
        undeclared_paths = ()
        if snapshot is not None:
            verification_error = None
            try:
                changed = snapshot.changes(target.path)
            except ProjectSnapshotError as exc:
                changed = []
                verification_error = str(exc)
            snapshot_report = {**snapshot.to_dict(),
                               "unchanged": not changed if verification_error is None else None,
                               "changed_paths": changed}
            if verification_error is not None:
                snapshot_report["verification_error"] = verification_error
            declared_paths = {path for item in ordered if item.coverage is not None
                              for path in item.coverage.inspected_paths}
            manifest_paths = {file.path for file in snapshot.files}
            undeclared_paths = sorted(manifest_paths - declared_paths)
            snapshot_report.update({
                "declared_inspected_paths": sorted(declared_paths),
                "undeclared_paths": undeclared_paths,
                "declared_file_coverage": (len(manifest_paths & declared_paths) / len(manifest_paths)
                                           if manifest_paths else 0.0),
            })
            if undeclared_paths:
                warnings.append("Source files not declared inspected: " + ", ".join(undeclared_paths[:20]))
            if changed or verification_error is not None:
                reason = ("Project source could not be verified: " + verification_error
                          if verification_error is not None else
                          "Project source changed during evaluation: " + ", ".join(changed[:20]))
                warnings.append(reason)
                emit("source_verification_failed" if verification_error is not None else "source_changed",
                     {"changed_paths": changed, "reason": reason})
                ordered = tuple(replace(
                    item, status="inconclusive", reason=reason, findings=(), evidence=(),
                    coverage=ProjectCoverage("partial", item.coverage.inspected_paths if item.coverage else (), (reason,)),
                ) if item.status in {"passed", "failed"} else item for item in ordered)
        usage_totals: Counter[str] = Counter()
        for entry in trace:
            if entry["event"] in {"agent_response", "agent_error"} and isinstance(entry.get("usage"), dict):
                usage_totals.update(entry["usage"])
            if entry["event"] in {"agent_response", "agent_error"}:
                probe = (entry.get("details") or {}).get("policy_probe_usage")
                if isinstance(probe, dict) and not (entry.get("details") or {}).get("usage_includes_policy_probe"):
                    usage_totals.update(probe)
        agent_requests = sum(entry["event"] == "agent_request" for entry in trace)
        usage_reported_calls = sum(
            entry["event"] in {"agent_response", "agent_error"} and bool(entry.get("usage"))
            for entry in trace
        )
        emit("run_finished", {
            "duration_seconds": round(monotonic() - started, 3),
            "statuses": dict(Counter(item.status for item in ordered)),
            "usage_totals": dict(usage_totals) if usage_totals else None,
            "agent_requests": agent_requests,
            "usage_reported_calls": usage_reported_calls,
        })
        summary = summarize(ordered, project=target.kind == "project")
        if undeclared_paths or snapshot is not None and snapshot.limitations:
            summary = replace(summary, quality_score=None)
        return EvaluationReport(
            run_id=str(uuid.uuid4()),
            profile=profile,
            target=target,
            provider=self.provider.descriptor(model, reasoning_effort),
            summary=summary,
            results=ordered,
            warnings=tuple(warnings),
            debug_trace=tuple(trace),
            source_snapshot=snapshot_report,
        )
