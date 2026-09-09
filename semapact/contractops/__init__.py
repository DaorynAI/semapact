"""M2 ContractOps domain."""

from semapact.contractops.changeset import (
    build_change_set,
    build_change_set_from_decision,
)
from semapact.contractops.models import (
    ChangeSet,
    ReleasePlan,
    ReleasePrecondition,
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
    "ChangeSet",
    "ReleasePlan",
    "ReleasePrecondition",
    "VersionAuthority",
    "VersionAuthorityConfig",
    "VersionResolution",
    "build_change_set",
    "build_change_set_from_decision",
    "build_release_plan",
    "extract_version_from_release_reference",
    "resolve_release_version",
]
