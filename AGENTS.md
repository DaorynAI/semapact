# 🤖 SemaPact AI Agent Guidelines

SemaPact is an open-source, enterprise lifecycle-governance and production-assurance platform for Open Data Contracts (ODCS).

## 1. Architectural Alignment

SemaPact is change-driven, not CRUD. Main governed contracts are not edited blindly; lifecycle, release, authorization, deployment, and reconciliation remain separate boundaries.

- **Always read [`ARCHITECTURE.md`](./ARCHITECTURE.md)** before designing features, adding state, or moving code across packages.
- Preserve canonical dependency direction: interfaces → application → domain/ports; platform adapters implement external/provider boundaries.

### Package ownership rules

Place code by semantic ownership, not by whichever caller happens to use it:

- canonical domain artifacts and domain rules → their owning domain package (`governance/`, `contractops/`, `deployment/`, `reconciliation/`, `runtime/`, `lifecycle/`);
- application/use-case result DTOs that compose domain artifacts → `semapact/application/models/`;
- interface-independent workflow orchestration → `semapact/application/services/`;
- CLI/API/UI parsing and rendering → `semapact/interfaces/`;
- provider SDK/client mappings and physical platform behavior → `semapact/platforms/`;
- `semapact/services/` is compatibility-only. **Do not add new logic or models there.**

Do not create generic `schema/`, `models/`, or `data_models/` dumping grounds at the package root. A model belongs with its semantic owner. ODCS schema, domain artifacts, application DTOs, persistence records, and provider SDK representations are different concerns.

## 2. Load Your Skills

- Read [`.agents/README.md`](./.agents/README.md) at the start of a coding session.
- Load the task-specific `SKILL.md`, especially `semapact-system`, `service-layer`, `lifecycle-policy`, or UI/provider skills as applicable.

## 3. Core Principles

1. **Defensive Coding**: Fully type new code and fail closed where required evidence or authorization is incomplete.
2. **Configuration over ad-hoc environment reads**: Prefer `ConfigManager` for product configuration; environment variables are explicit overrides or CI/runtime inputs.
3. **Preserve canonical contracts**: Do not overwrite governed main contracts from interface code.
4. **One authority per rule**: Interfaces and application services must not reimplement lifecycle, governance, versioning, deployment translation, or reconciliation semantics.
5. **Exact artifacts cross side-effect boundaries**: Downstream phases consume the exact immutable artifacts produced upstream; do not silently reload mutable state and reinterpret it.

## 4. Agent Working Style

1. **Plan before code**: inspect ownership and dependency direction before editing.
2. **Keep it simple**: avoid speculative abstractions and duplicate façade layers.
3. **Verify**: add or update tests for behavior and architecture boundaries; run the relevant suite/CI.
4. **Surgical changes**: do not refactor unrelated areas. Remove only dead code introduced by your own change unless the task explicitly calls for broader cleanup.

## 5. Testing

- Domain behavior changes require deterministic unit tests.
- Application services should be tested with canonical models and fake/narrow ports rather than live providers.
- Interface tests should prove parsing, rendering, and process outcomes without duplicating domain assertions.
- When changing package ownership, add an architecture/import test so future agents do not regress the boundary.
- Keep minimal-install import safety: optional provider dependencies must remain lazy until that provider is actually composed.

## 6. Behavioral Guidelines

### Think before coding

Do not hide ambiguity. State assumptions and surface trade-offs before creating a new abstraction.

### Simplicity first

Implement the minimum structure that gives one clear owner for each responsibility. Do not introduce an interface for a pure deterministic function merely for symmetry.

### Goal-driven execution

Translate work into verifiable outcomes, for example:

```text
1. move application orchestration → imports and behavior tests pass
2. move application DTOs → module-ownership test passes
3. preserve compatibility imports → legacy import identity tests pass
4. update contributor rules → docs match the actual package tree
```

These rules are working when a contributor can tell where a new model or workflow belongs without inspecting every caller.
