"""One-click diagnostic orchestrating Agent Bridge and Agent Code Checker.

Open this file in PyCharm and press Run. All task-specific calls live here:
Bridge discovery/info/ask, followed by EvaluationService.evaluate(). The two
libraries remain reusable independently. Command-line arguments override the
configuration below when the script is launched from a terminal or IDE.
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
    from agent_bridge import BridgeClient, HarnessLaunch, connect_harness, discover_harnesses
    from agent_code_checker import EvaluationService, EvaluationTarget, load_code_smells_profile
    from agent_code_checker.providers import AgentBridgeProvider
except ModuleNotFoundError as exc:
    raise SystemExit(
        f"Missing {exc.name!r}. Select the checker .venv as the PyCharm interpreter, "
        "or install Agent Bridge and Agent Code Checker into this Python environment."
    ) from None


# Edit these values for another project. RULES=None is the user's full 80-rule run.
TARGET = Path("examples/sample_target.py")
AGENTS = "auto"  # Or "codex", "antigravity", "opencode,claude_code", etc.
RULES = None  # All 80 code-smell rules; e.g. "long_method,large_class" for a short run.
OUTPUT_DIR = Path(__file__).resolve().parent / "debug-runs"
MODELS = {"antigravity": "gemini-3.8-flash-medium", "codex": "gpt-6-sol",
          "opencode": "qwen3.5:9b", "claude_code": "qwen3.5:9b"}
URLS: dict[str, str] = {}  # Existing Bridge peers, e.g. {"codex": "http://127.0.0.1:8765"}.
COMMANDS: dict[str, str] = {}  # Manual executable paths, e.g. {"antigravity": "C:/tools/agy.exe"}.
PROFILES: dict[str, Path] = {}  # OpenCode/Claude Code profile JSON for non-Ollama providers.
OLLAMA_URL = "http://127.0.0.1:11434"
POEM_PROMPT = "Напиши короткое стихотворение на русском о чистом коде: ровно четыре строки."
DEFAULT_PORTS = {"antigravity": 8766, "codex": 8765, "opencode": 8767, "claude_code": 8768}


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
        Harness("codex", args.codex_url, args.codex_model, "medium"),
        Harness("opencode", args.opencode_url, args.opencode_model,
                "none" if not args.opencode_profile else None, "no_tools"),
        Harness("claude_code", args.claude_url, args.claude_model, tool_policy="no_tools"),
    )
    chosen = ({item.name for item in configured} if args.agents == "auto" else
              {name.strip() for name in args.agents.split(",") if name.strip()})
    unknown = chosen - {item.name for item in configured}
    if unknown or not chosen:
        raise ValueError(f"Unknown/empty --agents selection: {', '.join(sorted(unknown)) or args.agents}")
    return tuple(item for item in configured if item.name in chosen)


def selected_model(harness: Harness, info: dict | None) -> str:
    if not isinstance(info, dict):
        return harness.model
    models = info.get("capabilities", {}).get("models", [])
    identifiers = [item if isinstance(item, str) else item.get("id")
                   for item in models if isinstance(item, (str, dict))]
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
    """Part 1: call Bridge.info() and Bridge.ask() for a small poem."""
    result: dict = {"url": harness.url}
    info = None
    print(f"\n=== {harness.name}: модели и лимиты ===", flush=True)
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
        result["poem"] = {"text": answer.text, "state": answer.state,
                          "usage": answer.usage, "details": answer.details}
        _print_json(result["poem"])
    except Exception as exc:
        result["poem_error"] = f"{type(exc).__name__}: {exc}"
        print(result["poem_error"], file=sys.stderr, flush=True)
    return result


async def check_smells(harness: Harness, model: str, target: EvaluationTarget,
                       profile, output_dir: Path, *, batch_size: int,
                       use_session: bool) -> dict:
    """Part 2: compose the checker with an Agent Bridge transport provider."""
    print(f"\n=== {harness.name}: code smells ===", flush=True)
    provider = AgentBridgeProvider(harness.url, harness.name, tool_policy=harness.tool_policy)

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
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", choices=("all", "agents", "smells"), default="all")
    parser.add_argument("--agents", default=AGENTS)
    parser.add_argument("--target", type=Path, default=TARGET)
    parser.add_argument("--rules", default=RULES, help="Comma-separated IDs; default from RULES above")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--no-session", action="store_true")
    parser.add_argument("--no-auto-start", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    for name in ("antigravity", "codex", "opencode", "claude_code"):
        flag = "claude" if name == "claude_code" else name
        parser.add_argument(f"--{flag}-url", default=URLS.get(name))
        parser.add_argument(f"--{flag}-model", default=MODELS[name])
    parser.add_argument("--agy-command", default=COMMANDS.get("antigravity"))
    parser.add_argument("--opencode-command", default=COMMANDS.get("opencode"))
    parser.add_argument("--claude-command", default=COMMANDS.get("claude_code"))
    parser.add_argument("--opencode-profile", type=Path, default=PROFILES.get("opencode"))
    parser.add_argument("--claude-profile", type=Path, default=PROFILES.get("claude_code"))
    parser.add_argument("--ollama-url", default=OLLAMA_URL)
    args = parser.parse_args(raw)
    args.explicit_urls = {name for name in DEFAULT_PORTS
                          if name in URLS or f"--{'claude' if name == 'claude_code' else name}-url" in raw}
    for name, port in DEFAULT_PORTS.items():
        field = "claude_url" if name == "claude_code" else f"{name}_url"
        if getattr(args, field) is None:
            setattr(args, field, f"http://127.0.0.1:{port}")
    return args


async def run(args: argparse.Namespace) -> int:
    """Application workflow; the libraries below provide only reusable tools."""
    chosen = harnesses(args)
    commands = {name: command for name, command in (
        ("antigravity", args.agy_command), ("opencode", args.opencode_command),
        ("claude_code", args.claude_command)) if command}
    installed = discover_harnesses(commands)
    profiles = {"opencode": args.opencode_profile, "claude_code": args.claude_profile}
    for name, path in profiles.items():
        if path is not None:
            if not path.is_file():
                raise ValueError(f"{name} profile not found: {path}")
            installed.setdefault(name, "profile")

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

    if args.agents == "auto":
        available = []
        for harness in chosen:
            if harness.name in installed or harness.name in args.explicit_urls:
                available.append(harness)
                continue
            try:
                await client.capabilities(harness.url)
                available.append(harness)
            except Exception:
                pass
        chosen = tuple(available)
        print(f"[discovery] available: {', '.join(item.name for item in chosen) or 'none'}", flush=True)
    if not chosen:
        raise RuntimeError("No installed or running harnesses found; set AGENTS or COMMANDS/URLS")

    for harness in chosen:
        entry = results["harnesses"].setdefault(harness.name, {"url": harness.url})
        launch = HarnessLaunch(
            name=harness.name, url=harness.url,
            workspace=(args.target.parent if target is not None else Path.cwd()),
            model=harness.model, command=installed.get(harness.name),
            profile_path=profiles.get(harness.name), ollama_url=args.ollama_url,
            log_path=output_dir / f"{harness.name}.bridge.log",
            start_if_missing=not (args.no_auto_start or harness.name in args.explicit_urls),
        )
        try:
            async with connect_harness(launch, client=client) as connection:
                print(f"[discovery] {harness.name}: "
                      f"{'started temporary Bridge' if connection.started else 'existing Bridge'} "
                      f"at {connection.url}; log={connection.log_path}", flush=True)
                if args.part in {"all", "agents"}:
                    entry.update(await probe(harness, client))
                if args.part in {"all", "smells"}:
                    assert target is not None and profile is not None
                    print(f"\nПроверка {len(profile.rules)} правил: {harness.name}; отчёты: {output_dir}", flush=True)
                    info = entry.get("info")
                    if info is None:
                        try:
                            info = await client.info(harness.url)
                            entry["info"] = info
                        except Exception as exc:
                            entry["info_error"] = f"{type(exc).__name__}: {exc}"
                    model = entry.get("model") or selected_model(harness, info)
                    entry["model"] = model
                    entry["smells"] = await check_smells(
                        harness, model, target, profile, output_dir,
                        batch_size=args.batch_size, use_session=not args.no_session,
                    )
        except Exception as exc:
            entry["setup_error"] = f"{type(exc).__name__}: {exc}"
            print(entry["setup_error"], file=sys.stderr, flush=True)

    summary = output_dir / "summary.json"
    summary.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nСводка: {summary}", flush=True)
    failures = any(entry.get("setup_error") or entry.get("info_error") or entry.get("poem_error")
                   or entry.get("smells", {}).get("error")
                   or entry.get("smells", {}).get("summary", {}).get("errors", 0)
                   for entry in results["harnesses"].values())
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        print(f"Target: {args.target}", flush=True)
        print(f"Harnesses: {args.agents}; rules: {args.rules or 'all 80'}", flush=True)
        return asyncio.run(run(args))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
