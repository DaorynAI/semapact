"""Platform-neutral read-side models for observed external state.

An observation describes what an external data platform reports at a point in
time. It is deliberately separate from the governed ODCS contract model and is
never governed truth by itself.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator

from semapact.observation.evidence import ObservedEvidenceAvailability


class ObservationModel(BaseModel):
    """Shared immutable base for observation models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ObservedAssetIdentity(ObservationModel):
    """Platform-local identity for one observed asset.

    ``namespace`` is intentionally provider-neutral so adapters can map their
    own hierarchy without changing the observation domain model.
    """

    platform: str
    namespace: tuple[str, ...] = ()
    asset: str

    @property
    def canonical_key(self) -> tuple[str, ...]:
        """Return a case-normalized identity key without provider semantics."""
        return (
            self.platform.casefold(),
            *(part.casefold() for part in self.namespace),
            self.asset.casefold(),
        )


class ObservedPropertyIdentity(ObservationModel):
    """Identity for a property within an observed asset."""

    asset: ObservedAssetIdentity
    property: str

    @property
    def canonical_key(self) -> tuple[str, ...]:
        """Return the case-normalized property identity key."""
        return (*self.asset.canonical_key, self.property.casefold())


class ObservedTag(ObservationModel):
    """One normalized platform tag assignment."""

    key: str
    value: str | None = None
    provenance: str | None = None


class ObservedConstraintKind(str, Enum):
    """Constraint semantics that a provider can identify without inference."""

    PRIMARY_KEY = "PRIMARY_KEY"
    UNIQUE = "UNIQUE"
    NAMED = "NAMED"


class ObservedConstraint(ObservationModel):
    """Normalized non-relational constraint evidence for one asset."""

    kind: ObservedConstraintKind
    properties: tuple[str, ...] = ()
    name: str | None = None
    provenance: str | None = None


class ObservedRelationshipKind(str, Enum):
    """Relationship semantics that a provider reports explicitly."""

    FOREIGN_KEY = "FOREIGN_KEY"


class ObservedRelationshipDirection(str, Enum):
    """Direction from the asset carrying the relationship evidence."""

    OUTBOUND = "OUTBOUND"


class ObservedRelationship(ObservationModel):
    """Normalized explicit relationship evidence between observed assets.

    ``target_reference`` preserves provider evidence when the target cannot be
    normalized into a platform-local asset identity. Empty property tuples mean
    the provider did not identify those columns; they must never be inferred.
    """

    kind: ObservedRelationshipKind
    source_asset: ObservedAssetIdentity
    source_properties: tuple[str, ...] = ()
    target_asset: ObservedAssetIdentity | None = None
    target_properties: tuple[str, ...] = ()
    target_reference: str | None = None
    direction: ObservedRelationshipDirection = ObservedRelationshipDirection.OUTBOUND
    name: str | None = None
    provenance: str | None = None


class ObservedProperty(ObservationModel):
    """Observed physical and semantic property/column state."""

    identity: ObservedPropertyIdentity
    physical_type: str | None = None
    nullable: bool | None = None
    comment: str | None = None
    tags: tuple[ObservedTag, ...] = ()


class ObservedAsset(ObservationModel):
    """Observed physical, semantic, and operational state for one external asset."""

    identity: ObservedAssetIdentity
    asset_type: str | None = None
    owner: str | None = None
    comment: str | None = None
    tags: tuple[ObservedTag, ...] = ()
    properties: tuple[ObservedProperty, ...] = ()
    constraints: tuple[ObservedConstraint, ...] = ()
    relationships: tuple[ObservedRelationship, ...] = ()

    @model_validator(mode="after")
    def _validate_nested_identity(self) -> ObservedAsset:
        for prop in self.properties:
            if prop.identity.asset.canonical_key != self.identity.canonical_key:
                raise ValueError(
                    "Observed property asset identity must match its containing asset"
                )
        for relationship in self.relationships:
            if relationship.source_asset.canonical_key != self.identity.canonical_key:
                raise ValueError(
                    "Observed relationship source identity must match its containing asset"
                )
        return self


class ObservedPlatformState(ObservationModel):
    """Point-in-time platform observation independent from governed ODCS state.

    ``fingerprint`` is the optional versioned semantic content hash for this
    observed state. Provider adapters may populate it through the shared
    fingerprint capability; manually constructed observations may leave it
    unset until fingerprinting is requested.

    ``evidence_availability`` records whether each provider-neutral evidence
    kind was actually observable. Unspecified kinds are treated as ``UNKNOWN``
    by shared classification and fingerprinting logic.
    """

    platform: str
    source_identifier: str
    assets: tuple[ObservedAsset, ...]
    captured_at: datetime
    evidence_availability: tuple[ObservedEvidenceAvailability, ...] = ()
    fingerprint: str | None = None

    @model_validator(mode="after")
    def _validate_state_identity(self) -> ObservedPlatformState:
        platform = self.platform.casefold()
        for asset in self.assets:
            if asset.identity.platform.casefold() != platform:
                raise ValueError(
                    "Observed asset platform must match ObservedPlatformState.platform"
                )

        kinds = [entry.kind for entry in self.evidence_availability]
        if len(kinds) != len(set(kinds)):
            raise ValueError("Observed evidence availability must contain each kind at most once")
        return self


def serialize_observed_state(state: ObservedPlatformState) -> str:
    """Serialize observed state deterministically for machine-readable use."""
    return json.dumps(
        state.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
