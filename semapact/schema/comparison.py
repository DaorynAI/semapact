"""Provider-neutral comparison of normalized schema state.

The comparator knows only expected and observed schema snapshots. ODCS,
runtime-provider models, governance policy, deployment capability, SQL rendering,
and authorization belong to projection or interpretation layers.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator

from semapact.exceptions import ValidationError


class SchemaComparisonModel(BaseModel):
    """Shared immutable base for schema comparison values."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SchemaDifferenceType(str, Enum):
    """Difference direction relative to expected desired state."""

    MISSING = "missing"
    UNEXPECTED = "unexpected"
    MISMATCH = "mismatch"


class SchemaSubject(str, Enum):
    """Comparable schema subject."""

    ASSET = "asset"
    PROPERTY = "property"
    PHYSICAL_TYPE = "physical_type"
    NULLABILITY = "nullability"


class SchemaPropertyState(SchemaComparisonModel):
    """Normalized comparable state for one property.

    native_definition is opaque provider output retained for later transition
    rendering. It is deliberately excluded from schema comparison semantics.
    """

    identity: str
    physical_type: str | None = None
    nullable: bool | None = None
    native_definition: str | None = None

    @field_validator("identity")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("schema property identity must not be empty")
        return cleaned

    @field_validator("physical_type", "native_definition")
    @classmethod
    def _normalize_optional_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class SchemaAssetState(SchemaComparisonModel):
    """Normalized comparable state for one asset."""

    identity: str
    properties: tuple[SchemaPropertyState, ...] = ()

    @field_validator("identity")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("schema asset identity must not be empty")
        return cleaned


class SchemaSnapshot(SchemaComparisonModel):
    """Normalized schema state independent of its source object model."""

    assets: tuple[SchemaAssetState, ...] = ()


class SchemaDifference(SchemaComparisonModel):
    """One raw schema fact; no policy or deployment meaning is attached."""

    difference_type: SchemaDifferenceType
    subject: SchemaSubject
    path: str
    asset_identity: str
    property_identity: str | None = None
    expected: str | bool | None = None
    observed: str | bool | None = None


class SchemaComparisonResult(SchemaComparisonModel):
    """Deterministic schema differences plus evidence gaps."""

    differences: tuple[SchemaDifference, ...] = ()
    unverified_paths: tuple[str, ...] = ()


_SUBJECT_ORDER = {
    SchemaSubject.ASSET: 0,
    SchemaSubject.PROPERTY: 1,
    SchemaSubject.PHYSICAL_TYPE: 2,
    SchemaSubject.NULLABILITY: 3,
}


def compare_schema_snapshots(
    expected: SchemaSnapshot,
    observed: SchemaSnapshot,
) -> SchemaComparisonResult:
    """Compare normalized expected and observed schema state exactly once."""
    expected_assets = _asset_index(expected, role="expected")
    observed_assets = _asset_index(observed, role="observed")

    differences: list[SchemaDifference] = []
    unverified_paths: list[str] = []

    expected_keys = set(expected_assets)
    observed_keys = set(observed_assets)

    for asset_key in sorted(expected_keys - observed_keys):
        differences.append(
            _difference(
                difference_type=SchemaDifferenceType.MISSING,
                subject=SchemaSubject.ASSET,
                asset_identity=asset_key,
            )
        )

    for asset_key in sorted(observed_keys - expected_keys):
        differences.append(
            _difference(
                difference_type=SchemaDifferenceType.UNEXPECTED,
                subject=SchemaSubject.ASSET,
                asset_identity=asset_key,
            )
        )

    for asset_key in sorted(expected_keys & observed_keys):
        asset_differences, asset_unverified = _compare_asset(
            expected=expected_assets[asset_key],
            observed=observed_assets[asset_key],
        )
        differences.extend(asset_differences)
        unverified_paths.extend(asset_unverified)

    return SchemaComparisonResult(
        differences=tuple(sorted(differences, key=_difference_sort_key)),
        unverified_paths=tuple(sorted(unverified_paths)),
    )


def _compare_asset(
    *,
    expected: SchemaAssetState,
    observed: SchemaAssetState,
) -> tuple[list[SchemaDifference], list[str]]:
    expected_properties = _property_index(expected, role="expected")
    observed_properties = _property_index(observed, role="observed")

    differences: list[SchemaDifference] = []
    unverified_paths: list[str] = []

    expected_keys = set(expected_properties)
    observed_keys = set(observed_properties)

    for property_key in sorted(expected_keys - observed_keys):
        differences.append(
            _difference(
                difference_type=SchemaDifferenceType.MISSING,
                subject=SchemaSubject.PROPERTY,
                asset_identity=expected.identity,
                property_identity=property_key,
            )
        )

    for property_key in sorted(observed_keys - expected_keys):
        differences.append(
            _difference(
                difference_type=SchemaDifferenceType.UNEXPECTED,
                subject=SchemaSubject.PROPERTY,
                asset_identity=expected.identity,
                property_identity=property_key,
            )
        )

    for property_key in sorted(expected_keys & observed_keys):
        desired = expected_properties[property_key]
        actual = observed_properties[property_key]

        if desired.physical_type is not None:
            path = _difference_path(
                subject=SchemaSubject.PHYSICAL_TYPE,
                asset_identity=expected.identity,
                property_identity=property_key,
            )
            if actual.physical_type is None:
                unverified_paths.append(path)
            elif desired.physical_type.casefold() != actual.physical_type.casefold():
                differences.append(
                    _difference(
                        difference_type=SchemaDifferenceType.MISMATCH,
                        subject=SchemaSubject.PHYSICAL_TYPE,
                        asset_identity=expected.identity,
                        property_identity=property_key,
                        expected=desired.physical_type,
                        observed=actual.physical_type,
                    )
                )

        if desired.nullable is not None:
            path = _difference_path(
                subject=SchemaSubject.NULLABILITY,
                asset_identity=expected.identity,
                property_identity=property_key,
            )
            if actual.nullable is None:
                unverified_paths.append(path)
            elif desired.nullable is not actual.nullable:
                differences.append(
                    _difference(
                        difference_type=SchemaDifferenceType.MISMATCH,
                        subject=SchemaSubject.NULLABILITY,
                        asset_identity=expected.identity,
                        property_identity=property_key,
                        expected=desired.nullable,
                        observed=actual.nullable,
                    )
                )

    return differences, unverified_paths


def _asset_index(snapshot: SchemaSnapshot, *, role: str) -> dict[str, SchemaAssetState]:
    index: dict[str, SchemaAssetState] = {}
    for asset in snapshot.assets:
        key = asset.identity.casefold()
        if key in index:
            raise ValidationError(
                f"Duplicate normalized {role} asset identity: '{asset.identity}'"
            )
        index[key] = asset.model_copy(update={"identity": key})
    return index


def _property_index(
    asset: SchemaAssetState,
    *,
    role: str,
) -> dict[str, SchemaPropertyState]:
    index: dict[str, SchemaPropertyState] = {}
    for prop in asset.properties:
        key = prop.identity.casefold()
        if key in index:
            raise ValidationError(
                f"Duplicate normalized {role} property identity: '{prop.identity}'"
            )
        index[key] = prop.model_copy(update={"identity": key})
    return index


def _difference(
    *,
    difference_type: SchemaDifferenceType,
    subject: SchemaSubject,
    asset_identity: str,
    property_identity: str | None = None,
    expected: str | bool | None = None,
    observed: str | bool | None = None,
) -> SchemaDifference:
    return SchemaDifference(
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
    subject: SchemaSubject,
    asset_identity: str,
    property_identity: str | None,
) -> str:
    asset_path = f"schema[{asset_identity}]"
    if subject is SchemaSubject.ASSET:
        return asset_path
    if property_identity is None:
        raise ValueError(f"property_identity is required for {subject.value}")
    property_path = f"{asset_path}.properties[{property_identity}]"
    if subject is SchemaSubject.PROPERTY:
        return property_path
    if subject is SchemaSubject.PHYSICAL_TYPE:
        return f"{property_path}.physicalType"
    return f"{property_path}.nullability"


def _difference_sort_key(
    difference: SchemaDifference,
) -> tuple[str, str, int, str]:
    return (
        difference.asset_identity,
        difference.property_identity or "",
        _SUBJECT_ORDER[difference.subject],
        difference.difference_type.value,
    )
