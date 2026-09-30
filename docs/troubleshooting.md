# Troubleshooting and Diagnostics

[English](troubleshooting.md) | [Русский](ru/troubleshooting.md)

This guide covers real-time diagnostic tools, event traces, common error messages, and their solutions.

---

## 1. Real-Time Tracing with `--debug`

When running evaluations from the CLI or Python API, pass `--debug` (or `debug=True`) to stream real-time JSON events to `stderr` and embed the full audit trace into `report.debug_trace`:

```powershell
qriterra evaluate file src/service.py --provider agent-shuttle:codex --debug
```

### Event Lifecycle

| Event Name | Description |
|---|---|
| `run_started` | Initialized run parameters, total rules, planned batches, and timeout limits. |
| `session_opened` | Established a persistent A2A session (`session_id`). |
| `batch_started` | Started processing a batch (`batch_id`, `scope`, `rule_ids`). |
| `agent_request` | Sent prompt to the model (includes `attempt` and `prompt_bytes`). |
| `agent_waiting` | Emitted every 10 seconds while awaiting model generation (`waiting_seconds`). |
| `agent_response` | Received completion (includes `response_bytes` and token `usage` if supported). |
| `validated` | Structured JSON validated successfully. |
| `validation_failed` | JSON violated Schema 1.0 or 2.0; triggers a single self-repair turn. |
| `batch_finished` | Batch complete (records `duration_seconds` and status counts). |
| `batch_budget_exhausted` | Monotonic deadline exceeded; remaining rules marked `inconclusive`. |
| `session_closed` | Closed persistent A2A session. |
| `run_finished` | Overall execution finished (reports `usage_totals`, `agent_requests`, durations). |

---

## 2. Common Errors and Resolutions

### 1. `Bridge workspace ... does not match project ...`
- **Cause**: An existing Agent Shuttle server was launched in a different directory than the target project directory.
- **Fix**: Either start the Bridge server in the exact project directory using `--workspace <path>`, or omit `--agent-url` to let the CLI automatically launch a temporary server in the project folder.

### 2. `Antigravity project evaluation requires full_access`
- **Cause**: Project evaluation was attempted with Google Antigravity without granting `full_access`.
- **Fix**: The Antigravity CLI does not enforce a read-only filesystem sandbox in headless automation. Pass `--tool-policy full_access`:
  ```powershell
  qriterra evaluate project path/to/project `
    --provider agent-shuttle:antigravity --tool-policy full_access
  ```

### 3. `Project evaluation requires agent tools; no_tools cannot inspect the project`
- **Cause**: `--tool-policy no_tools` was specified for a project target.
- **Fix**: Project analysis requires file search and reading tools. Use `read_only` (default for Codex, OpenCode, Claude Code) or `full_access` (for Antigravity).

### 4. `Project evaluation requires one persistent agent session`
- **Cause**: `--no-session` was passed to a project evaluation.
- **Fix**: Multi-file project exploration requires conversational continuity across rule batches so the model maintains its mental map of the project. Remove `--no-session`.

### 5. `file target is ... bytes; the inline limit is 1000000 bytes`
- **Cause**: The target file exceeds 1 MB. Single-file evaluations inline source code directly into the prompt.
- **Fix**: Split the file, evaluate specific functions via `evaluate snippet`, or run a project evaluation scoped to the directory.

### 6. `project contains a symlink outside its boundary: ...`
- **Cause**: A symbolic link inside the target directory points to a location outside the repository root.
- **Fix**: Remove the escaping symlink or point the target to a higher-level directory containing both paths.

### 7. `Rule ... cannot pass with partial coverage`
- **Cause**: The model returned `status: "passed"` while self-reporting `coverage.status: "partial"`.
- **Explanation**: Qriterra rejects claiming a rule has passed if the project was only partially explored. The validator triggers a repair; if the model fails to correct it, the rule is marked `error`.

### 8. `Rule ... evidence excerpt does not match source lines`
- **Cause**: The model hallucinated code in `excerpt` that does not match the actual text on lines `start_line` to `end_line` of the cited file.
- **Explanation**: The validator physically inspects the file on disk. A single repair prompt is automatically sent to the model to correct the line numbers or excerpt.

### 9. `English prompt profile is stale; regenerate it from the current catalog`
- **Cause**: `code_smells.min.json` was edited without updating `code_smells.en.json` and `code_smells.en.sha256`.
- **Fix**: Re-run the translation generator:
  ```powershell
  python scripts/translate_catalog.py
  ```

---

## 3. Why is Quality Score Reported as `N/A` (`null`)?

The `quality_score` metric represents confidence in assessed quality. It is intentionally suppressed (`null`) whenever the evaluation is incomplete or compromised:
1. **Any Technical Error**: If `report.summary.errors > 0`, the score is `null`.
2. **Partial Project Coverage**: If any rule in a project scan reports `coverage.status: "partial"`, the score is `null`.
3. **Unresolved Inconclusive / Skipped Checks**: In project mode, every rule must achieve either `passed` or `failed` with complete coverage for a quality score to be computed.
4. **No Assessed Rules**: If all selected rules were skipped or failed technically, the score is `null`.

When `quality_score` is `N/A`, rely on `assessment_coverage` and inspect the **Unresolved checks** section in the report.

---

## 4. Token Usage Reporting

When inspecting `report.debug_trace` or CLI stderr:
- **Codex and Antigravity**: Real token usage (input, output, cache reads) is returned via Agent Shuttle and aggregated under `usage_totals`.
- **Local Ollama (OpenCode)**: Local Ollama profiles do not report token quota (`usage.available=false`). Token counts in debug events will show as `null`.
