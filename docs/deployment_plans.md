# Deployment plans

SemaPact treats a released ODCS contract as governed desired state, not as an executable SQL, Terraform, or platform program.

The deployment planning boundary is therefore:

```text
AppliedContractRelease
+ DeploymentTarget
        ↓
DeploymentPlan
        ↓
DeploymentAuthorization
        ↓
platform adapter validate / preview / execute
        ↓
runtime
        ↓
reconciliation verifies convergence
```

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
└── serverName?     # optional provenance
```

`platform` is the downstream adapter dispatch key. `runtimeTarget` is an opaque provider-local target descriptor at this layer.

The plan does not contain credentials, workspace clients, SQL connections, or provider sessions.

## CLI workflow

The deployment CLI consumes and emits canonical JSON artifacts. Planning and preview are read-only; `execute` is the runtime mutation boundary.

### Plan

```bash
semapact deployment plan \
  --release ./artifacts/applied-release.json \
  --platform databricks \
  --runtime main.sales
```

Optional `--server` preserves the selected contract-server reference as target provenance.

The output is the canonical `DeploymentPlan` JSON.

### Preview

```bash
semapact deployment preview \
  --plan ./artifacts/deployment-plan.json
```

Preview observes the exact target scope and derives a canonical `DeploymentPreview`. It does not mutate runtime and does not require a Databricks SQL warehouse merely to inspect provider-native operations.

### Execute

```bash
semapact deployment execute \
  --plan ./artifacts/deployment-plan.json \
  --preview ./artifacts/deployment-preview.json \
  --authorization ./artifacts/deployment-authorization.json \
  --warehouse-id <databricks-sql-warehouse-id>
```

Execution requires the exact plan, exact preview, and exact `DeploymentAuthorization`. The adapter re-observes the target, validates the observation source and fingerprint, re-derives the expected preview for integrity/freshness validation, and executes only the supplied operations when the artifacts still match.

Provider execution success is not convergence proof.

### Verify

```bash
semapact deployment verify \
  --plan ./artifacts/deployment-plan.json \
  --output json
```

Verification performs fresh runtime observation and reuses the normal reconciliation semantics:

| Runtime status | Exit code |
| --- | ---: |
| `IN_SYNC` | `0` |
| `DRIFT` | `6` |
| `INDETERMINATE` | `7` |

This keeps execution status separate from convergence evidence.

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

For review-required changes, structured review evidence may carry an opaque `scopeReference`. Deployment requires that scope to match the exact `deploymentPlanId`, so an approval for one target cannot be reused for another target.

A PUBLISH authorization cannot authorize DEPLOY.

## Determinism

`deploymentPlanId` is UUID5-derived from the full stable plan record:

- exact `AppliedContractRelease` identity and provenance;
- exact deployment target;
- canonical actions ordered by governed asset identity;
- plan schema version.

The same exact applied release and target therefore produce the same DeploymentPlan.

Action ordering is canonical even when schemas appear in a different order in source ODCS. However, DeploymentPlan does not redefine release identity: two distinct `AppliedContractRelease` artifacts remain distinct authorities even if their projected actions happen to be equivalent.

`DeploymentPreview` is likewise deterministic for the same plan and observed runtime evidence, but deterministic IDs provide artifact consistency rather than cryptographic authenticity. Execution still validates exact binding and fresh runtime evidence at the side-effect boundary.

## Provider support belongs to the adapter

DeploymentPlan intentionally does not contain generic `preconditions`, `adapterKey`, or guessed platform-specific operations.

A deployment adapter is responsible for explicit provider support and execution semantics. It receives an already-built DeploymentPlan and an allowed DeploymentAuthorization; it does not construct or reinterpret governance artifacts.

A provider adapter must explicitly report unsupported ODCS-to-platform mappings. It must never silently ignore unsupported governed state.

A successful execution call is also not proof of convergence. Runtime convergence is verified separately through SemaPact reconciliation.
