"""Stable semantic fingerprints for platform-neutral observed state.

A fingerprint identifies the semantic content of an ``ObservedPlatformState``.
It deliberately excludes observation-envelope fields such as ``captured_at``
and ``source_identifier`` so repeated captures of the same platform state have
the same fingerprint.

Version ``obs-v2`` extends the physical observation payload with normalized
owner, comments, tags, constraints, and explicit relationship evidence.
Provider-specific normalization remains the responsibility of the provider
adapter before it constructs the platform-neutral observation model.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from semapact.observation.models import (
    ObservedAsset,
    ObservedConstraint,
    ObservedPlatformState,
    ObservedProperty,
    ObservedRelationship,
    ObservedTag,
)

OBSERVED_STATE_FINGERPRINT_VERSION = "obs-v2"
OBSERVED_STATE_FINGERPRINT_ALGORITHM = "sha256"


def canonical_observed_state_payload(state: ObservedPlatformState) -> dict[str, object]:
    """Return the versioned semantic payload used by the current fingerprint."""
    assets = [_canonical_asset(asset) for asset in state.assets]
    assets.sort(key=_canonical_json)

    return {
        "fingerprint_version": OBSERVED_STATE_FINGERPRINT_VERSION,
        "platform": state.platform.casefold(),
        "assets": assets,
    }


def fingerprint_observed_state(state: ObservedPlatformState) -> str:
    """Return the deterministic fingerprint for observed semantic state."""
    canonical = _canonical_json(canonical_observed_state_payload(state)).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return (
        f"{OBSERVED_STATE_FINGERPRINT_VERSION}:"
        f"{OBSERVED_STATE_FINGERPRINT_ALGORITHM}:{digest}"
    )


def with_observed_state_fingerprint(state: ObservedPlatformState) -> ObservedPlatformState:
    """Return an immutable copy of ``state`` with its canonical fingerprint set."""
    return state.model_copy(update={"fingerprint": fingerprint_observed_state(state)})


def _canonical_asset(asset: ObservedAsset) -> dict[str, object]:
    properties = [_canonical_property(prop) for prop in asset.properties]
    properties.sort(key=_canonical_json)
    tags = [_canonical_tag(tag) for tag in asset.tags]
    tags.sort(key=_canonical_json)
    constraints = [_canonical_constraint(item) for item in asset.constraints]
    constraints.sort(key=_canonical_json)
    relationships = [_canonical_relationship(item) for item in asset.relationships]
    relationships.sort(key=_canonical_json)

    return {
        "identity": list(asset.identity.canonical_key),
        "asset_type": _normalize_optional_text(asset.asset_type),
        "owner": _normalize_optional_text(asset.owner),
        "comment": _normalize_optional_text(asset.comment),
        "tags": tags,
        "properties": properties,
        "constraints": constraints,
        "relationships": relationships,
    }


def _canonical_property(prop: ObservedProperty) -> dict[str, object]:
    tags = [_canonical_tag(tag) for tag in prop.tags]
    tags.sort(key=_canonical_json)
    return {
        "identity": list(prop.identity.canonical_key),
        "physical_type": _normalize_optional_text(prop.physical_type),
        "nullable": prop.nullable,
        "comment": _normalize_optional_text(prop.comment),
        "tags": tags,
    }


def _canonical_tag(tag: ObservedTag) -> dict[str, object]:
    return {
        "key": tag.key.strip(),
        "value": _normalize_optional_text(tag.value),
        "provenance": _normalize_optional_text(tag.provenance),
    }


def _canonical_constraint(constraint: ObservedConstraint) -> dict[str, object]:
    return {
        "kind": constraint.kind.value,
        "properties": [item.casefold() for item in constraint.properties],
        "name": _normalize_optional_text(constraint.name),
        "provenance": _normalize_optional_text(constraint.provenance),
    }


def _canonical_relationship(relationship: ObservedRelationship) -> dict[str, object]:
    return {
        "kind": relationship.kind.value,
        "source_asset": list(relationship.source_asset.canonical_key),
        "source_properties": [item.casefold() for item in relationship.source_properties],
        "target_asset": (
            list(relationship.target_asset.canonical_key)
            if relationship.target_asset is not None
            else None
        ),
        "target_properties": [item.casefold() for item in relationship.target_properties],
        "target_reference": _normalize_optional_text(relationship.target_reference),
        "direction": relationship.direction.value,
        "name": _normalize_optional_text(relationship.name),
        "provenance": _normalize_optional_text(relationship.provenance),
    }


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
