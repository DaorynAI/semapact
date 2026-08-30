"""Read-side domain models for observed runtime state.

Observed runtime state is deliberately separate from the governed ODCS contract model.
It describes what a platform reports now; it is never governed truth by itself.
"""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RuntimeModel(BaseModel):
    """Shared immutable base for runtime observation models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ObservedAssetIdentity(RuntimeModel):
    """Platform-local identity for one observed runtime asset."""

    platform: str
    catalog: str
    schema: str
    asset: str

    @property
    def canonical_key(self) -> tuple[str, str, str, str]:
        """Return the case-normalized runtime identity key."""
        return (
            self.platform.casefold(),
            self.catalog.casefold(),
            self.schema.casefold(),
            self.asset.casefold(),
        )


class ObservedPropertyIdentity(RuntimeModel):
    """Identity for a property within an observed runtime asset."""

    asset: ObservedAssetIdentity
    property: str

    @property
    def canonical_key(self) -> tuple[str, str, str, str, str]:
        """Return the case-normalized runtime property identity key."""
        return (*self.asset.canonical_key, self.property.casefold())


class RuntimeMetadata(RuntimeModel):
    """Canonical preservation of platform metadata not modeled directly."""

    key: str
    value_json: str


class RuntimeTag(RuntimeModel):
    """Observed platform tag."""

    key: str
    value: str


class ObservedProperty(RuntimeModel):
    """Observed runtime property/column state."""

    identity: ObservedPropertyIdentity
    logical_type: str | None = None
    physical_type: str | None = None
    nullable: bool | None = None
    required: bool | None = None
    position: int | None = None
    comment: str | None = None
    tags: tuple[RuntimeTag, ...] = ()
    metadata: tuple[RuntimeMetadata, ...] = ()


class ObservedConstraint(RuntimeModel):
    """Observed non-relational table constraint."""

    constraint_type: str
    name: str | None = None
    columns: tuple[str, ...] = ()
    expression: str | None = None
    metadata: tuple[RuntimeMetadata, ...] = ()


class ObservedRelationship(RuntimeModel):
    """Observed relationship from one runtime asset to another."""

    relationship_type: str
    source_columns: tuple[str, ...] = ()
    target_reference: str | None = None
    target_columns: tuple[str, ...] = ()
    constraint_name: str | None = None
    metadata: tuple[RuntimeMetadata, ...] = ()


class RuntimeEvidence(RuntimeModel):
    """Reference to runtime evidence reported by the source platform."""

    kind: str
    reference: str
    metadata: tuple[RuntimeMetadata, ...] = ()


class ObservedAsset(RuntimeModel):
    """Observed state for one runtime asset."""

    identity: ObservedAssetIdentity
    asset_type: str | None = None
    data_source_format: str | None = None
    owner: str | None = None
    comment: str | None = None
    properties: tuple[ObservedProperty, ...] = ()
    constraints: tuple[ObservedConstraint, ...] = ()
    relationships: tuple[ObservedRelationship, ...] = ()
    tags: tuple[RuntimeTag, ...] = ()
    metadata: tuple[RuntimeMetadata, ...] = ()


class ObservedContractState(RuntimeModel):
    """Point-in-time runtime observation independent from governed ODCS state.

    ``fingerprint`` is intentionally optional. M1 fingerprint normalization and
    hashing are a separate capability; this model only reserves the contract.
    """

    platform: str
    source_identifier: str
    assets: tuple[ObservedAsset, ...]
    captured_at: datetime
    fingerprint: str | None = None
    evidence: tuple[RuntimeEvidence, ...] = ()


def serialize_observed_state(state: ObservedContractState) -> str:
    """Serialize observed state deterministically for machine-readable use."""
    return json.dumps(
        state.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
