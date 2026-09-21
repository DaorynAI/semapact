from __future__ import annotations

import json
from datetime import datetime, timezone

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
    Server,
)

from semapact.deployment import (
    DeploymentAdapter,
    DeploymentPreview,
    NativeOperation,
    NativeOperationKind,
)
from semapact.deployment.models import compute_deployment_preview_id
from semapact.interfaces import cli
from semapact.observation import ObservedPlatformState, with_observed_state_fingerprint
from semapact.reconciliation import ReconciliationResult
from semapact.utils.yaml_utils import dump_yaml


SOURCE_REFERENCE = "https://workspace.example"


class _PreviewAdapter(DeploymentAdapter):
    key = "databricks"

    def validate(self, plan) -> None:
        pass

    def preview(self, plan) -> DeploymentPreview:
        observation = with_observed_state_fingerprint(
            ObservedPlatformState(
                platform="databricks",
                source_identifier=plan.target.source_reference,
                assets=(),
                captured_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
            )
        )
        assert observation.fingerprint is not None
        operations = (
            NativeOperation(
                kind=NativeOperationKind.CREATE,
                governed_asset="orders",
                statement="CREATE orders",
            ),
        )
        return DeploymentPreview(
            deployment_preview_id=compute_deployment_preview_id(
                deployment_plan_id=plan.deployment_plan_id,
                platform="databricks",
                runtime_target=plan.target.runtime_target,
                source_identifier=observation.source_identifier,
                observation_fingerprint=observation.fingerprint,
                operations=operations,
            ),
            deployment_plan_id=plan.deployment_plan_id,
            platform="databricks",
            runtime_target=plan.target.runtime_target,
            source_identifier=observation.source_identifier,
            observation_fingerprint=observation.fingerprint,
            operations=operations,
        )

    def apply(self, plan, preview) -> None:
        raise AssertionError("CI assessment must not mutate runtime")

    def verify(self, plan) -> ReconciliationResult:
        raise AssertionError("CI assessment must not verify runtime")


class _ExecutionAdapter(DeploymentAdapter):
    key = "databricks"

    def __init__(self) -> None:
        self.preview_calls = 0
        self.apply_calls = 0
        self.verify_calls = 0
        self.metadata_calls = 0

    def validate(self, plan) -> None:
        pass

    def preview(self, plan) -> DeploymentPreview:
        self.preview_calls += 1
        observation = with_observed_state_fingerprint(
            ObservedPlatformState(
                platform="databricks",
                source_identifier=plan.target.source_reference,
                assets=(),
                captured_at=datetime(2026, 9, 21, 1, tzinfo=timezone.utc),
            )
        )
        assert observation.fingerprint is not None
        operations = (
            NativeOperation(
                kind=NativeOperationKind.NO_OP,
                governed_asset="orders",
            ),
        )
        return DeploymentPreview(
            deployment_preview_id=compute_deployment_preview_id(
                deployment_plan_id=plan.deployment_plan_id,
                platform="databricks",
                runtime_target=plan.target.runtime_target,
                source_identifier=observation.source_identifier,
                observation_fingerprint=observation.fingerprint,
                operations=operations,
            ),
            deployment_plan_id=plan.deployment_plan_id,
            platform="databricks",
            runtime_target=plan.target.runtime_target,
            source_identifier=observation.source_identifier,
            observation_fingerprint=observation.fingerprint,
            operations=operations,
        )

    def apply(self, plan, preview) -> None:
        self.apply_calls += 1

    def verify(self, plan) -> ReconciliationResult:
        self.verify_calls += 1
        return ReconciliationResult(
            contract_id=plan.contract_id,
            contract_version=plan.contract_version,
            observation_source_identifier=plan.target.source_reference,
            observation_fingerprint="obs-v1:sha256:verified",
        )

    def project_release_metadata(self, plan, metadata) -> None:
        self.metadata_calls += 1


def _server(name: str, schema_name: str) -> Server:
    return Server.model_validate(
        {
            "server": name,
            "type": "databricks",
            "host": SOURCE_REFERENCE,
            "catalog": "main",
            "schema": schema_name,
        }
    )


def _contract(*, include_created_at: bool = False) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="varchar(255)",
            required=True,
        )
    ]
    if include_created_at:
        properties.append(
            SchemaProperty(
                name="created_at",
                logicalType="timestamp",
                physicalType="timestamp",
                required=False,
            )
        )
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name="Orders",
        version="1.2.3",
        status="active",
        servers=[
            _server("development", "development"),
            _server("production", "production"),
        ],
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _run_cli(monkeypatch, capsys, *args: str) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["semapact", *args])
    code = cli.main()
    output = capsys.readouterr().out
    return code, output


def test_data_product_sample_command_chain_executes_end_to_end(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Exercise the same public artifact handoff used by the sample GitHub pipeline."""
    base_path = dump_yaml(_contract(), tmp_path / "base.yaml")
    candidate_path = dump_yaml(
        _contract(include_created_at=True),
        tmp_path / "contract.yaml",
    )
    candidate_bundle = tmp_path / "candidate.deployment.bundle.json"
    release_bundle = tmp_path / "release.bundle.json"
    released_contract = tmp_path / "released.yaml"
    release_artifact = tmp_path / "contract-release.json"
    production_bundle = tmp_path / "production.deployment.bundle.json"

    execution_adapter = _ExecutionAdapter()

    def _adapter_factory(platform: str, **kwargs):
        assert platform == "databricks"
        if kwargs.get("execution_config") is None:
            return _PreviewAdapter()
        return execution_adapter

    monkeypatch.setattr(
        "semapact.platforms.runtime_registry.create_deployment_adapter",
        _adapter_factory,
    )
    monkeypatch.setattr(
        "semapact.core.config.config_manager.get",
        lambda *args, **kwargs: None,
    )

    # Pull-request candidate assessment: read-only and artifact-producing.
    code, _ = _run_cli(
        monkeypatch,
        capsys,
        "deployment",
        "assess",
        "--base",
        str(base_path),
        "--candidate",
        str(candidate_path),
        "--base-revision-ref",
        "git:base",
        "--candidate-revision-ref",
        "git:candidate",
        "--effective-date",
        "2026-09-21",
        "--server",
        "development",
        "--bundle-out",
        str(candidate_bundle),
        "--output",
        "json",
    )
    assert code == 0
    assert candidate_bundle.is_file()

    # Main-branch formal release assessment.
    code, release_output = _run_cli(
        monkeypatch,
        capsys,
        "release",
        "assess",
        "--base",
        str(base_path),
        "--candidate",
        str(candidate_path),
        "--base-revision-ref",
        "git:base",
        "--candidate-revision-ref",
        "git:candidate",
        "--effective-date",
        "2026-09-21",
        "--bundle-out",
        str(release_bundle),
    )
    assert code == 0
    assert json.loads(release_output)["decision"]["decision"] == "REVIEW"
    assert release_bundle.is_file()

    # Protected release environment records approval for the exact bundle.
    code, _ = _run_cli(
        monkeypatch,
        capsys,
        "release",
        "approve",
        "--bundle",
        str(release_bundle),
        "--actor-reference",
        "github-environment:contract-release/run:1",
        "--recorded-at",
        "2026-09-21T04:00:00Z",
        "--repository-root",
        str(tmp_path),
    )
    assert code == 0

    # Finalization materializes ODCS and emits the immutable ContractRelease artifact.
    code, finalize_output = _run_cli(
        monkeypatch,
        capsys,
        "release",
        "finalize",
        "--bundle",
        str(release_bundle),
        "--output-contract",
        str(released_contract),
        "--release-out",
        str(release_artifact),
        "--repository-root",
        str(tmp_path),
    )
    assert code == 0
    finalized = json.loads(finalize_output)
    assert finalized["contractVersion"] == "1.3.0"
    assert release_artifact.is_file()
    assert released_contract.is_file()

    # Production assessment consumes the ContractRelease artifact directly.
    code, _ = _run_cli(
        monkeypatch,
        capsys,
        "deployment",
        "assess",
        "--release",
        str(release_artifact),
        "--server",
        "production",
        "--bundle-out",
        str(production_bundle),
    )
    assert code == 0
    assert production_bundle.is_file()

    # Protected production environment consumes the exact target bundle.
    code, deploy_output = _run_cli(
        monkeypatch,
        capsys,
        "deployment",
        "deploy",
        "--bundle",
        str(production_bundle),
        "--warehouse-id",
        "warehouse-1",
        "--output",
        "json",
    )
    assert code == 0
    deployed = json.loads(deploy_output)
    assert deployed["status"] == "IN_SYNC"
    assert deployed["contract_release_id"] == finalized["contractReleaseId"]
    assert execution_adapter.preview_calls == 1
    assert execution_adapter.apply_calls == 1
    assert execution_adapter.verify_calls == 1
    assert execution_adapter.metadata_calls == 1
