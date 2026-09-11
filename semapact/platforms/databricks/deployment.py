"""Databricks write-side deployment adapter."""

from __future__ import annotations

import re
import time
from typing import Any

from open_data_contract_standard.model import SchemaObject, SchemaProperty

from semapact.deployment.models import (
    DeploymentActionKind,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    NativeOperation,
    NativeOperationKind,
    compute_deployment_preview_id,
    validate_deployment_authorization_identity,
    validate_deployment_plan_identity,
    validate_deployment_preview_identity,
)
from semapact.exceptions import ContractOpsAuthorizationError, ValidationError
from semapact.observation.fingerprint import fingerprint_observed_state
from semapact.observation.models import ObservedAsset, ObservedPlatformState
from semapact.observation.providers import RuntimeProvider
from semapact.platforms.databricks.target import parse_databricks_runtime_target
from semapact.runtime import RuntimeAssetSpec

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_DECIMAL_RE = re.compile(r"^DECIMAL\((\d{1,2}),(\d{1,2})\)$")
_CHAR_RE = re.compile(r"^(CHAR|VARCHAR)\((\d+)\)$")
_PRIMITIVE_TYPES = {
    "BIGINT",
    "BINARY",
    "BOOLEAN",
    "BYTE",
    "DATE",
    "DOUBLE",
    "FLOAT",
    "INT",
    "INTEGER",
    "LONG",
    "REAL",
    "SHORT",
    "SMALLINT",
    "STRING",
    "TIMESTAMP",
    "TIMESTAMP_NTZ",
    "TINYINT",
}
_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELED", "CLOSED"}


class DatabricksDeploymentAdapter:
    """Translate approved desired state into guarded Unity Catalog mutations."""

    key = "databricks"

    def __init__(
        self,
        *,
        client: Any,
        runtime_provider: RuntimeProvider,
        warehouse_id: str | None = None,
        poll_interval_seconds: float = 1.0,
        max_poll_attempts: int = 300,
    ) -> None:
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be non-negative")
        if max_poll_attempts < 1:
            raise ValueError("max_poll_attempts must be positive")
        self._client = client
        self._runtime_provider = runtime_provider
        self._warehouse_id = warehouse_id.strip() if warehouse_id and warehouse_id.strip() else None
        self._poll_interval_seconds = poll_interval_seconds
        self._max_poll_attempts = max_poll_attempts

    def validate(self, plan: DeploymentPlan) -> None:
        """Fail closed when a released desired state cannot be safely translated."""
        validate_deployment_plan_identity(plan)
        if plan.target.platform.casefold() != self.key:
            raise ValidationError(
                f"Databricks adapter cannot deploy platform '{plan.target.platform}'"
            )
        catalog, schema_name = parse_databricks_runtime_target(plan.target.runtime_target)
        _validate_identifier(catalog, "catalog")
        _validate_identifier(schema_name, "schema")

        physical_assets: set[str] = set()
        for action in plan.actions:
            if action.kind is not DeploymentActionKind.ENSURE_ASSET_STATE:
                raise ValidationError(
                    f"Unsupported deployment action kind: {action.kind.value}"
                )
            _validate_identifier(action.physical_name, "asset")
            asset_key = action.physical_name.casefold()
            if asset_key in physical_assets:
                raise ValidationError(
                    "Databricks deployment cannot bind multiple governed assets to "
                    f"the same physical asset '{action.physical_name}'"
                )
            physical_assets.add(asset_key)
            desired = SchemaObject.model_validate_json(action.desired_state_json)
            _desired_columns(desired)

    def preview(
        self,
        plan: DeploymentPlan,
        observed_state: ObservedPlatformState,
    ) -> DeploymentPreview:
        """Derive exact CREATE/ALTER/NO_OP operations from current runtime evidence."""
        self.validate(plan)
        _validate_observation(plan, observed_state)
        catalog, schema_name = parse_databricks_runtime_target(plan.target.runtime_target)
        observed_by_asset = {
            asset.identity.asset.casefold(): asset for asset in observed_state.assets
        }

        operations: list[NativeOperation] = []
        for action in plan.actions:
            desired = SchemaObject.model_validate_json(action.desired_state_json)
            observed = observed_by_asset.get(action.physical_name.casefold())
            if observed is None:
                statement = _create_table_statement(
                    catalog=catalog,
                    schema_name=schema_name,
                    table_name=action.physical_name,
                    desired=desired,
                )
                operations.append(
                    NativeOperation(
                        kind=NativeOperationKind.CREATE,
                        governed_asset=action.governed_asset,
                        statement=statement,
                    )
                )
                continue

            additions = _required_additions(desired, observed)
            if additions:
                statement = _add_columns_statement(
                    catalog=catalog,
                    schema_name=schema_name,
                    table_name=action.physical_name,
                    additions=additions,
                )
                operations.append(
                    NativeOperation(
                        kind=NativeOperationKind.ALTER,
                        governed_asset=action.governed_asset,
                        statement=statement,
                    )
                )
            else:
                operations.append(
                    NativeOperation(
                        kind=NativeOperationKind.NO_OP,
                        governed_asset=action.governed_asset,
                    )
                )

        ordered = tuple(operations)
        assert observed_state.fingerprint is not None
        preview_id = compute_deployment_preview_id(
            deployment_plan_id=plan.deployment_plan_id,
            platform=self.key,
            runtime_target=plan.target.runtime_target,
            source_identifier=observed_state.source_identifier,
            observation_fingerprint=observed_state.fingerprint,
            operations=ordered,
        )
        return DeploymentPreview(
            deployment_preview_id=preview_id,
            deployment_plan_id=plan.deployment_plan_id,
            platform=self.key,
            runtime_target=plan.target.runtime_target,
            source_identifier=observed_state.source_identifier,
            observation_fingerprint=observed_state.fingerprint,
            operations=ordered,
        )

    def execute(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        authorization: DeploymentAuthorization,
    ) -> None:
        """Execute only the exact preview while its runtime preconditions still hold."""
        validate_deployment_plan_identity(plan)
        validate_deployment_preview_identity(preview)
        validate_deployment_authorization_identity(authorization)
        self.validate(plan)

        if not authorization.allowed:
            raise ContractOpsAuthorizationError("DeploymentAuthorization is not allowed")
        if authorization.deployment_plan_id != plan.deployment_plan_id:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization is not bound to this DeploymentPlan"
            )
        if authorization.applied_release_id != plan.applied_release_id:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization release does not match DeploymentPlan"
            )
        if preview.deployment_plan_id != plan.deployment_plan_id:
            raise ValidationError("DeploymentPreview is not bound to this DeploymentPlan")
        if preview.platform.casefold() != self.key:
            raise ValidationError("DeploymentPreview platform does not match adapter")
        if preview.runtime_target != plan.target.runtime_target:
            raise ValidationError("DeploymentPreview target does not match DeploymentPlan")
        if preview.source_identifier != plan.target.source_reference:
            raise ValidationError(
                "DeploymentPreview runtime source does not match DeploymentPlan source reference"
            )

        current = self._observe_plan_scope(plan)
        if current.source_identifier != preview.source_identifier:
            raise ValidationError(
                "Runtime source changed since DeploymentPreview was produced"
            )
        if current.fingerprint != preview.observation_fingerprint:
            raise ValidationError(
                "Runtime state changed since DeploymentPreview was produced"
            )

        expected = self.preview(plan, current)
        if expected != preview:
            raise ValidationError(
                "DeploymentPreview no longer equals the deterministic preview for "
                "the authorized plan and runtime evidence"
            )

        for operation in preview.operations:
            if operation.kind is NativeOperationKind.NO_OP:
                continue
            assert operation.statement is not None
            self._execute_statement(operation.statement)

    def _observe_plan_scope(self, plan: DeploymentPlan) -> ObservedPlatformState:
        assets = tuple(
            RuntimeAssetSpec(
                governed_asset=action.governed_asset,
                physical_name=action.physical_name,
            )
            for action in plan.actions
        )
        bindings = self._runtime_provider.resolve_bindings(
            runtime_target=plan.target.runtime_target,
            assets=assets,
        )
        return self._runtime_provider.observe(bindings=bindings)

    def _execute_statement(self, statement: str) -> None:
        if self._warehouse_id is None:
            raise ValidationError(
                "Databricks deployment execution requires a SQL warehouse_id"
            )
        response = self._client.statement_execution.execute_statement(
            statement=statement,
            warehouse_id=self._warehouse_id,
            wait_timeout="10s",
        )
        state = _statement_state(response)
        attempts = 0
        while state not in _TERMINAL_STATES:
            statement_id = getattr(response, "statement_id", None)
            if not statement_id:
                raise RuntimeError(
                    "Databricks statement is non-terminal but returned no statement_id"
                )
            if attempts >= self._max_poll_attempts:
                raise RuntimeError(
                    f"Databricks statement did not reach terminal state: {statement_id}"
                )
            if self._poll_interval_seconds:
                time.sleep(self._poll_interval_seconds)
            response = self._client.statement_execution.get_statement(statement_id)
            state = _statement_state(response)
            attempts += 1

        if state != "SUCCEEDED":
            status = getattr(response, "status", None)
            error = getattr(status, "error", None)
            raise RuntimeError(
                f"Databricks deployment statement finished with state {state}: {error}"
            )


def _validate_observation(
    plan: DeploymentPlan,
    observed_state: ObservedPlatformState,
) -> None:
    if observed_state.platform.casefold() != "databricks":
        raise ValidationError("Databricks preview requires Databricks runtime evidence")
    if not observed_state.source_identifier.strip():
        raise ValidationError("Runtime observation source_identifier is required")
    if observed_state.source_identifier != plan.target.source_reference:
        raise ValidationError(
            "Runtime observation source does not match DeploymentPlan source reference"
        )
    if observed_state.fingerprint is None:
        raise ValidationError("Runtime observation fingerprint is required")
    if observed_state.fingerprint != fingerprint_observed_state(observed_state):
        raise ValidationError("Runtime observation fingerprint does not match its content")

    namespace = parse_databricks_runtime_target(plan.target.runtime_target)
    expected_assets = {action.physical_name.casefold() for action in plan.actions}
    seen: set[str] = set()
    for asset in observed_state.assets:
        identity = asset.identity
        if identity.platform.casefold() != "databricks":
            raise ValidationError("Observed asset platform does not match Databricks")
        if tuple(part.casefold() for part in identity.namespace) != tuple(
            part.casefold() for part in namespace
        ):
            raise ValidationError("Observed asset is outside DeploymentPlan runtime target")
        asset_key = identity.asset.casefold()
        if asset_key not in expected_assets:
            raise ValidationError("Runtime evidence contains an asset outside plan scope")
        if asset_key in seen:
            raise ValidationError("Runtime evidence contains duplicate asset identities")
        seen.add(asset_key)


def _desired_columns(
    desired: SchemaObject,
) -> tuple[tuple[str, str, bool], ...]:
    columns: list[tuple[str, str, bool]] = []
    seen: set[str] = set()
    for prop in desired.properties or []:
        physical_name = _property_physical_name(prop)
        _validate_identifier(physical_name, "column")
        key = physical_name.casefold()
        if key in seen:
            raise ValidationError(
                f"Duplicate physical column binding in desired schema: '{physical_name}'"
            )
        seen.add(key)
        physical_type = getattr(prop, "physicalType", None)
        if physical_type is None or not str(physical_type).strip():
            raise ValidationError(
                f"Databricks deployment requires physicalType for column '{physical_name}'"
            )
        rendered_type = _render_type(str(physical_type))
        columns.append((physical_name, rendered_type, bool(getattr(prop, "required", False))))
    if not columns:
        raise ValidationError("Databricks deployment requires at least one schema property")
    return tuple(columns)


def _required_additions(
    desired: SchemaObject,
    observed: ObservedAsset,
) -> tuple[tuple[str, str, bool], ...]:
    if (observed.asset_type or "").strip().casefold() != "managed":
        raise ValidationError(
            "Existing Databricks asset must be a MANAGED table for deployment mutation"
        )

    observed_columns = {
        prop.identity.property.casefold(): prop for prop in observed.properties
    }
    additions: list[tuple[str, str, bool]] = []
    for name, desired_type, required in _desired_columns(desired):
        current = observed_columns.get(name.casefold())
        if current is None:
            if required:
                raise ValidationError(
                    f"Cannot add required column '{name}' without a safe default"
                )
            additions.append((name, desired_type, required))
            continue
        if current.physical_type is None:
            raise ValidationError(f"Observed type is unknown for column '{name}'")
        current_type = _render_type(current.physical_type)
        if current_type != desired_type:
            raise ValidationError(
                f"Unsupported existing column type mutation for '{name}': "
                f"{current_type} -> {desired_type}"
            )
        if current.nullable is None:
            raise ValidationError(f"Observed nullability is unknown for column '{name}'")
        desired_nullable = not required
        if current.nullable is not desired_nullable:
            raise ValidationError(
                f"Unsupported existing column nullability mutation for '{name}'"
            )
    return tuple(additions)


def _property_physical_name(prop: SchemaProperty) -> str:
    physical = getattr(prop, "physicalName", None)
    if physical is not None and str(physical).strip():
        return str(physical).strip()
    name = getattr(prop, "name", None)
    if name is None or not str(name).strip():
        raise ValidationError("Schema property name is required for deployment binding")
    return str(name).strip()


def _create_table_statement(
    *,
    catalog: str,
    schema_name: str,
    table_name: str,
    desired: SchemaObject,
) -> str:
    columns = []
    for name, physical_type, required in _desired_columns(desired):
        suffix = " NOT NULL" if required else ""
        columns.append(f"{_quote_identifier(name)} {physical_type}{suffix}")
    column_sql = ", ".join(columns)
    return (
        f"CREATE TABLE {_qualified_name(catalog, schema_name, table_name)} "
        f"({column_sql}) USING DELTA"
    )


def _add_columns_statement(
    *,
    catalog: str,
    schema_name: str,
    table_name: str,
    additions: tuple[tuple[str, str, bool], ...],
) -> str:
    columns = ", ".join(
        f"{_quote_identifier(name)} {physical_type}"
        for name, physical_type, _required in additions
    )
    return (
        f"ALTER TABLE {_qualified_name(catalog, schema_name, table_name)} "
        f"ADD COLUMNS ({columns})"
    )


def _qualified_name(catalog: str, schema_name: str, table_name: str) -> str:
    return ".".join(
        _quote_identifier(part) for part in (catalog, schema_name, table_name)
    )


def _quote_identifier(value: str) -> str:
    _validate_identifier(value, "identifier")
    return f"`{value}`"


def _validate_identifier(value: str, role: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValidationError(
            f"Unsupported Databricks {role} identifier for M1 deployment: '{value}'"
        )


def _render_type(value: str) -> str:
    normalized = re.sub(r"\s+", "", value.strip().upper())
    if normalized in _PRIMITIVE_TYPES:
        return normalized

    decimal = _DECIMAL_RE.fullmatch(normalized)
    if decimal:
        precision = int(decimal.group(1))
        scale = int(decimal.group(2))
        if 1 <= precision <= 38 and 0 <= scale <= precision:
            return f"DECIMAL({precision},{scale})"
        raise ValidationError(f"Unsupported Databricks DECIMAL type: '{value}'")

    char_type = _CHAR_RE.fullmatch(normalized)
    if char_type:
        length = int(char_type.group(2))
        if length > 0:
            return f"{char_type.group(1)}({length})"

    raise ValidationError(f"Unsupported Databricks physicalType: '{value}'")


def _statement_state(response: Any) -> str:
    status = getattr(response, "status", None)
    state = getattr(status, "state", None)
    if state is None:
        raise RuntimeError("Databricks statement response did not contain status.state")
    value = getattr(state, "value", state)
    return str(value).upper()
