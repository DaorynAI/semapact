"""Immutable domain models for governed contract revision identity."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class ContractRevision(BaseModel):
    """Exact governed ODCS content identity.

    The model owns structure only. Derived identity validation belongs to the
    revision integrity rules so model definition and domain computation stay
    separate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    revision_id: str
    contract_id: str
    contract_version: str
    content_fingerprint: str
    canonical_contract_json: str

    @field_validator("revision_id", "contract_id", "contract_version")
    @classmethod
    def _require_canonical_text(cls, value: str) -> str:
        return _canonical_text(value)

    @field_validator("content_fingerprint")
    @classmethod
    def _require_sha256_hex(cls, value: str) -> str:
        if value != value.strip().lower() or not _SHA256_HEX.fullmatch(value):
            raise ValueError("content_fingerprint must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("canonical_contract_json")
    @classmethod
    def _require_contract_json(cls, value: str) -> str:
        if not value:
            raise ValueError("canonical_contract_json must not be empty")
        return value


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
