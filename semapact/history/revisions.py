"""Immutable content identity for governed ODCS contract states."""

from __future__ import annotations

import hashlib
import re
import uuid

from open_data_contract_standard.model import OpenDataContractStandard
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError as PydanticValidationError,
    field_validator,
    model_validator,
)

from semapact.utils.contracts import canonical_contract_json
from semapact.utils.deterministic import deterministic_uuid5


SEMAPACT_CONTRACT_REVISION_NAMESPACE = uuid.UUID(
    "53dc6172-6f46-46b1-a9d6-f7d967b0635c"
)
SEMAPACT_CONTRACT_REVISION_SOURCE_NAMESPACE = uuid.UUID(
    "81b9275f-02b6-447b-b219-c355119a78d5"
)
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class ContractRevision(BaseModel):
    """Immutable governed contract state identified only by canonical content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    revision_id: str
    contract_id: str
    contract_version: str
    content_fingerprint: str
    canonical_contract_json: str

    @field_validator("revision_id", "contract_id", "contract_version")
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("content_fingerprint")
    @classmethod
    def _validate_fingerprint_shape(cls, value: str) -> str:
        if value != value.strip().lower() or not _SHA256_HEX.fullmatch(value):
            raise ValueError("content_fingerprint must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("canonical_contract_json")
    @classmethod
    def _require_canonical_json(cls, value: str) -> str:
        if not value:
            raise ValueError("canonical_contract_json must not be empty")
        return value

    @model_validator(mode="after")
    def _validate_content_identity(self) -> ContractRevision:
        try:
            contract = OpenDataContractStandard.model_validate_json(
                self.canonical_contract_json
            )
        except PydanticValidationError as exc:
            raise ValueError("canonical_contract_json is not a valid ODCS contract") from exc

        canonical = canonical_contract_json(contract)
        if canonical != self.canonical_contract_json:
            raise ValueError("canonical_contract_json is not in canonical form")

        contract_id = str(contract.id or "").strip()
        contract_version = str(contract.version or "").strip()
        if contract_id != self.contract_id:
            raise ValueError("contract_id does not match canonical contract content")
        if contract_version != self.contract_version:
            raise ValueError("contract_version does not match canonical contract content")

        expected_fingerprint = compute_contract_content_fingerprint(canonical)
        if expected_fingerprint != self.content_fingerprint:
            raise ValueError("content_fingerprint does not match canonical contract content")

        expected_revision_id = compute_contract_revision_id(expected_fingerprint)
        if expected_revision_id != self.revision_id:
            raise ValueError("revision_id does not match deterministic content identity")
        return self


class ContractRevisionSource(BaseModel):
    """Immutable provenance link from one revision to one opaque source reference.

    Source provenance is intentionally separate from ContractRevision identity so the
    same governed content can be observed from multiple Git or external references
    without rewriting the revision artifact.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_link_id: str
    revision_id: str
    source_reference: str

    @field_validator("source_link_id", "revision_id", "source_reference")
    @classmethod
    def _require_source_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_source_identity(self) -> ContractRevisionSource:
        expected = compute_contract_revision_source_id(
            revision_id=self.revision_id,
            source_reference=self.source_reference,
        )
        if expected != self.source_link_id:
            raise ValueError("source_link_id does not match deterministic provenance identity")
        return self


def compute_contract_content_fingerprint(canonical_json: str) -> str:
    """Return SHA-256 over the exact canonical contract JSON bytes."""
    if not isinstance(canonical_json, str):
        raise TypeError("canonical_json must be str")
    if not canonical_json:
        raise ValueError("canonical_json must not be empty")
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_contract_revision_id(content_fingerprint: str) -> str:
    """Return the stable UUIDv5 identity for one content fingerprint."""
    if (
        content_fingerprint != content_fingerprint.strip().lower()
        or not _SHA256_HEX.fullmatch(content_fingerprint)
    ):
        raise ValueError("content_fingerprint must be a lowercase SHA-256 hex digest")
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
    revision_id = _required_text(revision_id, "revision_id")
    source_reference = _required_text(source_reference, "source_reference")
    return deterministic_uuid5(
        SEMAPACT_CONTRACT_REVISION_SOURCE_NAMESPACE,
        {
            "revisionId": revision_id,
            "sourceReference": source_reference,
        },
    )


def build_contract_revision(contract: OpenDataContractStandard) -> ContractRevision:
    """Create the immutable content identity for one exact ODCS contract state."""
    canonical = canonical_contract_json(contract)
    contract_id = _required_text(str(contract.id or ""), "contract.id")
    contract_version = _required_text(str(contract.version or ""), "contract.version")
    fingerprint = compute_contract_content_fingerprint(canonical)
    return ContractRevision(
        revision_id=compute_contract_revision_id(fingerprint),
        contract_id=contract_id,
        contract_version=contract_version,
        content_fingerprint=fingerprint,
        canonical_contract_json=canonical,
    )


def link_contract_revision_source(
    revision: ContractRevision,
    *,
    source_reference: str,
) -> ContractRevisionSource:
    """Create one immutable provenance link without changing revision identity."""
    if not isinstance(revision, ContractRevision):
        raise TypeError(
            f"revision must be ContractRevision, got {type(revision).__name__}"
        )
    source_reference = _required_text(source_reference, "source_reference")
    return ContractRevisionSource(
        source_link_id=compute_contract_revision_source_id(
            revision_id=revision.revision_id,
            source_reference=source_reference,
        ),
        revision_id=revision.revision_id,
        source_reference=source_reference,
    )


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
