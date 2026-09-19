"""Deterministic governed-desired-state to observed-state reconciliation."""

from __future__ import annotations

from collections.abc import Sequence

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
from semapact.observation.providers import RuntimeAssetBinding
from semapact.reconciliation.models import (
    ReconciliationDifference,
    ReconciliationDifferenceType,
    ReconciliationResult,
    ReconciliationSubject,
    RuntimeReasonCode,
)
from semapact.schema import (
    SchemaAssetState,
    SchemaDifference,
    SchemaPropertyState,
    SchemaSnapshot,
    compare_schema_snapshots,
)

_REASON_CODE_BY_RAW_DIFFERENCE: dict[
    tuple[ReconciliationDifferenceType, ReconciliationSubject], RuntimeReasonCode
] = {
    (ReconciliationDifferenceType.UNEXPECTED, ReconciliationSubject.ASSET): RuntimeReasonCode.RUNTIME_SCHEMA_ADDED,
    (ReconciliationDifferenceType.MISSING, ReconciliationSubject.ASSET): RuntimeReasonCode.RUNTIME_SCHEMA_REMOVED,
    (ReconciliationDifferenceType.UNEXPECTED, ReconciliationSubject.PROPERTY): RuntimeReasonCode.RUNTIME_PROPERTY_ADDED,
    (ReconciliationDifferenceType.MISSING, ReconciliationSubject.PROPERTY): RuntimeReasonCode.RUNTIME_PROPERTY_REMOVED,
    (ReconciliationDifferenceType.MISMATCH, ReconciliationSubject.PHYSICAL_TYPE): RuntimeReasonCode.RUNTIME_PHYSICAL_TYPE_CHANGED,
    (ReconciliationDifferenceType.MISMATCH, ReconciliationSubject.NULLABILITY): RuntimeReasonCode.RUNTIME_REQUIRED_CHANGED,
}


def reconcile_governed_contract(
    contract: OpenDataContractStandard,
    observation: ObservedPlatformState,
    *,
    asset_bindings: Sequence[RuntimeAssetBinding] | None = None,
) -> ReconciliationResult:
    """Compare governed ODCS desired state with platform-neutral observed state.

    Projection into normalized schema snapshots owns ODCS/runtime identity
    binding. The shared comparator owns structural comparison exactly once.
    Reconciliation then projects raw schema facts into stable runtime reason codes.
    """
    governed_assets = build_schema_index(contract)
    if asset_bindings is None:
        observed_assets = _build_observed_asset_index(observation)
    else:
        observed_assets = _build_bound_observed_asset_index(
            observation=observation,
            governed_keys=set(governed_assets),
            bindings=asset_bindings,
        )

    comparison = compare_schema_snapshots(
        _governed_snapshot(governed_assets),
        _observed_snapshot(
            governed_assets=governed_assets,
            observed_assets=observed_assets,
        ),
    )

    differences = tuple(_reconciliation_difference(item) for item in comparison.differences)
    return ReconciliationResult(
        contract_id=_required_contract_text(getattr(contract, "id", None), field="id"),
        contract_version=_required_contract_text(getattr(contract, "version", None), field="version"),
        observation_source_identifier=observation.source_identifier,
        observation_fingerprint=observation.fingerprint or fingerprint_observed_state(observation),
        differences=differences,
        unverified_paths=comparison.unverified_paths,
    )


def _governed_snapshot(
    governed_assets: dict[str, object],
) -> SchemaSnapshot:
    assets: list[SchemaAssetState] = []
    for asset_key, governed_schema in governed_assets.items():
        properties: list[SchemaPropertyState] = []
        for prop in governed_schema.properties or []:
            name = normalize_identity_name(str(prop.name), "Property")
            physical = _optional_text(getattr(prop, "physicalType", None))
            required = getattr(prop, "required", None)
            properties.append(
                SchemaPropertyState(
                    identity=name,
                    physical_type=physical,
                    nullable=(not required) if isinstance(required, bool) else None,
                )
            )
        assets.append(
            SchemaAssetState(
                identity=asset_key,
                properties=tuple(properties),
            )
        )
    return SchemaSnapshot(assets=tuple(assets))


def _observed_snapshot(
    *,
    governed_assets: dict[str, object],
    observed_assets: dict[str, ObservedAsset],
) -> SchemaSnapshot:
    assets: list[SchemaAssetState] = []
    for asset_key, observed_asset in observed_assets.items():
        governed_schema = governed_assets.get(asset_key)
        if governed_schema is None:
            properties = tuple(
                SchemaPropertyState(
                    identity=normalize_identity_name(
                        prop.identity.property,
                        "Observed property",
                    ),
                    physical_type=_optional_text(prop.physical_type),
                    nullable=prop.nullable,
                )
                for prop in observed_asset.properties
            )
        else:
            observed_properties = _build_observed_property_index(
                asset_key,
                observed_asset,
                governed_properties=governed_schema.properties or [],
            )
            properties = tuple(
                SchemaPropertyState(
                    identity=property_key[1],
                    physical_type=_optional_text(prop.physical_type),
                    nullable=prop.nullable,
                )
                for property_key, prop in observed_properties.items()
            )

        assets.append(
            SchemaAssetState(
                identity=asset_key,
                properties=properties,
            )
        )
    return SchemaSnapshot(assets=tuple(assets))


def _reconciliation_difference(
    difference: SchemaDifference,
) -> ReconciliationDifference:
    return ReconciliationDifference(
        difference_type=difference.difference_type,
        subject=difference.subject,
        reason_code=_runtime_reason_code(
            difference_type=difference.difference_type,
            subject=difference.subject,
        ),
        path=difference.path,
        asset_identity=difference.asset_identity,
        property_identity=difference.property_identity,
        expected=difference.expected,
        observed=difference.observed,
    )


def _build_observed_asset_index(observation: ObservedPlatformState) -> dict[str, ObservedAsset]:
    index: dict[str, ObservedAsset] = {}
    for asset in observation.assets:
        key = normalize_identity_name(asset.identity.asset, "Observed asset")
        if key in index:
            raise ValidationError(f"Duplicate canonical observed asset identity found: '{key}'")
        index[key] = asset
    return index


def _build_bound_observed_asset_index(
    *,
    observation: ObservedPlatformState,
    governed_keys: set[str],
    bindings: Sequence[RuntimeAssetBinding],
) -> dict[str, ObservedAsset]:
    binding_by_governed: dict[str, RuntimeAssetBinding] = {}
    bound_runtime_keys: set[tuple[str, ...]] = set()

    for binding in bindings:
        governed_key = normalize_identity_name(binding.governed_asset, "Runtime binding governed asset")
        if governed_key in binding_by_governed:
            raise ValidationError(f"Duplicate runtime binding for governed asset: '{governed_key}'")
        if binding.observed_asset.platform.casefold() != observation.platform.casefold():
            raise ValidationError("Runtime binding platform must match observed platform state")
        runtime_key = binding.observed_asset.canonical_key
        if runtime_key in bound_runtime_keys:
            raise ValidationError("Multiple governed assets cannot bind to one runtime asset")
        bound_runtime_keys.add(runtime_key)
        binding_by_governed[governed_key] = binding

    binding_keys = set(binding_by_governed)
    if binding_keys != governed_keys:
        missing = sorted(governed_keys - binding_keys)
        unexpected = sorted(binding_keys - governed_keys)
        raise ValidationError(
            "Runtime bindings must cover exactly the governed data-product assets; "
            f"missing={missing}, unexpected={unexpected}"
        )

    observed_by_runtime: dict[tuple[str, ...], ObservedAsset] = {}
    for asset in observation.assets:
        runtime_key = asset.identity.canonical_key
        if runtime_key in observed_by_runtime:
            raise ValidationError(
                "Duplicate canonical observed runtime asset identity found: "
                f"{runtime_key}"
            )
        observed_by_runtime[runtime_key] = asset

    unbound_runtime = sorted(set(observed_by_runtime) - bound_runtime_keys)
    if unbound_runtime:
        raise ValidationError(
            "Observed state contains assets outside the explicit runtime product bindings"
        )

    index: dict[str, ObservedAsset] = {}
    for governed_key, binding in binding_by_governed.items():
        observed_asset = observed_by_runtime.get(binding.observed_asset.canonical_key)
        if observed_asset is not None:
            index[governed_key] = observed_asset
    return index


def _build_observed_property_index(
    asset_key: str,
    asset: ObservedAsset,
    *,
    governed_properties: Sequence[SchemaProperty],
) -> dict[PropertyIdentity, ObservedProperty]:
    physical_to_governed = _property_binding_index(governed_properties)
    index: dict[PropertyIdentity, ObservedProperty] = {}
    for prop in asset.properties:
        if prop.identity.asset != asset.identity:
            raise ValidationError("Observed property asset identity must match its containing asset")
        observed_name = normalize_identity_name(prop.identity.property, "Observed property")
        governed_name = physical_to_governed.get(observed_name, observed_name)
        key: PropertyIdentity = (asset_key, governed_name)
        if key in index:
            raise ValidationError(
                f"Duplicate canonical observed property identity found: '{governed_name}'"
                f" in asset '{asset_key}'"
            )
        index[key] = prop
    return index


def _property_binding_index(
    governed_properties: Sequence[SchemaProperty],
) -> dict[str, str]:
    physical_to_governed: dict[str, str] = {}
    for prop in governed_properties:
        logical_raw = getattr(prop, "name", None)
        if logical_raw is None:
            raise ValidationError("Governed property name is required for runtime binding")
        governed_name = normalize_identity_name(str(logical_raw), "Property")
        physical_raw = getattr(prop, "physicalName", None)
        physical_text = str(physical_raw).strip() if physical_raw is not None else ""
        physical_name = normalize_identity_name(
            physical_text or str(logical_raw),
            "Property physical binding",
        )
        existing = physical_to_governed.get(physical_name)
        if existing is not None and existing != governed_name:
            raise ValidationError(
                "Multiple governed properties cannot bind to one physical runtime property: "
                f"'{physical_name}'"
            )
        physical_to_governed[physical_name] = governed_name
    return physical_to_governed


def _runtime_reason_code(
    *,
    difference_type: ReconciliationDifferenceType,
    subject: ReconciliationSubject,
) -> RuntimeReasonCode:
    reason_code = _REASON_CODE_BY_RAW_DIFFERENCE.get((difference_type, subject))
    if reason_code is None:
        raise ValueError(
            "Unsupported runtime difference combination: "
            f"{difference_type.value}/{subject.value}"
        )
    return reason_code


def _required_contract_text(value: object, *, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValidationError(
            f"Governed desired-state contract {field} is required for reconciliation"
        )
    return text


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
