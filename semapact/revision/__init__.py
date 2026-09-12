"""Governed contract revision identity domain."""

from semapact.revision.builders import (
    build_contract_revision,
    link_contract_revision_source,
)
from semapact.revision.integrity import (
    SEMAPACT_CONTRACT_REVISION_NAMESPACE,
    SEMAPACT_CONTRACT_REVISION_SOURCE_NAMESPACE,
    compute_contract_content_fingerprint,
    compute_contract_revision_id,
    compute_contract_revision_source_id,
    validate_contract_revision_identity,
    validate_contract_revision_source_identity,
)
from semapact.revision.models import ContractRevision, ContractRevisionSource

__all__ = [
    "ContractRevision",
    "ContractRevisionSource",
    "SEMAPACT_CONTRACT_REVISION_NAMESPACE",
    "SEMAPACT_CONTRACT_REVISION_SOURCE_NAMESPACE",
    "build_contract_revision",
    "compute_contract_content_fingerprint",
    "compute_contract_revision_id",
    "compute_contract_revision_source_id",
    "link_contract_revision_source",
    "validate_contract_revision_identity",
    "validate_contract_revision_source_identity",
]
