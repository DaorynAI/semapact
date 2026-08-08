from __future__ import annotations


import pytest

import semapact.core.loader as contract_loader
import semapact.utils.yaml_utils as yaml_utils
from semapact.utils.schema_utils import (
    contract_to_dict,
    contract_to_model,
    ensure_schema_key,
)
from semapact.utils.yaml_utils import (
    dump_yaml,
    dump_yaml_text,
    list_yaml_documents,
    load_yaml,
    parse_yaml_text,
)


def test_yaml_utils_can_load_and_dump_sample_contract(sample_odcs_dict, tmp_path):
    output_path = dump_yaml(sample_odcs_dict, tmp_path / "roundtrip.yaml")
    reloaded = load_yaml(output_path)

    assert output_path.exists()
    assert reloaded["id"] == sample_odcs_dict["id"]
    assert len(reloaded["schema"]) == len(sample_odcs_dict["schema"])


def test_yaml_utils_parse_and_dump_yaml_text_use_odcs_contract_shape(sample_odcs_dict):
    rendered = dump_yaml_text(sample_odcs_dict)
    reparsed = parse_yaml_text(rendered)

    assert reparsed["id"] == sample_odcs_dict["id"]
    assert len(reparsed["schema"]) == len(sample_odcs_dict["schema"])


def test_yaml_utils_rejects_non_mapping_yaml(tmp_path):
    invalid_yaml = tmp_path / "invalid.yaml"
    invalid_yaml.write_text("- not-a-mapping", encoding="utf-8")

    with pytest.raises(Exception, match="mapping object"):
        load_yaml(invalid_yaml)


def test_yaml_utils_list_yaml_documents_supports_recursive_local_root(tmp_path):
    contracts_root = tmp_path / "contracts"
    dump_yaml({"id": "a"}, contracts_root / "domain-a" / "a.yaml")
    dump_yaml({"id": "b"}, contracts_root / "domain-b" / "nested" / "b.yml")
    (contracts_root / "ignore.txt").write_text("x", encoding="utf-8")

    discovered = list_yaml_documents(contracts_root)

    assert discovered == [
        str((contracts_root / "domain-a" / "a.yaml").resolve()),
        str((contracts_root / "domain-b" / "nested" / "b.yml").resolve()),
    ]


def test_yaml_utils_list_yaml_documents_supports_adls2_directory(monkeypatch):
    monkeypatch.setattr(
        contract_loader,
        "list_adls2_paths",
        lambda root: [
            "abfss://contracts@acct.dfs.core.windows.net/contracts/a.yaml",
            "abfss://contracts@acct.dfs.core.windows.net/contracts/sub/b.yml",
        ],
    )

    discovered = list_yaml_documents(
        "abfss://contracts@acct.dfs.core.windows.net/contracts"
    )

    assert discovered == [
        "abfss://contracts@acct.dfs.core.windows.net/contracts/a.yaml",
        "abfss://contracts@acct.dfs.core.windows.net/contracts/sub/b.yml",
    ]


def test_yaml_utils_load_yaml_metadata_supports_adls2_file(monkeypatch):
    class FakeDownloader:
        @staticmethod
        def readall() -> bytes:
            return b"id: orders\ndataProduct: seller_payments\nversion: 1.0.0\nstatus: active\ntenant: tenant-a\n"

    class FakeFileClient:
        @staticmethod
        def download_file() -> FakeDownloader:
            return FakeDownloader()

    monkeypatch.setattr(
        contract_loader, "_create_adls2_file_client", lambda path: FakeFileClient()
    )

    metadata = yaml_utils.load_yaml_metadata(
        "abfss://contracts@acct.dfs.core.windows.net/orders.yaml",
        keys=["id", "dataProduct", "version", "status", "tenant"],
    )

    assert metadata == {
        "id": "orders",
        "dataProduct": "seller_payments",
        "version": "1.0.0",
        "status": "active",
        "tenant": "tenant-a",
    }


def test_yaml_utils_load_yaml_metadata_handles_quoted_colons_multiline_and_comments(
    tmp_path,
):
    contract_file = tmp_path / "metadata.yaml"
    contract_file.write_text(
        """
id: "orders:au"
dataProduct: >-
  seller:payments
version: '1.0.0'
status: active # inline comment should not leak into value
tenant: "tenant:a"
description:
  purpose: ignored nested mapping
""".strip(),
        encoding="utf-8",
    )

    metadata = yaml_utils.load_yaml_metadata(
        contract_file,
        keys=["id", "dataProduct", "version", "status", "tenant"],
    )

    assert metadata == {
        "id": "orders:au",
        "dataProduct": "seller:payments",
        "version": "1.0.0",
        "status": "active",
        "tenant": "tenant:a",
    }


def test_schema_utils_convert_sample_contract_between_input_types(
    sample_odcs_dict, sample_odcs_path, sample_odcs_model
):
    model_from_dict = contract_to_model(sample_odcs_dict)
    model_from_path = contract_to_model(sample_odcs_path)
    model_from_string_path = contract_to_model(str(sample_odcs_path))
    dict_from_model = contract_to_dict(sample_odcs_model)

    assert model_from_dict.id == sample_odcs_dict["id"]
    assert model_from_path.id == sample_odcs_dict["id"]
    assert model_from_string_path.id == sample_odcs_dict["id"]
    assert dict_from_model["id"] == sample_odcs_dict["id"]


def test_schema_utils_rejects_unsupported_input_type():
    with pytest.raises(TypeError, match="Unsupported contract input type"):
        contract_to_model(12345)  # type: ignore[arg-type]


def test_schema_utils_ensure_schema_key_handles_schema_alias_and_missing_key():
    assert ensure_schema_key({"schema": []}) == "schema"
    assert ensure_schema_key({"schema_": []}) == "schema_"

    payload = {}
    key = ensure_schema_key(payload)
    assert key == "schema"
    assert payload["schema"] == []
