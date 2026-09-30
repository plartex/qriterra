"""Command line entry point for code-quality evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from agent_shuttle import HarnessLaunch, connect_harness

from . import EvaluationService, EvaluationTarget, format_text_report, load_code_smells_profile
from .providers import agent_bridge_provider_from_name


_PROJECT_HARNESSES = {
    "codex": ("codex", 8765, "BRIDGE_CODEX_URL"),
    "antigravity": ("antigravity", 8766, "BRIDGE_ANTIGRAVITY_URL"),
    "opencode": ("opencode", 8767, "BRIDGE_OPENCODE_URL"),
    "claude_code": ("claude_code", 8768, "BRIDGE_CLAUDE_CODE_URL"),
}


def _project_harness(provider_name: str) -> tuple[str, int, str]:
    name = provider_name.strip().lower().removeprefix("agent-shuttle:").removeprefix("agent-bridge:")
    if name not in _PROJECT_HARNESSES:
        raise ValueError("Automatic project launch requires codex, antigravity, opencode or claude_code")
    return _PROJECT_HARNESSES[name]


def main() -> None:
    parser = argparse.ArgumentParser(prog="qriterra")
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser("evaluate", help="Run an LLM-first code-quality evaluation")
    evaluate.add_argument("target_type", choices=["snippet", "file", "project"])
    evaluate.add_argument("target", nargs="?", help="File/project path, or snippet when --code is omitted")
    evaluate.add_argument("--code", help="Code content for a snippet target")
    evaluate.add_argument("--language", help="Optional language hint for a snippet")
    evaluate.add_argument("--profile", default="code_smells", choices=["code_smells"])
    evaluate.add_argument("--rules", help="Comma-separated rule IDs; defaults to every profile rule")
    evaluate.add_argument("--batch-size", type=int, default=10)
    evaluate.add_argument("--max-project-seconds", type=float, default=1800)
    evaluate.add_argument(
        "--no-session", action="store_true",
        help="Use an independent agent request for every batch (comparison/fallback)",
    )
    evaluate.add_argument("--provider", default="agent-shuttle:codex")
    evaluate.add_argument("--agent-url", help="A2A URL for any Agent Shuttle profile")
    evaluate.add_argument("--harness-profile", type=Path, help="OpenCode/Claude Code profile for temporary project launch")
    evaluate.add_argument("--tool-policy", choices=["no_tools", "read_only", "workspace_write", "full_access"])
    evaluate.add_argument("--model")
    evaluate.add_argument("--reasoning-effort")
    evaluate.add_argument("--catalog", type=Path, help="Override the bundled code-smells catalog")
    evaluate.add_argument(
        "--prompt-language", choices=["auto", "en", "ru"], default="auto",
        help="LLM-facing rule language; auto uses English for the bundled catalog",
    )
    evaluate.add_argument("--json", action="store_true", dest="json_output")
    evaluate.add_argument(
        "--debug", action="store_true",
        help="Print batch-by-batch JSON trace to stderr and include it in the report",
    )
    evaluate.add_argument("--output", type=Path, help="Write the selected report format to a file")
    args = parser.parse_args()

    if args.target_type == "snippet":
        content = args.code if args.code is not None else args.target
        if content is None:
            parser.error("snippet requires --code or a positional target")
        target = EvaluationTarget.snippet(content, language=args.language)
    else:
        if args.code is not None:
            parser.error("--code is only valid for snippet targets")
        if args.target is None:
            parser.error(f"{args.target_type} requires a path")
        target = (
            EvaluationTarget.file(args.target)
            if args.target_type == "file"
            else EvaluationTarget.project(args.target)
        )
    rule_ids = None
    if args.rules:
        rule_ids = [item.strip() for item in args.rules.split(",") if item.strip()]
    profile = load_code_smells_profile(
        args.catalog, rule_ids=rule_ids, prompt_language=args.prompt_language,
    )
    try:
        async def run_evaluation():
            if target.kind == "project":
                if args.no_session:
                    raise ValueError("Project evaluation requires one persistent agent session")
                if args.tool_policy == "no_tools":
                    raise ValueError("Project evaluation requires agent tools; no_tools cannot inspect the project")
                if args.agent_url is not None and args.harness_profile is not None:
                    raise ValueError("--harness-profile cannot be combined with --agent-url")
                if args.agent_url is None:
                    harness, port, env_name = _project_harness(args.provider)
                    url = os.environ.get(env_name) or f"http://127.0.0.1:{port}"
                else:
                    harness = args.provider.strip().lower().removeprefix("agent-shuttle:").removeprefix("agent-bridge:")
                    url = args.agent_url
                provider_policy = args.tool_policy or (
                    "full_access" if harness == "antigravity" else "read_only"
                )
                if harness == "antigravity" and provider_policy != "full_access":
                    raise ValueError("Antigravity project evaluation requires full_access")
                provider = agent_bridge_provider_from_name(
                    args.provider, peer_url=url, tool_policy=provider_policy,
                )
                if args.agent_url is None:
                    assert target.path is not None
                    launch = HarnessLaunch(
                        name=harness, url=url, workspace=target.path, model=args.model,
                        profile_path=args.harness_profile, tool_policy=provider_policy,
                    )
                    async with connect_harness(launch):
                        return await EvaluationService(provider).evaluate(
                            target, profile, model=args.model, reasoning_effort=args.reasoning_effort,
                            batch_size=args.batch_size, use_session=True, debug=args.debug,
                            max_project_seconds=args.max_project_seconds,
                            on_debug_event=debug_event,
                        )
            else:
                if args.harness_profile is not None:
                    raise ValueError("--harness-profile is only valid for project targets")
                provider = agent_bridge_provider_from_name(
                    args.provider, peer_url=args.agent_url, tool_policy=args.tool_policy,
                )
            return await EvaluationService(provider).evaluate(
                target,
                profile,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                batch_size=args.batch_size,
                max_project_seconds=args.max_project_seconds,
                use_session=not args.no_session,
                debug=args.debug,
                on_debug_event=debug_event,
            )

        debug_event = (
            lambda event: print(
                "[debug] " + json.dumps(event, ensure_ascii=False),
                file=sys.stderr, flush=True,
            )
        ) if args.debug else None
        report = asyncio.run(run_evaluation())
    except ValueError as exc:
        parser.error(str(exc))
    rendered = report.to_json() if args.json_output else format_text_report(report)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    if report.summary.errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
