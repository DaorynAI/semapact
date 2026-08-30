"""Platform-neutral read-side models for observed external state.

An observation describes what an external data platform reports at a point in
time. It is deliberately separate from the governed ODCS contract model and is
never governed truth by itself.
"""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ObservationModel(BaseModel):
    """Shared immutable base for observation models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ObservedAssetIdentity(ObservationModel):
    """Platform-local identity for one observed asset.

    ``namespace`` is intentionally provider-neutral. A Databricks adapter may
    populate it with ``(catalog, schema)`` while another platform may use a
    different hierarchy without changing the domain model.
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


class ObservedProperty(ObservationModel):
    """Observed physical property/column state."""

    identity: ObservedPropertyIdentity
    physical_type: str | None = None
    nullable: bool | None = None


class ObservedAsset(ObservationModel):
    """Observed physical state for one external asset."""

    identity: ObservedAssetIdentity
    asset_type: str | None = None
    properties: tuple[ObservedProperty, ...] = ()


class ObservedPlatformState(ObservationModel):
    """Point-in-time platform observation independent from governed ODCS state.

    ``fingerprint`` is intentionally optional. Stable normalization and hashing
    belong to the dedicated observed-state fingerprint capability; this model
    only reserves the field used by that later capability.
    """

    platform: str
    source_identifier: str
    assets: tuple[ObservedAsset, ...]
    captured_at: datetime
    fingerprint: str | None = None


def serialize_observed_state(state: ObservedPlatformState) -> str:
    """Serialize observed state deterministically for machine-readable use."""
    return json.dumps(
        state.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
