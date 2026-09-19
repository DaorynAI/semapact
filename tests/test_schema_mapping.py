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
    parse_sql_target_asset,
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


def test_pass_through_mapper_projects_governed_logical_identity() -> None:
    mapper = PassThroughSchemaMapper()

    desired = mapper.map_desired_asset(
        _schema(),
        asset_identity="orders",
    )

    assert [prop.identity for prop in desired.properties] == [
        "customer_id",
        "note",
    ]
    assert desired.properties[0].physical_type == "BIGINT"
    assert desired.properties[0].nullable is False
    assert desired.properties[1].nullable is True


def test_pass_through_mapper_projects_runtime_physical_names_back_to_governed_identity() -> None:
    schema = _schema()
    mapper = PassThroughSchemaMapper()

    observed = mapper.map_observed_asset(
        _observed(),
        asset_identity="orders",
        property_bindings=build_physical_property_bindings(
            schema.properties or []
        ),
    )

    assert [prop.identity for prop in observed.properties] == [
        "customer_id",
        "note",
    ]


def test_schema_mapper_contract_operates_on_whole_assets() -> None:
    mapper: SchemaMapper = PassThroughSchemaMapper()

    desired = mapper.map_desired_asset(
        _schema(),
        asset_identity="orders",
    )
    observed = mapper.map_observed_asset(
        _observed(),
        asset_identity="orders",
    )

    assert desired.identity == "orders"
    assert observed.identity == "orders"



def test_sql_target_parser_keeps_only_top_level_nested_columns() -> None:
    asset = parse_sql_target_asset(
        (
            "CREATE TABLE orders ("
            "payload STRUCT<a: INT, b: STRING>, "
            "attrs MAP<STRING, BIGINT>, "
            "values ARRAY<DECIMAL(10,2)>"
            ")"
        ),
        asset_identity="orders",
        dialect="databricks",
    )

    assert [prop.identity for prop in asset.properties] == [
        "payload",
        "attrs",
        "values",
    ]
    assert len(asset.properties) == 3
    assert asset.properties[0].native_definition.startswith("`payload` STRUCT")
