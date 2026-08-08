---
name: defensive-coding
description: Defines the strict coding standards, exception handling, and typing rules for Coding Agents modifying SemaPact. Apply this skill whenever writing new logic, refactoring core pipelines, or debugging integration issues.
---

# Defensive Coding & Agent Directives

## 1. Exception Handling
- **NEVER use bare `except Exception:` blocks** unless at the absolute top-level entrypoint logging boundary (e.g., catching uncaught errors right before the process exits). If you must catch `Exception`, be sure to log it clearly.
- Always raise and catch domain-specific exceptions from the `semapact.exceptions` module:
  - `SemaPactError`: The base exception.
  - `ValidationError`: Raised when a contract fails governance or structure validation.
  - `MergeConflictError`: Raised by the merge engine when business and technical metadata fatally conflict.
  - `LifecycleError`: Raised for invalid promotion or deployment actions.
  - `StorageError`: Wraps Azure ADLS / file system / Unity Catalog connection errors.
- External DevOps systems and GitOps pipelines rely on these exceptions to properly classify failures.
- When wrapping third-party exceptions (like `urllib.error.URLError` or `json.JSONDecodeError`), pass the originating exception up using the `raise CustomError(...) from exc` syntax.

## 2. Typing & Pydantic
- All code MUST be fully statically typed using Python 3.11+ syntax (`|` union operators, `list[str]`, etc.).
- The `OpenDataContractStandard` Pydantic model must be used exclusively as the single source of truth across the architecture.
- Do NOT fall back to parsing or mutating configuration as raw `dict[str, Any]` inside core logic, parsers, or exporters. Avoid dictionary mappings unless strictly needed at the immediate edge/IO boundary.

## 3. Testing Policy
- Every new feature, logic update, or bug fix must be accompanied by relevant unit tests.
- **Strict Isolation:** When testing interactions with external APIs (like OpenAI for LLM enrichment) or external Cloud Storage (like Azure ADLS, Unity Catalog), you MUST heavily use `pytest-mock` or `unittest.mock.patch`.
- Do NOT allow the test suite to execute real HTTP requests, write to actual databases, or require unmocked credentials.

## 4. Upstream Adherence
- Stop and evaluate if upstream projects (e.g. `datacontract-cli`) already provide the feature you are implementing. Do not reinvent built-in validators, parsers, or linting processes.
