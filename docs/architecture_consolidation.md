# ContractOps architecture consolidation

This note records the dependency and composition boundaries established before the
first runtime deployment adapter is implemented.

## Canonical direction

```text
lifecycle / governance
        ↓
GovernanceDecision
        ↓
ContractOps release artifacts
        ↓
AppliedContractRelease
        ↓
DeploymentPlan
        ↓
DeploymentAuthorization
        ↓
platform adapter
        ↓
runtime
        ↓
observation / reconciliation
```

Read-side reconciliation and write-side deployment are siblings around shared
provider-neutral runtime identity/binding concepts. Neither side should own a model
that the other side needs to import.

## Shared runtime asset projection

`semapact.runtime` owns the provider-neutral projection from governed ODCS schemas to
runtime asset specifications:

```text
schema.name     → governed identity
physicalName    → runtime/deployment binding hint
```

`semapact.observation` and `semapact.deployment` both consume this projection.
`semapact.reconciliation.binding` remains a compatibility import path only.

## Versioning ownership

Pure semantic-version types and operations live in `semapact.versioning`.
Lifecycle owns governed release change classification because it is derived from
lifecycle changes/policy. Legacy `semapact.core.release` remains a compatibility
release workflow and re-exports the historical names, but canonical Governance and
ContractOps code must not depend on that legacy workflow module.

## Deployment authorization

Release publication and runtime deployment are different side effects:

```text
PUBLISH → publish an applied contract release/artifact
DEPLOY  → mutate a runtime toward a DeploymentPlan
```

M0 `GovernanceOperation.DEPLOY` preserves the same decision-level semantics as other
side-effect operations: ALLOW proceeds, REVIEW requires explicit review satisfaction,
and BLOCK cannot be overridden.

A `ContractOpsAuthorization(operation=DEPLOY)` is still release-context authority. A
runtime adapter must receive a `DeploymentAuthorization` bound to the exact
`DeploymentPlan` before mutation.

For REVIEW decisions, `ReviewAuthorizationEvidence.scopeReference` carries an opaque
downstream scope. ContractOps preserves but does not interpret it. Deployment requires
that scope to equal the exact `deploymentPlanId`. This lets review bind a concrete
runtime target without introducing a ContractOps → deployment dependency.

## Interface and instantiation audit

Introduce interfaces only where behavior is genuinely replaceable or side-effecting.
Do not add interfaces around pure functions/value objects for symmetry.

### Keep

- `RuntimeProvider` is a real provider port. `RuntimeProviderRegistry` is an
  application-facing registry and Databricks provider/client construction stays in
  `platforms.runtime_registry`, where optional dependencies can remain lazy.
- `ContractReleasePublisher` is a valid narrow side-effect port for release artifact
  publication. Concrete publishers should be constructed outside ContractOps domain
  code.
- `GitProvider` is a valid PR-provider port because GitHub/Azure DevOps are genuinely
  replaceable external systems.

### Do not abstract further yet

- `build_change_set`, `build_release_plan`, `resolve_release_version`,
  `authorize_contract_operation`, and `build_deployment_plan` are deterministic domain
  functions. Wrapping each in an interface would add indirection without a
  replaceability requirement.
- Domain Pydantic models do not need repository/factory interfaces.
- `DeploymentAdapter` should be introduced with #116 only when validate/preview/execute
  result semantics and the first supported Databricks projection are concrete.

### Compatibility debt to retire gradually

`PullRequestCreator` supports provider injection, but its legacy constructor also
interprets concrete config types and instantiates `AzureDevOpsProvider` or
`GitHubProvider`. The empty `GitProviderConfig` Protocol adds little type value.

Do not expand this pattern. New application code should receive a `GitProvider` (or a
composition-root factory should build it). Move legacy config-to-provider construction
out of the workflow when the old GitOps path is migrated onto the canonical ContractOps
application boundary.

Similarly, `ContractPipeline` and `devops.release_workflow` remain compatibility
orchestration paths. New CLI/API/agent flows should not reproduce those pipelines or
manually compose a second lifecycle/release workflow. #118 should expose the canonical
M2 services/artifacts and progressively delegate legacy entrypoints to that boundary.

## Deterministic identities

M2 artifacts share `canonical_compact_json()` and `deterministic_uuid5()` only where
the pre-existing algorithm was already identical:

```text
json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)
→ UUID5(namespace, payload)
```

GovernanceDecision fingerprinting intentionally remains separate because it has a
historical algorithm. Refactoring identity code must never silently migrate stable IDs.

## Composition rule for #116

The first platform adapter should follow this dependency shape:

```text
application/composition root
        ↓ constructs
DeploymentAdapter implementation + platform client
        ↓ receives
DeploymentPlan + allowed DeploymentAuthorization
```

The adapter must not construct its own governance evaluator, review store, version
authority, or DeploymentPlan. Provider credentials and SDK clients enter only through
composition/application code.
