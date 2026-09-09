"""Immutable artifacts for explicit ContractOps APPLY and PUBLISH phases."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard
from pydantic import field_validator, model_validator

from semapact.contractops.models import ContractOpsModel


class AppliedContractRelease(ContractOpsModel):
    """Exact released ODCS state produced by an authorized APPLY operation."""

    applied_release_id: str
    contract_id: str
    decision_id: str
    change_set_id: str
    release_plan_id: str
    version_resolution_id: str
    release_revision_ref: str
    selected_version: str
    authorization_id: str
    released_contract_json: str

    @field_validator(
        "applied_release_id",
        "contract_id",
        "decision_id",
        "change_set_id",
        "release_plan_id",
        "version_resolution_id",
        "release_revision_ref",
        "selected_version",
        "authorization_id",
        "released_contract_json",
    )
    @classmethod
    def _require_non_empty_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_released_contract_snapshot(self) -> AppliedContractRelease:
        contract = OpenDataContractStandard.model_validate_json(self.released_contract_json)
        if str(contract.id or "") != self.contract_id:
            raise ValueError("released contract ID does not match AppliedContractRelease")
        if str(contract.version or "") != self.selected_version:
            raise ValueError("released contract version does not match selected_version")
        return self

    def to_contract(self) -> OpenDataContractStandard:
        """Materialize a fresh mutable ODCS model from the immutable JSON snapshot."""
        return OpenDataContractStandard.model_validate_json(self.released_contract_json)


class PublicationResult(ContractOpsModel):
    """Successful result of one explicitly authorized external publication."""

    publication_id: str
    applied_release_id: str
    authorization_id: str
    publication_reference: str

    @field_validator(
        "publication_id",
        "applied_release_id",
        "authorization_id",
        "publication_reference",
    )
    @classmethod
    def _require_publication_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned
