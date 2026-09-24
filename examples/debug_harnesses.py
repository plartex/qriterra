"""One-click diagnostic: model info, poem, then code-smell checks.

Open this file in PyCharm and press Run. Edit TARGET/RULES/AGENTS below for
another project. CLI arguments supplied in PyCharm override these defaults.
The reusable libraries themselves contain no project-specific target path.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from agent_code_checker.debug_harnesses import main
except ModuleNotFoundError as exc:
    raise SystemExit(
        f"Missing {exc.name!r} in this Python environment. Select the checker .venv "
        "as the PyCharm interpreter, or install Agent Bridge and Agent Code Checker."
    ) from None


# Edit only these values to use the script with another project or model set.
TARGET = Path("examples/sample_target.py")
AGENTS = "auto"  # Or "codex", "antigravity", "opencode,claude_code", etc.
RULES = "long_method,large_class"  # Set to None for all 80 code-smell rules.
OUTPUT_DIR = Path(__file__).resolve().parent / "debug-runs"


def configured_args(extra: list[str] | None = None) -> list[str]:
    """Build runnable defaults; later CLI options override them."""
    args = ["--part", "all", "--agents", AGENTS, "--target", str(TARGET),
            "--output-dir", str(OUTPUT_DIR)]
    if RULES:
        args.extend(["--rules", RULES])
    return args + (extra or [])


if __name__ == "__main__":
    print(f"Target: {TARGET}", flush=True)
    print(f"Harnesses: {AGENTS}; rules: {RULES or 'all 80'}", flush=True)
    raise SystemExit(main(configured_args(sys.argv[1:])))
