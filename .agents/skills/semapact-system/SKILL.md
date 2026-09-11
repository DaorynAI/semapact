---
name: semapact-system
description: Defines the core operating model, layered architecture boundaries, and change-driven workflow of SemaPact. Apply when refactoring components, implementing modules, or deciding package ownership.
---

# SemaPact System Model & Architecture Rules

SemaPact is a change-driven ODCS lifecycle-governance and production-assurance control plane.

## 1. Core workflow principles

- governed contract state is canonical ODCS;
- main state is not directly overwritten from presentation paths;
- contract identity is immutable once governed;
- release version changes only through explicit release flow;
- side effects are operation-scoped: APPLY, PUBLISH, and DEPLOY are distinct;
- execution success is not convergence proof.

## 2. Layered dependency direction

```text
interfaces (CLI/API/UI)
        ↓
application services
        ↓
domain packages and narrow ports
        ↑
platform/provider adapters
```

Dependencies must not point from domain packages into application or presentation code.

### A. Import/ingestion

Converts external structures into ODCS only when explicit import is requested. Importers are stateless/idempotent and contain no lifecycle or CI/CD policy.

### B. Governed contract model

ODCS is authoritative desired contract state. External observations do not become governed truth implicitly.

### C. Lifecycle/governance domain

Owns identity, lifecycle semantics, breaking/deprecation policy, change classification, and deterministic governance decisions.

### D. ContractOps domain

Owns deterministic release artifacts, authorization, APPLY/PUBLISH contracts, and exact artifact association. Later phases consume earlier artifacts; they do not rerun governance/version classification.

### E. Deployment/runtime domain

Owns provider-neutral DeploymentPlan/authorization/preview contracts and neutral runtime asset projection. Provider-native operations belong behind deployment adapters.

### F. Observation/reconciliation domain

Owns platform-neutral observed state and deterministic desired-vs-observed comparison. Reconciliation does not infer deployment causality or mutate runtime.

### G. Application layer

Location: `semapact/application/`.

- `application/models/` owns use-case result DTOs that compose domain artifacts;
- `application/services/` owns thin interface-independent orchestration;
- it may construct semantic context/configuration needed by a workflow;
- it must not own lifecycle/governance/version/deployment/reconciliation rules.

`semapact/services/` is compatibility-only and must not receive new implementation.

### H. Interfaces

Parse request values, validate/load external artifacts at the interface edge, call application/domain boundaries, render output, and map process outcomes. Interfaces do not own business rules.

### I. Platform adapters

Provider SDK/client and physical-platform translation live under `semapact/platforms/`. Concrete construction belongs in composition/application/platform code, never domain logic.

## 3. Model ownership rule

Do not organize models by the fact that they are "data". Organize them by meaning:

```text
ODCS governed contract                 → ODCS model
GovernanceDecision / ReleasePlan       → owning domain package
ReleasePlanningResult                  → application/models
Databricks table/statement representation → platforms/databricks
future deployment/history persistence  → its persistence/history boundary
```

Avoid generic root-level `schema`, `models`, or `data_models` dumping grounds.

## 4. Interface/port rule

Create interfaces only at genuine replaceable or side-effecting seams. Pure deterministic planners/value objects remain functions/models rather than acquiring ports for symmetry.

## 5. Change discipline

When moving ownership:

1. establish the new canonical import path;
2. migrate internal callers;
3. retain a thin compatibility re-export when public/backward compatibility matters;
4. add architecture/import tests so compatibility wrappers cannot become a second implementation;
5. update contributor-facing architecture rules in the same change.
