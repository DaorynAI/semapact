import pytest
import sys
import builtins


import semapact.quality.validation as scb


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_create_spark_validator_happy_path(monkeypatch):
    calls = {}

    class FakeValidator:
        pass

    class FakeContext:
        def add_datasource(self, **kwargs):  # noqa: ANN003
            calls["datasource"] = kwargs

        def get_validator(self, **kwargs):  # noqa: ANN003
            calls["validator"] = kwargs
            return FakeValidator()

    class FakeGX:
        @staticmethod
        def get_context(mode):  # noqa: ANN001
            assert mode == "ephemeral"
            return FakeContext()

    class FakeBatchRequest:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.kwargs = kwargs
            calls["batch"] = kwargs

    monkeypatch.setattr(scb, "_load_great_expectations_module", lambda: FakeGX())
    monkeypatch.setattr(scb, "_load_runtime_batch_request", lambda: FakeBatchRequest)
    monkeypatch.setattr(scb, "_assert_ge_spark_runtime_classes", lambda: None)

    validator = scb.create_spark_validator(
        spark_df=object(), expectation_suite=object()
    )
    assert isinstance(validator, FakeValidator)
    assert (
        calls["datasource"]["execution_engine"]["class_name"]
        == "SparkDFExecutionEngine"
    )
    assert calls["batch"]["data_asset_name"] == "semapact_runtime_asset"


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_create_spark_validator_tolerates_add_datasource_failure(monkeypatch):
    class FakeContext:
        @staticmethod
        def add_datasource(**kwargs):  # noqa: ANN003
            _ = kwargs
            raise RuntimeError("already exists")

        @staticmethod
        def get_validator(**kwargs):  # noqa: ANN003
            return {"ok": True, "kwargs": kwargs}

    class FakeGX:
        @staticmethod
        def get_context(mode):  # noqa: ANN001
            _ = mode
            return FakeContext()

    class FakeBatchRequest:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.kwargs = kwargs

    monkeypatch.setattr(scb, "_load_great_expectations_module", lambda: FakeGX())
    monkeypatch.setattr(scb, "_load_runtime_batch_request", lambda: FakeBatchRequest)
    monkeypatch.setattr(scb, "_assert_ge_spark_runtime_classes", lambda: None)

    result = scb.create_spark_validator(spark_df=object(), expectation_suite="suite")
    assert result["ok"] is True


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_load_great_expectations_module_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001
        if name == "great_expectations":
            raise ImportError("missing gx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(Exception, match="great_expectations is required"):
        scb._load_great_expectations_module()  # noqa: SLF001


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_load_runtime_batch_request_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001
        if name.startswith("great_expectations.core.batch"):
            raise ImportError("missing batch")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(Exception, match="RuntimeBatchRequest is unavailable"):
        scb._load_runtime_batch_request()  # noqa: SLF001


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_assert_ge_spark_runtime_classes_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001
        if name.startswith("great_expectations.datasource.data_connector"):
            raise ImportError("missing connector")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(Exception, match="Spark runtime components are unavailable"):
        scb._assert_ge_spark_runtime_classes()  # noqa: SLF001


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_runtime_helper_loaders_success_paths():
    gx = scb._load_great_expectations_module()  # noqa: SLF001
    assert hasattr(gx, "get_context")

    runtime_batch_request = scb._load_runtime_batch_request()  # noqa: SLF001
    assert runtime_batch_request is not None


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_assert_ge_spark_runtime_classes_success_with_mocked_import(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001
        if name == "great_expectations.datasource.data_connector":

            class RuntimeDataConnector:  # noqa: D401
                pass

            return type(
                "DataConnectorModule",
                (),
                {"RuntimeDataConnector": RuntimeDataConnector},
            )()
        if name == "great_expectations.execution_engine":

            class SparkDFExecutionEngine:  # noqa: D401
                pass

            return type(
                "ExecutionEngineModule",
                (),
                {"SparkDFExecutionEngine": SparkDFExecutionEngine},
            )()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    scb._assert_ge_spark_runtime_classes()  # noqa: SLF001
