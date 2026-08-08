"""Great Expectations export adapter for ODCS contracts.

Responsibilities:
- normalize supported contract inputs into the canonical ODCS model
- delegate GE suite generation to datacontract-cli's built-in exporter
- run a lightweight GE-specific preflight check on the exported suite payload
- build a notebook/runtime-friendly ExpectationSuite object

Validation boundary:
- Contract-level quality rule validation belongs in `semapact.core.validator`
- GE-specific expectation validation belongs here, after datacontract-cli has
  mapped ODCS rules to Great Expectations expectation configs

This module intentionally does not:
- execute Spark or pandas validations
- implement governance logic
- implement vendor-specific deployment beyond Great Expectations suite generation
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, TypedDict, cast

from datacontract.export.exporter import ExportFormat
from datacontract.export.exporter_factory import exporter_factory
from open_data_contract_standard.model import OpenDataContractStandard

from semapact.utils.schema_utils import contract_to_model

LOGGER = logging.getLogger(__name__)


class ExpectationConfigDict(TypedDict, total=False):
    """Minimal JSON shape for one exported GE expectation."""

    expectation_type: str
    type: str
    kwargs: dict[str, Any]
    meta: dict[str, Any]


class ExpectationSuiteDict(TypedDict, total=False):
    """Minimal JSON shape returned by datacontract-cli GE exporter."""

    name: str
    expectations: list[ExpectationConfigDict]


@dataclass(slots=True)
class GreatExpectationsExporter:
    """Export ODCS contracts to Great Expectations suites via datacontract-cli.

    This is the GE adapter for generic Spark/pandas-style runtime validation.
    It is not the deployment mechanism for Databricks constraints or Lakeflow
    expectations.
    """

    def generate_suite(
        self,
        contract: OpenDataContractStandard | str | Path,
        *,
        schema_name: str = "all",
        suite_name: str | None = None,
        engine: str = "pandas",
    ) -> Any:
        model = contract_to_model(contract)
        if not hasattr(model, "schema_"):
            setattr(model, "schema_", getattr(model, "schema", None))
        return generate_expectation_suite(
            model, schema_name=schema_name, suite_name=suite_name, engine=engine
        )

    def export_to_path(
        self,
        contract: OpenDataContractStandard | str | Path,
        output_path: str,
        *,
        schema_name: str = "all",
        suite_name: str | None = None,
        engine: str = "pandas",
    ) -> Path:
        suite = self.generate_suite(
            contract, schema_name=schema_name, suite_name=suite_name, engine=engine
        )
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        if hasattr(suite, "to_json_dict"):
            payload = suite.to_json_dict()
        elif hasattr(suite, "to_dict"):
            payload = suite.to_dict()
        else:
            payload = _to_json_safe_dict(suite)

        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path


def generate_expectation_suite(
    contract: OpenDataContractStandard,
    schema_name: str = "all",
    suite_name: Optional[str] = None,
    engine: str = "pandas",
) -> Any:
    """Generate a Great Expectations suite using datacontract-cli exporter.

    The exporter first maps ODCS quality rules into GE expectation JSON and then
    performs a GE-specific preflight check to catch unknown expectation types
    before notebook/runtime execution.
    """
    exporter = exporter_factory.create(ExportFormat.great_expectations)
    try:
        exported = exporter.export(
            data_contract=contract,
            schema_name=schema_name,
            server="",
            sql_server_type="auto",
            export_args={"engine": engine, "suite_name": suite_name},
        )
    except ModuleNotFoundError as exc:
        if exc.name == "pyspark" and engine == "spark":
            from semapact.exceptions import LifecycleError

            raise LifecycleError(
                "datacontract-cli Great Expectations export with engine='spark' requires pyspark to be installed"
            ) from exc
        raise
    suite_dict = cast(ExpectationSuiteDict, json.loads(exported))
    _validate_ge_suite_dict(suite_dict)
    return _suite_dict_to_expectation_suite(suite_dict)


def _suite_dict_to_expectation_suite(suite_dict: ExpectationSuiteDict) -> Any:
    """Build a GE ExpectationSuite instance from exported JSON."""
    ExpectationSuite, ExpectationConfiguration = _load_ge_suite_classes()
    get_expectation_impl = _load_ge_expectation_registry()

    suite_name = suite_dict.get("name") or "semapact_suite"
    expectation_suite = _create_suite_object(ExpectationSuite, suite_name)

    for expectation in suite_dict.get("expectations", []):
        if not isinstance(expectation, dict):
            continue
        expectation_type = _expectation_type(expectation)
        if not expectation_type:
            continue

        expectation_obj = _create_expectation_object(
            get_expectation_impl=get_expectation_impl,
            expectation_type=expectation_type,
            kwargs=expectation.get("kwargs", {}),
            meta=expectation.get("meta", {}),
            raw_expectation=expectation,
        )
        if expectation_obj is None:
            expectation_obj = _create_expectation_config(
                ExpectationConfiguration,
                expectation_type=expectation_type,
                kwargs=expectation.get("kwargs", {}),
                meta=expectation.get("meta", {}),
            )
        _add_expectation(expectation_suite, expectation_obj)

    return expectation_suite


def _validate_ge_suite_dict(suite_dict: ExpectationSuiteDict) -> None:
    """Run lightweight GE-specific sanity checks before building a suite.

    This is intentionally a preflight check, not a runtime data validation. It
    ensures the exported suite shape is sane and that each expectation type can
    be resolved by the installed Great Expectations registry.
    """
    if not isinstance(suite_dict, dict):
        raise ValueError(
            "Great Expectations exporter output must deserialize into a mapping object"
        )

    expectations = suite_dict.get("expectations", [])
    if not isinstance(expectations, list):
        raise ValueError("Great Expectations suite must contain an expectations list")

    get_expectation_impl = _load_ge_expectation_registry()

    for index, expectation in enumerate(expectations):
        if not isinstance(expectation, dict):
            raise ValueError(f"Expectation at index {index} must be a mapping object")

        expectation_type = _expectation_type(expectation)
        if not expectation_type:
            raise ValueError(
                f"Expectation at index {index} must define expectation_type or type"
            )

        try:
            expectation_impl = get_expectation_impl(expectation_type)
        except Exception as exc:
            from semapact.exceptions import ValidationError

            raise ValidationError(
                f"Failed to resolve Great Expectations rule '{expectation_type}'"
            ) from exc

        if not expectation_impl:
            raise ValueError(f"Unknown Great Expectations rule '{expectation_type}'")


def _expectation_type(expectation: ExpectationConfigDict) -> str:
    """Resolve the GE expectation type from exporter JSON."""
    return str(
        expectation.get("expectation_type") or expectation.get("type") or ""
    ).strip()


def _create_suite_object(ExpectationSuite: Any, suite_name: str) -> Any:
    try:
        return ExpectationSuite(expectation_suite_name=suite_name)
    except TypeError:
        return ExpectationSuite(name=suite_name)


def _create_expectation_config(
    ExpectationConfiguration: Any,
    *,
    expectation_type: str,
    kwargs: dict[str, Any],
    meta: dict[str, Any],
) -> Any:
    """Create an expectation config across GE version differences."""
    try:
        return ExpectationConfiguration(
            expectation_type=expectation_type,
            kwargs=kwargs,
            meta=meta,
        )
    except TypeError:
        try:
            return ExpectationConfiguration(
                type=expectation_type,
                kwargs=kwargs,
                meta=meta,
            )
        except TypeError:
            return ExpectationConfiguration(expectation_type, kwargs, meta)


def _create_expectation_object(
    *,
    get_expectation_impl: Any,
    expectation_type: str,
    kwargs: dict[str, Any],
    meta: dict[str, Any],
    raw_expectation: dict[str, Any],
) -> Any | None:
    """Create a runtime expectation object when the installed GE version expects it."""
    try:
        expectation_impl = get_expectation_impl(expectation_type)
    except (ImportError, AttributeError, KeyError) as e:
        LOGGER.debug(f"Could not load GE expectation impl {expectation_type}: {e}")
        return None

    if not callable(expectation_impl):
        return None

    init_kwargs = dict(kwargs)
    if meta:
        init_kwargs["meta"] = meta

    for key in (
        "notes",
        "description",
        "severity",
        "success_on_last_run",
        "id",
        "rendered_content",
    ):
        if key in raw_expectation:
            init_kwargs[key] = raw_expectation[key]

    try:
        return expectation_impl(**init_kwargs)
    except Exception as e:
        LOGGER.debug(f"Failed to instantiate GE expectation {expectation_type}: {e}")
        return None


def _add_expectation(expectation_suite: Any, config: Any) -> None:
    if hasattr(expectation_suite, "add_expectation"):
        try:
            expectation_suite.add_expectation(expectation_configuration=config)
            return
        except Exception as e1:
            try:
                expectation_suite.add_expectation(config)
                return
            except Exception as e2:
                LOGGER.debug(f"Failed both add_expectation signatures: {e1} / {e2}")

    expectations = getattr(expectation_suite, "expectations", None)
    if isinstance(expectations, list):
        expectations.append(config)
        return
    raise TypeError("Unsupported ExpectationSuite object: cannot add expectations")


def _load_ge_suite_classes() -> tuple[Any, Any]:
    try:
        from great_expectations.core import ExpectationConfiguration, ExpectationSuite

        return ExpectationSuite, ExpectationConfiguration
    except ImportError as first_exc:
        try:
            from great_expectations.core.expectation_configuration import (
                ExpectationConfiguration,
            )
            from great_expectations.core.expectation_suite import ExpectationSuite

            return ExpectationSuite, ExpectationConfiguration
        except ImportError as second_exc:
            try:
                from great_expectations.expectations.expectation_configuration import (
                    ExpectationConfiguration,
                )
                from great_expectations.core.expectation_suite import ExpectationSuite

                return ExpectationSuite, ExpectationConfiguration
            except ImportError as third_exc:
                LOGGER.error(
                    "Great Expectations import failed: %s ; %s ; %s",
                    first_exc,
                    second_exc,
                    third_exc,
                )
                raise RuntimeError(
                    "great_expectations is required to generate expectation suites at runtime"
                ) from third_exc


def _load_ge_expectation_registry() -> Any:
    """Load the GE expectation registry used for export-time preflight checks."""
    try:
        from great_expectations.expectations.registry import get_expectation_impl

        return get_expectation_impl
    except (ImportError, AttributeError) as exc:
        from semapact.exceptions import LifecycleError

        raise LifecycleError(
            "great_expectations expectation registry is required to validate exported suites"
        ) from exc


def _to_json_safe_dict(value: Any) -> dict[str, Any]:
    """Fallback JSON serialization for suite-like objects across GE versions."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return {"value": str(value)}
