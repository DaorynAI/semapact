# Contributing to SemaPact

Thanks for contributing to SemaPact.

## Development setup

SemaPact uses Python 3.11+ and `uv`.

```bash
uv sync --all-extras --group dev
uv run pytest
uvx ruff check . --select E9,F63,F7,F82
uv build
```

## Architecture boundaries

SemaPact is a change-driven governance system, not a CRUD layer. Keep responsibilities separated:

- importers translate external metadata into canonical contract inputs; they must not own lifecycle or CI/CD policy
- lifecycle and governance code owns deterministic change analysis, policy evaluation, version classification, and governed decisions
- callers must consume the canonical governance decision instead of independently re-interpreting validation, breaking changes, or policy
- runtime integrations should provide observed state without redefining governance semantics
- side-effecting operations must respect the centralized governance gate

When changing governance behavior, prefer one canonical calculation that downstream components consume over duplicated derivations.

## Pull requests

Keep changes small and explicit. A pull request should explain:

- what behavior changes
- why the change belongs in that architectural layer
- what tests cover the behavior
- whether the change affects compatibility, lifecycle policy, or release behavior

Use Conventional Commit-style titles where practical, for example `feat:`, `fix:`, `docs:`, `ci:`, or `refactor:`. Release versioning is intentionally triggered manually by maintainers.

## Testing

Add or update tests for behavior changes. Governance and lifecycle changes should test both allowed and prohibited paths where relevant.

Do not weaken deterministic checks solely to make a test pass; fix the model, policy, or fixture that is actually incorrect.
