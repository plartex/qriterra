# Qriterra

[![Tests](https://github.com/Plartex/qriterra/actions/workflows/tests.yml/badge.svg)](https://github.com/Plartex/qriterra/actions/workflows/tests.yml)
[![MIT license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Architecture](https://img.shields.io/badge/architecture-LLM--first-brightgreen.svg)](docs/architecture.md)
[![Rule Catalog](https://img.shields.io/badge/rules-80%20smells-orange.svg)](docs/rule-catalog.md)
[![Language](https://img.shields.io/badge/docs-English%20%7C%20Русский-lightgrey.svg)](README.ru.md)

[English](README.md) | [Русский](README.ru.md)

**Qriterra** is the first step toward an extensible evaluation platform. The idea is to apply configurable checks to a target and return a clear, structured result backed by evidence.

The library supports three target scopes:
- **`snippet`**: In-memory code strings with an optional language hint.
- **`file`**: Single files on disk (inlined up to 1 MB for tool-free, closed-book inspection).
- **`project`**: Multi-file repository directories investigated interactively by agentic harnesses using search and file-reading tools.

---

## Agent Shuttle as a Dependency

Qriterra is housed in an independent Git repository and does not contain agent execution harnesses. Instead, it relies on [**Agent Shuttle**](https://github.com/Plartex/agent-shuttle) (`agent-shuttle`) as a separate transport dependency.

- **Agent Shuttle** exposes standard Agent-to-Agent (A2A) HTTP endpoints to run underlying coding assistants: **Codex**, **Antigravity**, **OpenCode**, and **Claude Code**.
- **Qriterra** orchestrates the evaluation: it loads the 80-rule smell catalog, plans stable rule batches, manages agent sessions, validates strict structured JSON responses, verifies citations against real source lines, and calculates deterministic scores.
- Agent Shuttle knows nothing about code smells, batching, or scoring; Qriterra knows nothing about CLI subprocesses or provider-specific harness internals.

---

## Installation

> [!NOTE]
> These packages are not published on PyPI yet. Install Agent Shuttle first, then Qriterra, directly from their GitHub repositories.

Create a virtual environment (Python 3.11 or newer) and install both packages from GitHub:

```powershell
python -m venv .venv
# On Windows:
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install "git+https://github.com/Plartex/agent-shuttle.git"
.\.venv\Scripts\python.exe -m pip install "git+https://github.com/Plartex/qriterra.git"
```

On Linux or macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install "git+https://github.com/Plartex/agent-shuttle.git"
pip install "git+https://github.com/Plartex/qriterra.git"
```

Once installed, two console entry points become available in your virtual environment:
- `qriterra`: Command-line evaluation interface.
- `qriterra-mcp`: FastMCP stdio server providing the `evaluate` tool.

Existing integrations can continue to use the `agent_code_checker` import and the
`agent-code-checker` / `agent-code-checker-mcp` commands as compatibility aliases.

---

## Quickstart

### 1. Evaluate a Code Snippet

Pass code directly on the CLI using a local or remote Agent Shuttle endpoint:

```powershell
qriterra evaluate snippet `
  --code "def process(data): return [x * 2 for x in data if x > 0]" `
  --language python `
  --provider agent-shuttle:codex `
  --agent-url http://127.0.0.1:8765 `
  --rules long_method,complex_conditional
```

### 2. Evaluate a Single File

Single files are inlined into a closed-book, tool-free prompt:

```powershell
qriterra evaluate file src/service.py `
  --provider agent-shuttle:opencode `
  --agent-url http://127.0.0.1:8767 `
  --model qwen3.5:9b `
  --rules long_method,large_class `
  --json --output service.report.json
```

### 3. Evaluate a Project Directory

In project mode, the harness uses search and read tools within the workspace:

```powershell
qriterra evaluate project path/to/project `
  --provider agent-shuttle:codex `
  --rules duplicate_code,cyclic_dependency `
  --max-project-seconds 900 `
  --debug
```

If `--agent-url` is omitted for built-in harnesses (`codex`, `antigravity`, `opencode`, `claude_code`), the CLI temporarily launches an Agent Shuttle instance scoped to the target project directory. The old `agent-bridge:` provider prefix remains supported.

---

## Usage Modes

### Command Line Interface (CLI)

```text
qriterra evaluate <snippet|file|project> [target] [options]
```

Key CLI options:
- `--rules <id1,id2>`: Comma-separated rule IDs (defaults to all 80 profile rules).
- `--batch-size <N>`: Rules evaluated per turn (default: `10`).
- `--model <name>`: Model ID override (e.g. `gpt-6-sol`, `gemini-3.8-flash-medium`, `qwen3.5:9b`).
- `--reasoning-effort <effort>`: Reasoning depth (`low`, `medium`, `high`).
- `--tool-policy <policy>`: Execution sandbox permissions (`no_tools`, `read_only`, `workspace_write`, `full_access`).
- `--prompt-language <auto|en|ru>`: Language for LLM prompts (`auto` selects English for the bundled catalog).
- `--max-project-seconds <sec>`: Time budget for project analysis (default: `1800`).
- `--no-session`: Force independent requests per batch (disallowed for `project` evaluations).
- `--json`: Output full structured JSON report instead of formatted plain text.
- `--debug`: Stream real-time batch traces to `stderr` and include `debug_trace` in the report.
- `--output <path>`: Write the resulting report directly to disk.

### Python API

```python
import asyncio
from qriterra import (
    EvaluationService,
    EvaluationTarget,
    format_text_report,
    load_code_smells_profile,
)
from qriterra.providers import AgentBridgeProvider

async def main():
    # 1. Connect to an Agent Shuttle instance
    provider = AgentBridgeProvider(
        peer_url="http://127.0.0.1:8765",
        agent="codex",
        tool_policy="read_only",
    )

    # 2. Select rules and target
    profile = load_code_smells_profile(rule_ids=["long_method", "large_class"])
    target = EvaluationTarget.file("src/service.py")

    # 3. Execute evaluation
    service = EvaluationService(provider)
    report = await service.evaluate(target, profile, debug=True)

    # 4. Render results
    print(format_text_report(report))
    print(f"Quality Score: {report.summary.quality_score}%")

if __name__ == "__main__":
    asyncio.run(main())
```

### Model Context Protocol (MCP)

Qriterra provides an MCP server (`qriterra-mcp`) exposing the unified `evaluate` tool. Configure it in your editor or IDE (e.g., Claude Desktop, Codex, Cursor):

```json
{
  "mcpServers": {
    "qriterra": {
      "command": "path/to/.venv/Scripts/qriterra-mcp.exe",
      "args": [],
      "env": {
        "BRIDGE_CODEX_URL": "http://127.0.0.1:8765",
        "BRIDGE_ANTIGRAVITY_URL": "http://127.0.0.1:8766"
      }
    }
  }
}
```

---

## Workspace, Permissions, and Safety

| Target Scope | Execution Environment | Permitted Tool Policies |
|---|---|---|
| `snippet` | In-memory text | `no_tools` (default) |
| `file` | Inlined text (< 1 MB) | `no_tools` (default) |
| `project` | Multi-file directory | `read_only` (default for Codex, OpenCode, Claude Code), `workspace_write`, `full_access` (mandatory for Antigravity) |

> [!WARNING]
> **Antigravity and `full_access`**: The Antigravity CLI does not enforce a read-only filesystem sandbox in headless automation. Therefore, temporary project launches with Antigravity automatically use `full_access`. The evaluator explicitly prompts the agent not to modify files, but this restriction is enforced at the prompt level, not by an OS sandbox.

> [!IMPORTANT]
> **Local A2A Security**: Agent Shuttle endpoints communicate via unauthenticated HTTP on `127.0.0.1`. Never expose these ports to public networks. Inspected code is always treated as untrusted data to mitigate prompt-injection attempts.

---

## Quality Score and Evaluation Outcomes

Each evaluated rule receives exactly one of five outcomes:
- **`passed`**: Rule checked; smell was not detected.
- **`failed`**: Violation confirmed with verifiable source-code excerpts and line numbers.
- **`skipped`**: Incompatible target scope (e.g., checking circular dependencies on an isolated snippet).
- **`inconclusive`**: Potentially applicable, but available data or inspection budget was insufficient.
- **`error`**: Technical or protocol failure (e.g., malformed agent JSON, timeout, transport disruption).

### Deterministic Quality Score

The quality score is severity-weighted (`low = 1`, `medium = 2`, `high = 3`, `critical = 5`):

$$\text{Quality Score} = 100 \times \frac{\sum \text{weight}(\text{passed})}{\sum \text{weight}(\text{passed}) + \sum \text{weight}(\text{failed})}$$

**When is Quality Score `N/A` (`null`)?**
To prevent misleading scores:
1. If any rule encounters an **`error`**, the quality score is `null`.
2. In **`project`** evaluations, if any rule has **`partial`** coverage or ends in **`inconclusive`** / **`skipped`**, the score is `null`.
3. If no rules could be assessed (`passed_weight + failed_weight == 0`), the score is `null`.

**Assessment Coverage**:
$$\text{Assessment Coverage} = 100 \times \frac{\text{Assessed Rules}}{\text{Total Rules}}$$

---

## Testing

Run the full offline unit and integration test suite without consuming model quota:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The offline test suite runs with local fake providers, without model quota usage.

---

## Documentation

- [Getting Started Guide](docs/getting-started.md)
- [Python API Reference](docs/api.md)
- [Project Evaluation & Semantics](docs/project-evaluation.md)
- [Rule Catalog & Bilingual Parity](docs/rule-catalog.md)
- [Architecture & Protocols](docs/architecture.md)
- [Troubleshooting & Diagnostics](docs/troubleshooting.md)
- [Contributing Guidelines](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [Evaluation Framework Design](docs/evaluation-framework-design.md) (Original design RFC)
