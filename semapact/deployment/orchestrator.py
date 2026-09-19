"""Generic deployment orchestration over provider contracts."""

from __future__ import annotations

from open_data_contract_standard.model import SchemaObject

from semapact.deployment.adapters import DeploymentAdapter
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
from semapact.deployment.providers import DeploymentPlatform, NativeOperationExecutor
from semapact.deployment.schema_transitions import plan_additive_schema_transition
from semapact.deployment.verification import verify_deployment_convergence
from semapact.exceptions import ContractOpsAuthorizationError, ValidationError
from semapact.observation.fingerprint import fingerprint_observed_state
from semapact.observation.models import ObservedPlatformState
from semapact.runtime import RuntimeAssetSpec
from semapact.schema import (
    SchemaAssetState,
    SchemaSnapshot,
    compare_schema_snapshots,
)


class DeploymentOrchestrator(DeploymentAdapter):
    """Provider-neutral deployment lifecycle.

    Flow:
        validate plan
        → validate observation
        → map desired/observed state
        → compare
        → derive transition
        → compile provider-native operation
        → bind deterministic preview
        → re-observe/freshness check
        → execute exact authorized operation
    """

    def __init__(
        self,
        *,
        platform: DeploymentPlatform,
        executor: NativeOperationExecutor,
    ) -> None:
        if platform.key.casefold() != executor.key.casefold():
            raise ValueError(
                "Deployment platform and native operation executor keys must match"
            )
        if platform.key.casefold() != platform.runtime_provider.key.casefold():
            raise ValueError(
                "Deployment platform and runtime provider keys must match"
            )
        self._platform = platform
        self._executor = executor

    @property
    def key(self) -> str:
        return self._platform.key

    def validate(self, plan: DeploymentPlan) -> None:
        """Validate one plan and all mapped desired assets fail-closed."""
        self._validate_and_map_plan(plan)

    def preview(self, plan: DeploymentPlan) -> DeploymentPreview:
        """Validate, observe runtime, and derive exact provider-native operations."""
        desired_by_action = self._validate_and_map_plan(plan)
        observed_state = self._observe_plan_scope(plan)
        return self._preview_from_observation(
            plan,
            observed_state,
            desired_by_action=desired_by_action,
        )

    def _preview_from_observation(
        self,
        plan: DeploymentPlan,
        observed_state: ObservedPlatformState,
        *,
        desired_by_action: dict[str, SchemaAssetState] | None = None,
    ) -> DeploymentPreview:
        if desired_by_action is None:
            desired_by_action = self._validate_and_map_plan(plan)
        self._validate_observation(plan, observed_state)

        observed_by_asset = {
            asset.identity.asset.casefold(): asset
            for asset in observed_state.assets
        }

        operations: list[NativeOperation] = []
        for action in plan.actions:
            desired_asset = desired_by_action[action.governed_asset]
            observed = observed_by_asset.get(action.physical_name.casefold())

            observed_assets = ()
            if observed is not None:
                self._platform.validate_observed_asset(
                    target=plan.target,
                    physical_name=action.physical_name,
                    observed=observed,
                )
                observed_assets = (
                    self._platform.schema_mapper.map_observed_asset(
                        observed,
                        asset_identity=action.physical_name,
                    ),
                )

            comparison = compare_schema_snapshots(
                SchemaSnapshot(assets=(desired_asset,)),
                SchemaSnapshot(assets=observed_assets),
            )
            transition = plan_additive_schema_transition(
                governed_asset=action.governed_asset,
                physical_name=action.physical_name,
                desired_columns=desired_asset.properties,
                comparison=comparison,
            )
            operations.append(
                self._platform.transition_compiler.compile(
                    runtime_target=plan.target.runtime_target,
                    transition=transition,
                )
            )

        ordered = tuple(operations)
        if observed_state.fingerprint is None:
            raise ValidationError("Runtime observation fingerprint is required")

        return DeploymentPreview(
            deployment_preview_id=compute_deployment_preview_id(
                deployment_plan_id=plan.deployment_plan_id,
                platform=self.key,
                runtime_target=plan.target.runtime_target,
                source_identifier=observed_state.source_identifier,
                observation_fingerprint=observed_state.fingerprint,
                operations=ordered,
            ),
            deployment_plan_id=plan.deployment_plan_id,
            platform=self.key,
            runtime_target=plan.target.runtime_target,
            source_identifier=observed_state.source_identifier,
            observation_fingerprint=observed_state.fingerprint,
            operations=ordered,
        )

    def verify(self, plan: DeploymentPlan):
        """Verify convergence through the same configured runtime provider."""
        self.validate(plan)
        return verify_deployment_convergence(
            plan,
            self._platform.runtime_provider,
        )

    def execute(
        self,
        plan: DeploymentPlan,
        preview: DeploymentPreview,
        authorization: DeploymentAuthorization,
    ) -> None:
        """Execute only the exact authorized preview against unchanged runtime state."""
        validate_deployment_plan_identity(plan)
        validate_deployment_preview_identity(preview)
        validate_deployment_authorization_identity(authorization)
        self.validate(plan)

        if not authorization.allowed:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization is not allowed"
            )
        if authorization.deployment_plan_id != plan.deployment_plan_id:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization is not bound to this DeploymentPlan"
            )
        if authorization.applied_release_id != plan.applied_release_id:
            raise ContractOpsAuthorizationError(
                "DeploymentAuthorization release does not match DeploymentPlan"
            )
        if preview.deployment_plan_id != plan.deployment_plan_id:
            raise ValidationError(
                "DeploymentPreview is not bound to this DeploymentPlan"
            )
        if preview.platform.casefold() != self.key.casefold():
            raise ValidationError(
                "DeploymentPreview platform does not match deployment platform"
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

        current = self._observe_plan_scope(plan)
        if current.source_identifier != preview.source_identifier:
            raise ValidationError(
                "Runtime source changed since DeploymentPreview was produced"
            )
        if current.fingerprint != preview.observation_fingerprint:
            raise ValidationError(
                "Runtime state changed since DeploymentPreview was produced"
            )

        expected = self._preview_from_observation(plan, current)
        if expected != preview:
            raise ValidationError(
                "DeploymentPreview no longer equals the deterministic preview for "
                "the authorized plan and runtime evidence"
            )

        for operation in preview.operations:
            if operation.kind is NativeOperationKind.NO_OP:
                continue
            self._executor.execute(operation)

    def _validate_and_map_plan(
        self,
        plan: DeploymentPlan,
    ) -> dict[str, SchemaAssetState]:
        validate_deployment_plan_identity(plan)
        if plan.target.platform.casefold() != self.key.casefold():
            raise ValidationError(
                f"Deployment platform '{self.key}' cannot deploy "
                f"'{plan.target.platform}'"
            )

        self._platform.validate_target(plan.target)

        physical_assets: set[str] = set()
        desired_by_action: dict[str, SchemaAssetState] = {}

        for action in plan.actions:
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
            mapped = self._platform.schema_mapper.map_desired_asset(
                desired,
                asset_identity=action.physical_name,
            )
            self._platform.validate_desired_asset(
                target=plan.target,
                physical_name=action.physical_name,
                desired=desired,
                mapped=mapped,
            )
            desired_by_action[action.governed_asset] = mapped

        return desired_by_action

    def _validate_observation(
        self,
        plan: DeploymentPlan,
        observed_state: ObservedPlatformState,
    ) -> None:
        if observed_state.platform.casefold() != self.key.casefold():
            raise ValidationError(
                "Runtime observation platform does not match deployment platform"
            )
        if not observed_state.source_identifier.strip():
            raise ValidationError(
                "Runtime observation source_identifier is required"
            )
        if observed_state.source_identifier != plan.target.source_reference:
            raise ValidationError(
                "Runtime observation source does not match DeploymentPlan "
                "source reference"
            )
        if observed_state.fingerprint is None:
            raise ValidationError("Runtime observation fingerprint is required")
        if observed_state.fingerprint != fingerprint_observed_state(observed_state):
            raise ValidationError(
                "Runtime observation fingerprint does not match its content"
            )

        expected_assets = {
            action.physical_name.casefold()
            for action in plan.actions
        }
        seen: set[str] = set()
        for asset in observed_state.assets:
            asset_key = asset.identity.asset.casefold()
            if asset_key not in expected_assets:
                raise ValidationError(
                    "Runtime evidence contains an asset outside plan scope"
                )
            if asset_key in seen:
                raise ValidationError(
                    "Runtime evidence contains duplicate asset identities"
                )
            seen.add(asset_key)

    def _observe_plan_scope(
        self,
        plan: DeploymentPlan,
    ) -> ObservedPlatformState:
        assets = tuple(
            RuntimeAssetSpec(
                governed_asset=action.governed_asset,
                physical_name=action.physical_name,
            )
            for action in plan.actions
        )
        bindings = self._platform.runtime_provider.resolve_bindings(
            runtime_target=plan.target.runtime_target,
            assets=assets,
        )
        return self._platform.runtime_provider.observe(bindings=bindings)
