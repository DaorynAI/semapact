import pytest
from pathlib import Path
from semapact.core.lifecycle_cli import apply_lifecycle
from semapact.utils.yaml_utils import load_yaml
from collections import namedtuple

Args = namedtuple(
    "Args", ["contract", "schema", "property", "output", "runtime_context"]
)


@pytest.fixture
def sample_contract_path(tmp_path: Path) -> str:
    contract_yaml = """
kind: DataContract
apiVersion: v3.0.0
id: my-contract
name: my-contract
version: 1.0.0
schema:
  - name: my_schema
    properties:
      - name: my_prop
        type: string
"""
    file_path = tmp_path / "contract.yaml"
    file_path.write_text(contract_yaml)
    return str(file_path)


def test_promote_contract(sample_contract_path):
    args = Args(
        contract=sample_contract_path,
        schema=None,
        property=None,
        output=None,
        runtime_context=None,
    )
    apply_lifecycle(args, is_promote=True)

    data = load_yaml(sample_contract_path)
    assert data["status"] == "active"


def test_deprecate_contract(sample_contract_path):
    args = Args(
        contract=sample_contract_path,
        schema=None,
        property=None,
        output=None,
        runtime_context=None,
    )
    apply_lifecycle(args, is_promote=False)

    data = load_yaml(sample_contract_path)
    assert data["status"] == "deprecated"


def test_promote_schema(sample_contract_path):
    args = Args(
        contract=sample_contract_path,
        schema="my_schema",
        property=None,
        output=None,
        runtime_context=None,
    )
    apply_lifecycle(args, is_promote=True)

    data = load_yaml(sample_contract_path)
    schema = data["schema"][0]
    cp = schema.get("customProperties", [])
    assert any(
        c["property"] == "lifecycleStatus" and c["value"] == "active" for c in cp
    )


def test_deprecate_schema(sample_contract_path):
    args = Args(
        contract=sample_contract_path,
        schema="my_schema",
        property=None,
        output=None,
        runtime_context=None,
    )
    apply_lifecycle(args, is_promote=False)

    data = load_yaml(sample_contract_path)
    schema = data["schema"][0]
    cp = schema.get("customProperties", [])
    assert any(
        c["property"] == "lifecycleStatus" and c["value"] == "deprecated" for c in cp
    )
    assert any(c["property"] == "deprecationDate" for c in cp)
    assert "deprecated" in schema.get("tags", [])


def test_promote_property(sample_contract_path):
    args = Args(
        contract=sample_contract_path,
        schema="my_schema",
        property="my_prop",
        output=None,
        runtime_context=None,
    )
    apply_lifecycle(args, is_promote=True)

    data = load_yaml(sample_contract_path)
    prop = data["schema"][0]["properties"][0]
    cp = prop.get("customProperties", [])
    assert any(
        c["property"] == "lifecycleStatus" and c["value"] == "active" for c in cp
    )


def test_deprecate_property(sample_contract_path):
    args = Args(
        contract=sample_contract_path,
        schema="my_schema",
        property="my_prop",
        output=None,
        runtime_context=None,
    )
    apply_lifecycle(args, is_promote=False)

    data = load_yaml(sample_contract_path)
    prop = data["schema"][0]["properties"][0]
    cp = prop.get("customProperties", [])
    assert any(
        c["property"] == "lifecycleStatus" and c["value"] == "deprecated" for c in cp
    )
    assert any(c["property"] == "deprecationDate" for c in cp)
    assert "deprecated" in prop.get("tags", [])
