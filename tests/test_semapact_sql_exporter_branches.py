import pytest

from open_data_contract_standard.model import (
    DataQuality,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

import semapact.exporters.sql_exporter as exporter_mod


def _minimal_contract_model():
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="c1",
        name="c1",
        version="1.0.0",
        status="draft",
        schema=[
            SchemaObject(
                name="tbl",
                physicalName="tbl_phys",
                properties=[
                    SchemaProperty(
                        name="id",
                        physicalName="id_phys",
                        logicalType="integer",
                        physicalType="BIGINT",
                    )
                ],
            )
        ],
    )


def test_load_contract_model_from_dict_and_model():
    as_dict = _minimal_contract_model().model_dump(by_alias=True, exclude_none=True)
    loaded_from_dict = exporter_mod._load_contract_model(as_dict)  # noqa: SLF001
    assert loaded_from_dict.id == "c1"

    loaded_from_model = exporter_mod._load_contract_model(_minimal_contract_model())  # noqa: SLF001
    assert loaded_from_model.id == "c1"


def test_load_contract_model_invalid_yaml_raises(tmp_path):
    file_path = tmp_path / "bad.yaml"
    file_path.write_text("- list", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping object"):
        exporter_mod._load_contract_model(file_path)  # noqa: SLF001


def test_prepare_for_sql_export_handles_nested_items_and_existing_custom_property():
    model = _minimal_contract_model()
    prop = model.schema_[0].properties[0]
    prop.customProperties = [
        exporter_mod.CustomProperty(property="physicalType", value="BIGINT")
    ]
    prop.items = SchemaProperty(logicalType="string", physicalType="STRING")

    prepared = exporter_mod._prepare_for_sql_export(model, use_physical_names=True)  # noqa: SLF001
    schema = prepared.schema_[0]
    assert schema.name == "tbl_phys"
    assert schema.properties[0].name == "id_phys"
    assert len(schema.properties[0].customProperties) == 1


def test_upsert_unity_server_replaces_existing():
    contract = _minimal_contract_model()
    exporter_mod._upsert_unity_server(  # noqa: SLF001
        contract,
        server_name="semapact_target",
        catalog="main",
        schema_name="silver",
    )
    exporter_mod._upsert_unity_server(  # noqa: SLF001
        contract,
        server_name="semapact_target",
        catalog="main2",
        schema_name="gold",
    )
    servers = [s for s in (contract.servers or []) if s.server == "semapact_target"]
    assert len(servers) == 1
    assert servers[0].catalog == "main2"


def test_export_contract_appends_check_constraint_for_valid_values():
    contract = _minimal_contract_model()
    contract.schema_[0].properties[0].quality = [
        DataQuality(
            metric="invalidValues",
            mustBe=0,
            arguments={"validValues": ["A", "B"]},
        )
    ]

    ddl = exporter_mod.export_contract_to_spark_sql(contract)

    assert "ADD CONSTRAINT chk_tbl_phys_id_phys_valid_values" in ddl
    assert "CHECK (id_phys IN ('A', 'B'))" in ddl


def test_export_contract_appends_check_constraint_for_pattern():
    contract = _minimal_contract_model()
    contract.schema_[0].properties[0].quality = [
        DataQuality(
            metric="invalidValues",
            mustBe=0,
            arguments={"pattern": "^[A-Z]{2}$"},
        )
    ]

    ddl = exporter_mod.export_contract_to_spark_sql(contract)

    assert "ADD CONSTRAINT chk_tbl_phys_id_phys_pattern" in ddl
    assert "CHECK (id_phys RLIKE '^[A-Z]{2}$')" in ddl


def test_export_contract_does_not_duplicate_not_null_when_required_already_true():
    contract = _minimal_contract_model()
    contract.schema_[0].properties[0].required = True
    contract.schema_[0].properties[0].quality = [
        DataQuality(metric="nullValues", mustBe=0),
    ]

    ddl = exporter_mod.export_contract_to_spark_sql(contract)

    assert "id_phys BIGINT not null" in ddl
    assert "ALTER COLUMN id_phys SET NOT NULL" not in ddl


def test_export_contract_ignores_non_mappable_quality_rules():
    contract = _minimal_contract_model()
    contract.schema_[0].properties[0].quality = [
        DataQuality(metric="duplicateValues", mustBe=0),
        DataQuality(metric="rowCount", mustBeGreaterThan=0),
    ]

    ddl = exporter_mod.export_contract_to_spark_sql(contract)

    assert "ADD CONSTRAINT" not in ddl
    assert "ALTER COLUMN" not in ddl


def test_export_contract_does_not_append_quality_constraints_for_non_databricks_target():
    contract = _minimal_contract_model()
    contract.schema_[0].properties[0].quality = [
        DataQuality(metric="nullValues", mustBe=0),
        DataQuality(metric="invalidValues", mustBe=0, arguments={"validValues": ["A"]}),
    ]

    ddl = exporter_mod.export_contract_to_spark_sql(
        contract, sql_server_type="postgres"
    )

    assert "ALTER TABLE" not in ddl
    assert "ADD CONSTRAINT" not in ddl


def test_export_contract_rejects_unity_catalog_for_non_databricks_target():
    with pytest.raises(
        ValueError, match="only supported for sql_server_type=databricks"
    ):
        exporter_mod.export_contract_to_spark_sql(
            _minimal_contract_model(),
            unity_catalog="main",
            unity_schema="silver",
            sql_server_type="postgres",
        )


def test_export_contract_uses_constraint_friendly_quality_fixture(
    sample_constraint_quality_contract_path,
):
    ddl = exporter_mod.export_contract_to_spark_sql(
        sample_constraint_quality_contract_path
    )

    assert "ALTER COLUMN country_code SET NOT NULL" in ddl
    assert "ADD CONSTRAINT chk_quality_rules_country_code_pattern" in ddl
    assert "CHECK (country_code RLIKE '^[A-Z]{2}$')" in ddl
    assert "ADD CONSTRAINT chk_quality_rules_status_code_valid_values" in ddl
    assert "CHECK (status_code IN ('ACTIVE', 'INACTIVE', 'PENDING'))" in ddl
    assert "ALTER COLUMN processed_at SET NOT NULL" in ddl
