"""Canonical provider-neutral observation normalization primitives."""

from __future__ import annotations

from collections.abc import Iterable

from semapact.observation.evidence import (
    ObservedEvidenceAvailability,
    ObservedEvidenceKind,
    resolve_evidence_availability,
)
from semapact.observation.models import (
    ObservedConstraint,
    ObservedRelationship,
    ObservedTag,
)


def normalize_optional_text(value: str | None) -> str | None:
    """Trim optional text and collapse empty strings to ``None``."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def normalize_casefold_text(value: str | None) -> str | None:
    """Normalize case-insensitive semantic text."""
    cleaned = normalize_optional_text(value)
    return cleaned.casefold() if cleaned is not None else None


def canonical_tag_payload(tag: ObservedTag) -> dict[str, object]:
    return {
        "key": tag.key.strip(),
        "value": normalize_optional_text(tag.value),
        "provenance": normalize_optional_text(tag.provenance),
    }


def canonical_tag_key(tag: ObservedTag) -> tuple[str, str, str]:
    payload = canonical_tag_payload(tag)
    return (
        str(payload["key"]),
        str(payload["value"] or ""),
        str(payload["provenance"] or ""),
    )


def normalize_observed_tags(tags: Iterable[ObservedTag]) -> tuple[ObservedTag, ...]:
    """Deduplicate and deterministically order canonical tag evidence."""
    unique = {canonical_tag_key(tag): tag for tag in tags}
    return tuple(sorted(unique.values(), key=canonical_tag_key))


def canonical_constraint_payload(constraint: ObservedConstraint) -> dict[str, object]:
    return {
        "kind": constraint.kind.value,
        "properties": [item.casefold() for item in constraint.properties],
        "name": normalize_optional_text(constraint.name),
        "provenance": normalize_optional_text(constraint.provenance),
    }


def canonical_constraint_key(constraint: ObservedConstraint) -> tuple[object, ...]:
    payload = canonical_constraint_payload(constraint)
    return (
        payload["kind"],
        tuple(payload["properties"]),
        payload["name"] or "",
        payload["provenance"] or "",
    )


def canonical_relationship_payload(
    relationship: ObservedRelationship,
) -> dict[str, object]:
    target_asset = relationship.target_asset
    return {
        "kind": relationship.kind.value,
        "source_asset": list(relationship.source_asset.canonical_key),
        "source_properties": [item.casefold() for item in relationship.source_properties],
        "target_asset": list(target_asset.canonical_key) if target_asset is not None else None,
        "target_properties": [item.casefold() for item in relationship.target_properties],
        "target_reference": (
            None
            if target_asset is not None
            else normalize_optional_text(relationship.target_reference)
        ),
        "direction": relationship.direction.value,
        "name": normalize_optional_text(relationship.name),
        "provenance": normalize_optional_text(relationship.provenance),
    }


def canonical_relationship_key(
    relationship: ObservedRelationship,
) -> tuple[object, ...]:
    payload = canonical_relationship_payload(relationship)
    target_asset = payload["target_asset"]
    return (
        payload["kind"],
        tuple(payload["source_asset"]),
        tuple(payload["source_properties"]),
        tuple(target_asset) if isinstance(target_asset, list) else (),
        tuple(payload["target_properties"]),
        payload["target_reference"] or "",
        payload["direction"],
        payload["name"] or "",
        payload["provenance"] or "",
    )


def canonical_evidence_availability_payload(
    entries: tuple[ObservedEvidenceAvailability, ...],
) -> list[dict[str, str]]:
    """Return complete deterministic availability semantics for every evidence kind."""
    return [
        {
            "kind": kind.value,
            "status": resolve_evidence_availability(entries, kind).value,
        }
        for kind in ObservedEvidenceKind
    ]
