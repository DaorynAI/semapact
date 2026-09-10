# ContractOps review authorization

SemaPact keeps governance classification and review authorization as separate immutable facts.

```text
GovernanceDecision(REVIEW)
        +
exact version-resolved release context
        +
matching explicit approval evidence
        ↓
ContractOpsAuthorization(allowed=true)
```

The original `GovernanceDecision` remains `REVIEW`. Approval never rewrites it to `ALLOW`.

## Why authorization happens after version resolution

A review must authorize the release that will actually be executed, not an earlier approximation of it.

```text
GovernanceDecision
→ ChangeSet
→ ReleasePlan
→ VersionResolution
→ ContractOpsAuthorization
→ APPLY / PUBLISH / DEPLOY
```

Review evidence is scoped to all of:

```text
decisionId
changeSetId
releasePlanId
versionResolutionId
operation
scopeReference?   # optional downstream scope
```

Changing the proposal, release plan, selected version, requested operation, or an explicitly bound downstream scope invalidates the evidence for that new action.

## Decision behavior

| Governance gate result | Review evidence | Authorization |
| --- | --- | --- |
| `allowed` | not required | allowed by governance |
| `review_required` | missing | denied: authorization required |
| `review_required` | exact `APPROVE` | allowed by review |
| `review_required` | `REJECT` / `REQUEST_CHANGES` | denied |
| `review_required` | stale or mismatched | denied |
| `blocked` | any | denied; review cannot override BLOCK |

`GovernanceGateResult` remains authoritative for whether the operation is already allowed, requires review, or is blocked. ContractOps authorization only satisfies `review_required`; it does not re-run policy.

## Explicit evidence, not comment parsing

ContractOps consumes structured evidence:

```text
ReviewAuthorizationEvidence
├── evidenceReference
├── decisionId
├── changeSetId
├── releasePlanId
├── versionResolutionId
├── operation
├── scopeReference?
└── action
```

`evidenceReference` is opaque. `scopeReference`, when present, is also opaque to ContractOps and may be used by a downstream boundary to bind approval to an exact target-specific artifact such as a deployment plan.

This layer does not store approvals or infer approval from human comments, PR text, Slack messages, or similar free-form content. Durable review history and reviewer workflow are separate persistence/application concerns and can project structured evidence into this boundary without changing its authorization semantics.

## Operation scope

Approval is not a generic bypass token.

```text
approval for APPLY
≠ approval for PUBLISH
≠ approval for DEPLOY
```

Likewise, approval for one `VersionResolution` does not authorize a different selected version.

Runtime deployment adds another scope boundary: a review-required deployment must bind approval to the exact `DeploymentPlan`, so approval for one runtime target cannot be rebound to another target.

## Invalid context vs denied authorization

SemaPact distinguishes malformed artifact composition from a valid release that simply lacks approval.

If `GovernanceDecision`, `ChangeSet`, `ReleasePlan`, and `VersionResolution` do not refer to the same immutable release context, authorization fails closed with a validation error.

If the release context is valid but evidence is missing, rejected, stale, or mismatched, SemaPact returns a deterministic `ContractOpsAuthorization` with `allowed=false` and a machine-readable reason.

This lets APPLY, PUBLISH, and DEPLOY boundaries consume one authoritative release-context authorization result without implementing their own approval rules.

## Non-goals

This boundary does not implement approval persistence, reviewer routing, quorum, IAM/SSO, approval UI, GitHub review parsing, or BLOCK overrides.
