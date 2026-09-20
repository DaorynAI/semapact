# ContractOps execution phases

ContractOps separates reasoning from side effects so CI, agents, APIs, and user interfaces can inspect a governed release before anything external changes.

## Canonical contract release flow

Contract release is explicit and distinct from ordinary runtime deployment.

Candidate deployment does not enter the version-resolution path:

```text
ANALYZE
→ GovernanceDecision
→ ChangeSet
→ candidate DeploymentSourceSnapshot
→ DeploymentPlan
→ runtime deployment
```

A formal release enters ContractOps release planning exactly once:

```text
ANALYZE
→ GovernanceDecision

PLAN RELEASE
→ ChangeSet
→ ReleasePlan
→ VersionResolution
→ ReleaseSnapshot

FORMAL RELEASE
→ immutable ContractRelease

DEPLOY
→ one or more target-specific DeploymentPlan / deployment occurrences
```

The same formal contract version may be deployed to dev, test, and prod without another version bump. Runtime promotion is not a new contract release.
## The contract is the desired-state artifact

SemaPact does not introduce a canonical BUILD phase that turns a contract into a separately authoritative DDL artifact.

The governed contract remains the model of desired state throughout the lifecycle:

```text
candidate ODCS
    ↓ ANALYZE / PLAN
ReleaseSnapshot
= immutable selected governed desired state
    ↓ target-specific DeploymentPlan
fresh runtime observation
    ↓
provider-native preview operations
```

A SQL or provider-specific export is a **derived compilation output**, not a second source of truth and not deployment authority. It may be regenerated from the exact governed contract state whenever required.

This creates two distinct comparisons:

```text
Contract comparison
base contract ↔ candidate contract
→ governance changes, breaking classification, version requirements

Runtime deployment comparison
ReleaseSnapshot / DeploymentPlan ↔ observed runtime state
→ CREATE / ALTER / NO_OP or an explicit unsupported transition
```

The first comparison explains how governed intent changed. The second explains how one concrete runtime must change to converge to that already-governed intent. The same release may therefore produce different deployment previews for different targets without changing the released contract.

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

PUBLISH and DEPLOY are the external side-effect scopes that matter to the new workflow. The historical APPLY authorization remains supported for compatibility while callers migrate to pure `ReleaseSnapshot` materialization. Runtime DEPLOY remains scoped to the exact `DeploymentPlan` before mutation.

## RELEASE SNAPSHOT

Release snapshot construction is pure. It materializes the exact selected ODCS state from the planned candidate and `VersionResolution.selectedVersion` without crossing an external side-effect boundary.

`build_release_snapshot(...)`:

- requires the supplied candidate revision reference to match the planned revision;
- validates contract identity and the expected current version;
- copies the candidate and synchronizes only the selected release version;
- does not mutate the input candidate;
- does not rerun governance or version authority;
- produces a deterministic `ReleaseSnapshot` with no authorization ID.

This pure snapshot is used only for formal `--release` bundles. Candidate deployment freezes the candidate directly in a non-release `DeploymentSourceSnapshot` and does not calculate a new semantic version.

## APPLY compatibility

`apply_contract_release(...)` remains available for existing callers. It validates the historical `ContractOpsAuthorization(operation=APPLY)`, builds the same pure `ReleaseSnapshot`, and wraps that snapshot into the legacy `AppliedContractRelease` artifact.

New CI deployment workflows must not require APPLY authorization merely to plan or preview a deployment. The compatibility wrapper exists to preserve current publication/history integrations while the authorization surface is simplified.

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

DEPLOY mutates a runtime toward one exact target-specific `DeploymentPlan`. It is downstream of governance and may consume either:

- a candidate deployment source (`release=false`), with no release version/approval/history; or
- a formal release source (`release=true`), with exact release/version provenance and REVIEW approval when required.

Candidate REVIEW deployments are allowed as non-release validation/test deployments without creating release approval evidence. `BLOCK` always fails closed.

For formal release mode, the new `ContractRelease` is the durable Git governance fact. Runtime deployment history is operational telemetry and is not written to Git by default.

Provider-specific execution stays behind the deployment adapter. For Databricks, a formal release that reaches `IN_SYNC` also projects SemaPact-owned release/version provenance into Unity Catalog tags.

See [`deployment_plans.md`](deployment_plans.md) for the complete candidate/release CLI flow, operational-history backends, Databricks tags, and convergence semantics.
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
