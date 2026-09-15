"""Stable semantic fingerprints for platform-neutral observed state.

A fingerprint identifies the semantic content of an ``ObservedPlatformState``.
It deliberately excludes observation-envelope fields such as ``captured_at``
and ``source_identifier`` so repeated captures of the same platform state have
the same fingerprint.

Version ``obs-v2`` extends the physical observation payload with normalized
owner, comments, tags, constraints, relationships, and evidence availability.
Provider-specific normalization remains the responsibility of the provider
adapter before it constructs the platform-neutral observation model.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from semapact.observation.canonical import (
    canonical_constraint_payload,
    canonical_evidence_availability_payload,
    canonical_relationship_payload,
    canonical_tag_payload,
    normalize_casefold_text,
    normalize_optional_text,
)
from semapact.observation.models import ObservedAsset, ObservedPlatformState, ObservedProperty

OBSERVED_STATE_FINGERPRINT_VERSION = "obs-v2"
OBSERVED_STATE_FINGERPRINT_ALGORITHM = "sha256"


def canonical_observed_state_payload(state: ObservedPlatformState) -> dict[str, object]:
    """Return the versioned semantic payload used by the current fingerprint."""
    assets = [_canonical_asset(asset) for asset in state.assets]
    assets.sort(key=_canonical_json)

    return {
        "fingerprint_version": OBSERVED_STATE_FINGERPRINT_VERSION,
        "platform": state.platform.strip().casefold(),
        "evidence_availability": canonical_evidence_availability_payload(
            state.evidence_availability
        ),
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
    tags = [canonical_tag_payload(tag) for tag in asset.tags]
    tags.sort(key=_canonical_json)
    constraints = [canonical_constraint_payload(item) for item in asset.constraints]
    constraints.sort(key=_canonical_json)
    relationships = [canonical_relationship_payload(item) for item in asset.relationships]
    relationships.sort(key=_canonical_json)

    return {
        "identity": list(asset.identity.canonical_key),
        "asset_type": normalize_casefold_text(asset.asset_type),
        "owner": normalize_optional_text(asset.owner),
        "comment": normalize_optional_text(asset.comment),
        "tags": tags,
        "properties": properties,
        "constraints": constraints,
        "relationships": relationships,
    }


def _canonical_property(prop: ObservedProperty) -> dict[str, object]:
    tags = [canonical_tag_payload(tag) for tag in prop.tags]
    tags.sort(key=_canonical_json)
    return {
        "identity": list(prop.identity.canonical_key),
        "physical_type": normalize_casefold_text(prop.physical_type),
        "nullable": prop.nullable,
        "comment": normalize_optional_text(prop.comment),
        "tags": tags,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
