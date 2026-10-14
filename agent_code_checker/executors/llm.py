"""LLM-backed rule executor."""

from __future__ import annotations

import asyncio
from time import monotonic
from ..models import CheckResult, ProjectCoverage

from ..prompting import (
    build_evaluation_prompt,
    build_repair_prompt,
    build_session_batch_prompt,
)
from ..providers.base import AgentProvider, ProviderResponse, ProviderExecutionError
from ..validation import BatchProtocolError, recover_valid_project_results, validate_batch_response
from ..privacy import diagnostic_error, assessment_error
from .base import BatchRequest


class LlmCheckExecutor:
    id = "llm"

    def __init__(self, provider: AgentProvider, *, session_mode: bool = False):
        self.provider = provider
        self.session_mode = session_mode
        self._has_target_context = False

    async def execute(self, request: BatchRequest):
        is_continuation = self.session_mode and self._has_target_context
        prompt = (
            build_session_batch_prompt(request.batch_id, request.rules, target=request.target)
            if is_continuation else
            build_evaluation_prompt(request.batch_id, request.target, request.rules, snapshot=request.snapshot)
        )
        async def run(text: str, attempt: int, batch_id=None) -> str:
            active_batch = batch_id or request.batch_id
            if request.emit:
                request.emit("agent_request", {
                    "batch_id": active_batch,
                    "attempt": attempt,
                    "prompt_bytes": len(text.encode("utf-8")),
                })
            call = self.provider.run(
                text,
                workspace=request.target.workspace,
                model=request.model,
                reasoning_effort=request.reasoning_effort,
            )
            if request.emit:
                started = monotonic()
                task = asyncio.create_task(call)
                try:
                    while True:
                        try:
                            response = await asyncio.wait_for(asyncio.shield(task), timeout=10)
                            break
                        except asyncio.TimeoutError as exc:
                            if task.done():
                                raise ProviderExecutionError(f"Provider turn timed out: {exc}") from exc
                            request.emit("agent_waiting", {
                                "batch_id": active_batch,
                                "attempt": attempt,
                                "waiting_seconds": round(monotonic() - started, 1),
                            })
                except BaseException:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    raise
            else:
                try:
                    response = await call
                except TimeoutError as exc:
                    raise ProviderExecutionError(f"Provider turn timed out: {exc}") from exc
            raw = response.text if isinstance(response, ProviderResponse) else response
            if self.session_mode and not is_continuation:
                self._has_target_context = True
            if request.emit:
                request.emit("agent_response", {
                    "batch_id": active_batch,
                    "attempt": attempt,
                    "response_bytes": len(raw.encode("utf-8")),
                    "usage": response.usage if isinstance(response, ProviderResponse) else None,
                    "details": response.details if isinstance(response, ProviderResponse) else None,
                })
            return raw

        if request.target.kind == "project":
            return await self._execute_project(request, prompt, run)

        raw = await run(prompt, 1)
        try:
            results = validate_batch_response(
                raw,
                batch_id=request.batch_id,
                rules=request.rules,
                target=request.target,
            )
            if request.emit:
                request.emit("validated", {"batch_id": request.batch_id, "attempt": 1})
            return results
        except BatchProtocolError as first_error:
            if request.emit:
                request.emit("validation_failed", {
                    "batch_id": request.batch_id,
                    "attempt": 1,
                    "reason": diagnostic_error(first_error),
                })
            repair = build_repair_prompt(
                prompt,
                request.batch_id,
                tuple(rule.id for rule in request.rules),
                raw,
                str(first_error),
                include_original=not self.session_mode,
                schema_version="2.0" if request.target.kind == "project" else "1.0",
            )
            repaired = await run(repair, 2)
            try:
                results = validate_batch_response(
                    repaired,
                    batch_id=request.batch_id,
                    rules=request.rules,
                    target=request.target,
                )
                if request.emit:
                    request.emit("validated", {"batch_id": request.batch_id, "attempt": 2})
                return results
            except BatchProtocolError as second_error:
                raise BatchProtocolError(
                    f"invalid response after one repair: {second_error}; first error: {first_error}"
                ) from second_error

    async def _execute_project(self, request, prompt, run):
        accepted = {}
        errors = {}
        call_number = 0

        async def investigate(rules, batch_id, initial_prompt):
            nonlocal call_number
            pending = rules
            text = initial_prompt
            raw = ""
            for attempt in range(2):
                call_number += 1
                try:
                    raw = await run(text, call_number, batch_id)
                except ProviderExecutionError as exc:
                    if request.emit:
                        request.emit("agent_error", {"batch_id": batch_id, "attempt": call_number,
                                     "usage": exc.usage, "details": exc.details,
                                     "retryable": exc.retryable, "reason": diagnostic_error(exc)})
                    if not exc.retryable:
                        raise
                    problem = diagnostic_error(exc)
                    for rule in pending:
                        errors[rule.id] = problem
                else:
                    results = recover_valid_project_results(
                        (raw,), batch_id=batch_id, rules=pending, target=request.target,
                    )
                    for item in results:
                        if item.status == "error":
                            errors[item.rule_id] = assessment_error(item.reason)
                        elif item.rule_id not in accepted:
                            accepted[item.rule_id] = item
                            if request.on_result:
                                request.on_result(item)
                    pending = tuple(rule for rule in pending if rule.id not in accepted)
                    if not pending:
                        if request.emit:
                            request.emit("validated", {"batch_id": batch_id, "attempt": call_number})
                        return
                    problem = "\n".join(f"{rule.id}: {errors[rule.id]}" for rule in pending)
                if request.emit:
                    request.emit("validation_failed", {"batch_id": batch_id, "attempt": call_number,
                                 "reason": problem[:1500], "pending_rule_ids": [r.id for r in pending]})
                text = build_repair_prompt(
                    initial_prompt, batch_id, tuple(r.id for r in pending), raw, problem,
                    include_original=False, schema_version="2.0", target=request.target, rules=pending,
                )
            if len(pending) > 1:
                midpoint = len(pending) // 2
                if request.emit:
                    request.emit("batch_split", {"batch_id": batch_id,
                                 "pending_rule_ids": [r.id for r in pending]})
                for number, child_rules in enumerate((pending[:midpoint], pending[midpoint:]), 1):
                    child_id = f"{batch_id}.{number}"
                    await investigate(child_rules, child_id,
                                      build_session_batch_prompt(child_id, child_rules, target=request.target))

        await investigate(request.rules, request.batch_id, prompt)
        return tuple(accepted.get(rule.id) or CheckResult(
            rule_id=rule.id, status="error", severity=rule.severity,
            reason=errors.get(rule.id, "No valid result after bounded recovery"),
            coverage=ProjectCoverage("partial", (), (errors.get(rule.id, "Recovery exhausted"),)),
        ) for rule in request.rules)
