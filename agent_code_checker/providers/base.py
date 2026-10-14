"""Agent transport abstraction used by the LLM check executor."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..models import ProviderDescriptor


@dataclass(frozen=True)
class ProviderCapabilities:
    file_targets: bool = True
    dynamic_workspace: bool = False
    read_only: bool = False
    structured_output: bool = False
    project_tools: bool = False


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    usage: dict[str, int] | None = None
    details: dict[str, object] | None = None


class ProviderExecutionError(RuntimeError):
    """A failed native turn, with an explicit continuation and retry decision."""

    def __init__(self, message, *, retryable=False, usage=None, details=None):
        super().__init__(message)
        self.retryable = retryable
        self.usage = usage
        self.details = details


class AgentProvider(Protocol):
    capabilities: ProviderCapabilities

    def descriptor(
        self,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderDescriptor: ...

    async def run(
        self,
        prompt: str,
        *,
        workspace: Path | None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str | ProviderResponse: ...
