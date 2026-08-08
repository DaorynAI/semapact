from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from pathlib import Path

from open_data_contract_standard.model import (
    DataQuality,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.utils.schema_utils import contract_to_model


@dataclass(slots=True)
class ValidationIssue:
    """Represents a contract validation issue."""

    path: str
    message: str
    severity: str = "error"


@dataclass(slots=True)
class ValidationReport:
    """Validation result envelope."""

    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)


@dataclass(slots=True)
class ContractValidator:
    """Validate ODCS schema structure and quality rule completeness."""

    def validate(
        self, contract_input: OpenDataContractStandard | dict[str, Any] | str | Path
    ) -> ValidationReport:
        from datacontract.data_contract import DataContract
        from pydantic import ValidationError

        issues: list[ValidationIssue] = []

        # 1. Strict ODCS Pydantic validation
        contract = None
        try:
            contract = _normalize_contract(contract_input)
        except ValidationError as e:
            for error in e.errors():
                loc = ".".join(str(p) for p in error["loc"])
                issues.append(
                    ValidationIssue(path=loc, message=error["msg"], severity="error")
                )
        except Exception as e:
            from semapact.exceptions import ValidationError as CHValidationError

            raise CHValidationError(f"Failed to normalize contract: {e}") from e

        if not contract:
            return ValidationReport(valid=False, issues=issues)

        # 2. Base datacontract-cli linting (fastjsonschema)
        # We can pass the validated model directly to DataContract.
        # This bypasses serialization issues where fastjsonschema fails on intermediate dict representations.
        cli_dc = DataContract(data_contract=contract)
        run_result = cli_dc.lint()

        if run_result and run_result.checks:
            for check in run_result.checks:
                # check.result is an enum DataContract ResultEnum, but mypy might not know
                if check.result and getattr(check.result, "name", str(check.result)) != "passed":
                    issues.append(
                        ValidationIssue(
                            path="datacontract-cli",
                            message=check.reason or getattr(check, "name", "Validation failed"),
                            severity="error",
                        )
                    )

        # 3. Advanced semantic checks
        if contract and contract.schema_:
            for schema_idx, schema_obj in enumerate(contract.schema_):
                issues.extend(self._validate_schema_object(schema_idx, schema_obj))

        return ValidationReport(valid=not issues, issues=issues)

    def _validate_schema_object(
        self, schema_idx: int, schema_obj: SchemaObject
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        path = f"schema[{schema_idx}]"

        if schema_obj.properties:
            for prop_idx, prop in enumerate(schema_obj.properties):
                issues.extend(
                    self._validate_property(f"{path}.properties[{prop_idx}]", prop)
                )

        if schema_obj.quality:
            issues.extend(
                self._validate_quality_rules(f"{path}.quality", schema_obj.quality)
            )

        return issues

    def _validate_property(
        self, path: str, prop: SchemaProperty
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if prop.quality:
            issues.extend(self._validate_quality_rules(f"{path}.quality", prop.quality))

        if prop.properties:
            for idx, nested_prop in enumerate(prop.properties):
                issues.extend(
                    self._validate_property(f"{path}.properties[{idx}]", nested_prop)
                )

        if prop.items:
            issues.extend(self._validate_property(f"{path}.items", prop.items))

        return issues

    def _validate_quality_rules(
        self, path: str, rules: Iterable[DataQuality | None]
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        for idx, rule in enumerate(rules):
            if rule is None:
                issues.append(
                    ValidationIssue(
                        path=f"{path}[{idx}]", message="Quality rule must not be null"
                    )
                )
                continue

            issues.extend(self._validate_quality_rule(f"{path}[{idx}]", rule))

        return issues

    def _validate_quality_rule(
        self, path: str, rule: DataQuality
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        rule_type = self._quality_rule_type(rule)

        if rule_type not in {"library", "text", "sql", "custom"}:
            issues.append(
                ValidationIssue(
                    path=f"{path}.type",
                    message="Quality rule type must be one of: library, text, sql, custom",
                )
            )
            return issues

        if rule_type == "library":
            metric = str(rule.metric or rule.rule or "").strip()
            if not metric:
                issues.append(
                    ValidationIssue(
                        path=f"{path}.metric",
                        message="Library quality rule metric is required",
                    )
                )
                return issues

            if metric not in {
                "nullValues",
                "missingValues",
                "invalidValues",
                "duplicateValues",
                "rowCount",
            }:
                issues.append(
                    ValidationIssue(
                        path=f"{path}.metric",
                        message="Unsupported ODCS library metric",
                    )
                )

            if not self._has_comparison(rule):
                issues.append(
                    ValidationIssue(
                        path=path,
                        message="Library quality rule must include at least one comparison operator",
                    )
                )

            arguments = rule.arguments
            if metric == "missingValues" and not self._argument_value(
                arguments, "missingValues"
            ):
                issues.append(
                    ValidationIssue(
                        path=f"{path}.arguments.missingValues",
                        message="missingValues metric requires arguments.missingValues",
                    )
                )
            if metric == "invalidValues" and not (
                self._argument_value(arguments, "validValues")
                or self._argument_value(arguments, "pattern")
            ):
                issues.append(
                    ValidationIssue(
                        path=f"{path}.arguments",
                        message="invalidValues metric requires arguments.validValues or arguments.pattern",
                    )
                )
            if (
                metric == "duplicateValues"
                and path.startswith("schema[")
                and ".properties[" not in path
            ):
                if not self._argument_value(arguments, "properties"):
                    issues.append(
                        ValidationIssue(
                            path=f"{path}.arguments.properties",
                            message="Schema-level duplicateValues metric requires arguments.properties",
                        )
                    )

        elif rule_type == "text":
            if not str(rule.description or "").strip():
                issues.append(
                    ValidationIssue(
                        path=f"{path}.description",
                        message="Text quality rule description is required",
                    )
                )

        elif rule_type == "sql":
            if not str(rule.query or "").strip():
                issues.append(
                    ValidationIssue(
                        path=f"{path}.query",
                        message="SQL quality rule query is required",
                    )
                )
            if not self._has_comparison(rule):
                issues.append(
                    ValidationIssue(
                        path=path,
                        message="SQL quality rule must include at least one comparison operator",
                    )
                )

        elif rule_type == "custom":
            if not str(rule.engine or "").strip():
                issues.append(
                    ValidationIssue(
                        path=f"{path}.engine",
                        message="Custom quality rule engine is required",
                    )
                )
            if not str(rule.implementation or "").strip():
                issues.append(
                    ValidationIssue(
                        path=f"{path}.implementation",
                        message="Custom quality rule implementation is required",
                    )
                )

        return issues

    def _quality_rule_type(self, rule: DataQuality) -> str:
        explicit_type = str(rule.type or "").strip()
        if explicit_type:
            return explicit_type
        if rule.metric or rule.rule:
            return "library"
        return "library"

    def _has_comparison(self, rule: DataQuality) -> bool:
        return any(
            value is not None
            for value in (
                rule.mustBe,
                rule.mustNotBe,
                rule.mustBeGreaterThan,
                rule.mustBeGreaterOrEqualTo,
                rule.mustBeLessThan,
                rule.mustBeLessOrEqualTo,
                rule.mustBeBetween,
                rule.mustNotBeBetween,
            )
        )

    def _argument_value(self, arguments: dict[str, Any] | None, key: str) -> Any:
        if arguments is None:
            return None
        return arguments.get(key)


def validate(
    contract_input: OpenDataContractStandard | dict[str, Any] | str | Path,
) -> ValidationReport:
    """Validate a contract input using the shared ContractValidator."""
    return ContractValidator().validate(contract_input)


def _normalize_contract(
    contract_input: OpenDataContractStandard | dict[str, Any] | str | Path,
) -> OpenDataContractStandard:
    """Normalize supported validator inputs into the canonical ODCS model."""
    if isinstance(contract_input, dict):
        return OpenDataContractStandard.model_validate(contract_input)
    return contract_to_model(contract_input)
