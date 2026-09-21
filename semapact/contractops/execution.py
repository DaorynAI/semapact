"""Pure ContractOps release snapshot construction."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.contractops.context import validate_release_context
from semapact.contractops.execution_models import ReleaseSnapshot
from semapact.contractops.integrity import compute_release_snapshot_id
from semapact.contractops.models import (
    ChangeSet,
    ReleasePlan,
    VersionResolution,
)
from semapact.exceptions import ReleaseValidationError
from semapact.governance.models import GovernanceDecision
from semapact.odcs.serialization import canonical_contract_json
from semapact.versioning import normalize_semver


def build_release_snapshot(
    candidate_contract: OpenDataContractStandard,
    *,
    candidate_revision_ref: str,
    decision: GovernanceDecision,
    change_set: ChangeSet,
    release_plan: ReleasePlan,
    version_resolution: VersionResolution,
) -> ReleaseSnapshot:
    """Freeze one exact governed release without requiring side-effect authorization."""
    if not isinstance(candidate_contract, OpenDataContractStandard):
        raise TypeError(
            "candidate_contract must be OpenDataContractStandard, "
            f"got {type(candidate_contract).__name__}"
        )
    if not isinstance(candidate_revision_ref, str):
        raise TypeError("candidate_revision_ref must be str")

    validate_release_context(decision, change_set, release_plan, version_resolution)

    supplied_revision_ref = candidate_revision_ref.strip()
    if not supplied_revision_ref:
        raise ReleaseValidationError("candidate_revision_ref must not be empty")
    if supplied_revision_ref != release_plan.release_revision_ref:
        raise ReleaseValidationError(
            "Supplied candidate revision does not match the planned release revision"
        )

    if str(candidate_contract.id or "") != release_plan.contract_id:
        raise ReleaseValidationError(
            "Candidate contract ID does not match the planned release contract"
        )

    current_version = _canonical_version(
        version_resolution.current_version,
        field_name="VersionResolution current_version",
    )
    selected_version = _canonical_version(
        version_resolution.selected_version,
        field_name="VersionResolution selected_version",
    )
    candidate_version = _canonical_version(
        str(candidate_contract.version or ""),
        field_name="candidate contract version",
    )
    if candidate_version != current_version:
        raise ReleaseValidationError(
            "Candidate contract version does not match VersionResolution current_version"
        )

    released_contract = candidate_contract.model_copy(deep=True)
    released_contract.version = selected_version
    released_contract_json = canonical_contract_json(released_contract)

    release_snapshot_id = compute_release_snapshot_id(
        contract_id=release_plan.contract_id,
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        release_revision_ref=release_plan.release_revision_ref,
        selected_version=selected_version,
        released_contract_json=released_contract_json,
    )
    return ReleaseSnapshot(
        release_snapshot_id=release_snapshot_id,
        contract_id=release_plan.contract_id,
        decision_id=decision.decision_id,
        change_set_id=change_set.change_set_id,
        release_plan_id=release_plan.release_plan_id,
        version_resolution_id=version_resolution.version_resolution_id,
        release_revision_ref=release_plan.release_revision_ref,
        selected_version=selected_version,
        released_contract_json=released_contract_json,
    )
