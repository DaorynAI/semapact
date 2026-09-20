"""CLI adapter for the bundle-driven deployment workflow."""

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
from semapact.deployment import DeploymentTarget
from semapact.exceptions import ValidationError
from semapact.interfaces.outcomes import (
    ProcessOutcome,
    outcome_from_gate_result,
    outcome_from_reconciliation_status,
)
from semapact.interfaces.parsing import parse_iso_timestamp


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


def run_deployment_approve(args: argparse.Namespace) -> DeploymentCommandResult:
    """Create one exact DEPLOY ApprovalRecord from a REVIEW DeploymentBundle."""
    from semapact.application.services.deployment_workflow import (
        DeploymentWorkflowService,
    )

    bundle = _load_model(args.bundle, DeploymentBundle)
    approval = DeploymentWorkflowService().approve(
        bundle,
        actor_reference=args.actor_reference,
        recorded_at=parse_iso_timestamp(args.recorded_at),
        comment=args.comment,
    )
    if args.approval_out:
        _write_model_artifact(args.approval_out, approval)

    rendered = (
        _model_json(approval)
        if args.output == "json"
        else _approval_text(approval, artifact_path=args.approval_out)
    )
    return DeploymentCommandResult(
        output=rendered,
        outcome=ProcessOutcome.SUCCESS,
    )


def run_deployment_deploy(args: argparse.Namespace) -> DeploymentCommandResult:
    """Consume one exact DeploymentBundle and run the canonical CD workflow."""
    from semapact.application.services.deployment_workflow import (
        DeploymentWorkflowService,
    )
    from semapact.platforms.runtime_registry import create_deployment_adapter

    bundle = _load_model(args.bundle, DeploymentBundle)
    approval = _resolve_deployment_approval(
        bundle,
        approval_path=args.approval,
        repository_root=args.repository_root,
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


def _resolve_deployment_approval(
    bundle: DeploymentBundle,
    *,
    approval_path: str | None,
    repository_root: str,
) -> ApprovalRecord | None:
    if approval_path is not None:
        return _load_model(approval_path, ApprovalRecord)

    from semapact.application.services.deployment_approval import (
        DeploymentApprovalResolver,
    )
    from semapact.governance import DecisionResult
    from semapact.platforms.git import GitWorkingTreeHistoryRepository

    if bundle.decision.decision is not DecisionResult.REVIEW:
        return None

    return DeploymentApprovalResolver(
        GitWorkingTreeHistoryRepository(repository_root),
    ).resolve(bundle)


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



def _approval_text(
    approval: ApprovalRecord,
    *,
    artifact_path: str | None,
) -> str:
    lines = [
        f"Approval: {approval.approval_id}",
        f"Actor: {approval.actor_reference}",
        f"Operation: {approval.operation.value}",
        f"Action: {approval.action.value}",
        f"Deployment plan: {approval.scope_reference}",
    ]
    if approval.evidence_references:
        lines.append(
            "Evidence: " + ", ".join(approval.evidence_references)
        )
    if artifact_path:
        lines.append(f"Approval artifact: {artifact_path}")
    return "\n".join(lines)
