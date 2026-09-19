# Deployment plans

SemaPact treats a released ODCS contract as governed desired state, not as an executable SQL, Terraform, or platform program.

The released contract is the authoritative artifact. SemaPact does **not** require a separate DDL build artifact before deployment. SQL and other provider-native commands are derived only after an exact released desired state is compared with an exact runtime target.

```text
AppliedContractRelease
        = governed desired state
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
AppliedContractRelease
+ DeploymentTarget
        ↓
DeploymentPlan
        ↓
DeploymentAuthorization
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
  → freshness / exact authorization
  → execute
  → verify
        ↓
provider NativeOperationExecutor / RuntimeProvider
        ↓
runtime
```

The orchestration above is provider-neutral. Platform packages configure or implement only the narrow `DeploymentPlatform`, `SchemaMapper`, `SchemaTransitionPlanner`, `TransitionCompiler`, `RuntimeProvider`, and `NativeOperationExecutor` seams. The initial Databricks path reuses the shared fail-closed `AdditiveSchemaTransitionPlanner`; a future platform can supply a different planner without changing orchestration.

## What a DeploymentPlan means

A `DeploymentPlan` is a deterministic, provider-neutral statement of the runtime state that an exact applied contract release intends to converge toward.

It is built only from `AppliedContractRelease`; drafts and raw candidate contracts are not deployment authority.

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

## CLI workflow

The deployment CLI consumes and emits canonical JSON artifacts. Planning and preview are read-only; `execute` is the runtime mutation boundary.

### Plan

```bash
semapact deployment plan \
  --release ./artifacts/applied-release.json \
  --platform databricks \
  --runtime main.sales \
  --source-reference https://dbc-example.cloud.databricks.com
```

`--source-reference` must match the stable source identity reported by the runtime provider. Optional `--server` preserves the selected contract-server reference as target provenance.

The output is the canonical `DeploymentPlan` JSON.

### Preview

```bash
semapact deployment preview \
  --plan ./artifacts/deployment-plan.json
```

Preview observes the exact target scope and derives a canonical `DeploymentPreview`. It does not mutate runtime and does not require a Databricks SQL warehouse merely to inspect provider-native operations.

### Execute

For a preview containing CREATE or ALTER operations, provide the SQL warehouse used for mutation:

```bash
semapact deployment execute \
  --plan ./artifacts/deployment-plan.json \
  --preview ./artifacts/deployment-preview.json \
  --authorization ./artifacts/deployment-authorization.json \
  --warehouse-id <databricks-sql-warehouse-id>
```

For an all-`NO_OP` preview, `--warehouse-id` may be omitted because no native mutation is executed. Any CREATE/ALTER attempt without a warehouse fails closed.

Execution requires the exact plan, exact preview, and exact `DeploymentAuthorization`. The adapter re-observes the target, validates the authorized runtime source and observation fingerprint, re-derives the expected preview for integrity/freshness validation, and executes only the supplied operations when the artifacts still match.

Provider execution success is not convergence proof.

Complete DDL export remains a useful inspection or integration utility, especially for creating new assets, but export is not a lifecycle phase. Exported SQL is derived output; deployment planning remains responsible for comparing the exact released contract with fresh runtime evidence before any mutation is authorized.

### Verify

```bash
semapact deployment verify \
  --plan ./artifacts/deployment-plan.json \
  --output json
```

Verification enters through the same DeploymentAdapter / DeploymentOrchestrator boundary, performs fresh runtime observation, and reuses the normal reconciliation semantics with the same platform schema mapper used by preview:

| Runtime status | Exit code |
| --- | ---: |
| `IN_SYNC` | `0` |
| `DRIFT` | `6` |
| `INDETERMINATE` | `7` |

This keeps execution status separate from convergence evidence. VERIFY is assurance/read-side behavior: provider mutation restrictions such as Databricks MANAGED-only writes do not prevent SemaPact from verifying an observable non-managed asset.

## Databricks deployment capability

The first Databricks write slice is intentionally narrow and fail-closed.

| Observed state | Supported behavior |
| --- | --- |
| Governed table is missing | `CREATE TABLE ... USING DELTA` as a managed table |
| Existing `MANAGED` table is missing a governed nullable column | `ALTER TABLE ... ADD COLUMNS (...)` |
| Existing `MANAGED` table already satisfies the governed shape | `NO_OP` |
| Runtime contains extra columns not governed by this contract | Leave them untouched; no inferred `DROP` |

For this slice, `ALTER` means **only additive nullable-column change**. The adapter does not interpret `ALTER` as generic schema evolution.

The following are rejected rather than guessed or silently converted:

- column rename;
- existing-column physical type change;
- existing-column nullability change;
- adding a required/non-null column without an explicit safe migration/default strategy;
- `DROP` or other destructive reconciliation;
- mutation of existing external/non-managed assets;
- unsupported or ambiguous provider mappings.

Existing external/non-managed assets remain observable through the runtime read side, but this deployment adapter does not claim mutation authority over them.

The adapter is also not a general Databricks infrastructure engine. Workspace, catalog, schema, SQL warehouse, credentials, external locations, storage configuration, grants, jobs, and clusters are outside this deployment boundary and must be provisioned separately.

## Authorization scope

Runtime deployment is a separate protected operation from publishing a contract release artifact.

A `ContractOpsAuthorization(operation=DEPLOY)` establishes release-context authorization. Before runtime mutation, it must be bound to the exact `DeploymentPlan` as a `DeploymentAuthorization`.

For review-required changes, structured review evidence may carry an opaque `scopeReference`. Deployment requires that scope to match the exact `deploymentPlanId`, so an approval for one exact platform/runtime/source target cannot be reused for another target.

A PUBLISH authorization cannot authorize DEPLOY.

## Determinism

`deploymentPlanId` is UUID5-derived from the full stable plan record:

- exact `AppliedContractRelease` identity and provenance;
- exact deployment target, including runtime source reference;
- canonical actions ordered by governed asset identity;
- plan schema version.

The same exact applied release and target therefore produce the same DeploymentPlan.

Action ordering is canonical even when schemas appear in a different order in source ODCS. However, DeploymentPlan does not redefine release identity: two distinct `AppliedContractRelease` artifacts remain distinct authorities even if their projected actions happen to be equivalent.

`DeploymentPreview` is likewise deterministic for the same plan and observed runtime evidence, but deterministic IDs provide artifact consistency rather than cryptographic authenticity. Execution still validates exact binding and fresh runtime evidence at the side-effect boundary.

## Provider support belongs behind generic deployment contracts

Platform composition is centralized behind `PlatformFactory`. A platform owns its ODCS Server → runtime-target projection and composes its RuntimeProvider and DeploymentAdapter; the shared registry only dispatches a platform key to a lazy factory loader. Adding another platform does not require another deployment lifecycle or another runtime/deployment composition branch.

DeploymentPlan intentionally does not contain generic `preconditions`, `adapterKey`, or guessed platform-specific operations.

The public deployment contracts define the complete orchestration boundary. `DeploymentOrchestrator` owns lifecycle ordering and invariant checks; platform implementations provide only target/runtime validation, target schema mapping configuration, transition compilation, and native execution.

For Databricks, the native side effect is executed through the Databricks SDK Statement Execution API using an exact SQL warehouse. SemaPact does not shell out to the Databricks CLI for deployment.

A platform implementation must explicitly report unsupported ODCS-to-platform mappings or runtime capabilities. It must never silently ignore unsupported governed state.

A successful execution call is also not proof of convergence. Runtime convergence is verified separately through SemaPact reconciliation.
