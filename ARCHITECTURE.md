# SemaPact Architecture

## Purpose

SemaPact is an ODCS-first, change-driven contract governance and production-assurance control plane. It separates governed contract semantics, release authorization, runtime mutation, and runtime verification so each concern has one authoritative owner.

The canonical product flow is:

```text
ODCS base + candidate
        ↓
lifecycle / governance
        ↓
GovernanceDecision
        ↓
ChangeSet → ReleasePlan → VersionResolution
        ↓
ContractOpsAuthorization
        ↓
AppliedContractRelease
        ↓
DeploymentPlan → DeploymentAuthorization
        ↓
DeploymentAdapter
        ↓
runtime
        ↓
observation / reconciliation
```

Later phases consume exact artifacts from earlier phases. They do not re-run governance, lifecycle classification, version authority, or approval semantics.

## Dependency Direction

Application and domain boundaries follow this direction:

```text
interfaces (CLI / API / UI / CI)
        ↓
application services
        ↓
domain functions / models / ports
        ↑
platform and external-system adapters
```

Domain packages must not depend on `application` or `interfaces`. Provider-specific SDK/client construction stays outside domain logic.

## Package Ownership

### Domain packages

Domain models live with the rules that give them meaning:

- `semapact/lifecycle/` — canonical identity, lifecycle policy, merge/change semantics;
- `semapact/governance/` — `GovernanceDecision`, reason codes, centralized gate;
- `semapact/revision/` — immutable governed contract content identity and source-provenance links;
- `semapact/contractops/` — `ChangeSet`, `ReleasePlan`, `VersionResolution`, ContractOps authorization, APPLY/PUBLISH artifacts;
- `semapact/deployment/` — provider-neutral `DeploymentPlan`, `DeploymentPreview`, deployment authorization and adapter contract;
- `semapact/runtime/` — provider-neutral governed runtime asset projection;
- `semapact/observation/` — provider-neutral point-in-time runtime state;
- `semapact/reconciliation/` — desired-vs-observed comparison and `RuntimeDriftStatus`.

A domain artifact does not move into the application or persistence layer merely because an application service returns it or a history backend stores it.

### Application layer

Location:

```text
semapact/application/
├── models/
└── services/
```

`application/services/` owns thin, interface-independent use-case orchestration. It may resolve workflow context/configuration and compose existing domain functions or ports, but it must not reimplement domain policy.

`application/models/` owns typed use-case results that aggregate canonical domain artifacts. Examples include:

- `GovernanceAnalysis`;
- `GovernanceProposal`;
- `RuntimeReconciliation`;
- `ReleasePlanningResult`.

These are application DTOs, not new governance/release/deployment authorities.

### Compatibility package

`semapact/services/` is a backward-compatible import surface for the former package layout. It contains re-exports only and owns no models or business logic. New code must import from `semapact.application`.

### Interfaces

`semapact/interfaces/` owns parsing, loading input artifacts at the interface edge, rendering, and process-outcome mapping. Interfaces delegate to application/domain boundaries and must not independently calculate governance, version, deployment, or reconciliation results.

### History persistence

`semapact/history/` owns storage-neutral typed persistence/query ports and persistence errors. It stores canonical artifacts from their owning domains but does not redefine their models, identity formulas, or business semantics.

### Platform adapters

`semapact/platforms/` owns provider SDK/client integration and physical-platform translation. Databricks DDL generation/execution is provider behavior; it does not belong in ContractOps or application DTOs. Storage backend layout and physical persistence mechanics likewise belong to the corresponding platform adapter.

### Import/export and compatibility workflows

- `semapact/importers/` projects explicitly imported external metadata into ODCS and contains no lifecycle policy;
- `semapact/exporters/` and `quality/` are read-only projections;
- `semapact/devops/` and parts of `core/` contain stable compatibility workflows and must not become a second canonical ContractOps implementation.

## Model Placement Rule

Do not create a generic root `schema/`, `models/`, or `data_models/` directory to collect unrelated objects. Decide placement from semantic ownership:

| What the object represents | Owner |
| --- | --- |
| governed ODCS contract | ODCS model |
| governed contract revision identity/provenance | `semapact/revision/` |
| governance/release/deployment/reconciliation artifact | owning domain package |
| application/use-case aggregate result | `application/models/` |
| application orchestration | `application/services/` |
| storage-neutral history persistence/query capability | `semapact/history/` |
| provider/SDK/physical representation | `platforms/<provider>/` |
| presentation-only rendering state | `interfaces/` |

The fact that every object is “data” is not a useful architectural boundary.

## Canonical Contract Model

SemaPact reuses `OpenDataContractStandard` as the canonical logical contract model. It must not create a second contract representation merely to support governance, revision history, persistence, or deployment.

Domain artifacts may reference or wrap the canonical ODCS model while adding only semantics owned by that domain. For example, `ContractRevision` adds content identity around an exact `OpenDataContractStandard`; it does not duplicate `contract.id`, `contract.version`, schema fields, or a serialized contract copy as parallel logical fields.

Canonical JSON may be derived transiently for deterministic hashing, signatures, persistence, or transport. That serialization is not a second logical contract model.

## Governed Identity

For current governance semantics:

```text
schema identity   = lowercase(schema.name)
property identity = lowercase(schema.name) + lowercase(property.name)
```

`physicalName` is a deployment/runtime binding hint and never replaces governed logical identity.

## Lifecycle and Governance

Lifecycle/governance is the sole authority for change meaning. Active entities participate in governance; draft/deprecated entities are excluded where policy specifies; retired state is immutable. Interfaces, application services, adapters, and exporters must not independently reinterpret these rules.

Governance produces one immutable `GovernanceDecision`. Downstream phases consume that decision and its projected artifacts rather than diffing again.

## ContractOps Release Boundary

Canonical planning is:

```text
base + candidate + exact revision refs
        ↓
GovernanceDecision + ChangeSet
        ↓
ReleasePlan
        ↓
VersionResolution
```

Version selection is separate from governance classification. SemaPact-managed and Git-managed authority both resolve through the canonical version-authority boundary.

APPLY materializes the exact released ODCS snapshot only after matching authorization. PUBLISH publishes a released artifact and is distinct from DEPLOY.

## Deployment Boundary

Deployment planning starts from an exact `AppliedContractRelease`:

```text
AppliedContractRelease + DeploymentTarget
        ↓
DeploymentPlan
        ↓
fresh runtime observation + adapter preview
        ↓
DeploymentPreview
        ↓
exact plan + preview + DeploymentAuthorization
        ↓
DeploymentAdapter.execute(...)
```

`DeploymentPlan` stays provider-neutral. Provider-native CREATE/ALTER/NO_OP operations begin at the adapter boundary. Runtime mutation must fail closed when capability or evidence is insufficient.

Provider execution success is not convergence proof.

## Observation and Reconciliation

Observation captures platform-neutral runtime evidence. It never mutates ODCS or invokes governance.

Reconciliation compares governed desired state with fresh observation and yields the existing status vocabulary:

```text
IN_SYNC
DRIFT
INDETERMINATE
```

Deployment verification reuses this same reconciliation authority rather than introducing another convergence state machine.

## Application Services

Application services exist only when a use case genuinely coordinates multiple domain/port calls. Current examples include governance context construction, configured version authority, canonical release planning, runtime reconciliation orchestration, and deployment orchestration.

Rules:

- keep services thin;
- reusable application result DTOs live in `application/models`, not beside service implementation;
- do not pass untyped dictionaries internally when a canonical model exists;
- do not introduce ports around pure deterministic functions only for symmetry;
- provider construction is composition/platform behavior, not domain behavior;
- optional provider dependencies remain lazy so the base installation stays import-safe.

## Public Architecture Invariants

1. **Change-driven, not CRUD** — governed state evolves through explicit analysis/planning/authorization boundaries.
2. **One authority per rule** — lifecycle, governance, revision identity, version selection, deployment translation, and reconciliation each have one canonical owner.
3. **Exact artifacts cross boundaries** — side effects consume exact immutable artifacts; mutable current state is not silently substituted.
4. **Operation-scoped authorization** — APPLY, PUBLISH, and DEPLOY are distinct operations; authorization for one cannot authorize another.
5. **Logical identity is stable** — `physicalName` binds runtime state but does not redefine governed identity.
6. **Execution is not convergence** — runtime state must be observed and reconciled independently.
7. **Interfaces stay thin** — CLI/API/UI parse, delegate, and render; they do not become a second business-logic implementation.
8. **Compatibility is not ownership** — legacy import paths may re-export canonical implementations but must not accumulate new logic.
9. **One canonical contract model** — SemaPact reuses ODCS rather than maintaining a parallel contract schema.
