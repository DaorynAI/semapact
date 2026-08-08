from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from semapact.core.loader import load_contract
from semapact.quality.ge_exporter import generate_expectation_suite

LOGGER = logging.getLogger(__name__)


def create_spark_validator(spark_df: Any, expectation_suite: Any) -> Any:
    """Create a GE validator for Spark DataFrame runtime execution."""
    gx = _load_great_expectations_module()
    RuntimeBatchRequest = _load_runtime_batch_request()
    _assert_ge_spark_runtime_classes()

    context = gx.get_context(mode="ephemeral")
    datasource_name = "semapact_runtime_spark"
    data_connector_name = "semapact_runtime_connector"

    try:
        context.add_datasource(
            name=datasource_name,
            class_name="Datasource",
            execution_engine={"class_name": "SparkDFExecutionEngine"},
            data_connectors={
                data_connector_name: {
                    "class_name": "RuntimeDataConnector",
                    "batch_identifiers": ["default_identifier_name"],
                }
            },
        )
    except Exception as exc:
        LOGGER.debug("Datasource add skipped/failed (may already exist): %s", exc)

    batch_request = RuntimeBatchRequest(
        datasource_name=datasource_name,
        data_connector_name=data_connector_name,
        data_asset_name="semapact_runtime_asset",
        runtime_parameters={"batch_data": spark_df},
        batch_identifiers={"default_identifier_name": "default_batch"},
    )

    return context.get_validator(
        batch_request=batch_request,
        expectation_suite=expectation_suite,
    )


def run_contract_tests_on_df(
    contract_path: str,
    spark_df: Any,
    *,
    schema_name: str = "all",
    contract_runtime_context: str | None = None,
) -> Dict[str, Any]:
    if contract_runtime_context is None:
        contract = load_contract(contract_path)
    else:
        contract = load_contract(
            contract_path, runtime_context=contract_runtime_context
        )
    expectation_suite = generate_expectation_suite(contract, schema_name=schema_name)
    validator = create_spark_validator(spark_df, expectation_suite)
    validation_result = validator.validate()
    formatted = format_validation_result(validation_result)
    LOGGER.info(
        "Contract validation on dataframe completed: success=%s", formatted["success"]
    )
    return formatted


def run_contract_tests_on_table(
    contract_path: str,
    table_fqn: str,
    spark_session: Any,
    *,
    schema_name: str = "all",
    contract_runtime_context: str | None = None,
) -> Dict[str, Any]:
    spark_df = spark_session.table(table_fqn)
    LOGGER.info("Loaded table as dataframe for validation: %s", table_fqn)
    return run_contract_tests_on_df(
        contract_path,
        spark_df,
        schema_name=schema_name,
        contract_runtime_context=contract_runtime_context,
    )


def run_contract_tests(
    *,
    contract_path: str,
    spark_df: Optional[Any] = None,
    table_fqn: Optional[str] = None,
    spark_session: Optional[Any] = None,
    schema_name: str = "all",
    contract_runtime_context: str | None = None,
) -> Dict[str, Any]:
    """Notebook-friendly top-level API."""
    if spark_df is not None:
        return run_contract_tests_on_df(
            contract_path,
            spark_df,
            schema_name=schema_name,
            contract_runtime_context=contract_runtime_context,
        )

    if table_fqn and spark_session is not None:
        return run_contract_tests_on_table(
            contract_path=contract_path,
            table_fqn=table_fqn,
            spark_session=spark_session,
            schema_name=schema_name,
            contract_runtime_context=contract_runtime_context,
        )

    raise ValueError(
        "Provide either spark_df or (table_fqn and spark_session) to run contract tests"
    )


def format_validation_result(validation_result: Any) -> Dict[str, Any]:
    """Format GE validation result into a standardized payload."""
    if isinstance(validation_result, dict):
        result_dict = validation_result
    elif hasattr(validation_result, "to_json_dict"):
        result_dict = validation_result.to_json_dict()
    else:
        return {"success": False, "statistics": {}, "failed_expectations": []}

    if not isinstance(result_dict, dict):
        return {"success": False, "statistics": {}, "failed_expectations": []}

    statistics = result_dict.get("statistics", {})
    failed = []

    for item in result_dict.get("results", []):
        if not isinstance(item, dict):
            continue
        success = item.get("success", False)
        if success:
            continue
        config = item.get("expectation_config", {})
        if not isinstance(config, dict):
            config = {}
        failed.append(
            {
                "expectation_type": config.get("expectation_type"),
                "kwargs": config.get("kwargs", {}),
                "result": item.get("result", {}),
            }
        )

    return {
        "success": bool(result_dict.get("success", False)),
        "statistics": statistics,
        "failed_expectations": failed,
    }


def _load_great_expectations_module() -> Any:
    try:
        import great_expectations as gx

        return gx
    except ImportError as exc:
        from semapact.exceptions import LifecycleError

        raise LifecycleError(
            "great_expectations is required for Spark validator runtime"
        ) from exc


def _load_runtime_batch_request() -> Any:
    try:
        from great_expectations.core.batch import RuntimeBatchRequest

        return RuntimeBatchRequest
    except ImportError as exc:
        from semapact.exceptions import LifecycleError

        raise LifecycleError(
            "RuntimeBatchRequest is unavailable in installed great_expectations version"
        ) from exc


def _assert_ge_spark_runtime_classes() -> None:
    try:
        from great_expectations.datasource.data_connector import RuntimeDataConnector
        from great_expectations.execution_engine import SparkDFExecutionEngine

        _ = RuntimeDataConnector, SparkDFExecutionEngine
    except ImportError as exc:
        from semapact.exceptions import LifecycleError

        raise LifecycleError(
            "Great Expectations Spark runtime components are unavailable: "
            "RuntimeDataConnector and SparkDFExecutionEngine are required"
        ) from exc
