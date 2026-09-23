"""Source-checkout wrapper for the installed ``agent-code-checker-debug`` command."""

try:
    from agent_code_checker.debug_harnesses import main
except ModuleNotFoundError as exc:
    raise SystemExit(
        f"Missing {exc.name!r} in this Python environment. Install Agent Bridge and "
        "Agent Code Checker into the interpreter used by your IDE."
    ) from None


if __name__ == "__main__":
    raise SystemExit(main())
