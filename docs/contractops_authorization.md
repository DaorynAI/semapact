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
→ APPLY / PUBLISH
```

Review evidence is therefore scoped to all of:

```text
decisionId
changeSetId
releasePlanId
versionResolutionId
operation
```

Changing the proposal, release plan, selected version, or requested operation invalidates the evidence for that new action.

## Decision behavior

| Governance gate result | Review evidence | Authorization |
| --- | --- | --- |
| `allowed` | not required | allowed by governance |
| `review_required` | missing | denied: authorization required |
| `review_required` | exact `APPROVE` | allowed by review |
| `review_required` | `REJECT` / `REQUEST_CHANGES` | denied |
| `review_required` | stale or mismatched | denied |
| `blocked` | any | denied; review cannot override BLOCK |

M0 `GovernanceGateResult` remains authoritative for whether the operation is already allowed, requires review, or is blocked. ContractOps authorization only satisfies `review_required`; it does not re-run policy.

## Explicit evidence, not comment parsing

M2 consumes structured evidence:

```text
ReviewAuthorizationEvidence
├── evidenceReference
├── decisionId
├── changeSetId
├── releasePlanId
├── versionResolutionId
├── operation
└── action
```

`evidenceReference` is opaque. This layer does not store approvals or infer approval from human comments, PR text, Slack messages, or similar free-form content.

Future durable review history belongs to M3. A persisted `ApprovalRecord` can later be resolved/projected into `ReviewAuthorizationEvidence` without changing the ContractOps authorization semantics.

## Operation scope

Approval is not a generic bypass token.

```text
approval for APPLY
≠ approval for PUBLISH
```

Likewise, approval for one `VersionResolution` does not authorize a different selected version.

## Invalid context vs denied authorization

SemaPact distinguishes malformed artifact composition from a valid release that simply lacks approval.

If `GovernanceDecision`, `ChangeSet`, `ReleasePlan`, and `VersionResolution` do not refer to the same immutable release context, authorization fails closed with a validation error.

If the release context is valid but evidence is missing, rejected, stale, or mismatched, SemaPact returns a deterministic `ContractOpsAuthorization` with `allowed=false` and a machine-readable reason.

This lets later APPLY/PUBLISH boundaries consume one authoritative authorization result without implementing their own approval rules.

## Non-goals

This boundary does not implement approval persistence, reviewer routing, quorum, IAM/SSO, approval UI, GitHub review parsing, or BLOCK overrides.
