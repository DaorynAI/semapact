"""CLI adapter for canonical deployment planning, execution, and verification."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from semapact.approval import ApprovalRecord
from semapact.application.models.deployment_workflow import DeploymentBundle
from semapact.application.services.deployment import DeploymentService
from semapact.contractops import AppliedContractRelease, ReleaseSnapshot
from semapact.deployment import (
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentPreview,
    DeploymentTarget,
)
from semapact.exceptions import ValidationError
from semapact.interfaces.outcomes import (
    ProcessOutcome,
    outcome_from_gate_result,
    outcome_from_reconciliation_status,
)
from semapact.reconciliation import classify_reconciliation_status


_ModelT = TypeVar("_ModelT", bound=BaseModel)


@dataclass(frozen=True)
class DeploymentCommandResult:
    """Rendered CLI output plus its existing semantic process outcome."""

    output: str
    outcome: ProcessOutcome


def run_deployment_assess(args: argparse.Namespace) -> DeploymentCommandResult:
    """Build one immutable CI/manual deployment bundle without runtime mutation."""
    from semapact.application.services.deployment_workflow import (
        DeploymentWorkflowService,
    )
    from semapact.core.loader import ContractLoader
    from semapact.governance import GovernanceOperation, evaluate_governance_gate
    from semapact.platforms.runtime_registry import (
        create_deployment_adapter,
        resolve_runtime_location,
    )

    loader = ContractLoader(runtime_context=args.runtime_context)
    base_contract = loader.load(args.base)
    candidate_contract = loader.load(args.candidate)
    location = resolve_runtime_location(
        candidate_contract,
        server_name=args.server,
        fallback_platform=args.platform,
        fallback_runtime_target=args.runtime,
    )
    source_reference = _assessment_source_reference(
        location.contract_server,
        args.source_reference,
    )
    target = DeploymentTarget(
        platform=location.platform,
        runtime_target=location.runtime_target,
        source_reference=source_reference,
        server_name=location.server_name,
    )
    adapter = create_deployment_adapter(
        location.platform,
        contract_server=location.contract_server,
    )
    bundle = DeploymentWorkflowService().assess(
        base_contract,
        candidate_contract,
        effective_date=args.effective_date,
        base_revision_ref=args.base_revision_ref,
        candidate_revision_ref=args.candidate_revision_ref,
        authority_reference=args.authority_reference,
        target=target,
        adapter=adapter,
    )
    if args.bundle_out:
        _write_model_artifact(args.bundle_out, bundle)

    gate = evaluate_governance_gate(
        bundle.decision,
        GovernanceOperation.PROPOSE,
    )
    rendered = (
        _model_json(bundle)
        if args.output == "json"
        else _bundle_text(bundle, artifact_path=args.bundle_out)
    )
    return DeploymentCommandResult(
        output=rendered,
        outcome=outcome_from_gate_result(gate),
    )

def run_deployment_deploy(args: argparse.Namespace) -> DeploymentCommandResult:
    """Consume one exact DeploymentBundle and run the canonical CD workflow."""
    from semapact.application.services.deployment_workflow import (
        DeploymentWorkflowService,
    )
    from semapact.platforms.runtime_registry import create_deployment_adapter

    bundle = _load_model(args.bundle, DeploymentBundle)
    approval = (
        _load_model(args.approval, ApprovalRecord)
        if args.approval is not None
        else None
    )

    execution_config = None
    if bundle.deployment_plan.target.platform == "databricks":
        from semapact.platforms.databricks.deployment import (
            DatabricksDeploymentExecutionConfig,
        )

        execution_config = DatabricksDeploymentExecutionConfig(
            warehouse_id=args.warehouse_id,
        )
    elif args.warehouse_id is not None:
        raise ValidationError(
            "--warehouse-id is only supported for Databricks deployment"
        )

    adapter = create_deployment_adapter(
        bundle.deployment_plan.target.platform,
        execution_config=execution_config,
    )
    result = DeploymentWorkflowService().deploy(
        bundle,
        adapter=adapter,
        approval=approval,
    )
    rendered = (
        _model_json(result)
        if args.output == "json"
        else _deployment_result_text(result)
    )
    return DeploymentCommandResult(
        output=rendered,
        outcome=outcome_from_reconciliation_status(result.status),
    )


def run_deployment_plan(args: argparse.Namespace) -> DeploymentCommandResult:
    """Build one provider-neutral DeploymentPlan from an exact release artifact."""
    release = _load_release_artifact(args.release)
    target = DeploymentTarget(
        platform=args.platform,
        runtime_target=args.runtime,
        source_reference=args.source_reference,
        server_name=args.server,
    )
    plan = DeploymentService().plan(release, target)
    return DeploymentCommandResult(
        output=_model_json(plan),
        outcome=ProcessOutcome.SUCCESS,
    )


def run_deployment_preview(args: argparse.Namespace) -> DeploymentCommandResult:
    """Observe exact runtime scope and render the adapter's canonical preview."""
    plan = _load_model(args.plan, DeploymentPlan)
    from semapact.platforms.runtime_registry import create_deployment_adapter

    adapter = create_deployment_adapter(plan.target.platform)
    preview = DeploymentService().preview(
        plan,
        adapter=adapter,
    )
    return DeploymentCommandResult(
        output=_model_json(preview),
        outcome=ProcessOutcome.SUCCESS,
    )


def run_deployment_execute(args: argparse.Namespace) -> DeploymentCommandResult:
    """Execute only an exact plan/preview/authorization tuple."""
    plan = _load_model(args.plan, DeploymentPlan)
    preview = _load_model(args.preview, DeploymentPreview)
    authorization = _load_model(args.authorization, DeploymentAuthorization)

    from semapact.platforms.runtime_registry import create_deployment_adapter

    execution_config = None
    if plan.target.platform == "databricks":
        from semapact.platforms.databricks.deployment import (
            DatabricksDeploymentExecutionConfig,
        )

        execution_config = DatabricksDeploymentExecutionConfig(
            warehouse_id=args.warehouse_id,
        )
    elif args.warehouse_id is not None:
        raise ValidationError(
            "--warehouse-id is only supported for Databricks deployment"
        )

    adapter = create_deployment_adapter(
        plan.target.platform,
        execution_config=execution_config,
    )
    DeploymentService().execute(
        plan,
        preview,
        authorization,
        adapter=adapter,
    )
    return DeploymentCommandResult(
        output=json.dumps(
            {
                "convergenceVerified": False,
                "deploymentPlanId": plan.deployment_plan_id,
                "deploymentPreviewId": preview.deployment_preview_id,
                "providerExecution": "SUCCEEDED",
            },
            indent=2,
            sort_keys=True,
        ),
        outcome=ProcessOutcome.SUCCESS,
    )


def run_deployment_verify(args: argparse.Namespace) -> DeploymentCommandResult:
    """Verify exact DeploymentPlan convergence through the unified deployment adapter."""
    plan = _load_model(args.plan, DeploymentPlan)
    from semapact.platforms.runtime_registry import create_deployment_adapter

    adapter = create_deployment_adapter(plan.target.platform)
    result = DeploymentService().verify(
        plan,
        adapter=adapter,
    )
    status = classify_reconciliation_status(result)
    rendered = (
        _verification_json(status.value, result)
        if args.output == "json"
        else _verification_text(status.value, result)
    )
    return DeploymentCommandResult(
        output=rendered,
        outcome=outcome_from_reconciliation_status(status),
    )


def _load_model(path: str, model_type: type[_ModelT]) -> _ModelT:
    try:
        raw = (
            sys.stdin.read()
            if path == "-"
            else Path(path).read_text(encoding="utf-8")
        )
        return model_type.model_validate_json(raw)
    except (OSError, PydanticValidationError) as exc:
        raise ValidationError(
            f"Invalid {model_type.__name__} artifact '{path}': {exc}"
        ) from exc


def _load_release_artifact(path: str) -> ReleaseSnapshot | AppliedContractRelease:
    try:
        raw = (
            sys.stdin.read()
            if path == "-"
            else Path(path).read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise ValidationError(f"Invalid release artifact '{path}': {exc}") from exc

    errors: list[str] = []
    for model_type in (ReleaseSnapshot, AppliedContractRelease):
        try:
            return model_type.model_validate_json(raw)
        except PydanticValidationError as exc:
            errors.append(f"{model_type.__name__}: {exc}")
    raise ValidationError(
        f"Invalid release artifact '{path}': " + " | ".join(errors)
    )


def _write_model_artifact(path: str, model: BaseModel) -> None:
    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(_model_json(model) + "\n", encoding="utf-8")


def _model_json(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


def _verification_json(status: str, result: BaseModel) -> str:
    return json.dumps(
        {
            "reconciliation": result.model_dump(mode="json"),
            "status": status,
        },
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


def _verification_text(status: str, result: BaseModel) -> str:
    differences = getattr(result, "differences")
    unverified_paths = getattr(result, "unverified_paths")
    lines = [
        f"Status: {status}",
        (
            f"Contract: {getattr(result, 'contract_id')}@"
            f"{getattr(result, 'contract_version')}"
        ),
        f"Observation source: {getattr(result, 'observation_source_identifier')}",
        f"Observation fingerprint: {getattr(result, 'observation_fingerprint')}",
    ]
    if differences:
        lines.append("Differences:")
        for difference in differences:
            detail = f"  - {difference.reason_code.value} {difference.path}"
            if difference.expected is not None or difference.observed is not None:
                detail += (
                    f" expected={difference.expected!r}"
                    f" observed={difference.observed!r}"
                )
            lines.append(detail)
    else:
        lines.append("Differences: none")

    if unverified_paths:
        lines.append("Unverified paths:")
        lines.extend(f"  - {path}" for path in unverified_paths)
    else:
        lines.append("Unverified paths: none")
    return "\n".join(lines)



def _assessment_source_reference(contract_server, cli_source_reference: str | None) -> str:
    cli_value = (cli_source_reference or "").strip()
    if contract_server is None:
        if not cli_value:
            raise ValidationError(
                "Contract defines no server host; provide --source-reference"
            )
        return cli_value

    host = str(getattr(contract_server, "host", "") or "").strip()
    if not host:
        raise ValidationError(
            "Selected contract server must define host for deployment assessment"
        )
    if cli_value and cli_value != host:
        raise ValidationError(
            "--source-reference cannot override the selected contract server host"
        )
    return host


def _bundle_text(
    bundle: DeploymentBundle,
    *,
    artifact_path: str | None,
) -> str:
    plan = bundle.deployment_plan
    preview = bundle.review_preview
    lines = [
        f"Contract: {bundle.release_snapshot.contract_id}@"
        f"{bundle.release_snapshot.selected_version}",
        f"Governance: {bundle.decision.decision.value}",
        f"Required bump: {bundle.decision.required_version_bump}",
        f"Target: {plan.target.platform}/{plan.target.runtime_target}",
        f"Deployment plan: {plan.deployment_plan_id}",
        f"Bundle digest: {bundle.bundle_digest}",
        "Execution authority: none (CI/read-only bundle)",
        "Review operations:",
    ]
    for operation in preview.operations:
        detail = f"  - {operation.kind.value} {operation.governed_asset}"
        if operation.statement is not None:
            detail += f": {operation.statement}"
        lines.append(detail)
    if not preview.operations:
        lines.append("  - none")
    lines.extend(
        [
            f"Observation source: {preview.source_identifier}",
            f"Observation fingerprint: {preview.observation_fingerprint}",
        ]
    )
    if artifact_path:
        lines.append(f"Bundle artifact: {artifact_path}")
    return "\n".join(lines)



def _deployment_result_text(result) -> str:
    lines = [
        f"Bundle digest: {result.bundle_digest}",
        f"Deployment plan: {result.deployment_plan_id}",
        f"Authorization: {result.authorization_id}",
        "Provider execution: SUCCEEDED",
        f"Verification: {result.status.value}",
        (
            "CI review preview changed: "
            f"{'yes' if result.review_preview_changed else 'no'}"
        ),
        "Fresh operations:",
    ]
    for operation in result.fresh_preview.operations:
        detail = f"  - {operation.kind.value} {operation.governed_asset}"
        if operation.statement is not None:
            detail += f": {operation.statement}"
        lines.append(detail)
    if not result.fresh_preview.operations:
        lines.append("  - none")
    return "\n".join(lines)
