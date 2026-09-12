from __future__ import annotations

from pathlib import Path

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)
from pydantic import ValidationError as PydanticValidationError

from semapact.history import (
    ContractRevision,
    ContractRevisionHistoryRepository,
    ContractRevisionSourceHistoryRepository,
    HistoryCorruptionError,
    build_contract_revision,
    link_contract_revision_source,
)
from semapact.platforms.git import GitWorkingTreeHistoryRepository


def _contract(
    *,
    name: str = "orders",
    version: str = "1.0.0",
    physical_type: str = "varchar(255)",
) -> OpenDataContractStandard:
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders-product",
        name=name,
        version=version,
        status="active",
        schema=[
            SchemaObject(
                name="orders",
                properties=[
                    SchemaProperty(
                        name="id",
                        logicalType="string",
                        physicalType=physical_type,
                        required=True,
                    )
                ],
            )
        ],
    )


def test_identical_content_has_stable_revision_identity() -> None:
    first = build_contract_revision(_contract())
    second = build_contract_revision(_contract())

    assert first == second
    assert first.revision_id == second.revision_id
    assert first.content_fingerprint == second.content_fingerprint
    assert first.revision_id != first.contract_version


def test_governed_content_change_changes_revision_identity() -> None:
    before = build_contract_revision(_contract())
    after = build_contract_revision(_contract(physical_type="string"))

    assert before.content_fingerprint != after.content_fingerprint
    assert before.revision_id != after.revision_id


def test_semantic_version_is_part_of_exact_contract_content_not_revision_alias() -> None:
    first = build_contract_revision(_contract(version="1.0.0"))
    second = build_contract_revision(_contract(version="1.0.1"))

    assert first.contract_version == "1.0.0"
    assert second.contract_version == "1.0.1"
    assert first.revision_id != second.revision_id
    assert first.revision_id not in {first.contract_version, second.contract_version}


def test_source_provenance_does_not_change_revision_identity() -> None:
    revision = build_contract_revision(_contract())

    branch_source = link_contract_revision_source(
        revision,
        source_reference="git:refs/heads/main@abc123",
    )
    tag_source = link_contract_revision_source(
        revision,
        source_reference="git:refs/tags/v1.0.0@def456",
    )

    assert branch_source.revision_id == revision.revision_id
    assert tag_source.revision_id == revision.revision_id
    assert branch_source.source_link_id != tag_source.source_link_id
    assert branch_source.source_reference != tag_source.source_reference


def test_revision_rehydration_rejects_tampered_content_identity() -> None:
    revision = build_contract_revision(_contract())
    payload = revision.model_dump(mode="json")
    payload["content_fingerprint"] = "0" * 64

    with pytest.raises(PydanticValidationError, match="content_fingerprint"):
        ContractRevision.model_validate(payload)


def test_revision_and_sources_round_trip_through_typed_history_ports(
    tmp_path: Path,
) -> None:
    backend = GitWorkingTreeHistoryRepository(tmp_path)
    revisions: ContractRevisionHistoryRepository = backend
    sources: ContractRevisionSourceHistoryRepository = backend
    revision = build_contract_revision(_contract())
    source_a = link_contract_revision_source(
        revision,
        source_reference="git:commit:abc123",
    )
    source_b = link_contract_revision_source(
        revision,
        source_reference="artifact:registry:orders/1.0.0",
    )

    revisions.put_revision(revision)
    revisions.put_revision(revision)
    sources.put_revision_source(source_b)
    sources.put_revision_source(source_a)

    assert revisions.get_revision(revision.revision_id) == revision
    assert revisions.list_revisions("orders-product") == (revision,)
    assert revisions.list_revisions("other-contract") == ()
    assert sources.get_revision_source(source_a.source_link_id) == source_a
    assert [item.source_link_id for item in sources.list_revision_sources(revision.revision_id)] == sorted(
        [source_a.source_link_id, source_b.source_link_id]
    )


def test_corrupted_persisted_revision_fails_closed(tmp_path: Path) -> None:
    repository = GitWorkingTreeHistoryRepository(tmp_path)
    revision = build_contract_revision(_contract())
    repository.put_revision(revision)

    path = (
        tmp_path
        / ".semapact"
        / "history"
        / "contract_revisions"
        / f"{revision.revision_id}.json"
    )
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(HistoryCorruptionError, match="is invalid"):
        repository.get_revision(revision.revision_id)
