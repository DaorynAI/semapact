"""M2 ContractOps domain."""

from semapact.contractops.authorization import authorize_contract_operation
from semapact.contractops.changeset import (
    build_change_set,
    build_change_set_from_decision,
)
from semapact.contractops.execution import (
    ContractReleasePublisher,
    apply_contract_release,
    publish_contract_release,
)
from semapact.contractops.execution_models import (
    AppliedContractRelease,
    PublicationResult,
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
    "AppliedContractRelease",
    "AuthorizationReason",
    "ChangeSet",
    "ContractOpsAuthorization",
    "ContractReleasePublisher",
    "PublicationResult",
    "ReleasePlan",
    "ReleasePrecondition",
    "ReviewAuthorizationEvidence",
    "ReviewEvidenceAction",
    "VersionAuthority",
    "VersionAuthorityConfig",
    "VersionResolution",
    "apply_contract_release",
    "authorize_contract_operation",
    "build_change_set",
    "build_change_set_from_decision",
    "build_release_plan",
    "extract_version_from_release_reference",
    "publish_contract_release",
    "resolve_release_version",
]
