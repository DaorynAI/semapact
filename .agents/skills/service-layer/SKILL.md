---
name: service-layer
description: Defines SemaPact's interface-independent application layer in `semapact/application/`. Use when CLI, UI, API, or CI workflows need typed use-case orchestration without owning domain rules.
---

# Application Service Layer

The application layer sits between interfaces and domain/provider ports.

```text
interfaces
    ↓
application/services
    ↓
domain functions + ports
    ↑
platform/provider adapters
```

## Package ownership

```text
semapact/application/
├── models/      # use-case/application result DTOs only
└── services/    # thin workflow orchestration only
```

Canonical domain artifacts remain in their owning packages. For example, `GovernanceDecision`, `ChangeSet`, `ReleasePlan`, `VersionResolution`, `DeploymentPlan`, `DeploymentPreview`, and `ReconciliationResult` do not move into application models.

Application result objects that aggregate those artifacts, such as `GovernanceProposal`, `GovernanceAnalysis`, `RuntimeReconciliation`, or `ReleasePlanningResult`, belong in `application/models`.

`semapact/services/` is a backward-compatibility import surface only. Do not add new models or behavior there.

## Responsibilities

- normalize interface request values into explicit domain inputs;
- create workflow-scoped context such as `ChangeContext` once;
- compose existing deterministic domain functions and narrow ports;
- select configuration needed by a use case;
- return typed domain artifacts or typed application result DTOs.

## Strict rules

- CLI/UI/API must not implement business rules;
- application services must not re-diff or reinterpret downstream governance/version/deployment/reconciliation artifacts;
- service modules must not define unrelated application DTOs inline; place reusable use-case results in `application/models`;
- services must not depend on presentation modules;
- do not use raw `dict[str, Any]` as an internal service contract when a formal model/dataclass exists;
- governance-semantic dates must not silently default from wall-clock time;
- optional provider SDK/client construction belongs in composition/platform code and remains lazy where possible.

## Model placement decision

Before creating a model, ask what it represents:

- governed business/domain fact → owning domain package;
- application use-case result/composition → `application/models`;
- provider/physical representation → provider package under `platforms`;
- persistence/history record → persistence/history owner when that boundary exists;
- presentation-only rendering state → interface package.

Do not create a root `schema`, `models`, or `data_models` directory simply to collect unrelated types.

## Preferred flow

1. interface collects request values;
2. application service resolves workflow context/configuration;
3. service delegates to existing domain rules/ports;
4. service returns typed results;
5. interface renders or maps the result to process outcomes.

## Forbidden

- duplicating lifecycle or breaking-change policy in application services;
- bypassing governance/authorization gates;
- provider-specific DDL or SDK logic inside application models/services;
- presentation imports from application code;
- new implementation under `semapact/services/`.

## Review checklist

1. Does each model have one semantic owner?
2. Is orchestration under `application/services`, separate from reusable result DTOs?
3. Do interfaces only parse/render/delegate?
4. Does the service reuse one resolved context throughout a workflow?
5. Are domain rules delegated rather than duplicated?
6. Are optional provider dependencies still lazy?
7. Are compatibility imports wrappers rather than a second implementation?

Read also:
- [semapact-system](../../semapact-system/SKILL.md)
- [lifecycle-policy](../../lifecycle-policy/SKILL.md)
