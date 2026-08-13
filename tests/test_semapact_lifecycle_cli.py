import pytest
from pathlib import Path
from collections import namedtuple

from semapact.core.lifecycle_cli import apply_lifecycle
from semapact.exceptions import GovernanceReviewRequiredError
from semapact.utils.yaml_utils import load_yaml

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
status: active
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
    with pytest.raises(GovernanceReviewRequiredError):
        apply_lifecycle(args, is_promote=True)


def test_deprecate_schema(sample_contract_path):
    args = Args(
        contract=sample_contract_path,
        schema="my_schema",
        property=None,
        output=None,
        runtime_context=None,
    )
    with pytest.raises(GovernanceReviewRequiredError):
        apply_lifecycle(args, is_promote=False)


def test_promote_property(sample_contract_path):
    args = Args(
        contract=sample_contract_path,
        schema="my_schema",
        property="my_prop",
        output=None,
        runtime_context=None,
    )
    with pytest.raises(GovernanceReviewRequiredError):
        apply_lifecycle(args, is_promote=True)


def test_deprecate_property(sample_contract_path):
    args = Args(
        contract=sample_contract_path,
        schema="my_schema",
        property="my_prop",
        output=None,
        runtime_context=None,
    )
    with pytest.raises(GovernanceReviewRequiredError):
        apply_lifecycle(args, is_promote=False)
