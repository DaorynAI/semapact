"""Stable semantic fingerprints for platform-neutral observed state.

A fingerprint identifies the semantic content of an ``ObservedPlatformState``.
It deliberately excludes observation-envelope fields such as ``captured_at``
and ``source_identifier`` so repeated captures of the same platform state have
the same fingerprint.

Version ``obs-v1`` hashes the minimal observation model introduced by M1:
platform, asset identity/type, and property identity/physical type/nullability.
Provider-specific semantic normalization remains the responsibility of the
provider adapter before it constructs the platform-neutral observation model.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from semapact.observation.models import (
    ObservedAsset,
    ObservedPlatformState,
    ObservedProperty,
)

OBSERVED_STATE_FINGERPRINT_VERSION = "obs-v1"
OBSERVED_STATE_FINGERPRINT_ALGORITHM = "sha256"


def canonical_observed_state_payload(state: ObservedPlatformState) -> dict[str, object]:
    """Return the versioned semantic payload used by the v1 fingerprint."""
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

    return {
        "identity": list(asset.identity.canonical_key),
        "asset_type": _normalize_optional_text(asset.asset_type),
        "properties": properties,
    }


def _canonical_property(prop: ObservedProperty) -> dict[str, object]:
    return {
        "identity": list(prop.identity.canonical_key),
        "physical_type": _normalize_optional_text(prop.physical_type),
        "nullable": prop.nullable,
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
