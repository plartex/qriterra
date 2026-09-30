"""MCP entry point for code-quality checks; Agent Shuttle is the transport dependency."""

from __future__ import annotations

import os
from pathlib import Path

from agent_shuttle import HarnessLaunch, connect_harness
from mcp.server.fastmcp import FastMCP

from . import EvaluationService, EvaluationTarget, load_code_smells_profile
from .cli import _project_harness
from .providers import agent_bridge_provider_from_name


mcp = FastMCP(
    "Qriterra",
    instructions=(
        "Use evaluate to detect code smells in a snippet, file, or project. "
        "Project scans use read-only agent tools. This tool only reports findings; "
        "it does not change source code."
    ),
)


@mcp.tool()
async def evaluate(
    target_type: str,
    target: str,
    profile: str = "code_smells",
    rules: list[str] | None = None,
    provider: str = "agent-shuttle:codex",
    agent_url: str | None = None,
    harness_profile: str | None = None,
    tool_policy: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    batch_size: int = 10,
    max_project_seconds: float = 1800,
    language: str | None = None,
    prompt_language: str = "auto",
    use_session: bool = True,
    debug: bool = False,
) -> dict:
    """Evaluate a snippet, file, or project with batched LLM checks."""
    if profile != "code_smells":
        raise ValueError(f"Unknown evaluation profile: {profile}")
    if target_type == "snippet":
        evaluation_target = EvaluationTarget.snippet(target, language=language)
    elif target_type == "file":
        evaluation_target = EvaluationTarget.file(target)
    elif target_type == "project":
        evaluation_target = EvaluationTarget.project(target)
    else:
        raise ValueError("target_type must be snippet, file or project")
    evaluation_profile = load_code_smells_profile(
        rule_ids=rules, prompt_language=prompt_language,
    )
    if target_type == "project":
        if not use_session or tool_policy not in {None, "read_only"}:
            raise ValueError("Project evaluation requires one read-only agent session")
        if agent_url is None:
            harness, port, env_name = _project_harness(provider)
            url = os.environ.get(env_name) or f"http://127.0.0.1:{port}"
        else:
            harness = provider.strip().lower().removeprefix("agent-shuttle:").removeprefix("agent-bridge:")
            url = agent_url
        selected_policy = None if harness == "codex" else "read_only"
        agent_provider = agent_bridge_provider_from_name(
            provider, peer_url=url, tool_policy=selected_policy,
        )
        if agent_url is None:
            assert evaluation_target.path is not None
            launch = HarnessLaunch(
                name=harness, url=url, workspace=evaluation_target.path, model=model,
                profile_path=Path(harness_profile) if harness_profile else None,
                tool_policy="read_only",
            )
            async with connect_harness(launch):
                report = await EvaluationService(agent_provider).evaluate(
                    evaluation_target, evaluation_profile, model=model,
                    reasoning_effort=reasoning_effort, batch_size=batch_size,
                    max_project_seconds=max_project_seconds,
                    use_session=True, debug=debug,
                )
        else:
            if harness_profile is not None:
                raise ValueError("harness_profile cannot be combined with an explicit agent_url")
            report = await EvaluationService(agent_provider).evaluate(
                evaluation_target, evaluation_profile, model=model,
                reasoning_effort=reasoning_effort, batch_size=batch_size,
                max_project_seconds=max_project_seconds,
                use_session=True, debug=debug,
            )
    else:
        if harness_profile is not None:
            raise ValueError("harness_profile is only valid for project targets")
        agent_provider = agent_bridge_provider_from_name(
            provider, peer_url=agent_url, tool_policy=tool_policy,
        )
        report = await EvaluationService(agent_provider).evaluate(
            evaluation_target, evaluation_profile, model=model,
            reasoning_effort=reasoning_effort, batch_size=batch_size,
            max_project_seconds=max_project_seconds,
            use_session=use_session, debug=debug,
        )
    return report.to_dict()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
