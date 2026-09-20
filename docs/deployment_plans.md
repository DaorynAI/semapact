# Deployment plans

SemaPact treats a released ODCS contract as governed desired state, not as an executable SQL, Terraform, or platform program.

The released contract is the authoritative artifact. SemaPact does **not** require a separate DDL build artifact before deployment. SQL and other provider-native commands are derived only after an exact released desired state is compared with an exact runtime target.

```text
Candidate contract or finalized ContractRelease
        = exact governed desired state
                +
ObservedPlatformState
        = point-in-time runtime state
                ↓
semantic runtime transition assessment
                ↓
provider-native operation compilation
                ↓
DeploymentPreview
```

This matters because one release may require different native operations in different environments. A missing table may require CREATE in one target, an additive ALTER in another, and NO_OP in a target that already satisfies the governed state. A pre-built DDL script cannot represent those three runtime states without becoming another mutable source of truth.

The deployment planning boundary is therefore:

```text
DeploymentSourceSnapshot
+ DeploymentTarget
        ↓
DeploymentPlan
        ↓
DeploymentService
        ↓
DeploymentAdapter interface
        ↓
DeploymentOrchestrator
  validate / map desired
  → observe
  → validate / map observed
  → compare
  → transition
  → compile
  → preview
  → freshness validation
  → apply
  → verify
        ↓
provider NativeOperationExecutor / RuntimeProvider
        ↓
runtime
```

The orchestration above is provider-neutral. Platform packages configure or implement only the narrow `SchemaMapper`, `SchemaTransitionPlanner`, `TransitionCompiler`, `RuntimeProvider`, and `NativeOperationExecutor` seams. The initial Databricks path reuses the shared fail-closed `AdditiveSchemaTransitionPlanner`; a future platform can supply a different planner without changing orchestration.

## What a DeploymentPlan means

A `DeploymentPlan` is a deterministic, provider-neutral statement of the runtime state that one exact deployment source intends to converge toward.

Canonical plans are v5 and bind only the immutable source snapshot plus optional release provenance. Candidate versus release mode is not stored as another boolean: it is derived from the source provenance. Legacy `AppliedContractRelease` / `ReleaseSnapshot` plan payloads remain readable behind compatibility seams.

The initial action vocabulary deliberately contains only:

```text
ENSURE_ASSET_STATE
```

One action is emitted for each governed ODCS schema. The action carries the governed logical asset identity, its physical-name binding hint, and the canonical released schema snapshot.

## Why plans do not say CREATE / ALTER / DROP

Planning sees released desired state only. Without observed runtime state SemaPact cannot know whether a provider must create an asset, alter an existing asset, or do nothing.

Likewise, an object that exists in runtime but is absent from one contract must not be interpreted as safe to drop. The contract may not own that object.

Concrete provider-native operations therefore begin at the platform adapter boundary, where validation and preview combine the DeploymentPlan with provider semantics and fresh runtime evidence.

Provider preview should keep **comparison facts**, **transition semantics**, and SQL rendering separate. Conceptually:

```text
normalized desired schema + normalized observed schema
        ↓
shared schema comparator
        ↓
SchemaDifference[]
        ↓
deployment transition projection
  CREATE_ASSET / ADD_PROPERTIES / NO_OP
        ↓
provider compiler
        ↓
CREATE / ALTER / NO_OP native operation
```

The same shared schema comparison facts are consumed by runtime reconciliation. Reconciliation projects them into drift reason codes; deployment projects them into convergence intent. Provider adapters must not implement a second desired-vs-observed comparator.

Schema projection is also shared. `semapact.schema` defines the mapping contract that converts provider target-schema output and observed runtime state into normalized `SchemaSnapshot` values. SemaPact should not reimplement an ODCS-to-platform compiler when datacontract-cli already provides one.

For Databricks, the desired side delegates the complete ODCS → Databricks target-schema compilation to datacontract-cli's SQL exporter, including physical property names, target types, nested types, and nullability. SemaPact parses that compiler output into its normalized comparison model, rejects any output that is not exactly one CREATE TABLE statement, and retains only the governed physical column shape currently covered by comparison semantics (identity, type, nullability). The observed side maps fresh runtime evidence into the same model.

The exported CREATE DDL is **not** execution authority: datacontract-cli currently emits full creation-oriented DDL, while SemaPact must derive CREATE / ALTER / NO_OP from the released target schema versus fresh runtime state and compile only the exact authorized transition.

The semantic transition layer is an internal planning boundary, not a new release artifact or authorization authority. This lets compatible execution families share transition semantics while keeping provider-specific naming, capability checks, SQL rendering, authentication, and execution in their adapters.

## Identity and physical binding

The same governed identity rule applies on both deployment and reconciliation paths:

```text
schema.name
= governed logical identity

schema.physicalName
= deployment/runtime binding hint only
```

For example:

```yaml
schema:
  - name: Orders
    physicalName: prod_orders_v2
```

produces an action whose governed identity is `orders` while the physical binding hint remains `prod_orders_v2`.

Changing a physical name does not redefine the governed contract identity.

## Targeting

A plan requires an explicit target:

```text
DeploymentTarget
├── platform
├── runtimeTarget
├── sourceReference
└── serverName?     # optional provenance
```

`platform` is the downstream adapter dispatch key. `runtimeTarget` is an opaque provider-local product target. `sourceReference` identifies the exact runtime source/end point against which the plan is authorized; for Databricks this is the workspace host used by runtime observation. It is an identity reference, never a credential.

Preview, execution, and verification fail closed when fresh runtime evidence comes from a different source than the plan's `sourceReference`. This prevents an authorization for the same catalog/schema name from being reused against another workspace.

The plan does not contain credentials, workspace clients, SQL connections, or provider sessions.

## ReleaseBundle and DeploymentBundle boundaries

Formal contract release and runtime deployment are separate lifecycles with separate immutable handoff artifacts.

A formal release is target-neutral:

```text
base + candidate
    ↓
GovernanceDecision
→ ChangeSet
→ ReleasePlan
→ VersionResolution
→ ReleaseSnapshot
→ ReleaseBundle
```

`ReleaseBundle` contains no runtime target, workspace, catalog, schema, warehouse, or deployment preview. It freezes exactly what is intended to become a released contract.

For REVIEW decisions, approval binds:

```text
PUBLISH
+ exact ReleaseSnapshot ID
+ exact ReleaseBundle digest
```

Finalization then creates the formal release fact and materializes the selected semantic version back into ODCS:

```text
ReleaseBundle
+ exact approval when REVIEW
        ↓
release finalize
        ↓
ContractRelease
+ versioned ODCS contract
```

A finalized release is environment-neutral. One release can subsequently fan out to multiple runtime targets without another version bump:

```text
ContractRelease orders@1.4.0
├── dev
├── test
└── prod
```

Deployment begins only after the release exists, or directly from an unreleased candidate for validation/test use.

Candidate deployment:

```text
base + candidate
→ GovernanceDecision + ChangeSet
→ DeploymentSourceSnapshot(source_kind=candidate)
→ target-specific DeploymentPlan
→ fresh DeploymentPreview
→ DeploymentBundle
```

Finalized-release deployment:

```text
ContractRelease
→ DeploymentSourceSnapshot(source_kind=contract_release)
→ target-specific DeploymentPlan
→ fresh DeploymentPreview
→ DeploymentBundle
```

A release-mode `DeploymentBundle` therefore carries the exact finalized `ContractRelease`, not `ReleasePlan`, `VersionResolution`, or `ReleaseSnapshot`. Deployment never creates or versions a contract release.

## CLI workflow

### Candidate deployment

Candidate deployment remains a direct `assess → deploy` path:

```bash
semapact deployment assess \
  --base ./contracts/orders.yaml \
  --candidate ./contracts/orders.candidate.yaml \
  --base-revision-ref git:abc123 \
  --candidate-revision-ref git:def456 \
  --effective-date 2026-09-20 \
  --server development \
  --bundle-out ./artifacts/orders-dev.deployment.bundle.json

semapact deployment deploy \
  --bundle ./artifacts/orders-dev.deployment.bundle.json \
  --warehouse-id <warehouse-id>
```

This does not calculate another semantic version, create release approval, or write release history. REVIEW may proceed for candidate runtime validation; BLOCK always fails closed.

### Formal release

Build the target-neutral release artifact first:

```bash
semapact release assess \
  --base ./contracts/orders.yaml \
  --candidate ./contracts/orders.candidate.yaml \
  --base-revision-ref git:abc123 \
  --candidate-revision-ref git:def456 \
  --effective-date 2026-09-20 \
  --bundle-out ./artifacts/orders.release.bundle.json
```

For a REVIEW release, an external workflow may persist exact approval with the convenience command:

```bash
semapact release approve \
  --bundle ./artifacts/orders.release.bundle.json \
  --actor-reference github-environment:contract-release \
  --recorded-at 2026-09-20T10:00:00+10:00
```

The approval is `PUBLISH`-scoped to the exact `ReleaseSnapshot` and `ReleaseBundle` digest. ALLOW releases do not require an ApprovalRecord.

Finalize exactly once:

```bash
semapact release finalize \
  --bundle ./artifacts/orders.release.bundle.json \
  --output-contract ./contracts/orders.yaml \
  --release-out ./artifacts/orders.contract-release.json
```

Finalization:

- authorizes the exact formal release;
- writes one immutable `ContractRelease` to the Git governance ledger;
- writes the selected version back to the ODCS contract file.

After finalization, hand the immutable ContractRelease artifact directly to target-specific deployment:

```bash
semapact deployment assess \
  --release ./artifacts/orders.contract-release.json \
  --server production \
  --bundle-out ./artifacts/orders-prod.deployment.bundle.json
```

The same ContractRelease artifact may be assessed/deployed against dev, test, prod, or another runtime target. `--release-id` remains a convenience fallback for resolving the same artifact from the Git governance ledger; Git history is not the canonical CI/CD transport.

### CI/CD handoff rules

Two immutable boundaries are now explicit:

```text
CI release planning
→ ReleaseBundle
→ approval/finalize
→ ContractRelease

runtime planning
ContractRelease + target
→ DeploymentBundle
→ fresh CD execution
```

CD must not rebuild either artifact from mutable repository state after its trust boundary. Deployment always re-observes runtime before mutation, so the CI-time preview remains review evidence only and is never replayed blindly.

At execution time:

```text
protected CI/CD execution boundary
→ exact DeploymentBundle
→ validate candidate/finalized-release provenance
→ fresh runtime observation
→ fresh DeploymentPreview
→ apply
→ fresh reconciliation
→ IN_SYNC / DRIFT / INDETERMINATE
```

## Governance ledger vs operational history

SemaPact deliberately separates low-frequency governance facts from high-frequency deployment telemetry.

### Git governance ledger

Git-backed history is appropriate for durable reviewable facts such as:

```text
ApprovalRecord
ContractRelease
```

`semapact release finalize` creates one immutable, target-neutral `ContractRelease` containing the released contract version, the exact source revision from which the release was derived, and release-artifact identities. The released contract snapshot itself is canonical; the source revision is provenance and need not already contain the materialized version bump. Target-specific deployment bundles remain separate. Candidate deployment creates no release history.

The Git adapter writes deterministic history files under `.semapact/history/`. The surrounding GitOps workflow remains responsible for committing/publishing those files; SemaPact does not silently push repository branches.

The formal release fact is independent of runtime convergence. Once `ContractRelease` is created, a later runtime deployment failure does not undo or renumber the release.

### Operational history — opt in

Deployment executions can be much more frequent than releases, so SemaPact does **not** write deployment/reconciliation telemetry to Git by default.

Without configuration:

```text
deployment execute + verify
→ return DeploymentExecutionResult
→ no operational history persistence
```

Configure operational telemetry once in `.semapact.yaml`:

```yaml
history:
  operational:
    backend: sqlite
    path: .semapact/operational.db
```

For a shared/higher-volume Delta sink:

```yaml
history:
  operational:
    backend: delta
    table_uri: s3://governance/semapact/operational-history
```

The `history.operational` subsection is validated fail-closed by the typed `SemaPactConfigSchema`. Unknown backends, missing backend-specific fields, or extra fields are rejected.

Resolution precedence is:

```text
--operational-history CLI override
        ↓
history.operational project/global config
        ↓
disabled
```

The CLI URI remains available for one-off/custom pipeline overrides, but ordinary CI/CD does not repeat the history destination on every deployment.

Supported operational history backends in this slice are SQLite and Delta. The Delta backend is lazy and requires the `delta` optional extra. Operational event payloads carry an explicit schema version so the telemetry contract can evolve independently of governance-history models.

Legacy Git-backed deployment/runtime history artifacts remain readable for compatibility, but the canonical bundle workflow does not create new operational records in Git.

Operational events record concrete deployment occurrence facts including success/failure, exact bundle/plan/source provenance, target, timestamps, and reconciliation status when available.

## Databricks deployment capability

The first Databricks write slice remains intentionally narrow and fail-closed for schema mutation:

| Observed state | Supported behavior |
| --- | --- |
| Governed table is missing | `CREATE TABLE ... USING DELTA` as a managed table |
| Existing `MANAGED` table is missing a governed nullable column | `ALTER TABLE ... ADD COLUMNS (...)` |
| Existing `MANAGED` table already satisfies the governed shape | `NO_OP` |
| Runtime contains extra columns not governed by this contract | Leave them untouched |

Rename, existing-column type/nullability mutation, unsafe required-column addition, DROP, non-managed mutation, and ambiguous mappings fail closed.

### Unity Catalog release provenance tags

After deployment of a **finalized formal release** reaches schema reconciliation status `IN_SYNC`, the Databricks adapter projects SemaPact-owned release provenance onto every governed Unity Catalog table:

```text
semapact_contract_id
semapact_contract_version
semapact_release_id
semapact_source_revision
```

For example, a released `orders@1.4.0` table is tagged with version `1.4.0` and the exact `ContractRelease` identity. Candidate/non-release deployments never publish formal release/version tags.

This projection is deliberately limited to SemaPact provenance. ODCS business tags, classifications, PII labels, or governed ABAC tags are **not** automatically mapped to Unity Catalog tags; those require a separate explicit mapping policy.

The Databricks principal running CD must have the Unity Catalog privileges needed to apply table tags, including `APPLY TAG` on the target object plus `USE CATALOG` and `USE SCHEMA` on its parents. SemaPact uses `ALTER TABLE ... SET TAGS`, supported by current Unity Catalog SQL surfaces.

Tag mutation is a provider side effect and therefore requires a Databricks SQL warehouse even when the schema deployment itself resolves to `NO_OP`. A tag-write failure fails the release deployment command rather than silently claiming the runtime is fully projected.

## Execution trust boundary

Candidate and finalized-release deployments use different provenance, but neither turns release state into runtime execution authority:

```text
candidate deployment
→ exact GovernanceDecision + candidate source snapshot
→ BLOCK fails closed

formal release deployment
→ exact finalized ContractRelease provenance
```

Whether runtime mutation may execute is decided by the surrounding protected CD context, such as a GitHub Environment or Azure DevOps Environment. SemaPact validates the exact bundle, source/plan linkage, fresh runtime observation, deterministic preview, and convergence; it does not manufacture DEPLOY authority from a ContractRelease.

## Determinism

`deploymentPlanId` is UUID5-derived from the full stable plan record:

- exact deployment source snapshot (candidate or release) and revision/version provenance;
- exact deployment target, including runtime source reference;
- canonical actions ordered by governed asset identity;
- plan schema version.

The same exact deployment source and target therefore produce the same DeploymentPlan.

Action ordering is canonical even when schemas appear in a different order in source ODCS. However, DeploymentPlan does not redefine release identity: two distinct exact release artifacts remain distinct plan inputs even if their projected actions happen to be equivalent.

`DeploymentPreview` is likewise deterministic for the same plan and observed runtime evidence, but deterministic IDs provide artifact consistency rather than cryptographic authenticity. Execution still validates exact binding and fresh runtime evidence at the side-effect boundary.

## Provider support belongs behind generic deployment contracts

`semapact.platforms.runtime_registry` is the composition root. It lazily constructs the selected platform's runtime provider and deployment adapter and owns the small amount of dispatch needed for supported built-in platforms. SemaPact does not introduce a separate platform-factory hierarchy merely to construct these objects.

Platform extensibility belongs in behavior seams—`RuntimeProvider`, `SchemaMapper`, `SchemaTransitionPlanner`, `TransitionCompiler`, and `NativeOperationExecutor`—rather than in an additional platform wrapper or composition abstraction.

DeploymentPlan intentionally does not contain generic `preconditions`, `adapterKey`, or guessed platform-specific operations.

The public deployment contracts define the complete orchestration boundary. `DeploymentOrchestrator` owns lifecycle ordering and generic binding invariants; platform implementations provide only runtime binding/observation, target-schema mapping configuration, transition capability policy, transition compilation, and native execution.

For Databricks, the native side effect is executed through the Databricks SDK Statement Execution API using an exact SQL warehouse. SemaPact does not shell out to the Databricks CLI for deployment.

A platform implementation must explicitly report unsupported ODCS-to-platform mappings or runtime capabilities. It must never silently ignore unsupported governed state.

A successful execution call is also not proof of convergence. Runtime convergence is verified separately through SemaPact reconciliation.
