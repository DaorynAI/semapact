"""Exact desired-state snapshots consumed by deployment planning."""

from __future__ import annotations

import uuid

from open_data_contract_standard.model import OpenDataContractStandard
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from semapact.contractops import ReleaseSnapshot
from semapact.utils.deterministic import canonical_compact_json, deterministic_uuid5


SEMAPACT_DEPLOYMENT_SOURCE_NAMESPACE = uuid.UUID(
    "598e0c13-d9af-4cf9-a8a7-9fc7628e17c1"
)


class DeploymentSourceSnapshot(BaseModel):
    """Immutable desired state for deployment, with optional release provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_snapshot_id: str
    contract_id: str
    revision_ref: str
    contract_version: str
    contract_json: str
    release: bool
    release_id: str | None = None
    release_plan_id: str | None = None

    @field_validator(
        "source_snapshot_id",
        "contract_id",
        "revision_ref",
        "contract_version",
        "contract_json",
    )
    @classmethod
    def _require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_source(self) -> "DeploymentSourceSnapshot":
        contract = self.to_contract()
        if str(contract.id or "").strip() != self.contract_id:
            raise ValueError("DeploymentSourceSnapshot contract ID mismatch")
        if str(contract.version or "").strip() != self.contract_version:
            raise ValueError("DeploymentSourceSnapshot contract version mismatch")
        if self.release:
            if self.release_id is None or self.release_plan_id is None:
                raise ValueError(
                    "Release deployment source requires release provenance"
                )
        elif self.release_id is not None or self.release_plan_id is not None:
            raise ValueError(
                "Non-release deployment source cannot contain release provenance"
            )
        expected = compute_deployment_source_id(
            contract_id=self.contract_id,
            revision_ref=self.revision_ref,
            contract_version=self.contract_version,
            contract_json=self.contract_json,
            release=self.release,
            release_id=self.release_id,
            release_plan_id=self.release_plan_id,
        )
        if self.source_snapshot_id != expected:
            raise ValueError(
                "DeploymentSourceSnapshot deterministic identity does not match content"
            )
        return self

    def to_contract(self) -> OpenDataContractStandard:
        return OpenDataContractStandard.model_validate_json(self.contract_json)


def build_candidate_deployment_source(
    contract: OpenDataContractStandard,
    *,
    revision_ref: str,
) -> DeploymentSourceSnapshot:
    """Freeze candidate desired state without calculating or changing its version."""
    if not isinstance(contract, OpenDataContractStandard):
        raise TypeError(
            "contract must be OpenDataContractStandard, "
            f"got {type(contract).__name__}"
        )
    contract_id = str(contract.id or "").strip()
    contract_version = str(contract.version or "").strip()
    revision = revision_ref.strip()
    if not contract_id or not contract_version or not revision:
        raise ValueError(
            "Candidate deployment source requires contract ID, version, and revision"
        )
    contract_json = canonical_compact_json(
        contract.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    source_id = compute_deployment_source_id(
        contract_id=contract_id,
        revision_ref=revision,
        contract_version=contract_version,
        contract_json=contract_json,
        release=False,
        release_id=None,
        release_plan_id=None,
    )
    return DeploymentSourceSnapshot(
        source_snapshot_id=source_id,
        contract_id=contract_id,
        revision_ref=revision,
        contract_version=contract_version,
        contract_json=contract_json,
        release=False,
    )


def build_release_deployment_source(
    snapshot: ReleaseSnapshot,
) -> DeploymentSourceSnapshot:
    """Project one exact ReleaseSnapshot into the generic deployment source seam."""
    contract_json = snapshot.released_contract_json
    source_id = compute_deployment_source_id(
        contract_id=snapshot.contract_id,
        revision_ref=snapshot.release_revision_ref,
        contract_version=snapshot.selected_version,
        contract_json=contract_json,
        release=True,
        release_id=snapshot.release_snapshot_id,
        release_plan_id=snapshot.release_plan_id,
    )
    return DeploymentSourceSnapshot(
        source_snapshot_id=source_id,
        contract_id=snapshot.contract_id,
        revision_ref=snapshot.release_revision_ref,
        contract_version=snapshot.selected_version,
        contract_json=contract_json,
        release=True,
        release_id=snapshot.release_snapshot_id,
        release_plan_id=snapshot.release_plan_id,
    )


def compute_deployment_source_id(
    *,
    contract_id: str,
    revision_ref: str,
    contract_version: str,
    contract_json: str,
    release: bool,
    release_id: str | None,
    release_plan_id: str | None,
) -> str:
    return deterministic_uuid5(
        SEMAPACT_DEPLOYMENT_SOURCE_NAMESPACE,
        {
            "contract_id": contract_id,
            "revision_ref": revision_ref,
            "contract_version": contract_version,
            "contract_json": contract_json,
            "release": release,
            "release_id": release_id,
            "release_plan_id": release_plan_id,
        },
    )
