"""Construction helpers for canonical contract revision artifacts."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.odcs.serialization import canonical_contract_json
from semapact.revision.integrity import (
    compute_contract_content_fingerprint,
    compute_contract_revision_id,
    compute_contract_revision_source_id,
    validate_contract_revision_identity,
    validate_contract_revision_source_identity,
)
from semapact.revision.models import ContractRevision, ContractRevisionSource


def build_contract_revision(contract: OpenDataContractStandard) -> ContractRevision:
    """Build a revision envelope around one exact canonical ODCS contract snapshot."""
    if not isinstance(contract, OpenDataContractStandard):
        raise TypeError(
            "contract must be OpenDataContractStandard, "
            f"got {type(contract).__name__}"
        )

    canonical = canonical_contract_json(contract)
    contract_snapshot = OpenDataContractStandard.model_validate_json(canonical)
    fingerprint = compute_contract_content_fingerprint(canonical)

    revision = ContractRevision(
        revision_id=compute_contract_revision_id(fingerprint),
        content_fingerprint=fingerprint,
        contract=contract_snapshot,
    )
    validate_contract_revision_identity(revision)
    return revision


def link_contract_revision_source(
    revision: ContractRevision,
    *,
    source_reference: str,
) -> ContractRevisionSource:
    """Build one immutable provenance link without changing revision identity."""
    validate_contract_revision_identity(revision)
    source = ContractRevisionSource(
        source_link_id=compute_contract_revision_source_id(
            revision_id=revision.revision_id,
            source_reference=source_reference,
        ),
        revision_id=revision.revision_id,
        source_reference=source_reference,
    )
    validate_contract_revision_source_identity(source)
    return source
