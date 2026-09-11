# ContractOps execution phases

ContractOps separates reasoning from side effects so CI, agents, APIs, and user interfaces can inspect a governed release before anything external changes.

## Canonical contract release flow

```text
ANALYZE
→ GovernanceDecision

PLAN
→ ChangeSet
→ ReleasePlan
→ VersionResolution

AUTHORIZE
→ ContractOpsAuthorization

APPLY
→ AppliedContractRelease

PUBLISH
→ PublicationResult

DEPLOY
→ DeploymentPlan + DeploymentAuthorization
→ runtime mutation through a platform adapter
```

Each phase consumes artifacts from the previous phases. Later phases do not recalculate earlier decisions.

## ANALYZE

ANALYZE evaluates the candidate against the governed base contract and produces the authoritative `GovernanceDecision`.

It is pure. It does not write files, create Git branches or tags, update ODCS, or mutate a runtime platform.

The CLI analysis surface is:

```bash
semapact release classify \
  --base ./contracts/orders.yaml \
  --candidate ./contracts/orders.candidate.yaml \
  --effective-date 2026-09-11
```

`release classify` is analysis-only. It reports the governance decision and required version bump, but it does not create a `ChangeSet`, `ReleasePlan`, or `VersionResolution` and does not authorize a release.

## PLAN

PLAN converts the authoritative decision into deterministic release artifacts:

- `ChangeSet` identifies the exact base and candidate revisions and carries the authoritative governance changes.
- `ReleasePlan` describes the exact candidate revision intended for release and its minimum required version bump.
- `VersionResolution` selects the actual release version according to the configured version authority.

PLAN remains pure.

The canonical CLI planning surface is:

```bash
semapact release plan \
  --base ./contracts/orders.yaml \
  --candidate ./contracts/orders.candidate.yaml \
  --base-revision-ref git:abc123 \
  --candidate-revision-ref git:def456 \
  --effective-date 2026-09-11
```

The revision references are required because release artifacts must be bound to the exact base and candidate workflow revisions rather than to mutable file paths alone.

When `release.versionAuthority=git`, provide the repository release reference explicitly:

```bash
semapact release plan \
  --base ./contract.yaml \
  --candidate ./contract.candidate.yaml \
  --base-revision-ref git:abc123 \
  --candidate-revision-ref git:def456 \
  --authority-reference v1.4.0 \
  --effective-date 2026-09-11
```

The JSON output is serialized directly from the canonical models and contains:

```text
governanceDecision
changeSet
releasePlan
versionResolution
```

One planning pass evaluates governance once, then feeds the exact resulting artifacts forward. The CLI does not independently re-diff, reclassify, or reimplement version policy downstream.

## AUTHORIZE

AUTHORIZE evaluates whether one exact operation can cross a side-effect boundary.

A release-context authorization is scoped to:

```text
decisionId
changeSetId
releasePlanId
versionResolutionId
operation
scopeReference?
```

`GovernanceDecision(REVIEW)` remains `REVIEW` after approval. Matching explicit review evidence produces an allowed `ContractOpsAuthorization`; it does not rewrite governance history.

APPLY, PUBLISH, and DEPLOY are distinct operation scopes. Runtime DEPLOY additionally binds authorization to the exact `DeploymentPlan` before mutation.

## APPLY

APPLY materializes the exact released ODCS state from the planned candidate and `VersionResolution.selectedVersion`.

The canonical APPLY path:

- requires an allowed `ContractOpsAuthorization(operation=APPLY)`;
- requires the supplied candidate revision reference to match the planned revision;
- validates contract identity and the expected current version;
- copies the candidate and synchronizes only the selected release version;
- does not mutate the input candidate;
- does not rerun diffing, lifecycle policy, breaking-change classification, or version authority.

The output is an immutable `AppliedContractRelease` containing provenance IDs and a canonical JSON snapshot of the released ODCS state. Consumers can materialize a fresh ODCS model from that snapshot.

This also covers metadata-only governed releases: `requiredVersionBump=none` may have been resolved by SemaPact version authority to an actual patch release, and APPLY uses that already-selected version directly.

## PUBLISH

PUBLISH publishes an applied contract release or release artifact. It is distinct from runtime deployment.

It requires an allowed `ContractOpsAuthorization(operation=PUBLISH)` matching the exact applied release context before the publisher adapter is invoked. An APPLY authorization cannot authorize PUBLISH.

ContractOps defines only a narrow publisher port:

```text
AppliedContractRelease
        ↓
ContractReleasePublisher.publish(...)
        ↓
opaque publication reference
        ↓
PublicationResult
```

Git, storage, and other release-artifact publication behavior belongs in adapters rather than the ContractOps domain.

## DEPLOY

DEPLOY mutates a runtime toward a provider-neutral `DeploymentPlan` and is separate from release publication.

A release-context `ContractOpsAuthorization(operation=DEPLOY)` is not enough on its own. Runtime execution also requires a `DeploymentAuthorization` bound to the exact deployment plan, including its target. A review approval scoped to one deployment plan therefore cannot be rebound to another target.

Platform-specific execution belongs behind a deployment adapter. The adapter must not recompute governance, version authority, release planning, or approval semantics.

See [`deployment_plans.md`](deployment_plans.md) for the deployment CLI, Databricks capability boundary, preview integrity checks, and convergence verification semantics.

## Failure semantics

ContractOps distinguishes invalid context from denied authorization:

- mismatched revision/artifact/operation context → `ReleaseValidationError`;
- a valid context whose explicit authorization is denied → `ContractOpsAuthorizationError`;
- external publishers or runtime adapters are never invoked when authorization validation fails.

Unexpected publisher/runtime failures are not converted into governance decisions; they propagate as execution failures.

## Compatibility helpers

`semapact release prepare` and `semapact release create-pr` remain compatibility workflows for existing Git-based release processes. They are not the canonical ContractOps PLAN/APPLY/PUBLISH path and should not be treated as equivalent to `release plan` plus explicit authorization.

`semapact.core.release.prepare_release_candidate()` likewise remains a backward-compatible helper and is not the canonical ContractOps APPLY path because it may classify changes itself.

New ContractOps flows consume the existing authoritative `GovernanceDecision`, `ChangeSet`, `ReleasePlan`, and `VersionResolution` instead of recomputing them.
