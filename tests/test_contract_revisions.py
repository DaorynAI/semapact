from __future__ import annotations

from pathlib import Path

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.history import (
    ContractRevisionHistoryRepository,
    ContractRevisionSourceHistoryRepository,
    HistoryCorruptionError,
)
from semapact.platforms.git import GitWorkingTreeHistoryRepository
from semapact.revision import (
    ContractRevision,
    build_contract_revision,
    compute_contract_content_fingerprint,
    compute_contract_revision_id,
    compute_contract_revision_source_id,
    link_contract_revision_source,
    validate_contract_revision_identity,
)
from semapact.utils.deterministic import canonical_compact_json


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


def test_revision_identity_protocol_has_golden_values() -> None:
    canonical = '{"id":"x"}'
    fingerprint = compute_contract_content_fingerprint(canonical)

    assert fingerprint == "5e2b92cc57ce618dfbb54844a31775e4b95c6fb552ee6bf5a068133c12d2ad90"
    revision_id = compute_contract_revision_id(fingerprint)
    assert revision_id == "88b0f51f-8208-528e-92c7-75d2b357a751"
    assert (
        compute_contract_revision_source_id(
            revision_id=revision_id,
            source_reference="git:commit:abc123",
        )
        == "8598e362-fef7-58e9-87c1-a582d511728d"
    )


def test_revision_reuses_odcs_contract_model_without_duplicate_contract_fields() -> None:
    contract = _contract()
    revision = build_contract_revision(contract)

    assert isinstance(revision.contract, OpenDataContractStandard)
    assert revision.contract == contract
    assert revision.contract is not contract
    assert set(ContractRevision.model_fields) == {
        "revision_id",
        "content_fingerprint",
        "contract",
    }


def test_identical_content_has_stable_revision_identity() -> None:
    first = build_contract_revision(_contract())
    second = build_contract_revision(_contract())

    assert first == second
    assert first.revision_id == second.revision_id
    assert first.content_fingerprint == second.content_fingerprint
    assert first.revision_id != str(first.contract.version or "")


def test_governed_content_change_changes_revision_identity() -> None:
    before = build_contract_revision(_contract())
    after = build_contract_revision(_contract(physical_type="string"))

    assert before.content_fingerprint != after.content_fingerprint
    assert before.revision_id != after.revision_id


def test_semantic_version_is_part_of_exact_contract_content_not_revision_alias() -> None:
    first = build_contract_revision(_contract(version="1.0.0"))
    second = build_contract_revision(_contract(version="1.0.1"))

    assert str(first.contract.version) == "1.0.0"
    assert str(second.contract.version) == "1.0.1"
    assert first.revision_id != second.revision_id
    assert first.revision_id not in {
        str(first.contract.version),
        str(second.contract.version),
    }


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


def test_revision_model_structure_is_separate_from_derived_identity_validation() -> None:
    revision = build_contract_revision(_contract())
    payload = revision.model_dump(mode="json", by_alias=True)
    payload["content_fingerprint"] = "0" * 64

    structurally_valid = ContractRevision.model_validate(payload)

    with pytest.raises(ValueError, match="content_fingerprint"):
        validate_contract_revision_identity(structurally_valid)


def test_revision_integrity_detects_changed_nested_contract_content() -> None:
    revision = build_contract_revision(_contract())
    changed_contract = revision.contract.model_copy(deep=True)
    changed_contract.name = "changed-orders"
    tampered = revision.model_copy(update={"contract": changed_contract})

    with pytest.raises(ValueError, match="content_fingerprint"):
        validate_contract_revision_identity(tampered)


def test_source_link_builder_rejects_invalid_revision_identity() -> None:
    revision = build_contract_revision(_contract())
    tampered = revision.model_copy(update={"content_fingerprint": "0" * 64})

    with pytest.raises(ValueError, match="content_fingerprint"):
        link_contract_revision_source(
            tampered,
            source_reference="git:commit:abc123",
        )


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
    source_ids = [
        item.source_link_id
        for item in sources.list_revision_sources(revision.revision_id)
    ]
    assert source_ids == sorted([source_a.source_link_id, source_b.source_link_id])


def test_semantically_corrupted_persisted_revision_fails_closed(tmp_path: Path) -> None:
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
    tampered = revision.model_copy(update={"content_fingerprint": "0" * 64})
    path.write_text(
        canonical_compact_json(
            tampered.model_dump(mode="json", by_alias=True)
        ),
        encoding="utf-8",
    )

    with pytest.raises(HistoryCorruptionError, match="is invalid"):
        repository.get_revision(revision.revision_id)
