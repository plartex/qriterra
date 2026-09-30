# Getting Started with Qriterra

[English](getting-started.md) | [Русский](ru/getting-started.md)

This guide walks you through setting up **Qriterra**, connecting it to **Agent Shuttle**, and running code-quality evaluations across all supported target types: code snippets, single files, and multi-file projects.

---

## 1. Prerequisites and Installation

Qriterra requires **Python 3.11** or newer. It depends on `agent-shuttle` (Agent Shuttle) for agent transport and `mcp` for the Model Context Protocol server.

> [!NOTE]
> Qriterra and Agent Shuttle reside in separate Git repositories. Neither package is published on PyPI yet; install Agent Shuttle first.

### Setting Up a Dedicated Virtual Environment

Create an isolated virtual environment and install both packages from GitHub:

#### On Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install "git+https://github.com/Plartex/agent-shuttle.git"
.\.venv\Scripts\python.exe -m pip install "git+https://github.com/Plartex/qriterra.git"
```

#### On Linux or macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install "git+https://github.com/Plartex/agent-shuttle.git"
pip install "git+https://github.com/Plartex/qriterra.git"
```

### Verifying the Installation

Verify that the CLI executable and MCP entry points are available:

```powershell
.\.venv\Scripts\qriterra.exe --help
.\.venv\Scripts\qriterra-mcp.exe --help
```

---

## 2. Connecting to Agent Shuttle

Qriterra acts as an orchestration client. To run actual evaluations, it communicates with an Agent Shuttle instance via the Agent-to-Agent (A2A) protocol over local HTTP.

Supported agent harnesses include:
- **Codex**: OpenAI models (`gpt-6-sol`, etc.) running through Codex CLI or SDK.
- **Antigravity**: Google models (`gemini-3.8-flash-medium`, `gemini-3.8-pro-high`, etc.) running via Antigravity CLI.
- **OpenCode**: Local models (such as `qwen3.5:9b` on Ollama) or custom OpenAI-compatible endpoints.
- **Claude Code**: Anthropic Claude models running through Claude Code CLI.

### Starting Persistent Bridge Instances

In separate terminals, you can launch long-running Bridge servers scoped to your target workspace:

```powershell
# Terminal 1: Codex harness on port 8765
agent-shuttle serve codex --workspace . --port 8765

# Terminal 2: Antigravity harness on port 8766
agent-shuttle serve antigravity --workspace . --port 8766

# Terminal 3: OpenCode harness on port 8767 (using a custom JSON profile)
agent-shuttle serve profile --profile path/to/opencode.profile.json --workspace . --port 8767
```

You can point Qriterra to these instances using `--agent-url` or standard environment variables:
- `BRIDGE_CODEX_URL=http://127.0.0.1:8765`
- `BRIDGE_ANTIGRAVITY_URL=http://127.0.0.1:8766`
- `BRIDGE_OPENCODE_URL=http://127.0.0.1:8767`
- `BRIDGE_CLAUDE_CODE_URL=http://127.0.0.1:8768`

---

## 3. Running Your First Evaluation

### Evaluating an In-Memory Snippet

Use `evaluate snippet` to check code logic directly from the command line or stdin:

```powershell
qriterra evaluate snippet `
  --code "def calculate_discount(price, customer):
    if customer.is_vip:
        if customer.orders_count > 50:
            if price > 1000:
                return price * 0.3
            return price * 0.2
        return price * 0.1
    return 0" `
  --language python `
  --provider agent-shuttle:codex `
  --agent-url http://127.0.0.1:8765 `
  --rules complex_conditional,deeply_nested_code
```

The evaluator runs with `tool_policy="no_tools"` in closed-book mode. The LLM receives the code directly in `REQUEST_DATA_JSON`.

### Evaluating a Single File

For single files on disk, Qriterra reads the file contents (up to 1 MB) and embeds them directly into the request:

```powershell
qriterra evaluate file src/checkout.py `
  --provider agent-shuttle:opencode `
  --agent-url http://127.0.0.1:8767 `
  --model qwen3.5:9b `
  --rules long_method,large_class `
  --debug
```

Because the file content is embedded into the prompt, the agent cannot and does not inspect neighboring files, imports, or external dependencies.

### Evaluating an Entire Project

In project mode, the agent receives the directory path and utilizes read and search tools to explore cross-file relationships:

```powershell
qriterra evaluate project path/to/project `
  --provider agent-shuttle:codex `
  --rules duplicate_code,cyclic_dependency `
  --max-project-seconds 900 `
  --json --output project.evaluation.json
```

> [!TIP]
> **Automatic Temporary Harness**: If you do not provide `--agent-url`, Qriterra automatically spawns a temporary Bridge server scoped to the project directory for the duration of the scan and shuts it down upon completion.

---

## 4. Configuring MCP (Model Context Protocol)

The MCP server allows AI assistants in editors like Claude Desktop, Cursor, or PyCharm to invoke the evaluation engine.

### Configuration Example

Add the `qriterra` entry to your MCP settings file (e.g., `claude_desktop_config.json` or `mcp_config.json`):

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

The MCP server exposes a single tool: `evaluate(target_type, target, profile="code_smells", ...)`.

---

## 5. Next Steps

- Explore the [Python API Reference](api.md) for programmatic integration into CI/CD pipelines.
- Understand multi-file analysis in [Project Evaluation & Semantics](project-evaluation.md).
- Learn about the 80 smells and translation guarantees in [Rule Catalog](rule-catalog.md).
- Review execution flow and batching in [Architecture](architecture.md).
- Diagnose common issues in [Troubleshooting](troubleshooting.md).
