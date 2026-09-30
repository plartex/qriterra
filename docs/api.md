# Python API Reference

[English](api.md) | [Русский](ru/api.md)

This document provides a comprehensive reference for the public Python API of **Qriterra**.

All public classes, models, and helper functions can be imported directly from the top-level package or `qriterra.providers`:

```python
from qriterra import (
    EvaluationService,
    EvaluationTarget,
    EvaluationProfile,
    EvaluationReport,
    EvaluationSummary,
    CheckResult,
    Evidence,
    ProjectFinding,
    ProjectCoverage,
    RuleDefinition,
    load_code_smells_profile,
    format_text_report,
    CatalogError,
)
from qriterra.providers import (
    AgentBridgeProvider,
    agent_bridge_provider_from_name,
    FakeAgentProvider,
)
```

---

## 1. Domain Models

### `EvaluationTarget`
Represents the entity being analyzed. Instances are immutable and created via factory methods.

```python
@dataclass(frozen=True)
class EvaluationTarget:
    kind: Literal["snippet", "file", "project"]
    content: str | None = None
    path: Path | None = None
    language: str | None = None
```

#### Factory Methods:
- **`EvaluationTarget.snippet(content: str, language: str | None = None) -> EvaluationTarget`**:
  Creates an in-memory snippet target. `content` must be a non-empty string.
- **`EvaluationTarget.file(path: str | Path) -> EvaluationTarget`**:
  Creates a single-file target. The path is immediately resolved to an absolute path and checked for existence. Inlined into prompts up to 1,000,000 bytes.
- **`EvaluationTarget.project(path: str | Path) -> EvaluationTarget`**:
  Creates a multi-file project directory target. Recursively validates that no symlinks escape the project root directory boundary.

#### Properties:
- `workspace: Path | None`: Returns `path.parent` for files, `path` for projects, or `None` for snippets.

---

### `RuleDefinition`
Represents an individual inspection rule loaded from the catalog.

```python
@dataclass(frozen=True)
class RuleDefinition:
    id: str
    title: str
    title_en: str
    severity: Literal["low", "medium", "high", "critical"]
    scope: str
    category_id: str
    summary: str
    definition: str
    symptoms: tuple[str, ...]
    detection_hints: dict[str, str]
    tags: tuple[str, ...] = ()
    executor: str = "llm"
    criterion_en: str | None = None
    full_english: bool = False
```

- `prompt_dict() -> dict[str, Any]`: Formats the rule data for transmission to the LLM agent, preserving metric thresholds and omitting verbose examples to conserve tokens.

---

### `Evidence`
Represents a concrete, line-level citation proving a code smell.

```python
@dataclass(frozen=True)
class Evidence:
    path: str | None
    start_line: int
    end_line: int
    excerpt: str
    reason: str
```
- `path`: `None` for snippets; relative POSIX path within the project for projects; matching file path for single files.
- `excerpt`: Exact code snippet from the source file. For project targets, the validator strictly verifies that `excerpt` exists on lines `start_line` through `end_line`.

---

### `ProjectFinding` and `ProjectCoverage`
Used in project evaluation (Schema 2.0).

```python
@dataclass(frozen=True)
class ProjectFinding:
    summary: str
    evidence: tuple[Evidence, ...]

@dataclass(frozen=True)
class ProjectCoverage:
    status: Literal["complete", "partial"]
    inspected_paths: tuple[str, ...]
    limitations: tuple[str, ...]
```
- `ProjectFinding` groups multiple related locations into one finding (e.g. `duplicate_code` spanning two files).
- `ProjectCoverage` captures the agent's self-reported inspection scope. `complete` requires non-empty `inspected_paths` and no `limitations`.

---

### `CheckResult`
The outcome of evaluating one specific rule against the target.

```python
@dataclass(frozen=True)
class CheckResult:
    rule_id: str
    status: Literal["passed", "failed", "skipped", "inconclusive", "error"]
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float | None = None
    evidence: tuple[Evidence, ...] = ()
    reason: str | None = None
    findings: tuple[ProjectFinding, ...] = ()
    coverage: ProjectCoverage | None = None
```

---

### `EvaluationSummary` and `EvaluationReport`

```python
@dataclass(frozen=True)
class EvaluationSummary:
    total: int
    passed: int
    failed: int
    skipped: int
    inconclusive: int
    errors: int
    findings: int
    quality_score: float | None
    assessment_coverage: float

@dataclass(frozen=True)
class EvaluationReport:
    run_id: str
    profile: EvaluationProfile
    target: EvaluationTarget
    provider: ProviderDescriptor
    summary: EvaluationSummary
    results: tuple[CheckResult, ...]
    warnings: tuple[str, ...]
    debug_trace: tuple[dict[str, Any], ...]
    schema_version: str = "1.0"
```
- `to_dict() -> dict[str, Any]`: Serializes report to dictionary (`schema_version` is `"2.0"` for projects, `"1.0"` for snippets and files).
- `to_json(*, indent: int | None = 2) -> str`: Serializes report to a formatted JSON string.

---

## 2. Services and Helpers

### `EvaluationService`
Main orchestration service.

```python
class EvaluationService:
    def __init__(self, provider: AgentProvider): ...

    async def evaluate(
        self,
        target: EvaluationTarget,
        profile: EvaluationProfile,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
        batch_size: int = 10,
        max_project_seconds: float = 1800,
        use_session: bool = True,
        debug: bool = False,
        on_debug_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> EvaluationReport: ...
```

#### Parameters:
- `target`: The `EvaluationTarget` to evaluate.
- `profile`: An `EvaluationProfile` loaded via `load_code_smells_profile`.
- `model`: Model identifier passed to the agent harness (e.g., `"gpt-6-sol"`).
- `reasoning_effort`: Reasoning effort level (`"low"`, `"medium"`, `"high"`).
- `batch_size`: Maximum rules sent per turn (default: `10`).
- `max_project_seconds`: Deadline in seconds for project evaluation (default: `1800.0`).
- `use_session`: If `True` (default), reuses one continuous Agent Shuttle session across batches.
- `debug`: If `True`, records all lifecycle events and token metrics into `report.debug_trace`.
- `on_debug_event`: Optional real-time callback invoked with each event dict.

---

### `load_code_smells_profile`

Loads and validates evaluation profiles.

```python
def load_code_smells_profile(
    catalog_path: str | Path | None = None,
    rule_ids: list[str] | tuple[str, ...] | None = None,
    *,
    prompt_language: str = "auto",
) -> EvaluationProfile: ...
```

- `catalog_path`: Optional path to a custom catalog JSON file. Defaults to bundled `code_smells.min.json`.
- `rule_ids`: Optional list of rule IDs to filter the profile (e.g. `["long_method"]`).
- `prompt_language`: `"auto"`, `"en"`, or `"ru"`.
  - `"auto"`: Uses English for the bundled catalog, Russian for custom catalogs.
  - `"en"`: English mirror (only available for the bundled catalog).
  - `"ru"`: Uses Russian catalog prose.

Raises `CatalogError` if the catalog file is invalid, missing required fields, or if an English mirror has mismatched hashes.

---

### `format_text_report`

```python
def format_text_report(report: EvaluationReport) -> str: ...
```
Formats an `EvaluationReport` into a test-runner-like summary string suitable for console display.

---

## 3. Providers

### `AgentBridgeProvider`

Connects to an Agent Shuttle A2A server.

```python
class AgentBridgeProvider:
    def __init__(
        self,
        peer_url: str,
        agent: str,
        timeout_seconds: float = 1800,
        *,
        tool_policy: str | None = None,
    ): ...
```
- `peer_url`: Base URL of the Agent Shuttle server (e.g. `"http://127.0.0.1:8765"`).
- `agent`: Harness identifier (e.g. `"codex"`, `"antigravity"`, `"opencode"`).
- `tool_policy`: Sandbox policy (`"no_tools"`, `"read_only"`, `"workspace_write"`, `"full_access"`).

### `agent_bridge_provider_from_name`

Helper to resolve providers from standard aliases or environment variables:

```python
def agent_bridge_provider_from_name(
    name: str,
    *,
    peer_url: str | None = None,
    tool_policy: str | None = None,
) -> AgentBridgeProvider: ...
```

Supported names: `codex`, `antigravity`, `opencode`, `claude_code`, or prefixed variants (`agent-shuttle:codex`). The former `agent-bridge:` prefix remains supported. Falls back to environment variables (`BRIDGE_CODEX_URL`, `BRIDGE_ANTIGRAVITY_URL`, etc.) if `peer_url` is omitted.

### `FakeAgentProvider`

Mock provider for offline unit testing without network or model costs.

```python
class FakeAgentProvider:
    def __init__(
        self,
        handler: Callable[[str, Path | None, str | None], str | ProviderResponse],
        capabilities: ProviderCapabilities | None = None,
    ): ...
```

---

## 4. Complete Programmatic Example

```python
import asyncio
from pathlib import Path
from qriterra import (
    EvaluationService,
    EvaluationTarget,
    format_text_report,
    load_code_smells_profile,
)
from qriterra.providers import AgentBridgeProvider

async def run_check():
    # 1. Connect to Codex harness
    provider = AgentBridgeProvider(
        peer_url="http://127.0.0.1:8765",
        agent="codex",
        tool_policy="read_only",
    )

    # 2. Load 2 specific rules in English
    profile = load_code_smells_profile(
        rule_ids=["long_method", "duplicate_code"],
        prompt_language="en",
    )

    # 3. Target a single file
    target = EvaluationTarget.file(Path("src/service.py"))

    # 4. Run evaluation with debug tracing
    service = EvaluationService(provider)
    report = await service.evaluate(
        target,
        profile,
        model="gpt-6-sol",
        reasoning_effort="medium",
        debug=True,
    )

    # 5. Output
    print(format_text_report(report))
    if report.summary.errors > 0:
        print("Evaluation finished with technical errors!")

if __name__ == "__main__":
    asyncio.run(run_check())
```
