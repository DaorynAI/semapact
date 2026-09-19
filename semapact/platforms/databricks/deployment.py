"""Databricks write-side deployment adapter."""

from __future__ import annotations

import time
from typing import Any

from open_data_contract_standard.model import SchemaObject

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
from semapact.observation.models import ObservedPlatformState
from semapact.observation.providers import RuntimeProvider
from semapact.platforms.databricks.identifiers import (
    validate_databricks_identifier,
)
from semapact.platforms.databricks.schema_planner import (
    plan_databricks_schema_transition,
    validate_databricks_desired_schema,
)
from semapact.platforms.databricks.sql_compiler import (
    compile_databricks_schema_transition,
)
from semapact.platforms.databricks.target import parse_databricks_runtime_target
from semapact.runtime import RuntimeAssetSpec

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
        validate_databricks_identifier(catalog, "catalog")
        validate_databricks_identifier(schema_name, "schema")

        physical_assets: set[str] = set()
        for action in plan.actions:
            if action.kind is not DeploymentActionKind.ENSURE_ASSET_STATE:
                raise ValidationError(
                    f"Unsupported deployment action kind: {action.kind.value}"
                )
            validate_databricks_identifier(action.physical_name, "asset")
            asset_key = action.physical_name.casefold()
            if asset_key in physical_assets:
                raise ValidationError(
                    "Databricks deployment cannot bind multiple governed assets to "
                    f"the same physical asset '{action.physical_name}'"
                )
            physical_assets.add(asset_key)
            desired = SchemaObject.model_validate_json(action.desired_state_json)
            validate_databricks_desired_schema(
                table_name=action.physical_name,
                desired=desired,
            )

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
            transition = plan_databricks_schema_transition(
                runtime_target=plan.target.runtime_target,
                governed_asset=action.governed_asset,
                table_name=action.physical_name,
                desired=desired,
                observed=observed,
            )
            operations.append(
                compile_databricks_schema_transition(
                    catalog=catalog,
                    schema_name=schema_name,
                    transition=transition,
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


def _statement_state(response: Any) -> str:
    status = getattr(response, "status", None)
    state = getattr(status, "state", None)
    if state is None:
        raise RuntimeError("Databricks statement response did not contain status.state")
    value = getattr(state, "value", state)
    return str(value).upper()
