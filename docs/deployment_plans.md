# Deployment plans

SemaPact treats a released ODCS contract as governed desired state, not as an executable SQL, Terraform, or platform program.

The deployment planning boundary is therefore:

```text
AppliedContractRelease
+ DeploymentTarget
        ↓
DeploymentPlan
        ↓
platform adapter validate / preview / publish
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

Concrete provider-native operations therefore begin at the platform adapter boundary, where `validate` and `preview` can combine the DeploymentPlan with actual provider semantics and, where required, runtime evidence.

## Identity and physical binding

The same rule used by M1 reconciliation applies on the write side:

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

## Determinism

`deploymentPlanId` is UUID5-derived from the full stable plan record:

- exact `AppliedContractRelease` identity and provenance;
- exact deployment target;
- canonical actions ordered by governed asset identity;
- plan schema version.

The same exact applied release and target therefore produce the same DeploymentPlan.

Action ordering is canonical even when schemas appear in a different order in source ODCS. However, DeploymentPlan does not redefine release identity: two distinct `AppliedContractRelease` artifacts remain distinct authorities even if their projected actions happen to be equivalent.

## Provider support belongs to the adapter

DeploymentPlan intentionally does not contain generic `preconditions`, `adapterKey`, or guessed platform-specific operations.

The next boundary is responsible for explicit support:

```text
DeploymentAdapter
├── validate(plan)
├── preview(plan)
└── publish(plan, authorization)
```

A provider adapter must explicitly report unsupported ODCS-to-platform mappings. It must never silently ignore unsupported governed state.

A successful plan or publish call is also not proof of convergence. Runtime convergence is verified separately through SemaPact reconciliation.
