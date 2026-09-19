from __future__ import annotations

from semapact.schema import (
    SchemaAssetState,
    SchemaDifferenceType,
    SchemaPropertyState,
    SchemaSnapshot,
    SchemaSubject,
    compare_schema_snapshots,
)


def _property(
    name: str,
    physical_type: str | None,
    nullable: bool | None,
) -> SchemaPropertyState:
    return SchemaPropertyState(
        identity=name,
        physical_type=physical_type,
        nullable=nullable,
    )


def test_shared_schema_comparator_reports_structural_and_value_facts() -> None:
    expected = SchemaSnapshot(
        assets=(
            SchemaAssetState(
                identity="orders",
                properties=(
                    _property("id", "BIGINT", False),
                    _property("amount", "DECIMAL(18,2)", True),
                ),
            ),
            SchemaAssetState(identity="customers"),
        )
    )
    observed = SchemaSnapshot(
        assets=(
            SchemaAssetState(
                identity="orders",
                properties=(
                    _property("id", "STRING", True),
                    _property("runtime_only", "STRING", True),
                ),
            ),
            SchemaAssetState(identity="payments"),
        )
    )

    result = compare_schema_snapshots(expected, observed)

    assert [
        (item.difference_type, item.subject, item.path)
        for item in result.differences
    ] == [
        (
            SchemaDifferenceType.MISSING,
            SchemaSubject.ASSET,
            "schema[customers]",
        ),
        (
            SchemaDifferenceType.MISSING,
            SchemaSubject.PROPERTY,
            "schema[orders].properties[amount]",
        ),
        (
            SchemaDifferenceType.MISMATCH,
            SchemaSubject.PHYSICAL_TYPE,
            "schema[orders].properties[id].physicalType",
        ),
        (
            SchemaDifferenceType.MISMATCH,
            SchemaSubject.NULLABILITY,
            "schema[orders].properties[id].nullability",
        ),
        (
            SchemaDifferenceType.UNEXPECTED,
            SchemaSubject.PROPERTY,
            "schema[orders].properties[runtime_only]",
        ),
        (
            SchemaDifferenceType.UNEXPECTED,
            SchemaSubject.ASSET,
            "schema[payments]",
        ),
    ]


def test_shared_schema_comparator_reports_evidence_gaps_without_policy() -> None:
    expected = SchemaSnapshot(
        assets=(
            SchemaAssetState(
                identity="orders",
                properties=(_property("id", "BIGINT", False),),
            ),
        )
    )
    observed = SchemaSnapshot(
        assets=(
            SchemaAssetState(
                identity="orders",
                properties=(_property("id", None, None),),
            ),
        )
    )

    result = compare_schema_snapshots(expected, observed)

    assert result.differences == ()
    assert result.unverified_paths == (
        "schema[orders].properties[id].nullability",
        "schema[orders].properties[id].physicalType",
    )


def test_shared_schema_comparator_is_case_insensitive_for_identity_and_type() -> None:
    expected = SchemaSnapshot(
        assets=(
            SchemaAssetState(
                identity="Orders",
                properties=(_property("ID", "BIGINT", False),),
            ),
        )
    )
    observed = SchemaSnapshot(
        assets=(
            SchemaAssetState(
                identity="orders",
                properties=(_property("id", "bigint", False),),
            ),
        )
    )

    result = compare_schema_snapshots(expected, observed)

    assert result.differences == ()
    assert result.unverified_paths == ()
