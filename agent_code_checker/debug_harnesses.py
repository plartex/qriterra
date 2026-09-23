"""Probe four Agent Bridge harnesses, then evaluate one file with each of them.

Run ``agent-code-checker-debug --help`` for options. Installed harnesses are
discovered automatically; temporary local Bridge servers are stopped on exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent_bridge import BridgeClient, discover_harnesses
from . import EvaluationService, EvaluationTarget, load_code_smells_profile
from .providers import AgentBridgeProvider


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
        Harness("codex", args.codex_url, args.codex_model, "medium"),
        Harness("opencode", args.opencode_url, args.opencode_model or args.ollama_model,
                "none" if not args.opencode_profile else None, "no_tools"),
        Harness("claude_code", args.claude_url, args.claude_model or args.ollama_model,
                tool_policy="no_tools"),
    )
    chosen = ({item.name for item in configured} if args.agents == "auto" else
              {name.strip() for name in args.agents.split(",") if name.strip()})
    unknown = chosen - {item.name for item in configured}
    if unknown or not chosen:
        raise ValueError(f"Unknown/empty --agents selection: {', '.join(sorted(unknown)) or args.agents}")
    return tuple(item for item in configured if item.name in chosen)


def _command_overrides(args: argparse.Namespace) -> dict[str, str]:
    return {name: command for name, command in (
        ("antigravity", args.agy_command), ("opencode", args.opencode_command),
        ("claude_code", args.claude_command),
    ) if command}


def _verify_peer(harness: Harness, info: dict) -> None:
    expected = {"codex": {"codex_app_server"},
                "antigravity": {"agy_cli", "antigravity_sdk"},
                "opencode": {"opencode"}, "claude_code": {"claude_code"}}[harness.name]
    backend = info.get("backend")
    if backend is not None and backend not in expected:
        raise ValueError(f"{harness.url} serves backend {backend!r}, not {harness.name!r}")


@asynccontextmanager
async def ready_harness(harness: Harness, args: argparse.Namespace, client: BridgeClient,
                        output_dir: Path, installed: dict[str, str]):
    """Reuse a matching peer or own a temporary local server for this run."""
    url_name = harness.name if harness.name != "claude_code" else "claude"
    explicit_url = url_name in args.explicit_urls
    try:
        info = await client.capabilities(harness.url)
        _verify_peer(harness, info)
        print(f"[discovery] {harness.name}: existing Bridge at {harness.url}", flush=True)
        yield harness
        return
    except ValueError:
        raise
    except Exception as exc:
        if explicit_url or args.no_auto_start:
            raise RuntimeError(f"{harness.name}: Bridge at {harness.url} unavailable: {exc}") from exc
    command = installed.get(harness.name)
    if command is None and not (args.opencode_profile if harness.name == "opencode" else
                                args.claude_profile if harness.name == "claude_code" else None):
        raise RuntimeError(f"{harness.name}: harness not installed; specify its command or a Bridge URL")
    port = int(harness.url.rsplit(":", 1)[1])
    workspace = (args.target.parent if args.target else Path.cwd()).resolve()
    profile_path = (args.opencode_profile if harness.name == "opencode" else
                    args.claude_profile if harness.name == "claude_code" else None)
    with tempfile.TemporaryDirectory(prefix="agent-bridge-debug-") as temp_dir:
        if harness.name in {"opencode", "claude_code"} and profile_path is None:
            profile_path = Path(temp_dir) / "profile.json"
            profile = {
                "id": harness.name, "runtime": harness.name, "provider": "ollama",
                "workspace": str(workspace), "endpoint": args.ollama_url,
                "default_model": harness.model, "allowed_models": [harness.model],
                "runtime_command": command, "max_tool_policy": "no_tools",
            }
            if harness.name == "opencode":
                profile["reasoning_efforts"] = ["none"]
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
        argv = [sys.executable, "-m", "agent_bridge.cli", "serve",
                "profile" if profile_path else harness.name,
                "--port", str(port), "--workspace", str(workspace)]
        if profile_path:
            argv += ["--profile", str(profile_path)]
        if harness.name == "antigravity":
            argv += ["--agy-command", command]
        log_path = output_dir / f"{harness.name}.bridge.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, cwd=workspace)
            print(f"[discovery] {harness.name}: started temporary Bridge pid={process.pid}; log={log_path}", flush=True)
            try:
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError(f"{harness.name}: Bridge exited with code {process.returncode}; see {log_path}")
                    try:
                        info = await client.capabilities(harness.url)
                        _verify_peer(harness, info)
                        break
                    except RuntimeError:
                        raise
                    except Exception:
                        await asyncio.sleep(0.5)
                else:
                    raise TimeoutError(f"{harness.name}: Bridge did not start; see {log_path}")
                yield harness
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        await asyncio.to_thread(process.wait, timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        await asyncio.to_thread(process.wait)
                print(f"[discovery] {harness.name}: temporary Bridge stopped", flush=True)


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
    parser.add_argument("--agents", default="auto",
                        help="auto (installed harnesses) or comma-separated harness names")
    parser.add_argument("--target", type=Path,
                        help="File to check; required for --part all or smells")
    parser.add_argument("--rules", help="Comma-separated smell IDs; default: all 80 rules")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--no-session", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("debug-runs"))
    parser.add_argument("--codex-url", default=None)
    parser.add_argument("--antigravity-url", default=None)
    parser.add_argument("--opencode-url", default=None)
    parser.add_argument("--claude-url", default=None)
    parser.add_argument("--agy-command", help="Override discovered Antigravity CLI")
    parser.add_argument("--opencode-command", help="Override discovered OpenCode executable")
    parser.add_argument("--claude-command", help="Override discovered Claude Code executable")
    parser.add_argument("--opencode-profile", type=Path, help="Existing Bridge profile for another provider")
    parser.add_argument("--claude-profile", type=Path, help="Existing Bridge profile for another provider")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--no-auto-start", action="store_true")
    parser.add_argument("--antigravity-model", default="gemini-3.8-flash-medium")
    parser.add_argument("--codex-model", default="gpt-6-sol")
    parser.add_argument("--ollama-model", default="qwen3.5:9b")
    parser.add_argument("--opencode-model", help="Override OpenCode model (including cloud profiles)")
    parser.add_argument("--claude-model", help="Override Claude Code model (including cloud profiles)")
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw_argv)
    for name, port in (("codex", 8765), ("antigravity", 8766),
                       ("opencode", 8767), ("claude", 8768)):
        if getattr(args, f"{name}_url") is None:
            setattr(args, f"{name}_url", f"http://127.0.0.1:{port}")
    args.explicit_urls = {name for name in ("codex", "antigravity", "opencode", "claude")
                          if f"--{name}-url" in raw_argv}
    return args


async def run(args: argparse.Namespace) -> int:
    chosen = harnesses(args)
    installed = discover_harnesses(_command_overrides(args))
    for name, profile_path in (("opencode", args.opencode_profile),
                               ("claude_code", args.claude_profile)):
        if profile_path is not None:
            if not profile_path.is_file():
                raise ValueError(f"{name} profile not found: {profile_path}")
            installed.setdefault(name, "profile")
    target = profile = None
    if args.part in {"all", "smells"}:
        if args.target is None:
            raise ValueError("--target FILE is required for the code-smells part")
        target = EvaluationTarget.file(args.target)
        rule_ids = [item.strip() for item in args.rules.split(",") if item.strip()] if args.rules else None
        profile = load_code_smells_profile(rule_ids=rule_ids)
        if args.batch_size < 1:
            raise ValueError("--batch-size must be positive")

    output_dir = args.output_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                                    + "-" + uuid4().hex[:6])
    output_dir.mkdir(parents=True, exist_ok=False)
    results: dict = {"target": str(args.target) if args.target else None,
                     "part": args.part, "harnesses": {}}
    client = BridgeClient()

    if args.agents == "auto":
        available = []
        for harness in chosen:
            if harness.name in installed:
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
        raise RuntimeError("No installed or running harnesses found; use --agents and a command or URL override")

    for harness in chosen:
        entry = results["harnesses"].setdefault(harness.name, {"url": harness.url})
        try:
            async with ready_harness(harness, args, client, output_dir, installed):
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
    failures = any(
        entry.get("setup_error") or entry.get("info_error") or entry.get("poem_error") or entry.get("smells", {}).get("error")
        or entry.get("smells", {}).get("summary", {}).get("errors", 0)
        for entry in results["harnesses"].values()
    )
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(run(parse_args(argv)))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
