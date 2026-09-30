# Contributing to Qriterra

[English](CONTRIBUTING.md) | [Русский](CONTRIBUTING.ru.md)

Thank you for your interest in contributing to **Qriterra**. This project adheres to test-driven development (TDD), comprehensive offline testing, and strict bilingual documentation parity.

---

## 1. Development Principles

1. **Test-Driven Development (TDD)**:
   - Write failing unit or contract tests before implementing bug fixes or new features.
   - Maintain high test coverage across all domain models, validation logic, prompt builders, and executors.
2. **Zero-Quota Offline Tests**:
   - The primary test suite must run completely offline without accessing live LLM endpoints, consuming API quotas, or requiring network credentials.
   - Use `FakeAgentProvider` to simulate agent completions, errors, and session interactions.
3. **Decoupled Architecture**:
   - Qriterra must remain independent of Agent Shuttle internals. Agent Shuttle is strictly an A2A transport client dependency.
   - Do not commit changes to the Agent Shuttle repository from this workspace.
4. **Bilingual Parity**:
   - English is canonical; Russian is a semantically faithful counterpart.
   - Any public documentation update in `docs/*.md` must have a corresponding, accurate counterpart under `docs/ru/*.md`.
   - Any change to `code_smells.min.json` must be reflected in `code_smells.en.json` with an updated `code_smells.en.sha256`.

---

## 2. Environment Setup

Clone the repository and set up a Python 3.11+ virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e "path/to/agent-shuttle" -e .
```

---

## 3. Running Tests

### Fast Offline Unit Suite

Run the full suite of unit tests, catalog validators, and provider resolution checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The offline test suite must pass without contacting a live harness.

### Opt-In Live Harness Verification

Live model tests require actual LLM credentials and active local agent harnesses. They are **never run automatically in CI** to avoid quota exhaustion and unpredictability.

You can run manual live checks using the standalone script in `examples/debug_harnesses.py`:

```powershell
# Check discovered harnesses with a short prompt
.\.venv\Scripts\python.exe .\examples\debug_harnesses.py --part agents --agents codex

# Check a single file against specific rules
.\.venv\Scripts\python.exe .\examples\debug_harnesses.py --part smells `
  --target .\agent_code_checker\service.py `
  --rules long_method,large_class `
  --agents codex
```

---

## 4. Documentation and Link Validation

Before submitting changes:
- Verify that all relative Markdown links in `README.md`, `README.ru.md`, and `docs/` point to valid existing files.
- Ensure all example commands use portable relative paths (avoid hardcoded user directories like `C:\Users\...` or `D:\...`).
- Verify that signatures and flags in documentation match `agent_code_checker/cli.py` and `agent_code_checker/mcp_server.py`; `qriterra/` provides the public compatibility facade.

---

## 5. Pull Request Checklist

- [ ] New functionality is covered by unit tests in `tests/`.
- [ ] Offline unit test suite passes: `python -m unittest discover -s tests -v`.
- [ ] No uncommitted scratch files or temporary debug runs (`examples/debug-runs/`) are staged.
- [ ] Both English and Russian documentation are updated with matching facts and valid cross-links.
