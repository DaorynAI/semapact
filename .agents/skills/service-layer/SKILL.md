---
name: service-layer
description: Defines the UI-independent SemaPact application service layer in `semapact/services/`. Use when interfaces such as CLI, UI, or API need to translate request inputs into domain context and delegate contract loading, draft management, validation, permissions, governance, observation, or reconciliation orchestration without owning business rules.
---

# Service Layer

This is the application boundary between interfaces and system logic.

------------------------------------------------
RESPONSIBILITIES

- normalize interface request values into formal domain inputs
- own workflow-scoped context construction such as `ChangeContext`
- load main contracts and manage drafts where applicable
- enforce permissions where applicable
- validate contracts through shared core components
- delegate governance analysis to lifecycle/governance components
- coordinate read-only observation/reconciliation workflows without reimplementing domain logic

------------------------------------------------
STRICT RULES

- CLI, UI, and API layers must NOT implement business logic
- interfaces must NOT construct or regenerate governance-semantic context directly
- service must NOT depend on presentation modules
- service methods should accept and return `OpenDataContractStandard`, formal Pydantic models, or formal dataclasses
- do NOT fall back to raw `dict[str, Any]` merely to accommodate an interface
- governance-semantic dates must not silently default from wall-clock time

------------------------------------------------
ALLOWED DEPENDENCIES

- `semapact.core`
- `semapact.governance`
- `semapact.lifecycle`
- `semapact.observation`
- `semapact.platforms`
- `semapact.reconciliation`
- `semapact.utils`

------------------------------------------------
CURRENT API

Governance:
- `GovernanceService.create_context(effective_date)`
- `GovernanceService.evaluate(base, candidate, effective_date=...)`
- `GovernanceService.merge_and_evaluate(source, governed, effective_date=...)`

Runtime assurance:
- `ReconciliationService.reconcile_databricks_table(...)`

Future draft/application services may expose:
- `list_contracts(user)`
- `get_contract(contract_id)`
- `get_draft(contract_id, user)`
- `save_draft(contract, user)`
- `promote_draft(contract_id, user)`

------------------------------------------------
IMPLEMENTATION GUIDANCE

Keep services thin.

Preferred flow:

1. receive already-collected interface request values
2. normalize those values into explicit domain inputs
3. delegate validation, merge, lifecycle, governance, observation, and reconciliation rules to their owning layers
4. return typed service results

For deterministic governance context:

```text
interface request
    ↓
GovernanceService creates ChangeContext once
    ↓
merge / evaluator consume the same context
```

For runtime assurance:

```text
interface request
    ↓
ReconciliationService coordinates load + observe + reconcile + classify
    ↓
interface formats the typed result
```

------------------------------------------------
FORBIDDEN

- duplicating lifecycle or breaking-change policy in services
- duplicating observation, reconciliation, reason-code, or drift-status logic in services
- bypassing governance gates
- resolving governance-semantic dates from `date.today()` / `datetime.now()` inside lower layers
- importing presentation frameworks from services
- overwriting canonical main contracts directly from an interface path
- mutating runtime state from read-side reconciliation workflows

------------------------------------------------
REVIEW CHECKLIST

1. Is the service independent of CLI/UI/API implementation details?
2. Does the interface pass request values rather than constructing domain context itself?
3. Does the service delegate lifecycle, governance, observation, and reconciliation rules instead of duplicating them?
4. Is one resolved context reused throughout a single workflow?
5. Are existing semantic dates preserved instead of overwritten?
6. Are operational timestamps kept separate from governance context?
7. Are runtime assurance workflows read-only unless an explicit write-side operation exists?

------------------------------------------------
Read these first-class Agent Skills when needed:

- [semapact-system](../../semapact-system/SKILL.md) for system architecture rules
- [lifecycle-policy](../../lifecycle-policy/SKILL.md) for contract lifecycle and deprecation logic
