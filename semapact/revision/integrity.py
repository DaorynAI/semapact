"""Deterministic identity rules for governed contract revisions."""

from __future__ import annotations

import hashlib
import re
import uuid

from semapact.revision.models import ContractRevision, ContractRevisionSource
from semapact.utils.contracts import canonical_contract_json
from semapact.utils.deterministic import deterministic_uuid5


SEMAPACT_CONTRACT_REVISION_NAMESPACE = uuid.UUID(
    "53dc6172-6f46-46b1-a9d6-f7d967b0635c"
)
SEMAPACT_CONTRACT_REVISION_SOURCE_NAMESPACE = uuid.UUID(
    "81b9275f-02b6-447b-b219-c355119a78d5"
)
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def compute_contract_content_fingerprint(canonical_json: str) -> str:
    """Return SHA-256 over the exact canonical contract JSON bytes."""
    if not isinstance(canonical_json, str):
        raise TypeError("canonical_json must be str")
    if not canonical_json:
        raise ValueError("canonical_json must not be empty")
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_contract_revision_id(content_fingerprint: str) -> str:
    """Return the stable UUIDv5 identity for one content fingerprint."""
    _require_sha256_hex(content_fingerprint)
    return deterministic_uuid5(
        SEMAPACT_CONTRACT_REVISION_NAMESPACE,
        {"contentFingerprint": content_fingerprint},
    )


def compute_contract_revision_source_id(
    *,
    revision_id: str,
    source_reference: str,
) -> str:
    """Return deterministic identity for one revision-to-source provenance link."""
    revision_id = _require_canonical_text(revision_id, "revision_id")
    source_reference = _require_canonical_text(source_reference, "source_reference")
    return deterministic_uuid5(
        SEMAPACT_CONTRACT_REVISION_SOURCE_NAMESPACE,
        {
            "revisionId": revision_id,
            "sourceReference": source_reference,
        },
    )


def validate_contract_revision_identity(revision: ContractRevision) -> None:
    """Fail if a revision's derived identity does not match its exact ODCS state."""
    if not isinstance(revision, ContractRevision):
        raise TypeError(
            f"revision must be ContractRevision, got {type(revision).__name__}"
        )

    _require_canonical_text(str(revision.contract.id or ""), "contract.id")
    _require_canonical_text(str(revision.contract.version or ""), "contract.version")

    canonical = canonical_contract_json(revision.contract)
    expected_fingerprint = compute_contract_content_fingerprint(canonical)
    if expected_fingerprint != revision.content_fingerprint:
        raise ValueError("content_fingerprint does not match canonical contract content")

    expected_revision_id = compute_contract_revision_id(expected_fingerprint)
    if expected_revision_id != revision.revision_id:
        raise ValueError("revision_id does not match deterministic content identity")


def validate_contract_revision_source_identity(source: ContractRevisionSource) -> None:
    """Fail if a provenance link ID does not match its revision/source pair."""
    if not isinstance(source, ContractRevisionSource):
        raise TypeError(
            "source must be ContractRevisionSource, "
            f"got {type(source).__name__}"
        )
    expected = compute_contract_revision_source_id(
        revision_id=source.revision_id,
        source_reference=source.source_reference,
    )
    if expected != source.source_link_id:
        raise ValueError("source_link_id does not match deterministic provenance identity")


def _require_sha256_hex(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("content_fingerprint must be str")
    if value != value.strip().lower() or not _SHA256_HEX.fullmatch(value):
        raise ValueError("content_fingerprint must be a lowercase SHA-256 hex digest")


def _require_canonical_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty canonical text")
    return value
