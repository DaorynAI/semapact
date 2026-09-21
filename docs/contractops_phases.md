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

`GovernanceDecision(REVIEW)` remains `REVIEW` after approval. Formal-release approval is represented by an immutable `ApprovalRecord` bound to the exact `ReleaseSnapshot` and `ReleaseBundle` digest. `ReleaseFinalizer` projects that evidence into the PUBLISH authorization check without rewriting governance history.

Runtime deployment is a separate boundary. SemaPact does not create a deployment-authorization artifact; the surrounding protected CI/CD environment controls whether runtime mutation may be invoked, while SemaPact validates exact source/plan binding and runtime freshness.

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

## PUBLISH

PUBLISH is the formal-release authorization boundary. For a REVIEW decision, the approval must bind the exact `ReleaseSnapshot` and `ReleaseBundle` digest. For ALLOW, no explicit approval record is required.

After that check, `ReleaseFinalizer` constructs the immutable, target-neutral `ContractRelease`. The CLI persists that release fact to the Git governance ledger and may also emit the `ContractRelease` JSON artifact for CI/CD handoff.

PUBLISH does not authorize runtime mutation. A `ContractRelease` records what was formally released; deployment remains a separate protected execution boundary.

## DEPLOY

DEPLOY converges one runtime toward an exact target-specific `DeploymentPlan`. The desired state comes from one immutable `DeploymentSourceSnapshot`:

- `source_kind=candidate` for validation/test deployment without a formal release;
- `source_kind=contract_release` for deployment of an already-finalized `ContractRelease`.

Candidate `BLOCK` decisions fail closed. Candidate `REVIEW` may still be deployed for non-release validation/test because this path creates no formal release fact or release approval.

Formal REVIEW approval belongs to the earlier PUBLISH boundary. A `ContractRelease` proves what was released; it does not grant permission to mutate a runtime. Whether `semapact deployment deploy` may run is controlled by the surrounding protected execution context, such as a GitHub or Azure DevOps Environment.

The deployment adapter validates exact plan/source binding, re-observes runtime, derives a fresh deterministic preview, checks runtime freshness, applies safe operations, then verifies convergence. For Databricks, a finalized release that reaches `IN_SYNC` also projects SemaPact-owned release/version provenance into Unity Catalog tags.

Runtime deployment history is optional operational telemetry and is not written to Git by default.

See [`deployment_plans.md`](deployment_plans.md) for the complete candidate/release CLI flow, operational-history backends, Databricks tags, and convergence semantics.

## Failure semantics

ContractOps distinguishes invalid release context from denied publication authorization:

- mismatched release revision/artifact context → `ReleaseValidationError`;
- a valid formal release whose required PUBLISH approval is denied/missing → `ContractOpsAuthorizationError`;
- runtime deployment fails closed on invalid source/plan provenance, stale runtime evidence, or unsupported provider transitions.

Unexpected persistence/runtime failures are not converted into governance decisions; they propagate as execution failures.

