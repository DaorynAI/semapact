"""CLI adapter for target-specific deployment workflows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from semapact.application.models.deployment_workflow import DeploymentBundle
from semapact.deployment import DeploymentTarget
from semapact.exceptions import ValidationError
from semapact.interfaces.outcomes import (
    ProcessOutcome,
    outcome_from_gate_result,
    outcome_from_reconciliation_status,
)


_ModelT = TypeVar("_ModelT", bound=BaseModel)


@dataclass(frozen=True)
class DeploymentCommandResult:
    """Rendered CLI output plus its semantic process outcome."""

    output: str
    outcome: ProcessOutcome


def run_deployment_assess(args: argparse.Namespace) -> DeploymentCommandResult:
    """Build one target-specific candidate or finalized-release deployment bundle."""
    from open_data_contract_standard.model import OpenDataContractStandard

    from semapact.application.services.deployment_workflow import (
        DeploymentWorkflowService,
    )
    from semapact.core.loader import ContractLoader
    from semapact.contractops import ContractRelease
    from semapact.governance import GovernanceOperation, evaluate_governance_gate
    from semapact.platforms.git import GitWorkingTreeHistoryRepository
    from semapact.platforms.runtime_registry import (
        create_deployment_adapter,
        resolve_runtime_location,
    )

    service = DeploymentWorkflowService()
    loader = ContractLoader(runtime_context=args.runtime_context)

    if args.release or args.release_id:
        _reject_candidate_args_for_release(args)
        release = (
            _load_model(args.release, ContractRelease)
            if args.release
            else GitWorkingTreeHistoryRepository(
                args.repository_root
            ).get_contract_release(args.release_id)
        )
        source_contract = OpenDataContractStandard.model_validate_json(
            release.released_contract_json
        )
        location = resolve_runtime_location(
            source_contract,
            server_name=args.server,
            fallback_platform=args.platform,
            fallback_runtime_target=args.runtime,
        )
        target = _deployment_target(
            location,
            source_reference=_assessment_source_reference(
                location.contract_server,
                args.source_reference,
            ),
        )
        adapter = create_deployment_adapter(
            location.platform,
            contract_server=location.contract_server,
        )
        bundle = service.assess_release(
            release,
            target=target,
            adapter=adapter,
        )
        outcome = ProcessOutcome.SUCCESS
    else:
        _require_candidate_args(args)
        base_contract = loader.load(args.base)
        candidate_contract = loader.load(args.candidate)
        location = resolve_runtime_location(
            candidate_contract,
            server_name=args.server,
            fallback_platform=args.platform,
            fallback_runtime_target=args.runtime,
        )
        target = _deployment_target(
            location,
            source_reference=_assessment_source_reference(
                location.contract_server,
                args.source_reference,
            ),
        )
        adapter = create_deployment_adapter(
            location.platform,
            contract_server=location.contract_server,
        )
        bundle = service.assess(
            base_contract,
            candidate_contract,
            effective_date=args.effective_date,
            base_revision_ref=args.base_revision_ref,
            candidate_revision_ref=args.candidate_revision_ref,
            target=target,
            adapter=adapter,
        )
        assert bundle.decision is not None
        gate = evaluate_governance_gate(
            bundle.decision,
            GovernanceOperation.PROPOSE,
        )
        outcome = outcome_from_gate_result(gate)

    if args.bundle_out:
        _write_model_artifact(args.bundle_out, bundle)

    rendered = (
        _model_json(bundle)
        if args.output == "json"
        else _bundle_text(bundle, artifact_path=args.bundle_out)
    )
    return DeploymentCommandResult(output=rendered, outcome=outcome)


def run_deployment_deploy(args: argparse.Namespace) -> DeploymentCommandResult:
    """Consume one exact DeploymentBundle and run the canonical CD workflow."""
    from semapact.application.services.deployment_workflow import (
        DeploymentWorkflowService,
    )
    from semapact.platforms.runtime_registry import create_deployment_adapter

    bundle = _load_model(args.bundle, DeploymentBundle)

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

    from semapact.history import create_operational_history_sink

    operational_history = create_operational_history_sink(
        _resolve_operational_history_uri(args.operational_history)
    )
    result = DeploymentWorkflowService().deploy(
        bundle,
        adapter=adapter,
        operational_history=operational_history,
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


def _require_candidate_args(args: argparse.Namespace) -> None:
    required = {
        "--base": args.base,
        "--candidate": args.candidate,
        "--base-revision-ref": args.base_revision_ref,
        "--candidate-revision-ref": args.candidate_revision_ref,
        "--effective-date": args.effective_date,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValidationError(
            "Candidate deployment assessment requires " + ", ".join(missing)
        )


def _reject_candidate_args_for_release(args: argparse.Namespace) -> None:
    supplied = [
        name
        for name, value in (
            ("--base", args.base),
            ("--candidate", args.candidate),
            ("--base-revision-ref", args.base_revision_ref),
            ("--candidate-revision-ref", args.candidate_revision_ref),
            ("--effective-date", args.effective_date),
        )
        if value
    ]
    if supplied:
        raise ValidationError(
            "Release deployment cannot be combined with candidate assessment arguments: "
            + ", ".join(supplied)
        )


def _deployment_target(location, *, source_reference: str) -> DeploymentTarget:
    return DeploymentTarget(
        platform=location.platform,
        runtime_target=location.runtime_target,
        source_reference=source_reference,
        server_name=location.server_name,
    )


def _resolve_operational_history_uri(cli_override: str | None) -> str | None:
    """Resolve CLI override first, then typed project/global configuration."""
    if cli_override is not None and cli_override.strip():
        return cli_override.strip()

    from pydantic import ValidationError as PydanticConfigValidationError

    from semapact.core.config import config_manager
    from semapact.core.config_schema import operational_history_uri_from_config

    raw_config = config_manager.get("history.operational", default=None)
    try:
        return operational_history_uri_from_config(raw_config)
    except PydanticConfigValidationError as exc:
        raise ValidationError(
            f"Invalid history.operational configuration: {exc}"
        ) from exc


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
        f"Contract: {bundle.deployment_source.contract_id}@"
        f"{bundle.deployment_source.contract_version}",
        f"Mode: {'release' if bundle.release else 'candidate'}",
        f"Target: {plan.target.platform}/{plan.target.runtime_target}",
        f"Deployment plan: {plan.deployment_plan_id}",
        f"Bundle digest: {bundle.bundle_digest}",
        "Execution authority: none (CI/read-only bundle)",
    ]
    if bundle.release:
        assert bundle.contract_release is not None
        lines.append(
            f"Contract release: {bundle.contract_release.contract_release_id}"
        )
    else:
        assert bundle.decision is not None
        lines.append(f"Governance: {bundle.decision.decision.value}")
    lines.append("Review operations:")
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
        *(
            [f"Contract release: {result.contract_release_id}"]
            if result.contract_release_id is not None
            else []
        ),
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
