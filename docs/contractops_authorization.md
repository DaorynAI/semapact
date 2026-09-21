# ContractOps review authorization

SemaPact keeps governance classification and formal-release approval as separate immutable facts.

The current canonical use of ContractOps authorization is the PUBLISH boundary for a formal release:

```text
GovernanceDecision(REVIEW)
        +
ChangeSet
        +
ReleasePlan
        +
VersionResolution
        +
matching explicit PUBLISH approval evidence
        ↓
ContractOpsAuthorization(allowed=true)
        ↓
ContractRelease
```

The original `GovernanceDecision` remains `REVIEW`. Approval never rewrites it to `ALLOW`.

## Why authorization happens after version resolution

A reviewer must approve the release that will actually be published, including the selected semantic version.

```text
GovernanceDecision
→ ChangeSet
→ ReleasePlan
→ VersionResolution
→ ReleaseSnapshot
→ ReleaseBundle
→ PUBLISH approval when REVIEW
→ ContractRelease
```

Review evidence is scoped to the exact release context:

```text
decisionId
changeSetId
releasePlanId
versionResolutionId
operation = PUBLISH
scopeReference = releaseSnapshotId
evidenceReference = releaseBundleDigest
```

Changing the proposal, release plan, selected version, release snapshot, or bundle invalidates the approval for the new release.

## Decision behavior

| Governance gate result | Review evidence | Publication authorization |
| --- | --- | --- |
| `allowed` | not required | allowed by governance |
| `review_required` | missing | denied: approval required |
| `review_required` | exact `APPROVE` | allowed by review |
| `review_required` | `REJECT` / `REQUEST_CHANGES` | denied |
| `review_required` | stale or mismatched | denied |
| `blocked` | any | denied; review cannot override BLOCK |

`GovernanceGateResult` remains authoritative for whether publication is already allowed, requires review, or is blocked. ContractOps authorization satisfies the review requirement; it does not re-run policy.

## Explicit evidence, not comment parsing

ContractOps consumes structured `ReviewAuthorizationEvidence`. The evidence reference and scope reference are opaque identifiers whose exact values are produced by the release workflow.

This layer does not parse human comments, PR text, Slack messages, or similar free-form content. `ApprovalRecord` is the durable structured fact; Git history is an audit/conflict ledger and the exact approval artifact is the preferred CI/CD handoff.

## Runtime deployment is a separate trust boundary

A `ContractRelease` proves what was formally released. It does not grant permission to mutate a runtime.

SemaPact does not create a `DeploymentAuthorization` artifact. Runtime execution permission belongs to the surrounding protected CI/CD environment, such as a GitHub or Azure DevOps Environment. The deployment domain instead validates exact source/plan provenance, re-observes runtime state, derives a fresh preview, applies only supported transitions, and verifies convergence.

Candidate deployment likewise does not create release approval or release history. `BLOCK` fails closed; `REVIEW` may still be used for non-release validation/test deployment because no formal publication occurs.

## Invalid context vs denied publication

SemaPact distinguishes malformed release composition from a valid release that lacks required approval.

If `GovernanceDecision`, `ChangeSet`, `ReleasePlan`, and `VersionResolution` do not refer to the same immutable release context, authorization fails closed with a validation error.

If the release context is valid but required PUBLISH evidence is missing, rejected, stale, or mismatched, SemaPact returns a deterministic `ContractOpsAuthorization` with `allowed=false` and a machine-readable reason.

## Non-goals

This boundary does not implement approval persistence mechanics, reviewer routing, quorum, IAM/SSO, approval UI, GitHub review parsing, runtime deployment permission, or BLOCK overrides.
