"""Deterministic approved-contract to observed-state reconciliation."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard, SchemaProperty

from semapact.exceptions import ValidationError
from semapact.lifecycle.identity import (
    PropertyIdentity,
    build_property_index,
    build_schema_index,
    normalize_identity_name,
)
from semapact.observation.fingerprint import fingerprint_observed_state
from semapact.observation.models import ObservedAsset, ObservedPlatformState, ObservedProperty
from semapact.reconciliation.models import (
    ReconciliationDifference,
    ReconciliationDifferenceType,
    ReconciliationResult,
    ReconciliationSubject,
)


def reconcile_approved_contract(
    contract: OpenDataContractStandard,
    observation: ObservedPlatformState,
) -> ReconciliationResult:
    """Compare approved ODCS desired state with platform-neutral observed state.

    This function reports raw differences only. It does not classify drift cause
    or operational status and never mutates either input.
    """
    approved_assets = build_schema_index(contract)
    observed_assets = _build_observed_asset_index(observation)
    differences: list[ReconciliationDifference] = []

    approved_keys = set(approved_assets)
    observed_keys = set(observed_assets)

    for asset_key in sorted(approved_keys - observed_keys):
        differences.append(
            _difference(
                difference_type=ReconciliationDifferenceType.MISSING,
                subject=ReconciliationSubject.ASSET,
                asset_identity=asset_key,
            )
        )

    for asset_key in sorted(observed_keys - approved_keys):
        differences.append(
            _difference(
                difference_type=ReconciliationDifferenceType.UNEXPECTED,
                subject=ReconciliationSubject.ASSET,
                asset_identity=asset_key,
            )
        )

    for asset_key in sorted(approved_keys & observed_keys):
        approved_schema = approved_assets[asset_key]
        observed_asset = observed_assets[asset_key]
        differences.extend(
            _reconcile_properties(
                asset_key=asset_key,
                approved_properties=list(approved_schema.properties or []),
                observed_asset=observed_asset,
            )
        )

    ordered = tuple(sorted(differences, key=_difference_sort_key))
    return ReconciliationResult(
        contract_id=_required_contract_text(getattr(contract, "id", None), field="id"),
        contract_version=_required_contract_text(
            getattr(contract, "version", None), field="version"
        ),
        observation_source_identifier=observation.source_identifier,
        observation_fingerprint=(
            observation.fingerprint or fingerprint_observed_state(observation)
        ),
        differences=ordered,
    )


def _reconcile_properties(
    *,
    asset_key: str,
    approved_properties: list[SchemaProperty],
    observed_asset: ObservedAsset,
) -> list[ReconciliationDifference]:
    approved = build_property_index(asset_key, approved_properties)
    observed = _build_observed_property_index(asset_key, observed_asset)
    differences: list[ReconciliationDifference] = []

    approved_keys = set(approved)
    observed_keys = set(observed)

    for prop_key in sorted(approved_keys - observed_keys):
        differences.append(
            _difference(
                difference_type=ReconciliationDifferenceType.MISSING,
                subject=ReconciliationSubject.PROPERTY,
                asset_identity=asset_key,
                property_identity=prop_key[1],
            )
        )

    for prop_key in sorted(observed_keys - approved_keys):
        differences.append(
            _difference(
                difference_type=ReconciliationDifferenceType.UNEXPECTED,
                subject=ReconciliationSubject.PROPERTY,
                asset_identity=asset_key,
                property_identity=prop_key[1],
            )
        )

    for prop_key in sorted(approved_keys & observed_keys):
        differences.extend(
            _reconcile_matching_property(
                asset_key=asset_key,
                property_key=prop_key,
                approved=approved[prop_key],
                observed=observed[prop_key],
            )
        )

    return differences


def _reconcile_matching_property(
    *,
    asset_key: str,
    property_key: PropertyIdentity,
    approved: SchemaProperty,
    observed: ObservedProperty,
) -> list[ReconciliationDifference]:
    differences: list[ReconciliationDifference] = []
    property_identity = property_key[1]

    expected_physical = _optional_text(getattr(approved, "physicalType", None))
    observed_physical = _optional_text(observed.physical_type)
    if (
        expected_physical is not None
        and observed_physical is not None
        and _normalize_comparable_text(expected_physical)
        != _normalize_comparable_text(observed_physical)
    ):
        differences.append(
            _difference(
                difference_type=ReconciliationDifferenceType.MISMATCH,
                subject=ReconciliationSubject.PHYSICAL_TYPE,
                asset_identity=asset_key,
                property_identity=property_identity,
                expected=expected_physical,
                observed=observed_physical,
            )
        )

    required = getattr(approved, "required", None)
    nullable = observed.nullable
    if isinstance(required, bool) and isinstance(nullable, bool):
        expected_nullable = not required
        if expected_nullable != nullable:
            differences.append(
                _difference(
                    difference_type=ReconciliationDifferenceType.MISMATCH,
                    subject=ReconciliationSubject.NULLABILITY,
                    asset_identity=asset_key,
                    property_identity=property_identity,
                    expected=expected_nullable,
                    observed=nullable,
                )
            )

    return differences


def _build_observed_asset_index(
    observation: ObservedPlatformState,
) -> dict[str, ObservedAsset]:
    index: dict[str, ObservedAsset] = {}
    for asset in observation.assets:
        key = normalize_identity_name(asset.identity.asset, "Observed asset")
        if key in index:
            raise ValidationError(
                f"Duplicate canonical observed asset identity found: '{key}'"
            )
        index[key] = asset
    return index


def _build_observed_property_index(
    asset_key: str,
    asset: ObservedAsset,
) -> dict[PropertyIdentity, ObservedProperty]:
    index: dict[PropertyIdentity, ObservedProperty] = {}
    for prop in asset.properties:
        if prop.identity.asset != asset.identity:
            raise ValidationError(
                "Observed property asset identity must match its containing asset"
            )
        prop_name = normalize_identity_name(
            prop.identity.property, "Observed property"
        )
        key: PropertyIdentity = (asset_key, prop_name)
        if key in index:
            raise ValidationError(
                f"Duplicate canonical observed property identity found: '{prop_name}'"
                f" in asset '{asset_key}'"
            )
        index[key] = prop
    return index


def _difference(
    *,
    difference_type: ReconciliationDifferenceType,
    subject: ReconciliationSubject,
    asset_identity: str,
    property_identity: str | None = None,
    expected: str | bool | None = None,
    observed: str | bool | None = None,
) -> ReconciliationDifference:
    return ReconciliationDifference(
        difference_type=difference_type,
        subject=subject,
        path=_difference_path(
            subject=subject,
            asset_identity=asset_identity,
            property_identity=property_identity,
        ),
        asset_identity=asset_identity,
        property_identity=property_identity,
        expected=expected,
        observed=observed,
    )


def _difference_path(
    *,
    subject: ReconciliationSubject,
    asset_identity: str,
    property_identity: str | None,
) -> str:
    asset_path = f"schema[{asset_identity}]"
    if subject is ReconciliationSubject.ASSET:
        return asset_path

    if property_identity is None:
        raise ValueError(f"property_identity is required for {subject.value}")

    property_path = f"{asset_path}.properties[{property_identity}]"
    if subject is ReconciliationSubject.PROPERTY:
        return property_path
    if subject is ReconciliationSubject.PHYSICAL_TYPE:
        return f"{property_path}.physicalType"
    return f"{property_path}.nullability"


def _difference_sort_key(
    difference: ReconciliationDifference,
) -> tuple[str, str, str, str]:
    return (
        difference.asset_identity,
        difference.property_identity or "",
        difference.subject.value,
        difference.difference_type.value,
    )


def _required_contract_text(value: object, *, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValidationError(f"Approved contract {field} is required for reconciliation")
    return text


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_comparable_text(value: str) -> str:
    return value.strip().casefold()
