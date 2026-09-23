"""Agent Bridge transport provider."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from agent_bridge import BridgeClient, BridgeResult, BridgeSession, ToolPolicy
from ..models import ProviderDescriptor
from .base import ProviderCapabilities, ProviderResponse


class AgentBridgeProvider:
    def __init__(
        self, peer_url: str, agent: str, timeout_seconds: float = 1800,
        *, tool_policy: str | None = None,
    ):
        if not peer_url.strip():
            raise ValueError("peer_url must be nonempty")
        if not agent.strip():
            raise ValueError("agent must be nonempty")
        if tool_policy is not None:
            try:
                tool_policy = ToolPolicy(tool_policy).value
            except ValueError as exc:
                raise ValueError("tool_policy must be no_tools, read_only, or workspace_write") from exc
        self.peer_url = peer_url.rstrip("/")
        self.agent = agent.strip()
        self.tool_policy = tool_policy
        self._bridge_read_only = self.agent.lower() == "codex" and tool_policy is None
        self.client = BridgeClient(timeout_seconds=timeout_seconds)
        self.capabilities = ProviderCapabilities(
            file_targets=True,
            dynamic_workspace=False,
            read_only=self._bridge_read_only or tool_policy in {"no_tools", "read_only"},
            structured_output=False,
        )

    def descriptor(
        self,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="agent_bridge",
            agent=self.agent,
            model=model,
            reasoning_effort=reasoning_effort,
            read_only=self.capabilities.read_only,
        )

    async def run(
        self,
        prompt: str,
        *,
        workspace: Path | None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderResponse:
        # The current bridge server owns its workspace. The absolute target path in
        # the prompt scopes the evaluation; workspace is retained for future
        # dynamic-workspace support.
        options = {
            "model": model,
            "reasoning_effort": reasoning_effort,
            "read_only": self._bridge_read_only,
        }
        if self.tool_policy is not None:
            options["tool_policy"] = self.tool_policy
        result = await self.client.ask(self.peer_url, prompt, **options)
        return _provider_response(result)

    @asynccontextmanager
    async def open_session(
        self,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[_SessionProvider]:
        """Keep one AB conversation alive for all batches in one evaluation."""
        options = {
            "model": model,
            "reasoning_effort": reasoning_effort,
            "read_only": self._bridge_read_only,
        }
        if self.tool_policy is not None:
            options["tool_policy"] = self.tool_policy
        async with self.client.session(self.peer_url, **options) as session:
            yield _SessionProvider(self, session, model, reasoning_effort)


class _SessionProvider:
    def __init__(
        self,
        parent: AgentBridgeProvider,
        session: BridgeSession,
        model: str | None,
        reasoning_effort: str | None,
    ):
        self.parent = parent
        self.session = session
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.capabilities = parent.capabilities

    @property
    def session_id(self) -> str:
        return self.session.id

    def descriptor(
        self,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderDescriptor:
        return self.parent.descriptor(model, reasoning_effort)

    async def run(
        self,
        prompt: str,
        *,
        workspace: Path | None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderResponse:
        if model != self.model or reasoning_effort != self.reasoning_effort:
            raise ValueError("model and reasoning_effort are fixed for a bridge session")
        result = await self.session.ask(prompt)
        return _provider_response(result)


def _provider_response(result: BridgeResult) -> ProviderResponse:
    if result.state not in {"TASK_STATE_COMPLETED", "message"}:
        raise RuntimeError(f"Agent Bridge task ended in {result.state}: {result.text}")
    return ProviderResponse(result.text, result.usage)


def agent_bridge_provider_from_name(
    name: str, *, peer_url: str | None = None, tool_policy: str | None = None,
) -> AgentBridgeProvider:
    normalized = name.strip().lower()
    aliases = {
        "codex": ("codex", "BRIDGE_CODEX_URL"),
        "agent-bridge:codex": ("codex", "BRIDGE_CODEX_URL"),
        "antigravity": ("antigravity", "BRIDGE_ANTIGRAVITY_URL"),
        "agent-bridge:antigravity": ("antigravity", "BRIDGE_ANTIGRAVITY_URL"),
    }
    if normalized in aliases:
        agent, env_name = aliases[normalized]
        url = peer_url or os.environ.get(env_name)
        if not url:
            raise RuntimeError(f"Set {env_name} to the local A2A server URL")
    elif normalized.startswith("agent-bridge:") and name.strip().split(":", 1)[1].strip():
        agent = name.strip().split(":", 1)[1].strip()
        url = peer_url
        if not url:
            raise ValueError("Custom Agent Bridge profiles require agent_url")
    else:
        raise ValueError(f"Unknown provider: {name}")
    return AgentBridgeProvider(url, agent, tool_policy=tool_policy)
