from __future__ import annotations

from types import SimpleNamespace

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.interfaces.commands.release_cmd import (
    run_release_approve,
    run_release_assess,
    run_release_finalize,
)
from semapact.platforms.git import GitWorkingTreeHistoryRepository
from semapact.utils.yaml_utils import dump_yaml


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
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def test_release_finalize_materializes_selected_version_and_history(tmp_path) -> None:
    base = tmp_path / "base.yaml"
    candidate = tmp_path / "contract.yaml"
    bundle = tmp_path / "release.bundle.json"
    released = tmp_path / "released.yaml"
    release_artifact = tmp_path / "contract-release.json"
    approval_artifact = tmp_path / "approval.json"
    dump_yaml(_contract(), base)
    dump_yaml(_contract(include_created_at=True), candidate)

    run_release_assess(
        SimpleNamespace(
            base=str(base),
            candidate=str(candidate),
            base_revision_ref="git:base",
            candidate_revision_ref="git:candidate",
            authority_reference=None,
            runtime_context="auto",
            bundle_out=str(bundle),
        )
    )
    run_release_approve(
        SimpleNamespace(
            bundle=str(bundle),
            actor_reference="github-environment:contract-release",
            recorded_at="2026-09-20T10:00:00+10:00",
            comment=None,
            repository_root=str(tmp_path),
            approval_out=str(approval_artifact),
        )
    )
    result = run_release_finalize(
        SimpleNamespace(
            bundle=str(bundle),
            approval=str(approval_artifact),
            output_contract=str(released),
            release_out=str(release_artifact),
            repository_root=str(tmp_path),
        )
    )

    materialized = OpenDataContractStandard.from_file(str(released))
    assert str(materialized.version) == "1.3.0"

    repository = GitWorkingTreeHistoryRepository(tmp_path)
    record = repository.get_contract_release(result["contractReleaseId"])
    assert record.contract_version == "1.3.0"
    assert record.source_revision_ref == "git:candidate"
    assert result["sourceRevisionRef"] == "git:candidate"
    assert record.released_contract_json
    assert approval_artifact.is_file()
    assert release_artifact.is_file()
    assert release_artifact.read_text(encoding="utf-8").strip()
