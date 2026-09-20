"""Generic deployment orchestration over explicit provider behavior seams."""

from __future__ import annotations

from open_data_contract_standard.model import SchemaObject

from semapact.deployment.adapters import DeploymentAdapter
from semapact.deployment.compilers import TransitionCompiler
from semapact.deployment.models import (
    DeploymentAction,
    DeploymentActionKind,
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentTarget,
    NativeOperation,
    NativeOperationKind,
    compute_deployment_preview_id,
    validate_deployment_authorization_identity,
    validate_deployment_plan_identity,
    validate_deployment_preview_identity,
)
from semapact.deployment.providers import NativeOperationExecutor
from semapact.deployment.schema_transitions import SchemaTransitionPlanner
from semapact.deployment.verification import verify_deployment_convergence
from semapact.exceptions import ContractOpsAuthorizationError, ValidationError
from semapact.observation.fingerprint import fingerprint_observed_state
from semapact.observation.models import ObservedAssetIdentity, ObservedPlatformState
from semapact.observation.providers import RuntimeAssetBinding, RuntimeProvider
from semapact.reconciliation import ReconciliationResult
from semapact.runtime import RuntimeAssetSpec
from semapact.schema import (
    SchemaAssetState,
    SchemaMapper,
    SchemaSnapshot,
    compare_schema_snapshots,
)


class DeploymentOrchestrator(DeploymentAdapter):
    """Provider-neutral deployment lifecycle over explicit behavior dependencies."""

    def __init__(
        self,
        *,
        runtime_provider: RuntimeProvider,
        schema_mapper: SchemaMapper,
        transition_planner: SchemaTransitionPlanner,
        transition_compiler: TransitionCompiler,
        executor: NativeOperationExecutor,
    ) -> None:
        provider_key = runtime_provider.key.strip().casefold()
        if not provider_key:
            raise ValueError("Runtime provider key is required")
        if transition_compiler.key.strip().casefold() != provider_key:
            raise ValueError(
                "Runtime provider and transition compiler keys must match"
            )
        if executor.key.strip().casefold() != provider_key:
            raise ValueError(
                "Runtime provider and native operation executor keys must match"
            )

        self._runtime_provider = runtime_provider
        self._schema_mapper = schema_mapper
        self._transition_planner = transition_planner
        self._transition_compiler = transition_compiler
        self._executor = executor

    @property
    def key(self) -> str:
        return self._runtime_provider.key

    def validate(self, plan: DeploymentPlan) -> None:
        """Validate one exact plan without runtime observation side effects."""
        self._validate_and_map_plan(plan)

    def preview(self, plan: DeploymentPlan) -> DeploymentPreview:
        """Validate, observe, compare, plan, and compile one deterministic preview."""
        desired_by_action = self._validate_and_map_plan(plan)
        observed_state, bindings = self._observe_plan_scope(plan)
        return self._preview_from_observation(
            plan,
            observed_state,
            bindings=bindings,
            desired_by_action=desired_by_action,
        )

    def verify(self, plan: DeploymentPlan) -> ReconciliationResult:
        """Verify convergence using the same runtime provider and schema mapping."""
        return verify_deployment_convergence(
            plan,
            self._runtime_provider,
            schema_mapper=self._schema_mapper,
        )

    def execute(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        authorization: DeploymentAuthorization,
    ) -> None:
        """Execute only the exact authorized preview against unchanged runtime state."""
        validate_deployment_preview_identity(preview)
        validate_deployment_authorization_identity(authorization)
        desired_by_action = self._validate_and_map_plan(plan)

        if not authorization.allowed:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization is not allowed"
            )
        if authorization.deployment_plan_id != plan.deployment_plan_id:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization is not bound to this DeploymentPlan"
            )
        if authorization.source_snapshot_id != plan.source_snapshot_id:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization source does not match DeploymentPlan"
            )
        if preview.deployment_plan_id != plan.deployment_plan_id:
            raise ValidationError(
                "DeploymentPreview is not bound to this DeploymentPlan"
            )
        if preview.platform.casefold() != self.key.casefold():
            raise ValidationError(
                "DeploymentPreview platform does not match runtime provider"
            )
        if preview.runtime_target != plan.target.runtime_target:
            raise ValidationError(
                "DeploymentPreview target does not match DeploymentPlan"
            )
        if preview.source_identifier != plan.target.source_reference:
            raise ValidationError(
                "DeploymentPreview runtime source does not match DeploymentPlan "
                "source reference"
            )

        current, bindings = self._observe_plan_scope(plan)
        if current.source_identifier != preview.source_identifier:
            raise ValidationError(
                "Runtime source changed since DeploymentPreview was produced"
            )
        if current.fingerprint != preview.observation_fingerprint:
            raise ValidationError(
                "Runtime state changed since DeploymentPreview was produced"
            )

        expected = self._preview_from_observation(
            plan,
            current,
            bindings=bindings,
            desired_by_action=desired_by_action,
        )
        if expected != preview:
            raise ValidationError(
                "DeploymentPreview no longer equals the deterministic preview for "
                "the authorized plan and runtime evidence"
            )

        for operation in preview.operations:
            if operation.kind is NativeOperationKind.NO_OP:
                continue
            self._executor.execute(operation)

    def _preview_from_observation(
        self,
        plan: DeploymentPlan,
        observed_state: ObservedPlatformState,
        *,
        bindings: tuple[RuntimeAssetBinding, ...],
        desired_by_action: dict[str, SchemaAssetState] | None = None,
    ) -> DeploymentPreview:
        if desired_by_action is None:
            desired_by_action = self._validate_and_map_plan(plan)
        operations = self._operations_for_scope(
            plan.target,
            plan.actions,
            observed_state,
            bindings=bindings,
            desired_by_action=desired_by_action,
        )

        if observed_state.fingerprint is None:
            raise ValidationError("Runtime observation fingerprint is required")
        return DeploymentPreview(
            deployment_preview_id=compute_deployment_preview_id(
                deployment_plan_id=plan.deployment_plan_id,
                platform=self.key,
                runtime_target=plan.target.runtime_target,
                source_identifier=observed_state.source_identifier,
                observation_fingerprint=observed_state.fingerprint,
                operations=operations,
            ),
            deployment_plan_id=plan.deployment_plan_id,
            platform=self.key,
            runtime_target=plan.target.runtime_target,
            source_identifier=observed_state.source_identifier,
            observation_fingerprint=observed_state.fingerprint,
            operations=operations,
        )

    def _operations_for_scope(
        self,
        target: DeploymentTarget,
        actions: tuple[DeploymentAction, ...],
        observed_state: ObservedPlatformState,
        *,
        bindings: tuple[RuntimeAssetBinding, ...],
        desired_by_action: dict[str, SchemaAssetState],
    ) -> tuple[NativeOperation, ...]:
        self._validate_observation_for_scope(
            target,
            observed_state,
            bindings=bindings,
        )
        observed_by_asset = {
            asset.identity.asset.casefold(): asset
            for asset in observed_state.assets
        }

        operations: list[NativeOperation] = []
        for action in actions:
            desired_asset = desired_by_action[action.governed_asset]
            observed = observed_by_asset.get(action.physical_name.casefold())
            observed_assets = (
                ()
                if observed is None
                else (
                    self._schema_mapper.map_observed_asset(
                        observed,
                        asset_identity=action.physical_name,
                    ),
                )
            )
            comparison = compare_schema_snapshots(
                SchemaSnapshot(assets=(desired_asset,)),
                SchemaSnapshot(assets=observed_assets),
            )
            transition = self._transition_planner.plan(
                governed_asset=action.governed_asset,
                physical_name=action.physical_name,
                desired_columns=desired_asset.properties,
                comparison=comparison,
                observed_asset=observed,
            )
            operations.append(
                self._transition_compiler.compile(
                    runtime_target=target.runtime_target,
                    transition=transition,
                )
            )
        return tuple(operations)

    def _validate_and_map_plan(
        self,
        plan: DeploymentPlan,
    ) -> dict[str, SchemaAssetState]:
        validate_deployment_plan_identity(plan)
        return self._validate_and_map_actions(plan.target, plan.actions)

    def _validate_and_map_actions(
        self,
        target: DeploymentTarget,
        actions: tuple[DeploymentAction, ...],
    ) -> dict[str, SchemaAssetState]:
        if target.platform.casefold() != self.key.casefold():
            raise ValidationError(
                f"Runtime provider '{self.key}' cannot deploy '{target.platform}'"
            )

        physical_assets: set[str] = set()
        desired_by_action: dict[str, SchemaAssetState] = {}
        for action in actions:
            if action.kind is not DeploymentActionKind.ENSURE_ASSET_STATE:
                raise ValidationError(
                    f"Unsupported deployment action kind: {action.kind.value}"
                )

            physical_key = action.physical_name.casefold()
            if physical_key in physical_assets:
                raise ValidationError(
                    "Deployment cannot bind multiple governed assets to the same "
                    f"physical asset '{action.physical_name}'"
                )
            physical_assets.add(physical_key)

            desired = SchemaObject.model_validate_json(action.desired_state_json)
            mapped = self._schema_mapper.map_desired_asset(
                desired,
                asset_identity=action.physical_name,
            )
            if mapped.identity.casefold() != physical_key:
                raise ValidationError(
                    "Mapped desired asset identity does not match physical target"
                )
            desired_by_action[action.governed_asset] = mapped

        self._resolve_bindings(target, actions)
        return desired_by_action

    def _resolve_plan_bindings(
        self,
        plan: DeploymentPlan,
    ) -> tuple[RuntimeAssetBinding, ...]:
        return self._resolve_bindings(plan.target, plan.actions)

    def _resolve_bindings(
        self,
        target: DeploymentTarget,
        actions: tuple[DeploymentAction, ...],
    ) -> tuple[RuntimeAssetBinding, ...]:
        assets = tuple(
            RuntimeAssetSpec(
                governed_asset=action.governed_asset,
                physical_name=action.physical_name,
            )
            for action in actions
        )
        bindings = self._runtime_provider.resolve_bindings(
            runtime_target=target.runtime_target,
            assets=assets,
        )

        expected = {
            action.governed_asset: action.physical_name.casefold()
            for action in actions
        }
        if len(bindings) != len(expected):
            raise ValidationError(
                "Runtime provider did not resolve exactly one binding per deployment action"
            )

        seen_governed: set[str] = set()
        seen_observed: set[tuple[str, tuple[str, ...], str]] = set()
        for binding in bindings:
            if binding.governed_asset not in expected:
                raise ValidationError(
                    "Runtime provider returned a binding outside DeploymentPlan scope"
                )
            if binding.governed_asset in seen_governed:
                raise ValidationError(
                    "Runtime provider returned duplicate governed asset bindings"
                )
            seen_governed.add(binding.governed_asset)

            identity = binding.observed_asset
            if identity.platform.casefold() != self.key.casefold():
                raise ValidationError(
                    "Runtime binding platform does not match runtime provider"
                )
            if identity.asset.casefold() != expected[binding.governed_asset]:
                raise ValidationError(
                    "Runtime binding asset does not match DeploymentPlan physical asset"
                )

            identity_key = _identity_key(identity)
            if identity_key in seen_observed:
                raise ValidationError(
                    "Runtime provider returned duplicate observed asset bindings"
                )
            seen_observed.add(identity_key)

        return bindings

    def _validate_observation(
        self,
        plan: DeploymentPlan,
        observed_state: ObservedPlatformState,
        *,
        bindings: tuple[RuntimeAssetBinding, ...],
    ) -> None:
        self._validate_observation_for_scope(
            plan.target,
            observed_state,
            bindings=bindings,
        )

    def _validate_observation_for_scope(
        self,
        target: DeploymentTarget,
        observed_state: ObservedPlatformState,
        *,
        bindings: tuple[RuntimeAssetBinding, ...],
    ) -> None:
        if observed_state.platform.casefold() != self.key.casefold():
            raise ValidationError(
                "Runtime observation platform does not match runtime provider"
            )
        if not observed_state.source_identifier.strip():
            raise ValidationError(
                "Runtime observation source_identifier is required"
            )
        if observed_state.source_identifier != target.source_reference:
            raise ValidationError(
                "Runtime observation source does not match deployment target "
                "source reference"
            )
        if observed_state.fingerprint is None:
            raise ValidationError("Runtime observation fingerprint is required")
        if observed_state.fingerprint != fingerprint_observed_state(observed_state):
            raise ValidationError(
                "Runtime observation fingerprint does not match its content"
            )

        expected_identities = {
            _identity_key(binding.observed_asset)
            for binding in bindings
        }
        seen: set[tuple[str, tuple[str, ...], str]] = set()
        for asset in observed_state.assets:
            identity_key = _identity_key(asset.identity)
            if identity_key not in expected_identities:
                raise ValidationError(
                    "Runtime evidence contains an asset outside resolved plan scope"
                )
            if identity_key in seen:
                raise ValidationError(
                    "Runtime evidence contains duplicate asset identities"
                )
            seen.add(identity_key)

    def _observe_plan_scope(
        self,
        plan: DeploymentPlan,
    ) -> tuple[ObservedPlatformState, tuple[RuntimeAssetBinding, ...]]:
        return self._observe_scope(plan.target, plan.actions)

    def _observe_scope(
        self,
        target: DeploymentTarget,
        actions: tuple[DeploymentAction, ...],
    ) -> tuple[ObservedPlatformState, tuple[RuntimeAssetBinding, ...]]:
        bindings = self._resolve_bindings(target, actions)
        return (
            self._runtime_provider.observe(bindings=bindings),
            bindings,
        )


def _identity_key(
    identity: ObservedAssetIdentity,
) -> tuple[str, tuple[str, ...], str]:
    return (
        identity.platform.casefold(),
        tuple(part.casefold() for part in identity.namespace),
        identity.asset.casefold(),
    )
