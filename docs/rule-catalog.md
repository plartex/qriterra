# Rule Catalog and Bilingual Parity

[English](rule-catalog.md) | [Русский](ru/rule-catalog.md)

Qriterra comes with a comprehensive knowledge base of **80 code smells**. This document explains the catalog architecture, translation verification, prompt optimization, and how to select or extend rules.

---

## 1. Catalog Architecture and Files

The catalog files are bundled in the compatibility-backed implementation under `agent_code_checker/profiles/data/`:

| File | Purpose |
|---|---|
| `code_smells.min.json` | The canonical Russian knowledge base (80 smells across architectural, class, and method scopes). |
| `code_smells.en.json` | The full English mirror, providing exact translations of all natural language fields. |
| `code_smells.en.sha256` | SHA-256 checksum of `code_smells.min.json`. Guarantees that the English mirror is up to date. |
| `code_smells.schema.json` | JSON Schema validating catalog structure and required metadata. |

---

## 2. Bilingual Parity and Strict Verification

Maintaining exact semantic correspondence between the English and Russian catalogs is enforced at runtime by `_validate_translation_shape()` in `agent_code_checker/catalog.py`:

1. **Structural Identity**:
   - The English JSON object has the exact same hierarchy, keys, rule order, and array lengths as the Russian original.
   - All rule `id`s, category identifiers, severities, and scopes are identical.
2. **Untouched Code Examples**:
   - Code snippets inside `bad_example.code` and `good_example.code` are copied verbatim. No variables or syntax are translated, ensuring code behavior remains completely intact.
3. **Exact Numeric Metric Retention**:
   - Numeric thresholds in `detection_metrics` (e.g. `> 85% token match`, `LOC > 30`, `cyclomatic complexity > 10`) are preserved without alteration or rounding.
4. **Automated Translation Pipeline**:
   - The mirror is generated via `scripts/translate_catalog.py` using Google Antigravity. It records incremental checkpoints in `.runtime/catalog-translation/` and validates every field before committing.
   - If `code_smells.min.json` changes without regenerating `code_smells.en.json`, the loader rejects the stale translation with a `CatalogError`.

---

## 3. Rule Fields: Prompt Optimization vs. Catalog Depth

Each smell in the catalog defines rich educational and diagnostic metadata:
- `id`: Unique identifier (e.g. `long_method`, `duplicate_code`, `god_object`).
- `name` / `name_en`: Display titles.
- `severity`: `"low"`, `"medium"`, `"high"`, or `"critical"`.
- `level` (`scope`): Target granularity (`"method"`, `"class"`, `"file"`, `"subsystem"`, `"architecture"`).
- `summary` & `definition`: Core explanation of the design violation.
- `symptoms`: Observable code patterns indicating the smell.
- `detection_metrics`: Quantitative thresholds and heuristic indicators.
- `root_causes` & `impact`: Architectural context and technical debt implications.
- `refactoring_techniques`: Recommended remedial patterns.
- `bad_example` & `good_example`: Code demonstrations with explanatory notes.

### Prompt-Level Context Optimization

To minimize token usage and prevent the LLM from generating unsolicited refactorings, `RuleDefinition.prompt_dict()` excludes non-diagnostic fields from prompt payloads:

```text
Transmitted to LLM:
├── id
├── title (English or Russian based on prompt_language)
├── severity
├── scope
├── summary
├── definition
├── symptoms
└── detection_hints (detection_metrics)

Omitted from Prompts:
├── root_causes
├── impact
├── refactoring_techniques
├── bad_example
└── good_example
```

By excluding examples and refactoring instructions, the prompt remains focused strictly on **detection**, saving thousands of tokens per batch.

---

## 4. Language Selection (`--prompt-language`)

The `--prompt-language` CLI flag and Python parameter control which language is sent to the LLM:

- **`auto` (default)**:
  - If using the bundled catalog, automatically selects **`en`** (English mirror).
  - If using a custom catalog via `--catalog`, automatically selects **`ru`** (Russian).
- **`en`**:
  - Uses the verified English mirror.
  - Only valid for the bundled catalog. Specifying `en` with a custom catalog raises `CatalogError`.
- **`ru`**:
  - Uses the canonical Russian text directly from `code_smells.min.json`.

---

## 5. Filtering Rules and Custom Catalogs

### Selecting Specific Rules

By default, all 80 rules are evaluated. You can restrict the evaluation to specific rule IDs using `--rules`:

```powershell
qriterra evaluate file src/orders.py `
  --rules long_method,complex_conditional,primitive_obsession
```

In Python:

```python
profile = load_code_smells_profile(
    rule_ids=["long_method", "duplicate_code"],
    prompt_language="en",
)
```

If an unknown rule ID is passed, `load_code_smells_profile` raises `CatalogError` before any model calls are made.

### Supplying a Custom Catalog

You can point to your own JSON catalog file using `--catalog`:

```powershell
qriterra evaluate project path/to/repo `
  --catalog path/to/custom_rules.json `
  --prompt-language ru
```

Your custom catalog must match the structure of `code_smells.schema.json` and declare `meta.total_smells` equal to the number of entries in `smells`.
