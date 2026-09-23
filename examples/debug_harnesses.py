"""Probe four Agent Bridge harnesses, then evaluate one file with each of them.

Run ``python examples/debug_harnesses.py --help`` for options. All requests go
through local Agent Bridge A2A servers; this script does not launch a harness.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    from agent_bridge import BridgeClient
    from agent_code_checker import EvaluationService, EvaluationTarget, load_code_smells_profile
    from agent_code_checker.providers import AgentBridgeProvider
except ModuleNotFoundError as exc:
    project_python = Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / "python.exe"
    raise SystemExit(
        f"Модуль {exc.name!r} отсутствует в интерпретаторе {sys.executable}.\n"
        f"В PyCharm выберите интерпретатор проекта: {project_python}\n"
        "Если окружение ещё не создано, выполните установку из README.md."
    ) from None


DEFAULT_TARGET = Path(r"C:/path/to/project")
POEM_PROMPT = "Напиши короткое стихотворение на русском о чистом коде: ровно четыре строки."


@dataclass(frozen=True)
class Harness:
    name: str
    url: str
    model: str
    reasoning_effort: str | None = None
    tool_policy: str | None = None


def harnesses(args: argparse.Namespace) -> tuple[Harness, ...]:
    configured = (
        Harness("antigravity", args.antigravity_url, args.antigravity_model),
        Harness("codex", args.codex_url, "gpt-6-sol", "medium"),
        Harness("opencode", args.opencode_url, "qwen3.5:9b", "none", "no_tools"),
        Harness("claude_code", args.claude_url, "qwen3.5:9b", tool_policy="no_tools"),
    )
    chosen = {name.strip() for name in args.agents.split(",") if name.strip()}
    unknown = chosen - {item.name for item in configured}
    if unknown or not chosen:
        raise ValueError(f"Unknown/empty --agents selection: {', '.join(sorted(unknown)) or args.agents}")
    return tuple(item for item in configured if item.name in chosen)


def selected_model(harness: Harness, info: dict | None) -> str:
    """Use a reported Gemini 3.8 variant if the configured one is unavailable."""
    if not isinstance(info, dict):
        return harness.model
    models = info.get("capabilities", {}).get("models", [])
    identifiers = [
        item if isinstance(item, str) else item.get("id")
        for item in models if isinstance(item, (str, dict))
    ]
    identifiers = [item for item in identifiers if isinstance(item, str)]
    if not identifiers or harness.model in identifiers or f"ollama/{harness.model}" in identifiers:
        return harness.model
    if harness.name == "antigravity":
        variants = [item for item in identifiers if "gemini-3.8" in item.lower()]
        if variants:
            return variants[0]
    raise ValueError(f"Model {harness.model!r} is absent from {harness.name} model catalog")


def _print_json(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


async def probe(harness: Harness, client: BridgeClient) -> dict:
    print(f"\n=== {harness.name}: модели и лимиты ===", flush=True)
    result: dict = {"url": harness.url}
    info = None
    try:
        info = await client.info(harness.url)
        result["info"] = info
        _print_json(info)
    except Exception as exc:
        result["info_error"] = f"{type(exc).__name__}: {exc}"
        print(result["info_error"], file=sys.stderr, flush=True)

    print(f"\n=== {harness.name}: стих ===", flush=True)
    try:
        model = selected_model(harness, info)
        result["model"] = model
        options = {"model": model, "reasoning_effort": harness.reasoning_effort}
        if harness.tool_policy is not None:
            options["tool_policy"] = harness.tool_policy
        answer = await client.ask(harness.url, POEM_PROMPT, **options)
        if answer.state not in {"TASK_STATE_COMPLETED", "message"}:
            raise RuntimeError(f"Agent task ended in {answer.state}: {answer.text}")
        result["poem"] = {
            "text": answer.text, "state": answer.state,
            "usage": answer.usage, "details": answer.details,
        }
        _print_json(result["poem"])
    except Exception as exc:
        result["poem_error"] = f"{type(exc).__name__}: {exc}"
        print(result["poem_error"], file=sys.stderr, flush=True)
    return result


async def check_smells(
    harness: Harness, model: str, target: EvaluationTarget,
    profile, output_dir: Path, *, batch_size: int, use_session: bool,
) -> dict:
    print(f"\n=== {harness.name}: code smells ===", flush=True)
    provider = AgentBridgeProvider(
        harness.url, harness.name, tool_policy=harness.tool_policy,
    )

    def trace(event: dict) -> None:
        print(f"[debug:{harness.name}] {json.dumps(event, ensure_ascii=False)}",
              file=sys.stderr, flush=True)

    try:
        report = await EvaluationService(provider).evaluate(
            target, profile, model=model, reasoning_effort=harness.reasoning_effort,
            batch_size=batch_size, use_session=use_session, debug=True,
            on_debug_event=trace,
        )
        path = output_dir / f"{harness.name}.code-smells.json"
        path.write_text(report.to_json() + "\n", encoding="utf-8")
        result = {"report": str(path), "summary": report.summary.to_dict()}
        _print_json(result)
        return result
    except Exception as exc:
        error = {"error": f"{type(exc).__name__}: {exc}"}
        print(error["error"], file=sys.stderr, flush=True)
        return error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", choices=("all", "agents", "smells"), default="all")
    parser.add_argument("--agents", default="antigravity,codex,opencode,claude_code",
                        help="Comma-separated harness names")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET,
                        help="Python file to check; defaults to the known rls.py path")
    parser.add_argument("--rules", help="Comma-separated smell IDs; default: all 80 rules")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--no-session", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("debug-runs"))
    parser.add_argument("--codex-url", default="http://127.0.0.1:8765")
    parser.add_argument("--antigravity-url", default="http://127.0.0.1:8766")
    parser.add_argument("--opencode-url", default="http://127.0.0.1:8767")
    parser.add_argument("--claude-url", default="http://127.0.0.1:8768")
    parser.add_argument("--antigravity-model", default="gemini-3.8-flash-medium")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    chosen = harnesses(args)
    target = profile = None
    if args.part in {"all", "smells"}:
        target = EvaluationTarget.file(args.target)
        rule_ids = [item.strip() for item in args.rules.split(",") if item.strip()] if args.rules else None
        profile = load_code_smells_profile(rule_ids=rule_ids)
        if args.batch_size < 1:
            raise ValueError("--batch-size must be positive")

    output_dir = args.output_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                                    + "-" + uuid4().hex[:6])
    output_dir.mkdir(parents=True, exist_ok=False)
    results: dict = {"target": str(args.target), "part": args.part, "harnesses": {}}
    client = BridgeClient()

    if args.part in {"all", "agents"}:
        for harness in chosen:
            results["harnesses"][harness.name] = await probe(harness, client)

    if args.part in {"all", "smells"}:
        assert target is not None and profile is not None
        print(f"\nПроверка {len(profile.rules)} правил в {len(chosen)} харнессах; отчёты: {output_dir}", flush=True)
        for harness in chosen:
            entry = results["harnesses"].setdefault(harness.name, {"url": harness.url})
            info = entry.get("info")
            if args.part == "smells":
                try:
                    info = await client.info(harness.url)
                    entry["info"] = info
                except Exception as exc:
                    entry["info_error"] = f"{type(exc).__name__}: {exc}"
            try:
                model = entry.get("model") or selected_model(harness, info)
                entry["model"] = model
                entry["smells"] = await check_smells(
                    harness, model, target, profile, output_dir,
                    batch_size=args.batch_size, use_session=not args.no_session,
                )
            except Exception as exc:
                entry["smells"] = {"error": f"{type(exc).__name__}: {exc}"}

    summary = output_dir / "summary.json"
    summary.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nСводка: {summary}", flush=True)
    failures = any(
        entry.get("info_error") or entry.get("poem_error") or entry.get("smells", {}).get("error")
        or entry.get("smells", {}).get("summary", {}).get("errors", 0)
        for entry in results["harnesses"].values()
    )
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(run(parse_args(argv)))
    except (OSError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
