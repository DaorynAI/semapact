import pytest

import semapact.quality.validation as runner


class FakeSparkDataFrame:
    """Sample spark-like dataframe object used for local unit tests."""


class FakeValidator:
    @staticmethod
    def validate():
        return {
            "success": True,
            "statistics": {"evaluated_expectations": 1, "successful_expectations": 1},
            "results": [],
        }


def test_run_contract_tests_on_df_with_sample_spark_df(monkeypatch):
    monkeypatch.setattr(runner, "load_contract", lambda _: object())
    monkeypatch.setattr(
        runner,
        "generate_expectation_suite",
        lambda contract, schema_name="all": object(),
    )
    monkeypatch.setattr(
        runner,
        "create_spark_validator",
        lambda spark_df, expectation_suite: FakeValidator(),
    )

    result = runner.run_contract_tests_on_df("contract.yaml", FakeSparkDataFrame())
    assert result["success"] is True
    assert result["failed_expectations"] == []


def test_run_contract_tests_on_table_reads_table_then_runs(monkeypatch):
    calls = {"table": None}

    class FakeSparkSession:
        @staticmethod
        def table(table_fqn):
            calls["table"] = table_fqn
            return FakeSparkDataFrame()

    monkeypatch.setattr(
        runner,
        "run_contract_tests_on_df",
        lambda contract_path, spark_df, schema_name="all", contract_runtime_context=None: {
            "success": True,
            "statistics": {},
            "failed_expectations": [],
        },
    )

    result = runner.run_contract_tests_on_table(
        contract_path="contract.yaml",
        table_fqn="main.sales.orders",
        spark_session=FakeSparkSession(),
    )
    assert calls["table"] == "main.sales.orders"
    assert result["success"] is True


def test_notebook_friendly_api_dispatch(monkeypatch):
    monkeypatch.setattr(
        runner,
        "run_contract_tests_on_df",
        lambda contract_path, spark_df, schema_name="all", contract_runtime_context=None: {
            "mode": "df"
        },
    )
    monkeypatch.setattr(
        runner,
        "run_contract_tests_on_table",
        lambda contract_path, table_fqn, spark_session, schema_name="all", contract_runtime_context=None: {
            "mode": "table"
        },
    )

    assert (
        runner.run_contract_tests(
            contract_path="contract.yaml", spark_df=FakeSparkDataFrame()
        )["mode"]
        == "df"
    )
    assert (
        runner.run_contract_tests(
            contract_path="contract.yaml",
            table_fqn="main.sales.orders",
            spark_session=object(),
        )["mode"]
        == "table"
    )


def test_run_contract_tests_on_df_passes_contract_runtime_context(monkeypatch):
    calls = {"context": None}

    def fake_load_contract(path, runtime_context=None):  # noqa: ANN001
        _ = path
        calls["context"] = runtime_context
        return object()

    monkeypatch.setattr(runner, "load_contract", fake_load_contract)
    monkeypatch.setattr(
        runner,
        "generate_expectation_suite",
        lambda contract, schema_name="all": object(),
    )
    monkeypatch.setattr(
        runner,
        "create_spark_validator",
        lambda spark_df, expectation_suite: FakeValidator(),
    )

    runner.run_contract_tests_on_df(
        "contract.yaml",
        FakeSparkDataFrame(),
        contract_runtime_context="synapse",
    )

    assert calls["context"] == "synapse"


def test_run_contract_tests_requires_df_or_table_inputs():
    with pytest.raises(ValueError, match="Provide either spark_df"):
        runner.run_contract_tests(contract_path="contract.yaml")
