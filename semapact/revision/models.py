"""Immutable domain models for governed contract revision identity."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard
from pydantic import BaseModel, ConfigDict, field_validator


class ContractRevision(BaseModel):
    """Content-identity envelope around one exact canonical ODCS contract state.

    The ODCS model remains the canonical contract representation. This model adds only
    SemaPact-owned revision identity and does not duplicate contract ID, version, or a
    serialized contract copy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    revision_id: str
    content_fingerprint: str
    contract: OpenDataContractStandard

    @field_validator("revision_id", "content_fingerprint")
    @classmethod
    def _require_canonical_text(cls, value: str) -> str:
        return _canonical_text(value)


class ContractRevisionSource(BaseModel):
    """Immutable provenance link from one revision to one source reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_link_id: str
    revision_id: str
    source_reference: str

    @field_validator("source_link_id", "revision_id", "source_reference")
    @classmethod
    def _require_canonical_text(cls, value: str) -> str:
        return _canonical_text(value)


def _canonical_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be str")
    if not value or value != value.strip():
        raise ValueError("value must be non-empty canonical text")
    return value
