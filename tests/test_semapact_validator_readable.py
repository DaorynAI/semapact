from __future__ import annotations

from open_data_contract_standard.model import DataQuality

from semapact.core.validator import ContractValidator


def test_validator_accepts_full_sample_contract(sample_odcs_model):
    report = ContractValidator().validate(sample_odcs_model)

    assert report.valid is True
    assert report.issues == []


# Tests removed: redundant structural validations (like checking for empty schema name, etc)
# which are now delegated to datacontract-cli and pydantic. Pydantic accepts an empty list of properties
# if it's not strictly restricted, and we trust upstream linting instead of manual structural checks.


def test_validator_reports_quality_rule_missing_metric_and_threshold():
    validator = ContractValidator()

    issues = validator._validate_quality_rules(  # noqa: SLF001
        "schema[0].quality",
        [None, DataQuality()],
    )

    issue_paths = {issue.path for issue in issues}
    assert "schema[0].quality[0]" in issue_paths
    assert "schema[0].quality[1].metric" in issue_paths


def test_validator_accepts_custom_ge_quality_rule_without_metric():
    validator = ContractValidator()

    issues = validator._validate_quality_rules(  # noqa: SLF001
        "schema[0].quality",
        [
            DataQuality(
                type="custom",
                engine="greatExpectations",
                implementation="type: expect_table_row_count_to_be_between",
            )
        ],
    )

    assert issues == []


def test_validator_reports_sql_quality_rule_missing_query_or_comparison():
    validator = ContractValidator()

    issues = validator._validate_quality_rules(  # noqa: SLF001
        "schema[0].quality",
        [DataQuality(type="sql")],
    )

    issue_paths = {issue.path for issue in issues}
    assert "schema[0].quality[0].query" in issue_paths
    assert "schema[0].quality[0]" in issue_paths


def test_validator_reports_invalid_values_rule_missing_arguments():
    validator = ContractValidator()

    issues = validator._validate_quality_rules(  # noqa: SLF001
        "schema[0].properties[0].quality",
        [DataQuality(metric="invalidValues", mustBe=0)],
    )

    assert issues[0].path == "schema[0].properties[0].quality[0].arguments"


def test_validator_reports_schema_duplicate_values_without_properties_argument():
    validator = ContractValidator()

    issues = validator._validate_quality_rules(  # noqa: SLF001
        "schema[0].quality",
        [DataQuality(metric="duplicateValues", mustBe=0, arguments={})],
    )

    assert issues[0].path == "schema[0].quality[0].arguments.properties"


def test_validator_treats_metric_without_type_as_library_rule():
    validator = ContractValidator()

    issues = validator._validate_quality_rules(  # noqa: SLF001
        "schema[0].properties[0].quality",
        [DataQuality(metric="nullValues", mustBe=0)],
    )

    assert issues == []


def test_validator_accepts_additional_contract_fixtures(
    sample_spark_ddl_contract_model,
    sample_delta_rs_contract_model,
    sample_unity_contract_model,
    sample_custom_ge_quality_contract_model,
    sample_temporal_types_contract_model,
    sample_nested_types_contract_model,
    sample_numeric_precision_contract_model,
    sample_constraint_quality_contract_model,
    sample_enum_constraint_contract_model,
    sample_type_narrowing_base_contract_model,
    sample_type_narrowing_target_contract_model,
):
    validator = ContractValidator()

    assert validator.validate(sample_spark_ddl_contract_model).valid is True
    assert validator.validate(sample_delta_rs_contract_model).valid is True
    assert validator.validate(sample_unity_contract_model).valid is True
    assert validator.validate(sample_custom_ge_quality_contract_model).valid is True
    assert validator.validate(sample_temporal_types_contract_model).valid is True
    assert validator.validate(sample_nested_types_contract_model).valid is True
    assert validator.validate(sample_numeric_precision_contract_model).valid is True
    assert validator.validate(sample_constraint_quality_contract_model).valid is True
    assert validator.validate(sample_enum_constraint_contract_model).valid is True
    assert validator.validate(sample_type_narrowing_base_contract_model).valid is True
    assert validator.validate(sample_type_narrowing_target_contract_model).valid is True
