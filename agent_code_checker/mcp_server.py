"""MCP entry point for code-quality checks; Agent Bridge is the transport dependency."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import EvaluationService, EvaluationTarget, load_code_smells_profile
from .providers import agent_bridge_provider_from_name


mcp = FastMCP(
    "Agent Code Checker",
    instructions=(
        "Use evaluate to detect code smells in a snippet or a file. "
        "Project scanning is not implemented yet. This tool only reports findings; "
        "it does not change source code."
    ),
)


@mcp.tool()
async def evaluate(
    target_type: str,
    target: str,
    profile: str = "code_smells",
    rules: list[str] | None = None,
    provider: str = "agent-bridge:codex",
    model: str | None = None,
    reasoning_effort: str | None = None,
    batch_size: int = 10,
    language: str | None = None,
    prompt_language: str = "auto",
    use_session: bool = True,
    debug: bool = False,
) -> dict:
    """Evaluate a code snippet or file with batched LLM checks."""
    if profile != "code_smells":
        raise ValueError(f"Unknown evaluation profile: {profile}")
    if target_type == "snippet":
        evaluation_target = EvaluationTarget.snippet(target, language=language)
    elif target_type == "file":
        evaluation_target = EvaluationTarget.file(target)
    elif target_type == "project":
        raise ValueError("Project scanning is not implemented; no model calls were made")
    else:
        raise ValueError("target_type must be snippet or file")
    evaluation_profile = load_code_smells_profile(
        rule_ids=rules, prompt_language=prompt_language,
    )
    agent_provider = agent_bridge_provider_from_name(provider)
    report = await EvaluationService(agent_provider).evaluate(
        evaluation_target,
        evaluation_profile,
        model=model,
        reasoning_effort=reasoning_effort,
        batch_size=batch_size,
        use_session=use_session,
        debug=debug,
    )
    return report.to_dict()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
