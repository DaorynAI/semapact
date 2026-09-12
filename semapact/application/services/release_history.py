"""Application orchestration for finalized contract release history."""

from __future__ import annotations

from semapact.contractops.context import validate_release_context
from semapact.contractops.execution_models import AppliedContractRelease
from semapact.contractops.integrity import (
    validate_applied_release_identity,
    validate_contractops_authorization_identity,
)
from semapact.contractops.models import (
    ContractOpsAuthorization,
    ReleasePlan,
    VersionResolution,
)
from semapact.governance.gate import GovernanceOperation
from semapact.history import (
    ChangeSetDecisionLinkHistoryRepository,
    ChangeSetHistoryRepository,
    ContractRevisionHistoryRepository,
    DecisionHistoryRepository,
    ReleasePlanHistoryRepository,
    ReleaseRecord,
    ReleaseRecordHistoryRepository,
)
from semapact.history.integrity import compute_release_record_id
from semapact.revision import build_contract_revision
from semapact.revision.integrity import validate_contract_revision_identity


class ReleaseHistoryService:
    """Record one already-applied release without recomputing release semantics."""

    def __init__(
        self,
        *,
        revisions: ContractRevisionHistoryRepository,
        change_sets: ChangeSetHistoryRepository,
        decisions: DecisionHistoryRepository,
        decision_links: ChangeSetDecisionLinkHistoryRepository,
        release_plans: ReleasePlanHistoryRepository,
        release_records: ReleaseRecordHistoryRepository,
    ) -> None:
        self._revisions = revisions
        self._change_sets = change_sets
        self._decisions = decisions
        self._decision_links = decision_links
        self._release_plans = release_plans
        self._release_records = release_records

    def record_release(
        self,
        *,
        release_plan: ReleasePlan,
        version_resolution: VersionResolution,
        authorization: ContractOpsAuthorization,
        applied_release: AppliedContractRelease,
    ) -> ReleaseRecord:
        """Persist the exact proposal → plan → released-revision audit chain.

        All supplied ContractOps artifacts must already exist as valid outputs from
        their owning M2 stages. This use case validates linkage only; it never reruns
        governance, version authority, authorization, or APPLY.
        """
        decision = self._decisions.get_decision(release_plan.decision_id)
        change_set = self._change_sets.get_change_set(release_plan.change_set_id)
        candidate_revision = self._revisions.get_revision(release_plan.release_revision_ref)

        _require_decision_link(
            self._decision_links,
            change_set_id=change_set.change_set_id,
            decision_id=decision.decision_id,
        )
        validate_contract_revision_identity(candidate_revision)
        validate_release_context(
            decision,
            change_set,
            release_plan,
            version_resolution,
        )
        _validate_candidate_revision(candidate_revision, release_plan, version_resolution)
        _validate_apply_authorization(
            authorization,
            release_plan=release_plan,
            version_resolution=version_resolution,
        )
        _validate_applied_release(
            applied_release,
            release_plan=release_plan,
            version_resolution=version_resolution,
            authorization=authorization,
        )

        released_revision = build_contract_revision(applied_release.to_contract())
        if released_revision.revision_id == candidate_revision.revision_id:
            raise ValueError(
                "released revision must differ from candidate revision after APPLY versioning"
            )

        record_id = compute_release_record_id(
            contract_id=release_plan.contract_id,
            contract_version=version_resolution.selected_version,
            decision_id=release_plan.decision_id,
            change_set_id=release_plan.change_set_id,
            release_plan_id=release_plan.release_plan_id,
            version_resolution_id=version_resolution.version_resolution_id,
            authorization_id=authorization.authorization_id,
            applied_release_id=applied_release.applied_release_id,
            released_revision_id=released_revision.revision_id,
            required_version_bump=version_resolution.required_version_bump,
            actual_version_bump=version_resolution.actual_bump,
            version_authority=version_resolution.authority.value,
            authority_reference=version_resolution.authority_reference,
            review_evidence_reference=authorization.evidence_reference,
            review_evidence_action=(
                authorization.evidence_action.value
                if authorization.evidence_action is not None
                else None
            ),
        )
        record = ReleaseRecord(
            release_record_id=record_id,
            contract_id=release_plan.contract_id,
            contract_version=version_resolution.selected_version,
            decision_id=release_plan.decision_id,
            change_set_id=release_plan.change_set_id,
            release_plan_id=release_plan.release_plan_id,
            version_resolution_id=version_resolution.version_resolution_id,
            authorization_id=authorization.authorization_id,
            applied_release_id=applied_release.applied_release_id,
            released_revision_id=released_revision.revision_id,
            required_version_bump=version_resolution.required_version_bump,
            actual_version_bump=version_resolution.actual_bump,
            version_authority=version_resolution.authority,
            authority_reference=version_resolution.authority_reference,
            review_evidence_reference=authorization.evidence_reference,
            review_evidence_action=authorization.evidence_action,
        )

        # Persist referenced artifacts before the final record so a partial failure
        # cannot leave a ReleaseRecord pointing at absent release/revision history.
        self._release_plans.put_release_plan(release_plan)
        self._revisions.put_revision(released_revision)
        self._release_records.put_release_record(record)
        return record


def _require_decision_link(
    repository: ChangeSetDecisionLinkHistoryRepository,
    *,
    change_set_id: str,
    decision_id: str,
) -> None:
    links = repository.list_change_set_decision_links(change_set_id)
    if not any(link.decision_id == decision_id for link in links):
        raise ValueError(
            "release history requires the ChangeSet-to-GovernanceDecision history link"
        )


def _validate_candidate_revision(
    candidate_revision,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
) -> None:
    contract_id = str(candidate_revision.contract.id or "").strip()
    contract_version = str(candidate_revision.contract.version or "").strip()
    if contract_id != release_plan.contract_id:
        raise ValueError("candidate ContractRevision does not match ReleasePlan contract")
    if contract_version != version_resolution.current_version:
        raise ValueError(
            "candidate ContractRevision version does not match VersionResolution current_version"
        )


def _validate_apply_authorization(
    authorization: ContractOpsAuthorization,
    *,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
) -> None:
    validate_contractops_authorization_identity(authorization)
    if authorization.operation is not GovernanceOperation.APPLY:
        raise ValueError("release history requires APPLY-scoped authorization")
    if not authorization.allowed:
        raise ValueError("release history requires an allowed APPLY authorization")
    if (
        authorization.decision_id != release_plan.decision_id
        or authorization.change_set_id != release_plan.change_set_id
        or authorization.release_plan_id != release_plan.release_plan_id
        or authorization.version_resolution_id != version_resolution.version_resolution_id
    ):
        raise ValueError("APPLY authorization does not match the exact release context")


def _validate_applied_release(
    applied_release: AppliedContractRelease,
    *,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
    authorization: ContractOpsAuthorization,
) -> None:
    validate_applied_release_identity(applied_release)
    if (
        applied_release.contract_id != release_plan.contract_id
        or applied_release.decision_id != release_plan.decision_id
        or applied_release.change_set_id != release_plan.change_set_id
        or applied_release.release_plan_id != release_plan.release_plan_id
        or applied_release.version_resolution_id != version_resolution.version_resolution_id
        or applied_release.release_revision_ref != release_plan.release_revision_ref
        or applied_release.selected_version != version_resolution.selected_version
        or applied_release.authorization_id != authorization.authorization_id
    ):
        raise ValueError("AppliedContractRelease does not match the exact release context")
