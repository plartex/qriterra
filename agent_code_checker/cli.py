"""Command line entry point for code-quality evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from . import EvaluationService, EvaluationTarget, format_text_report, load_code_smells_profile
from .providers import agent_bridge_provider_from_name


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-code-checker")
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser("evaluate", help="Run an LLM-first code-quality evaluation")
    evaluate.add_argument("target_type", choices=["snippet", "file", "project"])
    evaluate.add_argument("target", nargs="?", help="File/project path, or snippet when --code is omitted")
    evaluate.add_argument("--code", help="Code content for a snippet target")
    evaluate.add_argument("--language", help="Optional language hint for a snippet")
    evaluate.add_argument("--profile", default="code_smells", choices=["code_smells"])
    evaluate.add_argument("--rules", help="Comma-separated rule IDs; defaults to every profile rule")
    evaluate.add_argument("--batch-size", type=int, default=10)
    evaluate.add_argument("--provider", default="agent-bridge:codex")
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
    provider = agent_bridge_provider_from_name(args.provider)
    try:
        report = asyncio.run(
            EvaluationService(provider).evaluate(
                target,
                profile,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                batch_size=args.batch_size,
                debug=args.debug,
                on_debug_event=(
                    lambda event: print(
                        "[debug] " + json.dumps(event, ensure_ascii=False),
                        file=sys.stderr,
                        flush=True,
                    )
                ) if args.debug else None,
            )
        )
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
