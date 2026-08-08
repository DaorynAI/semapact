import pytest
import builtins
import sys
from types import ModuleType


import semapact.quality.ge_exporter as ge_adapter


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_suite_dict_defaults_name_and_skips_invalid_entries(monkeypatch):
    class FakeExpectationConfiguration:
        def __init__(self, expectation_type, kwargs, meta):
            self.expectation_type = expectation_type
            self.kwargs = kwargs
            self.meta = meta

    class FakeSuite:
        def __init__(self, expectation_suite_name):
            self.expectation_suite_name = expectation_suite_name
            self.expectations = []

        def add_expectation(self, expectation_configuration):
            self.expectations.append(expectation_configuration)

    monkeypatch.setattr(
        ge_adapter,
        "_load_ge_suite_classes",
        lambda: (FakeSuite, FakeExpectationConfiguration),
    )
    suite = ge_adapter._suite_dict_to_expectation_suite(  # noqa: SLF001
        {
            "expectations": [
                "not-a-dict",
                {"kwargs": {}},
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "id"},
                },
            ]
        }
    )
    assert suite.expectation_suite_name == "semapact_suite"
    assert len(suite.expectations) == 1
    assert (
        suite.expectations[0].expectation_type == "expect_column_values_to_not_be_null"
    )


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_validate_ge_suite_dict_rejects_unknown_expectation(monkeypatch):
    monkeypatch.setattr(
        ge_adapter,
        "_load_ge_expectation_registry",
        lambda: lambda expectation_type: None,
    )

    with pytest.raises(Exception, match="Unknown Great Expectations rule"):
        ge_adapter._validate_ge_suite_dict(  # noqa: SLF001
            {
                "expectations": [
                    {
                        "type": "definitely_not_real_expectation",
                        "kwargs": {},
                    }
                ]
            }
        )


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_validate_ge_suite_dict_requires_expectations_list(monkeypatch):
    monkeypatch.setattr(
        ge_adapter,
        "_load_ge_expectation_registry",
        lambda: lambda expectation_type: object(),
    )

    with pytest.raises(Exception, match="expectations list"):
        ge_adapter._validate_ge_suite_dict({"expectations": {}})  # noqa: SLF001


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_validate_ge_suite_dict_accepts_real_ge_expectation_class():
    ge_adapter._validate_ge_suite_dict(  # noqa: SLF001
        {
            "expectations": [
                {
                    "type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "id"},
                    "meta": {},
                }
            ]
        }
    )


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_create_suite_object_falls_back_to_name_kwarg():
    class FallbackSuite:
        def __init__(self, **kwargs):
            if "expectation_suite_name" in kwargs:
                raise TypeError("unsupported")
            self.name = kwargs["name"]

    suite = ge_adapter._create_suite_object(FallbackSuite, "suite.alt")  # noqa: SLF001
    assert suite.name == "suite.alt"


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_create_expectation_config_supports_type_keyword_fallback():
    class FallbackExpectationConfiguration:
        def __init__(self, *, type, kwargs, meta):  # noqa: A002
            self.type = type
            self.kwargs = kwargs
            self.meta = meta

    config = ge_adapter._create_expectation_config(  # noqa: SLF001
        FallbackExpectationConfiguration,
        expectation_type="expect_column_values_to_not_be_null",
        kwargs={"column": "id"},
        meta={},
    )

    assert config.type == "expect_column_values_to_not_be_null"
    assert config.kwargs == {"column": "id"}


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_add_expectation_fallback_to_positional():
    class Suite:
        def __init__(self):
            self.calls = []

        def add_expectation(self, config):  # noqa: ANN001
            self.calls.append(config)

    suite = Suite()
    ge_adapter._add_expectation(suite, "cfg-1")  # noqa: SLF001
    assert suite.calls == ["cfg-1"]


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_add_expectation_appends_to_expectations_list():
    class Suite:
        expectations = []

    ge_adapter._add_expectation(Suite, "cfg-2")  # noqa: SLF001
    assert Suite.expectations[-1] == "cfg-2"


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_add_expectation_raises_on_unsupported_suite():
    class Suite:
        expectations = None

    with pytest.raises(TypeError, match="Unsupported ExpectationSuite"):
        ge_adapter._add_expectation(Suite(), "cfg")  # noqa: SLF001


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_load_ge_suite_classes_raises_runtime_error_when_imports_fail(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001
        if name.startswith("great_expectations"):
            raise ImportError("boom")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(Exception, match="great_expectations is required"):
        ge_adapter._load_ge_suite_classes()  # noqa: SLF001


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_load_ge_suite_classes_uses_fallback_import_path(monkeypatch):
    class ExpectationConfiguration:
        pass

    class ExpectationSuite:
        pass

    fallback_cfg = ModuleType("great_expectations.core.expectation_configuration")
    fallback_cfg.ExpectationConfiguration = ExpectationConfiguration
    fallback_suite = ModuleType("great_expectations.core.expectation_suite")
    fallback_suite.ExpectationSuite = ExpectationSuite
    monkeypatch.setitem(
        sys.modules, "great_expectations.core.expectation_configuration", fallback_cfg
    )
    monkeypatch.setitem(
        sys.modules, "great_expectations.core.expectation_suite", fallback_suite
    )

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001
        if name == "great_expectations.core":
            raise ImportError("force primary path failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    suite_cls, config_cls = ge_adapter._load_ge_suite_classes()  # noqa: SLF001
    assert suite_cls is ExpectationSuite
    assert config_cls is ExpectationConfiguration


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_load_ge_suite_classes_primary_import_path_success():
    suite_cls, config_cls = ge_adapter._load_ge_suite_classes()  # noqa: SLF001
    assert suite_cls is not None
    assert config_cls is not None


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_generate_expectation_suite_surfaces_clear_error_when_pyspark_is_missing(
    monkeypatch,
):
    class FakeExporter:
        @staticmethod
        def export(*args, **kwargs):  # noqa: ANN002, ANN003
            raise ModuleNotFoundError("No module named 'pyspark'", name="pyspark")

    monkeypatch.setattr(ge_adapter.exporter_factory, "create", lambda _: FakeExporter())

    with pytest.raises(Exception, match="requires pyspark"):
        ge_adapter.generate_expectation_suite(contract=object(), schema_name="all", engine="spark")
