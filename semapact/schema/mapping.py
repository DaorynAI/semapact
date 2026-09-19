"""Shared schema projection contract and helpers.

Schema mapping converts source object models into the normalized SchemaSnapshot
vocabulary consumed by the shared comparator. Provider implementations own
native type normalization; identity projection and ODCS/runtime shape handling
remain shared.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.schema.comparison import SchemaAssetState, SchemaPropertyState


class SchemaMapper(Protocol):
    """Provider seam for native physical-type normalization."""

    key: str

    def normalize_desired_type(self, prop: SchemaProperty) -> str | None: ...

    def normalize_observed_type(self, value: str | None) -> str | None: ...


class PassThroughSchemaMapper:
    """Provider-neutral mapper that preserves declared native type text."""

    key = "generic"

    def normalize_desired_type(self, prop: SchemaProperty) -> str | None:
        return _optional_text(getattr(prop, "physicalType", None))

    def normalize_observed_type(self, value: str | None) -> str | None:
        return _optional_text(value)


def map_desired_schema_asset(
    schema: SchemaObject,
    *,
    asset_identity: str,
    mapper: SchemaMapper,
    use_physical_property_names: bool,
) -> SchemaAssetState:
    """Project one ODCS schema into normalized comparable state."""
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
                physical_type=mapper.normalize_desired_type(prop),
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
    mapper: SchemaMapper,
    property_bindings: Mapping[str, str] | None = None,
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

        properties.append(
            SchemaPropertyState(
                identity=identity,
                physical_type=mapper.normalize_observed_type(prop.physical_type),
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
