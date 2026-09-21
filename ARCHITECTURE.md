# SemaPact Architecture

## Purpose

SemaPact is an ODCS-first, change-driven contract governance and production-assurance control plane. It separates governed contract semantics, formal release publication, runtime deployment, and runtime verification so each concern has one authoritative owner.

The canonical product flow has two paths after governance:

```text
ODCS base + candidate
        ↓
lifecycle / governance
        ↓
GovernanceDecision
        ├──────────────────────────────────────────────┐
        │ candidate deployment                         │ formal release
        │                                              │
        ↓                                              ↓
DeploymentSourceSnapshot(candidate)                ChangeSet
        ↓                                              ↓
DeploymentPlan                                     ReleasePlan
        ↓                                              ↓
CI-time DeploymentPreview                          VersionResolution
        ↓                                              ↓
DeploymentBundle                                   ReleaseSnapshot
        │                                              ↓
        │                                          ReleaseBundle
        │                                              ↓
        │                                      PUBLISH approval
        │                                        when REVIEW
        │                                              ↓
        │                                          ContractRelease
        │                                              ↓
        │                               DeploymentSourceSnapshot(contract_release)
        │                                              ↓
        │                                        DeploymentPlan
        │                                              ↓
        │                                  CI-time DeploymentPreview
        │                                              ↓
        └───────────────────────┬──────────────DeploymentBundle
                                ↓
                    protected CD execution context
                                ↓
                     fresh runtime observation
                                ↓
                     fresh DeploymentPreview
                                ↓
                              apply
                                ↓
                    observation / reconciliation
                                ↓
                 IN_SYNC / DRIFT / INDETERMINATE
```

Later phases consume exact immutable artifacts from earlier phases. They do not re-run governance, version selection, approval semantics, or release identity.

Formal release approval protects PUBLISH. Runtime deployment permission belongs to the surrounding protected CI/CD execution context. A `ContractRelease` is release provenance, not DEPLOY authorization.

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
- `semapact/approval/` — immutable structured review evidence;
- `semapact/contractops/` — `ChangeSet`, `ReleasePlan`, `VersionResolution`, `ReleaseSnapshot`, publication authorization, and `ContractRelease`;
- `semapact/deployment/` — `DeploymentSourceSnapshot`, provider-neutral `DeploymentPlan`, `DeploymentPreview`, provenance validation, and adapter contracts;
- `semapact/runtime/` — provider-neutral governed runtime asset projection;
- `semapact/observation/` — provider-neutral point-in-time runtime state;
- `semapact/reconciliation/` — desired-vs-observed comparison and `RuntimeDriftStatus`;
- `semapact/history/` — storage-neutral typed governance and operational-history ports/models.

A domain artifact does not move into the application or persistence layer merely because an application service returns it or a backend stores it.

### Application layer

Location:

```text
semapact/application/
├── models/
└── services/
```

`application/services/` owns thin, interface-independent use-case orchestration. It may resolve configuration and compose existing domain functions or ports, but it must not reimplement domain policy.

`application/models/` owns typed use-case results that aggregate canonical domain artifacts. Examples include:

- `GovernanceAnalysis`;
- `GovernanceProposal`;
- `RuntimeReconciliation`;
- `ReleasePlanningResult`;
- deployment workflow result DTOs.

These are application DTOs, not new governance, release, deployment, or reconciliation authorities.

### Interfaces

`semapact/interfaces/` owns argument parsing, loading input artifacts at the interface edge, rendering, and process-outcome mapping. Interfaces delegate to application/domain boundaries and must not independently calculate governance, versions, deployment plans, or reconciliation results.

### History persistence

Git is the low-frequency governance ledger for facts such as `ApprovalRecord` and `ContractRelease`. It is not the CI/CD artifact transport and not an operational telemetry database.

Operational deployment telemetry is disabled by default and can be configured through typed `history.operational` settings with SQLite or Delta backends. High-frequency deployment/reconciliation events are never written to Git by the canonical workflow.

### Platform adapters

`semapact/platforms/` owns provider SDK/client integration and physical-platform translation. Databricks DDL generation/execution and Unity Catalog tag projection are provider behavior; they do not belong in ContractOps or application DTOs.

### Import/export and integration workflows

- `semapact/importers/` projects explicitly imported external metadata into ODCS and contains no lifecycle policy;
- runtime observation evidence is not an importer source of canonical ODCS semantics; evidence-assisted bootstrap or enrichment must produce an explicit proposal/candidate for normal governance rather than mutate a governed contract;
- `semapact/exporters/` and `quality/` are read-only projections;
- `semapact/devops/` contains Git/CI integration helpers only and must not become a second canonical release implementation.

SemaPact is treated as a greenfield architecture. Superseded package aliases, artifact schemas, and compatibility workflows are removed rather than retained as parallel public surfaces.

## Model Placement Rule

Do not create a generic root `schema/`, `models/`, or `data_models/` directory to collect unrelated objects. Decide placement from semantic ownership:

| What the object represents | Owner |
| --- | --- |
| governed ODCS contract | ODCS model |
| governed contract revision identity/provenance | `semapact/revision/` |
| structured review evidence | `semapact/approval/` |
| release artifact | `semapact/contractops/` or release application DTO owner |
| deployment source/plan/preview artifact | `semapact/deployment/` |
| application/use-case aggregate result | `application/models/` |
| application orchestration | `application/services/` |
| storage-neutral persistence/query capability | `semapact/history/` |
| provider/SDK/physical representation | `platforms/<provider>/` |
| presentation-only rendering state | `interfaces/` |

The fact that every object is “data” is not a useful architectural boundary.

## Canonical Contract Model

SemaPact reuses `OpenDataContractStandard` as the canonical logical contract model. It must not create a second contract representation merely to support governance, revision history, persistence, or deployment.

Domain artifacts may reference or serialize the canonical ODCS model while adding only semantics owned by that domain. Canonical JSON may be derived for deterministic hashing, persistence, or transport; that serialization is not a second logical contract model.

## Governed Identity

For current governance semantics:

```text
schema identity   = lowercase(schema.name)
property identity = lowercase(schema.name) + lowercase(property.name)
```

`physicalName` is a deployment/runtime binding hint and never replaces governed logical identity.

## Lifecycle and Governance

Lifecycle/governance is the sole authority for change meaning. Interfaces, application services, adapters, and exporters must not independently reinterpret those rules.

A business effective date is mutation context only, for operations that materialize dated lifecycle state such as deprecation. Pure governance evaluation, release assessment, repository classification, and deployment assessment are date-independent.

Governance produces one immutable `GovernanceDecision`. Downstream phases consume that decision and its projected artifacts rather than diffing again.

## Formal Release Boundary

Canonical formal release planning is:

```text
base + candidate + exact revision refs
        ↓
GovernanceDecision
        ↓
ChangeSet
        ↓
ReleasePlan
        ↓
VersionResolution
        ↓
ReleaseSnapshot
        ↓
ReleaseBundle
```

Version selection is separate from governance classification. SemaPact-managed and Git-managed authority both resolve through the canonical version-authority boundary.

For `REVIEW`, an exact `ApprovalRecord` must bind the PUBLISH operation, exact `ReleaseSnapshot`, and exact `ReleaseBundle` digest. The preferred CI/CD handoff is the approval artifact itself; Git retains the same fact for audit/conflict detection and fallback lookup.

Finalization creates one target-neutral `ContractRelease` and materializes the selected semantic version into the released ODCS snapshot. The same `ContractRelease` may subsequently be deployed to multiple targets without another version calculation.

Candidate deployment bypasses this formal release path entirely. It does not calculate a release version, create release approval, or write release history.

## Deployment Boundary

Deployment planning starts from one exact `DeploymentSourceSnapshot`:

```text
candidate contract + governance decision
        ↓
DeploymentSourceSnapshot(source_kind=candidate)

or

ContractRelease
        ↓
DeploymentSourceSnapshot(source_kind=contract_release)
```

The source snapshot plus one exact target produces the deployment artifacts:

```text
DeploymentSourceSnapshot + DeploymentTarget
        ↓
DeploymentPlan
        ↓
fresh runtime observation + adapter preview
        ↓
DeploymentPreview
        ↓
DeploymentBundle
```

The CI-time preview is review evidence only; CD never blindly replays it. At execution time:

```text
protected CI/CD execution context
        +
exact DeploymentBundle
        ↓
validate source / plan / bundle integrity
        ↓
fresh runtime observation
        ↓
fresh DeploymentPreview
        ↓
apply supported operations
        ↓
fresh verification
        ↓
IN_SYNC / DRIFT / INDETERMINATE
```

SemaPact does not create a `DeploymentAuthorization` artifact. Runtime execution permission is delegated to the surrounding protected environment. The deployment domain owns provenance validation and runtime freshness, not IAM approval policy.

Candidate `BLOCK` decisions fail closed. Candidate `REVIEW` may still be deployed for validation/test because no formal publication occurs.

For Databricks, a finalized formal release that reaches `IN_SYNC` also projects reserved SemaPact release provenance tags to governed Unity Catalog tables. Candidate deployments do not publish formal release/version tags.

Provider execution success is not convergence proof.

## Observation and Reconciliation

Observation captures platform-neutral runtime evidence. It never mutates ODCS or invokes governance.

Lineage is time-varying runtime evidence, not canonical contract truth. Table/column lineage and query history may support provenance, impact analysis, reconciliation, or an explicit contract proposal, but observation must not directly project them into authoritative ODCS fields.

Reconciliation compares governed desired state with fresh observation and yields:

```text
IN_SYNC
DRIFT
INDETERMINATE
```

Deployment verification reuses this same reconciliation authority rather than introducing another convergence state machine.

## Application Services

Application services exist only when a use case genuinely coordinates multiple domain/port calls.

Rules:

- keep services thin;
- reusable application result DTOs live in `application/models`, not beside service implementation;
- do not pass untyped dictionaries internally when a canonical model exists;
- do not introduce ports around pure deterministic functions only for symmetry;
- provider construction is composition/platform behavior, not domain behavior;
- optional provider dependencies remain lazy so the base installation stays import-safe.

## Public Architecture Invariants

1. **Change-driven, not CRUD** — governed state evolves through explicit analysis, release, deployment, and reconciliation boundaries.
2. **One authority per rule** — lifecycle, governance, version selection, release publication, deployment translation, and reconciliation each have one canonical owner.
3. **Exact artifacts cross boundaries** — side effects consume exact immutable artifacts; mutable current state is not silently substituted.
4. **PUBLISH approval is not DEPLOY authority** — release approval protects formal publication; runtime mutation permission comes from the protected execution environment.
5. **Candidate deployment is not release** — it performs no release version calculation, approval persistence, or release-history write.
6. **Logical identity is stable** — `physicalName` binds runtime state but does not redefine governed identity.
7. **Execution is not convergence** — runtime state must be observed and reconciled independently.
8. **Interfaces stay thin** — CLI/API/UI parse, delegate, and render; they do not become a second business-logic implementation.
9. **Greenfield means one surface** — superseded aliases, legacy artifacts, and compatibility workflows are removed rather than maintained beside canonical paths.
10. **One canonical contract model** — SemaPact reuses ODCS rather than maintaining a parallel contract schema.
11. **Evidence is not contract truth** — runtime evidence may inform analysis or an explicit governed proposal, but it never silently mutates canonical ODCS semantics.
