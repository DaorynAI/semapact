from __future__ import annotations
import sys


import json

import pandas as pd
import pytest

import semapact.quality.ge_exporter as ge_adapter


def _create_pandas_validator(df: pd.DataFrame, expectation_suite):
    gx = pytest.importorskip("great_expectations")

    context = gx.get_context(mode="ephemeral")
    datasource_name = "semapact_runtime_pandas"
    asset_name = "semapact_runtime_asset"

    try:
        datasource = context.data_sources.get(datasource_name)
    except Exception:
        datasource = context.data_sources.add_pandas(name=datasource_name)

    try:
        asset = datasource.get_asset(asset_name)
    except Exception:
        asset = datasource.add_dataframe_asset(name=asset_name)
        asset.add_batch_definition_whole_dataframe("whole_dataframe")

    batch_request = asset.build_batch_request(options={"dataframe": df})
    return context.get_validator(
        batch_request=batch_request, expectation_suite=expectation_suite
    )


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_generate_expectation_suite_can_validate_pandas_dataframe_with_real_ge_runtime(
    monkeypatch,
    sample_custom_ge_quality_contract_model,
):
    class FakeExporter:
        @staticmethod
        def export(data_contract, schema_name, server, sql_server_type, export_args):
            assert data_contract == sample_custom_ge_quality_contract_model
            assert schema_name == "orders"
            assert export_args["engine"] == "pandas"
            return json.dumps(
                {
                    "name": "suite.orders",
                    "expectations": [
                        {
                            "type": "expect_column_values_to_not_be_null",
                            "kwargs": {"column": "id"},
                            "meta": {},
                        }
                    ],
                }
            )

    monkeypatch.setattr(ge_adapter.exporter_factory, "create", lambda _: FakeExporter())

    suite = ge_adapter.generate_expectation_suite(
        sample_custom_ge_quality_contract_model, schema_name="orders"
    )
    validator = _create_pandas_validator(pd.DataFrame({"id": ["a", "b"]}), suite)
    result = validator.validate()

    result_dict = result.to_json_dict() if hasattr(result, "to_json_dict") else result
    assert result_dict["success"] is True
