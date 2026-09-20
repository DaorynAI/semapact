# Deployment plans

SemaPact treats a released ODCS contract as governed desired state, not as an executable SQL, Terraform, or platform program.

The released contract is the authoritative artifact. SemaPact does **not** require a separate DDL build artifact before deployment. SQL and other provider-native commands are derived only after an exact released desired state is compared with an exact runtime target.

```text
ReleaseSnapshot
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
ReleaseSnapshot
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

The orchestration above is provider-neutral. Platform packages configure or implement only the narrow `SchemaMapper`, `SchemaTransitionPlanner`, `TransitionCompiler`, `RuntimeProvider`, and `NativeOperationExecutor` seams. The initial Databricks path reuses the shared fail-closed `AdditiveSchemaTransitionPlanner`; a future platform can supply a different planner without changing orchestration.

## What a DeploymentPlan means

A `DeploymentPlan` is a deterministic, provider-neutral statement of the runtime state that one exact release snapshot intends to converge toward.

The canonical CI path builds it from a pure `ReleaseSnapshot`, which freezes the selected contract revision/version without requiring side-effect authorization. Legacy `AppliedContractRelease` inputs remain readable for v2-plan compatibility, but new CI bundles use v3 plans bound to `releaseId`.

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

## CI assessment and the DeploymentBundle boundary

CI must produce a stable artifact that CD can consume after approval. SemaPact packages the exact planning material into a content-addressed `DeploymentBundle`:

```text
base + candidate
    ↓
GovernanceDecision
→ ChangeSet
→ ReleasePlan
→ VersionResolution
→ ReleaseSnapshot
→ DeploymentPlan
        +
fresh runtime observation
        ↓
DeploymentPreview   # review evidence only
        ↓
DeploymentBundle
        ↓
sha256 content digest
```

`DeploymentBundle` is a transport and integrity boundary, not another governance authority. It contains the canonical decision/planning artifacts, the exact release snapshot, the target-specific deployment plan, and the runtime preview that CI showed to reviewers.

The bundle contains **no execution authorization**. The CI preview is also not a future SQL script: CD must re-observe runtime and re-derive provider operations at the mutation boundary. The bundle digest lets CI publish one immutable artifact and lets approval/CD pin the exact reviewed material.

The previous candidate-specific `DeploymentAssessment` artifact is intentionally not part of this model. CI uses the same canonical `DeploymentPlan → preview` path as later deployment rather than maintaining a second desired-vs-runtime workflow.

## CLI workflow

The deployment CLI exposes a high-level bundle workflow plus low-level compatibility/debugging commands. `assess` is the canonical CI/manual planning surface; `deploy` is the canonical CD/manual execution surface.

### Assess

```bash
semapact deployment assess \
  --base ./contracts/orders.yaml \
  --candidate ./contracts/orders.candidate.yaml \
  --base-revision-ref git:abc123 \
  --candidate-revision-ref git:def456 \
  --effective-date 2026-09-20 \
  --server production \
  --bundle-out ./artifacts/orders-prod.bundle.json \
  --output text
```

When the candidate contract defines the selected server, its platform, catalog/schema target, and host are authoritative. For contracts without servers, provide `--platform`, `--runtime`, and `--source-reference`.

The bundle file contains the canonical planning artifacts, `ReleaseSnapshot`, v3 `DeploymentPlan`, and CI-time `reviewPreview`, protected by `bundleDigest`. Use `--output json` to emit that same bundle on stdout instead. CI can publish the file using its normal pipeline-artifact mechanism; SemaPact does not couple this package to one CI vendor.

### CI artifact handoff

SemaPact deliberately emits an ordinary file artifact so CI systems can use their native immutable artifact store. The pipeline should publish the exact bundle file produced by `assess`; CD should download that artifact rather than rebuilding it from the merged repository state.

Generic CI:

```text
CI job
  semapact deployment assess --bundle-out deployment.bundle.json
        ↓
  publish deployment.bundle.json
        ↓
  record immutable artifact/digest reference
        ↓
approval
        ↓
CD job
  download the exact published deployment.bundle.json
        ↓
  semapact deployment deploy --bundle deployment.bundle.json
```

GitHub Actions can use the normal artifact actions:

```yaml
- name: Build SemaPact deployment bundle
  run: |
    semapact deployment assess \
      --base contracts/orders.base.yaml \
      --candidate contracts/orders.yaml \
      --base-revision-ref "git:${{ github.event.pull_request.base.sha }}" \
      --candidate-revision-ref "git:${{ github.event.pull_request.head.sha }}" \
      --effective-date "$(date -u +%F)" \
      --server production \
      --bundle-out artifacts/orders-prod.bundle.json

- name: Publish deployment bundle
  uses: actions/upload-artifact@v4
  with:
    name: semapact-orders-prod
    path: artifacts/orders-prod.bundle.json
    if-no-files-found: error
```

The corresponding CD job downloads that exact artifact and passes it unchanged to `deployment deploy`. Azure DevOps should use the equivalent Pipeline Artifact publish/download tasks. SemaPact does not require a vendor-specific artifact registry.

Do not regenerate the bundle in CD. Rebuilding would create a new CI boundary and could make approval refer to material different from what CD consumes. CD is allowed—and required—to re-observe runtime, but not to replace the approved desired-state bundle.

### Deploy

After CI publishes the exact bundle and any required human approval is recorded, CD consumes that bundle directly:

```bash
semapact deployment deploy \
  --bundle ./artifacts/orders-prod.bundle.json \
  --approval ./artifacts/orders-prod.approval.json \
  --warehouse-id <databricks-sql-warehouse-id> \
  --output json
```

`--approval` is required only when the bundle carries a `GovernanceDecision(REVIEW)`. The approval must be an exact `ApprovalRecord` for DEPLOY, scoped to the bundle's `deploymentPlanId`, and its evidence references must include the exact `bundleDigest`.

The CD workflow deliberately ignores the CI-time review preview as execution input:

```text
load + validate exact DeploymentBundle
→ validate approval / operation authorization
→ fresh runtime observation
→ fresh DeploymentPreview
→ execute exact fresh preview
→ fresh verification
→ IN_SYNC / DRIFT / INDETERMINATE
```

If runtime changed between CI and CD, the fresh preview may differ. A CI-time ALTER can become NO_OP; a newly unsafe or conflicting transition fails closed. Provider execution success is not sufficient: the command returns reconciliation semantics after a separate fresh verify.

For governance-ALLOW deployments, `--approval` may be omitted.

### Low-level artifact commands

The following commands remain available for compatibility, diagnostics, and explicit artifact workflows. They are not the recommended CI/CD happy path.

### Plan

```bash
semapact deployment plan \
  --release ./artifacts/release-snapshot.json \
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

### Execute (low-level compatibility)

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

At the canonical application boundary, callers provide an exact `DeploymentBundle` and, for REVIEW decisions, an `ApprovalRecord`. The approval must bind the exact `deploymentPlanId` and include the exact `bundleDigest` as evidence. This makes the CI artifact itself part of the approval scope rather than approving a mutable path or a SQL string.

The current low-level domain implementation still bridges this into the historical `ContractOpsAuthorization → DeploymentAuthorization` types before calling the adapter. That bridge is compatibility machinery; Data Engineers and CI/CD callers do not construct those artifacts in the bundle workflow. A future cleanup can collapse the bridge without changing the public bundle contract.

A PUBLISH authorization cannot authorize DEPLOY.

## Determinism

`deploymentPlanId` is UUID5-derived from the full stable plan record:

- exact release identity and provenance (`ReleaseSnapshot` for v3 plans; legacy applied-release identity for v2 compatibility);
- exact deployment target, including runtime source reference;
- canonical actions ordered by governed asset identity;
- plan schema version.

The same exact release and target therefore produce the same DeploymentPlan.

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
