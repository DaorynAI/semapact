"""Shared schema mapping contract and provider-neutral helpers.

Schema mapping projects source object models into the normalized SchemaSnapshot
vocabulary consumed by the shared comparator. Provider implementations may
delegate desired-state compilation to an external compiler such as
datacontract-cli rather than reinterpreting ODCS themselves.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.schema.comparison import SchemaAssetState, SchemaPropertyState


class SchemaMapper(Protocol):
    """Map desired and observed provider state into one comparable schema model."""

    key: str

    def map_desired_asset(
        self,
        schema: SchemaObject,
        *,
        asset_identity: str,
    ) -> SchemaAssetState: ...

    def map_observed_asset(
        self,
        observed: ObservedAsset,
        *,
        asset_identity: str,
        property_bindings: Mapping[str, str] | None = None,
    ) -> SchemaAssetState: ...


class PassThroughSchemaMapper:
    """Provider-neutral mapper preserving ODCS/runtime physical type text."""

    key = "generic"

    def map_desired_asset(
        self,
        schema: SchemaObject,
        *,
        asset_identity: str,
    ) -> SchemaAssetState:
        return map_odcs_schema_asset(
            schema,
            asset_identity=asset_identity,
            use_physical_property_names=False,
        )

    def map_observed_asset(
        self,
        observed: ObservedAsset,
        *,
        asset_identity: str,
        property_bindings: Mapping[str, str] | None = None,
    ) -> SchemaAssetState:
        return map_observed_schema_asset(
            observed,
            asset_identity=asset_identity,
            property_bindings=property_bindings,
        )


def map_odcs_schema_asset(
    schema: SchemaObject,
    *,
    asset_identity: str,
    use_physical_property_names: bool,
) -> SchemaAssetState:
    """Direct ODCS projection for provider-neutral callers only.

    Provider target compilation should prefer a provider SchemaMapper
    implementation backed by the platform compiler rather than this helper.
    """
    properties: list[SchemaPropertyState] = []
    seen: set[str] = set()

    for prop in schema.properties or []:
        identity = property_identity(
            prop,
            use_physical_name=use_physical_property_names,
        )
        key = identity.casefold()
        if key in seen:
            raise ValidationError(
                f"Duplicate normalized desired property identity: '{identity}'"
            )
        seen.add(key)

        required = getattr(prop, "required", None)
        properties.append(
            SchemaPropertyState(
                identity=identity,
                physical_type=_optional_text(getattr(prop, "physicalType", None)),
                nullable=(not required) if isinstance(required, bool) else None,
            )
        )

    return SchemaAssetState(
        identity=asset_identity,
        properties=tuple(properties),
    )


def map_observed_schema_asset(
    observed: ObservedAsset,
    *,
    asset_identity: str,
    property_bindings: Mapping[str, str] | None = None,
    normalize_physical_type=None,
) -> SchemaAssetState:
    """Project one observed runtime asset into normalized comparable state."""
    bindings = {
        key.casefold(): value
        for key, value in (property_bindings or {}).items()
    }
    properties: list[SchemaPropertyState] = []
    seen: set[str] = set()

    for prop in observed.properties:
        observed_name = prop.identity.property.strip()
        if not observed_name:
            raise ValidationError("Observed property identity must not be empty")
        identity = bindings.get(observed_name.casefold(), observed_name)
        key = identity.casefold()
        if key in seen:
            raise ValidationError(
                f"Duplicate canonical observed property identity found: '{key}'"
            )
        seen.add(key)

        physical_type = prop.physical_type
        if normalize_physical_type is not None:
            physical_type = normalize_physical_type(physical_type)

        properties.append(
            SchemaPropertyState(
                identity=identity,
                physical_type=_optional_text(physical_type),
                nullable=prop.nullable,
            )
        )

    return SchemaAssetState(
        identity=asset_identity,
        properties=tuple(properties),
    )


def build_physical_property_bindings(
    governed_properties: Sequence[SchemaProperty],
) -> dict[str, str]:
    """Map physical runtime property names to governed logical identities."""
    bindings: dict[str, str] = {}
    for prop in governed_properties:
        logical = property_identity(prop, use_physical_name=False)
        physical = property_identity(prop, use_physical_name=True)
        physical_key = physical.casefold()

        existing = bindings.get(physical_key)
        if existing is not None and existing.casefold() != logical.casefold():
            raise ValidationError(
                "Multiple governed properties cannot bind to one physical runtime "
                f"property: '{physical}'"
            )
        bindings[physical_key] = logical

    return bindings


def property_identity(
    prop: SchemaProperty,
    *,
    use_physical_name: bool,
) -> str:
    """Resolve one logical or physical property identity deterministically."""
    logical = _optional_text(getattr(prop, "name", None))
    if logical is None:
        raise ValidationError("Schema property name is required for schema mapping")

    if not use_physical_name:
        return logical

    physical = _optional_text(getattr(prop, "physicalName", None))
    return physical or logical


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
