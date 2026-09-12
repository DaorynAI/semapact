"""Construction helpers for canonical contract revision artifacts."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.revision.integrity import (
    compute_contract_content_fingerprint,
    compute_contract_revision_id,
    compute_contract_revision_source_id,
    validate_contract_revision_identity,
)
from semapact.revision.models import ContractRevision, ContractRevisionSource
from semapact.utils.contracts import canonical_contract_json


def build_contract_revision(contract: OpenDataContractStandard) -> ContractRevision:
    """Build the immutable content identity for one exact ODCS contract state."""
    if not isinstance(contract, OpenDataContractStandard):
        raise TypeError(
            "contract must be OpenDataContractStandard, "
            f"got {type(contract).__name__}"
        )

    canonical = canonical_contract_json(contract)
    contract_id = _canonical_text(str(contract.id or ""), "contract.id")
    contract_version = _canonical_text(str(contract.version or ""), "contract.version")
    fingerprint = compute_contract_content_fingerprint(canonical)

    revision = ContractRevision(
        revision_id=compute_contract_revision_id(fingerprint),
        contract_id=contract_id,
        contract_version=contract_version,
        content_fingerprint=fingerprint,
        canonical_contract_json=canonical,
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
    source_reference = _canonical_text(source_reference, "source_reference")
    return ContractRevisionSource(
        source_link_id=compute_contract_revision_source_id(
            revision_id=revision.revision_id,
            source_reference=source_reference,
        ),
        revision_id=revision.revision_id,
        source_reference=source_reference,
    )


def _canonical_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
