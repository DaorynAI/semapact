"""Provider-neutral schema mapping contracts and common implementations.

The shared layer owns generic mapping mechanics. Platform modules only
instantiate a mapper with target compiler/dialect parameters or add genuinely
platform-specific validation/capability rules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Callable, Protocol

import sqlglot
from datacontract.export.sql_exporter import to_sql_ddl
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from sqlglot import exp

from semapact.exceptions import ValidationError
from semapact.observation.models import ObservedAsset
from semapact.schema.comparison import SchemaAssetState, SchemaPropertyState


_UNRESOLVED_SQL_TYPES = {
    exp.DataType.Type.UNKNOWN,
    exp.DataType.Type.USERDEFINED,
    exp.DataType.Type.NULL,
}


class SchemaMapper(Protocol):
    """Map desired and observed schema state into one comparable model."""

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


class SqlSchemaMapper:
    """Common SQL target-schema mapper backed by datacontract-cli + sqlglot."""

    def __init__(
        self,
        *,
        key: str,
        server_type: str,
        dialect: str,
    ) -> None:
        self.key = _required_text(key, "schema mapper key")
        self.server_type = _required_text(server_type, "SQL server type")
        self.dialect = _required_text(dialect, "SQL dialect")

    def map_desired_asset(
        self,
        schema: SchemaObject,
        *,
        asset_identity: str,
    ) -> SchemaAssetState:
        """Compile ODCS with datacontract-cli and adapt the target DDL."""
        desired = schema.model_copy(update={"name": asset_identity})
        contract = OpenDataContractStandard.model_construct(
            id="semapact:deployment-target",
            version="0.0.0",
            schema_=[desired],
            servers=[],
        )
        ddl = to_sql_ddl(contract, server_type=self.server_type)
        return parse_sql_target_asset(
            ddl,
            asset_identity=asset_identity,
            dialect=self.dialect,
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
            normalize_physical_type=lambda value: normalize_sql_type(
                value,
                dialect=self.dialect,
            ),
        )


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


def parse_sql_target_asset(
    ddl: str,
    *,
    asset_identity: str,
    dialect: str,
) -> SchemaAssetState:
    """Parse one compiler-emitted CREATE TABLE into normalized schema state."""
    try:
        statements = [
            statement
            for statement in sqlglot.parse(ddl, read=dialect)
            if statement is not None
        ]
    except Exception as exc:
        raise ValidationError(
            f"Target schema compiler emitted {dialect} DDL that could not be parsed"
        ) from exc

    creates = [
        statement
        for statement in statements
        if isinstance(statement, exp.Create)
        and (statement.kind or "").upper() == "TABLE"
    ]
    if len(creates) != 1:
        raise ValidationError(
            "Target schema compilation must emit exactly one CREATE TABLE"
        )

    properties: list[SchemaPropertyState] = []
    seen: set[str] = set()

    for column in creates[0].find_all(exp.ColumnDef):
        name = column.name.strip()
        if not name:
            raise ValidationError("Target schema contains an empty column identity")

        key = name.casefold()
        if key in seen:
            raise ValidationError(
                f"Duplicate physical column binding in target schema: '{name}'"
            )
        seen.add(key)

        data_type = column.args.get("kind")
        if (
            not isinstance(data_type, exp.DataType)
            or data_type.this in _UNRESOLVED_SQL_TYPES
        ):
            raise ValidationError(
                f"Unsupported target physicalType for column '{name}'"
            )

        properties.append(
            SchemaPropertyState(
                identity=name,
                physical_type=data_type.sql(dialect=dialect),
                nullable=column.find(exp.NotNullColumnConstraint) is None,
                native_definition=column.sql(dialect=dialect),
            )
        )

    if not properties:
        raise ValidationError("Target schema compilation emitted no properties")

    return SchemaAssetState(
        identity=asset_identity,
        properties=tuple(properties),
    )


def normalize_sql_type(
    value: str | None,
    *,
    dialect: str,
) -> str | None:
    """Canonicalize one observed native type using a SQL dialect parser."""
    if value is None:
        return None

    try:
        parsed = sqlglot.parse_one(
            value.strip(),
            into=exp.DataType,
            dialect=dialect,
        )
    except Exception as exc:
        raise ValidationError(
            f"Unsupported {dialect} physicalType: '{value}'"
        ) from exc

    if (
        not isinstance(parsed, exp.DataType)
        or parsed.this in _UNRESOLVED_SQL_TYPES
    ):
        raise ValidationError(f"Unsupported {dialect} physicalType: '{value}'")

    return parsed.sql(dialect=dialect)


def map_odcs_schema_asset(
    schema: SchemaObject,
    *,
    asset_identity: str,
    use_physical_property_names: bool,
) -> SchemaAssetState:
    """Direct ODCS projection for provider-neutral reconciliation callers."""
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
    normalize_physical_type: Callable[[str | None], str | None] | None = None,
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


def _required_text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
