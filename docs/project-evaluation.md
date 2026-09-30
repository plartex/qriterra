# Project Evaluation and Multi-File Semantics

[English](project-evaluation.md) | [Русский](ru/project-evaluation.md)

Project evaluation (`EvaluationTarget.project`) is designed to inspect an entire codebase repository directory. Rather than relying on simple text inlining or static syntax trees, Qriterra grants an AI agent interactive search and reading tools within an isolated session to uncover complex, cross-module code smells.

---

## 1. How Project Evaluation Differs from Snippets and Files

| Aspect | `snippet` / `file` | `project` |
|---|---|---|
| **Context Delivery** | Inlined into the prompt text (< 1 MB) | Directory path passed; agent explores files using tools |
| **Agent Tools** | `tool_policy="no_tools"` (closed-book) | Read and search tools enabled (`read_only` or `full_access`) |
| **Response Schema** | Schema 1.0 (flat list of `evidence`) | Schema 2.0 (`findings` with multiple citations, `coverage`) |
| **Session Model** | Optional session reuse (`--no-session` allowed) | Exactly **one** persistent session required across all batches |
| **Coverage Requirement**| Implicitly complete for supplied code | Agent-reported `complete` or `partial` per rule |

---

## 2. Agent Exploration and Semantic Judgment

Traditional linters and copy-paste detectors (such as CPD or AST diffing) rely on lexical or syntactic token identity. In contrast, Qriterra performs **LLM-first semantic investigation**:

1. **Tool-Assisted Exploration**: The agent receives the root directory path and rule definitions. It executes read and search tools (e.g. grep, file outline, file read) to trace module boundaries, inheritance trees, and data flows.
2. **Semantic Understanding**: The agent identifies problems that syntax trees miss, such as:
   - **Semantic Duplication**: Two functions with entirely different variable names and algorithmic structures that solve the identical domain problem with identical edge-case logic.
   - **Cyclic Dependencies & Layer Leaks**: High-level business entities inadvertently importing low-level UI or database adapters.
   - **Interface Bloat & Shotgun Surgery**: Changes in one concept requiring ripple edits across disjoint modules.
3. **Numeric Hints as Guidance**: Detection metrics in the catalog (such as `token_similarity > 85%` or `cyclomatic_complexity > 10`) are sent to the model as evaluation guidance, not mechanical assertions. The agent applies engineering judgment.

---

## 3. Schema 2.0: Grouped Findings and Evidence Verification

In single-file evaluations (Schema 1.0), each violation points to an isolated file location. In project evaluations, a single violation often spans multiple files. Schema 2.0 accommodates this structure:

```json
{
  "schema_version": "2.0",
  "batch_id": "batch-0001",
  "results": [
    {
      "rule_id": "duplicate_code",
      "status": "failed",
      "confidence": 0.95,
      "findings": [
        {
          "summary": "Shared tax calculation logic duplicated across billing and cart checkout",
          "evidence": [
            {
              "path": "src/billing/invoice.py",
              "start_line": 42,
              "end_line": 56,
              "excerpt": "def calculate_state_tax(amount, state):\n    rates = {'NY': 0.08875, 'CA': 0.0725}\n    return amount * rates.get(state, 0.0)",
              "reason": "Primary tax calculation table and multiplier"
            },
            {
              "path": "src/cart/checkout.py",
              "start_line": 105,
              "end_line": 119,
              "excerpt": "def compute_taxes(subtotal, region):\n    lookup = {'NY': 0.08875, 'CA': 0.0725}\n    return subtotal * lookup.get(region, 0.0)",
              "reason": "Identical regional tax table reimplemented with renamed local variables"
            }
          ]
        }
      ],
      "coverage": {
        "status": "complete",
        "inspected_paths": [
          "src/billing/invoice.py",
          "src/cart/checkout.py",
          "src/common/pricing.py"
        ],
        "limitations": []
      }
    }
  ]
}
```

### Strict Source Excerpt Verification

To eliminate LLM hallucinations, Qriterra's response validator verifies every citation:
- `path` must resolve to an existing file strictly inside the project root (symlinks escaping the root are rejected).
- `start_line` and `end_line` must be within valid file boundaries.
- **`excerpt` must physically match** the actual lines of code read from disk on lines `[start_line, end_line]`. If the model invents code that does not exist at that location, the response is rejected and sent for retry repair.

---

## 4. Coverage Semantics: Complete vs. Partial

A critical design principle of the framework is that **an agent's self-reported coverage is not an objective guarantee of exhaustive analysis**. Therefore, strict rules govern coverage status:

### Complete Coverage
- `status: "complete"`
- Must provide a non-empty list of `inspected_paths`.
- `limitations` must be completely empty.
- A rule can only receive **`passed`** if coverage is `complete`.

### Partial Coverage
- `status: "partial"`
- `limitations` must contain explicit reasons why exploration was constrained (e.g. timeout budget, complex dynamic metaprogramming, uninspected subdirectories).
- **A rule with partial coverage CANNOT pass**: If the model claims `status: "passed"` with `coverage.status: "partial"`, the validator raises a protocol error.
- If the agent explored partially and found no smell, it must report **`inconclusive`** with a descriptive reason.
- A rule may be **`failed`** with partial coverage if a real, verified violation was found before the agent could inspect the rest of the project.

---

## 5. Session Requirements and Time Budgets

Project evaluations require continuous interaction with the codebase:
1. **Single Session (`use_session=True`)**:
   - The CLI and MCP server open a single session on the Agent Shuttle server.
   - All rule batches are evaluated within this conversation, allowing the model to leverage its mental map of the codebase.
   - `--no-session` is explicitly forbidden for project targets and raises an immediate `ValueError`.
2. **Workspace Verification**:
   - Before any model calls occur, Qriterra queries the Bridge server's identity. If the server's working directory does not match the canonical target project path, execution terminates immediately.
3. **Time Budget (`--max-project-seconds`)**:
   - Default: `1800` seconds (30 minutes).
   - If the monotonic runtime exceeds this limit during a batch, that batch and all subsequent batches terminate immediately.
   - The remaining rules are marked as **`inconclusive`** with the reason `"Project time budget of ...s exhausted"` and partial coverage.
   - Because incomplete coverage exists, the final `quality_score` becomes `null` (`N/A`).

---

## 6. Real-World Live Run Benchmarks and Token Costs

Full project scans explore extensive file contexts and consume substantial token quotas.

> [!WARNING]
> **Live Benchmark Example**:
> In a controlled benchmark with Google Antigravity evaluating **two files** against **one rule** (`duplicate_code`):
> - **Execution Time**: 173.5 seconds (~2.9 minutes).
> - **Token Consumption**: 205,154 total tokens.
>
> Running a complete scan of all 80 rules across a large repository will take significantly longer and consume millions of tokens.

### Best Practices for Project Scans:
1. **Target Specific Rules**: Use `--rules` to focus on architectural or multi-file smells:
   ```powershell
   qriterra evaluate project path/to/project `
     --rules duplicate_code,cyclic_dependency,shotgun_surgery `
     --max-project-seconds 600
   ```
2. **Monitor Debug Output**: Use `--debug` to inspect real-time progress, token consumption, and agent tool execution.
3. **Start with Subdirectories**: Point at specific subpackages or domain modules before initiating whole-repository audits.
