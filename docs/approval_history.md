# Approval history intake

SemaPact records explicit review actions as immutable `ApprovalRecord` artifacts.
Approval history is an audit and authorization-evidence primitive; it is not a workflow
engine and does not decide who should review, which reviewer wins, or whether a quorum
has been reached.

## Intake boundary

The canonical path is:

```text
GitHub / GitLab / Azure DevOps review event
                 ↓
        trusted CI / adapter
                 ↓
      ApprovalRecordService
                 ↓
           ApprovalRecord
                 ↓
      ApprovalHistoryRepository
                 ↓
        .semapact/history/
```

`ApprovalRecordService` is deliberately named after the artifact it manages. It records
and queries approval evidence; it does not itself approve a change, select a reviewer,
or grant authorization.

The external provider owns the review interaction. SemaPact records the explicit fact
that the provider supplied: actor, action, provider timestamp, exact ContractOps scope,
and stable evidence references.

A Git commit is not approval evidence by itself. For Git-hosted workflows, the approval
fact normally comes from the pull-request review API/event and is then recorded by CI.

Persisting a record also does not by itself authorize an operation. One explicitly
selected `ApprovalRecord` can be projected into `ReviewAuthorizationEvidence`, after
which existing M2 ContractOps authorization validates the exact decision, ChangeSet,
ReleasePlan, VersionResolution, operation, scope, and action.

## CLI

CI can record an explicit provider review through the application API exposed by the
CLI:

```bash
semapact approval record \
  --repository-root . \
  --decision-id "$SEMAPACT_DECISION_ID" \
  --change-set-id "$SEMAPACT_CHANGE_SET_ID" \
  --release-plan-id "$SEMAPACT_RELEASE_PLAN_ID" \
  --version-resolution-id "$SEMAPACT_VERSION_RESOLUTION_ID" \
  --operation PUBLISH \
  --action APPROVE \
  --actor-reference "github:user:${REVIEWER}" \
  --recorded-at "$REVIEW_SUBMITTED_AT" \
  --capability-reference "github:team:data-owners" \
  --evidence-reference "github:repo:${REPOSITORY}:pull:${PR_NUMBER}:review:${REVIEW_ID}"
```

`--recorded-at` is required and must be timezone-aware. SemaPact intentionally does not
substitute the local execution time because the review event timestamp is part of the
audit fact and deterministic approval identity.

`--evidence-reference` may be repeated. References should be stable provider-local
identifiers or URIs that allow an auditor to trace the recorded event back to its
source.

The Git working-tree backend writes the resulting immutable record under
`.semapact/history/`. Committing or otherwise publishing those generated history files
remains the responsibility of the surrounding GitOps workflow; the approval command
does not push branches or bypass repository protections.

## Python SDK

The same application API is available from the public Python package:

```python
from datetime import datetime, timezone

from semapact import ApprovalRecordService
from semapact.contractops import ReviewEvidenceAction
from semapact.governance import GovernanceOperation
from semapact.platforms.git import GitWorkingTreeHistoryRepository

service = ApprovalRecordService(GitWorkingTreeHistoryRepository("."))
record = service.record_review_action(
    decision_id="...",
    change_set_id="...",
    release_plan_id="...",
    version_resolution_id="...",
    operation=GovernanceOperation.PUBLISH,
    action=ReviewEvidenceAction.APPROVE,
    actor_reference="github:user:alice",
    recorded_at=datetime.now(timezone.utc),
    capability_reference="github:team:data-owners",
    evidence_references=("github:repo:org/repo:pull:42:review:1001",),
)
```

Callers using another future persistence backend can provide the same
`ApprovalHistoryRepository` capability without changing `ApprovalRecordService`.

## Deployment approval resolution

For a **formal REVIEW release** (`DeploymentBundle.release=true`), callers do not have to pass an approval file explicitly. Candidate/non-release deployments never create or resolve release approval records.

When `semapact deployment deploy --bundle ...` receives a formal REVIEW release bundle without `--approval`, the CLI queries Git-backed approval history under `.semapact/history/approval_records` and resolves only records that match all of the following:

- exact `decisionId`;
- exact `changeSetId`;
- exact `releasePlanId`;
- exact `versionResolutionId`;
- operation `DEPLOY`;
- exact `deploymentPlanId` as scope;
- exact `bundleDigest` in evidence references.

A matching `APPROVE` record can therefore be recorded by a trusted GitHub/Azure DevOps/GitLab integration before CD begins, while `deployment deploy` consumes it automatically.

If exact scoped history contains conflicting review actions such as `REQUEST_CHANGES` or `REJECT`, resolution fails closed. SemaPact does not apply a hidden "latest review wins" rule.

Passing `--approval <record.json>` remains supported for custom/manual formal-release workflows and takes precedence over Git-history lookup. Supplying an approval to a non-release deployment is rejected.

## Trust boundary

`ApprovalRecord` preserves review evidence; it is not an authentication credential.
The intake adapter or CI workflow is responsible for obtaining review facts from a
trusted provider context. SemaPact does not infer approval from free-text comments,
commit messages, or an arbitrary `LGTM` string.

Likewise, this layer does not introduce `latest approval wins`, quorum, reviewer
precedence, routing, or escalation policy. Those are separate workflow concerns and
must not be hidden inside persistence or history queries.
