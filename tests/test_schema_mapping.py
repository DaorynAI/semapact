from __future__ import annotations

from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.observation.models import (
    ObservedAsset,
    ObservedAssetIdentity,
    ObservedProperty,
    ObservedPropertyIdentity,
)
from semapact.schema import (
    PassThroughSchemaMapper,
    SchemaMapper,
    build_physical_property_bindings,
    map_desired_schema_asset,
    map_observed_schema_asset,
)


def _schema() -> SchemaObject:
    return SchemaObject(
        name="orders",
        properties=[
            SchemaProperty(
                name="customer_id",
                physicalName="customerId",
                physicalType="BIGINT",
                required=True,
            ),
            SchemaProperty(
                name="note",
                physicalType="STRING",
                required=False,
            ),
        ],
    )


def _observed() -> ObservedAsset:
    identity = ObservedAssetIdentity(
        platform="example",
        namespace=("main",),
        asset="orders",
    )
    return ObservedAsset(
        identity=identity,
        properties=(
            ObservedProperty(
                identity=ObservedPropertyIdentity(
                    asset=identity,
                    property="customerId",
                ),
                physical_type="bigint",
                nullable=False,
            ),
            ObservedProperty(
                identity=ObservedPropertyIdentity(
                    asset=identity,
                    property="note",
                ),
                physical_type="string",
                nullable=True,
            ),
        ),
    )


def test_shared_mapping_projects_logical_or_physical_property_identity() -> None:
    mapper = PassThroughSchemaMapper()
    schema = _schema()

    logical = map_desired_schema_asset(
        schema,
        asset_identity="orders",
        mapper=mapper,
        use_physical_property_names=False,
    )
    physical = map_desired_schema_asset(
        schema,
        asset_identity="orders",
        mapper=mapper,
        use_physical_property_names=True,
    )

    assert [prop.identity for prop in logical.properties] == [
        "customer_id",
        "note",
    ]
    assert [prop.identity for prop in physical.properties] == [
        "customerId",
        "note",
    ]
    assert logical.properties[0].nullable is False
    assert logical.properties[1].nullable is True


def test_shared_mapping_projects_runtime_physical_names_back_to_governed_identity() -> None:
    schema = _schema()
    mapped = map_observed_schema_asset(
        _observed(),
        asset_identity="orders",
        mapper=PassThroughSchemaMapper(),
        property_bindings=build_physical_property_bindings(
            schema.properties or []
        ),
    )

    assert [prop.identity for prop in mapped.properties] == [
        "customer_id",
        "note",
    ]


def test_provider_mapper_owns_type_normalization_only() -> None:
    class UppercaseMapper:
        key = "test"

        def normalize_desired_type(self, prop: SchemaProperty) -> str | None:
            value = getattr(prop, "physicalType", None)
            return None if value is None else str(value).upper()

        def normalize_observed_type(self, value: str | None) -> str | None:
            return None if value is None else value.upper()

    mapper: SchemaMapper = UppercaseMapper()
    desired = map_desired_schema_asset(
        _schema(),
        asset_identity="orders",
        mapper=mapper,
        use_physical_property_names=True,
    )
    observed = map_observed_schema_asset(
        _observed(),
        asset_identity="orders",
        mapper=mapper,
    )

    assert desired.properties[0].physical_type == "BIGINT"
    assert observed.properties[0].physical_type == "BIGINT"
