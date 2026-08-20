"""SemaPact orchestration pipeline for import, merge, validation, and export.

This module is not the interactive draft-editing workflow used by the UI.
Instead, it is the automation layer for batch and CI/CD scenarios where we:

1. import or generate a technical contract from a source system
2. load an existing lifecycle-governed contract from storage/Git
3. merge technical updates into the governed contract
4. validate the merged result
5. evaluate lifecycle policy
6. export downstream artifacts such as GE suites and CI manifests

Think of this module as the non-interactive "pipeline runner" for SemaPact.
It is useful for engineering automation, scheduled imports, and GitOps flows.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from open_data_contract_standard.model import OpenDataContractStandard

from datacontract.data_contract import DataContract

from semapact.governance import (
    ChangeContext,
    GovernanceDecision,
    GovernanceOperation,
    enforce_governance_gate,
    evaluate_governance_decision,
    governance_decision_to_dict,
)
from semapact.importers.unity_importer import import_unity_contract
from semapact.core.loader import ContractLoader, RuntimeContext
from semapact.core.validator import ContractValidator, ValidationReport
from semapact.devops.audit import AuditMetadata
from semapact.lifecycle.merge_engine import ContractMergeEngine, MergeConflict, MergeResult
from semapact.lifecycle.policy import PolicyEvaluation, evaluate_merge_policy
from semapact.quality.ge_exporter import GreatExpectationsExporter
from semapact.utils.schema_utils import contract_to_dict
from semapact.utils.yaml_utils import dump_yaml

ImportSourceType = str


def _build_manifest_payload(
    decision: GovernanceDecision,
    *,
    merge_conflicts: Sequence[MergeConflict] = (),
    artifacts: dict[str, str] | None = None,
    audit_metadata: AuditMetadata | None = None,
) -> dict[str, Any]:
    """Build the canonical CI/CD manifest payload dict from a GovernanceDecision.

    Both write_decision_manifest and prepare_ci_cd_artifacts call this to ensure
    a single source of truth for manifest field names and serialization.
    """
    return {
        "governanceDecision": governance_decision_to_dict(decision),
        "valid": decision.validation.valid,
        "policyValid": decision.policy.valid,
        "idViolation": decision.policy.id_violation,
        "versionViolation": decision.policy.version_violation,
        "issues": [issue.model_dump(mode="json") for issue in decision.validation.issues],
        "breakingChanges": [
            v.model_dump(mode="json")
            for v in decision.policy.violations
            if v.code == "POLICY_BREAKING_CHANGE"
        ],
        "conflicts": [asdict(conflict) for conflict in merge_conflicts],
        "artifacts": artifacts or {},
        "audit": asdict(audit_metadata) if audit_metadata is not None else None,
    }


def write_decision_manifest(
    decision: GovernanceDecision,
    ci_manifest_path: str | Path,
    audit_metadata: AuditMetadata | None = None,
    merge_conflicts: Sequence[MergeConflict] = (),
) -> Path:
    """Write decision-only manifest without requiring external artifact creation."""
    resolved_path = Path(ci_manifest_path).expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = _build_manifest_payload(
        decision,
        merge_conflicts=merge_conflicts,
        audit_metadata=audit_metadata,
    )
    resolved_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return resolved_path


@dataclass(slots=True)
class PipelineArtifacts:
    """Artifacts produced by a contract pipeline run."""

    merged_contract_path: Path
    ge_suite_path: Path
    ci_manifest_path: Path


@dataclass(slots=True)
class ContractPipeline:
    """Orchestrate SemaPact import, merge, export, and CI artifact generation.

    Purpose:
    - Provide one non-UI entrypoint for technical schema ingestion and governed
      contract artifact generation.
    - Encapsulate the standard execution order for automation:
      import -> merge -> validate -> policy check -> export artifacts.

    Important boundary:
    - This pipeline works with the canonical lifecycle-governed contract.
    - It is not the user draft workflow. UI draft save/analyze flows belong to
      the service layer and governance adapters.
    """

    runtime_context: RuntimeContext = "auto"
    loader: ContractLoader = field(init=False)
    validator: ContractValidator = field(init=False)
    merge_engine: ContractMergeEngine = field(init=False)
    ge_exporter: GreatExpectationsExporter = field(init=False)

    def __post_init__(self) -> None:
        """Initialize shared collaborators for pipeline execution."""
        self.loader = ContractLoader(runtime_context=self.runtime_context)
        self.validator = ContractValidator()
        self.merge_engine = ContractMergeEngine()
        self.ge_exporter = GreatExpectationsExporter()

    def import_schema(
        self,
        source_type: ImportSourceType,
        source: str,
        *,
        uc_workspace_url: str | None = None,
        uc_token: str | None = None,
        import_args: dict[str, Any] | None = None,
    ) -> OpenDataContractStandard:
        """Import a technical contract from a supported source type."""
        import_args = import_args or {}
        normalized = source_type.strip().lower()

        if normalized in {"uc", "unity"}:
            return import_unity_contract(
                table_fqn=source,
                workspace_url=uc_workspace_url,
                token=uc_token,
                **import_args,
            )

        try:
            imported = DataContract.import_from_source(
                format=normalized,
                source=source,
                **import_args,
            )
        except ValueError as exc:
            from semapact.exceptions import ValidationError

            raise ValidationError(f"Unsupported source_type: {source_type}") from exc

        return imported

    def merge_contract_updates(
        self,
        source_contract: OpenDataContractStandard,
        business_contract: OpenDataContractStandard,
        *,
        context: ChangeContext,
        fail_on_conflict: bool = False,
    ) -> MergeResult:
        """Merge a technical source contract into a business contract."""
        return self.merge_engine.merge(
            source_contract,
            business_contract,
            context=context,
            fail_on_conflict=fail_on_conflict,
        )

    def validate_contract(
        self, contract: OpenDataContractStandard
    ) -> ValidationReport:
        """Validate a contract using the standard validator."""
        return self.validator.validate(contract)

    def evaluate_policy(
        self,
        base_contract: OpenDataContractStandard,
        merged_contract: OpenDataContractStandard,
    ) -> PolicyEvaluation:
        """Evaluate lifecycle policy constraints between base and merged contracts."""
        return evaluate_merge_policy(base_contract, merged_contract)

    def prepare_ci_cd_artifacts(
        self,
        merged_contract: OpenDataContractStandard,
        merge_result: MergeResult,
        decision: GovernanceDecision,
        *,
        merged_contract_output_path: str,
        ge_suite_output_path: str,
        ci_manifest_output_path: str,
        ge_schema_name: str = "all",
        ge_suite_name: str | None = None,
        audit_metadata: AuditMetadata | None = None,
    ) -> PipelineArtifacts:
        """Write the merged contract and downstream CI/CD artifacts to disk."""
        if not isinstance(decision, GovernanceDecision):
            raise TypeError(f"prepare_ci_cd_artifacts requires GovernanceDecision, got {type(decision).__name__}")

        # Enforce CI gate before writing any side-effect artifacts
        enforce_governance_gate(
            decision,
            GovernanceOperation.CI,
            manifest_path=ci_manifest_output_path,
        )

        merged_contract_path = dump_yaml(
            contract_to_dict(merged_contract), merged_contract_output_path
        )
        ge_suite_path = self.ge_exporter.export_to_path(
            merged_contract,
            ge_suite_output_path,
            schema_name=ge_schema_name,
            suite_name=ge_suite_name,
        )

        ci_manifest_path = Path(ci_manifest_output_path).expanduser().resolve()
        ci_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = _build_manifest_payload(
            decision,
            merge_conflicts=merge_result.conflicts,
            artifacts={
                "mergedContract": str(merged_contract_path),
                "greatExpectationsSuite": str(ge_suite_path),
            },
            audit_metadata=audit_metadata,
        )
        ci_manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )

        return PipelineArtifacts(
            merged_contract_path=merged_contract_path,
            ge_suite_path=ge_suite_path,
            ci_manifest_path=ci_manifest_path,
        )

    def run(
        self,
        *,
        source_type: ImportSourceType,
        source: str,
        business_contract_path: str,
        merged_contract_output_path: str,
        ge_suite_output_path: str,
        ci_manifest_output_path: str,
        change_context: ChangeContext,
        uc_workspace_url: str | None = None,
        uc_token: str | None = None,
        ge_schema_name: str = "all",
        ge_suite_name: str | None = None,
        audit_metadata: AuditMetadata | None = None,
    ) -> PipelineArtifacts:
        """Execute the full SemaPact automation pipeline end to end."""
        imported_contract = self.import_schema(
            source_type,
            source,
            uc_workspace_url=uc_workspace_url,
            uc_token=uc_token,
        )
        business_contract = self.loader.load(business_contract_path)

        # Merge updates with fail_on_conflict=False so governance decision evaluates all conflicts and changes
        merge_result = self.merge_contract_updates(
            imported_contract,
            business_contract,
            context=change_context,
            fail_on_conflict=False,
        )
        merged_contract = merge_result.contract
        conflicts = merge_result.conflicts

        if merged_contract is None:
            raise ValueError("Merge did not produce a contract")

        # Single-pass governance decision evaluation using the same explicit context as merge.
        decision = evaluate_governance_decision(
            business_contract,
            merged_contract,
            context=change_context,
            merge_conflicts=conflicts,
        )

        # Write decision-only manifest FIRST as audit output before gate enforcement
        manifest_path = write_decision_manifest(
            decision,
            ci_manifest_output_path,
            audit_metadata=audit_metadata,
            merge_conflicts=merge_result.conflicts,
        )

        # Centralized gate enforcement for CI operation (raises GovernanceBlockedError or GovernanceReviewRequiredError)
        enforce_governance_gate(decision, GovernanceOperation.CI, manifest_path=manifest_path)

        # ALLOW or REVIEW: Write artifacts and manifest
        artifacts = self.prepare_ci_cd_artifacts(
            merge_result.contract,
            merge_result,
            decision,
            merged_contract_output_path=merged_contract_output_path,
            ge_suite_output_path=ge_suite_output_path,
            ci_manifest_output_path=ci_manifest_output_path,
            ge_schema_name=ge_schema_name,
            ge_suite_name=ge_suite_name,
            audit_metadata=audit_metadata,
        )

        return artifacts

    def _resolve_lifecycle(self, contract: OpenDataContractStandard) -> str:
        """Resolve lifecycle status using centralized lifecycle resolution."""
        from semapact.lifecycle.status import resolve_contract_lifecycle

        return str(resolve_contract_lifecycle(contract))