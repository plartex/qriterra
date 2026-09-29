# Security Policy

[English](SECURITY.md) | [Русский](SECURITY.ru.md)

Agent Code Checker is designed to analyze software projects by orchestrating agentic AI models. Because this involves executing LLM prompts and interacting with local filesystems via Agent Bridge, understanding security boundaries and operational risks is essential.

---

## 1. Security Architecture and Threat Model

### Untrusted Code as Input (Prompt Injection Defense)

When evaluating code snippets, files, or repositories, **all target code is treated as untrusted data**.
- Source code, comments, strings, documentation, file names, and directory structures could potentially contain adversarial instructions (prompt injections) designed to subvert the evaluation instructions.
- The prompt generator encloses all inspected content within explicit `REQUEST_DATA_JSON` delimiters and includes defensive system instructions ordering the model to treat all codebase text strictly as data and never as execution commands.

---

## 2. Tool Policies and Permissions

Agent Code Checker enforces tool policies to restrict what capabilities the underlying agent harness can access:

| Policy | Capabilities | Intended Scope | Security Implications |
|---|---|---|---|
| `no_tools` | No tool calls permitted; closed-book evaluation. | `snippet`, `file` | Safest. The agent cannot touch the disk or run commands. |
| `read_only` | Read and search tools within the workspace. | `project` | Read-only inspection. The agent cannot modify source code. |
| `workspace_write` | Can create or modify files inside the workspace. | Specific workflows | Agent can alter files within the project root. |
| `full_access` | Unrestricted tool execution. | `project` (Antigravity) | Highest risk. |

### Operational Risk: Antigravity and `full_access`

> [!WARNING]
> **Antigravity CLI Sandbox Limitations**:
> The underlying Google Antigravity CLI does not currently enforce a restricted read-only execution sandbox when running in automated headless mode. Consequently, running project evaluations with Antigravity requires `--tool-policy full_access`.
>
> Although Agent Code Checker explicitly instructs the agent never to modify files or execute code, **this restriction is enforced solely at the prompt level, not by an operating-system sandbox**. When analyzing untrusted or third-party repositories with Antigravity, run in an isolated environment (such as a disposable virtual machine or container).

---

## 3. Local A2A Transport Security

Agent Code Checker communicates with Agent Bridge using the Agent-to-Agent (A2A) protocol over HTTP:

- **Localhost Binding**: Agent Bridge servers are designed to bind exclusively to `127.0.0.1` (loopback).
- **No Inherent Authentication**: By design, local A2A endpoints do not require authentication tokens or SSL certificates.
- **Exposure Risks**:
  - **Never** bind Agent Bridge to `0.0.0.0` or expose its listening ports (`8765`, `8766`, `8767`, `8768`) to external networks or the public internet.
  - On shared multi-user workstations, any user with local network access may be able to dispatch requests to an active Bridge server.

---

## 4. Reporting a Security Vulnerability

If you discover a security vulnerability or potential threat in Agent Code Checker:

- **Do NOT disclose the vulnerability publicly in public chat forums or social media.**
- Please report security concerns through **GitHub Security Advisories** on the repository page (under the "Security" tab -> "Report a vulnerability").
- If GitHub Security Advisories are unavailable, open a confidential issue or contact the repository maintainers directly through their official GitHub profiles.

We appreciate responsible disclosure and will investigate and address reported security issues promptly.
