"""M2 ContractOps domain."""

from semapact.contractops.authorization import authorize_contract_operation
from semapact.contractops.changeset import (
    build_change_set,
    build_change_set_from_decision,
)
from semapact.contractops.execution import build_release_snapshot
from semapact.contractops.execution_models import (
    ContractRelease,
    ReleaseSnapshot,
)
from semapact.contractops.integrity import (
    validate_contract_release_identity,
    validate_release_snapshot_identity,
    validate_change_set_identity,
    validate_contractops_authorization_identity,
    validate_release_plan_identity,
    validate_version_resolution_identity,
)
from semapact.contractops.models import (
    AuthorizationReason,
    ChangeSet,
    ContractOpsAuthorization,
    ReleasePlan,
    ReleasePrecondition,
    ReviewAuthorizationEvidence,
    ReviewEvidenceAction,
    VersionAuthority,
    VersionAuthorityConfig,
    VersionResolution,
)
from semapact.contractops.release_plan import build_release_plan
from semapact.contractops.version_authority import (
    extract_version_from_release_reference,
    resolve_release_version,
)

__all__ = [
    "ContractRelease",
    "ReleaseSnapshot",
    "AuthorizationReason",
    "ChangeSet",
    "ContractOpsAuthorization",
    "ReleasePlan",
    "ReleasePrecondition",
    "ReviewAuthorizationEvidence",
    "ReviewEvidenceAction",
    "VersionAuthority",
    "VersionAuthorityConfig",
    "VersionResolution",
    "build_release_snapshot",
    "authorize_contract_operation",
    "build_change_set",
    "build_change_set_from_decision",
    "build_release_plan",
    "extract_version_from_release_reference",
    "resolve_release_version",
    "validate_contract_release_identity",
    "validate_release_snapshot_identity",
    "validate_change_set_identity",
    "validate_contractops_authorization_identity",
    "validate_release_plan_identity",
    "validate_version_resolution_identity",
]
